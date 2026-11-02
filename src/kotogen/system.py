"""What differs from one operating system to the next, gathered in one place.

Where the program's folders are, the user folders XDG declares (`~/Bureau` on a
French Linux), what a terminal is, how a missing tool is installed and how the
clipboard is reached: the rest of the program asks here (`windows()`,
`macos()`) rather than testing the platform. A user folder XDG does not declare
comes back None; `exporter._known_folder` then takes the English name under `~`.
"""

from __future__ import annotations

import os
import secrets
import sys
import time
from pathlib import Path

from kotogen.i18n import _

# -- The platform -------------------------------------------------------------

def windows() -> bool:
    """True on Windows. Read at call time, so that a test can fake `sys.platform`."""
    return sys.platform == "win32"


def macos() -> bool:
    """True on macOS."""
    return sys.platform == "darwin"


def ignore_current_folder() -> None:
    """Keep Windows from running a program of the current folder for a bare name.

    Windows looks there before PATH, so an `ffmpeg.exe` left in the folder
    kotogen is run from would be run in place of the real one.
    """
    if windows():
        os.environ["NoDefaultCurrentDirectoryInExePath"] = "1"


# -- The terminal -------------------------------------------------------------

def terminal(stream) -> bool:
    """True if `stream` is a console someone reads or types in.

    Windows takes the NUL device for a terminal (`isatty` only asks for a
    character device), so there the handle must also answer `GetConsoleMode`.
    A stream with no device behind it (a test's stand-in) is taken at its word.
    """
    try:
        claimed = bool(stream.isatty())
    except (AttributeError, OSError, ValueError):
        return False
    if not claimed or not windows():
        return claimed
    try:
        descriptor = stream.fileno()
    except (AttributeError, OSError, ValueError):
        return True
    if not os.isatty(descriptor):
        return True
    return _console(descriptor)


def _console(descriptor: int) -> bool:
    """True if this Windows descriptor is a console, not another character device."""
    import ctypes
    import msvcrt

    try:
        handle = msvcrt.get_osfhandle(descriptor)
        mode = ctypes.c_ulong()
        return bool(ctypes.windll.kernel32.GetConsoleMode(ctypes.c_void_p(handle),
                                                          ctypes.byref(mode)))
    except (AttributeError, OSError, ValueError):
        return False


def can_ask() -> bool:
    """True if a question can be put and answered: a terminal on both sides."""
    return terminal(sys.stdin) and terminal(sys.stdout)


# -- Files ------------------------------------------------------------------------

# Windows refuses to replace a file another process holds open (OneDrive, an
# indexer, an antivirus), usually for an instant: the replace is tried again.
_REPLACE_TRIES = 5
_REPLACE_PAUSE = 0.1


def _replace(source: Path, target: Path) -> None:
    """`os.replace`, tried again for a while when Windows says the target is busy."""
    for attempt in range(_REPLACE_TRIES):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if not windows() or attempt == _REPLACE_TRIES - 1:
                raise
            time.sleep(_REPLACE_PAUSE * (attempt + 1))


def write_whole(path: Path, text: str, *, private: bool = False,
                durable: bool = False) -> None:
    """Write `path` so that it holds the old content or the new one, never half.

    Through a temporary file of its own in the same folder, `os.replace` being
    atomic only within one file system: two writers never share one. Lines end
    on a bare line feed on every system. `private` creates the file 0600;
    `durable` waits for the disk, for what cannot be typed again (a key).
    Raises OSError when the file stays busy (see `_replace`).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
    # Created with its mode, so that a private file is never readable, even for
    # the instant of the write; binary, so that Windows adds no carriage return.
    descriptor = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                         | getattr(os, "O_BINARY", 0), 0o600 if private else 0o666)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            if durable:
                handle.flush()
                os.fsync(handle.fileno())
        _replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


# -- Program folders ----------------------------------------------------------
# A disk cleaner may empty the cache (OpenRouter catalogue, downloaded PDFs,
# fallback TSVs), which rebuilds itself; never the data, which does not, nor the
# configuration, which was typed by hand.

def cache_dir() -> Path:
    """The program cache folder, at the usual place for this platform.

    What lives here is disposable: wiped, it downloads or recomputes on the next run.
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "kotogen"


def data_dir() -> Path:
    """The program data folder, at the usual place for this platform.

    Deck backups live here, the only copy of a note before it was touched: hence
    `XDG_DATA_HOME` and Application Support rather than a cache folder.
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "kotogen"


def config_dir() -> Path:
    """The program configuration folder, at the usual place for this platform.

    Holds `settings.env` and `secrets.env` when the program was installed rather
    than cloned. `APPDATA` rather than `LOCALAPPDATA` on Windows: settings and
    keys follow a roaming profile, a cache does not.
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "kotogen"


# -- User folders -------------------------------------------------------------
# On Linux the desktop and downloads folders are named in the session language
# and declared in `~/.config/user-dirs.dirs`; guessing `Desktop` would make a
# second folder beside the real one. A declaration reads:
#
#     XDG_DESKTOP_DIR="$HOME/Bureau"

def _expand(raw: str) -> Path:
    """The path of an XDG declaration: `$HOME` expanded, relative path rejoined."""
    path = Path(os.path.expandvars(raw)).expanduser()
    return path if path.is_absolute() else Path.home() / path


def xdg_user_dir(var: str) -> Path | None:
    """The user folder declared by XDG (`XDG_DESKTOP_DIR`...), or None.

    The environment variable wins over the file. None when the declaration is
    missing or empty: `XDG_DESKTOP_DIR=""` is XDG for "no desktop here".
    """
    value = os.environ.get(var, "").strip()
    if value:
        return _expand(value)

    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    try:
        lines = (config / "user-dirs.dirs").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None  # no such file (macOS, minimal Linux): the caller falls back

    for line in lines:
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _sep, raw = line.partition("=")
        if key.strip() != var:
            continue
        raw = raw.strip().strip('"').strip("'")
        return _expand(raw) if raw else None
    return None


# -- Installation messages ----------------------------------------------------

def chromium_hint() -> str:
    """The command that installs Playwright's Chromium on THIS system.

    Linux also needs the system libraries (`--with-deps`): without them Chromium
    installs cleanly, then fails to start with an error that says nothing of it.
    """
    if sys.platform in ("win32", "darwin"):
        return "playwright install chromium"
    return "playwright install --with-deps chromium"


def missing_chromium(exc: BaseException) -> bool:
    """True if this Playwright run failed for want of an installed browser.

    Usually the pip package moved up and wants a newer Chromium build. Recognised
    so that only the install command is shown, not Playwright's ten-line box.
    """
    text = str(exc)
    return "Executable doesn't exist" in text or "playwright install" in text


def ffmpeg_hint() -> str:
    """The command that installs FFmpeg on THIS system.

    FFmpeg is required by the NHK capture and by Whisper.
    """
    if sys.platform == "win32":
        return "winget install ffmpeg"
    if sys.platform == "darwin":
        return "brew install ffmpeg"
    return "sudo apt install ffmpeg  " + _("(or dnf/pacman/zypper depending on the distribution)")


# -- The clipboard ------------------------------------------------------------
# A utility per family of systems, then OSC 52: the escape sequence that hands
# text to the clipboard of the machine the terminal is DISPLAYED on. Only it
# crosses a remote session, but nothing comes back and a terminal that does not
# know it ignores it, so the utilities, which answer, come first.
#
# No dependency: `pyperclip` would call the same utilities.

_TOOLS = {
    # `clip` expects UTF-16LE: in UTF-8 the kana come out as mojibake.
    "win32": ((("clip",), "utf-16-le"),),
    "darwin": ((("pbcopy",), "utf-8"),),
}

# Wayland first, X11 second: a Wayland session often carries both, and `wl-copy`
# is the one that talks to the right server there.
_UNIX_TOOLS = (
    (("wl-copy",), "utf-8"),
    (("xclip", "-selection", "clipboard"), "utf-8"),
    (("xsel", "--clipboard", "--input"), "utf-8"),
)


def copy(text: str) -> str:
    """Put `text` on the clipboard; return the means used, "" if none.

    A utility's name is an observed success, `OSC52` a send never confirmed: the
    caller must not report both alike.
    """
    import subprocess

    for command, encoding in _TOOLS.get(sys.platform, _UNIX_TOOLS):
        try:
            subprocess.run(command, input=text.encode(encoding), check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            continue
        return command[0]
    return _osc52(text)


# The caller compares against this to hedge its sentence.
OSC52 = "OSC 52"


def _osc52(text: str) -> str:
    """Hand the text to the terminal itself, for want of an installed utility.

    Nothing is written outside a terminal, so as not to pollute a file or a CI log.
    """
    import base64

    if not sys.stdout.isatty():
        return ""
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    try:
        sys.stdout.write(f"\033]52;c;{payload}\a")
        sys.stdout.flush()
    except (OSError, ValueError):
        return ""
    return OSC52
