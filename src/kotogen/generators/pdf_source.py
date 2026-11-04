"""PDF source: study content pulled out of a local document.

For the vocab and reading modes, and for the past-paper booklets that give a
listening card its figure (`exam_items`). The PDF goes to the model as it is (see
`AIClient.chat_pdf`), which reads scans and broken text layers alike (a failing
ToUnicode table, common in JLPT past papers): no extraction dependency. A
document the model cannot use comes back as `{"error": "reason"}`, raised here
as a RuntimeError.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kotogen import prompts
from kotogen.ai_client import AIClient
from kotogen.generators.text_source import clean_path
from kotogen.i18n import _, counted, quoted

# Beyond this the APIs refuse the document (~32 MB / 100 pages at Anthropic).
MAX_PDF_BYTES = 25 * 1024 * 1024


# -- Recognising and loading --------------------------------------------------

def is_pdf_input(s: str) -> bool:
    """True if the input names a PDF document (existence is checked on loading)."""
    return str(clean_path(s or "")).lower().endswith(".pdf")


def load_pdf(path: Path) -> bytes:
    """Reads the PDF and validates its size and signature. Raises RuntimeError otherwise."""
    if not path.is_file():
        raise RuntimeError(_("file not found: {path}").format(path=path))
    data = path.read_bytes()
    if not data.startswith(b"%PDF"):
        raise RuntimeError(_("not a valid PDF file: {path}").format(path=path))
    if len(data) > MAX_PDF_BYTES:
        raise RuntimeError(
            _("PDF too large ({size} MB > {limit} MB) - split it first.").format(
                size=len(data) // (1024 * 1024),
                limit=MAX_PDF_BYTES // (1024 * 1024)))
    return data


# -- The error contract -------------------------------------------------------

def _raise_if_error(result) -> None:
    """Propagates the model's error contract (`{"error": ...}`) as a RuntimeError.

    The model's reason (see `pdf_error_contract`) lands in a translated sentence:
    a French screen shows a French frame around an English reason.
    """
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(_("document unusable: {reason}")
                           .format(reason=result["error"]))


# -- Vocabulary ---------------------------------------------------------------

def extract_vocab(client: AIClient, pdf_bytes: bytes, filename: str,
                  count: int, level: str) -> list[str]:
    """Extracts the vocabulary words of the document (count = 0 -> the maximum)."""
    limit_part = (
        f"Extract at most {count} words."
        if count else
        "Extract the MAXIMUM of words: every useful vocabulary word of the document."
    )
    level_part = (
        f"Aim first at words of roughly JLPT level {level} "
        "(ignore the markedly easier ones)."
        if level != "auto" else
        "Ignore the ultra-basic words (です, する, 人...) in favour of words that "
        "really enrich the vocabulary."
    )
    user_msg = f'Document "{filename}" attached. {limit_part} {level_part}'
    result = client.chat_json_pdf(prompts.load("pdf_vocab"), user_msg,
                                  pdf_bytes, filename)
    _raise_if_error(result)
    if not isinstance(result, list):
        raise ValueError(_("unexpected JSON structure: {kind}").format(kind=type(result).__name__))
    entries = [str(w).strip() for w in result if str(w).strip()]
    return entries[:count] if count else entries


# -- Reading ------------------------------------------------------------------

@dataclass(frozen=True)
class Text:
    """A reading support found in a document, and how it is read.

    `document` is true when the layout is the exercise (a poster, a timetable):
    `pdf_documents` then cuts its page out as an image. The lines are transcribed
    either way, for the questions and the back. An answer silent on it is prose.
    """

    title: str
    lines: list[str]
    document: bool = False
    # The page each line was read on. Filled for a mini-book alone, and empty
    # when the model did not tell the pages apart (see `_reading_lines`).
    page_of_line: tuple[int, ...] = ()


def _reading_lines(item: dict, pages: int) -> tuple[list[str], tuple[int, ...]]:
    """The lines of a transcription, and the page each of them was read on.

    Read page by page, the answer has a `pages` key (one group per page sent, the
    empty ones included); read flat, a `lines` list and no map. The map is kept
    only when the count of groups is the one asked for: one group missing would
    shift every later line onto the wrong page, which is worse than no page.
    """
    groups = item.get("pages")
    if isinstance(groups, list) and all(isinstance(group, list) for group in groups):
        lines: list[str] = []
        page_of_line: list[int] = []
        for number, group in enumerate(groups, start=1):
            kept = [str(line).strip() for line in group if str(line).strip()]
            lines += kept
            page_of_line += [number] * len(kept)
        return lines, tuple(page_of_line) if pages and len(groups) == pages else ()
    return [str(l).strip() for l in (item.get("lines") or []) if str(l).strip()], ()


def _readings(items, pages: int = 0) -> list[Text]:
    """[{"kind", "title", "lines" | "pages"}] -> [Text], the empty entries dropped.

    The keys are the protocol of `pdf_texts`, English whatever the language of the
    cards. `pages`: how many pages were sent, for a reading transcribed page by
    page; zero for a text read flat.
    """
    texts: list[Text] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        lines, page_of_line = _reading_lines(item, pages)
        nature = str(item.get("kind", "")).strip().lower()
        if lines:
            texts.append(Text(title, lines, nature == "document", page_of_line))
    return texts


def extract_texts(client: AIClient, pdf_bytes: bytes, filename: str,
                  max_texts: int | None) -> list[Text]:
    """The reading supports of the document, prose and composed documents mixed.

    max_texts = None -> every text identified.
    """
    limit_part = (
        f"Extract at most {max_texts} text(s)."
        if max_texts else
        "Extract ALL the reading texts of the document."
    )
    user_msg = f'Document "{filename}" attached. {limit_part}'
    result = client.chat_json_pdf(prompts.load("pdf_texts"), user_msg,
                                  pdf_bytes, filename)
    _raise_if_error(result)
    if isinstance(result, dict):
        result = [result]
    if not isinstance(result, list):
        raise ValueError(_("unexpected JSON structure: {kind}").format(kind=type(result).__name__))

    texts = _readings(result)
    return texts[:max_texts] if max_texts else texts


# -- Reading as a mini-book ---------------------------------------------------

def extract_map(client: AIClient, pdf_bytes: bytes, filename: str,
                pages: int, *, whole: bool = False) -> list[dict]:
    """The map of a 聴解 booklet: what each page carries, in order.

    One entry per page sent, empty ones included:
    `[{"section": 1 | None, "items": [{"number": 1, "figure": True, "example": False},
    ...]}, ...]`, the example of a section listed with its number None.
    The model's page numbers are off by one and ignored; its order holds, so the
    count is checked, and a mismatch raises rather than put figures on the wrong
    items. `whole` only tells the model whether it receives the whole booklet.
    """
    carrying = ("the whole booklet" if whole
                else "all of them carrying drawings of items")
    user_msg = f'Booklet "{filename}" attached: {pages} page(s), {carrying}.'
    result = client.chat_json_pdf(prompts.load("pdf_items"), user_msg,
                                  pdf_bytes, filename)
    _raise_if_error(result)

    returned = (result or {}).get("Pages") if isinstance(result, dict) else None
    if not isinstance(returned, list):
        raise RuntimeError(_("booklet map unreadable (no {field})").format(
            field=quoted("Pages")))
    if len(returned) != pages:
        raise RuntimeError(
            counted(len(returned),
                    "booklet map incomplete: {described} page described for {sent} "
                    "sent - the figures would no longer face the right items",
                    "booklet map incomplete: {described} pages described for {sent} "
                    "sent - the figures would no longer face the right items")
            .format(described=len(returned), sent=pages))

    chart = []
    for page in returned:
        page = page or {}
        items = page.get("items") or []
        chart.append({
            "section": _int_or_none(page.get("section")),
            "items": [_item(i) for i in items if isinstance(i, dict) and (
                i.get("example") is True or str(i.get("number", "")).strip().isdigit())],
        })
    return chart


def _item(raw: dict) -> dict:
    """One entry of a page: an item, or the example, kept so that its drawing
    is not handed to an item (`exam_items.Booklet._place`)."""
    if raw.get("example") is True:
        return {"number": None, "figure": bool(raw.get("figure")), "example": True}
    return {"number": int(raw["number"]), "figure": bool(raw.get("figure")), "example": False}


def _int_or_none(value) -> int | None:
    """A section number as the model returned it, or None.

    None for anything but a plain positive integer: the page then stays in the
    section opened before it, where a guessed value could be the wrong one.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value).strip()
    return int(text) if text.isdigit() and int(text) > 0 else None


def extract_items(client: AIClient, pdf_bytes: bytes, filename: str,
                  pages: int) -> list[list[dict]]:
    """The items of each page sent, in order: the map without its sections.

    For the typeset-booklet route, which reads its sections in the text layer.
    """
    return [page["items"] for page in extract_map(client, pdf_bytes, filename, pages)]


def extract_reading(client: AIClient, pdf_bytes: bytes, filename: str,
                    pages: int) -> Text:
    """The whole document seen as ONE reading, its lines placed on its pages.

    The mini-book counterpart of `extract_texts`. The card shows the pages: the
    text only feeds the questions, and its `page_of_line` says where the back opens.
    """
    user_msg = (f'Document "{filename}" attached: {pages} page(s) forming '
                "one single reading, in order. Hand the lines back grouped by "
                f"page: exactly {pages} group(s), the empty ones included.")
    result = client.chat_json_pdf(prompts.load("pdf_reading"), user_msg,
                                  pdf_bytes, filename)
    _raise_if_error(result)
    # The model sometimes answers with an array, as `pdf_texts` asks: its first
    # element is then the reading.
    if isinstance(result, list):
        result = result[0] if result else {}
    if not isinstance(result, dict):
        raise ValueError(_("unexpected JSON structure: {kind}").format(kind=type(result).__name__))

    title = str(result.get("title", "")).strip()
    lines, page_of_line = _reading_lines(result, pages)
    if not lines:
        raise RuntimeError(_("no Japanese text transcribed from these pages"))
    return Text(title, lines, page_of_line=page_of_line)


# -- Arbitration: nature AND content, in one single call ----------------------

def extract_mode_and_texts(client: AIClient, pdf_bytes: bytes, filename: str,
                           pages: int, max_texts: int | None = None
                           ) -> tuple[str, list[Text]]:
    """A scanned document: how to read it, and its content. ("book"|"text", texts).

    For pages with no text layer, which `pdf_pages.read_mode` cannot settle: the
    call that reads them decides. In "book" mode the list holds a single reading.
    """
    limit_part = (f" If it is a matter of text, extract at most {max_texts} text(s)."
                  if max_texts else "")
    scope = f": {pages} page(s) in image form" if pages else ""
    book_part = (f" If it is a book, hand its lines back grouped by page: exactly "
                 f"{pages} group(s), the empty ones included." if pages else "")
    user_msg = f'Document "{filename}" attached{scope}.{limit_part}{book_part}'
    result = client.chat_json_pdf(prompts.load("pdf_arbitration"), user_msg,
                                  pdf_bytes, filename)
    _raise_if_error(result)
    # A bare list of texts: nothing called for the images, so text.
    if isinstance(result, list):
        result = {"type": "text", "texts": result}
    if not isinstance(result, dict):
        raise ValueError(_("unexpected JSON structure: {kind}").format(kind=type(result).__name__))

    kind = str(result.get("type", "")).strip().lower()
    mode = "book" if kind == "book" else "text"
    # The page map only means anything in book mode, where the back opens at a page.
    texts = _readings(result.get("texts"), pages if mode == "book" else 0)
    if not texts:
        raise RuntimeError(_("no Japanese text transcribed from these pages"))
    if mode == "book":
        texts = texts[:1]
    elif max_texts:
        texts = texts[:max_texts]
    return mode, texts
