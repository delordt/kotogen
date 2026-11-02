"""The catalogues the listening and the reading dialogues both draw from.

The past papers of the JLPT, the いろどり lessons, the readings of 青空朗読 and
the works of 青空文庫: each is offered with what has already been made of it.
"""

from __future__ import annotations

import threading

from kotogen import console, memory, menu, seen
from kotogen.i18n import _, agreed
from kotogen.interactive.lists import _tickable_pages
from kotogen.interactive.screen import (
    _PROBE_NOTICE_DELAY,
    _ask,
    _ask_url,
    _Back,
    _columns,
    _header,
    _menu,
    _spin_while_alive,
    _submenu,
)

# ── Catalogue sources ─────────────────────────────────────────────────────────
# Each entry shows what has already been made of it, which memory alone cannot
# tell on lists of hundreds of Japanese titles.


def _chosen_exam_papers(mode: str) -> str:
    """The level of the past papers, then the collection they are taken from.

    The level first, as one knows it of oneself; the collections set the same
    exercise, so their screen shows how much of each is left at that level.
    `mode` picks what that is: the reading booklet or the listening sections.
    """
    from kotogen.generators import jlpt_papers

    while True:
        level = _menu(_("Official JLPT past papers - which level?"),
                      [(level, level) for level in jlpt_papers.LEVELS],
                      default=3, allow_back=True)
        try:
            # The year is in each collection's name, as the site publishes them.
            # The menu opens on the one the bare alias `jlpt` names, so that the
            # menu and the command line agree on "the" past papers.
            return _submenu(
                _("Official JLPT past papers - which collection? ({level})")
                .format(level=level),
                [(f"{key}-{level.lower()}", collection.name,
                  _exam_papers_state(collection, level, mode))
                 for key, collection in jlpt_papers.COLLECTIONS.items()],
                default=f"{jlpt_papers.DEFAULT}-{level.lower()}")
        except _Back:
            # Back to the levels, on a clean page: `_submenu` left its screen.
            _header()


def _exam_papers_state(collection, level: str, mode: str) -> str:
    """What this collection carries at this level, and what has been made of it."""
    from kotogen.generators import jlpt_papers

    target = jlpt_papers.Target(collection, level)
    if mode == "reading":
        return _("読解 booklet") + (_(" (already handled)")
                                    if jlpt_papers.is_read(target) else "")
    left, done = jlpt_papers.tracks(target)
    total = done + len(left)
    part = (agreed(done, ", {count} already handled", "section")
            .format(count=done) if done else "")
    return _("{count} listening {sections}").format(
        count=total, sections=console.plural(total, "section")) + part


def _chosen_irodori(mode: str) -> str:
    """The volume of いろどり, with the lesson one is up to.

    A textbook is followed in order, and every volume has eighteen lessons: what
    shows beside the name is the one reached.
    """
    from kotogen.generators import irodori

    options: list[tuple[str | None, str]] = [
        (alias, f"{irodori.level_label(volume.levels):<7}{volume.name}"
                f"{_irodori_state(volume, mode)}")
        for alias, volume in irodori.VOLUMES.items()]
    return _menu(_("いろどり 生活の日本語 - which volume? "
                   "(18 lessons each, Japan Foundation, free)"),
                 options, default=irodori.DEFAULT, allow_back=True)


def _irodori_state(volume, mode: str) -> str:
    """" - picks up at lesson 4", or nothing when one has not begun."""
    from kotogen.generators import irodori

    lessons, done = irodori.lessons(volume, 1, mode=mode)
    if not done:
        return ""
    if not lessons:
        return _(" (all 18 lessons are done)")
    return _(" - picks up at lesson {rank}").format(rank=lessons[0].rank)


def _chosen_roudoku() -> list[str]:
    """The shortest reading not yet done, or readings ticked in the library.

    The library is filed by duration, its fifteen hundred works running from
    under a minute to two and a half hours, so the default takes the shortest one
    left.
    """
    from kotogen.generators import aozora_roudoku as roudoku
    from kotogen.generators.nhk import format_duration

    choice = _menu(_("青空朗読 - which reading? "
                     "(public domain works, read aloud)"), _columns([
                         ("next", _("The shortest not yet handled"),
                          _("the library goes up from the shortest to the longest")),
                         ("list", _("Choose from the library"),
                          _("every reading, by increasing duration")),
                     ]), default=1, allow_back=True)
    if choice == "next":
        return ["roudoku"]

    readings = _roudoku_library()
    if not readings:
        print("   " + _("Library unreachable. The shortest not yet handled stays"
                        " reachable without a catalogue."))
        return ["roudoku"]
    # Both memories, as everywhere: the local file, then the deck, which knows
    # what the other machines have done.
    done = seen.load("audio", roudoku.SOURCE)
    deck, library = memory.known().sources(), roudoku.Library()
    # As wide as the longest duration shown: the library runs to two and a half
    # hours, and 分 and 秒 take two columns each.
    durations = [format_duration(reading.duration) for reading in readings]
    column = max(console.width(duration) for duration in durations)
    entries = [
        (reading.page,
         f"{console.pad_left(duration, column)}  {reading.label}"
         + (_(" (already handled)")
            if reading.reading_id in done
            or deck.knows("audio", roudoku.provenance(library, reading)) else ""))
        for reading, duration in zip(readings, durations)]
    return _tickable_pages("青空朗読", entries,
                           lambda n: console.plural(n, "reading")) or ["roudoku"]


def _roudoku_library() -> list:
    """The catalogue of 青空朗読, saying so when the wait shows."""
    from kotogen.generators import aozora_roudoku as roudoku

    readings: list = []
    worker = threading.Thread(target=lambda: readings.extend(roudoku.catalogue()))
    worker.start()
    worker.join(_PROBE_NOTICE_DELAY)
    if worker.is_alive():
        _spin_while_alive(worker, _("Library of 青空朗読..."))
    return readings


def _chosen_aozora() -> list[str]:
    """The 青空文庫 library: a shelf, an author, then the works ticked.

    Three steps for ten thousand works: the shelf, as children's books and
    literature lie a whole syllabus apart, then the author, the best supplied
    first, since 多読 is done inside one author.
    """
    from kotogen.generators import aozora

    works = _aozora_library()
    if not works:
        print("   " + _("Catalogue unreachable. The library is here:"))
        print("   https://www.aozora.gr.jp/")
        return [_ask_url(_("URL of the work or its record"))]

    options: list[tuple[str | None, str]] = [
        (key, f"{level:<7}{name}  "
              + _("({count} works)").format(count=len(aozora.shelf(works, key)))
              + f" - {what}")
        for key, name, level, what in aozora.SHELVES]
    options.append((None, ""))
    options.append(("search", _("Search by title or by author")))
    choice = _menu(_("青空文庫 - what to read? ({count} works in modern"
                     " spelling)").format(count=len(works)),
                   options, default=1, allow_back=True)
    if choice == "search":
        if menu.raw_ready():
            # The whole library in one list, searched as one types, rather than a
            # blind search field first.
            return _ticked_works("青空文庫", aozora.by_shelf(works), levelled=True)
        found = aozora.search(works, _ask(_("Title or author"), back=True))
        if not found:
            print("   " + _("Nothing of that name in the library."))
            return []
        return _ticked_works(_("Results"), found)

    authors = aozora.by_author(aozora.shelf(works, choice))
    entries = [(name, f"{name}  "
                      + _("({count} works)").format(count=len(works_of)))
               for name, works_of in authors]
    kept = _tickable_pages(_("Which author?"), entries,
                           lambda n: console.plural(n, "author"))
    if not kept:
        return []
    # Several authors: their works in one block, in the order of the authors.
    by_name = dict(authors)
    return _ticked_works(" / ".join(kept),
                         [work for name in kept for work in by_name[name]])


def _ticked_works(title: str, works: list, *, levelled: bool = False) -> list[str]:
    """The works of an author or of a search, tickable; hands back their addresses.

    `levelled` heads each line with the level of its shelf, for a list mixing
    shelves: the index gives no level for a single work.
    """
    from kotogen.generators import aozora

    # Both memories, as for the Tadoku books: the deck is compared on the
    # address of the page read, which the card keeps.
    done, deck = aozora.load_seen(), memory.known().sources()
    entries = [
        (work.url,
         (f"{aozora.level_of(work):<7}" if levelled else "")
         + f"{work.title} - {work.author}"
         + (_(" (already handled)") if work.work_id in done
            or deck.knows("reading", work.url) else ""))
        for work in works]
    return _tickable_pages(title, entries, lambda n: console.plural(n, "work"))


def _aozora_library() -> list:
    """The index of the library, saying so when the wait shows.

    Two megabytes and nineteen thousand lines the first time, then nothing for a
    month: a silent console would look like a crash.
    """
    from kotogen.generators import aozora

    works: list = []
    worker = threading.Thread(target=lambda: works.extend(aozora.catalogue()))
    worker.start()
    worker.join(_PROBE_NOTICE_DELAY)
    if worker.is_alive():
        _spin_while_alive(worker, _("Library of 青空文庫..."))
    return works
