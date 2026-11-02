"""Cut out of a page the document laid out on it: poster, table, timetable, memo.

Some JLPT reading items (情報検索) are a table or a diagram, whose layout is lost
in plain text. The transcription says which texts are such documents
(`pdf_source.extract_texts`), since no surface threshold can. Their page is found
here by matching kana and kanji with each page's text layer, the model's page
numbers being off by one (see `pdf_source.extract_items`). Nothing is guessed:
with no page or no frame found, the text stays a text, with no image.
"""

from __future__ import annotations

import re
from pathlib import Path

from kotogen.furigana import JP_RUN_RE, strip_furigana
from kotogen.generators import pdf_figures

# Length of a fingerprint, in kana and kanji: long enough not to occur on a page
# by chance, short enough for a title line to give one.
NGRAM = 6

# Breaks between chunks, such as the cells of a table row: a fingerprint across
# two is on no page and lowers the score. Never a single space, which furigana
# notation puts before each kanji group (`彼[かれ]は 学校[がっこう]に`).
_SPLIT_RE = re.compile(r"[\n\t　]+| {2,}")

# Share of a text's fingerprints its page must carry. Half, not nearly all: the
# text layer loses the digits and misplaces the furigana. Measured on four
# documents: 0.73 to 0.93 on the right page, 0.07 at most on the next best.
MATCH_MIN = 0.5

# Fewer fingerprints than this identify nothing, a page could carry them by
# chance. A station diagram, the sparsest document measured, gives fifteen.
FINGERPRINTS_MIN = 5


def _slices(chain: str) -> set[str]:
    """The NGRAM-character slices of an uninterrupted chain."""
    return {chain[start:start + NGRAM]
            for start in range(len(chain) - NGRAM + 1)}


def _japanese(chunk: str) -> str:
    """The kana and kanji of a chunk, in a row, the rest removed.

    Digits go from both sides: booklets print them as drawings, so the text layer
    lacks them while the model transcribes them.
    """
    return "".join(JP_RUN_RE.findall(strip_furigana(chunk or "")))


def fingerprints(lines: list[str]) -> set[str]:
    """The fingerprints of a transcribed text: the needle.

    Cut at the blanks of the layout (`_SPLIT_RE`), so that none straddles two
    chunks that do not touch on the page.
    """
    slices: set[str] = set()
    for line in lines:
        for chunk in _SPLIT_RE.split(line or ""):
            slices |= _slices(_japanese(chunk))
    return slices


def page_fingerprints(text: str) -> set[str]:
    """The fingerprints of a booklet page: the haystack.

    Taken in one block, unlike the needle: the text layer is not in reading
    order, and a spurious fingerprint in the haystack costs nothing.
    """
    return _slices(_japanese(text))


def page_of_text(source: bytes | Path | str, lines: list[str]) -> int:
    """The page this text is laid out on, counted from 1; 0 if unknown.

    0 is not an error: a text too short to identify, a document laid out as an
    image, a scanned booklet, or a tie. The card is then made with no image.
    """
    wanted = fingerprints(lines)
    if len(wanted) < FINGERPRINTS_MIN:
        return 0

    scores = sorted(
        ((len(wanted & page_fingerprints(text)) / len(wanted), number)
         for number, text in pdf_figures.page_texts(source).items()),
        reverse=True)

    if not scores or scores[0][0] < MATCH_MIN:
        return 0
    # A tie: one page may carry the document and the other its questions.
    if len(scores) > 1 and scores[1][0] >= scores[0][0]:
        return 0
    return scores[0][1]


# Rendering scale before the cut. The documents measured span 0.71 to 0.84 of an
# A4 width, 1270 to 1500 px here: near `pdf_pages.PAGE_WIDTH` (1400 px) with no
# enlarging. A wider cut is brought down when written.
SCALE = 3.0


def cut_out(source: bytes | Path | str,
            lines: list[str]) -> tuple[int, bytes] | None:
    """(page, PNG image of the document) for this text, or None if it is not found.

    None is not a failure: the text stays a text.
    """
    page = page_of_text(source, lines)
    if not page:
        return None
    pages = pdf_figures.boxes(source)
    area = pdf_figures.frame(pages[page]) if page in pages else None
    if area is None:
        return None
    return page, pdf_figures.render_area(source, page, area, scale=SCALE)
