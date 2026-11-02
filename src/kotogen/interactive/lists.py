"""The lists too long to go through with an arrow.

Two hundred rules or books are shown a page at a time, narrowed by what one
types, and ticked: the boxes hold while the search changes, and what comes back
is the keys ticked.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable

from kotogen import console, menu
from kotogen.i18n import _, quoted
from kotogen.interactive.screen import _header, _menu

# Lines displayed at once, books of a level or rules alike: a menu taller than
# the terminal would redraw itself crookedly under the arrow keys.
BOOKS_ROWS = 15


# ── Searching in a list ───────────────────────────────────────────────────────
# What one types narrows the list, found in the Japanese (にく), its romanisation
# (niku) or the gloss (diffi): the whole label is searched.

def _unaccented(text: str) -> str:
    """`Difficult` and `difficult`, `rōmaji` and `romaji`: the same word."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _searchable(label: str) -> str:
    """What a keystroke is searched in: the label, and its romanisation.

    Both together, so that にくい is found by にく as by niku.
    """
    from kotogen.furigana import to_romaji  # late: the assistant starts light

    return _unaccented(label) + " " + _unaccented(to_romaji(label))


def _matches(search: str, haystack: str) -> bool:
    """Are all the bits typed to be found in it? (the order does not matter)"""
    return all(bit in haystack for bit in _unaccented(search).split())


# What was ticked on previous screens stays counted, and the title says out of
# how many one is choosing.

# The prefix of a typed entry the list does not hold, offered as it stands. Never
# shown, it lets the caller recognise what it did not offer.
FREE = "\x00free:"


# A key and its label, or a key and the two parts of its label (what is chosen,
# what it means), the second shape laid out in two columns.
_Row = tuple[str, str] | tuple[str, str, str]


def _laid_out(page: list[_Row]) -> list[tuple[str, str]]:
    """Lays a PAGE out in two columns, the width taken from that page alone.

    Grammar titles run from two screen columns to forty: the width of the whole
    list would open a gutter before every short rule. The column moves only
    between pages, which replace each other. Counted in screen columns, a kana
    taking two. An entry in one part (the free entry) goes through as it is.
    """
    column = max((console.width(row[1]) for row in page if len(row) == 3),
                 default=0)
    return [(row[0], f"{console.pad(row[1], column)}  {row[2]}")
            if len(row) == 3 else (row[0], row[1])
            for row in page]


def _tickable_pages(title: str, entries: list[_Row],
                    unit: Callable[[int], str] | None = None,
                    marks: dict[str, str] | None = None, *,
                    locate: bool = True, free: str = "",
                    elsewhere: list[_Row] = ()) -> list[str]:
    """A list too long for the screen, tickable and searchable; hands back the ticked keys.

    Ticks survive the change of page, a page replaces the previous one, and keys
    come back in the order of the list. At the keyboard, typing searches (see
    `_searchable`) and the Page keys turn pages; without one (redirected output,
    tests, no ANSI), "n" and "p" do and entries are numbered.

    `marks` signs an entry that can still be chosen. `locate` puts the count of
    the list behind the title. `elsewhere` is reached by a search only (another
    JLPT level, say). `free` labels the entry offered when a search finds
    nothing, saying what it does, its `{name}` taking the keystroke; its key
    carries `FREE`.
    """
    unit = unit or (lambda n: console.plural(n, "entry", "entries"))
    checked: set[str] = set()
    keys = [row[0] for row in entries]
    if menu.raw_ready():
        kept = _search_and_tick(title, entries, unit, marks,
                                checked, locate=locate, free=free,
                                elsewhere=elsewhere)
        # The order of the list, then what was not in it (another level, a free
        # entry).
        in_the_list = set(keys)
        return ([key for key in keys if key in checked]
                + [key for key in kept if key not in in_the_list])

    start = 0
    while True:
        _header()
        page = _laid_out(entries[start:start + BOOKS_ROWS])
        left = len(entries) - start - len(page)
        turn: list[tuple[str | None, str]] = []
        if start:
            turn.append(("p", _("See the previous {count} again").format(
                count=min(start, BOOKS_ROWS))))
        if left:
            turn.append(("n", _("See the next {count}").format(count=left)))
        extras = [(None, ""), *turn] if turn else []
        choice = _menu(_("{title} - {count} {unit}").format(
                           title=title, count=len(entries),
                           unit=unit(len(entries))),
                       page, extras=extras, multi=True, checked=checked,
                       marks=marks, default=1, allow_back=True)
        checked = {key for key in choice if key not in ("n", "p")}
        if "n" in choice:
            start += BOOKS_ROWS
            continue
        if "p" in choice:
            start = max(0, start - BOOKS_ROWS)
            continue
        return [key for key in keys if key in checked]


def _search_and_tick(title: str, entries: list[_Row], unit: Callable[[int], str],
                     marks: dict[str, str] | None, checked: set[str], *,
                     locate: bool = True, free: str = "",
                     elsewhere: list[_Row] = ()) -> list[str]:
    """The same list, but searchable: the keystroke narrows it, the boxes hold.

    The search and the page live here and survive every rebuild; the menu holds
    the boxes, which is how they survive a filter.
    """
    state = {"start": 0}
    # Both parts searched together: a rule is reached by its name or its meaning.
    haystacks = {row[0]: _searchable(" ".join(row[1:]))
                 for row in [*entries, *elsewhere]}

    def build(search: str, jump: int) -> menu.View:
        kept = [row for row in entries
                if not search or _matches(search, haystacks[row[0]])]
        # Matches from outside the list, only when one types, after it: their
        # level, in the left column, tells them apart.
        others = [row for row in elsewhere
                  if search and _matches(search, haystacks[row[0]])]
        kept += others
        # Found nowhere: the keystroke is offered as it stands.
        nothing = free and search and not kept
        if nothing:
            kept = [(FREE + search, free.format(name=quoted(search)))]  # one part
        # A keystroke goes back to the top; a Page key moves within what is left.
        pages = max(0, (len(kept) - 1) // BOOKS_ROWS)
        state["start"] = (min(max(state["start"] // BOOKS_ROWS + jump, 0), pages)
                          * BOOKS_ROWS) if jump else 0
        page = _laid_out(kept[state["start"]:state["start"] + BOOKS_ROWS])
        # The title counts what is kept, and the page. The free entry is not one
        # of the list, hence "nothing found" rather than "1 of 200".
        if nothing:
            located = _(" - nothing found")
        elif search:
            located = _(" - {count} of {total}").format(count=len(kept),
                                                        total=len(entries))
        elif locate:
            located = _(" - {count} {unit}").format(
                count=len(entries), unit=unit(len(entries)))
        else:
            located = ""
        if others:
            located += _(", including {count} outside this list").format(
                count=len(others))
        if pages:
            located += _(", page {page}/{total}").format(
                page=state["start"] // BOOKS_ROWS + 1, total=pages + 1)
        hints = ((_("Search: {search}_").format(search=search),) if search
                 else (_("type to search"),))
        if pages:
            hints += (_("PgUp/PgDn"),)
        return menu.compose(f"{title}{located}", page, multi=True,
                        marks=marks, default=1, allow_back=True,
                        extra_hints=hints)

    _header()
    view = build("", 0)
    if not view.targets:
        return []
    # What the menu hands back, not only the boxes: with nothing ticked, Enter
    # takes the line aimed at ("niku", Enter, done).
    kept = menu.by_key(view, allow_back=True, multi=True,
                        checked=checked, recompose=build)
    checked.clear()
    checked.update(key for key in kept if not key.startswith(FREE))
    return list(kept)
