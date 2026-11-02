"""The dialogue of `kotogen reading`: an article, a document, a book, a work
of 青空文庫 or a text written on the deck, then how it is to be read."""

from __future__ import annotations

import threading

from kotogen import console, memory
from kotogen.i18n import _, agreed, convention, counted
from kotogen.interactive.audio import _ask_article_nhk
from kotogen.interactive.catalogues import _chosen_aozora, _chosen_exam_papers, _chosen_irodori
from kotogen.interactive.lists import _tickable_pages
from kotogen.interactive.screen import (
    _PROBE_NOTICE_DELAY,
    JLPT_LEVELS,
    _ask_auto_max,
    _ask_existing,
    _ask_int,
    _ask_pages,
    _ask_url,
    _Back,
    _columns,
    _header,
    _menu,
    _spin_while_alive,
    _submenu,
)

# Articles offered per site: the most recent screenful of a feed's ten to fifty.
ARTICLES_ROWS = 15


def _reading_source() -> str:
    # One entry per source, by what one holds rather than by what the card makes
    # of it, the catalogues one level down (as in `_audio_source`). The last has
    # a text written on what the deck is learning.
    while True:
        choice = _menu(_("Reading cards - where does the text come from?"),
                       _columns([
            ("article", _("An article"),
             _("NHK Easy and the Japanese press, from N5 to N1")),
            ("book", _("A book"), _("Tadoku albums, public domain, textbook")),
            ("jlpt", _("Official JLPT past papers"), _("the 読解 texts, by level")),
            ("url", _("A URL"), _("any Japanese page, or a PDF online")),
            ("file", _("A local file"),
             _("text, PDF or pictures - manga and albums")),
            ("deck", _("A tailored text"),
             _("the words and grammar you are learning, at your level")),
        ]), default=1, allow_back=True, memory="reading")
        try:
            if choice == "article":
                return _article_source()
            if choice == "book":
                # Each entry names its shelf; the right-hand column (see
                # `_columns`) says what is there and for whom.
                return _submenu(_("A book - which one?"), [
                    ("tadoku", "Tadoku",
                     _("albums graded for learners, from N5 to N1")),
                    ("aozora", "青空文庫",
                     _("the public domain: children N3-N2, literature N1")),
                    ("irodori", "いろどり",
                     _("a Japan Foundation textbook, one N5-N3 lesson")),
                ])
        except _Back:
            # A clean page, or the menu redraws under the submenu left behind
            # (see `_deck_mode`).
            _header()
            continue
        return choice


def _article_source() -> str:
    """NHK Easy and the press sites, on one screen filed by level.

    One scale, from the easy Japanese of NHK to native Japanese: the level on
    the left, as for the podcasts, then the genre. Hands back "nhk", or
    "press:<alias>" rather than a URL: the equivalent command stays readable,
    and only `press.catalogue()` knows the address of the feed.
    """
    from kotogen.generators import press

    known = press.catalogue()
    # The name last, after two columns: a long name followed by a description
    # would wrap past the hundredth screen column.
    entries = [("nhk", "N5-N4", "News", "NHK News Web Easy")]
    entries += [(f"press:{alias}", "N2-N1", site.genre, site.name)
                for _genre, group in press.by_genre(known) for alias, site in group]
    genres = max([10] + [console.width(_(genre)) + 2 for _key, _level, genre, _name in entries])
    options: list[tuple[str | None, str]] = [
        (key, f"{level:<7}{console.pad(_(genre), genres)}{name}")
        for key, level, genre, name in entries]
    options.append((None, ""))
    options.append(("press:", _("Another site (paste the URL of its RSS feed)")))
    return _menu(_("An article - from which site? "
                   "(from easy Japanese to native Japanese)"),
                 options, default=1, allow_back=True)


def _chosen_press(alias: str) -> list[str]:
    """The recent articles of the site already chosen, or of a feed whose URL one
    pastes.
    """
    from kotogen.generators import press

    known = press.catalogue()
    if alias not in known:
        return _chosen_article(_ask_url(_("URL of the site's RSS feed")))
    return _chosen_article(known[alias].url)


def _chosen_article(url: str) -> list[str]:
    """The recent articles of the feed; hands back the addresses of those ticked.

    The date leads each line, being part of the choice on a news feed. A silent
    feed asks for an address instead, as the article may still be reachable.
    Several can be ticked: a few pages of text cost little.
    """
    from kotogen.generators import feed, press

    articles: list = []
    worker = threading.Thread(
        target=lambda: articles.extend(_attempt(press.articles, url, ARTICLES_ROWS)))
    worker.start()
    worker.join(_PROBE_NOTICE_DELAY)
    if worker.is_alive():
        _spin_while_alive(worker, _("Recent articles..."))

    if not articles:
        return [_ask_url(_("URL of the article"))]

    def when(item) -> str:
        date = feed.when(item.published)
        # Day and month only, in the order of the language ("Aug 24", "24/08").
        return date.strftime(convention("short_date", "%b %d")) if date else ""

    # The title is the feed's: cleaned, and on one line.
    options = [(item.link, console.pad(when(item), 7) + " ".join(console.clean(item.title).split()))
               for item in articles]
    kept = set(_menu(counted(len(articles),
                             "{count} recent article",
                             "{count} recent articles").format(count=len(articles)),
                     options, multi=True, default=1, allow_back=True))
    # In the order of the feed, that of the screen, not that of the ticks.
    return [item.link for item in articles if item.link in kept]


def _attempt(function, *args) -> list:
    """Calls `function`, or says why it did not work and hands back an empty list.

    It runs in a thread, where an exception would die silently.
    """
    try:
        return list(function(*args))
    except Exception as exc:
        print(f"   {console.reason(exc, console.ALONE)}")
        return []


def _tadoku_books() -> list:
    """The catalogue of free books, saying so when the wait shows.

    An 800 KB page, several seconds on a bad line: a silent console would look
    like a crash.
    """
    from kotogen.generators import pdf_web

    books: list = []
    worker = threading.Thread(target=lambda: books.extend(pdf_web.books()))
    worker.start()
    worker.join(_PROBE_NOTICE_DELAY)
    if worker.is_alive():
        _spin_while_alive(worker, _("Free books from Tadoku..."))
    return books


def _chosen_book() -> list[str]:
    """Books from the Tadoku catalogue, filed by level, or a pasted URL.

    The catalogue is read on the site, which adds books every month. The level
    first, as one knows it of oneself, then the books of that level.
    """
    from kotogen.generators import pdf_web

    books = _tadoku_books()
    if not books:
        # Offline with nothing cached: the URL of a record still works.
        print("   " + _("Catalogue unreachable. The free books are here:"))
        print(f"   {pdf_web.FREE_BOOKS_URL}")
        return [_ask_url(_("URL of the book's record"))]

    levels = pdf_web.by_level(books)
    done = _already_done(books)
    # The JLPT level first, Tadoku's own step ("Level 3") after it; a step below
    # N5 leaves the box empty. The count is right-aligned, to compare at a glance.
    digits = len(str(max(len(group) for _label, group in levels)))
    options = _columns([(label, f"{group[0].jlpt:<7}{label}",
                         _("{count} {books}").format(
                             count=f"{len(group):>{digits}}",
                             books=console.plural(len(group), "book"))
                         + _books_done(group, done))
                        for label, group in levels])
    options.append((None, ""))
    options.append(("url", _("Another book (paste the URL of its record)")))
    choice = _menu(
        _("Free books from Tadoku - which level? "
          "({count} books, free to download)").format(count=len(books)),
        options, default=1, allow_back=True)
    if choice == "url":
        return [_ask_url(_("URL of the book's record"))]
    return _books_of_level(choice, dict(levels)[choice], done)


def _already_done(books: list) -> set[str]:
    """The URLs of the books that have already given cards, from both memories.

    The local history, true offline, and the deck, which knows what the other
    machines have done. Read once for both screens.
    """
    from kotogen.generators import pdf_web

    known, deck = pdf_web.load_seen(), memory.known().sources()
    return {book.url for book in books
            if pdf_web.book_id(book.url) in known
            or deck.knows("reading", book.url)}


def _books_done(books: list, done: set[str]) -> str:
    """", 3 already handled" behind the count of a level, or "" if it is new.

    "Handled", not "read": the book has given cards, as the history screen says.
    """
    count = sum(1 for book in books if book.url in done)
    return (agreed(count, ", {count} already handled", "book")
            .format(count=count) if count else "")


def _books_of_level(label: str, books: list, done: set[str]) -> list[str]:
    """The books of a level, by screenfuls; hands back the URLs ticked.

    Paged, as a level holds up to thirty-seven books and a menu taller than the
    terminal redraws awry; searchable, and tickable across pages (see
    `_tickable_pages`). `done`: the URLs of the books already handled, marked
    but still offered (see `_already_done`).
    """
    # The mark follows the title rather than a column, which a Japanese title
    # would shift. The box stays tickable, for other pages of a book.
    entries = [(book.url, book.title) for book in books]
    marks = {book.url: _(" (already handled)") for book in books
             if book.url in done}
    jlpt = f" ({books[0].jlpt})" if books[0].jlpt else ""
    # In the order of the level, whatever the order or page of the ticks (see
    # `_tickable_pages`).
    return _tickable_pages(f"{label}{jlpt}", entries,
                           lambda n: console.plural(n, "book"), marks)


def _deck_story_options() -> list[str]:
    """The shape, the level and the length of a text written on the deck, and
    how many.

    Asked here because the text is paid for as written: no template setting
    changes it later. Each menu remembers its last choice for the session. The
    level comes before the length, which it sets (see `_deck_story_lengths`).
    """
    from kotogen.generators import deck_story

    shape = _menu(_("A tailored text - which shape?"), _columns([
        ("story", _("A story"), _("everyday life, told or in dialogue")),
        ("exam", _("JLPT reading"), _("a notice, an e-mail, an essay, as the exam sets them")),
    ]), default=1, allow_back=True, memory="deck_story_shape")
    level = _menu(_("A tailored text - which level?"),
                  [(level, level) for level in JLPT_LEVELS]
                  + [("auto", _("The level of the deck"))],
                  default="auto", allow_back=True, memory="deck_story_level")
    length = _menu(_("A tailored text - which length?"),
                   _columns(_deck_story_lengths(level)),
                   default=1, allow_back=True, memory="deck_story_length")
    argv = ["reading", deck_story.KEYWORD]
    if shape != "story":
        argv += ["--shape", shape]
    if level != "auto":
        argv += ["--level", level]
    if length != "short":
        argv += ["--length", length]
    texts = _ask_int(_("Number of texts to write"), 1)
    if texts != 1:
        argv += ["--texts", str(texts)]
    return argv


def _deck_story_lengths(level: str) -> list[tuple[str, str, str]]:
    """The lengths a text at `level` can take, each with its size.

    With the level of the deck, unknown until it is read, each length gives its
    range across the levels. A level asked for gives its own figure, and below
    N3 no 長文, which the exam does not set there.
    """
    from kotogen.generators import deck_story

    if level not in deck_story.CHARACTERS:
        return [
            ("short", deck_story.EXAM_NAMES["short"], _("80 to 200 characters")),
            ("medium", deck_story.EXAM_NAMES["medium"], _("250 to 500 characters")),
            ("long", deck_story.EXAM_NAMES["long"],
             _("550 to 1,000 characters, from N3 up")),
        ]
    separator = convention("thousands_separator", ",")
    return [(length, deck_story.EXAM_NAMES[length],
             counted(size, "about {count} character", "about {count} characters")
             .format(count=f"{size:,}".replace(",", separator)))
            for length, size in deck_story.CHARACTERS[level].items()]


def _reading_options(source: str) -> list[str]:
    argv = ["reading"]
    if source == "deck":
        argv = _deck_story_options()
    elif source == "nhk":
        # As for listening: one source, and which article is asked afterwards.
        article = _ask_article_nhk()
        if article is not None:
            argv.append(article)
        else:
            argv.append("nhk")
            latest = _ask_int(_("Number of recent articles to handle"), 4)
            if latest != 4:
                argv += ["--latest", str(latest)]
    else:
        # The pages are asked before the mode (text or mini-book), which is only
        # settled once the document is open: they bound both alike.
        from kotogen.generators import pdf_pages, pdf_web, sources  # late

        if source == "tadoku":
            entries, document = _chosen_book(), True
        elif source == "aozora":
            # A web page: no pages to bound, no mini-book. Its length is the
            # resume cursor's business, without a question.
            entries, document = _chosen_aozora(), False
        elif source == "jlpt":
            entries, document = [_chosen_exam_papers("reading")], True
        elif source == "irodori":
            entries, document = [_chosen_irodori("reading")], True
        elif source.startswith("press:"):
            # A web page: no pages to bound, no mini-book. A bare "press:" is a
            # site not in the list, its feed address to be pasted.
            entries = _chosen_press(source.removeprefix("press:"))
            document = False
        elif source == "url":
            entry = _ask_url()
            entries, document = [entry], pdf_web.is_source(entry)
        else:
            entry = str(_ask_existing(_("Path of the file or folder")))
            entries = [entry]
            document = sources.is_pdf(entry) or pdf_pages.is_image_source(entry)
        argv += entries
        # A page range aims at one document, so it is not asked for several.
        if document and len(entries) == 1:
            pages = _ask_pages(_("Pages to keep"))
            if pages:
                argv += ["--pages", pages]

    # A ceiling, not a quota: by default the content sets it.
    count = _ask_auto_max(_("Max number of questions per reading"))
    if count is not None:
        argv += ["--count", str(count)]
    return argv
