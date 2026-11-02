"""What already exists: the cards a run must not make again.

`Known` is the collection a run's cards will join: the Anki deck
(`kotogen.anki.deck`), the JSON Lines file named by `--output` (`JsonlFile`), or
none (`Nothing`); no generator knows which one answers. It answers with cards
shaped as `{"id", "fields", "tags"}`, which `Words` and `Sources` compare with.

Nothing blocks: a collection that cannot be read answers "nothing" and all is
made, since a duplicate can be seen and deleted while a missing card cannot.
"""

from __future__ import annotations

import dataclasses
import html
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from kotogen import settings
from kotogen.furigana import JP_RUN_RE, KANJI_RE, reading_key, strip_furigana, surface_key

# A field edited in Anki's editor comes back wrapped (`<div>回る</div>`,
# `&nbsp;ナプキン`), which would hide the word from every comparison.
_TAG_RE = re.compile(r"<[^>]*>")


def field_text(value: str) -> str:
    """The text of a field as a collection stores it: no tag, no entity."""
    return html.unescape(_TAG_RE.sub("", value or ""))


def card_field(card: dict, name: str) -> str:
    """One field of a card, "" when it has none."""
    return str((card.get("fields") or {}).get(name) or "")


# -- The words already there ---------------------------------------------------

def _reading_guess(word: str) -> str:
    """The reading of a bare word, from the JLPT table, else the dictionary.

    The table first because it was written by hand: MeCab reads 円い as まりい.
    """
    from kotogen import dictionary, jlpt

    return jlpt.reading_of(word) or reading_key(dictionary.best_reading(word))


def _same_word(entry: str, spelling: str) -> bool:
    """True if two kanji spellings that read alike write one word.

    The same kanji in the same order is one word (上る and 上がる); otherwise it
    takes a kanji in common AND one dictionary entry (出かける and 出掛ける), as
    化学 and 科学 share 学 and are two. Without the dictionary, they are two.
    """
    from kotogen import dictionary  # late, like `_reading_guess`

    kanji, written = KANJI_RE.findall(entry), KANJI_RE.findall(spelling)
    if kanji == written:
        return True
    if not set(kanji) & set(written):
        return False
    found = dictionary.lemma(surface_key(entry))
    return bool(found) and found == dictionary.lemma(spelling)


@dataclass(frozen=True)
class Words:
    """Spellings and readings of the expressions a collection already holds."""

    surfaces: frozenset[str] = frozenset()
    readings: frozenset[str] = frozenset()
    # reading -> the spellings of the collection that carry it
    spellings: Mapping[str, frozenset[str]] = dataclasses.field(default_factory=dict)

    def __bool__(self) -> bool:
        """False when nothing is held: an empty collection, or one out of reach."""
        return bool(self.surfaces)

    def has(self, word: str) -> bool:
        """True if this bare Japanese word is already there."""
        if surface_key(word) in self.surfaces:
            return True
        # A kana-only entry has only its reading (たべる finds 食[た]べる).
        if not KANJI_RE.search(word):
            return reading_key(word) in self.readings
        # A kanji spelling the collection writes another way (入口 for 入り口,
        # 中々 for なかなか): the same reading AND the same word, or a kana
        # spelling. The reading alone would merge homophones (橋 and 箸).
        for spelling in self.spellings.get(_reading_guess(word), ()):
            if not KANJI_RE.search(spelling) or _same_word(word, spelling):
                return True
        return False

    def match(self, entry: str) -> str:
        """The known word(s) this entry would produce again, or "".

        Only when ALL its Japanese words are known (行く、来る needs both); an
        entry with no Japanese never matches, comparing it would take an AI call.
        """
        words = JP_RUN_RE.findall(strip_furigana(entry))
        if not words or not all(self.has(w) for w in words):
            return ""
        return "、".join(words)


NO_WORDS = Words()


def words_of(expressions: Iterable[str]) -> Words:
    """The words of these expressions, written as a field holds them."""
    surfaces: set[str] = set()
    spellings: dict[str, set[str]] = {}
    for value in expressions:
        text = field_text(value)
        surface, reading = surface_key(text), reading_key(text)
        if not surface:
            continue
        surfaces.add(surface)
        if reading:
            spellings.setdefault(reading, set()).add(surface)
    return Words(frozenset(surfaces), frozenset(spellings),
                 {reading: frozenset(s) for reading, s in spellings.items()})


def split_known(entries: list[str], words: Words) -> tuple[list[str], list[tuple[str, str]]]:
    """Split the entries into (to generate, already known).

    The known ones come as [(raw entry, word found)], to tell what was dropped.
    """
    todo: list[str] = []
    known: list[tuple[str, str]] = []
    for entry in entries:
        found = words.match(entry) if words else ""
        if found:
            known.append((entry, found))
        else:
            todo.append(entry)
    return todo, known


# -- The sources already handled -----------------------------------------------
# Listening and reading cards carry their provenance in `Source`. Each source
# writes its own trace (an article's URL, "feed - episode title"), and a card is
# compared by whether its field starts with it: nothing is parsed. Per mode, by
# note type: an article handled for listening is still to do for reading.

# The field where the source is written, and the two commands that have one
# (vocabulary and grammar cards do not keep their article).
SOURCE_FIELD = "Source"
SOURCE_SETTINGS = {"audio": "KOTOGEN_AUDIO_NOTETYPE",
                   "reading": "KOTOGEN_READING_NOTETYPE"}


def source_notetypes() -> dict[str, str]:
    """The note type of each mode that keeps a source, as this profile set it."""
    return {mode: settings.text(option) for mode, option in SOURCE_SETTINGS.items()}


def carries(card_trace: str, trace: str) -> bool:
    """True if a card really comes from this source, and not from a neighbour.

    A prefix followed by nothing or by what `sources.provenance` appends (a
    place such as "(p. 3-)", an address), since "Feed - Ep 7" also starts
    "Feed - Ep 70". Public so that the sources reading their provenance back
    (`recognise`) apply the same rule.
    """
    if not card_trace.startswith(trace):
        return False
    rest = card_trace[len(trace):]
    return not rest or rest.startswith((" (", " http"))


@dataclass(frozen=True)
class Sources:
    """The provenances a collection carries, filed by mode."""

    by_mode: dict[str, frozenset[str]] = dataclasses.field(default_factory=dict)

    def __bool__(self) -> bool:
        """False when it teaches nothing: empty, no Source field, out of reach."""
        return any(self.by_mode.values())

    def traces(self, mode: str) -> frozenset[str]:
        """Everything this mode has already drawn cards from, as the field writes it."""
        return self.by_mode.get(mode, frozenset())

    def knows(self, mode: str, trace: str) -> bool:
        """True if a card of this mode already comes from this source.

        An empty trace knows nothing: it would prefix every card.
        """
        trace = (trace or "").strip()
        if not trace:
            return False
        return any(carries(value, trace) for value in self.traces(mode))

    def knows_id(self, mode: str, identifier: str) -> bool:
        """True if a provenance of this mode CARRIES this identifier, anywhere in it.

        For an identifier in the address (a news_id, a video ID): it survives a
        change of domain, as NHK has made once, where the prefix would not. Only
        for identifiers that cannot occur by chance: "12" is in any title.
        """
        identifier = (identifier or "").strip()
        if not identifier:
            return False
        return any(identifier in trace for trace in self.traces(mode))


NO_SOURCES = Sources()


def sources_of(known: Known) -> Sources:
    """The provenances of each mode this collection carries, read now."""
    by_mode: dict[str, frozenset[str]] = {}
    for mode, notetype in source_notetypes().items():
        traces = {card_field(card, SOURCE_FIELD).strip() for card in known.cards(notetype)}
        traces.discard("")
        if traces:
            by_mode[mode] = frozenset(traces)
    return Sources(by_mode)


# -- The question --------------------------------------------------------------

class Known:
    """What one collection already holds, as a run asks it.

    An implementation owes `cards`; the other defaults suit a collection with
    no schedule, no history of its own, and always within reach.
    """

    _sources: Sources | None = None

    def cards(self, notetype: str) -> list[dict]:
        """The cards it holds under this note type, as `{"id", "fields", "tags"}`.

        `fields` maps each field name to its text, written as a card file writes
        it (furigana in brackets, `<br>` between lines); `id` names the card in
        this collection. A note type it does not hold gives an empty list.
        """
        return []

    def learning(self, notetype: str) -> set | None:
        """The `id` of those of its cards still being learnt, None when it cannot tell.

        Only a collection that schedules its cards knows; None ("no idea") is
        not an empty set.
        """
        return None

    def reachable(self, notetype: str) -> bool:
        """Whether what it holds can be known at all.

        A JLPT source asks it before working out what is missing: without an
        answer, it would be the whole level.
        """
        return True

    def live(self) -> bool:
        """Whether its answers are the collection itself, as it stands now.

        Then an empty answer (an empty deck, a missing note type) is worth
        saying; from a file or from nothing, it is not.
        """
        return False

    def name(self, deck: str) -> str:
        """What the screen calls it, `deck` being the deck the run aims at."""
        return deck

    def history(self, default: Path) -> Path | None:
        """Where the history of handled sources lives, or None for none.

        `default` is `seen.json`, the history of this machine.
        """
        return None

    def written(self, notetype: str, cards: list[dict]) -> None:
        """These cards were just written for it, in a file still to be imported."""

    def words(self, notetype: str, field_name: str = "Expression") -> Words:
        """What a field of this note type holds, as words to compare with."""
        return words_of(card_field(card, field_name) for card in self.cards(notetype))

    def sources(self) -> Sources:
        """The provenances its cards carry, read at the first request.

        Kept from then on: only a send changes them, and it calls `forget`.
        """
        if self._sources is None:
            self._sources = sources_of(self)
        return self._sources

    def forget(self) -> None:
        """It has just changed: what was read of it is read again."""
        self._sources = None


class Nothing(Known):
    """A run that remembers nothing.

    A JSON run with no file named, or a program that did not say what it keeps:
    everything asked for is made.
    """


class JsonlFile(Known):
    """The file a JSON Lines run is named after, standing for the deck.

    Cards for another tool are compared with the set this file holds, not with
    the deck; `<name>.seen.json` beside it stands for `seen.json`. A file not
    written yet holds nothing.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def cards(self, notetype: str) -> list[dict]:
        """Its cards, when its header names this note type.

        Read by `exporter.read_cards`; a line that does not read is passed over.
        """
        from kotogen import exporter  # late: the exporter remembers through `memory`

        try:
            read = exporter.read_cards(self.path)
        except (OSError, exporter.NotCards):
            return []
        if read.header.get("notetype") != notetype:
            return []
        return read.cards

    def name(self, deck: str) -> str:
        return self.path.name

    def history(self, default: Path) -> Path | None:
        return self.path.with_name(self.path.stem + ".seen.json")
