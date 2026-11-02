"""The menu drawn in the terminal: its lines, its highlight, its keys.

A menu is built once in memory (`compose`, or a `View` laid out by hand), then
printed whole for a numbered entry, or driven by the keys (`by_key`) where the
terminal allows it (`raw_ready`), rewritten in place at every key. It lives
outside `interactive` because a command's own questions (two duplicates, a
leech) use it without the assistant.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable, Collection
from dataclasses import dataclass

from kotogen import console, keyboard, settings, system
from kotogen.i18n import _, agreed, listed


class Back(Exception):
    """Escape (or "b"): the user wants to go back to the previous step.

    From a question, `interactive.screen._dialog` catches it and shows the
    command's menu again; from that menu, it goes up to the main menu.
    """


# ── Terminal ──────────────────────────────────────────────────────────────────

_ansi: bool | None = None  # None = not attempted yet


def _enable_ansi() -> bool:
    """Allows ANSI sequences on the Windows console; elsewhere, a given.

    The legacy console needs ENABLE_VIRTUAL_TERMINAL_PROCESSING, or it prints
    the codes as they stand.
    """
    if not system.windows():
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except (ImportError, AttributeError, OSError):
        return False


def ansi_ready() -> bool:
    """Are ANSI sequences interpreted? (attempted once, then remembered)"""
    global _ansi
    if _ansi is None:
        _ansi = _enable_ansi()
    return bool(_ansi)


def raw_ready() -> bool:
    """Can the menus be driven with the arrow keys on this terminal?

    Only on a real terminal on both sides, with ANSI sequences to redraw in
    place, and without `KOTOGEN_NO_RAW_KEYS`, the way out for an exotic terminal.
    """
    if settings.flag("KOTOGEN_NO_RAW_KEYS"):
        return False
    # `system.can_ask` first: on Windows the NUL device passes `isatty`, and the
    # keys would be read from a console nobody types in.
    if not (system.can_ask() and keyboard.available()):
        return False
    return ansi_ready()


def fits_on_screen(height: int) -> bool:
    """Can a block of this height redraw itself in place?

    The redraw cannot go back up past the top of the window: a taller block
    would redraw too low and scroll at every key, so it falls back on numbered
    entry. Strictly shorter than the window: the last line leaves the cursor below.
    """
    return height < shutil.get_terminal_size((100, 30)).lines


def fit(line: str, columns: int) -> str:
    """Truncates a line so that it does not spill over onto the next one.

    A wrap would throw off the redraw, which counts lines. Measured in SCREEN
    COLUMNS, not characters: `〜てください` takes twelve for six characters.
    """
    if console.width(line) < columns:
        return line
    kept: list[str] = []
    left = columns - 1
    for char in line:
        left -= console.width(char)
        if left < 0:
            break
        kept.append(char)
    return "".join(kept)


def emphasise(text: str, width: int) -> str:
    """Marks the current line with a full bar, from edge to edge of the block.

    Reverse video (`\\033[7m`) shows under any terminal theme, where bold would
    not; the chevron in the left margin repeats it for whoever cannot tell
    backgrounds apart.
    """
    marked = f"›{text[1:]}" if text.startswith(" ") else text
    return f"\033[7m{console.pad(marked, width)}\033[0m"


def dim(text: str) -> str:
    """Dims a line: it still reads, it is no longer ready to be chosen.

    The half-tone (`\\033[2m`) asks for no colour, so no theme hides it. A dimmed
    line can still be chosen, and the next screen says how to make it ready.
    Applied after the truncation, which would count the ANSI codes.
    """
    return f"\033[2m{text}\033[0m"


def repaint(lines: list[str], painted: int, highlight: int | None = None,
             dimmed: Collection[int] = ()) -> int:
    """Rewrites a block of lines in place; returns the number of lines drawn.

    `painted` is how many lines the previous turn drew, gone back up over.
    `\\033[K` clears the end of the lines that shrink, `\\033[J` those a filter
    removes. `dimmed` ranks lines in `lines` (see `dim`); the highlight wins.
    """
    columns = shutil.get_terminal_size((100, 30)).columns
    texts = [fit(line, columns) for line in lines]
    # The bar stops at the longest line, not the window's edge, so the menu keeps
    # its shape on a wide terminal.
    width = min(max((console.width(text) for text in texts), default=0) + 1,
                columns - 1)
    out = [f"\033[{painted}A"] if painted else []
    for i, text in enumerate(texts):
        # The highlight is applied after the truncation: the ANSI codes do not
        # count towards the width, but they would count in the cutting.
        if i == highlight:
            text = emphasise(text, width)
        elif i in dimmed:
            text = dim(text)
        out.append(f"\r{text}\033[K\n")
    out.append("\033[J")
    sys.stdout.write("".join(out))
    sys.stdout.flush()
    return len(lines)


@dataclass
class View:
    """A menu built up in memory, ready to be rendered and driven.

    The same lines serve the numbered entry and the arrow driving. A filterable
    list builds it again at every character typed.
    """

    lines: list[str]
    targets: list[str]
    tokens: list[str]
    line_of: dict[int, int]
    shortcuts: dict[str, int]
    boxes: dict[int, tuple[str, str]]
    dimmed: set[int]
    numbered: int
    start: int
    raw: bool
    footer: int

    @property
    def keys(self) -> set[str]:
        """The lettered keys, those of the extras: they act, nothing more."""
        return {token for token in self.tokens if not token.isdigit()}


def compose(title: str, options: list[tuple[str | None, str]], *,
             extras: list[tuple[str | None, str]] | None = None,
             default: int | str | None = None,
             marks: dict[str, str] | None = None,
             disabled: Collection[str] = (),
             multi: bool = False,
             allow_back: bool = False, allow_quit: bool = False,
             extra_hints: tuple[str, ...] = ()) -> View:
    """Builds the menu: its lines, its targets, and which key goes to each.

    `extra_hints` go to the footer ahead of the usual ones (a filterable list's
    search, for one). The title and the labels are cleaned (`console.clean`): a
    title of Tadoku or of 青空文庫 comes from the web.
    """
    title = console.clean(title)
    options = [(key, console.clean(label)) for key, label in options]
    extras = [(key, console.clean(label)) for key, label in extras or []]
    marks = marks or {}
    disabled = frozenset(disabled)
    # Menus with subheadings shift their options one notch, so that the eye
    # tells the groups from their content; flat menus do not.
    pad = "    " if any(key is None for key, _label in [*options, *extras]) else "  "
    # Numbers flush right, so that labels stay aligned past the tenth. Dimmed
    # options are numbered too: a list missing its 5 is read twice to find the 6.
    width = len(str(sum(1 for key, _label in options if key is not None)))

    lines: list[str] = []
    targets: list[str] = []          # choosable keys, in the order displayed
    tokens: list[str] = []           # what one types for each, same order
    line_of: dict[int, int] = {}     # rank in `targets` -> line on screen
    shortcuts: dict[str, int] = {}   # character typed -> rank in `targets`
    boxes: dict[int, tuple[str, str]] = {}  # tickable rank -> (prefix, label)
    dimmed: set[int] = set()         # dimmed lines, by their rank in `lines`

    def offer(key: str, token: str, label: str, *,
              checkable: bool = False, faded: bool = False) -> None:
        shortcuts[token.lower()] = len(targets)
        line_of[len(targets)] = len(lines)
        if faded:
            dimmed.add(len(lines))
        tokens.append(token)
        targets.append(key)
        prefix = f"{pad}{token:>{width}}. "
        if multi:
            # Every label leaves room for a box, ticking or not, so the column holds.
            if checkable:
                boxes[len(targets) - 1] = (prefix, label)
            prefix += "[ ] " if checkable else "    "
        lines.append(f"{prefix}{label}")

    if title:
        # `splitlines` keeps one entry of `lines` to one screen line, which the
        # repaint counts on. No blank line if the screen already ends on one.
        lines += ([] if console.ends_blank() else [""]) + title.splitlines()
    # A subheading with no label is a blank line: it detaches what follows unnamed.
    numbered = 0
    for key, label in options:
        if key is None:
            lines += ["", f"  {label}"] if label else [""]
            continue
        numbered += 1
        offer(key, str(numbered), f"{label}{marks.get(key, '')}",
              checkable=key not in disabled, faded=key in disabled)
    for key, label in extras:
        if key is None:
            lines += ["", f"  {label}"] if label else [""]
            continue
        offer(key, key, f"{label}{marks.get(key, '')}", faded=key in disabled)

    # On keys, going back is Escape, recalled in the footer, rather than a line.
    # The footer lines this mode adds count before they are laid down.
    raw = raw_ready() and fits_on_screen(
        len(lines) + (2 if allow_back or multi else 0) + (1 if allow_quit else 0))
    if allow_back and not raw:
        offer("b", "b", _("Back"))
    if allow_quit:
        offer("q", "q", _("Quit"))

    # `default` is what one types (`shortcuts`), or a target the menu handed back
    # before ("vocab", typed "1"), found again in `targets`.
    start = shortcuts.get(str(default),
                          targets.index(default) if default in targets else 0)

    footer = 0
    if targets and raw:
        # Only the hints that cannot be guessed (going back, ticking); arrows and
        # Enter go without saying. `by_key` takes them away once the choice is made.
        hints = list(extra_hints) + ([_("Space to tick")] if multi else []
                     ) + ([_("Escape to go back")] if allow_back else [])
        if hints:
            lines += ["", f"  {listed(hints)}"]
            footer = 1
    return View(lines, targets, tokens, line_of, shortcuts, boxes, dimmed,
                 numbered, start, raw, footer)


# Seconds a number is given to be typed in full. Harmless if misjudged, since a
# number only aims: half a second is long for two digits in a row, short for two
# separate aims.
NUMBER_WINDOW = 0.5


def ticked(checked: set[str], targets: list[str]) -> list[str]:
    """The ticked keys, in screen order; those from elsewhere after them.

    A paged list is ticked over several screens: keys ticked on another page
    stay in the choice.
    """
    return ([key for key in targets if key in checked]
            + [key for key in checked if key not in targets])


def by_key(view: View, *, allow_back: bool, multi: bool = False,
                 checked: set[str] | None = None,
                 recompose: Callable[[str, int], View] | None = None
                 ) -> str | list[str]:
    """The same menu, driven by keys: arrows, Enter, Escape.

    Everything aims and Enter alone decides: a number or a letter only moves the
    highlight ("14" to the fourteenth line), so a key typed awry opens nothing.
    With `multi`, Space ticks the line aimed at and Enter validates the boxes, or
    the line when none is ticked.

    `recompose` rebuilds the list for a search, making it filterable (see
    `interactive.lists._tickable_pages`): letters write the search, digits still
    aim, Escape wipes the search before going back, PgDn/PgUp turn the pages.
    """
    index = view.start
    checked = checked if checked is not None else set()
    hint = view.lines[-1] if view.footer else ""
    typed = ""      # the number being struck, as long as it is still written
    search = ""     # what is typed in a filterable list
    # An Enter queued before this screen showed cannot validate a line nobody has
    # seen: it is skipped until the first other key, so "1 2 Enter" still chains.
    early = keyboard.pending()

    def replay(jump: int = 0) -> None:
        """Builds the list back up for the search in hand, and puts the aim on top."""
        nonlocal index, hint
        fresh = recompose(search, jump)
        if not fresh.targets:
            return  # a search that hands back nothing leaves the screen as it is
        view.__dict__.update(fresh.__dict__)
        hint = view.lines[-1] if view.footer else ""
        # Where the rebuilt list says to aim: its top after a keystroke, and
        # back on the current entry once Escape has wiped the search.
        index = view.start

    with keyboard.raw_mode():
        painted = 0
        while True:
            # The boxes are redrawn from `checked`, which holds the list's state.
            for rank, (prefix, label) in view.boxes.items():
                tick = "x" if view.targets[rank] in checked else " "
                view.lines[view.line_of[rank]] = f"{prefix}[{tick}] {label}"
            if multi and view.footer:
                # The count goes to the footer: on a second page, nothing else
                # says that the boxes of the first still hold.
                count = (agreed(len(checked), " - {count} ticked")
                         .format(count=len(checked)) if checked else "")
                view.lines[-1] = f"{hint}{count}"
            painted = repaint(view.lines, painted,
                               highlight=view.line_of[index], dimmed=view.dimmed)
            # Only the pause tells a two-digit number from two aims: past
            # `NUMBER_WINDOW`, a "2" after a "1" aims at the second, not the 12th.
            if typed and not keyboard.pending(NUMBER_WINDOW):
                typed = ""
            key = keyboard.read_key()
            ahead = early
            early = early and key == keyboard.ENTER and keyboard.pending()
            started, typed = typed, ""
            if key == keyboard.ENTER:
                if ahead:
                    continue
                break
            if key == keyboard.ESC and allow_back:
                if search:
                    search = ""
                    replay()
                    continue
                raise Back
            if (allow_back and recompose is None and len(key) == 1
                    and key.lower() == "b" and key.lower() not in view.shortcuts):
                # "b" is not shown but goes back, as in every question typed as
                # a line, unless the menu uses that letter or the list filters.
                raise Back
            if key == " " and index in view.boxes:
                checked.symmetric_difference_update({view.targets[index]})
            elif key in (keyboard.UP, keyboard.LEFT):
                index = (index - 1) % len(view.targets)
            elif key in (keyboard.DOWN, keyboard.RIGHT):
                index = (index + 1) % len(view.targets)
            elif key == keyboard.HOME:
                index = 0
            elif key == keyboard.END:
                index = len(view.targets) - 1
            elif recompose is not None and key in (keyboard.PGDN, keyboard.PGUP):
                replay(1 if key == keyboard.PGDN else -1)
            elif recompose is not None and key == keyboard.BACKSPACE and search:
                search = search[:-1]
                replay()
            elif key.isdigit():
                # A digit extends the number in hand only while that still names
                # an option: in a list of fourteen, "1" then "7" aims at the 7th.
                number = started + key if started + key in view.shortcuts else key
                if number in view.shortcuts:
                    index = view.shortcuts[number]
                    typed = number
            elif recompose is not None and len(key) == 1 and key.isprintable():
                search += key
                replay()
            elif len(key) == 1 and key.lower() in view.shortcuts:
                index = view.shortcuts[key.lower()]

    # A last pass takes the key hint away (what follows is left by "b", not
    # Escape) but keeps its blank line and the highlight on the line opened. The
    # block may only shrink: a line added would push it one notch down.
    shown = view.lines[:len(view.lines) - view.footer] if view.footer else view.lines
    repaint(shown, painted, highlight=view.line_of[index], dimmed=view.dimmed)
    if not multi:
        return view.targets[index]
    # A line that does not tick is an action, returned after the boxes. A line
    # that ticks gives way to the boxes when there are any.
    if index not in view.boxes:
        return ticked(checked, view.targets) + [view.targets[index]]
    return ticked(checked or {view.targets[index]}, view.targets)
