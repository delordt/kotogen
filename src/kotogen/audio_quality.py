"""Compressing downloaded audio: none by default, three notches below.

NHK Easy already serves compressed audio (AAC around 64k), so by default the
stream is copied as it is (`-c:a copy`): re-encoding would stack a second loss
to save a few hundred kilobytes. A cut passage must be re-encoded (a stream copy
cuts only at frame boundaries, see `nhk.transcode_spans_to_mp3`), and "none"
then means `UNCOMPRESSED_BITRATE`.
"""

from __future__ import annotations

from typing import NamedTuple

from kotogen import settings
from kotogen.i18n import _


class Level(NamedTuple):
    """A notch: its code, its name, what it produces, its bitrate.

    `code` is what is typed (settings file, `--audio-quality`). `label` (settings
    screen) and `detail` (end of a download) are translated where they are
    printed: the tuple is built at import time. A `bitrate` of None means no
    encoding.
    """

    code: str
    label: str
    detail: str
    bitrate: str | None


# From the most faithful to the lightest: the order the "q" key cycles through.
LEVELS = (
    # The names agree with "compression", which the screen label carries just
    # before them: "Audio compression  none".
    Level("none", "none", "original sound", None),
    Level("light", "light", "mono 96k MP3", "96k"),
    Level("medium", "medium", "mono 64k MP3", "64k"),
    Level("strong", "strong", "mono 48k MP3", "48k"),
)

# The labels spell the bitrates out: a notch aims at a bitrate whatever the
# source, and 96k of a 64k stream only makes a bigger file ("none" is the notch
# there). The scale stops at 48k, the lowest still worth offering for a voice.

DEFAULT_CODE = LEVELS[0].code

ENV_VAR = "KOTOGEN_AUDIO_QUALITY"

# The bitrate of "none" when a cut forces a re-encode: inaudible on a source
# around 64k, and a thirty-second extract still weighs only 700 KB.
UNCOMPRESSED_BITRATE = "192k"

# None = no explicit choice for this session, we follow the .env.
_code: str | None = None


def by_code(value: str) -> Level:
    """The notch of that name, or the default if the name matches none.

    Never raises, so a stale setting does not stop a command; the CLI checks
    the name on input.
    """
    for level in LEVELS:
        if level.code == value:
            return level
    return LEVELS[0]


def codes() -> tuple[str, ...]:
    """The accepted names, in display order (for `--audio-quality`)."""
    return tuple(level.code for level in LEVELS)


def code() -> str:
    """The notch in force: the session's, failing that the settings'."""
    if _code is not None:
        return _code
    return by_code(settings.raw(ENV_VAR).lower()).code


def set_code(value: str) -> None:
    """Fix the notch for the current session, without rewriting the settings."""
    global _code
    _code = by_code(value).code


def current() -> Level:
    """The notch in force, in full."""
    return by_code(code())


def cycle() -> Level:
    """Move to the next notch, wrapping to the first after the last.

    A four-position toggle, which spares a selection screen for four lines.
    """
    following = LEVELS[(LEVELS.index(current()) + 1) % len(LEVELS)]
    set_code(following.code)
    return following


def describe() -> str:
    """What the settings screen shows facing the setting: the notch's name alone.

    Looked up under the "compression" context, since French translates "light"
    and "none" differently for a palette or a choice marker (`légère`, `claire`).
    """
    return _(current().label, "compression")


def resolve(args) -> Level:
    """The notch asked for on the command line, failing that the setting's.

    `getattr`: only the `audio` command carries the option, and the NHK
    pipeline also serves commands that do not have it.
    """
    return by_code(getattr(args, "audio_quality", None) or code())


def encoder_args(level: Level, *, copy: bool) -> list[str]:
    """ffmpeg output arguments for this notch.

    `copy` is whether the destination can take the stream as it is: false for a
    cut, or for a source codec with no known container. Only the copy carries
    `-vn`, as an `.m4a` would keep a video track. An MP3 takes no video, only
    cover art, which a cut drops; a whole file needs its own `-vn` (see
    `nhk.extract_audio_track`).
    """
    if level.bitrate is None:
        if copy:
            return ["-vn", "-c:a", "copy"]
        return ["-c:a", "libmp3lame", "-b:a", UNCOMPRESSED_BITRATE]
    # Mono: a voice has no stereo to lose, and it halves the file.
    return ["-ac", "1", "-c:a", "libmp3lame", "-b:a", level.bitrate]
