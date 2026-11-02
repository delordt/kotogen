"""Hearing a listening card again: what the sound says, against what the card says.

That catches an extract cut mid-sentence, a transcript that differs from the
audio, and `Timecodes` that drifted. This module reads the card (its medium, the
bounds its `Source` gives), lays the extract on whole sentences again (`recut`)
and asks the model for the transcript (`ask_transcript`);
`kotogen.anki.maintain.listening` finds the recording, hears it, cuts the new
extract and puts it into the deck.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from kotogen import prompts
from kotogen.ai_client import AIClient
from kotogen.exporter import safe_text
from kotogen.generators import audio_split, cuts, key_line
from kotogen.generators.audio_split import Block, Segment
from kotogen.i18n import _
from kotogen.maintenance.kinds import LISTENING
from kotogen.maintenance.review import _field, _laid_out, _line_pass, field_lines

# `Source` keeps the bounds as `(01:12 → 01:47)` (see `sources.provenance`).
_BOUNDS_RE = re.compile(r"\((\d+(?::\d{2}){1,2}) → (\d+(?::\d{2}){1,2})\)")

# An extract is named `<readable>_<rank>_<fingerprint><suffix>`; a file taken
# whole, `<readable>_<fingerprint><suffix>` (see `generators.audio`).
_EXTRACT_RE = re.compile(r"^(?P<readable>.+)_(?P<rank>\d{2})_[0-9a-f]{8}$")
_WHOLE_RE = re.compile(r"^(?P<readable>.+)_[0-9a-f]{8}$")
_SRC_RE = re.compile(r'src="([^"]+)"')


def _seconds(clock: str) -> float:
    total = 0.0
    for part in clock.split(":"):
        total = total * 60 + int(part)
    return total


def bounds_of(source: str) -> tuple[float, float] | None:
    """The bounds `Source` gives the extract in its recording, or None."""
    found = _BOUNDS_RE.findall(source)
    if not found:
        return None
    start, end = found[-1]
    return _seconds(start), _seconds(end)


def with_bounds(source: str, start: float, end: float) -> str:
    """`Source` with new bounds, the rest of it as it was."""
    new = f"({audio_split.timestamp(start)} → {audio_split.timestamp(end)})"
    found = list(_BOUNDS_RE.finditer(source))
    if not found:
        return source
    last = found[-1]
    return source[:last.start()] + new + source[last.end():]


@dataclass
class Media:
    """The medium a listening card plays, as its field carries it."""

    field: str          # Audio or Video
    name: str           # the file in Anki's media library
    readable: str = ""  # the readable name of the recording it was cut from
    rank: str = ""      # its rank in that recording, "" for a file taken whole

    @property
    def video(self) -> bool:
        return self.field == "Video"


def media_of(note: dict) -> Media | None:
    """The medium of the card, and what its name says of its recording."""
    for name in ("Video", "Audio"):
        found = _SRC_RE.search(_field(note, name))
        if found:
            media = Media(name, found.group(1))
            stem = Path(media.name).stem
            extract = _EXTRACT_RE.match(stem)
            whole = None if extract else _WHOLE_RE.match(stem)
            if extract:
                media.readable, media.rank = extract["readable"], extract["rank"]
            elif whole:
                media.readable = whole["readable"]
            return media
    return None


# ── Hearing again ─────────────────────────────────────────────────────────────

@dataclass
class Heard:
    """What Whisper heard, and where the extract sits in it."""

    audio: Path                 # the sound heard, the window or the extract itself
    offset: float               # where that sound starts in the recording
    sound: Path | None          # the track the window was cut from, None without one
    segments: list[Segment]
    block: Block | None         # the extract in `segments`, None when heard as it stands
    moved: bool = False         # the bounds changed

    @property
    def lines(self) -> list[str]:
        if self.block is None:
            return [s.text for s in self.segments]
        return self.block.texts(self.segments)


def recut(segments: list[Segment], start: float, end: float,
          silences: list[tuple[float, float]]) -> Block | None:
    """The extract laid again on whole sentences, in the window's time.

    `start` and `end` are the old bounds; a sentence they cut through is taken
    whole. The cuts go in the silence before the first sentence and after the
    last, as the split lays them (see `cuts.bound_before`).
    """
    heard = [i for i, s in enumerate(segments)
             if s.end > start + 0.3 and s.start < end - 0.3 and s.text.strip()]
    if not heard:
        return None
    first, last = heard[0], heard[-1]
    opening, closing = segments[first], segments[last]
    entry = (opening.words[0].start if opening.words
             else cuts._spoken_start(opening, silences))
    exit_at = (closing.words[-1].end if closing.words
               else cuts._spoken_end(closing, silences))
    cut_in = cuts.cut_start(
        entry, silences,
        cuts.bound_before(entry, opening, segments, first + 1, 0.0, silences),
        cuts._margin(opening))
    cut_out = cuts.cut_end(
        exit_at, silences,
        cuts.bound_after(exit_at, closing, segments, last + 1, math.inf, silences),
        cuts._margin(closing))
    if cut_out <= cut_in:
        return None
    return Block(tuple(range(first + 1, last + 2)), ((cut_in, cut_out),))


# ── What the model writes of it ───────────────────────────────────────────────

@dataclass
class Rewrite:
    """The transcript of the extract heard again, and what follows from it."""

    transcript: list[str]
    translation: list[str]
    key_lines: dict[int, str]   # question number -> key line ("" when none)
    lost: list[int]
    reason: str = ""
    refused: list[str] = field(default_factory=list)


def _numbered(lines: list[str]) -> list[str]:
    return [f"{i}. {line}" for i, line in enumerate(lines, 1)]


def ask_transcript(client: AIClient, heard: Heard, questions: list[dict]) -> Rewrite | None:
    """The transcript of what is heard; None when the model says it is right."""
    card = questions[0]
    lines = [_laid_out("Heard", "").rstrip(), *_numbered(heard.lines), "",
             _laid_out("Transcript", "").rstrip(),
             *_numbered(field_lines(_field(card, "Transcript"))), "",
             _laid_out("Translation", "").rstrip(),
             *_numbered(field_lines(_field(card, "Translation"))), "",
             prompts.say("Questions:")]
    for i, question in enumerate(questions, 1):
        lines.append(f"{i}. " + " | ".join(
            _laid_out(name, _field(question, name))
            for name in ("Question", "Answer", "KeyLine")))
    result = client.chat_json(prompts.load("maintain_audio_transcript"), "\n".join(lines))
    if not isinstance(result, dict):
        raise ValueError(_("unexpected AI answer: {kind}").format(kind=type(result)))
    if result.get("changed") is False:
        return None
    # Display-only text with the readings of the export, as every field a model
    # writes (`review._line_pass`).
    transcript = [safe_text(str(line).strip(), _line_pass("Transcript", LISTENING))
                  for line in result.get("TranscriptLines") or [] if str(line).strip()]
    translation = [safe_text(str(line).strip(), _line_pass("Translation", LISTENING))
                   for line in result.get("TranslationLines") or [] if str(line).strip()]
    raw_keys = result.get("KeyLines") if isinstance(result.get("KeyLines"), dict) else {}
    keys = {n: key_line.rank(raw_keys.get(str(n), raw_keys.get(n)), len(transcript))
            for n in range(1, len(questions) + 1)}
    lost = []
    for n in result.get("lost") or []:
        try:
            if 1 <= int(n) <= len(questions):
                lost.append(int(n))
        except (TypeError, ValueError):
            continue
    rewrite = Rewrite(transcript, translation, keys, lost,
                      str(result.get("reason", "")).strip())
    if not transcript:
        rewrite.refused.append(_("no transcript handed back"))
    elif len(translation) != len(transcript):
        rewrite.refused.append(_("translation not lined up ({given} lines vs "
                                 "{expected}).").format(given=len(translation),
                                                        expected=len(transcript)))
    return rewrite


def same_instants(new: str, old: str, tolerance: float = 0.5) -> bool:
    """Whether two `Timecodes` fields land on the same seconds.

    Within `tolerance`, as Whisper never times a word twice alike to the
    hundredth. An unknown instant (`-`) only matches another unknown one.
    """
    if not new:
        return True   # nothing timed: the field there stays as good as anything
    a, b = new.split(), old.split()
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        try:
            if abs(float(x) - float(y)) > tolerance:
                return False
        except ValueError:
            if x != y:
                return False
    return True
