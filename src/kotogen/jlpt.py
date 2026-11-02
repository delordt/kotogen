"""The JLPT level of a word, read from a local table rather than guessed by AI.

It tags vocabulary cards (`Level::N4`), and sorts and filters the words extracted
from a text before generation. The JLPT has published no official list since
2010: the table (data/jlpt_vocab.tsv, about 9,200 words) is a consensus, and a
word outside it has no level and is never dropped.

Each word is listed once, under its usual spelling, with its other spellings
beside it (美味しい, おいしい). A reading does not designate a word (はし: 橋, 箸
or 端), so the spelling decides and the reading is only a fallback.
"""

from __future__ import annotations

from pathlib import Path

from kotogen.furigana import JP_RUN_RE, KANJI_RE, reading_key, strip_furigana, surface_key

DATA_FILE = Path(__file__).parent / "data" / "jlpt_vocab.tsv"

# Easiest first, the order they are learnt in: the sort order, and the scale
# `is_much_easier` compares on.
LEVELS = ("N5", "N4", "N3", "N2", "N1")
_RANK = {level: i for i, level in enumerate(LEVELS)}

# The entry that asks a generator for what the level holds and the deck lacks
# (`kotogen vocab jlpt`, `grammar jlpt`, `kanji jlpt`).
KEYWORD = "jlpt"

# {spelling: level} and {reading: level}, loaded on the first question. A reading
# shared by words of different levels is left out.
_by_surface: dict[str, str] | None = None
_by_reading: dict[str, str] = {}
# {spelling: reading}, filled by the same load. Without the trap of
# `_by_reading`: a spelling carries one word.
_reading_of: dict[str, str] = {}
# {spelling a row heads: the place of that row}: the words `words_of` offers, in
# the order of the list (most frequent first). Other spellings are not words of
# their own.
_place: dict[str, int] = {}
# What separates the other spellings of a word, in the fourth column.
OTHERS_SEP = "、"


def _keep_easiest(table: dict[str, str], key: str, level: str) -> None:
    """A word listed at several levels is kept at the easier of the two.

    That is the level at which the learner meets it for the first time.
    """
    known = table.get(key)
    if known is None or _RANK[level] < _RANK[known]:
        table[key] = level


def _load() -> dict[str, str]:
    """Load the table on the first call. Empty table if the file is missing."""
    global _by_surface
    if _by_surface is not None:
        return _by_surface

    _by_surface = {}
    _by_reading.clear()
    _reading_of.clear()
    _place.clear()
    try:
        lines = DATA_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return _by_surface  # incomplete install: we keep quiet, without a level

    homophones: dict[str, set[str]] = {}  # reading -> spellings that carry it
    for line in lines:
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2 or parts[0] not in _RANK:
            continue
        level, surface = parts[0], parts[1].strip()
        reading = parts[2].strip() if len(parts) > 2 else ""
        if not surface:
            continue
        others = parts[3].split(OTHERS_SEP) if len(parts) > 3 else []
        _place.setdefault(surface, len(_place))
        for spelling in filter(None, (s.strip() for s in [surface, *others])):
            _keep_easiest(_by_surface, spelling, level)
            if reading:
                homophones.setdefault(reading_key(reading), set()).add(spelling)
                # the first row of a spelling is its likeliest word: the easiest
                # level, then the most frequent
                _reading_of.setdefault(spelling, reading_key(reading))

    _index_readings(_by_surface, homophones)
    return _by_surface


def _index_readings(table: dict[str, str], homophones: dict[str, set[str]]) -> None:
    """Index the readings that designate a single level.

    はし (橋 and 箸 N5, 端 N3) is left out. The spellings of one word share its
    row, hence its level, so they never set a reading apart.
    """
    for reading, surfaces in homophones.items():
        levels = {table[s] for s in surfaces if s in table}
        if len(levels) == 1:
            _by_reading[reading] = levels.pop()


def is_keyword(entry: str) -> bool:
    """True when the entry asks for the JLPT source: the keyword, alone."""
    return (entry or "").strip().lower() == KEYWORD


def level_of(word: str) -> str | None:
    """The JLPT level of a word ("N4"), or None if it is not in the table.

    Accepts a bare spelling, a raw entry ("涼しい - cool") or an Expression in
    furigana (`涼[すず]しい`). The spelling decides: the reading is only a
    fallback for a word all in kana, so 貴社, absent from the table, does not
    take the N4 of 汽車.
    """
    by_surface = _load()
    surface = _surface_of(word)
    if not surface:
        return None
    found = by_surface.get(surface)
    if found or KANJI_RE.search(surface):
        return found
    return _by_reading.get(reading_key(surface))


def _surface_of(word: str) -> str:
    """The spelling to look up in the table, extracted from the form received.

    An all-Japanese string is taken whole (気をつける, not its つける); one that
    carries anything else gives its longest Japanese run.
    """
    compact = surface_key(word)  # furigana and spaces removed
    if not compact:
        return ""
    if JP_RUN_RE.fullmatch(compact):
        return compact
    runs = JP_RUN_RE.findall(strip_furigana(word))
    return max(runs, key=len) if runs else ""


# The gap, in levels, from which a word is too easy for the target, as the AI is
# told to ignore words "clearly easier": N4 is still on target for N3, N5 is not.
# At 1, aiming at N3 on an NHK article would drop almost everything.
_DROP_GAP = 2


def is_much_easier(word: str, than: str) -> bool:
    """True if the KNOWN level of this word is clearly easier than the target.

    False when the level is unknown.
    """
    level = level_of(word)
    if level is None or than not in _RANK:
        return False
    return _RANK[than] - _RANK[level] >= _DROP_GAP


def sort_by_level(words: list[str]) -> list[str]:
    """Sort from the most accessible to the hardest, unknown ones last.

    Stable: at equal level, the AI's order (by usefulness) is kept.
    """
    def rank(word: str) -> int:
        level = level_of(word)
        return _RANK[level] if level else len(LEVELS)

    return sorted(words, key=rank)


def prepare(words: list[str], level: str) -> tuple[list[str], list[str]]:
    """Order the extracted words and, if a level is asked for, drop the too easy.

    Returns (words kept, words dropped). `level == "auto"` only sorts. A word
    absent from the table is always kept.
    """
    ordered = sort_by_level(words)
    if level not in _RANK:
        return ordered, []
    kept = [w for w in ordered if not is_much_easier(w, level)]
    dropped = [w for w in ordered if is_much_easier(w, level)]
    return kept, dropped


def reading_of(word: str) -> str:
    """The reading the table gives this spelling, in hiragana, or "".

    A kana spelling is its own reading; a spelling absent from the table has
    none here, and the caller asks the dictionary instead.
    """
    _load()
    return _reading_of.get(surface_key(word), "")


def words_of(level: str) -> list[str]:
    """Every word of the table at this level, the most frequent first.

    One per row, under the spelling that heads it (美味しい, not おいしい again).
    A `level` off the scale ("auto") returns the whole table, easiest level first.
    """
    table = _load()
    words = sorted(_place, key=lambda word: (_RANK[table[word]], _place[word]))
    if level in _RANK:
        return [word for word in words if table[word] == level]
    return words


def tag_for(word: str) -> str:
    """The `Level::NX` tag of the word, or "" if its level is unknown.

    Never translated, like the tags in `dictionary`: a tag is what a card is
    filed under, whatever language the card is written in.
    """
    level = level_of(word)
    return f"Level::{level}" if level else ""
