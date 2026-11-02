"""Reading a key without Enter: arrows, Escape, delete, characters.

Stdlib only: `msvcrt` on Windows (a prefix, then a letter), `termios` + `tty`
elsewhere (an `ESC [ ...` sequence), both brought back to one vocabulary (`UP`,
`ENTER`, `ESC`...); printable characters come back as they are. Decoding takes
its source as a parameter, so that it is tested without a terminal.
`available()` says whether the terminal plays along; the menus keep their
numbered input for when it does not.
"""

from __future__ import annotations

import codecs
import contextlib
import os
import sys
from collections.abc import Callable, Iterator

from kotogen import system

# Shared vocabulary. The names are longer than one character on purpose: a
# caller tells a special key from a typed character by `len(key) == 1`.
UP = "up"
DOWN = "down"
LEFT = "left"
RIGHT = "right"
HOME = "home"
END = "end"
PGUP = "pgup"
PGDN = "pgdn"
ENTER = "enter"
ESC = "esc"
BACKSPACE = "backspace"
TAB = "tab"
F5 = "f5"
UNKNOWN = "?unknown"

# Windows: second byte of a special key (the first is \x00 or \xe0).
_WINDOWS_SPECIAL = {
    "H": UP, "P": DOWN, "K": LEFT, "M": RIGHT,
    "G": HOME, "O": END, "I": PGUP, "Q": PGDN,
    "?": F5,  # F1 to F10 run from ';' to 'D'
}

# POSIX: last letter of an "ESC [ X" or "ESC O X" sequence.
_CSI_SPECIAL = {"A": UP, "B": DOWN, "C": RIGHT, "D": LEFT, "H": HOME, "F": END}

# POSIX: numbered "ESC [ n ~" sequences.
_TILDE_SPECIAL = {"1": HOME, "4": END, "5": PGUP, "6": PGDN, "15": F5}


def _plain(char: str) -> str:
    """Translate a character received as is (outside an escape sequence)."""
    if char in ("\r", "\n"):
        return ENTER
    if char in ("\x08", "\x7f"):
        return BACKSPACE
    if char == "\t":
        return TAB
    if char == "\x1b":
        return ESC
    if char == "\x03":
        # Read character by character on Windows, Ctrl+C raises nothing by itself.
        raise KeyboardInterrupt
    if not char or char < " ":
        return UNKNOWN
    return char


def decode_windows(getch: Callable[[], str],
                   code_waiting: Callable[[], bool] = lambda: True) -> str:
    """Decode a key from a `msvcrt.getwch`-style source.

    `\\xe0` opens a special key and is also `à`: it is a prefix only when
    `code_waiting` finds a code behind it in the buffer of `getwch`
    (`_code_waiting`).
    """
    char = getch()
    if char == "\x00" or (char == "\xe0" and code_waiting()):
        return _WINDOWS_SPECIAL.get(getch(), UNKNOWN)
    return _plain(char)


def _code_waiting() -> bool:
    """Does `getwch` hold the code of a special key, behind the prefix it gave?

    `kbhit` does not look into that one-character buffer (measured), so a marker
    is pushed in: refused, the code is there; accepted, it is read straight back.
    """
    import msvcrt

    try:
        msvcrt.ungetwch("\x00")
    except OSError:
        return True
    msvcrt.getwch()
    return False


def decode_posix(getch: Callable[[], str], pending: Callable[[], bool]) -> str:
    """Decode a key read byte by byte on a POSIX terminal.

    `pending` says whether something is left to read right away: that is what
    separates the Escape key (nothing behind it) from the start of an arrow
    sequence."""
    char = getch()
    if char != "\x1b":
        return _plain(char)
    if not pending():
        return ESC
    intro = getch()
    if intro not in ("[", "O"):
        return UNKNOWN
    code = getch()
    if code in _CSI_SPECIAL:
        return _CSI_SPECIAL[code]
    if code.isdigit():
        number = code
        while pending():
            char = getch()
            if char == "~":
                break
            number += char
        return _TILDE_SPECIAL.get(number, UNKNOWN)
    return UNKNOWN


def available() -> bool:
    """Does this terminal allow reading keys one at a time?"""
    if not system.can_ask():
        return False
    try:
        if system.windows():
            import msvcrt  # noqa: F401
        else:
            import termios  # noqa: F401
            import tty  # noqa: F401
    except ImportError:
        return False
    return True


@contextlib.contextmanager
def raw_mode() -> Iterator[None]:
    """Switch the terminal to immediate reading for the length of one screen.

    A no-op on Windows (`getwch` reads the console directly). Elsewhere "cbreak"
    rather than "raw", so that Ctrl+C still sends SIGINT."""
    if system.windows():
        yield
        return
    import termios
    import tty

    descriptor = sys.stdin.fileno()
    saved = termios.tcgetattr(descriptor)
    try:
        tty.setcbreak(descriptor)
        yield
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, saved)


def read_key() -> str:
    """Wait for a key and return it in the vocabulary of this module."""
    if system.windows():
        import msvcrt

        return decode_windows(msvcrt.getwch, _code_waiting)

    import select

    # Read from the descriptor, never `sys.stdin`: its buffer would swallow a
    # whole arrow sequence, and `select`, watching the descriptor, would take the
    # leading escape for an Escape key.
    descriptor = sys.stdin.fileno()
    # Holds the bytes of a multi-byte character; "replace" survives a stray byte.
    decoder = codecs.getincrementaldecoder(sys.stdin.encoding or "utf-8")("replace")

    def getch() -> str:
        while True:
            byte = os.read(descriptor, 1)
            if not byte:
                return ""
            char = decoder.decode(byte)
            if char:
                return char

    def more() -> bool:
        # An arrow arrives in one block: nothing within 50 ms means a bare Escape.
        return bool(select.select([descriptor], [], [], 0.05)[0])

    return decode_posix(getch, more)


# -- The rhythm of typing -----------------------------------------------------
# Whether a key is waiting, without reading it: a key typed before a screen was
# drawn is not meant for it, and a pause tells "20" from a "2" then a "0".

def pending(timeout: float = 0.0) -> bool:
    """Is a key there, right now or within the next `timeout` seconds?

    The key is not consumed: `read_key` is what reads it next."""
    if not available():
        return False
    if system.windows():
        import msvcrt
        import time

        # `getwch` cannot wait with a timeout: `kbhit` is polled every hundredth
        # of a second, which the fingers cannot feel.
        deadline = time.monotonic() + timeout
        while True:
            if msvcrt.kbhit():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)

    import select

    return bool(select.select([sys.stdin], [], [], timeout)[0])


def drain() -> None:
    """Throw away what was typed ahead of time, without waiting for anything."""
    if not available():
        return
    if system.windows():
        import msvcrt

        while msvcrt.kbhit():
            msvcrt.getwch()
        return

    import termios

    termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
