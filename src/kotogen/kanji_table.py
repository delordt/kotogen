"""What a kanji is - its readings, its level, its strokes - read from local tables.

A model asked for these facts now and then invents a reading; the tables answer
the same every time, without a call. Four files of `data/`, each saying at its
head how it was made:

- `joyo_kanji.tsv`: the Joyo table (常用漢字表, 2010), one row per reading. A
  card leaves out the readings it sets back (行 アン, 上 うわ).
- `joyo_special_readings.tsv`: its appendix, the words read as a whole (今日 is
  きょう), which illustrate no reading of their kanji.
- `jlpt_kanji.tsv`: the JLPT level of the 2136 Joyo kanji.
- `kanji_strokes.tsv`: the strokes of 5895 kanji, counted the Japanese way.

Only the Joyo kanji have readings and a level; a name kanji (伊, 翔) has none,
and is never dropped for it. A level is not read off the vocabulary table, which
writes words in kanji long before they are taught (美味しい is an N5 word).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from kotogen.jlpt import LEVELS

DATA = Path(__file__).parent / "data"
JOYO_FILE = DATA / "joyo_kanji.tsv"
SPECIAL_FILE = DATA / "joyo_special_readings.tsv"
LEVELS_FILE = DATA / "jlpt_kanji.tsv"
STROKES_FILE = DATA / "kanji_strokes.tsv"

# The four Joyo kanji the 2010 table prints outside JIS X 0208, the set keyboards
# type, keyed by the typed form the table itself allows (𠮟・叱 in its annex).
_TYPED_FORMS = {"叱": "𠮟", "填": "塡", "剥": "剝", "頬": "頰"}

# The ideographs only. `furigana.KANJI_CHARS` also counts 々, 〆, 〇, ヵ and ヶ,
# which take a reading in a word but have no kanji card.
_KANJI_RE = re.compile("[㐀-䶿一-鿿豈-﫿\U00020000-\U0003ffff]")

_ON_RE = re.compile(r"[ァ-ヶー]+")


@dataclass(frozen=True)
class Reading:
    """One reading of a kanji, as the Joyo table gives it."""

    # Katakana for an on reading (ガク), hiragana for a kun reading, with a dot
    # where the okurigana starts (まな.ぶ).
    text: str
    # Set back by the table: special, or of very narrow use (行 アン).
    narrow: bool
    # The words the table gives for this reading (学ぶ), as printed.
    examples: tuple[str, ...]
    # The remarks of the table about this reading (⇔ 当てる、充てる).
    notes: str

    @property
    def is_on(self) -> bool:
        return bool(_ON_RE.fullmatch(self.text))

    @property
    def kana(self) -> str:
        """The whole reading, okurigana included: まなぶ."""
        return self.text.replace(".", "")

    @property
    def own(self) -> str:
        """What the kanji itself reads, without its okurigana: まな."""
        return self.text.split(".", 1)[0]


@dataclass(frozen=True)
class Kanji:
    """A kanji, as far as the local tables know it."""

    char: str
    # Empty outside the Joyo table.
    readings: tuple[Reading, ...]
    # The traditional forms the Joyo table prints beside it: （學）.
    forms: str
    strokes: int | None
    level: str | None

    @property
    def joyo(self) -> bool:
        return bool(self.readings)

    @property
    def on(self) -> tuple[Reading, ...]:
        return tuple(r for r in self.readings if r.is_on)

    @property
    def kun(self) -> tuple[Reading, ...]:
        return tuple(r for r in self.readings if not r.is_on)

    @property
    def common(self) -> tuple[Reading, ...]:
        """The readings a card may show: all but those the table sets back."""
        return tuple(r for r in self.readings if not r.narrow)


@dataclass
class _Tables:
    readings: dict[str, list[Reading]]
    forms: dict[str, str]
    special: list[tuple[str, str]]          # (spelling, reading), in table order
    levels: dict[str, str]
    by_level: dict[str, list[str]]
    strokes: dict[str, int]


_tables: _Tables | None = None


def _rows(path: Path) -> list[list[str]]:
    """The data rows of a table, or none if the file is missing.

    Silent, as in `jlpt`: a card is then made without these facts.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [line.split("\t") for line in lines if line and not line.startswith("#")]


def _load() -> _Tables:
    global _tables
    if _tables is not None:
        return _tables

    readings: dict[str, list[Reading]] = {}
    forms: dict[str, str] = {}
    for row in _rows(JOYO_FILE):
        if len(row) < 6:
            continue
        char, text, use, examples, printed, notes = row[:6]
        readings.setdefault(char, []).append(Reading(
            text, use == "narrow", tuple(e for e in examples.split("、") if e), notes))
        if printed:
            forms[char] = printed

    special = []
    for row in _rows(SPECIAL_FILE):
        if len(row) >= 2:
            special.extend((spelling, row[0]) for spelling in row[1].split("、") if spelling)

    levels: dict[str, str] = {}
    by_level: dict[str, list[str]] = {level: [] for level in LEVELS}
    for row in _rows(LEVELS_FILE):
        if len(row) >= 2 and row[0] in by_level:
            levels[row[1]] = row[0]
            by_level[row[0]].append(row[1])

    strokes = {row[0]: int(row[1]) for row in _rows(STROKES_FILE)
               if len(row) >= 2 and row[1].isdigit()}

    _tables = _Tables(readings, forms, special, levels, by_level, strokes)
    return _tables


def lookup(char: str) -> Kanji | None:
    """What the tables know of this kanji, or None if none of them lists it.

    The form a keyboard types is taken for the one the Joyo table prints (叱 for
    𠮟), so the entry is found either way.
    """
    tables = _load()
    char = _TYPED_FORMS.get(char, char)
    readings = tuple(tables.readings.get(char, ()))
    strokes = tables.strokes.get(char)
    level = tables.levels.get(char)
    if not readings and strokes is None and level is None:
        return None
    return Kanji(char, readings, tables.forms.get(char, ""), strokes, level)


def level_of(char: str) -> str | None:
    """The JLPT level of a kanji ("N4"), or None when no list places it."""
    return _load().levels.get(_TYPED_FORMS.get(char, char))


def tag_for(char: str) -> str:
    """The `Level::NX` tag of the kanji, or "" if its level is unknown.

    The same tag as a vocabulary card's (`jlpt.tag_for`): what a card is filed
    under, never translated.
    """
    level = level_of(char)
    return f"Level::{level}" if level else ""


def of_level(level: str) -> list[str]:
    """The kanji of a level, the most frequent first.

    Only Joyo kanji carry a level, so every kanji listed is one of the table.
    """
    return list(_load().by_level.get(level, []))


def special_words(char: str) -> list[tuple[str, str]]:
    """The words of the appendix written with this kanji: (spelling, reading).

    今 gives 今日 きょう, 今朝 けさ and 今年 ことし: words a card may name, but
    never to illustrate a reading of 今.
    """
    char = _TYPED_FORMS.get(char, char)
    return [(spelling, reading) for spelling, reading in _load().special if char in spelling]


def is_special(word: str) -> bool:
    """True if the word is read as a whole (今日), not kanji by kanji."""
    return any(spelling == word for spelling, _ in _load().special)


def kanji_in(text: str) -> list[str]:
    """The kanji of a text, each once, in the order they first appear.

    The marks that stand among kanji without being one (々, 〆, 〇, ヵ, ヶ) are
    not taken: they have no card.
    """
    return list(dict.fromkeys(_KANJI_RE.findall(text)))
