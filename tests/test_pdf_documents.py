"""Finding the page of a composed document, and knowing when it is not found.

The two errors cost unequally: a missed page gives a text card, which it would
have been anyway; a wrong page gives a card showing another exercise's poster.
The figures were measured on the official N4R and N5R samples (2018); the header
of `pdf_documents` says where they come from.
"""

from __future__ import annotations

import pytest

from kotogen.generators import pdf_documents, pdf_figures
from kotogen.generators.pdf_figures import Objects

# -- What is compared on either side ------------------------------------------

def test_furigana_do_not_count():
    """The booklet prints readings beside the text, the transcription between
    brackets: kept, they would make a run of characters found nowhere."""
    with_readings = pdf_documents.fingerprints(
        ["鍵[かぎ]を 持[も]って 教室[きょうしつ]へ"])
    without = pdf_documents.fingerprints(["鍵を持って教室へ"])

    assert with_readings == without


def test_digits_do_not_count():
    """The booklets draw their digits, so the text layer drops them (measured on
    N4R) while the model, reading the image, transcribes them: removed on both
    sides, the two match again."""
    assert (pdf_documents.fingerprints(["お茶会[ちゃかい]は 300円[えん]です"])
            == pdf_documents.fingerprints(["お茶会[ちゃかい]は 円[えん]です"]))


def test_the_furigana_space_does_not_cut():
    """The notation puts an ASCII space before every group of kanji: cutting on it
    would leave crumbs too short for a single six-character fingerprint."""
    assert pdf_documents.fingerprints(["私[わたし]は 学校[がっこう]に 行[い]きます"])


def test_the_layout_space_does_cut():
    """A table row joins cells that do not touch on the page, and a fingerprint
    across the join is found nowhere: such fingerprints dropped N5R p.8 from 0.73
    to 0.31, under the threshold."""
    every = pdf_documents.fingerprints(
        ["東町駅[ひがしまちえき]です　西山駅[にしやまえき]です"])

    # Each cell gives its fingerprints, the join gives none.
    assert "東町駅です西山" not in every
    assert not any("です西山駅" in one for one in every)


def test_a_text_too_short_does_not_identify_itself():
    """Below a few fingerprints, a page could carry them by accident."""
    assert (len(pdf_documents.fingerprints(["春[はる]"]))
            < pdf_documents.FINGERPRINTS_MIN)


# -- Finding the page ---------------------------------------------------------

def _booklet(monkeypatch, pages: dict[int, str]) -> None:
    monkeypatch.setattr(pdf_figures, "page_texts", lambda source: pages)


POSTER = ["青葉町[あおばちょう]では、毎月[まいつき]、絵[え]の 教室[きょうしつ]や "
          "音楽会[おんがくかい]などを 開[ひら]いています。"]


def test_the_page_carrying_the_text_is_found(monkeypatch):
    _booklet(monkeypatch, {
        1: "べつのはなしです。ぜんぜんちがうことをかいてあります。",
        2: "あおばちょう\n青葉町では、毎月、絵の教室や音楽会などを開いています。",
    })

    assert pdf_documents.page_of_text(b"%PDF", POSTER) == 2


def test_a_document_absent_from_the_text_layer_gives_no_page(monkeypatch):
    """N4R p.3 lays its handwritten memo out as an image: the text layer holds
    only the prose announcing it, scoring 0.01 at best, so its card is text."""
    _booklet(monkeypatch, {
        1: "受付[うけつけ]の 窓[まど]に、この 紙[かみ]が はってあります。",
        2: "",
    })

    assert pdf_documents.page_of_text(b"%PDF", POSTER) == 0


def test_two_equal_pages_do_not_settle_it(monkeypatch):
    """Between two, we would not know which carries the document and which
    carries the questions quoting it."""
    page = "青葉町では、毎月、絵の教室や音楽会などを開いています。"
    _booklet(monkeypatch, {1: page, 2: page})

    assert pdf_documents.page_of_text(b"%PDF", POSTER) == 0


def test_a_scanned_booklet_gives_no_page(monkeypatch):
    """No text layer at all: nothing to confront, and nothing to guess."""
    _booklet(monkeypatch, {1: "", 2: "", 3: ""})

    assert pdf_documents.page_of_text(b"%PDF", POSTER) == 0


# -- The area to cut out ------------------------------------------------------

def box(top, bottom, left, right):
    return (top, bottom, left, right)


def test_the_largest_frame_is_the_document():
    """Recorded on N4R p.8: the poster sits in a frame of 0.704 of the page, and
    the 「読解」 tab in the margin, at 0.006, weighs nothing beside it."""
    page = Objects(images=(), strokes=(box(0.077, 0.914, 0.092, 0.934),
                                       box(0.214, 0.315, 0.943, 1.000)))

    area = pdf_figures.frame(page)

    assert area is not None
    top, bottom, left, right = area
    assert top == pytest.approx(0.077 - pdf_figures.BREATH)
    assert right == pytest.approx(0.934 + pdf_figures.BREATH)


def test_a_document_laid_out_as_an_image_frames_too():
    """The memo of N4R p.3 is an image object, not a traced path: both kinds
    compete, and size settles it."""
    page = Objects(images=(box(0.185, 0.471, 0.089, 0.819),),
                   strokes=(box(0.214, 0.315, 0.000, 0.057),))

    area = pdf_figures.frame(page)

    assert area is not None and area[0] == pytest.approx(0.185 - pdf_figures.BREATH)


def test_a_page_with_no_frame_has_no_document():
    """N4R p.2, p.4, p.6 and p.7: prose, and the tab in the margin."""
    page = Objects(images=(), strokes=(box(0.214, 0.315, 0.943, 1.000),))

    assert pdf_figures.frame(page) is None


def test_the_frame_is_not_widened_by_what_crosses_it():
    """`area_of` widens a figure with the strokes crossing it, right for listening
    booklets; here the margin tab crossing the poster of N4R p.8 would stretch
    the area to the page's edge."""
    page = Objects(images=(), strokes=(box(0.077, 0.914, 0.092, 0.934),
                                       box(0.214, 0.315, 0.943, 1.000)))

    area = pdf_figures.frame(page)

    assert area[3] < 0.943


# -- End to end: what is not found gives no image -----------------------------

def test_with_no_page_there_is_no_cutting_out(monkeypatch):
    _booklet(monkeypatch, {1: "", 2: ""})
    monkeypatch.setattr(pdf_figures, "boxes", lambda source: {})

    assert pdf_documents.cut_out(b"%PDF", POSTER) is None


def test_with_no_frame_there_is_no_cutting_out(monkeypatch):
    """The page is the right one, but nothing on it frames anything at all: a
    text card is better than a whole page laid down as an image."""
    _booklet(monkeypatch, {
        1: "青葉町では、毎月、絵の教室や音楽会などを開いています。"})
    monkeypatch.setattr(pdf_figures, "boxes",
                        lambda source: {1: Objects(images=(), strokes=())})

    assert pdf_documents.cut_out(b"%PDF", POSTER) is None


def test_the_cutting_out_gives_back_the_page_and_its_image(monkeypatch):
    _booklet(monkeypatch, {
        1: "青葉町では、毎月、絵の教室や音楽会などを開いています。"})
    monkeypatch.setattr(
        pdf_figures, "boxes",
        lambda source: {1: Objects(images=(), strokes=(box(0.1, 0.9, 0.1, 0.9),))})
    monkeypatch.setattr(pdf_figures, "render_area",
                        lambda source, page, area, scale=1.0: b"\x89PNG")

    assert pdf_documents.cut_out(b"%PDF", POSTER) == (1, b"\x89PNG")
