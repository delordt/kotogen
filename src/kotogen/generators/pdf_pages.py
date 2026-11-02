"""Pages of a document (a PDF, or images) rendered to JPEG for the mini-book.

The pages fill the `Images` field the reading card leafs through. They are
rendered here once rather than in the card: no Anki webview shows a PDF reliably
(iOS, Android), and pdf.js at every review would cost more than the JPEGs. The
"pdf" extra brings pypdfium2 (rendering) and Pillow (JPEG, and images to PDF).
"""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

from kotogen import console
from kotogen.exporter import image_ref
from kotogen.generators import pdf_figures
from kotogen.generators.text_source import clean_path
from kotogen.i18n import _, quoted

# Rendering width: wider mostly adds weight to sync to the phone, while at 1400
# px a scanned A5 page stays readable and the card's zoom has detail to show.
PAGE_WIDTH = 1400
JPEG_QUALITY = 82
# A tiny page (a thumbnail) is not enlarged past this: it would only be blur.
MAX_SCALE = 4.0

IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"})

# Translated where it is raised: a module-level `_()` would resolve the language
# before `cli.main()` loads the settings.
_MISSING_DEPS = (
    "page rendering unavailable ({module} is missing).\n"
    "   Install the dedicated extra, in the kotogen folder:  {command}"
)


def _deps():
    """(pypdfium2, PIL.Image), or an error that says what to install."""
    try:
        import pypdfium2
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(_(_MISSING_DEPS).format(
            module=exc.name, command=pdf_figures.PDF_EXTRA)) from exc
    return pypdfium2, Image


# -- Recognising the inputs ---------------------------------------------------

def is_image_file(s: str) -> bool:
    """True if the input names an image file that exists."""
    path = clean_path(s or "")
    return path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES


def is_image_source(s: str) -> bool:
    """True if the input is an image, or a folder holding some."""
    return is_image_file(s) or bool(list_images(clean_path(s or "")))


def list_images(path: Path) -> list[Path]:
    """The images of a folder, in name order (page01, page02...), or [].

    Name order is book order, as converters number their pages.
    """
    if not path.is_dir():
        return []
    return sorted((p for p in path.iterdir()
                   if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES),
                  key=lambda p: p.name.lower())


def resolve_images(s: str) -> list[Path]:
    """The images the input names: the file alone, or the whole folder."""
    path = clean_path(s)
    return [path] if is_image_file(s) else list_images(path)


# -- Page range ---------------------------------------------------------------

_RANGE_RE = re.compile(r"(\d+)(?:-(\d*))?")


def parse_pages(spec: str | None, total: int) -> list[int]:
    """"3-18", "5", "1,4,7-9", "12-" -> page indices (0 = the first one).

    The numbers are those read off the document. An empty range gives the whole
    document; one naming no existing page raises here, before any AI call.
    """
    if not spec or not spec.strip():
        return list(range(total))

    pages: list[int] = []
    for chunk in re.split(r"[,\s]+", spec.strip()):
        if not chunk:
            continue
        match = _RANGE_RE.fullmatch(chunk)
        if not match:
            raise ValueError(
                _("unreadable page range: {chunk} (expected: 3, 3-18, or 12-)")
                .format(chunk=quoted(chunk)))
        start = int(match.group(1))
        if match.group(2) is None:      # "5": one page
            end = start
        elif match.group(2) == "":      # "12-": to the end
            end = total
        else:
            end = int(match.group(2))
        if start > total:
            raise ValueError(
                _("the document only has {total} {pages}: {chunk} does not exist")
                .format(total=total, pages=console.plural(total, "page"),
                        chunk=quoted(chunk)))
        if start < 1 or end < start:
            raise ValueError(_("inconsistent page range: {chunk}")
                             .format(chunk=quoted(chunk)))
        pages.extend(range(start - 1, min(end, total)))

    # Duplicates removed, order of entry kept: "5,1-3" was asked for that way.
    seen: set[int] = set()
    unique = [p for p in pages if not (p in seen or seen.add(p))]
    if not unique:
        raise ValueError(_("no page kept: the document has {total}")
                         .format(total=total))
    return unique


# -- What kind of document is this --------------------------------------------
# A PDF is read as text or as pages, decided from two free local measurements:
# the share of the page covered by images, and the density of Japanese in the
# text layer. Only a scan, with no text layer, is left to the model to settle.
# An unreadable text layer (a broken ToUnicode table, common in JLPT past
# papers) merely counts no Japanese: the model reads the pages either way.

# Image cover above which the images, not the text over them, carry the page.
IMAGE_COVER = 0.6
# Japanese characters per page above which a page is a text, even in image form:
# an album carries a few dozen, a past paper's reading page several hundred.
TEXT_PER_PAGE = 250
# Pages examined at most: a long book need not be read whole to say what it is.
SAMPLE_PAGES = 12

# Kana and kanji only: punctuation and digits appear in a Latin PDF too.
_JAPANESE = re.compile("[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")


def _sample(indices: list[int]) -> list[int]:
    """Up to SAMPLE_PAGES pages spread over the whole range kept.

    Spread rather than the first ones, whose full-page cover would pass a
    textbook for an album.
    """
    if len(indices) <= SAMPLE_PAGES:
        return indices
    step = len(indices) / SAMPLE_PAGES
    return [indices[int(i * step)] for i in range(SAMPLE_PAGES)]


def measure(pdf_bytes: bytes, indices: list[int]) -> tuple[float, float]:
    """(Japanese characters per page, share of the page covered by images).

    The coverage is capped at 1 per page, for overlapping images.
    """
    pypdfium2, _image = _deps()
    pages = _sample(indices) or [0]

    chars = 0
    cover = 0.0
    with pypdfium2.PdfDocument(io.BytesIO(pdf_bytes)) as document:
        for index in pages:
            page = document[index]
            area = max(page.get_width() * page.get_height(), 1)
            chars += len(_JAPANESE.findall(page.get_textpage().get_text_range()))
            covered = 0.0
            for obj in page.get_objects():
                if obj.type == pypdfium2.raw.FPDF_PAGEOBJ_IMAGE:
                    left, bottom, right, top = obj.get_bounds()
                    covered += abs(right - left) * abs(top - bottom)
            cover += min(covered / area, 1.0)
    return chars / len(pages), cover / len(pages)


def read_mode(pdf_bytes: bytes, spec: str | None = None) -> tuple[str | None, str]:
    """How to read this PDF: "text", "book", or None if the model must settle it.

    With the decision, what it came down to, for `console.done` to show. None is
    not a failure: scanned pages, which go to the model anyway. This is how to
    read the document, not each text: `pdf_documents` cuts out the composed ones.
    """
    try:
        indices = parse_pages(spec, page_count(pdf_bytes))
        chars, cover = measure(pdf_bytes, indices)
    except RuntimeError:
        # Without the "pdf" extra nothing is measured, but the model still reads it.
        return None, _("not measurable here -> the model settles it")

    return _verdict(len(indices), chars, cover)


def _verdict(pages: int, chars: float, cover: float) -> tuple[str | None, str]:
    """The decision and what carried it, from the two measurements. Pure logic."""
    if cover < IMAGE_COVER:
        return "text", _("{percent}% image -> read as text").format(
            percent=f"{cover * 100:.0f}")
    if chars >= TEXT_PER_PAGE:
        return "text", _("in image form but {chars} char./page -> read as text").format(
            chars=f"{chars:.0f}")
    if chars >= 1:
        return "book", _("in image form, {chars} char./page -> mini-book").format(
            chars=f"{chars:.0f}")
    if pages == 1:
        # A single page is one reading, and showing it keeps the exercise's layout.
        return "book", _("a single page, no text layer -> mini-book")
    return None, _("{pages} pages with no text layer -> the model settles it").format(
        pages=pages)


# -- Naming in the media library ----------------------------------------------

def slug(name: str) -> str:
    """A short ASCII file name, drawn from the title of the document.

    A Japanese name does not survive every Anki client's media library. It may
    come out empty: the fingerprint after it tells two books apart.
    """
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()[:40]


def digest(data: bytes) -> str:
    """A short fingerprint of the document, which goes into the page names.

    Media names are shared by the whole collection. Taken from the content, it
    makes a book regenerated rewrite its files rather than add new ones.
    """
    return hashlib.sha1(data).hexdigest()[:8]


def media_name(stem: str, mark: str, number: int) -> str:
    """A page name in collection.media: reading_<title>_<fingerprint>_p003.jpg."""
    parts = ["reading", slug(stem), mark]
    return "_".join(p for p in parts if p) + f"_p{number:03}.jpg"


def images_field(paths: list[Path]) -> str:
    """The Images field of the card: the tags the mini-book will leaf through."""
    return "".join(image_ref(p.name) for p in paths)


# -- Rendering ----------------------------------------------------------------

def page_count(pdf_bytes: bytes) -> int:
    pypdfium2, _image = _deps()
    with pypdfium2.PdfDocument(io.BytesIO(pdf_bytes)) as document:
        return len(document)


def subset(pdf_bytes: bytes, indices: list[int]) -> bytes:
    """The sub-document of the pages kept, as it will leave for the model.

    The model gets exactly what the card shows, rather than the whole document,
    cover included, and a page range it might miscount.
    """
    pypdfium2, _image = _deps()
    with pypdfium2.PdfDocument(io.BytesIO(pdf_bytes)) as source:
        if list(indices) == list(range(len(source))):
            return pdf_bytes
        buffer = io.BytesIO()
        with pypdfium2.PdfDocument.new() as target:
            target.import_pages(source, indices)
            target.save(buffer)
    return buffer.getvalue()


def _save_jpeg(image, path: Path) -> None:
    """Writes the image as JPEG at the rendering width (never enlarged past it)."""
    from PIL import Image as PILImage

    if image.mode != "RGB":
        image = image.convert("RGB")
    if image.width > PAGE_WIDTH:
        height = round(image.height * PAGE_WIDTH / image.width)
        image = image.resize((PAGE_WIDTH, height), PILImage.LANCZOS)
    image.save(path, "JPEG", quality=JPEG_QUALITY, optimize=True)


def render_pdf(pdf_bytes: bytes, indices: list[int], out_dir: Path,
               stem: str) -> list[Path]:
    """Renders the pages kept as JPEG in out_dir; returns the files created.

    Each is named after its page number in the PDF, the mark being the whole
    document's: two ranges of it must neither share an `Images` field (and the
    card IDs drawn from it) nor overwrite each other's pages.
    """
    pypdfium2, _image = _deps()
    out_dir.mkdir(parents=True, exist_ok=True)
    mark = digest(pdf_bytes)

    paths: list[Path] = []
    made = [0]

    def render() -> None:
        # Saved inside the `with`: the PIL image shares the bitmap's memory,
        # which closing the document frees.
        with pypdfium2.PdfDocument(io.BytesIO(pdf_bytes)) as document:
            for rank, index in enumerate(indices, 1):
                page = document[index]
                scale = min(PAGE_WIDTH / max(page.get_width(), 1), MAX_SCALE)
                image = page.render(scale=scale).to_pil()
                path = out_dir / media_name(stem, mark, index + 1)
                _save_jpeg(image, path)
                paths.append(path)
                made[0] = rank

    # About ten seconds for twenty pages, so the wait counts them.
    console.while_working(render,
                          lambda: _("page {number} of {total}").format(
                              number=min(made[0] + 1, len(indices)),
                              total=len(indices)))
    return paths


def save_image(data: bytes, out_dir: Path, stem: str, number: int) -> Path:
    """Files an ALREADY rendered image in the media library, in the page mould.

    For the full-size PNG `pdf_documents` cuts out: bounded width, JPEG, page
    naming. Its fingerprint is the image's own, so a second cut rewrites the file.
    """
    _pypdfium2, Image = _deps()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / media_name(stem, digest(data), number)
    with Image.open(io.BytesIO(data)) as image:
        _save_jpeg(image, path)
    return path


def render_images(sources: list[Path], out_dir: Path, stem: str) -> list[Path]:
    """Normalises images already prepared (size, JPEG, media library naming).

    The mould of the rendered pages: a 4000 px scan shows nothing more on screen
    and weighs ten times as much to sync.
    """
    _pypdfium2, Image = _deps()
    out_dir.mkdir(parents=True, exist_ok=True)
    mark = digest(b"".join(hashlib.sha1(p.read_bytes()).digest() for p in sources))

    paths: list[Path] = []
    for number, source in enumerate(sources, 1):
        with Image.open(source) as image:
            path = out_dir / media_name(stem, mark, number)
            _save_jpeg(image, path)
        paths.append(path)
    return paths


def to_pdf(paths: list[Path]) -> bytes:
    """Assembles images into a PDF, the only form the model can read."""
    _pypdfium2, Image = _deps()
    pages = [Image.open(p).convert("RGB") for p in paths]
    try:
        buffer = io.BytesIO()
        pages[0].save(buffer, "PDF", save_all=True, append_images=pages[1:])
        return buffer.getvalue()
    finally:
        for page in pages:
            page.close()
