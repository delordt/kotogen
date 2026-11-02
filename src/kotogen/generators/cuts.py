"""Where a passage's sound starts and ends: the silences ffmpeg measures, the cut laid in them."""

from __future__ import annotations

import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from kotogen import console, system
from kotogen.i18n import _

if TYPE_CHECKING:
    # Named in the annotations only: audio_split imports this module, and an
    # import the other way would be a cycle.
    from kotogen.generators.audio_split import Segment, Word

# ── Settings ──────────────────────────────────────────────────────────────────

# Silence detection threshold: -35 dB lets the breath of a textbook recording
# through without taking it for silence; 0.35 s is the shortest pause between
# two lines.
SILENCE_DB = -35
SILENCE_MIN = 0.35

# Past this, a silence is a possible boundary rather than a breath, and is given
# to the model as a hint.
BOUNDARY_MIN = 0.8

# Placement of the cut, in seconds: lined up inside the detected silence, as a
# fixed margin either clips the first mora or lets the end of the bell in.
EDGE_MARGIN = 0.05        # never flush with the edge of the silence (encoding rounding)
ATTACK_MARGIN = 0.15      # blank left before the attack of the speech
TAIL_MARGIN = 0.30        # trail left after the last syllable
NO_SILENCE_MARGIN = 0.12  # fallback when no silence was found
SILENCE_WINDOW = 2.0      # beyond that, the silence is too far to be the right one

# The same fallback when the bounds come from a subtitle rather than Whisper: a
# cue is laid by hand and commonly two tenths out, which 0.12 s cannot absorb
# where no silence makes it up (opening credits, closing music).
NO_WORDS_MARGIN = 0.30

# Maximum duration of a spoken announcement (「第三問」 fits in a second). Past
# it, what was taken for a number is a sentence, and skipping it would clip the
# start of the conversation.
ANNOUNCEMENT_MAX = 1.2

_PUNCTUATION = re.compile(r"[\s、。，．,\.？?！!「」『』（）\(\)・…ー]+")
_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?[\d.]+)")


# ── Real silences (ffmpeg) ────────────────────────────────────────────────────

def detect_silences(audio_path: Path) -> list[tuple[float, float]]:
    """Silence intervals of the file, through `silencedetect`.

    An empty list rather than a failure: the cuts are then laid on the word
    timestamps with a fixed margin, less clean but not broken.
    """
    if shutil.which("ffmpeg") is None:
        console.failed(_("ffmpeg not found: less precise cuts ({hint}).").format(
            hint=system.ffmpeg_hint()))
        return []
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(audio_path),
           "-af", f"silencedetect=noise={SILENCE_DB}dB:d={SILENCE_MIN}", "-f", "null", "-"]
    try:
        output = subprocess.run(cmd, capture_output=True, timeout=600).stderr
    except (subprocess.SubprocessError, OSError) as exc:
        console.failed(_("cannot detect the silences ({error}): less precise "
                         "cuts.").format(error=exc))
        return []

    silences: list[tuple[float, float]] = []
    start: float | None = None
    for line in output.decode("utf-8", "replace").splitlines():
        if (m := _SILENCE_START_RE.search(line)):
            start = max(0.0, float(m.group(1)))
        elif (m := _SILENCE_END_RE.search(line)) and start is not None:
            silences.append((start, float(m.group(1))))
            start = None
    if start is not None:
        # The file ends on a silence ffmpeg never closes. An infinite end is
        # right: the cut bounds the trail to TAIL_MARGIN either way.
        silences.append((start, math.inf))
    return silences


# ── Placement of the cut ──────────────────────────────────────────────────────

# A silence enclosing the moment is the ordinary case, Whisper stretching a bound
# into the blank after it; one starting after the moment could lie past the next
# announcement. So a silence is kept by where it crosses the moment, or its edge.

def _silence_before(moment: float, silences: list[tuple[float, float]]):
    """The usable silence closest before the moment, within the window."""
    kept = None
    for s0, s1 in silences:
        arrival = min(s1, moment)
        if s0 + EDGE_MARGIN < moment + 0.01 and moment - arrival <= SILENCE_WINDOW:
            if kept is None or arrival > min(kept[1], moment):
                kept = (s0, s1)
    return kept


def _silence_after(moment: float, silences: list[tuple[float, float]]):
    """The usable silence closest after the moment, within the window."""
    kept = None
    for s0, s1 in silences:
        departure = max(s0, moment)
        if s1 - EDGE_MARGIN > moment - 0.01 and departure - moment <= SILENCE_WINDOW:
            if kept is None or departure < max(kept[0], moment):
                kept = (s0, s1)
    return kept


def _silence_around(moment: float, silences: list[tuple[float, float]]):
    """The silence this moment falls into, when there is one.

    Same tolerance as `_sounding_range`: a bound on the edge counts as inside,
    whatever the encoding rounding.
    """
    for s0, s1 in silences:
        if s0 - 0.01 <= moment <= s1 + 0.01:
            return (s0, s1)
    return None


def _spoken_end(segment: Segment, silences: list[tuple[float, float]] = ()) -> float:
    """End of the last speech of the segment, rather than its declared bound.

    Whisper often closes a segment on the silence after it, while its word
    timestamps stick to the speech. A subtitle has none, and its bound is when
    the cue disappears: one fallen in a silence comes back to its start, unless
    that eats the whole segment (a badly timed cue, whose bound stays).
    """
    if segment.words:
        return segment.words[-1].end
    silence = _silence_around(segment.end, silences)
    if silence is None or silence[0] <= segment.start:
        return segment.end
    return silence[0]


def _spoken_start(segment: Segment, silences: list[tuple[float, float]] = ()) -> float:
    """Start of the first speech of the segment. Symmetrical to `_spoken_end`.

    A cue is often displayed before the sentence is spoken: a bound in the
    silence before it moves to that silence's end.
    """
    if segment.words:
        return segment.words[0].start
    silence = _silence_around(segment.start, silences)
    if silence is None or silence[1] >= segment.end:
        return segment.start
    return silence[1]


def _margin(segment: Segment) -> float:
    """Blank left around the cut when no silence was found."""
    return NO_SILENCE_MARGIN if segment.words else NO_WORDS_MARGIN


def _range_before(moment: float, silences: list[tuple[float, float]]):
    """The range of sound ending at this moment (the start of a silence)."""
    start = 0.0
    for _s0, s1 in silences:
        if s1 <= moment - 0.01:
            start = max(start, s1)
    return (start, moment)


def _announcement_end(announcement: Segment, silences: list[tuple[float, float]]) -> float:
    """Real end of the announcement, when Whisper places it in the speech after it.

    The floor of the cut lines up on it, so a bound inside the conversation
    would skip its first words. It moves back only on proof: the bound sits in a
    sound too long to be an announcement, and a brief sound precedes the silence
    before that one; else the announcement may be welded to the speech.
    """
    declared = _spoken_end(announcement, silences)
    around = _sounding_range(declared, silences)
    if around is None:
        return declared                    # inside the silence: the bound holds
    sound_start, sound_end = around
    if math.isinf(sound_end) or sound_end - sound_start <= ANNOUNCEMENT_MAX:
        return declared                    # that range IS the announcement
    silence = next((s for s in silences if abs(s[1] - sound_start) < 0.01), None)
    if silence is None:
        return declared
    a0, a1 = _range_before(silence[0], silences)
    if a1 - a0 > ANNOUNCEMENT_MAX:
        return declared                    # no brief announcement to find again
    return a1


def bound_before(speech: float, opens: Segment, segments: list[Segment],
                 rank: int, floor: float,
                 silences: list[tuple[float, float]] = ()) -> float:
    """Below what the cut must never go back up.

    Lining up on the silence is not enough: when a blank too short for
    `silencedetect` follows the number, the nearest silence lies before it. The
    bound is what was left out on purpose: the end of the previous line, and of
    the last word of this line ending before the attack, which it never passes.
    """
    bound = floor
    if rank > 1:
        bound = max(bound, _announcement_end(segments[rank - 2], silences))
    for word in opens.words:
        # `word.start < speech` as well: a zero-length word, which Whisper makes
        # when it laid a boundary too late, "finishes before the attack" while
        # upstream of nothing, and would pull the floor onto the attack itself.
        if word.start < speech - 0.01 and word.end <= speech + 0.01:
            bound = max(bound, word.end)
    return min(bound, speech)


def bound_after(speech: float, closes: Segment, segments: list[Segment],
                rank: int, ceiling: float,
                silences: list[tuple[float, float]] = ()) -> float:
    """Beyond what the cut must never go down.

    Symmetrical to `bound_before`, against the number of the NEXT passage: the
    start of the next line, and of the first word of this line that begins after
    the fade, which it never goes below. `silences` only serves lines with no
    words, whose declared bound is not a speech bound (see `_spoken_start`).
    """
    bound = ceiling
    if rank < len(segments):
        bound = min(bound, _spoken_start(segments[rank], silences))
    for word in closes.words:
        if word.start >= speech - 0.01:
            bound = min(bound, word.start)
    return max(bound, speech)


def _sounding_range(moment: float, silences: list[tuple[float, float]]):
    """The range of sound around the moment, or None when it falls in a silence.

    Bounded by the detected silences, hence by the signal and not by Whisper.
    """
    start, end = 0.0, math.inf
    for s0, s1 in silences:
        if s0 - 0.01 <= moment <= s1 + 0.01:
            return None
        if s1 <= moment:
            start = max(start, s1)
        elif s0 >= moment:
            end = min(end, s0)
    return (start, end)


def _clear_of_announcement(cut: float, silences: list[tuple[float, float]]) -> float:
    """Pushes back a cut that fell in the middle of the announced number.

    The opening cut is capped by the declared end of the announcement, which
    Whisper often lays inside the figure. A cut in a range of sound short enough
    to be only an announcement moves to the silence after it; the margin is wide
    (0.6 s isolated against 3.7 s welded to speech, on the case measured), and
    past it nothing moves: better a slightly short start than a line swallowed.
    """
    around = _sounding_range(cut, silences)
    if around is None:
        return cut                       # already in the silence: nothing to fix
    sound_start, sound_end = around
    if math.isinf(sound_end) or sound_end - sound_start > ANNOUNCEMENT_MAX:
        return cut
    following = next((s for s in silences if abs(s[0] - sound_end) < 0.01), None)
    if following is None:
        return cut
    s0, s1 = following
    after = s0 + EDGE_MARGIN if math.isinf(s1) else max(s0 + EDGE_MARGIN, s1 - ATTACK_MARGIN)
    return max(cut, after)


def cut_start(speech: float, silences: list[tuple[float, float]],
                floor: float = 0.0,
                margin: float = NO_SILENCE_MARGIN) -> float:
    """Where to open the piece, knowing that the speech attacks at `speech`.

    Inside the silence before it and never below `floor` (see `bound_before`):
    the pair keeps out the bell, the number and the end of the previous passage.
    `margin` is the fallback when no silence was found, wider before a subtitle
    bound than before a word timestamp.
    """
    found = _silence_before(speech, silences)
    if found:
        s0, s1 = found
        cut = max(s0 + EDGE_MARGIN, min(s1, speech) - ATTACK_MARGIN)
    else:
        cut = speech - margin
    return _clear_of_announcement(max(0.0, floor, min(cut, speech)), silences)


def cut_end(speech: float, silences: list[tuple[float, float]],
            ceiling: float = math.inf,
            margin: float = NO_SILENCE_MARGIN) -> float:
    """Where to close the piece, knowing that the speech fades at `speech`.

    Symmetrical to `cut_start`: the cut stays in the silence after it, hence
    below the sound that follows (the announcement of the next passage, the bell).
    """
    found = _silence_after(speech, silences)
    if found:
        s0, s1 = found
        cut = min(s1 - EDGE_MARGIN, max(s0, speech) + TAIL_MARGIN)
    else:
        cut = speech + margin
    return min(ceiling, max(cut, speech))


# ── Finding a word again inside a segment ─────────────────────────────────────

def without_punctuation(text: str) -> str:
    return _PUNCTUATION.sub("", text)


def word_moment(segment: Segment, word: str, *, end: bool = False) -> float | None:
    """Timestamp of the word `word` inside the segment, or None when it is absent.

    For the number glued to the first line (`4 あっそれ`), where the cut falls
    inside the segment. Whisper's split into words is arbitrary in Japanese and
    the model hands back what it reads, so the words are joined, the text looked
    up in the string, and its position mapped back to the word covering it.
    """
    target = without_punctuation(word or "")
    if not target or not segment.words:
        return None

    joined = ""
    bounds: list[tuple[int, int, Word]] = []
    for m in segment.words:
        clean = without_punctuation(m.text)
        bounds.append((len(joined), len(joined) + len(clean), m))
        joined += clean

    position = joined.rfind(target) if end else joined.find(target)
    if position < 0:
        return None
    if end:
        position += len(target) - 1
    for start, stop, m in bounds:
        if start <= position < stop:
            return m.end if end else m.start
    return None
