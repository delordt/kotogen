"""PDFs coming from the web: the URL of a PDF, or the page of a free Tadoku book.

A Tadoku book page (にほんごたどく, tadoku.org) carries two PDFs: the ebook, in
reading order, which the mini-book needs, and an imposed version for printing.
A page with no PDF is a book for sale. The free-books page lists every book in
its HTML (its JavaScript only filters), which `books()` turns into a menu.
"""

from __future__ import annotations

import http.client
import json
import re
import time
import urllib.parse
from html import unescape
from pathlib import Path
from typing import NamedTuple

from kotogen import seen, system
from kotogen.exporter import cache_dir
from kotogen.generators import download
from kotogen.generators.text_source import is_url
from kotogen.i18n import _

# Past this it is not a book; the API's own limit (`MAX_PDF_BYTES`) is checked
# afterwards, with its own message.
MAX_DOWNLOAD = 40 * 1024 * 1024

_BOOK_URL_RE = re.compile(r"https?://(?:www\.)?tadoku\.org/japanese/book/\d+", re.I)
_PDF_LINK_RE = re.compile(r'href="([^"]+\.pdf)"', re.I)
# "f0048e-arimasuka-v4.pdf", "w0009e-tureduregusa_v6.pdf": the letter "e"
# following the reference names the ebook, "p" the version to print.
_EBOOK_RE = re.compile(r"[a-z]+\d+e[-_]", re.I)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
# Titles are in <ruby>: the readings are dropped rather than glued to the kanji,
# the title only going to the console.
_RT_RE = re.compile(r"<rt[^>]*>.*?</rt>|<rp[^>]*>.*?</rp>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


# -- Recognising the input ----------------------------------------------------

def is_pdf_url(s: str) -> bool:
    """True if the input is the URL of a PDF (the path ends in .pdf)."""
    if not is_url(s):
        return False
    return urllib.parse.urlsplit(s.strip()).path.lower().endswith(".pdf")


def is_book_url(s: str) -> bool:
    """True if the input is a Tadoku book page (tadoku.org/japanese/book/N)."""
    return bool(_BOOK_URL_RE.match((s or "").strip()))


def is_source(s: str) -> bool:
    """True if the input is a PDF to bring back before doing anything at all."""
    return is_book_url(s) or is_pdf_url(s)


# -- Downloading --------------------------------------------------------------

def _download(url: str, timeout: float = 60) -> bytes:
    """Downloads a URL. Raises RuntimeError with a reason in plain words."""
    try:
        with download.open_url(url, timeout, download.HEADERS) as response:
            announced = int(response.headers.get("Content-Length") or 0)
            data = response.read(MAX_DOWNLOAD + 1)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise download.failure(exc, url) from exc

    if len(data) > MAX_DOWNLOAD:
        raise RuntimeError(
            _("outsized file (over {limit} MB) - this is not a book.")
            .format(limit=MAX_DOWNLOAD // (1024 * 1024)))
    download.check_whole(len(data), announced)
    return data


# -- The page of a Tadoku book ------------------------------------------------

def pick_ebook(links: list[str]) -> str:
    """Among the PDFs of a page, the one that is read (and not the one printed).

    With no marker recognised, the first link, as on a page with a single PDF.
    """
    for link in links:
        if _EBOOK_RE.match(link.rsplit("/", 1)[-1]):
            return link
    return links[0]


def resolve_book(url: str) -> tuple[str, str]:
    """A Tadoku book page -> (URL of the PDF to read, title of the book)."""
    html = _download(url).decode("utf-8", errors="replace")
    # Absolute, and on the web: the page is someone else's.
    links = [link for link in dict.fromkeys(
        urllib.parse.urljoin(url, href) for href in _PDF_LINK_RE.findall(html))
        if download.is_web(link)]
    if not links:
        raise RuntimeError(
            _("no PDF on this page: this book is not free (the page only offers "
              "to sell it). The downloadable books are those of "
              "https://tadoku.org/japanese/free-books/"))
    found = _H1_RE.search(html)
    title = " ".join(_TAG_RE.sub("", _RT_RE.sub("", found.group(1))).split()) if found else ""
    return pick_ebook(links), title


# -- Entry point --------------------------------------------------------------

def cache_name(url: str) -> str:
    """The name a downloaded PDF is cached under: its site, then its own name.

    The site and a fingerprint of the whole address, so that two sites' or two
    folders' `sample.pdf` stay two files; the PDF's name, version included, so
    that a new version of a book is downloaded afresh.
    """
    name = Path(urllib.parse.urlsplit(url).path).name or "book.pdf"
    # A path segment may carry what a Windows file name cannot.
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return f"{download.url_key(url)}-{name}"


def fetch(source: str) -> tuple[Path, str]:
    """A URL (Tadoku page or direct PDF) -> (local PDF kept in cache, book title).

    Cached by `cache_name`, so a book asked for twice is downloaded once. The
    title is returned because the file does not carry it. Prints nothing: the
    caller announces the books in one batch.
    """
    # Late: downloading a PDF has no business loading the model's instructions.
    from kotogen.generators.pdf_source import MAX_PDF_BYTES

    url = (source or "").strip()
    title = ""
    if is_book_url(url):
        url, title = resolve_book(url)

    path = cache_dir() / "books" / cache_name(url)
    if path.is_file() and path.stat().st_size > 0:
        return path, title

    data = _download(url)
    if not data.startswith(b"%PDF"):
        raise RuntimeError(_("this address does not give back a PDF: {url}")
                           .format(url=url))
    if len(data) > MAX_PDF_BYTES:
        raise RuntimeError(
            _("PDF too large ({size} MB > {limit} MB) - download it and split it.")
            .format(size=len(data) // (1024 * 1024),
                    limit=MAX_PDF_BYTES // (1024 * 1024)))

    # Under a working name first: a write cut short (Ctrl+C, a full disk) must
    # not pass for the book on the next run.
    path.parent.mkdir(parents=True, exist_ok=True)
    draft = path.with_suffix(path.suffix + ".part")
    try:
        draft.write_bytes(data)
        draft.replace(path)
    finally:
        draft.unlink(missing_ok=True)
    return path, title

# -- The catalogue of free books ----------------------------------------------
# As the template catalogue: it never raises, and the disk keeps the last list
# known, an out-of-date menu being better than an empty one.

FREE_BOOKS_URL = "https://tadoku.org/japanese/free-books/"

# The catalogue gains a few books a month: past that, we ask again.
BOOKS_MAX_AGE = 30 * 24 * 3600

# Split on the book's container, which carries its level, rather than on the
# links: each block links its page several times (thumbnail, title, suggestions).
_ITEM_SPLIT_RE = re.compile('(?=<div class="[^"]*freebooks-book-item)')
_ITEM_LEVEL_RE = re.compile('data-order-level="([^"]*)"')
_ITEM_BOOK_RE = re.compile(
    '<div class="bl-title">.*?'
    '<a href="(https://tadoku[.]org/japanese/book/[0-9]+/)">(.*?)</a>', re.S)

# The order of the site, from the first step to continuous text.
LEVEL_ORDER = ("l-start", "l0", "l1", "l2", "l3", "l4", "l5")
LEVEL_LABELS = {"l-start": "Start"}

# The JLPT level of each step, as the site itself announces it
# (tadoku.org/japanese/levels). Start and Level 0, below N5, carry none.
LEVEL_JLPT = {"l1": "N5", "l2": "N4", "l3": "N3", "l4": "N3-N2", "l5": "N2-N1"}


class Book(NamedTuple):
    """A free book: its level, its title, the URL of its page."""

    level: str    # "l0", "l-start"...: the rank of the site
    title: str
    url: str

    @property
    def label(self) -> str:
        """The level as it is displayed: "Level 3", "Start"."""
        return LEVEL_LABELS.get(self.level) or _("Level {rank}").format(
            rank=self.level.lstrip("l"))

    @property
    def jlpt(self) -> str:
        """The matching JLPT level, or "" for the steps below N5."""
        return LEVEL_JLPT.get(self.level, "")


def clean_title(raw: str) -> str:
    """A book title stripped of its tags, its ruby and its entities."""
    return " ".join(unescape(_TAG_RE.sub("", _RT_RE.sub("", raw))).split())


def parse_books(html: str) -> list[Book]:
    """The page of free books -> the list of books, in the order of the site."""
    books: list[Book] = []
    for chunk in _ITEM_SPLIT_RE.split(html)[1:]:
        level = _ITEM_LEVEL_RE.search(chunk)
        book = _ITEM_BOOK_RE.search(chunk)
        if level and book:
            books.append(Book(level.group(1), clean_title(book.group(2)),
                              book.group(1)))
    return books


def by_level(books: list[Book]) -> list[tuple[str, list[Book]]]:
    """The books filed by level, from the simplest to the densest.

    Empty levels do not appear; a level the site adds comes last.
    """
    groups: dict[str, list[Book]] = {}
    for book in books:
        groups.setdefault(book.level, []).append(book)
    known = [level for level in LEVEL_ORDER if level in groups]
    unknown = sorted(level for level in groups if level not in LEVEL_ORDER)
    return [(groups[level][0].label, groups[level]) for level in known + unknown]


def books_cache_file() -> Path:
    return cache_dir() / "tadoku-books.json"


def _read_books_cache() -> tuple[list[Book], float] | None:
    try:
        data = json.loads(books_cache_file().read_text(encoding="utf-8"))
        return [Book(*entry) for entry in data["books"]], float(data["fetched"])
    except (OSError, ValueError, KeyError, TypeError):
        # Absent, truncated or of another shape: treated as absent, and rewritten.
        return None


def _write_books_cache(books: list[Book], fetched: float) -> None:
    try:
        system.write_whole(books_cache_file(), json.dumps(
            {"fetched": fetched, "books": [list(b) for b in books]}))
    except OSError:
        pass  # full disk, read-only folder: we do without


def books(*, refresh: bool = False, timeout: int = 20) -> list[Book]:
    """The free books, from the cache if it is fresh, from the site otherwise.

    Never raises: with the site unreachable, the cached list, or [] when nothing
    is known and the menu falls back on asking for the URL of the book.
    """
    cached = _read_books_cache()
    if not refresh and cached and time.time() - cached[1] < BOOKS_MAX_AGE:
        return cached[0]
    try:
        found = parse_books(_download(FREE_BOOKS_URL, timeout=timeout)
                            .decode("utf-8", "replace"))
    except (RuntimeError, OSError, TimeoutError):
        return cached[0] if cached else []
    if not found:
        # Served but unreadable (a redesign): the cache stays, not overwritten.
        return cached[0] if cached else []
    _write_books_cache(found, time.time())
    return found


# -- Books already handled ----------------------------------------------------
# Kept in the shared history (`seen`) like NHK or a podcast, but a handled book is
# only marked, never skipped: rereading it for other pages or other questions is
# a legitimate request.

SOURCE = "tadoku"

_BOOK_ID_RE = re.compile(r"/book/(\d+)")


def book_id(url: str) -> str:
    """The number a book page carries, or "" if it is not one.

    Checked with `is_book_url`, not by the number alone: a PDF under /book/12/
    elsewhere is not Tadoku's book 12.
    """
    text = (url or "").strip()
    found = _BOOK_ID_RE.search(text) if is_book_url(text) else None
    return found.group(1) if found else ""


def load_seen(mode: str = "reading") -> dict[str, str]:
    """The books already handled by this mode: {page number: title}."""
    return seen.load(mode, SOURCE)


def mark_seen(url: str, title: str = "", mode: str = "reading") -> None:
    """Memorises that a book gave cards.

    A URL that is not a book page gives an empty identifier, which `seen.mark`
    ignores.
    """
    seen.mark(mode, SOURCE, book_id(url), title)
