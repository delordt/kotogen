"""Keeping the picture of a video source, and at what price.

A video source makes an audio card by default. The `KOTOGEN_VIDEO` mode ("ask",
"always", "never") can keep its picture, and `--video` / `--no-video` win over
it. "ask" asks once per run, only when an input has a picture, and before any
download, since the answer decides what is pulled; with nobody at the terminal
the answer is sound only.

The extract is always re-encoded, since `.mkv` and `.avi` play in no WebView,
to a single 480p profile at the source's frame rate (fewer frames show as
jerkiness). Its size is bounded by duration rather than bitrate: past
`MAX_SECONDS` the passage falls back to sound only, without a word.

VP9 and Opus in WebM, not H.264 in MP4: Anki's Qt WebEngine is built without
the proprietary codecs and cannot open H.264, while VP9 and Opus play in every
Chromium build and in Android's WebView. `tests/codec_bench.py` puts its check
card into Anki to measure it again.
"""

from __future__ import annotations

from kotogen import console, settings
from kotogen.i18n import _

ENV_VAR = "KOTOGEN_VIDEO"

# The media produced (see the module docstring). VP9's CRF scale goes up to 63:
# 34 there is about x264's 30, for a file a good third smaller.
SUFFIX = ".webm"
HEIGHT = 480
CRF = "34"
AUDIO_BITRATE = "96k"

# Beyond this the passage goes back to sound only: ninety seconds is a long
# listening item, and anything longer is an episode, not for a synced media library.
MAX_SECONDS = 90

# `-2`: yuv420p needs an even width, and an odd one fails the encoding.
# `min(...,ih)` never enlarges a smaller source. The quotes belong to the filter
# graph, not the shell: they keep the comma from separating two filters.
SCALE = f"scale=-2:'min({HEIGHT},ih)'"

# In the order the "i" key of the settings cycles through them, the default first.
MODES = ("ask", "always", "never")

DEFAULT_MODE = MODES[0]

# The yes/no spellings one types from memory, read as the two fixed modes.
_SYNONYMS = {"1": "always", "true": "always", "yes": "always", "on": "always",
             "0": "never", "false": "never", "no": "never", "off": "never"}

# None: nothing chosen this session, the setting decides.
_mode: str | None = None


def by_mode(value: str) -> str:
    """The mode of that name, or the default if the name matches none.

    Never an error, as in `audio_quality.by_code`: a stale setting must not stop
    the command.
    """
    wanted = (value or "").strip().lower()
    if wanted in MODES:
        return wanted
    return _SYNONYMS.get(wanted, DEFAULT_MODE)


def mode() -> str:
    """The mode in force: the session's, failing that the settings'."""
    if _mode is not None:
        return _mode
    return by_mode(settings.raw(ENV_VAR))


def set_mode(value: str) -> None:
    """Fix the mode for the current session, without rewriting the settings."""
    global _mode
    _mode = by_mode(value)


def cycle() -> str:
    """Move to the next mode, wrapping to the first after the last.

    Cycled like the notches of `audio_quality`: three values are not worth a
    selection screen.
    """
    following = MODES[(MODES.index(mode()) + 1) % len(MODES)]
    set_mode(following)
    return following


def describe() -> str:
    """What the settings screen shows facing the setting.

    The mode's word alone, like the compression notch above it: the label
    already says what it is about ("Video picture  ask").
    """
    return _(mode())


def resolve(args, *, in_play: bool = False) -> bool:
    """Whether this run keeps the picture: the flag, the setting, or the question.

    The flag is None when not given (and absent outside `audio`). `in_play`
    says whether any input has a picture, which the caller knows once its
    inputs are sorted (see `audio.run_audio`); without one, nothing is asked.
    """
    asked = getattr(args, "video", None)
    if asked is not None:
        return bool(asked)
    current = mode()
    if current != "ask":
        return current == "always"
    return _ask() if in_play else False


def _ask() -> bool:
    """Put the question, once, and return the answer.

    Sound only comes LAST: it is what `ask_choice` returns when nobody can
    answer. The import is local: `exporter` is heavy and this module loads with
    the CLI.
    """
    from kotogen.exporter import ask_choice

    console.space()
    return ask_choice(_("Keep the picture of the video: [p] yes  [s] sound only"),
                      "ps") == "p"


def encoder_args() -> list[str]:
    """ffmpeg output arguments for a video extract.

    `-b:v 0` is what puts libvpx in constant quality: without it the CRF is only
    a ceiling under a 256k default, and the picture silently turns to mush.
    `-cpu-used 4` with `-row-mt` buys speed short of a visible loss. A WebM
    streams as is, with no `+faststart`.
    """
    return [
        "-c:v", "libvpx-vp9", "-crf", CRF, "-b:v", "0",
        "-cpu-used", "4", "-row-mt", "1", "-pix_fmt", "yuv420p",
        # Mono, like the audio notches: a voice has no stereo to lose.
        "-c:a", "libopus", "-b:a", AUDIO_BITRATE, "-ac", "1",
    ]
