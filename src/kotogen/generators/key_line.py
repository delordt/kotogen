"""The rank of the line that carries the answer, in a text split into lines.

The comprehension cards hold one sentence per line (`Text`, `Transcript`) and
fields keyed by line rank (translations, timestamps). The key line is one more:
a number rather than a marker in the text, which keeps the text free of
annotation and the transcript identical across the cards of one passage.
"""

from __future__ import annotations

from collections.abc import Sequence


def rank(value: object, total: int) -> str:
    """The rank as text, or "" if it designates no existing line.

    Better nothing highlighted than the wrong line. The model answers `2` or
    `"2"`, and both are accepted; `True` is not a rank.
    """
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value)
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= total:
        return str(value)
    return ""


def page(value: object, page_of_line: Sequence[int]) -> str:
    """The page the key line was read on, or "" if it designates none.

    For the mini-book, which shows pages while the model counts lines: the map
    comes from the transcription (`pdf_source.Text.page_of_line`). An empty map
    gives "", and the back opens the book at its first page.
    """
    number = rank(value, len(page_of_line))
    return str(page_of_line[int(number) - 1]) if number else ""
