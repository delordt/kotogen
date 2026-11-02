"""The number announcing a passage, spotted without the model.

Its value too (the rank of a past-paper item), and the other free nets of the
split: the reading time and its bell, the exam question asked twice.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from kotogen.generators import cuts

if TYPE_CHECKING:
    # Named in the annotations only: audio_split imports this module, and an
    # import the other way would be a cycle.
    from kotogen.generators.audio_split import Segment, Word

# ── The announcement number, spotted without the model ────────────────────────

# Whisper writes an announced number in any of four spellings, all to cover: the
# figure (`4`), hiragana (`に`, `さん`), katakana, and kanji (`二`), the last two
# for a number said alone. Past papers rather say 「第4問」 or 「問題4」.
_DIGIT = "[0-9０-９]{1,2}"
_KANJI = "[〇零一二三四五六七八九十]"

# In kana the readings do not string together freely, which tells a number from
# a word (「いちご」 is a strawberry, not "one-five"): the grammar of 0 to 99,
# the only range a passage is numbered in, is written out.
_UNIT = "(?:いち|に|さん|よん|し|ご|ろく|なな|しち|はち|きゅう|く)"
_KANA = rf"(?:{_UNIT}?じゅう{_UNIT}?|{_UNIT}|ぜろ|れい)"
_UNIT_KATA = "(?:イチ|ニ|サン|ヨン|シ|ゴ|ロク|ナナ|シチ|ハチ|キュウ|ク)"
_KATAKANA = rf"(?:{_UNIT_KATA}?ジュウ{_UNIT_KATA}?|{_UNIT_KATA}|ゼロ|レイ)"

_NUMBER = rf"(?:{_DIGIT}|{_KANA}|{_KATAKANA}|{_KANJI}+)"

# What can surround the number in an announcement. Cleaned like the text they are
# compared with, whose punctuation includes 「ー」, or 「ナンバー」 would never match.
_ANNOUNCE_BEFORE = tuple(cuts.without_punctuation(t) for t in ("第", "問題", "ナンバー", "その"))
_ANNOUNCE_AFTER = ("番目", "ばんめ", "番", "ばん", "問", "もん", "つ目", "つめ", "つ")

_NUMBER_RE = re.compile(
    rf"^(?:{'|'.join(_ANNOUNCE_BEFORE)})?{_NUMBER}(?:{'|'.join(_ANNOUNCE_AFTER)})?$")

# The common counters, which make a number part of the sentence (「4時」, 「3人」)
# rather than an announcement. In kana only forms of two moras or more: 「こ」
# would refuse 「これ」, the very speech to keep.
_COUNTERS = "時分秒人個番円歳才月日回本枚台冊杯匹頭階年度週目名件度倍"
_COUNTERS_KANA = ("ふん", "ぷん", "びょう", "にん", "えん", "さい", "がつ",
                   "ねん", "じかん", "まい", "かい")

# Written like a number without being one: 「一番」, the adverb "the most", and a
# common sentence ending (「これが一番」). At the head the counter after it
# settles it; at the tail nothing follows to settle it.
_ADVERBS = ("一番", "いちばん", "1番")

# What follows that adverb in the instruction of a past paper and the answer of
# its example (「いちばん いい」), heard in every section: taken for announcements,
# they would leave item 1 announced several times and placed nowhere.
_SUPERLATIVE_AFTER = ("いい", "よい", "良い", "よかった")

# One isolated katakana mora: what Whisper hands back of a foreign word, never of
# an announced number (which takes a line of its own, or is written as a figure).
_KATAKANA_RE = re.compile(r"^[゠-ヿ]$")

# Minimum blank between the number and the speech around it, for the former to be
# held as an announcement.
MARKER_PAUSE = 0.35


def is_marker(text: str) -> bool:
    """Is this text nothing but an announcement number, and nothing else?"""
    clean = cuts.without_punctuation(text)
    return bool(clean) and bool(_NUMBER_RE.match(clean))


# ── The value of the announced number ─────────────────────────────────────────
# `is_marker` answers "that is an announcement", what follows "which one": a
# downloaded past-paper section names only the section (`N5Q1.mp3`), while the
# sound announces every item.

# What makes an announced number the rank of an ITEM, not of a section: the
# suffix 「ばん」, the only thing telling apart three forms met in one file:
#   「1番」    item 1                                       -> read
#   「問題1」  the whole section                            -> refused
#   「2」      the bell, which Whisper writes as a figure   -> refused
# A bare number is never read as an item: better no figure than a bell's.
_ITEM_RE = re.compile(rf"^({_NUMBER})(?:番目|ばんめ|番|ばん)$")

# Past this it is a misreading rather than an item rank (the fullest section
# holds about fifteen), and nothing is handed back.
ITEM_MAX = 20

_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")

# The readings of `_UNIT` with their value: the grammar says what is a number,
# this table which one.
_READINGS = {
    "いち": 1, "に": 2, "さん": 3, "よん": 4, "し": 4, "ご": 5,
    "ろく": 6, "なな": 7, "しち": 7, "はち": 8, "きゅう": 9, "く": 9,
    "ぜろ": 0, "れい": 0,
}
_KANJI_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
                   "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _to_hiragana(text: str) -> str:
    """Katakana brought back to hiragana: 「サン」 and 「さん」 are worth the same 3."""
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヴ" else c for c in text)


def _compose(head: str, tail: str, table: dict[str, int]) -> int | None:
    """A number written with its tens: (before, after) the 「十」, or None."""
    tens = 1 if not head else table.get(head)
    units = 0 if not tail else table.get(tail)
    if tens is None or units is None:
        return None
    return tens * 10 + units


def number_value(text: str) -> int | None:
    """The value of a number written in figures, in kana or in kanji, or None.

    The numeric counterpart of `_NUMBER`, which only says whether it is one:
    Whisper writes 「1番」, 「に番」 or 「三番」 depending on what it heard.
    """
    word = _to_hiragana(text).translate(_FULLWIDTH_DIGITS)
    if not word:
        return None
    if word.isdigit():
        return int(word)
    if all(c in _KANJI_DIGITS or c == "十" for c in word):
        head, sep, tail = word.partition("十")
        return (_compose(head, tail, _KANJI_DIGITS) if sep
                else _KANJI_DIGITS.get(word))
    head, sep, tail = word.partition("じゅう")
    return _compose(head, tail, _READINGS) if sep else _READINGS.get(word)


def announced_item(segment: Segment) -> int | None:
    """The item rank the head announcement of this segment carries, or None.

    Read on the very tokens `head_announcement` takes out of the sound, and
    nowhere else: anywhere in the line, the 「1番」 of an example's answer would
    be read. With no timestamped words (a subtitle line), only an announcement
    taking a line of its own is read. The 「いちばん」 of the instruction is not
    read: see `_SUPERLATIVE_AFTER`.
    """
    if segment.words:
        end = head_announcement(segment.words)
        if not end:
            return None
        head = cuts.without_punctuation("".join(m.text for m in segment.words[:end]))
        if head in _ADVERBS and _opens_a_superlative(segment.words[end:]):
            return None
    else:
        head = cuts.without_punctuation(segment.text)
    found = _ITEM_RE.match(head)
    if not found:
        return None
    value = number_value(found.group(1))
    return value if value is not None and 1 <= value <= ITEM_MAX else None


def _opens_a_superlative(following: tuple[Word, ...]) -> bool:
    """Is the 「一番」 just read the adverb "the most" rather than item 1?

    The word after it settles it, as the counter does in `attack_after_marker`:
    an item announcement is followed by a noun setting up the conversation,
    never by 「いい」.
    """
    word = _to_hiragana(cuts.without_punctuation(following[0].text)) if following else ""
    return word.startswith(_SUPERLATIVE_AFTER)


def unique_items(segments: list[Segment]) -> frozenset[int]:
    """The item ranks this file announces ONLY ONCE.

    Whisper may write the bell closing the reading time as the number it just
    heard, so a rank can appear again in front of another item's conversation.
    A rank announced twice cannot be placed and is not read; the others stay.
    """
    counted: dict[int, int] = {}
    for segment in segments:
        value = announced_item(segment)
        if value is not None:
            counted[value] = counted.get(value, 0) + 1
    return frozenset(value for value, times in counted.items() if times == 1)


def block_item(segments: list[Segment], lines: list[int],
               unique: frozenset[int]) -> int | None:
    """The rank of the item these lines are the conversation of, or None.

    Read at the head of the first line kept (「3番 男の人と…」, the usual form),
    then on the line before it when the announcement takes a line of its own;
    further up lies the previous item's announcement. `unique` is the census of
    the file (`unique_items`). The block's rank in the file is never a fallback:
    the opening example and the refused passages shift it.
    """
    if not lines:
        return None
    first = lines[0]
    value = announced_item(segments[first - 1])
    if value is None and first >= 2:
        value = announced_item(segments[first - 2])
    return value if value in unique else None


# What announces the example of a past-paper section, glued to its setting up
# (「例 駅で…」) or written 0 as often (「0 すみません」): `item_opening` takes
# both. The kana that make it a word (例えば, 例の) keep it from being taken.
_EXAMPLE = "例"
_EXAMPLE_WORDS = ("え", "の")


def item_opening(segment: Segment) -> float | None:
    """Where the speech starts on a line that OPENS an item, or None.

    Such a line glues the item's announcement (「4番」, or 「例」 for the
    example) to its setting up or, in a 即時応答, to the prompt. Unlike in
    `attack_after_marker`, a long `4番` still counts: its suffix says it is no
    sentence, and Whisper stretches 「番」 over the pause after it. The bare
    forms of the example keep the bound.
    """
    words = segment.words
    if not words:
        return None
    head = head_announcement(words)
    if head and head < len(words):
        if announced_item(segment) is None:
            marker = cuts.without_punctuation("".join(m.text for m in words[:head]))
            if number_value(marker) != 0:
                return None
            if words[head - 1].end - words[0].start > cuts.ANNOUNCEMENT_MAX:
                return None
    elif cuts.without_punctuation(words[0].text) == _EXAMPLE and len(words) > 1:
        head = 1
        if cuts.without_punctuation(words[1].text).startswith(_EXAMPLE_WORDS):
            return None
    else:
        return None
    following = words[head]
    if _follows_a_counter(following.text):
        return None
    return following.start


# A silence too long for a line to be said in it: the reading time of a past
# paper lasts fifteen to twenty seconds, a pause in a reply under a second and a
# half, and a lower bound catches replies whose words Whisper spread over pauses.
UNHEARD_SILENCE = 3.0


def unheard(segment: Segment, silences: list[tuple[float, float]]) -> bool:
    """Is this a line nobody said - every word of it inside a long silence?

    Whisper writes something in a long blank rather than nothing, and such a
    line would take the blank into the card. The signal settles it word by word:
    where it measured silence, nothing was said.
    """
    long = [(start, end) for start, end in silences if end - start >= UNHEARD_SILENCE]
    if not segment.words or not long:
        return False

    def silent(spans: list[tuple[float, float]]) -> bool:
        return all(any(start - 0.01 <= (word.start + word.end) / 2 <= end + 0.01
                       for start, end in spans) for word in segment.words)

    if silent(long):
        return True
    # Or in the short blank between the bell and the voice, which follows the
    # long one by no more than a bell.
    blank_end = max((end for _start, end in long if end <= segment.words[0].start + 0.01),
                    default=None)
    return (blank_end is not None
            and segment.words[0].start - blank_end <= BELL_MAX and silent(silences))


def without_the_unheard(segments: list[Segment], lines: list[int],
                        silences: list[tuple[float, float]]) -> list[int]:
    """The lines, minus those nobody said, and minus the bare number that touches them.

    That number is the bell closing the reading time, which Whisper writes 「2」.
    Nothing is removed from a block that would be left empty: what was taken for
    silence would be all of it.
    """
    gone = {number for number in lines if unheard(segments[number - 1], silences)}
    if not gone or len(gone) == len(lines):
        return list(lines)
    # A line repeating word for word the unsaid line beside it is the same loop
    # of Whisper's, laid over the one sound of the blank.
    while True:
        echoes = {number for number in lines if number not in gone and any(
            other in gone and bare_text(segments[other - 1]) == bare_text(segments[number - 1])
            for other in (number - 1, number + 1))}
        if not echoes:
            break
        gone |= echoes
    gone |= {number for number in lines
             if (number - 1 in gone or number + 1 in gone)
             and is_marker(segments[number - 1].text)}
    kept = [number for number in lines if number not in gone]
    return kept or list(lines)


def _blank_between(before: Segment, after: Segment,
                   long: list[tuple[float, float]]) -> bool:
    """Does a long silence separate these two lines?

    Read from the start of the last word of the first to the end of the first
    word of the second, as Whisper lets a word run on into the blank.
    """
    last = before.words[-1].start if before.words else before.start
    first = after.words[0].end if after.words else after.end
    return any(last <= start and end <= first for start, end in long)


def at_the_blanks(runs: list[list[int]], segments: list[Segment],
                  silences: list[tuple[float, float]]) -> list[list[int]]:
    """The runs cut again where a long silence separates two lines that follow.

    The reading time of a past paper falls between the scene-setting and the
    conversation; when Whisper wrote nothing in it, the blank would stay in the
    card. The bare number touching the blank on either side (the bell, 「2」)
    goes with it.
    """
    long = [(start, end) for start, end in silences if end - start >= UNHEARD_SILENCE]
    if not long:
        return runs
    pieces: list[list[int]] = []
    for run in runs:
        piece = [run[0]]
        for before, after in zip(run, run[1:]):
            if _blank_between(segments[before - 1], segments[after - 1], long):
                pieces.append(piece)
                piece = []
            piece.append(after)
        pieces.append(piece)
    # Which edges of which piece touch a blank, including a blank on a cut already
    # made (the exam question taken out before it).
    opened = {id(piece) for previous, piece in zip(pieces, pieces[1:])
              if _blank_between(segments[previous[-1] - 1], segments[piece[0] - 1], long)}
    closed = {id(previous) for previous, piece in zip(pieces, pieces[1:])
              if id(piece) in opened}
    kept: list[list[int]] = []
    for piece in pieces:
        trimmed = list(piece)
        while id(piece) in opened and len(trimmed) > 1 and is_marker(segments[trimmed[0] - 1].text):
            trimmed.pop(0)
        while id(piece) in closed and len(trimmed) > 1 and is_marker(segments[trimmed[-1] - 1].text):
            trimmed.pop()
        if ((id(piece) in opened or id(piece) in closed) and len(trimmed) == 1
                and is_marker(segments[trimmed[0] - 1].text)):
            continue   # the bell alone, between two blanks
        kept.append(trimmed)
    return kept or runs


# How long the bell closing the reading time rings: 2.3 seconds measured.
BELL_MAX = 3.0


def after_the_bell(segment: Segment, silences: list[tuple[float, float]]) -> float | None:
    """Where the speech starts on a line opening after the reading time, when
    Whisper laid its first word over the bell; None otherwise.

    A first word running across a silence of its own says so, as a word holds no
    pause: the speech starts where that silence ends, if it ends within a bell's
    length after the blank.
    """
    long = [(start, end) for start, end in silences if end - start >= UNHEARD_SILENCE]
    if not segment.words or not long:
        return None
    head = segment.words[:2]
    blank_end = max((end for _start, end in long if end <= head[0].end + 0.01), default=None)
    if blank_end is None:
        return None
    for start, end in silences:
        if (end - start >= cuts.BOUNDARY_MIN and 0 <= start - blank_end <= BELL_MAX
                and any(word.start < start and word.end > end for word in head)):
            return end
    return None


def _follows_a_counter(text: str) -> bool:
    """Does the word that follows start with a counter (「4」「時に」)?

    That tells a number of the sentence from an announcement when no blank does.
    """
    clean = cuts.without_punctuation(text)
    if not clean:
        return False
    return clean[0] in _COUNTERS or clean.startswith(_COUNTERS_KANA)


def head_announcement(words: tuple[Word, ...]) -> int | None:
    """How many head tokens are nothing but the announcement of the passage, if any.

    Whisper splits an announcement in many ways (`4`|`あっ`|`それ`,
    `第`|`4`|`問`, `に`|`ばん`|`昨日の`), so tokens are gathered as long as they
    still form one, and the rank of the first token past it is handed back.
    `None` when the head is no announcement, by far the most frequent case.
    """
    joined = ""
    end: int | None = None
    for rank, word in enumerate(words):
        clean = cuts.without_punctuation(word.text)
        if not clean:
            # A token of pure punctuation says nothing: it belongs to what comes
            # before it, announcement or speech.
            if end == rank:
                end = rank + 1
            continue
        candidate = joined + clean
        if _NUMBER_RE.match(candidate):
            joined, end = candidate, rank + 1
        elif candidate in _ANNOUNCE_BEFORE:
            # 「第」 alone is not a number yet: it is gathered without moving the
            # boundary, which is only laid on a complete announcement.
            joined = candidate
        else:
            break
    return end


def attack_after_marker(segment: Segment, *, collection: bool = False) -> float | None:
    """Start of the speech when the segment opens on an announced number.

    Safety net for the `4 あっそれ` case, which the model should report through
    `start_word` and often omits. A number of the sentence is spared: the next
    word must not start with a counter (「4」「時に」), and a blank must follow
    the number, except in a collection: its passages are announced, and the
    blank is often too short to measure.
    """
    words = segment.words
    head = head_announcement(words)
    # `head >= len(words)`: the segment is ONLY the announcement, and the whole
    # line leaves the block.
    if not head or head >= len(words):
        return None
    if words[head - 1].end - words[0].start > cuts.ANNOUNCEMENT_MAX:
        return None
    # Whisper splits katakana mora by mora ('ク'|'リ'|'ス'), and ク and シ read as
    # figures: one katakana mora alone is never taken. Kana stays accepted (「に」,
    # 「さん」), as hiragana is not broken up that way.
    if len(cuts.without_punctuation("".join(m.text for m in words[:head]))) == 1 \
            and _KATAKANA_RE.match(words[0].text.strip()):
        return None
    following = words[head]
    if _follows_a_counter(following.text):
        return None
    if not collection and following.start - words[head - 1].end < MARKER_PAUSE:
        return None
    return following.start


def tail_announcement(words: tuple[Word, ...]) -> int | None:
    """Rank of the first tail token that is already nothing but the next announcement.

    Symmetrical to `head_announcement`, for a last line closing on the number of
    the NEXT passage (`…ですか。 に`). Walked back from the end, where the suffix
    (「問」) comes before the number.
    """
    joined = ""
    start: int | None = None
    for rank in range(len(words) - 1, -1, -1):
        clean = cuts.without_punctuation(words[rank].text)
        if not clean:
            if start == rank + 1:
                start = rank
            continue
        candidate = clean + joined
        if _NUMBER_RE.match(candidate):
            joined, start = candidate, rank
        elif candidate in _ANNOUNCE_AFTER:
            # 「問」 alone is not a number yet: it is gathered without moving the
            # boundary back, which is only laid on a complete announcement.
            joined = candidate
        else:
            break
    return start


def fade_before_marker(segment: Segment, *, collection: bool = False) -> float | None:
    """End of the speech when the segment closes on the number of the next one.

    Same safeguards as `attack_after_marker`, the waiver of the blank included,
    which is what lets it fire: Whisper's timestamps come from an alignment and
    string words with no gap, so the blank is never in the data. 「一番」, written
    like the number 1, is left alone rather than clip a conversation's last word.
    """
    words = segment.words
    start = tail_announcement(words)
    if not start:          # None, or the whole segment: nothing to cut off here
        return None
    tail = cuts.without_punctuation("".join(m.text for m in words[start:]))
    if tail in _ADVERBS:
        return None
    # A one-mora announcement in kana cannot be told from a verb ending (the 「く」
    # of 「行く」 reads 9), and at the tail no counter follows to settle it: only
    # the written figure is safe.
    if len(tail) == 1 and not tail.isdigit():
        return None
    if words[-1].end - words[start].start > cuts.ANNOUNCEMENT_MAX:
        return None
    previous = words[start - 1]
    if not collection and words[start].start - previous.end < MARKER_PAUSE:
        return None
    return previous.end


# ── The exam question, spotted without the model ──────────────────────────────
# A second deterministic net, like the one for announced numbers: what the model
# omits ends up in the sound, heard only at review time.

# An announcement at the head of a line with no timestamped words. The suffix is
# compulsory, unlike in `_NUMBER_RE`: in running text a bare number belongs to
# the sentence.
_HEAD_ANNOUNCEMENT_RE = re.compile(
    rf"^(?:{'|'.join(_ANNOUNCE_BEFORE)})?{_NUMBER}(?:{'|'.join(_ANNOUNCE_AFTER)})")


def bare_text(segment: Segment) -> str:
    """The text of the line, minus its announcement and minus its punctuation.

    For comparing lines: the exam asks its question again with the item's number
    in front, and the two statements must match.
    """
    if segment.words:
        start = head_announcement(segment.words) or 0
        # The safeguard of `attack_after_marker`: the number of 「2人は…」 belongs
        # to the sentence, and removing it would make two statements differ.
        if 0 < start < len(segment.words) and _follows_a_counter(segment.words[start].text):
            start = 0
        return cuts.without_punctuation("".join(m.text for m in segment.words[start:]))
    return cuts.without_punctuation(_HEAD_ANNOUNCEMENT_RE.sub("", segment.text.strip()))


def without_the_question(segments: list[Segment], lines: list[int],
                         window: tuple[int, int]) -> list[int]:
    """The lines, minus the question the exam asks about the passage.

    Told by repetition alone: an interrogative line at an edge of the block whose
    twin lies across the exchange, within `window` (up to the neighbouring kept
    blocks). An announced head line stays; so does a block under three lines.
    """
    lines = list(lines)
    if len(lines) < 3:
        return lines
    start, end = max(1, window[0]), min(len(segments), window[1])
    neighbours: dict[str, list[int]] = {}
    for number in range(start, end + 1):
        neighbours.setdefault(bare_text(segments[number - 1]), []).append(number)

    first, last = lines[0], lines[-1]
    kept = []
    for rank, number in enumerate(lines):
        segment = segments[number - 1]
        bare = bare_text(segment)
        # Interrogative, or it is a line, a verbal tic or a blank Whisper wrote
        # twice, not the exam question.
        if bare.endswith("か"):
            twins = [other for other in neighbours.get(bare, ()) if other != number]
            announced = bare != cuts.without_punctuation(segment.text)
            if rank <= 1 and not announced and any(other >= last for other in twins):
                continue
            if rank == len(lines) - 1 and any(other <= first + 1 for other in twins):
                continue
        kept.append(number)
    return kept if len(kept) > 1 else lines
