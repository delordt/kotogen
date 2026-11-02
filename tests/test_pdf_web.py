"""PDFs brought back from the web: the page of a free Tadoku book, or a direct URL.

Nothing goes out on the network: the tests bear on the choices made around the
download, such as the ebook over the print PDF, imposed two pages per image.
"""

from __future__ import annotations

import http.client
import urllib.error
from pathlib import Path

import pytest

from kotogen.generators import download, pdf_web

# The two files of a Tadoku page: the ebook and its version to print.
EBOOK = "https://tadoku.org/japanese/wp-content/uploads/f0048e-arimasuka-v4.pdf"
PRINT = "https://tadoku.org/japanese/wp-content/uploads/f0048p-arimasuka-v4.pdf"


# -- Recognising the input ----------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://tadoku.org/japanese/book/6346/",
    "https://tadoku.org/japanese/book/61273",
    "http://www.tadoku.org/japanese/book/5371/#bd-look-inside",
])
def test_a_tadoku_book_page_is_recognised(url):
    assert pdf_web.is_book_url(url)
    assert pdf_web.is_source(url)


@pytest.mark.parametrize("url", [
    # The list of books is not a book: it has its own route (books()).
    "https://tadoku.org/japanese/free-books/",
    "https://tadoku.org/japanese/book-search?level=l3",
    "https://news.web.nhk/news/easy/ne2024XXXX/ne2024XXXX.html",
    "nhk",
    "book.pdf",
])
def test_what_is_not_a_book_page(url):
    assert not pdf_web.is_book_url(url)


def test_a_pdf_url_can_be_brought_back_wherever_it_comes_from():
    assert pdf_web.is_pdf_url(EBOOK)
    assert pdf_web.is_source(EBOOK)
    # A local PDF has nothing to download, and a page is not a PDF.
    assert not pdf_web.is_pdf_url("C:/books/tadoku.pdf")
    assert not pdf_web.is_source("https://example.jp/article.html")


def test_the_extension_is_read_on_the_path_not_on_the_query():
    assert pdf_web.is_pdf_url("https://example.jp/book.pdf?dl=1")
    assert not pdf_web.is_pdf_url("https://example.jp/page?doc=book.pdf")


# -- Picking the PDF on a page ------------------------------------------------

def test_the_ebook_is_preferred_to_the_version_to_print():
    """"f0048e-" is read, "f0048p-" is imposed two pages per sheet."""
    assert pdf_web.pick_ebook([PRINT, EBOOK]) == EBOOK
    assert pdf_web.pick_ebook([EBOOK, PRINT]) == EBOOK


def test_the_ebook_is_recognised_whatever_the_reference():
    # The references seen on the site: f0048e-..., w0009e-..._v6, no version.
    for name in ("w0009e-tureduregusa_v6.pdf", "f0118e-nemuimachi.pdf",
                 "f0086e-yamani-v4-1.pdf"):
        url = f"https://tadoku.org/japanese/wp-content/uploads/{name}"
        assert pdf_web.pick_ebook([url.replace("e-", "p-"), url]) == url


def test_one_single_pdf_asks_no_question():
    other = "https://example.jp/uploads/book.pdf"
    assert pdf_web.pick_ebook([other]) == other


# -- A page with no PDF: the book has to be paid for --------------------------

def test_a_page_with_no_pdf_says_the_book_is_not_free(monkeypatch):
    """A paid book carries only purchase links: say so, not "no PDF found"."""
    monkeypatch.setattr(pdf_web, "_download",
                        lambda url: b"<html><h1>A book</h1><a href='https://amazon'>buy</a></html>")
    with pytest.raises(RuntimeError) as excinfo:
        pdf_web.resolve_book("https://tadoku.org/japanese/book/4254/")
    assert "not free" in str(excinfo.value)


def test_a_page_gives_the_pdf_to_read_and_the_title_of_the_book(monkeypatch):
    html = (f'<html><h1>ありますか？</h1>'
            f'<li><a href="{EBOOK}" download>PDF(電子本)</a></li>'
            f'<li><a href="{PRINT}" download>PDF(印刷用)</a></li></html>').encode()
    monkeypatch.setattr(pdf_web, "_download", lambda url: html)
    assert pdf_web.resolve_book("https://tadoku.org/japanese/book/6346/") == (
        EBOOK, "ありますか？")


def test_the_title_loses_the_furigana_of_the_site(monkeypatch):
    """The titles on the site are in <ruby>: glued to the text, the readings
    would give "花はなすけ" in the console."""
    html = ('<h1><ruby>花<rp>(</rp><rt>はな</rt><rp>)</rp></ruby>すけ</h1>'
            f'<a href="{EBOOK}">PDF</a>').encode()
    monkeypatch.setattr(pdf_web, "_download", lambda url: html)
    assert pdf_web.resolve_book("https://tadoku.org/japanese/book/5371/")[1] == "花すけ"


def test_a_link_off_the_web_is_not_taken_for_the_book(monkeypatch):
    """The page is someone else's: a `file://` marked as the ebook would be
    picked before the web one."""
    html = (b'<a href="file:///C:/private/f0001e-diary.pdf">PDF</a>'
            b'<a href="https://example.jp/uploads/f0001p-book.pdf">PDF</a>')
    monkeypatch.setattr(pdf_web, "_download", lambda url: html)
    url, _title = pdf_web.resolve_book("https://tadoku.org/japanese/book/6346/")
    assert url == "https://example.jp/uploads/f0001p-book.pdf"


def test_a_relative_link_is_brought_back_to_the_address_of_the_page(monkeypatch):
    monkeypatch.setattr(pdf_web, "_download",
                        lambda url: b'<a href="/japanese/wp-content/uploads/f0048e-x.pdf">PDF</a>')
    url, _title = pdf_web.resolve_book("https://tadoku.org/japanese/book/6346/")
    assert url == "https://tadoku.org/japanese/wp-content/uploads/f0048e-x.pdf"


# -- Downloading --------------------------------------------------------------

def _counting(monkeypatch, tmp_path) -> list[str]:
    """Downloads served from memory, into a cache of the test: the URLs asked."""
    calls: list[str] = []

    def fake_download(url: str) -> bytes:
        calls.append(url)
        return b"%PDF-1.7 content of " + url.encode()

    monkeypatch.setattr(pdf_web, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(pdf_web, "_download", fake_download)
    return calls


def test_the_book_is_kept_in_cache_under_its_version_name(monkeypatch, tmp_path):
    """Two page ranges on the same book: one single download."""
    calls = _counting(monkeypatch, tmp_path)

    first, _title = pdf_web.fetch(EBOOK)
    assert first.name.startswith("tadoku-org-")
    assert first.name.endswith("-f0048e-arimasuka-v4.pdf")
    assert first.read_bytes() == b"%PDF-1.7 content of " + EBOOK.encode()
    assert pdf_web.fetch(EBOOK)[0] == first
    assert calls == [EBOOK]


def test_two_sites_with_a_pdf_of_the_same_name_keep_one_each(monkeypatch, tmp_path):
    """The name alone would hand the second site the first one's file."""
    calls = _counting(monkeypatch, tmp_path)
    one = "https://a.example/sample.pdf"
    two = "https://b.example/sample.pdf"

    first, _title = pdf_web.fetch(one)
    second, _title = pdf_web.fetch(two)

    assert first != second
    assert second.read_bytes().endswith(two.encode())
    assert calls == [one, two]


def test_a_write_cut_short_is_not_taken_for_the_book(monkeypatch, tmp_path):
    """Ctrl+C in the middle of writing: the next run downloads it again rather
    than read half a PDF for ever."""
    calls = _counting(monkeypatch, tmp_path)
    real_write = Path.write_bytes

    def interrupted(self, data):
        monkeypatch.setattr(Path, "write_bytes", real_write)
        real_write(self, data[:len(data) // 2])
        raise KeyboardInterrupt

    monkeypatch.setattr(Path, "write_bytes", interrupted)
    with pytest.raises(KeyboardInterrupt):
        pdf_web.fetch(EBOOK)
    assert not list(tmp_path.rglob("*.pdf*")), "half a book stayed in the cache"

    path, _title = pdf_web.fetch(EBOOK)
    assert path.read_bytes() == b"%PDF-1.7 content of " + EBOOK.encode()
    assert calls == [EBOOK, EBOOK]


class _Answer:
    """An answer that announces `announced` bytes and gives `data`."""

    def __init__(self, data: bytes, announced: int) -> None:
        self.data = data
        self.headers = {"Content-Length": str(announced)}

    def read(self, size: int = -1) -> bytes:
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_a_download_cut_short_is_not_taken_for_the_book(monkeypatch):
    """The connection closed after half the PDF: `http.client` says nothing, and
    half a book would enter the cache for good."""
    sent = {}

    def open_url(url, timeout, headers=None):
        sent.update(headers or {})
        return _Answer(b"%PDF-1.7 half", 2000)

    monkeypatch.setattr(download, "open_url", open_url)
    with pytest.raises(RuntimeError, match="download interrupted"):
        pdf_web._download(EBOOK)
    # Asked for under the name of kotogen, like any other download.
    assert sent["User-Agent"] == download.AGENT


def test_a_broken_answer_is_said_in_plain_words(monkeypatch):
    def open_url(url, timeout, headers=None):
        raise http.client.BadStatusLine("garbage")

    monkeypatch.setattr(download, "open_url", open_url)
    with pytest.raises(RuntimeError, match="download interrupted"):
        pdf_web._download(EBOOK)


def test_an_address_that_does_not_give_back_a_pdf_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(pdf_web, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(pdf_web, "_download", lambda url: b"<!DOCTYPE html>")
    with pytest.raises(RuntimeError) as excinfo:
        pdf_web.fetch("https://example.jp/fake.pdf")
    assert "does not give back a PDF" in str(excinfo.value)
    # Nothing unusable stays in the cache.
    assert not list(tmp_path.rglob("*.pdf"))


def test_a_pdf_too_heavy_for_the_api_is_refused_before_entering_the_cache(
        monkeypatch, tmp_path):
    from kotogen.generators.pdf_source import MAX_PDF_BYTES

    monkeypatch.setattr(pdf_web, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(pdf_web, "_download",
                        lambda url: b"%PDF" + b"x" * MAX_PDF_BYTES)
    with pytest.raises(RuntimeError) as excinfo:
        pdf_web.fetch("https://example.jp/huge.pdf")
    assert "too large" in str(excinfo.value)
    assert not list(tmp_path.rglob("*.pdf"))

# -- The catalogue of free books ----------------------------------------------

PAGE = """
<div class="col-6 bl-wrap-small freebooks-book-item" data-level="l1"
     data-keywords="…" data-order-level="l1" data-date="1786535668">
  <div class="bl-thumb"><a href="https://tadoku.org/japanese/book/64329/"><img></a></div>
  <div class="bl-title">
    <span class="bl-new">NEW</span>      <a href="https://tadoku.org/japanese/book/64329/">
                金の斧銀の斧～イソップ物語より                    </a></div>
  <div class="bl-icons"><a href="https://tadoku.org/japanese/book/64329/">…</a></div>
</div>
<div class="col-6 bl-wrap-small freebooks-book-item" data-order-level="l-start">
  <div class="bl-thumb"><a href="https://tadoku.org/japanese/book/61273/"><img></a></div>
  <div class="bl-title">
    <a href="https://tadoku.org/japanese/book/61273/">ちょっと<ruby>来<rt>き</rt></ruby>て！</a></div>
</div>
<div class="col-6 bl-wrap-small freebooks-book-item" data-order-level="l0">
  <div class="bl-title">
    <a href="https://tadoku.org/japanese/book/3134/">きつねと&amp;#12484;ル</a></div>
</div>
"""


def test_one_book_per_block_and_not_one_per_link():
    """Each block links its book three times: thumbnail, title and icons."""
    books = pdf_web.parse_books(PAGE)
    assert [book.url for book in books] == [
        "https://tadoku.org/japanese/book/64329/",
        "https://tadoku.org/japanese/book/61273/",
        "https://tadoku.org/japanese/book/3134/",
    ]


def test_the_title_is_cleaned_like_that_of_a_page():
    """Tags, ruby and entities: this title goes into a menu, not into a card."""
    books = pdf_web.parse_books(PAGE)
    assert books[0].title == "金の斧銀の斧～イソップ物語より"
    assert books[1].title == "ちょっと来て！"


def test_the_levels_are_filed_from_the_simplest_to_the_densest():
    """The site's level order, not the page's, which files the books by date."""
    levels = pdf_web.by_level(pdf_web.parse_books(PAGE))
    assert [label for label, _books in levels] == ["Start", "Level 0", "Level 1"]
    assert [len(group) for _label, group in levels] == [1, 1, 1]


def test_an_unknown_level_goes_to_the_end_instead_of_disappearing():
    """The site can add a level: its books stay reachable."""
    books = pdf_web.parse_books(PAGE) + [
        pdf_web.Book("l9", "未来の本", "https://tadoku.org/japanese/book/99999/")]
    assert [label for label, _books in pdf_web.by_level(books)][-1] == "Level 9"


def test_the_catalogue_is_kept_on_disk(monkeypatch, tmp_path):
    """The page weighs 800 KB: it is not read again at every menu."""
    monkeypatch.setattr(pdf_web, "cache_dir", lambda: tmp_path)
    calls = []

    def download(url, timeout=60):
        calls.append(url)
        return PAGE.encode("utf-8")

    monkeypatch.setattr(pdf_web, "_download", download)
    assert len(pdf_web.books()) == 3
    assert len(pdf_web.books()) == 3
    assert calls == [pdf_web.FREE_BOOKS_URL]
    # --refresh (or an out-of-date cache) does ask again.
    assert len(pdf_web.books(refresh=True)) == 3
    assert len(calls) == 2


def test_offline_the_known_catalogue_still_serves(monkeypatch, tmp_path):
    """A month-old catalogue beats an empty menu: its books are still online."""
    monkeypatch.setattr(pdf_web, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(pdf_web, "_download", lambda url, timeout=60: PAGE.encode("utf-8"))
    pdf_web.books()

    def cut(url, timeout=60):
        raise RuntimeError("site unreachable")

    monkeypatch.setattr(pdf_web, "_download", cut)
    assert len(pdf_web.books(refresh=True)) == 3


def test_with_neither_network_nor_cache_the_catalogue_is_empty_without_raising(
        monkeypatch, tmp_path):
    """The menu then falls back on "paste the URL", it does not stop."""
    monkeypatch.setattr(pdf_web, "cache_dir", lambda: tmp_path)

    def cut(url, timeout=60):
        raise RuntimeError("site unreachable")

    monkeypatch.setattr(pdf_web, "_download", cut)
    assert pdf_web.books() == []


def test_the_catalogue_waits_no_longer_than_it_is_told(monkeypatch, tmp_path):
    """The reading menu waits on this fetch behind a spinner: the timeout it
    passes is the one the socket gets."""
    monkeypatch.setattr(pdf_web, "cache_dir", lambda: tmp_path)
    waited = []

    def open_url(url, timeout, headers=None):
        waited.append(timeout)
        raise urllib.error.URLError("unreachable")

    monkeypatch.setattr(download, "open_url", open_url)
    assert pdf_web.books(timeout=7) == []
    assert waited == [7]


def test_an_unreadable_page_does_not_wipe_the_known_catalogue(monkeypatch, tmp_path):
    """A redesigned page keeps the earlier list rather than caching an empty one
    for a month."""
    monkeypatch.setattr(pdf_web, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(pdf_web, "_download", lambda url, timeout=60: PAGE.encode("utf-8"))
    pdf_web.books()
    monkeypatch.setattr(pdf_web, "_download", lambda url, timeout=60: b"<html>redesign</html>")
    assert len(pdf_web.books(refresh=True)) == 3


# -- Books already handled ----------------------------------------------------
# The storage is tested in test_seen.py: here, only its key, the page number.

@pytest.mark.parametrize("url, number", [
    ("https://tadoku.org/japanese/book/6346/", "6346"),
    ("http://www.tadoku.org/japanese/book/5371/#bd-look-inside", "5371"),
    ("https://example.jp/papers.pdf", ""),
    ("https://example.jp/japanese/book/12/", ""),
    ("", ""),
])
def test_the_number_of_the_page_identifies_the_book(url, number):
    """/book/12/ on another site is not Tadoku's book 12: the two would discard
    each other."""
    assert pdf_web.book_id(url) == number


def test_a_handled_book_is_kept_with_its_title():
    assert pdf_web.load_seen() == {}
    pdf_web.mark_seen("https://tadoku.org/japanese/book/6346/", "くるみもち")
    assert pdf_web.load_seen() == {"6346": "くるみもち"}
    # Per mode, like the other sources: a book read is not a book listened to.
    assert pdf_web.load_seen("audio") == {}


def test_any_pdf_at_all_does_not_enter_the_history():
    """A PDF fetched by URL has no identifier: under an empty key, each would
    discard all the others."""
    pdf_web.mark_seen("https://example.jp/papers.pdf", "Papers")
    assert pdf_web.load_seen() == {}
