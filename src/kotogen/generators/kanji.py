"""Kanji card generator.

The facts (readings, level, strokes, words read as a whole) come from
`kanji_table`, never from the model, and check what it hands back. The model
writes the rest: the meaning, the words, the composition, the look-alikes, the
decoys. It is offered the deck's own words first, so that a card links words
already learnt. Which kanji get a card is read off the input or the tables,
except for an entry that names one without writing it (`gaku`, `study`).
"""

from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

from kotogen import console, dictionary, jlpt, kanji_table, memory, prompts
from kotogen.ai_client import AIAuthError, AIClient, AITruncatedError
from kotogen.exporter import append_cards, finish, resolve_output_path
from kotogen.furigana import (
    kata_to_hira,
    process_furigana,
    reading_key,
    strip_furigana,
    surface_key,
    without_readings,
)
from kotogen.i18n import _, agreed, counted, quoted
from kotogen.known import Known, card_field, field_text

# What the exporter writes, hence the fields `kotogen deck install` creates
# (see `notetypes`). Added to only: a field is never renamed or removed.
FIELDS = [
    # The character alone. First: Anki checks duplicates on the first field.
    "Kanji",
    # A keyword, and at most two more senses after a comma: "study, learning".
    "Meaning",
    # The readings the card's words illustrate, separated by 、: on readings in
    # katakana, kun readings in hiragana with a dot before the okurigana (まな.ぶ).
    "Onyomi",
    "Kunyomi",
    # One word per line: `学生[がくせい]|student|ガク` - the word with its
    # furigana, its translation, and the reading of the kanji it illustrates.
    "Words",
    "Strokes",
    # The common readings no word of the card illustrates (生 has twelve), from
    # the tables, never the model. Folded away on the card.
    "OtherReadings",
    # What the kanji is made of, in a few words: "⺍ + 冖 + 子 - a child under a
    # roof". Empty when there is nothing to take apart (山, 木).
    "Composition",
    # The kanji it is mistaken for, and what tells them apart. Empty unless the
    # confusion is real.
    "LookAlikes",
    "Notes",
    # Three kanji close in shape, for the card that will ask for the kanji among
    # four (`Production`, to come): generated already, so the notes hold them.
    "Decoy1",
    "Decoy2",
    "Decoy3",
]

DECK_KEYWORD = "deck"

# A level, a deck or a page holds hundreds of kanji: all at once would be a
# surprise bill. A rerun takes the next ones, those made being in the deck.
DEFAULT_COUNT = 20

# Kanji per call. Fewer than the words of a vocabulary batch: each kanji comes
# with its readings and the words of the deck written with it.
BATCH_SIZE = 8
JOBS = 4

# The words a card shows, and the words of the deck offered to the model for
# one kanji: enough to choose from, not a list to copy out.
MAX_WORDS = 4
DECK_WORDS_OFFERED = 8

# Past these lengths the field is left out: it is meant as a few words, not a
# paragraph read at every review.
LONGEST = {"Composition": 80, "LookAlikes": 80}

# At most this many words read as a whole in `Notes`, the ones met first: the
# field is an aside, not a list to review.
MAX_SPECIAL = 3

# A kanji, a radical or a stroke: `Composition` and `LookAlikes` must name one.
# One that names none ("a single horizontal stroke") only describes the drawing.
_COMPONENT_RE = re.compile("[⺀-⿟㇀-㇯㐀-䶿一-鿿"
                           "豈-﫿𠀀-𱍏]")


# ── What to make cards for ────────────────────────────────────────────────────

@dataclass
class Target:
    """A kanji to write a card for, or an entry that names one without writing it."""

    kanji: str = ""
    # An entry with no kanji (`gaku`, `study`): the model says which one it names.
    entry: str = ""


@dataclass
class DeckWord:
    """A word of the vocabulary deck: as written, with its readings, and its meaning."""

    surface: str
    expression: str
    translation: str


@dataclass
class Vocabulary:
    """The vocabulary deck, read once for the run."""

    by_kanji: dict[str, list[DeckWord]] = field(default_factory=dict)
    surfaces: set[str] = field(default_factory=set)
    # Kanji -> number of words of the deck written with it, in order of first
    # appearance: what the `deck` source ranks by.
    counts: dict[str, int] = field(default_factory=dict)


def read_vocabulary(known: Known, notetype: str) -> Vocabulary:
    """The words of the vocabulary deck, indexed by the kanji they are written with.

    With Anki closed, the copy of the deck has no translations: the model then
    translates the words, as it does its own.
    """
    vocabulary = Vocabulary()
    for card in known.cards(notetype):
        expression = field_text(card_field(card, "Expression")).strip()
        surface = surface_key(expression)
        if not surface:
            continue
        # Without readings: the template prints the word list as it stands, and a
        # translation written in Japanese carries those the export laid on it.
        translation = strip_furigana(field_text(card_field(card, "Translation"))).strip()
        vocabulary.surfaces.add(surface)
        word = DeckWord(surface, expression, translation)
        for char in kanji_table.kanji_in(surface):
            vocabulary.by_kanji.setdefault(char, []).append(word)
            vocabulary.counts[char] = vocabulary.counts.get(char, 0) + 1
    return vocabulary


def carded(known: Known, notetype: str) -> set[str]:
    """The kanji that already have a card in the deck (or in the file of a JSON run)."""
    found = set()
    for card in known.cards(notetype):
        found.update(kanji_table.kanji_in(field_text(card_field(card, "Kanji"))))
    return found


def _rank(char: str) -> int:
    level = kanji_table.level_of(char)
    return jlpt.LEVELS.index(level) if level else len(jlpt.LEVELS)


def by_level(kanji: list[str]) -> list[str]:
    """From the easiest level to the hardest, the order within a level kept.

    A kanji of unknown level comes last, and is never dropped for it.
    """
    return sorted(kanji, key=_rank)


def of_level(level: str, known: set[str]) -> list[str]:
    """The kanji of a level (every level when it is not one) that have no card.

    Only Joyo kanji carry a level, so the kanji of first names never come up.
    """
    levels = [level] if level in jlpt.LEVELS else list(jlpt.LEVELS)
    return [char for lv in levels for char in kanji_table.of_level(lv) if char not in known]


def of_deck(vocabulary: Vocabulary, known: set[str], level: str) -> list[str]:
    """The Joyo kanji of the vocabulary that have no card yet.

    The easiest level first, and within a level the kanji written in the most
    words of the deck: the card that links the most words already learnt.
    """
    kanji = [char for char in vocabulary.counts
             if char not in known and (kanji_table.lookup(char) or _NONE).joyo
             and (level not in jlpt.LEVELS or kanji_table.level_of(char) == level)]
    return sorted(kanji, key=lambda char: (_rank(char), -vocabulary.counts[char]))


def of_text(text: str, known: set[str], level: str) -> list[str]:
    """The Joyo kanji of a text that have no card, the easiest level first."""
    kanji = [char for char in kanji_table.kanji_in(text)
             if char not in known and (kanji_table.lookup(char) or _NONE).joyo
             and (level not in jlpt.LEVELS or kanji_table.level_of(char) == level)]
    return by_level(kanji)


def typed(entry: str, known: set[str]) -> tuple[list[Target], list[str]]:
    """The targets of an entry typed by hand, and the kanji left out as known.

    Every kanji written in it, in a table or not. With none, the entry goes to
    the model, which says which kanji it names.
    """
    kanji = kanji_table.kanji_in(entry)
    if not kanji:
        return [Target(entry=entry.strip())], []
    return ([Target(char) for char in kanji if char not in known],
            [char for char in kanji if char in known])


class _Unknown:
    joyo = False


_NONE = _Unknown()


# ── What the model is asked ───────────────────────────────────────────────────

def _offered(char: str, vocabulary: Vocabulary) -> list[DeckWord]:
    """The words of the deck offered for a kanji: the easiest and shortest first.

    Only words that carry one of the kanji's readings: a word read as a whole,
    listed in the table's appendix (今日) or not (一昨日), illustrates none.
    """
    info = kanji_table.lookup(char)

    def ease(word: DeckWord) -> tuple[int, int]:
        level = jlpt.level_of(word.surface)
        return (jlpt.LEVELS.index(level) if level else len(jlpt.LEVELS), len(word.surface))

    words = sorted((word for word in vocabulary.by_kanji.get(char, [])
                    if not kanji_table.is_special(word.surface)), key=ease)
    if info is None or not info.joyo:
        return words[:DECK_WORDS_OFFERED]

    # Taken in turn from each reading, in table order: eight words of 日 read か
    # (三日, 四日...) would leave nothing of the learner's own for ニチ.
    by_reading: dict[str, list[DeckWord]] = {}
    for word in words:
        carried = next((r.text for r in info.common if carries(word.expression, r)), None)
        if carried is not None:
            by_reading.setdefault(carried, []).append(word)
    offered: list[DeckWord] = []
    while len(offered) < DECK_WORDS_OFFERED and any(by_reading.values()):
        for bucket in by_reading.values():
            if bucket and len(offered) < DECK_WORDS_OFFERED:
                offered.append(bucket.pop(0))
    return offered


def _block(target: Target, vocabulary: Vocabulary) -> str:
    """What the model is told of one kanji: the facts it has to keep to.

    In the language of the cards (`prompts.say`), like everything composed
    around an instruction.
    """
    if not target.kanji:
        return (f"## ?\n{prompts.say('An entry that names a kanji without writing it:')}"
                f" {target.entry}")
    lines = [f"## {target.kanji}"]
    info = kanji_table.lookup(target.kanji)
    if info is not None and info.joyo:
        lines.append(f"{prompts.say('Readings:')} {'、'.join(r.text for r in info.common)}")
    else:
        lines.append(prompts.say("Readings: not in the Joyo table"))
    if info is not None and info.level:
        lines.append(f"{prompts.say('Level:')} {info.level}")
    words = _offered(target.kanji, vocabulary)
    if words:
        listed = prompts.say("; ").join(f"{word.expression} ({word.translation})"
                                        if word.translation else word.expression
                                        for word in words)
        lines.append(f"{prompts.say('Words of the learner deck written with it:')} {listed}")
    special = kanji_table.special_words(target.kanji)
    if special:
        listed = "、".join(f"{spelling} ({reading})" for spelling, reading in special)
        lines.append(f"{prompts.say('Read as a whole, never a word of the card:')} {listed}")
    return "\n".join(lines)


def _request(targets: list[Target], vocabulary: Vocabulary) -> str:
    head = prompts.say("Write the cards of these kanji (a JSON array, one object per "
                       "kanji, in this order):")
    return head + "\n\n" + "\n\n".join(_block(target, vocabulary) for target in targets)


def _ask(client: AIClient, targets: list[Target], vocabulary: Vocabulary) -> list:
    result = client.chat_json(prompts.load("kanji_card"), _request(targets, vocabulary))
    if isinstance(result, dict):
        result = [result]
    if not isinstance(result, list):
        raise ValueError(_("unexpected JSON structure: {kind}").format(kind=type(result).__name__))
    return [item for item in result if isinstance(item, dict)]


def _ask_batch(client: AIClient, targets: list[Target], vocabulary: Vocabulary,
               fatal: Event, lost: list[str] | None = None) -> list:
    """One batch, cut in two when the answer comes back truncated.

    Sent again, the batch would be cut on the token limit again; half of it fits.
    `lost` receives the line of each half dropped, for the caller to say under
    the batch it shows; None says it at once.
    """
    if fatal.is_set():
        raise AIAuthError(_("definitive AI failure reported by another batch"))
    try:
        return _ask(client, targets, vocabulary)
    except AIAuthError:
        fatal.set()
        raise
    except AITruncatedError:
        if len(targets) == 1:
            raise
    half = len(targets) // 2
    answered: list = []
    for part in (targets[:half], targets[half:]):
        try:
            answered.extend(_ask_batch(client, part, vocabulary, fatal, lost))
        except AIAuthError:
            raise
        except Exception as exc:
            # A lost half must not take the other, already paid for, with it.
            line = (counted(len(part), "half dropped ({count} kanji): {reason}",
                            "half dropped ({count} kanji): {reason}")
                    .format(count=len(part), reason=console.reason(exc)))
            if lost is None:
                console.failed(line)
            else:
                lost.append(line)
    return answered


# ── What comes back, checked against the tables ──────────────────────────────

# The sound changes a reading undergoes inside a word: the first kana voiced
# (はな -> ばな, rendaku), the last one doubled into a small っ (がく -> がっ).
_VOICED = dict(zip("かきくけこさしすせそたちつてとはひふへほ",
                   "がぎぐげござじずぜぞだぢづでどばびぶべぼ"))
_HALF_VOICED = dict(zip("はひふへほ", "ぱぴぷぺぽ"))


def _sounds(own: str) -> set[str]:
    """The forms a reading may take inside a word."""
    own = kata_to_hira(own)
    forms = {own}
    if own[-1:] in "くきつち" and len(own) > 1:
        forms.add(own[:-1] + "っ")
    for table in (_VOICED, _HALF_VOICED):
        if own[:1] in table:
            forms |= {table[own[0]] + form[1:] for form in list(forms)}
    return forms


def carries(expression: str, reading: kanji_table.Reading) -> bool:
    """True if the readings of the word hold this reading of the kanji.

    `学校[がっこう]` carries ガク, `花火[はなび]` carries ひ as び. Permissive on
    purpose: the reading has to be in the word, not at the kanji's place.
    """
    heard = reading_key(expression)
    return any(form in heard for form in _sounds(reading.own))


def _reading_of(label: str, info: kanji_table.Kanji) -> kanji_table.Reading | None:
    """The common reading of the table a label names, or None.

    The model is asked to copy the reading as listed; a dot forgotten, or an on
    reading written in hiragana, still names it.
    """
    label = label.strip()
    for reading in info.common:
        if label == reading.text:
            return reading
    plain = kata_to_hira(label.replace(".", ""))
    for reading in info.common:
        if plain == kata_to_hira(reading.kana):
            return reading
    return None


def _heard_reading(label: str, expression: str,
                   info: kanji_table.Kanji) -> kanji_table.Reading | None:
    """The common reading the word carries when the label does not name it.

    Three slips the word corrects: a kun reading without its okurigana (`なが` for
    `なが.い`), the table's first reading with that stem winning; a reading as the
    word sounds it (`ぐち` for `くち`); a label the word does not carry, when
    exactly one reading of the table is in the word.
    """
    heard = [reading for reading in info.common if carries(expression, reading)]
    stem = kata_to_hira(label.strip().split(".", 1)[0])
    for reading in heard:
        if stem and stem in _sounds(reading.own):
            return reading
    return heard[0] if len(heard) == 1 else None


def _own_reading(label: str) -> kanji_table.Reading | None:
    """A reading of a kanji outside the Joyo table, as the model gives it."""
    label = label.strip()
    if not label or not all(ch in "." or "ぁ" <= ch <= "ー" for ch in label):
        return None
    return kanji_table.Reading(label, False, (), "")


@dataclass
class Checked:
    """A card assembled from an answer, or why none was."""

    card: dict | None = None
    reason: str = ""


def _clean(value) -> str:
    return " ".join(str(value or "").replace("|", "/").split())


def _words(char: str, info, answered) -> list[tuple[str, str, kanji_table.Reading]]:
    """The words of an answer that hold up.

    The others are dropped silently: the card stands without them, and a "!"
    under every batch would read as a failure.
    """
    kept: list[tuple[str, str, kanji_table.Reading]] = []
    seen: set[str] = set()
    for item in answered if isinstance(answered, list) else []:
        if not isinstance(item, dict):
            continue
        expression = process_furigana(str(item.get("word", "")).strip())
        surface = surface_key(expression)
        if not surface or surface in seen:
            continue
        seen.add(surface)
        label = str(item.get("reading", ""))
        if char not in surface or kanji_table.is_special(surface):
            continue
        if not info.joyo:
            reading = _own_reading(label)
        elif ((reading := _reading_of(label, info)) is None
              or not carries(expression, reading)):
            reading = _heard_reading(label, expression, info) or reading
        if reading is not None and (not info.joyo or carries(expression, reading)):
            kept.append((expression, _clean(item.get("meaning")), reading))
    return kept[:MAX_WORDS]


def _first_word_first(char, words):
    """The word the Production card will hollow out goes first: one that writes
    the kanji once. The order of the model is kept otherwise."""
    for n, (expression, _meaning, _reading) in enumerate(words):
        if surface_key(expression).count(char) == 1:
            return [words[n], *words[:n], *words[n + 1:]]
    return words


def _decoys(char: str, first: str, answered, vocabulary: Vocabulary) -> list[str]:
    """Up to three kanji close in shape, none of which makes a real word in the
    place of the kanji in the first word - or the card would have two answers."""
    kept: list[str] = []
    for decoy in answered if isinstance(answered, list) else []:
        decoy = str(decoy).strip()
        if (len(decoy) != 1 or decoy == char or decoy in kept
                or not (kanji_table.lookup(decoy) or _NONE).joyo):
            continue
        swapped = first.replace(char, decoy)
        if first and (jlpt.level_of(swapped) or swapped in vocabulary.surfaces):
            continue
        kept.append(decoy)
    return kept[:3]


def _names_another(value: str, char: str) -> bool:
    """True if the text names a component other than the kanji it describes."""
    return any(found != char for found in _COMPONENT_RE.findall(value))


def special_notes(char: str, vocabulary: Vocabulary) -> str:
    """The `Notes` of a kanji: the words read as a whole the learner has met.

    From the appendix of the Joyo table, never from the model, and met under that
    reading (五月 as ごがつ is not さつき). Japanese only, the same in every
    language of the cards. The furigana are never completed: a completion would
    read the word the ordinary way.
    """
    heard = {(word.surface, reading_key(word.expression))
             for word in vocabulary.by_kanji.get(char, [])}
    met = [(spelling, reading) for spelling, reading in kanji_table.special_words(char)
           if (spelling, reading) in heard]

    def ease(word: tuple[str, str]) -> int:
        level = jlpt.level_of(word[0])
        return jlpt.LEVELS.index(level) if level else len(jlpt.LEVELS)

    met = sorted(dict.fromkeys(met), key=ease)[:MAX_SPECIAL]
    return "、".join(f" {spelling}[{reading}]" for spelling, reading in met)


def assemble(item: dict, vocabulary: Vocabulary) -> Checked:
    """The card of one object of the answer, the facts laid by the tables."""
    char = str(item.get("Kanji", "")).strip()
    if len(kanji_table.kanji_in(char)) != 1 or len(char) != 1:
        return Checked(reason=_("no single kanji in the answer"))
    info = kanji_table.lookup(char) or kanji_table.Kanji(char, (), "", None, None)
    meaning = _clean(item.get("Meaning"))
    if not meaning:
        return Checked(reason=_("no meaning"))

    words = _words(char, info, item.get("Words"))
    if not words:
        return Checked(reason=_("no word that holds up"))
    words = _first_word_first(char, words)
    shown = {reading.text for _expression, _meaning, reading in words}

    if info.joyo:
        onyomi = [r.text for r in info.on if r.text in shown and not r.narrow]
        kunyomi = [r.text for r in info.kun if r.text in shown and not r.narrow]
        others = [r.text for r in info.common if r.text not in shown]
    else:
        onyomi = [r.text for _e, _m, r in words if r.is_on]
        kunyomi = [r.text for _e, _m, r in words if not r.is_on]
        others = []

    card = {
        "Kanji": char,
        "Meaning": meaning,
        "Onyomi": "、".join(dict.fromkeys(onyomi)),
        "Kunyomi": "、".join(dict.fromkeys(kunyomi)),
        # A line break, which the export writes as the <br> of the field.
        "Words": "\n".join(f"{expression}|{meaning}|{reading.text}"
                            for expression, meaning, reading in words),
        "Strokes": str(info.strokes or ""),
        "OtherReadings": "、".join(others),
    }
    for name, longest in LONGEST.items():
        value = _clean(item.get(name))
        # Emptied silently, like a word that does not hold up: the field is
        # optional, and a warning would fire on nearly every N5 pictograph.
        if len(value) > longest or (value and not _names_another(value, char)):
            value = ""
        card[name] = value
    card["Notes"] = special_notes(char, vocabulary)

    first = surface_key(words[0][0])
    for n, decoy in enumerate(_decoys(char, first, item.get("Decoys"), vocabulary), 1):
        card[f"Decoy{n}"] = decoy

    # The level from the list, and a flag on the readings no table vouches for:
    # those of a kanji outside the Joyo table come from the model alone.
    tags = [kanji_table.tag_for(char)]
    if not info.joyo:
        tags.append(dictionary.READING_TAG)
    card["Tags"] = " ".join(tag for tag in tags if tag)
    return Checked(card)


# ── Generating ────────────────────────────────────────────────────────────────

# What tells a skipped entry that was already in the deck from the others.
KNOWN_FLAG = "_known"


def generate(client: AIClient, targets: list[Target], args: argparse.Namespace,
             out_path: Path, vocabulary: Vocabulary, known: set[str]) -> tuple[list[dict], list[dict]]:
    """The cards of these targets, in batches, written to the file as they come.

    Hands back (cards, skipped). The batches go off together and are collected
    in order, so the result is the one a sequential run would give.
    """
    size = max(1, getattr(args, "batch_size", None) or BATCH_SIZE)
    batches = [targets[i:i + size] for i in range(0, len(targets), size)]
    jobs = max(1, min(getattr(args, "jobs", None) or JOBS, len(batches) or 1))
    cards: list[dict] = []
    skipped: list[dict] = []
    made: set[str] = set(known)

    # One action per batch, whose rank gives the total; how many run at once is
    # not shown.
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        fatal = Event()
        # A pool thread would say a lost half under whatever batch is on screen.
        lost: list[list[str]] = [[] for _ in batches]
        futures = [pool.submit(_ask_batch, client, batch, vocabulary, fatal, halves)
                   for batch, halves in zip(batches, lost)]
        try:
            for rank, (batch, future) in enumerate(zip(batches, futures), 1):
                # A lone kanji has just been typed: its count would say nothing.
                among = ("" if len(batches) == 1 and len(batch) == 1
                         else counted(len(batch), "{count} kanji", "{count} kanji")
                         .format(count=len(batch)))
                if len(batches) > 1:
                    among = _("batch {rank}/{total}, {among}").format(
                        rank=rank, total=len(batches), among=among)
                console.action(_("Writing the cards"), among=among)
                try:
                    answered = console.while_working(future.result)
                except AIAuthError:
                    raise
                except Exception as exc:
                    console.failed(_("batch {rank}: {reason}, the earlier cards are saved.")
                                   .format(rank=rank, reason=console.reason(exc)))
                    continue
                for line in lost[rank - 1]:
                    console.failed(line)
                valid, lines = _collect(answered, vocabulary, made, skipped)
                if valid:
                    append_cards(out_path, valid, FIELDS, args.deck, args.notetype)
                cards.extend(valid)
                console.done(f"{len(valid)} {console.plural(len(valid), 'card')}")
                for line in lines:
                    console.aside(line)
        finally:
            for future in futures:
                future.cancel()
    return cards, skipped


def generate_into(client: AIClient, chars: list[str], deck: str, notetype: str) -> set[str]:
    """Makes the cards of these kanji and sends them straight into Anki.

    For `maintain`, which moves a lone kanji out of the vocabulary deck. Hands
    back the kanji of `chars` the deck holds afterwards, read again from Anki: a
    card may be turned down, and the caller deletes what it replaces.
    """
    from kotogen.cli import deck_config

    args = argparse.Namespace(output=None, send=True, format=None, deck=deck,
                              notetype=notetype, batch_size=None, jobs=None)
    out_path = resolve_output_path(args, "kanji")
    deck_held = memory.known()
    vocabulary = read_vocabulary(deck_held, deck_config("vocab")[1])
    # The lone kanji are leaving the vocabulary: none is a word for its own card.
    for char in chars:
        vocabulary.by_kanji[char] = [word for word in vocabulary.by_kanji.get(char, [])
                                     if word.surface != char]
    known = carded(deck_held, notetype)
    targets = [Target(char) for char in chars if char not in known]
    if targets:
        cards, _skipped = generate(client, targets, args, out_path, vocabulary, known)
        if cards:
            finish(cards, FIELDS, args, out_path, preview=[])
    return carded(deck_held, notetype) & set(chars)


def _collect(answered: list, vocabulary: Vocabulary, made: set[str],
             skipped: list[dict]) -> tuple[list[dict], list[str]]:
    """The cards of one answer, and the lines saying what was left out of it."""
    valid: list[dict] = []
    lines: list[str] = []
    for item in answered:
        if item.get("_skip"):
            entry = str(item.get("_input", "?"))
            reason = str(item.get("_reason", "?"))
            skipped.append({"_skip": True, "_input": entry, "_reason": reason})
            lines.append(_("{entry} skipped ({reason})").format(entry=entry, reason=reason))
            continue
        checked = assemble(item, vocabulary)
        char = str(item.get("Kanji", "?")).strip() or "?"
        if checked.card is None:
            skipped.append({"_skip": True, "_input": char, "_reason": checked.reason})
            lines.append(_("{entry} skipped ({reason})").format(entry=char, reason=checked.reason))
        elif checked.card["Kanji"] in made:
            # An entry resolved by the model to a kanji the deck or this run
            # already has: the card would be refused at the send.
            skipped.append({"_skip": True, "_input": char, KNOWN_FLAG: True,
                            "_reason": _("already in the deck ({word})").format(word=char)})
            lines.append(_("{entry} skipped ({reason})").format(
                entry=char, reason=_("already has a card")))
            continue
        else:
            made.add(checked.card["Kanji"])
            valid.append(checked.card)
    return valid, lines


def _say_known(known: list[str]) -> None:
    if known:
        console.item(agreed(len(known), "{count} already in the deck, not regenerated:"
                                        " {words}{extra}").format(
            count=len(known), words="、".join(known[:12]),
            extra=f"... (+{len(known) - 12})" if len(known) > 12 else ""))


def _found(todo: list[str], count: int, among: str = "", total: int | None = None) -> list[str]:
    """Say, as one action, what was found with no card, and keep the easiest.

    Its result is the only count of what is left beyond `count`: the end of the
    run does not repeat it.
    """
    console.action(_("Looking for the kanji with no card yet"), among=among)
    if len(todo) <= count:
        found = "{missing}" if total is None else _("{missing} of {total}")
    elif total is None:
        found = counted(count, "{missing}, the easiest one",
                        "{missing}, the {count} easiest")
    else:
        found = counted(count, "{missing} of {total}, the easiest one",
                        "{missing} of {total}, the {count} easiest")
    console.done(found.format(missing=len(todo), total=total, count=count))
    return todo[:count]


# ── Public entry point ────────────────────────────────────────────────────────

def run_kanji(args: argparse.Namespace) -> None:
    from kotogen.cli import deck_config
    from kotogen.generators import nhk, sources, text_source

    client = AIClient(provider=args.provider, model=args.model)
    out_path = resolve_output_path(args, "kanji")
    entry = (args.entry or "").strip()
    level = getattr(args, "level", "auto")
    count = args.count if args.count is not None else DEFAULT_COUNT
    force = getattr(args, "force", False)

    # Read for every source: the words of the cards are looked for there first.
    deck_held = memory.known()
    vocabulary = read_vocabulary(deck_held, deck_config("vocab")[1])
    known = set() if force else carded(deck_held, args.notetype)

    if entry.lower() == DECK_KEYWORD and not args.file:
        if not vocabulary.counts:
            sys.exit(_("{source} source: the vocabulary deck is empty, or unreadable "
                       "(Anki closed with no copy of it).").format(source=quoted(DECK_KEYWORD)))
        console.title(_("Kanji of your vocabulary"))
        targets = [Target(char) for char in _found(of_deck(vocabulary, known, level), count,
                                                   total=len(vocabulary.counts))]

    elif jlpt.is_keyword(entry) and not args.file:
        # Without the deck, the whole level would be made.
        if not force and not deck_held.reachable(args.notetype):
            sys.exit(_("{source} source: Anki has to be open (AnkiConnect) to know which "
                       "kanji already have a card - otherwise it is the whole level that "
                       "would be made.").format(source=quoted(jlpt.KEYWORD)))
        label = level if level in jlpt.LEVELS else _("every level")
        console.title(_("JLPT kanji missing from {deck}").format(
            deck=quoted(deck_held.name(args.deck))))
        targets = [Target(char) for char in _found(of_level(level, known), count, among=label)]

    elif args.file or sources.is_text(entry):
        if sources.is_pdf(str(args.file or entry)):
            sys.exit(_("A PDF is not read by the kanji cards: give its text, a page or "
                       "the kanji themselves."))
        try:
            if args.file:
                path = Path(args.file)
                # Decoded as every text source is: a Japanese lesson is often
                # Shift-JIS or EUC-JP rather than UTF-8.
                title, text = path.name, text_source.decode(path.read_bytes())
            else:
                # NHK Easy writes its article in the browser: over plain HTTP the
                # page holds the site's consent screen, whose kanji are not the article's.
                fetch = nhk.fetch_article_text if nhk.is_nhk_url(entry) else text_source.fetch
                title, lines = fetch(entry)
                text = "\n".join(lines)
        except (OSError, RuntimeError) as exc:
            sys.exit(console.reason(exc, console.ALONE))
        console.title(without_readings(title) or entry)
        targets = [Target(char) for char in _found(of_text(text, known, level), count)]
        _say_known([char for char in kanji_table.kanji_in(text) if char in known])

    elif sources.is_pdf(entry):
        sys.exit(_("A PDF is not read by the kanji cards: give its text, a page or "
                   "the kanji themselves."))

    else:
        console.title(entry)
        targets, already = typed(entry, known)
        _say_known(already)

    if not targets:
        console.item(_("Nothing to make: every kanji asked for already has a card "
                       "(--force to make them again)."))
        return

    cards, skipped = generate(client, targets, args, out_path, vocabulary, known)
    if not cards:
        sys.exit(_("No card generated."))

    extras = []
    if skipped:
        extras.append("   " + counted(len(skipped),
                                      "{count} entry skipped",
                                      "{count} entries skipped").format(count=len(skipped)))
    unvouched = sum(1 for c in cards if dictionary.READING_TAG in c.get("Tags", ""))
    if unvouched:
        extras.append("   " + agreed(unvouched, "{count} kanji outside the Joyo table: "
                                             "readings given by the model, tagged {tag}").format(
            count=unvouched, tag=quoted(dictionary.READING_TAG)))

    finish(cards, FIELDS, args, out_path, extras=extras, preview=[
        console.clean(f"  {i:3}. {card['Kanji']} - {card['Meaning']}")
        for i, card in enumerate(cards, 1)
    ])
