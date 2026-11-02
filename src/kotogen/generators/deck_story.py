"""Reading texts written on the deck: the words it is learning, at its level.

The targets are its leeches, its young cards and its grammar points. A source
rather than a generator: `DeckStory.fetch()` hands back `(title, lines)` like a
web page, and the rest is the reading of any text. Two calls per text: it is
written (`reading_compose`) and measured (`coverage`) before the questions, so
that a rewrite never pays for the translation and questions of a discarded text.
"""

from __future__ import annotations

import collections
import random
from dataclasses import dataclass
from datetime import date

from kotogen import console, coverage, jlpt, prompts, proofreading, seen
from kotogen.ai_client import AIAuthError
from kotogen.furigana import strip_furigana, surface_key
from kotogen.i18n import _, counted
from kotogen.known import Known, Words, card_field, field_text

# The keyword of the command line: `kotogen reading deck`.
KEYWORD = "deck"

SHAPES = ("story", "exam")
LENGTHS = ("short", "medium", "long")

# Characters per level and length, after the 読解 texts of the official guide
# (新しい「日本語能力試験」ガイドブック). No 長文 at N5 and N4: `long` falls back on
# the 中文 there. The guide's ranges (短文 at N4 and N3) are taken at their middle.
CHARACTERS = {
    "N5": {"short": 80, "medium": 250},
    "N4": {"short": 150, "medium": 450},
    "N3": {"short": 175, "medium": 350, "long": 550},
    "N2": {"short": 200, "medium": 500, "long": 900},
    "N1": {"short": 200, "medium": 500, "long": 1000},
}

# The exam's name for each length, shown as is in every language: the learner
# preparing it knows these words.
EXAM_NAMES = {"short": "短文", "medium": "中文", "long": "長文"}

# Below this share of known words, the text is rewritten once.
COVERAGE_MIN = 0.95

# What `proofreading` files a text that stayed under it: harder than asked, which
# is worth finding again in Anki.
COVERAGE_TAG = f"{proofreading.TAG_PREFIX}Coverage"

# Why such a card is to proofread. Held in English and translated where it is
# displayed, like `proofreading.UNALIGNED_TRANSLATION`.
TOO_HARD = "too many unknown words"

# One target word per this many characters, within bounds: too many targets
# turn a short text into a word list.
CHARACTERS_PER_TARGET = 60
TARGETS_MIN, TARGETS_MAX = 3, 8

# The history key of the words used in a text, and when: the next text takes the
# longest waiting first. Under `seen`, so the settings screen forgets it too.
HISTORY_SOURCE = "deck"

# What the `Source` field of such a card opens with. Never translated: `recognise`
# finds the provenance by it, whatever language the rest of the field is in.
NAME = "Kotogen"


def characters(level: str, length: str) -> int:
    """How long the body of the text should be, title left out."""
    lengths = CHARACTERS.get(level, CHARACTERS["N4"])
    return lengths.get(length) or lengths["medium"]


def exam_name(level: str, length: str) -> str:
    """The name the exam gives this length at this level: `long` is 中文 at N4."""
    return EXAM_NAMES["medium" if length not in CHARACTERS.get(level, {}) else length]


# -- What the deck is learning ------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    """A word or a rule of the deck, with what decides its turn."""

    name: str
    level: str
    # 0 for a leech, 1 for a young card, 2 for the rest of the deck.
    group: int


def _notetype(command: str) -> str:
    from kotogen.cli import deck_config  # late: cli imports the generators

    return deck_config(command)[1]


def _level_tag(tags) -> str:
    for tag in tags or []:
        if tag.startswith("Level::") and tag[7:] in jlpt.LEVELS:
            return tag[7:]
    return ""


def _group(card: dict, young: set | None) -> int:
    """0 for a leech, 1 for a card still being learnt, 2 for the rest.

    `young` is None when the deck could not say (Anki closed, a file), which is
    not "none".
    """
    if "leech" in (tag.lower() for tag in card.get("tags") or []):
        return 0
    if young is not None and card.get("id") in young:
        return 1
    return 2


def _words(known: Known, young_known: list[bool]) -> list[Candidate]:
    notetype = _notetype("vocab")
    young = known.learning(notetype)
    young_known.append(young is not None)
    found: dict[str, Candidate] = {}
    for card in known.cards(notetype):
        word = surface_key(field_text(card_field(card, "Expression")))
        if not word or word in found:
            continue
        found[word] = Candidate(word, _level_tag(card.get("tags"))
                                or jlpt.level_of(word) or "", _group(card, young))
    return list(found.values())


def _rules(known: Known) -> list[Candidate]:
    from kotogen.generators.grammar import _RULE_TAG_RE

    notetype = _notetype("grammar")
    young = known.learning(notetype)
    found: dict[str, Candidate] = {}
    for card in known.cards(notetype):
        tags = card.get("tags") or []
        rule = strip_furigana(field_text(card_field(card, "Rule"))).strip()
        level = ""
        for tag in tags:
            named = _RULE_TAG_RE.match(tag)
            if named:
                rule = rule or named.group(1)
                level = tag.split("::")[1] if tag.count("::") >= 2 else ""
        if rule and rule not in found:
            found[rule] = Candidate(rule, level or _level_tag(tags), _group(card, young))
    return list(found.values())


def _in_turn(candidates: list[Candidate], used: dict[str, str]) -> list[Candidate]:
    """Leeches first, then young cards, then the rest; the longest waiting first.

    Shuffled before the stable sort, so that words never used in a text come out
    in a different order every run.
    """
    shuffled = list(candidates)
    random.shuffle(shuffled)
    return sorted(shuffled, key=lambda c: (c.group, used.get(c.name, "")))


@dataclass(frozen=True)
class Targets:
    """What one text is written around."""

    words: tuple[str, ...]
    rules: tuple[str, ...]
    level: str


def plan(count: int, level: str, length: str, known: Known) -> tuple[list[Targets], bool]:
    """The targets of `count` texts, and whether the deck said what it is learning.

    No two texts of a run share a target. A JLPT `level` leaves the words above
    it for later; "auto" gives each text the level most of its targets carry and
    holds no word back, or the few above the rest would wait at every run.
    Raises when there is no word to write on, at all or at the level asked for.
    """
    intervals: list[bool] = []
    words = _words(known, intervals)
    if not words:
        raise RuntimeError(_("The deck holds no vocabulary card to write a text on."))
    rules = _rules(known)
    used = seen.load("reading", HISTORY_SOURCE)
    words, rules = _in_turn(words, used), _in_turn(rules, used)

    asked = level in jlpt.LEVELS
    planned: list[Targets] = []
    for _n in range(count):
        text_level = level if asked else _most_common(words[:TARGETS_MAX])
        usable = [w for w in words if _fits(w, text_level)] if asked else words
        if not usable:
            break
        wanted = min(TARGETS_MAX, max(TARGETS_MIN,
                     characters(text_level, length) // CHARACTERS_PER_TARGET))
        chosen = usable[:wanted]
        words = [w for w in words if w not in chosen]
        # A rule above the level of the text would ask for a construction the
        # rest of it is not allowed to use.
        taken = [r for r in rules if _fits(r, text_level)][:1 if length == "short" else 2]
        rules = [r for r in rules if r not in taken]
        planned.append(Targets(tuple(c.name for c in chosen),
                               tuple(r.name for r in taken), text_level))
    if not planned:
        raise RuntimeError(_("The deck holds no vocabulary card at {level} or below to "
                             "write a text on.").format(level=level))
    return planned, bool(intervals and intervals[0])


def _fits(candidate: Candidate, level: str) -> bool:
    """Whether a target may go into a text at `level`: at it or below it, or
    with no JLPT level to hold it back."""
    return (candidate.level not in jlpt.LEVELS
            or jlpt.LEVELS.index(candidate.level) <= jlpt.LEVELS.index(level))


def _most_common(candidates: list[Candidate]) -> str:
    levels = collections.Counter(c.level for c in candidates if c.level in jlpt.LEVELS)
    return levels.most_common(1)[0][0] if levels else "N4"


def knows(index: Words, level: str):
    """What the learner of a text at `level` is taken to know.

    The deck, and the JLPT words of the levels below. Not those of the level
    itself: they are where the new words of a text may come from.
    """
    below = set(jlpt.LEVELS[:jlpt.LEVELS.index(level)]) if level in jlpt.LEVELS else set()

    def known(word: str) -> bool:
        return index.has(word) or jlpt.level_of(word) in below

    return known


# -- Writing the text ---------------------------------------------------------

def _request(targets: Targets, shape: str, length: str,
             previous: tuple[str, list[str], coverage.Coverage] | None) -> str:
    """The user message of `reading_compose`.

    Plain English, as beside every structure instruction: the answer is Japanese
    whatever the language of the cards, so nothing goes through `prompts.say`.
    """
    parts = [
        f"Level: {targets.level}.",
        f"Shape: {shape}.",
        f"Length: about {characters(targets.level, length)} characters of "
        f"Japanese ({exam_name(targets.level, length)}), title left out.",
        f"Target words: {'、'.join(targets.words)}.",
    ]
    if targets.rules:
        parts.append(f"Grammar points: {'、'.join(targets.rules)}.")
    if previous:
        title, lines, measured = previous
        missing = [w for w in targets.words if not measured.uses(w)]
        parts.append("\nRewrite this text:\n" + "\n".join([title, *lines]))
        if measured.unknown:
            parts.append("Words the learner does not know yet, to replace: "
                         f"{'、'.join(measured.unknown)}.")
        if missing:
            parts.append(f"Target words it left out: {'、'.join(missing)}.")
    return "\n".join(parts)


def _written(client, targets: Targets, shape: str, length: str,
             previous=None) -> tuple[str, list[str]]:
    result = client.chat_json(prompts.load("reading_compose"),
                              _request(targets, shape, length, previous))
    if not isinstance(result, dict):
        raise ValueError(_("unexpected JSON structure: {kind}").format(kind=type(result).__name__))
    title = str(result.get("title", "")).strip()
    lines = [str(line).strip() for line in result.get("lines") or [] if str(line).strip()]
    if not lines:
        raise ValueError(_("the model handed back no text"))
    return title, lines


class DeckStory:
    """One text written on the deck, read like any other text source.

    Duck-typed on `sources.TextSource` rather than derived from it: `sources`
    imports the generators late, and this module is one of them.
    """

    kind = "deck"
    loading = "Writing the text"
    tracking_key = ""

    def __init__(self, client, targets: Targets, shape: str, length: str,
                 index: Words) -> None:
        self.client = client
        self.targets = targets
        self.shape = shape
        self.length = length
        self.index = index
        self.origin = self.label
        self.measured: coverage.Coverage | None = None
        self.rewritten = False
        # The reason the rewrite failed, if it did.
        self.unrewritten = ""

    @property
    def level(self) -> str:
        return self.targets.level

    @property
    def source_name(self) -> str:
        """The block these texts open under: what they are, and at which size."""
        return (f"{_('Texts written on the deck')} ({self.level}, "
                f"{_(self.shape, 'shape')}, {exam_name(self.level, self.length)})")

    @property
    def label(self) -> str:
        """The target words: they are what tells one text of the run from the next."""
        return "、".join(self.targets.words)

    @property
    def name(self) -> str:
        """What opens the IDs of its cards: the command line would eat the forty
        characters of `reading.READABLE_MAX` in options."""
        return f"{KEYWORD}_{self.level}"

    @property
    def provenance(self) -> str:
        """Where the matter of this text comes from: the deck itself, at that size.

        The level and shape with it, a 短文 and a 長文 not being the same exercise;
        not the command, which would write a different text when run again.
        Composed through `sources.provenance`, so that `known.carries` reads it
        like the others, and in the language of the cards (`source_name` follows
        the screen).
        """
        from kotogen.generators import sources

        written = prompts.say("written on the deck")
        detail = (f"{self.level}, {prompts.say(self.shape)}, "
                  f"{exam_name(self.level, self.length)}")
        return sources.provenance(f"{NAME} - {written}", detail)

    def fetch(self) -> tuple[str, list[str]]:
        known = knows(self.index, self.level)
        title, lines = _written(self.client, self.targets, self.shape, self.length)
        measured = coverage.measure([title, *lines], known)
        if measured is not None and measured.ratio < COVERAGE_MIN:
            try:
                again = _written(self.client, self.targets, self.shape, self.length,
                                 (title, lines, measured))
            except AIAuthError:
                raise
            except Exception as exc:
                # The first text is paid for: it stays, filed as too hard.
                self.unrewritten = console.reason(exc)
            else:
                remeasured = coverage.measure([again[0], *again[1]], known)
                self.rewritten = True
                # The rewrite is kept unless it reads worse.
                if remeasured is not None and remeasured.ratio >= measured.ratio:
                    (title, lines), measured = again, remeasured
        self.measured = measured
        from kotogen.furigana import process_furigana
        return process_furigana(title), [process_furigana(line) for line in lines]

    def summary(self, title: str, lines: list[str]) -> str:
        """What the writing gave back: how much of it the deck already knows.

        Not the title, written from the target words the rank line already shows.
        With no measure the action closes on its label.
        """
        if self.measured is None:
            return ""
        return _("{percent}% known").format(
            percent=f"{self.measured.ratio * 100:.0f}")

    def report(self) -> None:
        """What the measure has to say before the questions: under the loading line."""
        if self.measured is None:
            return
        if self.rewritten and self.measured.ratio >= COVERAGE_MIN:
            console.aside(_("Rewritten once to stay at the level"))
        elif self.too_hard and self.unrewritten:
            console.failed(_("{percent}% known, under {minimum}%, and the rewrite "
                             "failed: {reason}").format(
                percent=f"{self.measured.ratio * 100:.0f}",
                minimum=f"{COVERAGE_MIN * 100:.0f}", reason=self.unrewritten))
        elif self.too_hard:
            console.failed(_("{percent}% known, under {minimum}% even after a "
                             "rewrite").format(
                percent=f"{self.measured.ratio * 100:.0f}",
                minimum=f"{COVERAGE_MIN * 100:.0f}"))
        missing = [w for w in self.targets.words if not self.measured.uses(w)]
        if missing:
            line = counted(len(missing),
                           "{count} target word left out: {words}",
                           "{count} target words left out: {words}")
            console.aside(line.format(count=len(missing), words="、".join(missing)))

    @property
    def too_hard(self) -> bool:
        """True if the text stayed under the coverage asked for, rewrite included."""
        return self.measured is not None and self.measured.ratio < COVERAGE_MIN

    def check(self, cards: list[dict]) -> None:
        """Files the cards of a text that stayed too hard, for proofreading."""
        if self.too_hard:
            proofreading.mark(cards, COVERAGE_TAG, TOO_HARD)

    def mark_done(self, title: str) -> None:
        """The words that really went into the text wait their turn again."""
        today = date.today().isoformat()
        for word in self.targets.words:
            if self.measured is None or self.measured.uses(word):
                seen.mark("reading", HISTORY_SOURCE, word, today)
        for rule in self.targets.rules:
            seen.mark("reading", HISTORY_SOURCE, rule, today)


def stories(client, count: int, level: str, shape: str, length: str,
            known: Known) -> list[DeckStory]:
    """The texts of one run, each with its own targets.

    Says once, before the first text, when the deck could not say which cards
    are being learnt: the targets then come from the whole deck.
    """
    planned, intervals = plan(count, level, length, known)
    if not intervals:
        console.aside(_("Anki closed: targets drawn from the whole deck, not from "
                        "the cards being learnt"))
    index = known.words(_notetype("vocab"))
    return [DeckStory(client, targets, shape, length, index) for targets in planned]


# -- Reading a provenance back ------------------------------------------------

def recognise(trace: str) -> tuple[str, str] | None:
    """A card provenance -> (source key, identifier), or None.

    Recognised by `NAME`, which no language touches, since the rest follows the
    language of the cards. The identifier is always empty: the history is keyed
    by target words, which the card does not keep (a recovery counts it
    `without_id`).
    """
    trace = (trace or "").strip()
    return (HISTORY_SOURCE, "") if trace.startswith(f"{NAME} - ") else None
