"""At which second of the audio each line of the transcription starts.

The model rewrites the transcription, so its lines are matched on the text, as
`word_moment` does for a word: the timestamped source (Whisper's words or the
cues of a subtitle) is glued into one string without punctuation, and each line
is looked for in it from a cursor that only moves forward, a short "はい"
recurring. A line not found is rescued on its reading at cue level (「豚カツ」
against 「とんかつ」), then pro rata between the located lines, a rescued moment
having to fall strictly between its neighbours. With no line found, the field
stays empty.
"""

from __future__ import annotations

import re

from kotogen.furigana import process_furigana, reading_key, strip_furigana
from kotogen.generators.audio_split import Block, Segment
from kotogen.generators.cuts import without_punctuation

# Written for a line whose moment was not found. Not a zero, which is a valid
# moment: the line would replay the passage from its start at every click.
UNKNOWN = "-"

# Where the moment of a line comes from: the spelling, the reading, or a pro rata
# spread. Only the last is approximate, and worth saying on screen.
EXACT = "exact"
READING = "reading"
PRORATA = "prorata"

# Minimum length of a crop still looked for when the whole line is not found:
# shorter, it is a syllable that matches anywhere.
MIN_PREFIX = 4

# The share of the line a crop must keep, as a wrong hit drags every later line
# with it. A crop from the end keeps the line's start, distinctive (a third); one
# from the start keeps its ending, an inflection met everywhere (「ました」, half).
TAIL_SHARE = 3
HEAD_SHARE = 2

# How many times shorter than the text about to be dropped the sound left
# unmatched at the end must be (`spoken_lines`). A remainder of comparable length
# is likely the same passage spelled otherwise: the matching failed, not the sound.
SUSPECT_TAIL = 2

# Speaker label the model lays at the head of a line ("A：", "店員："): absent
# from the source, it would make every search in a dialogue fail.
_LABEL_RE = re.compile(r"^\s*[^：:\s][^：:]{0,11}[：:]\s*")


def _reading(text: str) -> str:
    """A text brought back to its reading: kana, without punctuation or spaces.

    For two sides spelled differently, as when the transcription does not come
    from the audio (「このあとも」 against 「この後も」). Kanji left without a
    reading get one on the way (`process_furigana`).
    """
    return without_punctuation(reading_key(process_furigana(text or "")))


def _target(line: str, *, reading: bool = False) -> str:
    """A line of the model brought back to what compares: no label, no reading,
    no punctuation."""
    bare = _LABEL_RE.sub("", line or "")
    if reading:
        return _reading(bare)
    return without_punctuation(strip_furigana(bare))


def _landmarks(segments: list[Segment], *,
               reading: bool = False) -> tuple[str, list[tuple[int, float]]]:
    """The glued source, and the moment that opens each position.

    Per word when Whisper timestamped words, per cue otherwise. In `reading` mode
    always per cue: the reading of a word fragment alone (「後」: あと or ご?)
    cannot be settled without its sentence.
    """
    joined = []
    anchors: list[tuple[int, float]] = []
    position = 0
    for segment in segments:
        units = ([(m.text, m.start) for m in segment.words]
                 if segment.words and not reading
                 else [(segment.text, segment.start)])
        for text, moment in units:
            clean = _reading(text) if reading else without_punctuation(text)
            if not clean:
                continue
            anchors.append((position, moment))
            joined.append(clean)
            position += len(clean)
    return "".join(joined), anchors


def _covered(segments: list[Segment], block: Block | None) -> list[Segment]:
    """The segments this block covers, or all of them when there is none."""
    if block is None:
        return list(segments)
    return [segments[i - 1] for i in block.lines if 1 <= i <= len(segments)]


def _locate(joined: str, target: str, cursor: int) -> tuple[int, int] | None:
    """Where this line sits in the glued source, starting from the cursor.

    Hands back (position of the moment, position where the cursor resumes), or
    None. Tried in order: the whole line; the line cropped from the end, for a
    word the model corrected there; cropped from the start, for something it
    added (「はい。」), the moment then taken as many characters upstream, which
    errs towards the previous sentence rather than past the first word.
    """
    if not target:
        return None
    position = joined.find(target, cursor)
    if position >= 0:
        return position, position + len(target)

    floor = max(MIN_PREFIX + 1, len(target) // TAIL_SHARE)
    tail = target
    while len(tail) > floor:
        tail = tail[:-1]
        position = joined.find(tail, cursor)
        if position >= 0:
            return position, position + len(tail)

    floor = max(MIN_PREFIX + 1, (len(target) + HEAD_SHARE - 1) // HEAD_SHARE)
    for cropped in range(1, len(target) - floor + 1):
        position = joined.find(target[cropped:], cursor)
        if position >= 0:
            # Never below the cursor: what is already matched is matched.
            return max(cursor, position - cropped), position + len(target) - cropped
    return None


def _moment_at(position: int, anchors: list[tuple[int, float]]) -> float | None:
    """The moment of the unit covering that position in the glued string."""
    found = None
    for start, moment in anchors:
        if start > position:
            break
        found = moment
    return found


def _rebase(moment: float, ranges: tuple[tuple[float, float], ...]) -> float:
    """The moment of the original file, brought back to that of the extracted piece.

    `Block.ranges` may hold several ranges, the split having dropped something in
    the middle (an exam question), and the extraction glues them back. A moment
    inside a dropped gap goes to the start of the next range.
    """
    elapsed = 0.0
    for start, end in ranges:
        if moment < start:
            return elapsed
        if moment <= end:
            return elapsed + (moment - start)
        elapsed += max(0.0, end - start)
    return elapsed


def _bounds(segments: list[Segment], block: Block | None,
            *, whole: bool = False) -> tuple[float, float] | None:
    """The first and the last sounding moment of the piece, in its own time.

    The outer ends the pro rata spread needs for the first and last lines. The
    start is that of the first word when there are words, landing on the speech
    rather than on a breath or a jingle before it.
    """
    covered = _covered(segments, block)
    if not covered:
        return None
    first = covered[0]
    start = first.words[0].start if first.words else first.start
    end = max(segment.end for segment in covered)
    ranges = block.ranges if (block is not None and not whole) else None
    if ranges is not None:
        start, end = _rebase(start, ranges), _rebase(end, ranges)
    return max(0.0, start), max(0.0, end)


def _fill_in(base: list[str], backup: list[str]) -> list[str]:
    """Pours into `base` the moments of a second matching, where they are missing.

    A rescued moment must fall strictly between its located neighbours, since the
    coarser matching often gives two lines the moment of the one cue holding both.
    Each accepted rescue is a neighbour for the next, so adjacent gaps cannot swap.
    """
    merged = list(base)
    for rank, (before, rescued) in enumerate(zip(base, backup)):
        if before != UNKNOWN or rescued == UNKNOWN:
            continue
        moment = float(rescued)
        previous = [float(m) for m in merged[:rank] if m != UNKNOWN]
        following = [float(m) for m in merged[rank + 1:] if m != UNKNOWN]
        if previous and moment <= previous[-1]:
            continue
        if following and moment >= following[0]:
            continue
        merged[rank] = f"{moment:.2f}"
    return merged


def _spread(found: list[str], lines: list[str],
            bounds: tuple[float, float] | None, *, reading: bool) -> list[str]:
    """Spreads the lines left without a moment over the time due to them.

    A run of unknown lines shares the interval between its located neighbours (or
    an end of the piece) with the line opening it, by the length of the text as
    heard (`_target`): read Japanese has a roughly constant rate. With no line
    located at all, nothing is spread.
    """
    if bounds is None or all(mark == UNKNOWN for mark in found):
        return found

    weights = [max(1, len(_target(line, reading=reading))) for line in lines]
    merged = list(found)
    rank = 0
    while rank < len(merged):
        if merged[rank] != UNKNOWN:
            rank += 1
            continue
        last = rank
        while last + 1 < len(merged) and merged[last + 1] == UNKNOWN:
            last += 1

        left = rank - 1 if rank else None
        right = last + 1 if last + 1 < len(merged) else None
        start = float(merged[left]) if left is not None else bounds[0]
        finish = float(merged[right]) if right is not None else bounds[1]
        # The line on the left takes up the start of the interval; the one on
        # the right starts at `finish`, where the sharing stops.
        shares = ([left] if left is not None else []) + list(range(rank, last + 1))
        total = sum(weights[r] for r in shares)

        if finish > start and total:
            running = 0
            for r in shares:
                if r >= rank:
                    merged[r] = f"{start + (running / total) * (finish - start):.2f}"
                running += weights[r]
        else:
            # Empty or reversed interval: every line goes to its start, right to
            # within a sentence.
            for r in range(rank, last + 1):
                merged[r] = f"{max(0.0, start):.2f}"
        rank = last + 1
    return merged


def _match(lines: list[str], segments: list[Segment], block: Block | None = None,
           *, whole: bool = False,
           reading: bool = False) -> tuple[list[str], int, int]:
    """The shared work: the moments, and where the search stopped.

    Hands back (moments, cursor, size): the position reached in the glued source
    and its length, whose difference `spoken_lines` reads as sound the text does
    not cover.
    """
    if not lines or not segments:
        return [UNKNOWN] * len(lines or []), 0, 0

    joined, anchors = _landmarks(_covered(segments, block), reading=reading)
    if not joined:
        return [UNKNOWN] * len(lines), 0, 0

    ranges = block.ranges if (block is not None and not whole) else None

    found: list[str] = []
    cursor = 0
    for line in lines:
        # Even a short line ("はい") is looked for: the cursor, not the length,
        # files it in the right place.
        hit = _locate(joined, _target(line, reading=reading), cursor)
        if hit is None:
            found.append(UNKNOWN)
            continue
        position, resume = hit

        moment = _moment_at(position, anchors)
        if moment is None:
            found.append(UNKNOWN)
            continue
        # The cursor moves on a hit only, to the end of what was matched.
        cursor = resume
        if ranges is not None:
            moment = _rebase(moment, ranges)
        found.append(f"{max(0.0, moment):.2f}")
    return found, cursor, len(joined)


def marks(lines: list[str], segments: list[Segment], block: Block | None = None,
          *, whole: bool = False, reading: bool = False,
          log: list[str] | None = None) -> list[str]:
    """One moment per line, `UNKNOWN` only when there is nothing to locate with.

    The three passes of the module docstring, in order. `reading` makes the first
    one compare readings, for a transcription that does not come from the audio
    (`_reading`), and the other comparator rescues. `log`, when given, receives
    where each moment comes from (`EXACT`, `READING`, `PRORATA`, or empty).
    """
    found = _match(lines, segments, block, whole=whole, reading=reading)[0]
    origin = [EXACT if mark != UNKNOWN else "" for mark in found]

    def _note(after: list[str], label: str) -> list[str]:
        for rank, (before, new) in enumerate(zip(found, after)):
            if before == UNKNOWN and new != UNKNOWN:
                origin[rank] = label
        return after

    if UNKNOWN in found:
        backup = _match(lines, segments, block, whole=whole,
                        reading=not reading)[0]
        found = _note(_fill_in(found, backup), READING)

    if UNKNOWN in found:
        bounds = _bounds(segments, block, whole=whole)
        found = _note(_spread(found, lines, bounds, reading=reading), PRORATA)

    if log is not None:
        log[:] = origin
    return found


def for_lines(lines: list[str], segments: list[Segment], block: Block | None,
              *, whole: bool = False, reading: bool = False,
              log: list[str] | None = None) -> str:
    """`Timecodes` field: one moment per line of the transcription, in seconds.

    `segments` is the timestamped source of the whole file, `block` the part this
    card covers; `whole` means the card's audio is the original file, with no
    shift to correct. Empty when nothing is timestamped: the lines are then not
    clickable.
    """
    if not lines or not segments:
        return ""
    found = marks(lines, segments, block, whole=whole, reading=reading, log=log)
    # Nothing found: empty rather than a row of dashes.
    if all(mark == UNKNOWN for mark in found):
        return ""
    return " ".join(found)


def spoken_lines(lines: list[str], segments: list[Segment], *,
                 reading: bool = False) -> tuple[list[str], list[str]]:
    """Separates the lines the audio speaks from the tail it does not speak.

    A text from elsewhere (an NHK Easy article) may run past its audio, and a
    question on an unheard sentence cannot be answered. Only a tail is dropped,
    a line missed in the middle being a word Whisper misheard, and only if the
    sound has stopped too (`SUSPECT_TAIL`): otherwise the matching failed and the
    text stays whole. Nothing found leaves no spoken line: the audio is not this
    text's.
    """
    found, cursor, size = _match(lines, segments, reading=reading)
    end = len(lines)
    while end and found[end - 1] == UNKNOWN:
        end -= 1
    silent = list(lines[end:])
    missing = sum(len(_target(line, reading=reading)) for line in silent)
    if end and (size - cursor) * SUSPECT_TAIL >= missing:
        return list(lines), []
    return list(lines[:end]), silent
