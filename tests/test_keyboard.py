"""Decoding the keys: the sequences of both platforms, without a terminal.

`decode_windows` and `decode_posix` take their source as a parameter, so any
sequence can be played to them without a keyboard.
"""

from __future__ import annotations

import sys

import pytest

from kotogen import keyboard


def windows(*chars: str) -> str:
    """Decodes what `msvcrt.getwch` would have returned, character by character."""
    source = iter(chars)
    return keyboard.decode_windows(lambda: next(source))


def test_windows_a_typed_a_grave_is_a_letter():
    """`\\xe0` is also `à`: with no code waiting behind it in the buffer of
    `getwch`, it is a letter and does not swallow the key after it."""
    remaining = ["\xe0", " ", "l", "a"]

    def decode() -> str:
        return keyboard.decode_windows(lambda: remaining.pop(0), lambda: False)

    assert [decode() for _ in range(4)] == ["à", " ", "l", "a"]


def posix(*chars: str) -> str:
    """Decodes a POSIX sequence; what is left to read counts as "pending"."""
    remaining = list(chars)

    def getch() -> str:
        return remaining.pop(0)

    return keyboard.decode_posix(getch, lambda: bool(remaining))


# ── Windows ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("code, expected", [
    ("H", keyboard.UP), ("P", keyboard.DOWN),
    ("K", keyboard.LEFT), ("M", keyboard.RIGHT),
    ("G", keyboard.HOME), ("O", keyboard.END),
    ("I", keyboard.PGUP), ("Q", keyboard.PGDN),
    ("?", keyboard.F5),
])
def test_windows_special_keys(code, expected):
    """Special keys arrive in two goes: a prefix, then the letter."""
    assert windows("\xe0", code) == expected
    assert windows("\x00", code) == expected   # the other prefix, per key


def test_windows_unknown_special_key_is_ignored_not_typed():
    """A key that is not handled (F12...) must not end up inside a filter."""
    assert windows("\xe0", "\x86") == keyboard.UNKNOWN


def test_windows_plain_characters_come_back_as_themselves():
    assert windows("g") == "g"
    assert windows("é") == "é"
    assert windows("\r") == keyboard.ENTER
    assert windows("\x1b") == keyboard.ESC
    assert windows("\x08") == keyboard.BACKSPACE


def test_ctrl_c_still_interrupts():
    """Read character by character on Windows, Ctrl+C interrupts nothing by
    itself: without this relay the menus would have no way out."""
    with pytest.raises(KeyboardInterrupt):
        windows("\x03")


# ── POSIX ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sequence, expected", [
    (("\x1b", "[", "A"), keyboard.UP),
    (("\x1b", "[", "B"), keyboard.DOWN),
    (("\x1b", "[", "C"), keyboard.RIGHT),
    (("\x1b", "[", "D"), keyboard.LEFT),
    (("\x1b", "O", "H"), keyboard.HOME),
    (("\x1b", "[", "5", "~"), keyboard.PGUP),
    (("\x1b", "[", "6", "~"), keyboard.PGDN),
    (("\x1b", "[", "1", "5", "~"), keyboard.F5),
])
def test_posix_escape_sequences(sequence, expected):
    assert posix(*sequence) == expected


def test_a_lone_escape_is_the_escape_key():
    """Nothing behind it: Escape is what was typed, not the start of an arrow."""
    assert posix("\x1b") == keyboard.ESC


def test_posix_plain_characters():
    assert posix("g") == "g"
    assert posix("\n") == keyboard.ENTER
    assert posix("\x7f") == keyboard.BACKSPACE


def test_an_unfinished_sequence_is_ignored():
    assert posix("\x1b", "[", "Z") == keyboard.UNKNOWN


# ── Availability ──────────────────────────────────────────────────────────────

def test_keys_are_unavailable_without_a_terminal():
    """Under pytest the menus take their numbered path, which the other tests use."""
    assert keyboard.available() is False


def test_keys_follow_the_shared_check_of_a_terminal(monkeypatch):
    """Windows takes the NUL device for a terminal: the shared check knows better."""
    from kotogen import system

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(system, "can_ask", lambda: False)
    assert keyboard.available() is False


def test_typed_ahead_keys_are_left_alone_without_a_terminal():
    """With no terminal there is no key queue to empty: a redirected run or a
    test reads its input to the end, intact."""
    assert keyboard.pending() is False
    assert keyboard.drain() is None

# ── The waiting delay ─────────────────────────────────────────────────────────
# POSIX hands the delay of `pending(delay)` to `select`; Windows has only
# `kbhit`, and polls it until the delay runs out.

@pytest.mark.skipif(sys.platform != "win32", reason="the msvcrt path")
@pytest.mark.parametrize("peeks, expected", [
    ([True], True),          # the key is already there at the first look
    ([False, True], True),   # it arrives during the wait
    ([False, False], False),  # nothing comes before the delay runs out
])
def test_windows_waits_for_a_key_without_reading_it(monkeypatch, peeks, expected):
    """The polling stops at the first key, or at the end of the delay."""
    import msvcrt

    monkeypatch.setattr(keyboard, "available", lambda: True)
    source = iter(peeks)
    monkeypatch.setattr(msvcrt, "kbhit", lambda: next(source, False))
    assert keyboard.pending(0.05) is expected


@pytest.mark.skipif(sys.platform == "win32", reason="the select path")
def test_posix_hands_the_delay_to_select(monkeypatch):
    """Elsewhere the delay goes to `select` whole, rather than being polled."""
    import select

    seen = []
    monkeypatch.setattr(keyboard, "available", lambda: True)
    monkeypatch.setattr(select, "select",
                        lambda r, w, x, delay: seen.append(delay) or ([], [], []))
    assert keyboard.pending(0.05) is False
    assert seen == [0.05]


def test_no_delay_is_still_no_delay():
    """With no terminal there is no queue to wait on: the delay is not spent."""
    assert keyboard.pending(10.0) is False


# ── On a real terminal ────────────────────────────────────────────────────────
# Through a pseudo-terminal, the only place the buffer of `sys.stdin` shows: an
# arrow arrives in one block, the text layer takes it whole, and `select`, which
# watches only the descriptor, sees nothing left behind the escape.

@pytest.mark.skipif(sys.platform == "win32", reason="no pty on Windows")
@pytest.mark.parametrize("sequence, expected", [
    (b"\x1b[A", keyboard.UP),
    (b"\x1b[B", keyboard.DOWN),
    (b"\x1b[6~", keyboard.PGDN),
    (b"\x1b", keyboard.ESC),      # Escape alone stays Escape
    (b"\xc3\xa9", "é"),           # an accented character is several bytes
])
def test_a_key_sent_in_one_block_is_read_whole(monkeypatch, sequence, expected):
    import io
    import os
    import pty
    import tty

    parent, child = pty.openpty()
    tty.setcbreak(child)
    monkeypatch.setattr(sys, "stdin",
                        io.TextIOWrapper(open(child, "rb"), encoding="utf-8"))
    os.write(parent, sequence)
    assert keyboard.read_key() == expected
