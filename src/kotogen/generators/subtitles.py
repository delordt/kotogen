"""The subtitle sitting next to the medium: a transcription already made, and right.

A transcription found beside a file replaces Whisper: it is free, more faithful,
and timed by hand. SRT and WebVTT are read alike, a cue being whatever holds
"-->"; of an ASS file only the dialogue is kept (`_read_ass`), here and when
`text_source` reads a subtitle as a text. A subtitle has no per-word timestamps
and its cue bounds are not speech bounds: `cuts` realigns them on the
measured silences (`_spoken_start`, `_spoken_end`). A track that is not in
Japanese is ignored, a video file usually coming with its translation instead.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

from kotogen.furigana import KANA_RE
from kotogen.generators.audio_split import Segment
from kotogen.generators.text_source import decode

# The dialects read, in the order tried under one same mark: `.srt` is the most
# common and holds only what is said, where an `.ass` must be sorted first.
EXTENSIONS = (".srt", ".vtt", ".ass", ".ssa")

# Advanced SubStation Alpha, the dialect of the fansubs, and `.ssa`, the older
# format it grew out of: a document in sections rather than a list of cues.
ASS_EXTENSIONS = (".ass", ".ssa")

# Language marks in the name (`ep.ja.srt`, yt-dlp's `ja-orig`, `japonais`): a
# clue to try a file first, the text alone deciding.
JA_MARKS = ("ja", "jpn", "jp", "ja-jp", "ja-orig", "japanese", "japonais")

# Share of the lines carrying kana for a track to count as Japanese: kana, as
# Chinese shares the ideographs; a share, as an English track carries a few
# Japanese lines (a sign, a song). A bilingual file is split by style first.
MIN_JAPANESE_SHARE = 0.5

# Why a subtitle next to the medium was turned down. Plain English, translated
# where shown: a module-level `_()` would resolve the language at import time.
UNREADABLE = "unreadable"
NOT_JAPANESE = "not in Japanese"

# Bounds of a cue: `00:00:12,340 --> 00:00:15,900` in SRT, with a full stop and
# an optional hour on top in WebVTT (`00:12.340 --> 00:15.900`).
_BOUNDS_RE = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})"
    r"\s*-->\s*"
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})")

# Inline tags: `<i>`, `<b>`, and the `<v Name>` of WebVTT. The speaker name is
# dropped: the card prompt accepts a name only if it is heard in the audio.
_TAG_RE = re.compile(r"<[^>]*>")

# ASS legacy found again in converted SRTs: `{\an8}`, `{\pos(…)}`.
_BRACE_RE = re.compile(r"\{\\[^}]*\}")

# An empty block separates two cues. Windows files arrive in CRLF, and some
# extractors leave spaces on the "empty" line.
_SEPARATOR_RE = re.compile(r"\n[ \t]*\n")

# ASS: the standard fields of an event, used when `[Events]` has no `Format:`
# line (the order varies: `.ssa` writes `Marked` for `Layer`). `Text` is always
# last, being the one field that may hold a comma.
_ASS_FIELDS = ("layer", "start", "end", "style", "name",
               "marginl", "marginr", "marginv", "effect", "text")

# An instant of ASS: `0:01:23.45`, the hour on one digit and the fraction in
# hundredths.
_ASS_TIME_RE = re.compile(r"(\d+):(\d{1,2}):(\d{2})[.,](\d{1,3})")

# Everything between braces is for the renderer: an override (`{\an8}`, `{\k40}`)
# or a typesetter's comment. Wider than `_BRACE_RE`, made for SRT leftovers.
_ASS_BLOCK_RE = re.compile(r"\{[^}]*\}")

# The escapes of the text: `\N` the line break the author chose, `\n` the one
# the renderer may take, `\h` a space that does not break. A cue broken over
# two lines is one cue, as in an SRT.
_ASS_ESCAPE_RE = re.compile(r"\\[Nnh]")

# What makes an ASS line unsaid, whatever its style: a karaoke timing (`\k`,
# `\kf`, `\ko`, `\K`) or a drawing (`\p1`), whose "text" is a shape's outline.
_ASS_UNSAID_RE = re.compile(r"\{[^}]*\\(?:[kK][fo]?\d|p[1-9])")

# Words of a style name that say its lines are written rather than said (signs,
# songs, credits, translator notes, the `Rubi` readings of a TV caption), matched
# on the words of the name (`SignTop`, `ED_JP`), and their Japanese.
_WRITTEN_STYLE_WORDS = frozenset({
    "sign", "signs", "ts", "typeset", "typesetting", "title", "titles",
    "op", "ed", "song", "songs", "insert", "lyric", "lyrics", "kara", "karaoke",
    "romaji", "credit", "credits", "staff", "note", "notes", "tl", "rubi", "ruby",
    "eyecatch", "logo"})
_WRITTEN_STYLE_JA = ("看板", "タイトル", "歌", "ルビ", "注", "クレジット", "スタッフ")

# The words of a style name: `SignTop` -> Sign, Top; `OPRomaji` -> OP, Romaji.
_STYLE_WORD_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


@dataclass(frozen=True)
class Track:
    """What was found next to the medium.

    Empty `segments` is the ordinary case, not a failure: the caller transcribes.
    `rejected` holds the subtitles turned down, with their reason, to be said
    before Whisper starts.
    """

    segments: tuple[Segment, ...] = ()
    path: Path | None = None
    rejected: tuple[tuple[Path, str], ...] = ()


# ── Reading a file ────────────────────────────────────────────────────────────

def _seconds(hours: str | None, minutes: str, seconds: str, fraction: str) -> float:
    """An instant in seconds, from the groups of the bounds pattern.

    The fraction is padded to three digits: `,3` is three tenths, not three
    thousandths.
    """
    return (int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)
            + int(fraction.ljust(3, "0")) / 1000)


def _clean(text: str) -> str:
    """The text of a cue, rid of what is not what is said."""
    text = _BRACE_RE.sub("", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    return " ".join(text.split())


def _block_to_segment(block: str) -> Segment | None:
    """One block of a subtitle file as a segment, or None if it is not one.

    A cue is a block with a bounds line, whatever stands above it (a number, an
    identifier); the text is below. Header, `NOTE` and style blocks have none.
    """
    lines = block.split("\n")
    # `rank` is read after the loop, at the line the break leaves it on.
    for rank, line in enumerate(lines):  # noqa: B007
        bounds = _BOUNDS_RE.search(line)
        if bounds:
            break
    else:
        return None

    text = _clean(" ".join(lines[rank + 1:]))
    if not text:
        return None

    start = _seconds(*bounds.group(1, 2, 3, 4))
    end = _seconds(*bounds.group(5, 6, 7, 8))
    # Hand-retimed files may end a cue before its start: its text is kept, with a
    # zero duration rather than a negative one.
    return Segment(text, start, max(start, end))


def _written_style(style: str) -> bool:
    """Does the name of this style say its lines are written, not said?"""
    words = {word.lower() for word in _STYLE_WORD_RE.findall(style)}
    return (bool(words & _WRITTEN_STYLE_WORDS)
            or any(word in style for word in _WRITTEN_STYLE_JA))


def _ass_event(value: str, fields: tuple[str, ...]) -> tuple[str, Segment] | None:
    """One `Dialogue:` line of an ASS file as (style, segment), or None if it
    is not something said.

    The `Name` field is dropped, like the `<v Name>` of WebVTT (`_TAG_RE`).
    """
    parts = value.split(",", len(fields) - 1)
    if len(parts) < len(fields):
        return None
    event = dict(zip(fields, parts))
    style = event.get("style", "").strip()
    text = event.get("text", "")
    # `Effect` is empty on dialogue; it holds a generated karaoke (`fx`) or a
    # scrolling banner.
    if (event.get("effect", "").strip() or _ASS_UNSAID_RE.search(text)
            or _written_style(style)):
        return None
    start = _ASS_TIME_RE.fullmatch(event.get("start", "").strip())
    end = _ASS_TIME_RE.fullmatch(event.get("end", "").strip())
    if not start or not end:
        return None

    text = _clean(_ASS_ESCAPE_RE.sub(" ", _ASS_BLOCK_RE.sub("", text)))
    if not text:
        return None

    start_s = _seconds(*start.groups())
    return style, Segment(text, start_s, max(start_s, _seconds(*end.groups())))


def _japanese_styles(events: list[tuple[str, Segment]]) -> list[Segment]:
    """The lines of the styles written in Japanese, when a file mixes languages.

    A bilingual release lays each language in its own style at the same instants,
    so the language is judged style by style (`is_japanese`). A file with no
    Japanese style comes back whole, for `is_japanese` to call it "not in
    Japanese" rather than unreadable.
    """
    styles: dict[str, list[Segment]] = {}
    for style, segment in events:
        styles.setdefault(style, []).append(segment)
    japanese = {style for style, lines in styles.items() if is_japanese(lines)}
    return [segment for style, segment in events
            if not japanese or style in japanese]


def _read_ass(raw: str) -> list[Segment]:
    """The dialogue of an ASS or SSA file, in the order it is shown.

    Only the `Dialogue:` lines of `[Events]` are shown. A line is left out when
    its style is named for what is written (`Sign`, `OP`, `Rubi`...), when it
    carries a karaoke or a drawing, or when its `Effect` is filled; then the
    styles not in Japanese. A line placed with `\\pos` is not taken for a sign:
    a TV caption converted to ASS places every line. The events are sorted by
    time, a file sorted by style or merged from two being out of screen order.
    """
    fields = _ASS_FIELDS
    in_events = False
    events = []
    for line in raw.split("\n"):
        line = line.strip()
        if line.startswith("["):
            in_events = line.lower() == "[events]"
            continue
        key, colon, value = line.partition(":")
        if not in_events or not colon:
            continue
        key = key.strip().lower()
        if key == "format":
            fields = tuple(name.strip().lower() for name in value.split(","))
        elif key == "dialogue":
            event = _ass_event(value, fields)
            if event is not None:
                events.append(event)
    # A stable sort: two lines shown at the same instant keep the order of the
    # file, which is the order they are stacked in.
    return sorted(_japanese_styles(events), key=lambda segment: segment.start)


def read(path: Path) -> list[Segment]:
    """Segments of a subtitle file, or [] if it cannot be read.

    Never raises: a subtitle that fails sends the caller back to Whisper.
    """
    try:
        raw = decode(path.read_bytes())
    except OSError:
        return []

    raw = raw.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if path.suffix.lower() in ASS_EXTENSIONS:
        cues = _read_ass(raw)
    else:
        blocks = _SEPARATOR_RE.split(raw)
        cues = [cue for cue in map(_block_to_segment, blocks) if cue is not None]

    segments: list[Segment] = []
    previous = ""
    for segment in cues:
        # Two consecutive cues with the same text come from "rolling" subtitles
        # or from an ASS line drawn on two layers (outline, fill): said once.
        if segment.text == previous:
            continue
        segments.append(segment)
        previous = segment.text
    return segments


def is_japanese(segments: list[Segment]) -> bool:
    """Does the track carry Japanese, and not its translation?"""
    if not segments:
        return False
    japanese = sum(1 for s in segments if KANA_RE.search(s.text))
    return japanese / len(segments) >= MIN_JAPANESE_SHARE


# ── The file laid next to the medium ──────────────────────────────────────────

def _mark(path: Path, stem: str) -> str:
    """What the subtitle name adds to the medium's: "ja", "en", ""."""
    return path.stem[len(stem):].strip(".").lower()


def companions(medium: Path) -> list[Path]:
    """The subtitles bearing the name of this medium, the Japanese ones first.

    The exact name (`episode.srt`) or the name and a mark (`episode.ja.srt`),
    never a bare prefix: `ep1.srt` is not the subtitle of `ep10.mkv`. The order
    (Japanese mark, bare name, the rest, then `EXTENSIONS`) only saves reading
    files: the text decides.
    """
    stem = medium.stem.lower()
    try:
        neighbours = sorted(medium.parent.iterdir())
    except OSError:
        return []

    found = []
    for path in neighbours:
        suffix = path.suffix.lower()
        if suffix not in EXTENSIONS:
            continue
        name = path.stem.lower()
        if name != stem and not name.startswith(stem + "."):
            continue
        mark = _mark(path, stem)
        rank = 0 if mark in JA_MARKS else (1 if not mark else 2)
        found.append((rank, EXTENSIONS.index(suffix), path.name.lower(), path))
    return [path for *_, path in sorted(found)]


def load(medium: Path) -> Track:
    """The first Japanese subtitle laid next to the medium, if there is one.

    The files turned down come back with their reason, for the caller to say why
    it transcribes anyway.
    """
    rejected: list[tuple[Path, str]] = []
    for path in companions(medium):
        segments = read(path)
        if not segments:
            rejected.append((path, UNREADABLE))
            continue
        if not is_japanese(segments):
            rejected.append((path, NOT_JAPANESE))
            continue
        return Track(tuple(segments), path, tuple(rejected))
    return Track((), None, tuple(rejected))
