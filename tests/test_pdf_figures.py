"""Cutting the figures out of a past-paper booklet, typeset or scanned.

A figure cut wrong costs more than none: a card showing the neighbouring item,
or the item number, asks another question. The pages and their frames are built
here to the pixel; a real booklet is checked by eye.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from kotogen.generators import pdf_figures

# -- On a real PDF ------------------------------------------------------------

def test_a_pdf_made_of_one_image_is_seen_as_a_scan(tmp_path):
    """A photocopied booklet: one image per page, and nothing else.

    On a real file, since the reading of the PDF is what is checked: the name of
    an object's bounds has changed between pypdfium2 versions.
    """
    Image = pytest.importorskip("PIL.Image")

    scanned_page = Image.new("RGB", (1240, 1754), "white")
    path = tmp_path / "scan.pdf"
    scanned_page.save(path, "PDF", resolution=150)

    probed = pdf_figures.probe(path)

    assert len(probed) == 1
    assert probed[0].scan, f"cover measured: {probed[0].cover}"
    assert pdf_figures.pages_with_figures(path) == [], "a scan has no drawing page"


def test_the_pdf_extra_asks_for_the_pypdfium2_the_code_calls():
    """`get_bounds` and `PdfDocument` as a context manager arrived in pypdfium2 5:
    a 4.x the extra let in would read no figure at all."""
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8")
    bound = re.search(r'^pdf = \[[^\]]*"pypdfium2>=(\d+)', pyproject, re.MULTILINE)

    assert bound and int(bound.group(1)) >= 5


def test_the_bytes_and_the_path_give_the_same_result(tmp_path):
    Image = pytest.importorskip("PIL.Image")

    path = tmp_path / "scan.pdf"
    Image.new("RGB", (600, 800), "white").save(path, "PDF")

    assert pdf_figures.probe(path) == pdf_figures.probe(path.read_bytes())


def _pdfium_open() -> int:
    """How many pypdfium2 objects (documents, pages) are still open.

    pypdfium2 closes unclosed ones at exit, writing "The following objects are
    still open..." on stderr, after the menu. Its registry is read directly: the
    garbage collector would hide the leak.
    """
    from pypdfium2.internal import ObjectTracker

    return sum(len(refs) for refs in ObjectTracker.values())


def test_reading_a_pdf_leaves_nothing_open(tmp_path):
    Image = pytest.importorskip("PIL.Image")

    path = tmp_path / "booklet.pdf"
    sheet = Image.new("RGB", (600, 800), "white")
    sheet.paste(Image.new("RGB", (200, 200), "black"), (100, 100))
    sheet.save(path, "PDF")
    data = path.read_bytes()

    before = _pdfium_open()
    pdf_figures.probe(data)
    drawn = pdf_figures.drawings(data)
    pdf_figures.render_area(data, 1, (0.1, 0.5, 0.1, 0.5))

    assert drawn, "the PDF of the test must carry an image"
    assert _pdfium_open() == before


def test_a_reading_that_fails_leaves_nothing_open(tmp_path, monkeypatch):
    """An interrupted reading: the exception holds the frame where the document
    was opened, so without an explicit close it lives until exit, where
    pypdfium2 closes it and says so on screen."""
    Image = pytest.importorskip("PIL.Image")

    path = tmp_path / "booklet.pdf"
    Image.new("RGB", (600, 800), "white").save(path, "PDF")

    def unreadable(obj):
        raise RuntimeError("unreadable PDF")

    monkeypatch.setattr(pdf_figures, "_bounds", unreadable)

    before = _pdfium_open()
    caught = None
    try:
        pdf_figures.probe(path.read_bytes())
    except RuntimeError as exc:
        caught = exc

    assert caught is not None
    assert _pdfium_open() == before


# -- Cutting a page into items, the number being known ------------------------

def box(top, bottom, left=0.1, right=0.9):
    return (top, bottom, left, right)


def test_two_items_are_cut_at_the_largest_gap():
    """The N5L p.4 case: a large illustration at the top, a grid at the bottom."""
    boxes = [box(0.106, 0.477),
             box(0.541, 0.750), box(0.542, 0.752),
             box(0.748, 0.916), box(0.750, 0.918)]

    groups = pdf_figures.group_into(boxes, 2)

    assert [len(g) for g in groups] == [1, 4]


def test_a_2x2_grid_is_not_cut_when_the_item_is_alone():
    """N5L p.7: a single item, its four options in two rows. The gap between the
    rows (0.083) exceeds one between two items elsewhere (0.064), so no gap
    threshold works; the known item count settles it."""
    boxes = [box(0.119, 0.276), box(0.162, 0.256),
             box(0.342, 0.436), box(0.347, 0.430)]

    groups = pdf_figures.group_into(boxes, 1)

    assert len(groups) == 1 and len(groups[0]) == 4


def test_the_grid_at_the_bottom_stays_whole_with_two_items():
    """N5L p.5: item 3 at the top, item 4 as a 2x2 grid below. The gap inside
    item 4 (0.083) would pass a threshold, but the one between 3 and 4 (0.117)
    is larger: cutting once, at the largest, needs nothing tuned."""
    boxes = [box(0.119, 0.463),
             box(0.580, 0.695), box(0.640, 0.694),
             box(0.778, 0.816), box(0.827, 0.881)]

    groups = pdf_figures.group_into(boxes, 2)

    assert [len(g) for g in groups] == [1, 4], "the bottom grid must stay whole"


def test_drawings_side_by_side_do_not_make_a_gap():
    """Drawings on one row overlap in height: the gap is measured from the lowest
    bottom met so far, not from the previous drawing's."""
    boxes = [box(0.10, 0.40), box(0.11, 0.39),      # row 1
             box(0.60, 0.90), box(0.61, 0.89)]      # row 2

    groups = pdf_figures.group_into(boxes, 2)

    assert [len(g) for g in groups] == [2, 2]


def test_the_item_number_stays_outside():
    """The "7ばん" printed above the frames is a booklet marker, not part of the
    question: lining up on the frames leaves it out without looking for it."""
    drawings = [box(0.119, 0.436, 0.206, 0.855)]
    frames = [box(0.106, 0.282, 0.176, 0.502), box(0.106, 0.282, 0.529, 0.854),
              box(0.301, 0.478, 0.176, 0.502), box(0.301, 0.478, 0.529, 0.854)]

    top, bottom, left, right = pdf_figures.area_of(drawings, tuple(frames))

    # The number on N5L p.7 sits at 0.078: the area must open lower than it.
    assert top > 0.078, "the item number would enter the figure"
    assert bottom >= 0.478, "the bottom of the frames must come in whole"


def test_the_frames_bound_the_figure_better_than_the_drawings():
    """The frames are vector-based and stick out of the drawings on all four
    sides: an area lined up on the images alone would crop them."""
    drawings = [box(0.119, 0.436, 0.206, 0.855)]
    frames = [box(0.106, 0.478, 0.176, 0.854)]

    area = pdf_figures.area_of(drawings, tuple(frames))
    frameless = pdf_figures.area_of(drawings)

    assert area[0] < frameless[0] and area[1] > frameless[1]
    assert area[2] < frameless[2]


def test_the_area_closes_on_the_sides():
    """The white of the page margins falls away: the card has no room to lose."""
    area = pdf_figures.area_of([box(0.2, 0.4, 0.30, 0.70)])

    assert area[2] > 0.2 and area[3] < 0.8, "the whole width is not kept"


def test_the_frames_of_the_other_item_do_not_widen_this_one():
    """On a page with two items, the frames at the bottom do not concern the top."""
    drawings = [box(0.10, 0.40)]
    frames = [box(0.09, 0.42), box(0.55, 0.92)]

    top, bottom, _left, _right = pdf_figures.area_of(drawings, tuple(frames))

    assert bottom < 0.5, "the frame of the bottom item was swallowed"


def test_an_area_never_leaves_the_page():
    area = pdf_figures.area_of([box(0.001, 0.999, 0.001, 0.999)])

    assert area[0] == 0.0 and area[1] == 1.0
    assert area[2] == 0.0 and area[3] == 1.0


# -- The frames of a scanned booklet ------------------------------------------
# A scan declares no object, only a page-wide image, so its frames are read in
# the ink, tested on pages built to the pixel: a real booklet is checked by eye.

def _scanned_page(tmp_path, frames, size=(620, 877), stroke=3, name="scan.pdf",
                  labels=()):
    """A one-page white PDF with `frames` traced on it as (top, bottom, left, right).

    Bounds are fractions of a page, the units of the results. `labels` stand for
    the 「2ばん」 printed in the margin above an item: filled blocks, since the
    detection looks for ink there, not a shape.
    """
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")

    width, height = size
    sheet = Image.new("RGB", size, "white")
    pen = ImageDraw.Draw(sheet)
    for top, bottom, left, right in frames:
        pen.rectangle([left * width, top * height, right * width, bottom * height],
                      outline="black", width=stroke)
    for top, bottom, left, right in labels:
        pen.rectangle([left * width, top * height, right * width, bottom * height],
                      fill="black")
    path = tmp_path / name
    sheet.save(path, "PDF", resolution=72)
    return path


def _frames(source) -> dict[int, tuple]:
    """The frames of each page, all items together, as `exam_items` lays them."""
    return {page: tuple(sorted(box for block in blocks for box in block))
            for page, blocks in pdf_figures.scanned_items(source).items()}


def _close(measured, expected, margin=0.02) -> bool:
    return all(abs(m - e) <= margin for m, e in zip(measured, expected))


def test_a_printed_frame_is_found_in_the_ink(tmp_path):
    """The basic case: a single figure, like a 発話表現 item."""
    pytest.importorskip("numpy")
    expected = (0.10, 0.45, 0.15, 0.85)
    path = _scanned_page(tmp_path, [expected])

    found = _frames(path)

    assert list(found) == [1], "the page carries a frame, it must be returned"
    (frame,) = found[1]
    assert _close(frame, expected), f"frame measured: {frame}"


def test_a_grid_of_four_options_gives_four_frames(tmp_path):
    """The 課題理解 of the N5 and the N4: four numbered drawings, in a 2x2 grid."""
    pytest.importorskip("numpy")
    grid = [(0.10, 0.30, 0.15, 0.48), (0.10, 0.30, 0.52, 0.85),
            (0.34, 0.54, 0.15, 0.48), (0.34, 0.54, 0.52, 0.85)]
    path = _scanned_page(tmp_path, grid)

    found = _frames(path)[1]

    assert len(found) == 4, f"frames found: {found}"
    for measured, expected in zip(found, sorted(grid)):
        assert _close(measured, expected), f"{measured} for {expected}"


def test_a_page_with_no_frame_is_not_returned(tmp_path):
    """An item whose options are words: no figure, no entry, as with `drawings`,
    so the caller handles both routes alike."""
    pytest.importorskip("numpy")
    path = _scanned_page(tmp_path, [])

    assert pdf_figures.scanned_items(path) == {}


def test_a_tiny_frame_is_a_detail_of_a_drawing(tmp_path):
    """A train window, a photo frame inside the illustration: not a figure. The
    area threshold alone guards against them, with room: the smallest item frame
    recorded is three times it."""
    pytest.importorskip("numpy")
    path = _scanned_page(tmp_path, [(0.20, 0.26, 0.40, 0.50)])

    assert pdf_figures.scanned_items(path) == {}


def test_the_rule_around_a_grid_is_not_a_figure(tmp_path):
    """A frame containing others is an envelope, not an item: kept, it would make
    a figure of the whole page, number included, ahead of the four real ones."""
    pytest.importorskip("numpy")
    grid = [(0.12, 0.30, 0.17, 0.46), (0.12, 0.30, 0.54, 0.83),
            (0.34, 0.52, 0.17, 0.46), (0.34, 0.52, 0.54, 0.83)]
    path = _scanned_page(tmp_path, [(0.10, 0.54, 0.15, 0.85)] + grid)

    found = _frames(path)[1]

    assert len(found) == 4, f"frames found: {found}"
    assert all(frame[0] >= 0.11 for frame in found), "the envelope got through"


def test_the_gutter_between_two_frames_is_not_one(tmp_path):
    """Two frames side by side leave a gutter bordered left and right only: the
    four-edge test refuses it, or an empty rectangle would be cut out."""
    pytest.importorskip("numpy")
    path = _scanned_page(tmp_path, [(0.10, 0.40, 0.15, 0.47),
                                    (0.10, 0.40, 0.53, 0.85)])

    found = _frames(path)[1]

    assert len(found) == 2, f"frames found: {found}"


# -- One item, or two? The label says so ---------------------------------------
# The gap between two rows of one grid and the gap between two items look alike
# (see the module header): on a scan, the number printed in the margin settles
# it. The two layouts are those of the 2012 booklets.

# Two 2x2 grids of options on a page: the 課題理解 of the N4, two items a page.
_TOP_GRID = [(0.11, 0.29, 0.16, 0.49), (0.11, 0.29, 0.51, 0.84),
             (0.31, 0.48, 0.16, 0.49), (0.31, 0.48, 0.51, 0.84)]
_BOTTOM_GRID = [(0.53, 0.71, 0.16, 0.49), (0.53, 0.71, 0.51, 0.84),
                (0.73, 0.90, 0.16, 0.49), (0.73, 0.90, 0.51, 0.84)]
# The 「2ばん」 that opens the second one, printed against the left edge of the
# figures, in the band the first grid leaves free.
_LABEL = (0.495, 0.520, 0.11, 0.155)


def test_the_printed_label_cuts_the_page_into_items(tmp_path):
    """Eight frames, two items (N4L 2012 p.4): no card may show all eight."""
    pytest.importorskip("numpy")
    path = _scanned_page(tmp_path, _TOP_GRID + _BOTTOM_GRID, labels=[_LABEL])

    blocks = pdf_figures.scanned_items(path)[1]

    assert [len(block) for block in blocks] == [4, 4], f"blocks: {blocks}"
    assert blocks[0][0][0] < 0.5 and blocks[1][0][0] > 0.5


def test_the_two_rows_of_one_grid_are_not_two_items(tmp_path):
    """The same eight frames with nothing printed between them are one figure: a
    gap threshold cannot tell grids from rows, only the margin does."""
    pytest.importorskip("numpy")
    path = _scanned_page(tmp_path, _TOP_GRID + _BOTTOM_GRID)

    blocks = pdf_figures.scanned_items(path)[1]

    assert len(blocks) == 1 and len(blocks[0]) == 8


def test_a_lone_figure_is_one_block(tmp_path):
    """The 発話表現 of the N4: one drawing, one item."""
    pytest.importorskip("numpy")
    path = _scanned_page(tmp_path, [(0.11, 0.48, 0.16, 0.84)])

    assert [len(b) for b in pdf_figures.scanned_items(path)[1]] == [1]


def test_the_bytes_and_the_path_give_the_same_frames(tmp_path):
    pytest.importorskip("numpy")
    path = _scanned_page(tmp_path, [(0.10, 0.45, 0.15, 0.85)])

    assert (pdf_figures.scanned_items(path)
            == pdf_figures.scanned_items(path.read_bytes()))


def test_reading_the_frames_leaves_nothing_open(tmp_path):
    """The rendering opens every page of the document, and must close them."""
    pytest.importorskip("numpy")
    data = _scanned_page(tmp_path, [(0.10, 0.45, 0.15, 0.85)]).read_bytes()

    before = _pdfium_open()
    pdf_figures.scanned_items(data)

    assert _pdfium_open() == before
