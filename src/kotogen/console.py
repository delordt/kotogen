"""What the screen shows while the program works, and nothing else.

The shape of the work (three forms, described above `title`), and the blank
line between its blocks: one blank line separates two blocks, it never opens
one. No caller knows what was printed before it, so `space()` asks the output:
`stdout` is wrapped in a watcher that remembers its last two visible characters,
ANSI sequences removed. `watch()` puts the wrapper on once, at startup. It
filters nothing, or the menu redraw would miscount lines.
"""

from __future__ import annotations

import re
import shutil
import sys
import threading
import unicodedata
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from kotogen import keyboard
from kotogen.i18n import _, convention, counted

# A complete ANSI sequence: "ESC [ ... letter". It prints nothing, and a line
# rewritten by `menu.repaint` always carries one.
_ANSI = re.compile(r"\033\[[0-9;?]*[ -/]*[@-~]")

_CLEAR = "\033[2J"


class _Watcher:
    """Wraps `stdout` and remembers whether the output ends on a blank line.

    Everything else is delegated (`isatty()`, `reconfigure()`, `flush()`, the
    binary buffer).
    """

    def __init__(self, stream) -> None:
        self.stream = stream
        # Nothing written counts as an empty screen: the first line of an output
        # has nothing to separate.
        self.tail = "\n\n"
        # Lines finished since the start: tells whether a step held on its own
        # line or something wrote below it.
        self.lines = 0

    def write(self, text: str) -> int:
        written = self.stream.write(text)
        if _CLEAR in text:
            self.tail = "\n\n"
            text = text.rsplit(_CLEAR, 1)[1]
        # A carriage return erases nothing already counted: only what prints counts.
        visible = _ANSI.sub("", text).replace("\r", "")
        if visible:
            self.tail = (self.tail + visible)[-2:]
            self.lines += visible.count("\n")
        return written

    def __getattr__(self, name):
        return getattr(self.stream, name)


def watch() -> None:
    """Put the wrapper on `stdout`, before the first line is written.

    Put on later, it would take the screen for empty and skip a blank line: the
    CLI calls it at startup. Without it, `space()` always writes a blank line.
    """
    if not isinstance(sys.stdout, _Watcher):
        sys.stdout = _Watcher(sys.stdout)


def ends_blank() -> bool:
    """True if the screen already carries a blank line at the bottom (or is empty).

    False when the output is not watched: better a blank line too many than two
    blocks stuck together.
    """
    stream = sys.stdout
    return isinstance(stream, _Watcher) and stream.tail.endswith("\n\n")


def lines_written() -> int:
    """How many lines the output has received so far.

    Two readings framing a step say whether it held on its line. Zero when the
    output is not watched, so the step passes for held.
    """
    stream = sys.stdout
    return stream.lines if isinstance(stream, _Watcher) else 0


def line_open() -> bool:
    """True if the output stopped in the middle of a line.

    False may also mean something wrote after the line (a retry announced by the
    AI client). True when the output is not watched: the caller that has just
    written without a newline knows better.
    """
    stream = sys.stdout
    if not isinstance(stream, _Watcher):
        return True
    return not stream.tail.endswith("\n")


# -- The step that holds on one line ------------------------------------------
# The stages of a step (what is handled, what is done to it, what comes out) are
# learnt one after another, and hook onto one line opened without a newline. It
# is held here because it is often closed three calls below where it was opened
# (`sources.each` opens, the generator closes). One step line at a time.

# What separates the stages of one line: the dash that sets an aside off in the
# prose of the program.
_SEPARATOR = " - "

# The step line in progress, as it was written, or `None`: kept to write it whole
# again once something (an error on stderr, a retry of the AI client) has cut it.
_step: str | None = None

# Whether the console itself wrote under the step line (`item`, `aside`,
# `failed`): known first hand, where `line_open()` knows nothing without a
# watcher. What writes without going through here is left to the watcher.
_cut = False

# The watcher's memory just before the step line was opened, given back when the
# line is erased rather than closed (`drop_line`).
_before_step = "\n\n"


def open_line(start: str) -> None:
    """Open a step line: what follows will hook onto it, not below it.

    Closes first any line left open, which this one would stick to.
    """
    global _step, _cut, _before_step
    close_line()
    stream = sys.stdout
    _before_step = stream.tail if isinstance(stream, _Watcher) else "\n\n"
    _step, _cut = start, False
    print(start, end="", flush=True)


def is_open() -> bool:
    """True if a step line is still waiting for its continuation.

    Tells a text unrolled by `sources.each` (one line) from a PDF document (a
    block).
    """
    return _step is not None


def extend(more: str, sep: str = _SEPARATOR) -> None:
    """Add a stage to the open line.

    `sep` is the dash (`_SEPARATOR`), except for what prolongs the start rather
    than adds a stage (the title after the rank of an article). With no open
    line, the continuation opens one.
    """
    global _step, _cut
    if _step is None:
        open_line(more)
        return
    _step += f"{sep}{more}"
    print(_step if _broken() else f"{sep}{more}", end="", flush=True)
    _cut = False


def close_line(outcome: str = "", sep: str = _SEPARATOR) -> None:
    """Close the open line, hooking its outcome onto it if there is one.

    If something wrote under the line meanwhile, it is written whole again before
    its outcome. `sep` is the dash (`_SEPARATOR`), or a space for the result of
    an action (`done`). With no open line, nothing is written.
    """
    global _step, _cut
    if _step is None:
        return
    line, broken, _step, _cut = _step, _broken(), None, False
    if not outcome:
        if not broken:
            print()
    elif broken:
        print(f"{line}{sep}{outcome}")
    else:
        print(f"{sep}{outcome}")


def drop_line() -> None:
    """Take the open line off the screen: it held a wait, and nothing more.

    For a line whose outcome is nothing to write ("Thinking…"). Only on a
    terminal and while the line is the last thing written; otherwise it closes
    as usual, and a log keeps the trace of the wait.
    """
    global _step, _cut
    if _step is None:
        return
    with _lock:
        if _broken() or not sys.stdout.isatty():
            close_line()
            return
        _clear_animation()
        print(f"\r{' ' * width(_step)}\r", end="", flush=True)
        _step, _cut = None, False
        # The watcher saw the spaces of the erasure: give it back what it held
        # before the line was opened, the cursor being back there.
        stream = sys.stdout
        if isinstance(stream, _Watcher):
            stream.tail = _before_step


def _broken() -> bool:
    """True if the step line is no longer the last thing written.

    Both sources are needed: `_cut` for what the console wrote itself, the
    watcher for what wrote without it (the AI client announcing a retry).
    """
    return _cut or not line_open()


def space() -> None:
    """A blank line to detach what follows, unless there is already one.

    A step still open is closed first.
    """
    close_line()
    if not ends_blank():
        print()


# -- The shape of the work ----------------------------------------------------
# Everything the program says while it works fits into three forms:
#
#     NHK Easy News                              a source, in the margin
#        Looking for articles... (3 new)         what was done to get it
#        ne2026083012345 - 台風13号…              what it carries
#
#     Downloading the episodes... (3, 34 MB)     a common action, in the margin
#
#     [1/3] ne2026083012345                      the rank: this is where we are
#        Loading the article... (5 sentences)    what is done to it, indented
#        Generating the cards... (4 cards)
#
# An action opens on its label and "..." and stays open while it lasts: its
# result hooks onto the same line, in brackets. The indent is the only hierarchy,
# one level deep: a piece of work inside another (passage 3 of 6 of a
# collection) is said in the label of the action.

INDENT = "   "

# The C0 controls but the line feed and the tab, DEL, and the C1 controls: in a
# model's answer or a web page, an ESC would drive the terminal (clear it, retitle it).
_CONTROLS = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def clean(text: str) -> str:
    """`text` without the control characters that drive a terminal.

    For text the program did not write: what a model says, what a page or a feed
    carries. The line feed and the tab stay.
    """
    return _CONTROLS.sub("", text)


def width(text: str) -> int:
    """What this text takes up on screen, in terminal columns.

    A kanji, a kana and Japanese punctuation take two columns where `len` counts
    one. "Ambiguous" characters (composed accents, symbols) count as one, as
    terminals outside an East Asian context show them. A combining mark takes
    none: it sits on the character before it (`か` + U+3099 in a name NFD wrote).
    """
    return sum(0 if unicodedata.category(char) in ("Mn", "Me")
               else 2 if unicodedata.east_asian_width(char) in "WF" else 1
               for char in text)


def pad(text: str, columns: int) -> str:
    """`text` filled with spaces up to `columns` screen columns.

    The counterpart of `f"{text:<{n}}"`, which counts characters where the
    screen counts columns.
    """
    return text + " " * max(0, columns - width(text))


def pad_left(text: str, columns: int) -> str:
    """`text` aligned right on `columns` screen columns, as `f"{text:>{n}}"` would
    align it if a kanji took one."""
    return " " * max(0, columns - width(text)) + text


def truncate(text: str, columns: int) -> str:
    """`text` brought back to `columns` screen columns, an ellipsis at the cut.

    The counterpart of `pad`, counting screen columns too.
    """
    if width(text) <= columns:
        return text
    if columns <= 1:
        return "…"[:max(0, columns)]
    kept, room = [], columns - 1
    for char in text:
        cost = width(char)
        if cost > room:
            break
        kept.append(char)
        room -= cost
    return "".join(kept) + "…"


def plural(n: int, singular: str, many: str = "", context: str = "") -> str:
    """The word at the right number, translated.

    `singular` and `many` are English, since the English pair keys the forms in
    the table. `many` defaults to the singular plus an "s" (`entry` passes
    `entries`). Which count takes which form is read by `i18n.counted`.
    """
    return counted(n, singular, many or f"{singular}s", context)


# The room of a reason given on a line of its own, an exit: the terminal wraps
# a sentence that long, and a dump is still cut.
ALONE = 200


def reason(error: BaseException | str, columns: int = 60) -> str:
    """What an error says on screen: its first line, cleaned, and nothing below it.

    Below it there is often debugging material (`chat_json` attaches the raw
    answer of the model), which stays in the exception. An exception that says
    nothing (`ConnectionError()`) is named by its kind.
    """
    lines = clean(str(error)).strip().splitlines()
    if lines:
        first = lines[0].strip()
    else:
        first = type(error).__name__ if isinstance(error, BaseException) else ""
    return truncate(first, columns)


def size(nbytes: float) -> str:
    """The size of a file, in the unit that reads: "412 KB", "2.1 MB", "1.4 GB"."""
    point = convention("decimal_point", ".")
    if nbytes < 1024 * 1024:
        # At least "1 KB" unless empty: "0 KB" would read as empty.
        return f"{round(nbytes / 1024) or int(nbytes > 0)} {_('KB')}"
    if nbytes < 1024 * 1024 * 1024:
        return f"{nbytes / (1024 * 1024):.1f}".replace(".", point) + f" {_('MB')}"
    return f"{nbytes / (1024 * 1024 * 1024):.1f}".replace(".", point) + f" {_('GB')}"


def size_of(paths) -> str:
    """The total size of a batch of files, formatted like `size`.

    A missing file counts for nothing: its failure is said elsewhere.
    """
    total = 0
    for path in paths:
        try:
            total += Path(path).stat().st_size
        except OSError:
            pass
    return size(total)


def duration(seconds: float) -> str:
    """A duration as it is read off a watch: "01:12", "1:03:20".

    For the position reached in an audio and the time a wait has taken.
    """
    total = int(round(max(0.0, seconds)))
    hours, rest = divmod(total, 3600)
    minutes, s = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{s:02d}" if hours else f"{minutes:02d}:{s:02d}"


def title(name: str) -> None:
    """Open a block in the margin: a source, or an action common to the batch.

    Detached from what precedes it by `space()`, like every block. The lines of
    the run are cleaned (`clean`): a source's name or title comes from the web.
    """
    space()
    print(clean(name))


def _under_the_action() -> None:
    """Go back to the start of the line WITHOUT closing the action in progress.

    What is written under an open action (a ceiling applied, a retry, a failure)
    does not end it: `done()` writes it whole again above its result. An
    animated wait is erased first, or its frame would head what is written.
    """
    global _cut
    if _step is None:
        return
    with _lock:
        if not _clear_animation() and not _broken():
            # Flushed at once: what follows may go out on stderr (`failed`), and
            # the two streams only stay in order if this one is already written.
            print(flush=True)
        _cut = True


def item(text: str) -> None:
    """One indented line under the block in progress: an item, a detail."""
    with _lock:
        _under_the_action()
        print(f"{INDENT}{clean(text)}", flush=True)


def items(names: list[str], maximum: int = 8) -> None:
    """What a source carries, cut short beyond `maximum`: the rest is counted."""
    for name in names[:maximum]:
        item(name)
    if len(names) > maximum:
        rest = len(names) - maximum
        item(_("... and {count} more").format(count=rest))


def rank(n: int, total: int, name: str) -> None:
    """Open the block of an item being handled: "[n/total] name".

    `name` is the one the source listed it under, to be found in the list above.
    """
    space()
    print(f"[{n}/{total}] {clean(name)}")


def action(label: str, *, among: str = "", margin: bool = False) -> None:
    """Open an action: "Label...", waiting for what it will return.

    `among` places it in a set the rank does not show (passage 3 of 6), in
    brackets before the ellipsis. `margin` takes it out of the indent, for an
    action common to the whole batch (a grouped download).
    """
    if among:
        label = f"{label} ({among})"
    if margin:
        # A block of its own: stuck to the list before it, it would pass for
        # its last item.
        space()
    open_line(f"{'' if margin else INDENT}{clean(label)}…")


def done(result: str = "") -> None:
    """Close the open action: what it returned, in brackets.

    With no result, the line closes on its label alone.
    """
    close_line(f"({clean(result)})" if result else "", sep=" ")


def aside(text: str) -> None:
    """A deliberate sorting: what was left aside, and why.

    Marked "!" on stdout: not a failure, but left unsaid it would make the final
    count look like a bug.
    """
    item(f"! {text}")


def failed(text: str) -> None:
    """An incident: what failed. Marked "!!", and on stderr.

    Written under the action without closing it: the action has no result, and
    the next block leaves it behind.
    """
    with _lock:
        _under_the_action()
        print(f"{INDENT}!! {clean(text)}", file=sys.stderr, flush=True)


@contextmanager
def leaving_no_trace():
    """What is written here erases itself: the screen is left as it was found.

    The output is not touched: the watcher gets back the memory it had before,
    or the spaces of a spinner's erasure would make it think the screen busy.
    """
    stream = sys.stdout
    before = stream.tail if isinstance(stream, _Watcher) else None
    try:
        yield
    finally:
        if before is not None:
            stream.tail = before


# -- The wait that turns ------------------------------------------------------
# A line frozen for minutes (a call to the model, a download, a transcription)
# cannot be told from a crash. A spinner turns at the end of the open action
# line, beside what the wait is busy doing ("03:30 of 09:12"), and erases itself
# before `done()` hooks the result there.

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPINNER_PERIOD = 0.08


def columns() -> int:
    """The width of the terminal, read again at each use: windows resize."""
    return shutil.get_terminal_size(fallback=(80, 24)).columns


# What the animation takes up on the line, zero when nothing is animating: the
# animated work may write itself (a retry of the AI client) and must erase it first.
_animated_width = 0

# The animated work runs in a thread and writes to the spinner's output: the lock
# keeps its lines from slipping between the erasure of a frame and the next.
_lock = threading.RLock()

# An animated wait in progress: what runs under it (an ffmpeg launched by a
# download) opens no second spinner on the same line.
_waiting = False


def _clear_animation() -> bool:
    """Take the animation off the screen, and say whether it was there.

    The label of the action goes with it: `_cut` remembers, and `done()` writes
    it whole again above its result.
    """
    global _animated_width
    if not _animated_width:
        return False
    print(f"\r{' ' * _animated_width}\r", end="", flush=True)
    _animated_width = 0
    return True


def animate(work, detail: Callable[[], str] | None = None) -> None:
    """Animate the open action line while `work` runs, then give it back intact.

    `detail` is read again at each frame: what the wait is busy doing (the second
    of the audio reached, the bytes received). Outside a terminal or with no open
    action, it only waits for `work`.
    """
    global _waiting, _animated_width
    if (_step is None or not sys.stdout.isatty()
            or threading.current_thread() is not threading.main_thread()):
        # In short joins: on Windows a bare `join()` holds Ctrl+C back until
        # the work ends, a paid call included.
        while work.is_alive():
            work.join(SPINNER_PERIOD)
        return

    frame = 0
    _waiting = True
    try:
        with leaving_no_trace():
            try:
                while work.is_alive():
                    with _lock:
                        line = f"{_step} {SPINNER[frame]} {detail() if detail else ''}".rstrip()
                        # A frame that wraps cannot be erased by a carriage return,
                        # and the detail (the output of pip...) has any length: cut
                        # to the terminal, one column left free for the cursor.
                        line = truncate(line, columns() - 1)
                        _animated_width = max(_animated_width, width(line))
                        print(f"\r{line}", end="", flush=True)
                    frame = (frame + 1) % len(SPINNER)
                    work.join(SPINNER_PERIOD)
            finally:
                # Ctrl+C included: a frame left on the line would head what the
                # next command writes there.
                with _lock:
                    # The line is given back as it was, unless the work wrote
                    # under it: `done()` then writes it whole again.
                    _clear_animation()
                    if not _broken():
                        # From the start of the line, where the cursor is whether
                        # a frame was erased or none was drawn.
                        print(f"\r{_step}", end="", flush=True)
    finally:
        _waiting = False


def while_working(work: Callable[[], object], detail: Callable[[], str] | None = None):
    """Run `work` alongside, the action line animated, and return what it gave.

    Its exception is raised here, as if it had run in place. A daemon thread, so
    that work that cannot stop (ffmpeg, Whisper) does not hold an interrupt back.
    """
    if _waiting or threading.current_thread() is not threading.main_thread():
        # Already animated, or not the thread that holds the line (the parallel
        # model calls of the vocabulary extraction): run here, no second spinner.
        return work()

    outcome: list = []

    def run() -> None:
        try:
            outcome.append((None, work()))
        except BaseException as exc:  # returned as it is to the calling thread
            outcome.append((exc, None))

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    animate(thread, detail)
    thread.join()
    exc, value = outcome[0]
    if exc is not None:
        raise exc
    return value


def read_line() -> str:
    """`input()`, counting the newline the Enter key writes.

    The terminal echoes the input past `sys.stdout`, so the watcher would think
    the line unfinished. Only its memory is updated, and only if the input took
    place.
    """
    answer = input()
    stream = sys.stdout
    if isinstance(stream, _Watcher):
        stream.tail = (stream.tail + "\n")[-2:]
    return answer


# -- A line one can leave with Escape -----------------------------------------
# `input()` never receives Escape: a Windows console keeps it to erase the line
# being typed. A question with a way back reads its answer key by key, as the
# menus do, and writes the echo itself.

def _erase(text: str) -> None:
    """Take back on screen what was echoed: a kanji is two columns wide."""
    columns = width(text)
    print("\b" * columns + " " * columns + "\b" * columns, end="", flush=True)


def _line(next_key: Callable[[], str]) -> str | None:
    """Assemble a typed line; None when Escape is pressed on an empty one.

    Escape on what has been typed erases it, as a Windows console does. Reading
    is passed as a parameter, as in `_stars`, to be checked without a terminal.
    """
    typed: list[str] = []
    while True:
        key = next_key()
        if key == keyboard.ENTER:
            print()
            return "".join(typed)
        if key == keyboard.ESC:
            if not typed:
                print()
                return None
            _erase("".join(typed))
            typed.clear()
        elif key == keyboard.BACKSPACE:
            if typed:
                _erase(typed.pop())
        elif len(key) == 1:
            typed.append(key)
            print(key, end="", flush=True)


def read_answer() -> str | None:
    """A line typed, or None when Escape asks to go back.

    Key by key when the terminal allows it; through `read_line` otherwise (a
    redirected input, the tests), where the letter of the way back still works.
    """
    if keyboard.available():
        with keyboard.raw_mode():
            return _line(keyboard.read_key)
    return read_line()


# -- A secret that shows without being read -----------------------------------
# `getpass` shows nothing, so a paste that never happened looks like one that
# did. One star per character shows that something arrived, and its length,
# without making the key readable over a shoulder or leaving it in the terminal
# history. `getpass` stays the fallback where keys cannot be read one by one.

def _stars(next_key: Callable[[], str]) -> str:
    """Assemble an input while writing only one star per character.

    Escape returns an empty input, like a line left empty: the caller has one
    case to handle. Reading is passed as a parameter, as in `keyboard`, to be
    checked without a terminal.
    """
    typed: list[str] = []
    while True:
        key = next_key()
        if key in (keyboard.ENTER, keyboard.ESC):
            # The terminal echoed nothing, so the newline is ours.
            print()
            return "" if key == keyboard.ESC else "".join(typed)
        if key == keyboard.BACKSPACE:
            if typed:
                typed.pop()
                # The echo is ours, so is its erasure: back up, blank, back up.
                print("\b \b", end="", flush=True)
        elif len(key) == 1:
            typed.append(key)
            print("*", end="", flush=True)


def read_secret(prompt: str) -> str:
    """Take in a secret, shown as stars and never in the clear."""
    print(prompt, end="", flush=True)
    if keyboard.available():
        with keyboard.raw_mode():
            return _stars(keyboard.read_key)

    import getpass

    typed = getpass.getpass("")
    stream = sys.stdout
    if isinstance(stream, _Watcher):
        # Like `read_line`: the echo and its newline do not go through
        # `sys.stdout`, and the watcher would think the line unfinished.
        stream.tail = (stream.tail + "\n")[-2:]
    return typed
