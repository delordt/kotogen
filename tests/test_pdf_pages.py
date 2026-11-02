"""Pages of a document rendered as images for the mini-book of the reading card.

Needs the "pdf" extra (pypdfium2 + Pillow): without it the whole file is skipped,
the page range and the naming (a book losing pages, two books colliding in
Anki's shared media folder) included.
"""

from __future__ import annotations

import io
import sys

import pytest

from kotogen import i18n
from kotogen.generators import pdf_pages

pillow = pytest.importorskip("PIL.Image", reason='"pdf" extra absent')
pytest.importorskip("pypdfium2", reason='"pdf" extra absent')


# -- Page range ---------------------------------------------------------------

def test_without_a_range_the_whole_document():
    assert pdf_pages.parse_pages(None, 3) == [0, 1, 2]
    assert pdf_pages.parse_pages("", 3) == [0, 1, 2]


def test_a_plain_range_is_1_based():
    # Pages 3 to 5 as printed are indices 2 to 4.
    assert pdf_pages.parse_pages("3-5", 10) == [2, 3, 4]


def test_a_single_page_and_an_open_end():
    assert pdf_pages.parse_pages("7", 10) == [6]
    assert pdf_pages.parse_pages("8-", 10) == [7, 8, 9]


def test_a_range_past_the_end_stops_at_the_document():
    assert pdf_pages.parse_pages("2-99", 4) == [1, 2, 3]


def test_several_chunks_keep_the_asked_order_without_duplicates():
    assert pdf_pages.parse_pages("5,1-2,5", 5) == [4, 0, 1]


@pytest.mark.parametrize("spec", ["abc", "3-1", "0", "3--5"])
def test_an_unreadable_or_inconsistent_range_is_refused(spec):
    with pytest.raises(ValueError):
        pdf_pages.parse_pages(spec, 10)


def test_a_page_that_does_not_exist_says_the_size_of_the_document():
    with pytest.raises(ValueError) as excinfo:
        pdf_pages.parse_pages("12-", 5)
    assert "5 pages" in str(excinfo.value)


def test_a_one_page_document_says_so_in_the_singular():
    """The noun is agreed, never "1 page(s)"."""
    with pytest.raises(ValueError) as excinfo:
        pdf_pages.parse_pages("4", 1)
    assert "1 page:" in str(excinfo.value)


# -- Naming in the media library ----------------------------------------------

def test_the_page_name_is_ascii_and_numbered():
    name = pdf_pages.media_name("こねこ Book #2", "abc123", 7)
    assert name == "reading_book_2_abc123_p007.jpg"
    assert name.isascii()


def test_two_documents_do_not_overlap_in_the_media_library():
    """Media names are shared by the whole collection: same title, different
    contents, and the pages must not overwrite each other."""
    a = pdf_pages.media_name("book", pdf_pages.digest(b"one"), 1)
    b = pdf_pages.media_name("book", pdf_pages.digest(b"two"), 1)
    assert a != b


def test_the_same_document_gives_back_the_same_names():
    """Regenerating a book rewrites its pages instead of piling up copies."""
    assert pdf_pages.digest(b"one") == pdf_pages.digest(b"one")


def test_the_images_field_is_ready_for_the_mini_book(tmp_path):
    paths = [tmp_path / "a_p001.jpg", tmp_path / "a_p002.jpg"]
    assert pdf_pages.images_field(paths) == (
        '<img src="a_p001.jpg"><img src="a_p002.jpg">')


# -- Rendering ----------------------------------------------------------------

def _pdf(pages: int, width: int = 800, height: int = 1200) -> bytes:
    from PIL import Image

    images = [Image.new("RGB", (width, height), "white") for _ in range(pages)]
    buffer = io.BytesIO()
    images[0].save(buffer, "PDF", save_all=True, append_images=images[1:])
    return buffer.getvalue()


def test_one_image_per_rendered_page(tmp_path):
    data = _pdf(4)
    assert pdf_pages.page_count(data) == 4
    files = pdf_pages.render_pdf(data, [1, 2], tmp_path, "book")
    assert len(files) == 2
    assert all(f.is_file() and f.stat().st_size > 0 for f in files)
    # Named after their page in the document, listed in the order asked for.
    assert [f.name[-8:] for f in files] == ["p002.jpg", "p003.jpg"]


def test_two_ranges_of_one_document_do_not_share_their_pages(tmp_path):
    """The mark is the whole document's: named by rank, pages 3-4 would take the
    names of pages 1-2, hence their `Images` field and the IDs of their cards,
    and overwrite their files in collection.media."""
    data = _pdf(4)
    first = pdf_pages.render_pdf(data, [0, 1], tmp_path, "book")
    second = pdf_pages.render_pdf(data, [2, 3], tmp_path, "book")
    assert not {f.name for f in first} & {f.name for f in second}
    assert pdf_pages.images_field(first) != pdf_pages.images_field(second)


def test_the_whole_document_keeps_the_names_it_always_had(tmp_path):
    """The decks already built hold these names, and the IDs drawn from them."""
    files = pdf_pages.render_pdf(_pdf(3), [0, 1, 2], tmp_path, "book")
    assert [f.name[-8:] for f in files] == ["p001.jpg", "p002.jpg", "p003.jpg"]


def test_the_document_sent_to_the_model_only_carries_the_pages_kept():
    data = _pdf(6)
    assert pdf_pages.page_count(pdf_pages.subset(data, [0, 1])) == 2
    # Every page kept: the document leaves as it is, with no rewriting.
    assert pdf_pages.subset(data, [0, 1, 2, 3, 4, 5]) is data


def _pdfium_open() -> int:
    """How many pypdfium2 objects (documents, pages) are still open.

    pypdfium2 closes unclosed ones at exit, writing "The following objects are
    still open..." on stderr, after the menu. Its registry is read directly: the
    garbage collector would hide the leak.
    """
    from pypdfium2.internal import ObjectTracker

    return sum(len(refs) for refs in ObjectTracker.values())


def test_rendering_a_pdf_leaves_nothing_open(tmp_path):
    data = _pdf(3)

    before = _pdfium_open()
    pdf_pages.page_count(data)
    pdf_pages.measure(data, [0, 1, 2])
    pdf_pages.subset(data, [0, 1])
    pdf_pages.render_pdf(data, [0], tmp_path, "book")

    assert _pdfium_open() == before


def test_a_rendering_that_fails_leaves_nothing_open(tmp_path, monkeypatch):
    """An interrupted rendering: the exception holds the frame where the document
    was opened, so without an explicit close it lives until exit, where
    pypdfium2 closes it and says so on screen."""
    def disk_full(image, path):
        raise OSError("disk full")

    monkeypatch.setattr(pdf_pages, "_save_jpeg", disk_full)

    before = _pdfium_open()
    caught = None
    try:
        pdf_pages.render_pdf(_pdf(2), [0, 1], tmp_path, "book")
    except OSError as exc:
        caught = exc

    assert caught is not None
    assert _pdfium_open() == before


def test_wide_pages_are_brought_back_to_the_rendering_width(tmp_path):
    from PIL import Image

    files = pdf_pages.render_pdf(_pdf(1, width=4000, height=6000), [0], tmp_path, "scan")
    with Image.open(files[0]) as image:
        assert image.width == pdf_pages.PAGE_WIDTH


# -- What kind of document is this --------------------------------------------
# "Text or mini-book" is decided for the user: when the measures cannot tell,
# the model settles it, in the call that reads the document anyway.

def test_a_typeset_course_is_text():
    # Little image on the page: it is text laid out, whatever it carries.
    assert pdf_pages._verdict(pages=40, chars=600, cover=0.05)[0] == "text"
    assert pdf_pages._verdict(pages=40, chars=0, cover=0.2)[0] == "text"


def test_an_illustrated_album_is_a_mini_book():
    """The image fills the page and text is rare: dropping the image would drop
    the story. A Tadoku book kept on disk comes this way."""
    mode, reason = pdf_pages._verdict(pages=24, chars=35, cover=0.95)
    assert mode == "book"
    assert "mini-book" in reason


def test_a_page_wholly_in_image_form_but_dense_is_text():
    """A scanned and OCRed past paper: the page is an image, but the wall of
    Japanese says the layout brings nothing."""
    assert pdf_pages._verdict(pages=30, chars=700, cover=1.0)[0] == "text"


def test_scanned_pages_let_the_model_settle_it():
    """With no text layer, a manga plate and a photocopied past paper look alike:
    only looking at the pages tells them apart."""
    mode, reason = pdf_pages._verdict(pages=30, chars=0, cover=1.0)
    assert mode is None
    assert "the model settles it" in reason


def test_a_single_scanned_page_is_a_mini_book():
    """Saves the most frequent arbitration call: a single page is one reading,
    and showing it keeps its layout."""
    assert pdf_pages._verdict(pages=1, chars=0, cover=1.0)[0] == "book"


def test_the_measurement_reads_the_pages_of_a_real_document():
    """Pages in image form, with no text layer: full cover, zero Japanese."""
    chars, cover = pdf_pages.measure(_pdf(3), [0, 1, 2])
    assert chars == 0
    assert cover > 0.99


def test_a_one_page_scan_goes_to_the_mini_book_without_asking():
    assert pdf_pages.read_mode(_pdf(1))[0] == "book"
    # The same document bounded to one page: the range counts, not the document.
    assert pdf_pages.read_mode(_pdf(6), "2")[0] == "book"
    assert pdf_pages.read_mode(_pdf(6))[0] is None


def test_without_the_pdf_extra_the_model_settles_it(monkeypatch):
    """Measuring needs pypdfium2, reading the document does not: being unable to
    measure must not stop the command."""
    def absent():
        raise RuntimeError("page rendering unavailable")

    monkeypatch.setattr(pdf_pages, "_deps", absent)
    mode, reason = pdf_pages.read_mode(_pdf(4))
    assert mode is None
    assert "not measurable" in reason


def test_images_already_prepared_make_a_book(tmp_path):
    from PIL import Image

    source = tmp_path / "source"
    source.mkdir()
    for name in ("page02.png", "page01.png", "page10.png"):
        Image.new("RGB", (600, 900), "white").save(source / name)

    # Name order is the book's order, and the folder itself is a source.
    assert pdf_pages.is_image_source(str(source))
    assert [p.name for p in pdf_pages.resolve_images(str(source))] == [
        "page01.png", "page02.png", "page10.png"]

    files = pdf_pages.render_images(pdf_pages.resolve_images(str(source)),
                                    tmp_path / "out", "book")
    assert [f.suffix for f in files] == [".jpg", ".jpg", ".jpg"]
    # The model only reads PDFs: the pages are glued back into one, in order.
    assert pdf_pages.page_count(pdf_pages.to_pdf(files)) == 3


def test_a_source_that_is_not_an_image_is_not_a_book(tmp_path):
    (tmp_path / "notes.txt").write_text("text", encoding="utf-8")
    assert not pdf_pages.is_image_source(str(tmp_path / "notes.txt"))
    assert not pdf_pages.is_image_source("nhk")
    assert not pdf_pages.is_image_source("https://example.jp/article")
    # Neither is a folder without a single image.
    assert not pdf_pages.is_image_source(str(tmp_path))


def test_the_missing_extra_is_named_as_zsh_takes_it(monkeypatch):
    """macOS's shell refuses bare brackets, and the install is from a clone."""
    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    with pytest.raises(RuntimeError) as raised:
        pdf_pages._deps()
    assert 'pip install -e ".[pdf]"' in str(raised.value)
    assert "kotogen folder" in str(raised.value)


@pytest.mark.parametrize("lang", [name for name in i18n.available()
                                  if name != i18n.SOURCE])
def test_every_table_says_what_the_page_rendering_lacks(lang):
    """`_MISSING_DEPS` is held in English and translated where it is raised."""
    assert pdf_pages._MISSING_DEPS in i18n._load(lang)
