"""The cutting out of the figures of a past-paper booklet.

A 課題理解 listening card asks its question in pictures, which its `Image` field
carries. What settles the extraction is locating each item, whatever its figure
is made of. A typeset booklet declares its figures as PDF objects and is cut by
them once the number of items is known; a page one image covers is a scan
(`probe`), and a scanned booklet is cut by the frames printed in its ink
(`scanned_items`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kotogen.i18n import _

# Share of the page ONE image object covers above which the page is a scan,
# with nothing to isolate object by object.
SCAN_COVER = 0.80

# White left around a figure, in fractions of a page, so that it does not touch
# the edge of the card. Not a safety margin: the frames give the exact boundary.
BREATH = 0.006


@dataclass(frozen=True)
class ProbedPage:
    """A page, and the share of it its largest image object covers."""

    number: int
    cover: float

    @property
    def scan(self) -> bool:
        return self.cover >= SCAN_COVER


# The command that installs the extra, typed as it stands: its quotes are the
# shell's, which `i18n.quoted` would turn into the screen's.
PDF_EXTRA = 'pip install -e ".[pdf]"'


def _deps():
    """(pypdfium2, PIL.Image), or an error that says what to install."""
    try:
        import pypdfium2
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(_("Missing extra: {command} ({packages})").format(
            command=PDF_EXTRA, packages="pypdfium2, pillow")) from exc
    return pypdfium2, Image


def _bounds(obj) -> tuple[float, float, float, float] | None:
    """The bounds of a page object, or None if it gives none: it is then left out."""
    try:
        bounds = obj.get_bounds()
    except Exception:
        return None
    if bounds and len(bounds) == 4:
        return tuple(float(v) for v in bounds)
    return None


def probe(source: bytes | Path | str) -> list[ProbedPage]:
    """How much of each page its largest image covers. Raises on an unreadable PDF."""
    pypdfium2, _image = _deps()
    import io

    import pypdfium2.raw as raw

    if isinstance(source, (str, Path)):
        source = Path(source).read_bytes()
    pages = []
    with pypdfium2.PdfDocument(io.BytesIO(source)) as document:
        for rank in range(len(document)):
            page = document[rank]
            width, height = page.get_size()
            area = (width or 1) * (height or 1)

            cover = 0.0
            for obj in page.get_objects():
                if obj.type != raw.FPDF_PAGEOBJ_IMAGE:
                    continue
                bounds = _bounds(obj)
                if bounds is None:
                    continue
                left, bottom, right, top = bounds
                cover = max(cover, abs((right - left) * (top - bottom)) / area)
            pages.append(ProbedPage(rank + 1, round(cover, 3)))
    return pages


def page_texts(source: bytes | Path | str) -> dict[int, str]:
    """The text layer of each page, as it is, page counted from 1.

    To FIND a page again, not to read it: 読解 booklets draw their digits, so the
    layer lacks what carries the question, but its kana and kanji are enough to
    recognise a page.
    """
    pypdfium2, _image = _deps()
    import io

    if isinstance(source, (str, Path)):
        source = Path(source).read_bytes()
    by_page: dict[int, str] = {}
    with pypdfium2.PdfDocument(io.BytesIO(source)) as document:
        for rank in range(len(document)):
            by_page[rank + 1] = document[rank].get_textpage().get_text_range() or ""
    return by_page


# -- The two primitives the measuring validated --------------------------------
#
# Measured on the official 2018 samples (N4L, N5L). The items are not delimited
# by the text layer (the printed number is drawn, and 「ばん」 goes missing or
# counts options), nor by a gap threshold (the rows of one 2x2 grid can sit 0.083
# apart, two items 0.064), nor by half a page (a figure can sit astride it). The
# object bounds are exact: the images group by item, the strokes (the frames)
# give the boundary. The number of items is read by `pdf_source.extract_map`.

@dataclass(frozen=True)
class Objects:
    """What a page carries, filed by nature. Bounds in fractions of a page.

    Each box is `(top, bottom, left, right)`, the heights counted from the TOP as
    the page is read, where PDF counts from the bottom.
    """

    images: tuple[tuple[float, float, float, float], ...] = ()
    strokes: tuple[tuple[float, float, float, float], ...] = ()


def boxes(source: bytes | Path | str) -> dict[int, Objects]:
    """The image and vector objects of EVERY page, page counted from 1.

    Pages without a drawing included: a 読解 booklet lays out its posters and
    tables in strokes alone, which `drawings` would drop.
    """
    pypdfium2, _image = _deps()
    import io

    import pypdfium2.raw as raw

    if isinstance(source, (str, Path)):
        source = Path(source).read_bytes()
    by_page: dict[int, Objects] = {}
    with pypdfium2.PdfDocument(io.BytesIO(source)) as document:
        for rank in range(len(document)):
            page = document[rank]
            width, height = page.get_size()
            if not width or not height:
                continue
            images, strokes = [], []
            for obj in page.get_objects():
                if obj.type not in (raw.FPDF_PAGEOBJ_IMAGE, raw.FPDF_PAGEOBJ_PATH):
                    continue
                bounds = _bounds(obj)
                if bounds is None:
                    continue
                left, bottom, right, top = bounds
                box = (1 - top / height, 1 - bottom / height,
                       left / width, right / width)
                (images if obj.type == raw.FPDF_PAGEOBJ_IMAGE else strokes).append(box)
            by_page[rank + 1] = Objects(tuple(sorted(images)), tuple(sorted(strokes)))
    return by_page


def drawings(source: bytes | Path | str) -> dict[int, Objects]:
    """The pages that carry DRAWINGS, and what they carry.

    The images alone group by item; the strokes, the frames around them, give the
    figure's real boundary, always sticking out of the drawings. Unlike `boxes`,
    a page with no drawing is left out: in a 聴解 booklet its options are words.
    """
    return {n: o for n, o in boxes(source).items() if o.images}


# -- The frames of a SCANNED booklet -------------------------------------------
# A scan is one image per page, whose objects say nothing, but every item figure
# sits in a printed frame: the strokes inked in the rows and columns, then the
# rectangles whose four edges are inked along their length, unlike a gutter.

# Below this grey level, the pixel is ink. A clean scan is clear-cut: the paper
# above 240, the strokes under 60.
INK_LEVEL = 128

# Share of the page a row (or column) has to cover to be a stroke. Frame edges
# cover 0.64 to 0.70 (N4L 2012), the false lines of the drawings under 0.20.
STROKE_SHARE = 0.30

# Two strokes closer than this, in rendering pixels, are the same one: a printed
# frame is two or three pixels thick at scale 2.
STROKE_THICKNESS = 4

# Share of an edge that has to be inked for the rectangle to be a frame. Not 1.0:
# a scan loses a pixel now and then.
EDGE_FULL = 0.90

# Minimum area of a frame, as a share of the page; below it, a rectangular detail
# of a drawing (a train window). The smallest item frame recorded is 0.056.
FRAME_AREA_MIN = 0.02

# Rendering scale for the detection: enough for strokes two or three pixels
# thick, at a quarter of the cost of scale 4.
FRAME_SCALE = 2.0

# The strip of margin searched for the item label, left of the figures, in
# fractions of a page. On the 2012 booklets the label spans 0.110 to 0.165: 0.08
# holds it whole and stops short of the thumb tab and running head at the edge.
LABEL_STRIP = 0.08

# Share of that strip a band must ink to carry a label: measured 0.084 between
# two items, 0.000 between the rows of one 2x2 grid (N4L 2012).
LABEL_INK = 0.01


def _numpy():
    """numpy, or an error that says what to install."""
    try:
        import numpy
    except ImportError as exc:
        raise RuntimeError(_("Missing extra: {command} ({packages})").format(
            command=PDF_EXTRA, packages="numpy")) from exc
    return numpy


def _strokes(mask, horizontal: bool) -> list[int]:
    """The rows (or columns) inked enough to be a frame line.

    Neighbouring rows merge into one stroke at their middle, a printed line being
    several pixels thick.
    """
    numpy = _numpy()
    axis, span = (1, mask.shape[1]) if horizontal else (0, mask.shape[0])
    enough = numpy.flatnonzero(mask.sum(axis=axis) > STROKE_SHARE * span)

    found: list[int] = []
    group: list[int] = []
    for rank in enough:
        if group and rank - group[-1] <= STROKE_THICKNESS:
            group.append(int(rank))
            continue
        if group:
            found.append(int(sum(group) / len(group)))
        group = [int(rank)]
    if group:
        found.append(int(sum(group) / len(group)))
    return found


def _edged(mask, y0: int, y1: int, x0: int, x1: int) -> bool:
    """Are the four edges of this rectangle inked along their whole length?

    Each edge is read three pixels thick, the stroke kept being only a middle.
    """
    bands = (
        mask[max(0, y0 - 1):y0 + 2, x0:x1].max(axis=0),
        mask[max(0, y1 - 1):y1 + 2, x0:x1].max(axis=0),
        mask[y0:y1, max(0, x0 - 1):x0 + 2].max(axis=1),
        mask[y0:y1, max(0, x1 - 1):x1 + 2].max(axis=1),
    )
    return all(band.size and band.mean() >= EDGE_FULL for band in bands)


def _page_frames(mask) -> list[tuple[float, float, float, float]]:
    """The frames of an inked page, in fractions of a page: (top, bottom, left, right)."""
    height, width = mask.shape
    horizontal, vertical = _strokes(mask, True), _strokes(mask, False)
    min_area = FRAME_AREA_MIN * height * width

    found = []
    for i, y0 in enumerate(horizontal):
        for y1 in horizontal[i + 1:]:
            for j, x0 in enumerate(vertical):
                for x1 in vertical[j + 1:]:
                    if (y1 - y0) * (x1 - x0) < min_area:
                        continue
                    if _edged(mask, y0, y1, x0, x1):
                        found.append((y0, y1, x0, x1))

    # A frame containing another is the rule around a grid, not a figure.
    kept = [c for c in found
            if not any(d is not c and c[0] <= d[0] and c[1] >= d[1]
                       and c[2] <= d[2] and c[3] >= d[3] for d in found)]
    return sorted((y0 / height, y1 / height, x0 / width, x1 / width)
                  for y0, y1, x0, x1 in kept)


def _rows(boxes: list[tuple[float, float, float, float]]
          ) -> list[list[tuple[float, float, float, float]]]:
    """The frames gathered by row: two that overlap in height are side by side."""
    rows: list[list[tuple[float, float, float, float]]] = []
    for box in sorted(boxes):
        if rows and box[0] < max(b[1] for b in rows[-1]):
            rows[-1].append(box)
        else:
            rows.append([box])
    return rows


def _page_blocks(mask, frames: list[tuple[float, float, float, float]]
                 ) -> tuple[tuple[tuple[float, float, float, float], ...], ...]:
    """The frames of an inked page, gathered by ITEM.

    The label opening an item (「2ばん」) is printed in the margin level with its
    figures, where the rows of one grid have bare paper: ink there starts an item.
    No margin left of the figures gives one block, and `exam_items` drops the
    image when the count disagrees, so a missed label never shows the neighbour.
    """
    height, width = mask.shape
    left = min(b[2] for b in frames)
    strip = slice(max(0, int((left - LABEL_STRIP) * width)), int(left * width))

    rows = _rows(frames)
    blocks = [list(rows[0])]
    for above, row in zip(rows, rows[1:]):
        band = mask[int(max(b[1] for b in above) * height):int(row[0][0] * height),
                    strip]
        if band.size and band.mean() >= LABEL_INK:
            blocks.append([])
        blocks[-1].extend(row)
    return tuple(tuple(sorted(block)) for block in blocks)


def scanned_items(source: bytes | Path | str, *, scale: float = FRAME_SCALE
                  ) -> dict[int, tuple[tuple[tuple[float, float, float, float], ...], ...]]:
    """The printed frames of each page, gathered by item, page counted from 1.

    Cut by the printed labels (`_page_blocks`), which unlike the gaps of
    `group_into` need not be told how many items there are. A page with no frame
    is left out, as in `drawings`.
    """
    pypdfium2, _image = _deps()
    numpy = _numpy()
    import io

    if isinstance(source, (str, Path)):
        source = Path(source).read_bytes()
    by_page: dict[int, tuple[tuple[tuple[float, float, float, float], ...], ...]] = {}
    with pypdfium2.PdfDocument(io.BytesIO(source)) as document:
        for rank in range(len(document)):
            image = document[rank].render(scale=scale).to_pil().convert("L")
            mask = numpy.asarray(image) < INK_LEVEL
            frames = _page_frames(mask)
            if frames:
                by_page[rank + 1] = _page_blocks(mask, frames)
    return by_page


def pages_with_figures(source: bytes | Path | str) -> list[int]:
    """The pages carrying item drawings, in order.

    A page one object covers entirely (a full-page notice, a scanned cover) is not.
    """
    scans = {p.number for p in probe(source) if p.scan}
    return [n for n in sorted(drawings(source)) if n not in scans]


def group_into(page_boxes: list[tuple[float, float, float, float]],
               count: int) -> list[list[tuple[float, float, float, float]]]:
    """Files boxes into `count` groups, cutting at the largest gaps.

    `count` comes from reading the printed numbers: geometry cannot guess it.
    Cutting at the `count - 1` largest vertical gaps needs no threshold, and keeps
    a 2x2 grid whole when the gap between items is the page's largest.
    """
    page_boxes = sorted(page_boxes)
    if count <= 1 or len(page_boxes) <= count:
        return [page_boxes] if count <= 1 else [[b] for b in page_boxes]

    gaps = []
    floor = page_boxes[0][1]
    for rank in range(1, len(page_boxes)):
        gaps.append((page_boxes[rank][0] - floor, rank))
        # The LOWEST bottom met so far, not the previous box's: drawings side by
        # side overlap in height, and the last one would show a false gap.
        floor = max(floor, page_boxes[rank][1])

    cuts = sorted(rank for _gap, rank in sorted(gaps, reverse=True)[:count - 1])
    groups, start = [], 0
    for cut in cuts + [len(page_boxes)]:
        groups.append(page_boxes[start:cut])
        start = cut
    return groups


def area_of(group: list[tuple[float, float, float, float]],
            strokes: tuple[tuple[float, float, float, float], ...] = ()
            ) -> tuple[float, float, float, float]:
    """The area to cut out for this group of drawings: (top, bottom, left, right).

    Bounded by the frames when there are any, so that they come in whole while the
    item number printed above them ("7ばん") stays out. Only the strokes crossing
    the group's height count: the other item's must not widen it.
    """
    top = min(b[0] for b in group)
    bottom = max(b[1] for b in group)
    left = min(b[2] for b in group)
    right = max(b[3] for b in group)

    for stroke in strokes:
        if stroke[1] < top or stroke[0] > bottom:   # entirely above or below
            continue
        top = min(top, stroke[0])
        bottom = max(bottom, stroke[1])
        left = min(left, stroke[2])
        right = max(right, stroke[3])

    return (max(0.0, top - BREATH), min(1.0, bottom + BREATH),
            max(0.0, left - BREATH), min(1.0, right + BREATH))


# Share of the page below which a box frames nothing: the smallest document
# recorded covers 0.209 (N4R p.3), the 「読解」 tab in the margin 0.006.
FRAME_MIN = 0.05


def frame(page: Objects) -> tuple[float, float, float, float] | None:
    """The area of the composed document on this page, or None if there is none.

    A 読解 booklet lays out ONE document per page (a poster, a timetable, a memo):
    the largest box, stroke or image, never widened by the strokes crossing it as
    in `area_of`, since the margin tab would stretch it to the edge. None, the
    common case, is a page of prose.
    """
    every = list(page.images) + list(page.strokes)
    if not every:
        return None
    largest = max(every, key=lambda b: (b[1] - b[0]) * (b[3] - b[2]))
    top, bottom, left, right = largest
    if (bottom - top) * (right - left) < FRAME_MIN:
        return None
    return (max(0.0, top - BREATH), min(1.0, bottom + BREATH),
            max(0.0, left - BREATH), min(1.0, right + BREATH))


def render_area(source: bytes | Path | str, page: int,
                area: tuple[float, float, float, float],
                *, scale: float = 2.0) -> bytes:
    """The `(top, bottom, left, right)` area of a page, as PNG.

    Cut in BOTH directions: the frames say where the options stop, and the whole
    width would only add the page's white margins.
    """
    pypdfium2, _image = _deps()
    import io

    if isinstance(source, (str, Path)):
        source = Path(source).read_bytes()
    buffer = io.BytesIO()
    # Cropped and saved inside the `with`: the PIL image shares the bitmap's
    # memory, which closing the document frees.
    with pypdfium2.PdfDocument(io.BytesIO(source)) as document:
        image = document[page - 1].render(scale=scale).to_pil()

        top, bottom, left, right = area
        width_px, height_px = image.size
        box = (int(max(0.0, left) * width_px), int(max(0.0, top) * height_px),
               int(min(1.0, max(left, right)) * width_px),
               int(min(1.0, max(top, bottom)) * height_px))
        image.crop(box).save(buffer, "PNG", optimize=True)
    return buffer.getvalue()
