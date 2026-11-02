"""What every screen of the assistant is made of.

The cleared page and its pause, questions and menus, the way back, what a menu
remembers, the spinner of a wait, a setting held across sessions. Nothing here
knows a command: the dialogues, one module per command, are built from these.
"""

from __future__ import annotations

import os
import re
import sys
import threading
from collections.abc import Callable, Collection
from pathlib import Path

from kotogen import console, jlpt, keyboard, menu, settings, system
from kotogen.i18n import BACK_ANSWERS, QUIT_ANSWERS, _, agreed, convention, means, quoted

BANNER = (
    " █▄▀ █▀█ ▀█▀ █▀█ █▀▀ █▀▀ █▄ █\n"
    " █ █ █▄█  █  █▄█ █▄█ ██▄ █ ▀█"
)

# The JLPT scale, easiest first. "auto" is not a level: it means all of them.
JLPT_LEVELS = jlpt.LEVELS


# ── Screen ────────────────────────────────────────────────────────────────────
# Each step redraws the menu on a cleared screen rather than under the history.
# Outside a terminal (redirected output, tests) everything scrolls normally.

def _clear() -> None:
    """Clears the screen and the scrollback."""
    if not sys.stdout.isatty():
        return
    if menu.ansi_ready():
        # H homes the cursor, 2J clears the screen, 3J the scrollback.
        print("\033[H\033[2J\033[3J", end="", flush=True)
    else:
        os.system("cls" if system.windows() else "clear")


def _header() -> None:
    """Starts again from an empty screen, headed by the banner."""
    _clear()
    # Written as it stands: the room above the banner, not a blank line between
    # two blocks.
    print(f"\n{BANNER}")


def _pause(message: str, *, to_copy: str = "") -> None:
    """Waits for Enter before clearing, to let what is on screen be read.

    Returns at once without a terminal. Keys typed during the command are
    drained, so an Enter typed ahead cannot cross the pause. "c" copies
    `to_copy` and asks again; the caller announces that key in `message`."""
    if not system.can_ask():
        return
    keyboard.drain()
    console.space()
    while True:
        print(f"{message}", end="", flush=True)
        try:
            answer = console.read_line()
        except (KeyboardInterrupt, EOFError):
            print()
            return
        if not to_copy or answer.strip().lower() != "c":
            return
        print(_copy_report(system.copy(to_copy)))


def _copy_report(via: str) -> str:
    """What can honestly be said of a copy, depending on how it went out.

    OSC 52 is not reported as a success: the terminal may ignore it silently.
    """
    if not via:
        return (console.INDENT + _("Clipboard unavailable: the command is on "
                                   "screen, to be taken with the mouse."))
    if via == system.OSC52:
        return (console.INDENT + _("Command handed to the terminal (OSC 52): not "
                                   "all of them accept it, check before pasting."))
    return console.INDENT + _("Command copied ({via}).").format(via=via)


# ── Going back ────────────────────────────────────────────────────────────────

_Back = menu.Back


# ── What the menus remember ───────────────────────────────────────────────────
# A reopened menu starts on the line last opened in it. The memory lives at
# module level because it must outlive the command, which hands back to the CLI
# between two turns (two passes through `interactive_argv`).
#
# Menu key -> key of the option chosen last time. The menu key is the command's
# ("backup"), not the shown title, which may change.
_remembered_choices: dict[str, str] = {}


def _remember_choice(memory: str | None, choice: str) -> str:
    """Remembers the choice for the next opening of the same menu, and hands it back."""
    if memory is not None:
        _remembered_choices[memory] = choice
    return choice


# ── Elementary questions ──────────────────────────────────────────────────────

def _ask(prompt: str, default: str | None = None, *, back: bool = False,
         sep: str | None = None) -> str:
    """Asks a question; Enter hands back `default` (shown between brackets).

    With `back`, "b" and Escape raise `_Back`. `sep` ends the wording, the
    language's colon unless given. The prompt goes through print(): input(prompt)
    writes on the C stdout (cp1252 on a Windows console) and crashes on Japanese.
    `console.read_line()` counts the newline typed, or the blank line closing the
    dialogue would take the question for an unfinished line."""
    sep = convention("colon", ": ") if sep is None else sep
    suffix = f" [{default}]" if default else ""
    hint = _(" (b = back)") if back else ""
    while True:
        print(f"{prompt}{suffix}{hint}{sep}", end="", flush=True)
        typed = console.read_answer() if back else console.read_line()
        if typed is None:
            raise _Back
        answer = typed.strip()
        if back and means(answer.lower(), BACK_ANSWERS, "back"):
            raise _Back
        if answer:
            return answer
        if default is not None:
            return default
        print("   " + (_("An answer is expected (b to go back).") if back
                       else _("An answer is expected (Ctrl+C to cancel).")))


def _ask_int(prompt: str, default: int, *, back: bool = True) -> int:
    while True:
        answer = _ask(prompt, str(default), back=back)
        if answer.isdigit() and int(answer) > 0:
            return int(answer)
        print("   " + _("A positive whole number is expected."))


# The English yes; a table announcing other letters adds them (see `i18n.means`).
_YES_ANSWERS = ("y", "yes")


def _ask_yes_no(prompt: str, default: bool = False) -> bool:
    answer = _ask(f"{prompt} {_('(y/n)')}", "y" if default else "n").lower()
    return means(answer, _YES_ANSWERS, "yes")


def _menu(title: str, options: list[tuple[str | None, str]], *,
          default: int | str | None = None, allow_quit: bool = False,
          allow_back: bool = False,
          extras: list[tuple[str | None, str]] | None = None,
          marks: dict[str, str] | None = None,
          disabled: Collection[str] = (),
          multi: bool = False, checked: set[str] | None = None,
          memory: str | None = None) -> str | list[str]:
    """Shows a numbered menu; hands back the key of the option chosen ('q' = quit).

    A key of None is a subheading, neither numbered nor chosen. `disabled` keys
    are dimmed but still chosen, the caller saying what is missing; `multi`
    hands back the list ticked, the `extras` acting rather than ticking;
    `memory` names the menu to reopen on its last choice; `allow_back` raises
    `_Back`. Outside a terminal that drives keys, the number typed is the answer.
    """
    checked = set(checked or ())
    # The remembered choice prevails; `default` only counts for the first visit.
    if memory is not None:
        default = _remembered_choices.get(memory, default)
    view = menu.compose(title, options, extras=extras, default=default, marks=marks,
                    disabled=disabled, multi=multi,
                    allow_back=allow_back, allow_quit=allow_quit)

    if view.targets and view.raw:
        choice = menu.by_key(view, allow_back=allow_back, multi=multi,
                              checked=checked)
        return choice if multi else _remember_choice(memory, choice)

    # Without key driving the dimming is painted once, here; never outside a
    # terminal, where the codes would show as they are.
    painted = view.dimmed and sys.stdout.isatty() and menu.ansi_ready()
    print("\n".join(menu.dim(line) if painted and i in view.dimmed else line
                    for i, line in enumerate(view.lines)))
    if multi and view.numbered > 1:
        # Without Space to tick, nothing else says several can be taken.
        console.space()
        already = (agreed(len(checked), " ({count} already ticked)")
                   .format(count=len(checked)) if checked else "")
        print("  " + _("Several at once: their numbers, separated by spaces.")
              + already)
    keys = view.keys
    console.space()
    # The default shows between brackets as its number or letter: "1", not "vocab".
    hint = view.tokens[view.start] if default is not None and view.tokens else None
    while True:
        answer = _ask(">", hint, sep=" ").lower()
        if allow_quit and means(answer, QUIT_ANSWERS, "quit"):
            return "q"
        if allow_back and means(answer, BACK_ANSWERS, "back"):
            raise _Back
        if multi:
            # Numbers tick, a letter acts: "1 3 n" ticks two, then turns the page
            # with the ticks kept.
            words = answer.split()
            numbers = [w for w in words if w.isdigit() and 1 <= int(w) <= view.numbered]
            actions = [w for w in words if w in keys]
            if words and len(numbers) + len(actions) == len(words):
                kept = checked | {view.targets[int(w) - 1] for w in numbers}
                return menu.ticked(kept, view.targets) + actions
        elif answer in keys:
            return _remember_choice(memory, answer)
        if not multi and answer.isdigit() and 1 <= int(answer) <= view.numbered:
            return _remember_choice(memory, view.targets[int(answer) - 1])
        # Letters only (the settings screen): no "number from 1 to 0".
        print("   " + _("Answer expected: ")
              + ((_("a number from 1 to {last}").format(last=view.numbered)
                  + (_(", or several separated by spaces") if multi else ""))
                 if view.numbered
                 else _("one of the letters offered ({letters})").format(
                     letters=" ".join(sorted(keys))))
              + (_(", b to go back") if allow_back else "")
              + (_(", or q to quit.") if allow_quit else "."))


def _columns(entries: list[tuple[str | None, str, str]]) -> list[tuple[str | None, str]]:
    """Lays the labels of a menu out in two columns: what one chooses, then what
    it covers.

    The column starts after the longest name, so names must stay short. Widths
    are screen columns (`青空朗読` takes eight); subheadings (key None) go
    through as they are.
    """
    width = max(console.width(name)
                for key, name, _desc in entries if key is not None) + 2
    return [(key, name if key is None or not desc
             else console.pad(name, width) + desc)
            for key, name, desc in entries]


def _ask_url(prompt: str | None = None) -> str:
    from kotogen.generators import pdf_web  # late: the assistant starts light

    prompt = _("Page URL") if prompt is None else prompt
    while True:
        url = _ask(prompt, back=True)
        if not url.startswith(("http://", "https://")):
            print("   " + _("The URL must begin with http:// or https://."))
            continue
        # Tadoku's list of books yields nothing: a book's own record is needed.
        if "tadoku.org" in url and not pdf_web.is_book_url(url):
            print("   " + _("On Tadoku, it is a book's record that is given "
                            "(tadoku.org/japanese/book/...),"))
            print("   " + _("or the {entry} entry of the menu, which lists them.")
                  .format(entry=quoted(_("A book > Tadoku"))))
            continue
        return url


def _ask_file(prompt: str, *, suffix: str | None = None) -> Path:
    """Asks for a path until it designates an existing file.

    Quotation marks are stripped: the Windows "copy as path" adds them."""
    while True:
        path = Path(_ask(prompt, back=True).strip('"').strip("'"))
        if path.is_file() and (suffix is None or path.suffix.lower() == suffix):
            return path
        print("   " + (_("PDF not found: {path}") if suffix
                       else _("Not found: {path}")).format(path=path))


def _ask_existing(prompt: str) -> Path:
    """Asks for an existing path, file or folder (a book in pictures is
    sometimes one, sometimes the other)."""
    while True:
        path = Path(_ask(prompt, back=True).strip('"').strip("'"))
        if path.exists():
            return path
        print("   " + _("Not found: {path}").format(path=path))


_PAGES_RE = re.compile(r"\d+(-\d*)?(,\d+(-\d*)?)*")

# What stands for "the whole document" in a page range.
_ALL_PAGES = ("all",)


def _ask_pages(prompt: str) -> str | None:
    """Page range of a document; Enter (or "all") = the whole document.

    Its "all" takes the "pages" context, since it agrees with its noun (French
    `toutes`); the comparison does too, so the word offered is accepted back.
    """
    while True:
        answer = _ask(prompt, _("all", "pages"), back=True).lower().replace(" ", "")
        if means(answer, _ALL_PAGES, "all_pages") or answer == _("all", "pages"):
            return None
        if _PAGES_RE.fullmatch(answer):
            return answer
        print("   " + _("Answer expected: 3-18, 12-, 7, or Enter for the whole"
                        " document."))


# ── One dialogue per subcommand ───────────────────────────────────────────────
# A menu of sources, then its questions: two functions, so that `_dialog` can
# go back from the questions to the menu. Only the options that differ from the
# default reach the argv.

def _dialog(choose: Callable[[], str], options: Callable[[str], list[str]]) -> list[str]:
    """Source menu then questions; a way back from the questions returns there.

    A way back from the menu itself is not caught: it goes up to the main menu."""
    while True:
        _header()
        source = choose()
        try:
            return options(source)
        except _Back:
            continue


# What stands for "no limit at all" in the questions that accept one.
_ALL_ANSWERS = ("all", "max")
_NONE_ANSWERS = ("none", "no", "nothing")
_NO_LIMIT_ANSWERS = ("no limit", "none", "no", "0")


def _ask_optional_max(prompt: str) -> int | None:
    """Question "limit or all": Enter (or 'all'/'max') = no limit.

    Its "all" takes the context "limit", not the thing counted: words at one call
    site, rules at another, so its translation must fit both (French `tout`).
    """
    while True:
        answer = _ask(prompt, _("all", "limit"), back=True).lower()
        if means(answer, _ALL_ANSWERS, "all") or answer == _("all", "limit"):
            return None
        if answer.isdigit() and int(answer) > 0:
            return int(answer)
        print("   " + _("Answer expected: a positive whole number, or Enter"
                        " for all."))


def _ask_auto_max(prompt: str) -> int | None:
    """Question "ceiling or auto": Enter (or 'auto') = the content decides.

    Unlike `_ask_optional_max` there is always a limit: "auto" has it worked out
    from the length of the source.
    """
    while True:
        answer = _ask(prompt, "auto", back=True).lower()
        if answer in ("auto", "a"):
            return None
        if answer.isdigit() and int(answer) > 0:
            return int(answer)
        print("   " + _("Answer expected: a positive whole number, or Enter to"
                        " let the content decide."))


def _ask_optional_seconds(prompt: str) -> int | None:
    """Question "max duration or none": Enter (or 'no limit') = no limit.

    "no limit" rather than "auto": unlike `_ask_auto_max`, nothing is worked out.
    """
    while True:
        answer = _ask(prompt, _("no limit"), back=True).lower()
        if means(answer, _NO_LIMIT_ANSWERS, "no_limit") or answer == _("no limit"):
            return None
        if (value := answer.rstrip("s")).isdigit() and int(value) > 0:
            return int(value)
        print("   " + _("Answer expected: a number of seconds (180), or Enter"
                        " for no limit."))


# The first screen asks for a kind of matter (an article, a programme, a book,
# past papers, a file): a closed list, where a new catalogue goes into one of the
# submenus. These hand back the key of the source, as `_audio_options` and
# `_reading_options` expect it.

def _submenu(title: str, entries: list[tuple[str, str, str]], default=1) -> str:
    """A second screen of choice, a way back from which returns to the first.

    The caller catches the `_Back` (see `_audio_source`), so that it does not
    leave the command. The screen is cleared first: the submenu replaces the
    first list rather than following it.
    """
    _header()
    return _menu(title, _columns(entries), default=default, allow_back=True)


def _entry(name: str, description: str, width: int) -> str:
    """A menu entry in two columns, like those of the welcome menu.

    `width` comes from the longest name of the caller's menu, in screen columns;
    a name, however long its translation, keeps two of them before its description.
    """
    return console.pad(name, max(width, console.width(name) + 2)) + description


# Seconds before the AnkiConnect probe animates: a quicker one would only flicker.
_PROBE_NOTICE_DELAY = 0.4

# The probe's spinner wipes itself once done, and turns with the frames of
# `console`, like every other wait of the program.
_SPINNER_FRAMES = console.SPINNER
_SPINNER_PERIOD = console.SPINNER_PERIOD


def _spin_while_alive(worker: threading.Thread, label: str) -> None:
    """Animates `label` as long as the thread turns, then wipes the line.

    It turns one line lower, where the state will show, then the cursor goes
    back up, so the layout is as if no probe had shown. Silent outside a terminal.
    """
    if not sys.stdout.isatty():
        # In short joins, as `console.animate`: on Windows a bare `join()` holds
        # Ctrl+C back until the probe ends.
        while worker.is_alive():
            worker.join(_SPINNER_PERIOD)
        return
    # `leaving_no_trace` keeps the wait out of the blank-line bookkeeping, or the
    # next block would add a blank line; this one goes only where there is none.
    lowered = not console.ends_blank()
    with console.leaving_no_trace():
        if lowered:
            print()
        frame = 0
        try:
            while worker.is_alive():
                print(f"\r{_SPINNER_FRAMES[frame]} {label}", end="", flush=True)
                frame = (frame + 1) % len(_SPINNER_FRAMES)
                worker.join(_SPINNER_PERIOD)
        finally:
            # Ctrl+C included, or the frame would head what comes next. Screen
            # columns: a kanji of the label takes two.
            print("\r" + " " * (console.width(label) + 2) + "\r", end="", flush=True)
            if lowered and menu.ansi_ready():
                print("\033[A", end="", flush=True)  # back up onto the blank line


# ── Holding on to a setting ───────────────────────────────────────────────────
# A setting chosen here is written at once, without asking or announcing it: the
# screen shows the value held, and only a failure speaks. The command-line
# options (--provider, --output...) change one command and write nothing.

def _remember(name: str, value: str) -> Path | None:
    """Lays the setting down for this session AND for the next ones.

    The environment comes first, so the command built next sees the value even
    when the file cannot be written: that failure is said, and the setting holds
    for this session only.
    """
    os.environ[name] = value
    try:
        return settings.write(name, value)
    except OSError as exc:
        console.space()
        print(_("Write impossible ({reason}).").format(reason=exc))
        print("   " + _("The setting holds for this session only."))
        return None


def _remember_toggle(name: str, value: str) -> None:
    """Holds a toggle, saying nothing when all goes well.

    The settings screen redraws at once with the value; a failed write pauses so
    that it is read first.
    """
    if _remember(name, value) is None:
        _pause(_("Enter to come back to the menu..."))
