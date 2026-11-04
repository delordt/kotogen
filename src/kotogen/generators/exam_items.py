"""Recognising the past-paper exercise a card is drawn from: its type, its figure.

The figure: a 課題理解 item draws its options in the booklet, which the audio
does not spell out. The exercise is read from the file name of an official
sample, or from the 「3ばん」 the split heard in a section file
(`announcements.block_item`), and `Booklet` finds it in the PDF. The type: two of
them are a prompt and three replies, which the listening chain must know before
generating (`section_type`, `looks_like_choice`). Nothing is guessed: what is
not found gives no image, since the figure of another exercise is worse than none.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from kotogen import system
from kotogen.ai_client import AIClient
from kotogen.furigana import surface_key
from kotogen.generators import pdf_figures, pdf_source

# JLPT level carried by a file name: "N5_sample…", "N5L.pdf". The key that pairs
# an audio with its booklet: the only part of the name both write the same way.
_LEVEL_RE = re.compile(r"(?<![A-Za-z0-9])([Nn][1-5])(?![0-9])")

# How the official samples write (section, item):
#   N5_sample2018-2_3     section 2, item 3   (the separator varies: -2-1 exists)
#   N5L_sample2018_m1b2   section 1, item 2   (m for mondai, b for ban)
# The level is required up front, or `3_0.mp3` and `Genki_K01-03.mp3` would read
# as exercises and a textbook card would get an exam figure.
_SECTION_ITEM_RE = re.compile(
    r"^[Nn][1-5]L?[-_].*?[-_]([0-9]{1,2})[-_]([0-9]{1,2})$")
_MONDAI_BAN_RE = re.compile(
    r"^[Nn][1-5]L?[-_].*?[-_]m([0-9]{1,2})b([0-9]{1,2})$")

# The example of a section (「れい」): it opens the exercise and is not an item.
# It is written `…_rey`, `…_rei`, `…_m1r1`, or carries the number 0.
_EXAMPLE_RE = re.compile(
    r"^[Nn][1-5]L?[-_].*?(?:[-_]re[yi]|[-_]m[0-9]{1,2}r[0-9]*)$", re.IGNORECASE)

# Section marker in the text layer of the booklet. Only these three forms are
# safe: a broader pattern also matches item numbers such as 「1かいの3ばん」.
_SECTION_RE = re.compile(r"(?:もんだい|問題|第)\s*([0-9０-９]{1,2})")

_FULLWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")

# Why a booklet gave nothing. Held in English and translated where it is
# displayed, since `_()` cannot run at import time.
NO_FIGURE_PAGE = "no figure page"


# ── What type is this exercise? ───────────────────────────────────────────────

# The make-up of the 聴解 part, section by section and level by level: fixed by
# the format in force since 2010, and read in no file. Its section counts match
# `jlpt_papers.COLLECTIONS` (checked in tests/test_exam_items.py).
TYPES: dict[str, tuple[str, ...]] = {
    "N5": ("課題理解", "ポイント理解", "発話表現", "即時応答"),
    "N4": ("課題理解", "ポイント理解", "発話表現", "即時応答"),
    "N3": ("課題理解", "ポイント理解", "概要理解", "発話表現", "即時応答"),
    "N2": ("課題理解", "ポイント理解", "概要理解", "即時応答", "統合理解"),
    "N1": ("課題理解", "ポイント理解", "概要理解", "即時応答", "統合理解"),
}

# The two types whose item is not a conversation: a prompt, then three numbered
# replies of which only one fits.
CHOICE_TYPES = ("発話表現", "即時応答")


def section_type(level: str, section: int) -> str:
    """The exercise type of that particular section, or "" if it is not known.

    The level has no default: section 4 is an 即時応答 in N4 but a 発話表現 in N3.
    """
    sections = TYPES.get((level or "").upper(), ())
    return sections[section - 1] if 1 <= section <= len(sections) else ""


def is_choice(exercise_type: str) -> bool:
    """Is this exercise type a prompt followed by answers to choose from?"""
    return exercise_type in CHOICE_TYPES


# The option heads as Whisper writes them, by rank. Mostly the digit; the kanji
# and the kana turn up when the voice detaches the number.
_HEADS = (
    ("1", "１", "一", "いち", "イチ"),
    ("2", "２", "二", "に", "ニ"),
    ("3", "３", "三", "さん", "サン"),
    ("4", "４", "四", "よん", "ヨン"),
)

# What must follow a head of any form for it to be an option number: 「1 いいですよ」
# is an option, 「1000円です」 and 「3時に行きます」 are not. Whisper detaches a
# number read out on its own.
_SEPARATORS = (" ", "　", "、", "。", "．", "，", "・", ".", ",", ":", "：")


def _opens_on(line: str, rank: int) -> bool:
    """Does this line open on the option number `rank`?"""
    text = (line or "").strip()
    for head in _HEADS[rank - 1]:
        if text.startswith(head) and text[len(head):len(head) + 1] in _SEPARATORS:
            return True
    return False


def looks_like_choice(lines) -> bool:
    """Do these lines have the shape of an item with answers to choose from?

    The fallback for `section_type` when no section is known (the 2009
    collection, one file per exam; a textbook track). Three lines opened by 1, 2
    then 3 in that order, past the first line, which is the prompt. A fourth
    option answers no: that is a 概要理解 reading its choices out, badly split.
    """
    lines = [str(line) for line in lines if str(line).strip()]
    if len(lines) < 4:
        return False
    expected = 1
    for rank, line in enumerate(lines):
        if _opens_on(line, 4):
            return False
        if rank and expected <= 3 and _opens_on(line, expected):
            expected += 1
    return expected > 3


def option_rank(line: str) -> int:
    """The option number a line opens on, or 0 when it opens on none."""
    for rank in range(1, len(_HEADS) + 1):
        if _opens_on(line, rank):
            return rank
    return 0


def answered_line(answer: str, lines) -> int:
    """The rank of the line the answer of a choice item was taken from, or 0.

    The answer is a reply copied with its number, so its line is found here; the
    model's rank, often one off as it counts on the transcript before its re-cut,
    is only the fallback. First the same text, spaces and readings aside; then
    the one line opening on the same option number. Anything less sure gives 0:
    a key line on the wrong reply would teach the wrong answer.
    """
    wanted = surface_key(answer)
    if wanted:
        for rank, line in enumerate(lines, 1):
            if surface_key(line) == wanted:
                return rank
    number = option_rank(answer)
    if not number:
        return 0
    found = [rank for rank, line in enumerate(lines, 1) if _opens_on(line, number)]
    return found[0] if len(found) == 1 else 0


@dataclass(frozen=True)
class Position:
    """Where an exercise sits in its booklet: its section, then its rank."""

    section: int
    item: int


def level_from_name(name: str) -> str:
    """The JLPT level written in a file name ("N5"), or an empty string."""
    found = _LEVEL_RE.search(name or "")
    return found.group(1).upper() if found else ""


def position_from_name(name: str) -> Position | None:
    """The position of the exercise this file name carries, or None.

    None is no error: a section's example, a file that is not a past paper, or
    a name that cannot be read. The card is then made without an image.
    """
    stem = Path(name or "").stem
    if not stem or _EXAMPLE_RE.match(stem):
        return None

    for pattern in (_MONDAI_BAN_RE, _SECTION_ITEM_RE):
        found = pattern.match(stem)
        if not found:
            continue
        section, item = int(found.group(1)), int(found.group(2))
        # Rank 0 is the other spelling of the example: `N5_sample2018-2_0` opens
        # section 2 the way `m1r1` opens the first.
        if section < 1 or item < 1:
            return None
        return Position(section, item)
    return None


def companion(audio: Path) -> Path | None:
    """The PDF booklet that goes with this audio, or None.

    Looked for next to the file, then in the parent folder (samples are often
    filed in an `audio/` subfolder), and paired on the level (`N5`). Of several
    booklets of a level (`N4L.pdf` for listening, `N4V.pdf` for vocabulary), the
    one with figure pages wins; two such give None rather than one drawn by lot.
    """
    level = level_from_name(audio.name)
    if not level:
        return None

    for folder in (audio.parent, audio.parent.parent):
        try:
            pdfs = [p for p in sorted(folder.iterdir())
                    if p.suffix.lower() == ".pdf"
                    and level_from_name(p.name) == level]
        except OSError:
            continue
        if len(pdfs) == 1:
            return pdfs[0]
        if pdfs:
            with_figures = [p for p in pdfs if _has_figures(p)]
            return with_figures[0] if len(with_figures) == 1 else None
    return None


def _has_figures(pdf: Path) -> bool:
    """Does this PDF have drawing pages? False rather than an error if unreadable."""
    try:
        return bool(pdf_figures.pages_with_figures(pdf))
    except Exception:
        return False


def _sections(source) -> dict[int, int]:
    """{section number: page where it starts}, read in the text layer."""
    pypdfium2, _img = pdf_figures._deps()
    import io

    if isinstance(source, (str, Path)):
        source = Path(source).read_bytes()
    starts: dict[int, int] = {}
    with pypdfium2.PdfDocument(io.BytesIO(source)) as document:
        for rank in range(len(document)):
            text = document[rank].get_textpage().get_text_range() or ""
            for found in _SECTION_RE.finditer(text):
                number = int(found.group(1).translate(_FULLWIDTH))
                # The first page where the section appears is authoritative: its
                # title is repeated in the instructions just below.
                starts.setdefault(number, rank + 1)
    return starts


def _section_of_page(page: int, starts: dict[int, int]) -> int | None:
    """The section a page belongs to: the last one opened before it."""
    opened = [(start, number) for number, start in starts.items() if start <= page]
    return max(opened)[1] if opened else None


# The map of a booklet is kept between runs, as drawing it costs a vision call
# and an exam is worked over several runs. Keyed by a digest of the bytes, so a
# booklet moved or renamed is found again; MAP_VERSION follows the shape of a map,
# and the read that made it (version 1 could number an example as item 1).
MAP_FOLDER = "booklets"
MAP_VERSION = 2


def _map_file(data: bytes) -> Path:
    return system.cache_dir() / MAP_FOLDER / f"{hashlib.sha256(data).hexdigest()}.json"


def _read_map(data: bytes) -> dict | None:
    """The map kept for these bytes, or None when there is none that reads."""
    try:
        raw = json.loads(_map_file(data).read_text(encoding="utf-8"))
        if raw.get("version") != MAP_VERSION:
            return None
        figures = {}
        for entry in raw["figures"]:
            area = tuple(float(edge) for edge in entry["area"])
            if len(area) != 4:
                return None
            figures[Position(int(entry["section"]), int(entry["item"]))] = (
                int(entry["page"]), area)
        return figures
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _write_map(data: bytes, figures: dict) -> None:
    """Keeps the map; one that cannot be written costs the next run its call."""
    try:
        system.write_whole(_map_file(data), json.dumps({"version": MAP_VERSION, "figures": [
            {"section": position.section, "item": position.item, "page": page,
             "area": list(area)}
            for position, (page, area) in figures.items()]}))
    except OSError:
        pass


class Booklet:
    """A past-paper booklet, read once and questioned as often as one likes.

    Its map costs one vision call, made on the first request and kept, on disk
    too (`_read_map`): the next run asks nothing of the model. A typeset
    booklet declares its figures as PDF objects and its sections in its text
    layer. A scan has neither: figures come from the printed frames, sections
    from the vision read of the items, and the printed labels are the only
    cross-check left (see `_place`).
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._figures: dict[Position, tuple[int, tuple[float, float, float, float]]] | None = None
        self._data: bytes | None = None
        # The sections where two figures claimed one item (see `_place`).
        self._claimed: set[int] = set()
        self.error = ""

    def _load(self, client: AIClient) -> dict:
        if self._figures is not None:
            return self._figures

        self._figures = {}
        try:
            self._data = pdf_source.load_pdf(self.path)
            kept = _read_map(self._data)
            if kept is not None:
                self._figures = kept
                return self._figures
            pages, objects, page_map, starts, blocks = self._survey(client)
            flagged = 0
            self._claimed = set()
            for items, page in zip(page_map, pages):
                self._place(page, items, objects[page], starts, blocks.get(page, ()))
                flagged += sum(1 for item in items
                               if item["figure"] and not item.get("example"))
            # Two figures for one item: the read numbered that section wrongly,
            # and nothing says which figure is right.
            self._figures = {position: found for position, found in self._figures.items()
                             if position.section not in self._claimed}
            # A map short of a figure is a misreading: kept under the digest of the
            # bytes, it would deny the booklet its figures for good.
            if self._figures and len(self._figures) >= flagged:
                _write_map(self._data, self._figures)
        except Exception as exc:
            # An unreadable booklet does not bring a generation down: the cards
            # are made without an image, and the reason is said once.
            self.error = str(exc)
        return self._figures

    def _survey(self, client: AIClient) -> tuple[list[int], dict, list[list[dict]], dict[int, int], dict]:
        """(figure pages, objects per page, items per page, section starts, blocks).

        PDF objects first, exact and free: a typeset booklet always declares its
        figure pages there, so finding none is the sign of a scan. `blocks`, the
        figures of a page cut up by item, is filled on the scanned route only.
        """
        pages = pdf_figures.pages_with_figures(self._data)
        if not pages:
            return self._survey_scanned(client)

        extract = _extract_pages(self._data, pages)
        page_map = pdf_source.extract_items(client, extract, self.path.name, len(pages))
        return (pages, pdf_figures.drawings(self._data), page_map,
                _sections(self._data), {})

    def _survey_scanned(self, client: AIClient) -> tuple[list[int], dict, list[list[dict]], dict[int, int], dict]:
        """The same survey, on a booklet whose every page is an image.

        The whole booklet goes to vision: a section title can open on a page with
        no figure, and the framed pages alone would put every figure in the
        first section.
        """
        from kotogen.generators import pdf_pages

        blocks = pdf_figures.scanned_items(self._data)
        if not blocks:
            raise RuntimeError(NO_FIGURE_PAGE)
        objects = {page: pdf_figures.Objects(
            tuple(sorted(box for block in page_blocks for box in block)), ())
            for page, page_blocks in blocks.items()}

        page_map = pdf_source.extract_map(
            client, self._data, self.path.name,
            pdf_pages.page_count(self._data), whole=True)

        # The first page a section appears on is authoritative, as in `_sections`.
        starts: dict[int, int] = {}
        for rank, page in enumerate(page_map, 1):
            if page["section"] is not None:
                starts.setdefault(page["section"], rank)

        pages = sorted(objects)
        return (pages, objects, [page_map[page - 1]["items"] for page in pages],
                starts, blocks)

    def _place(self, page: int, items: list[dict], objects, starts: dict[int, int],
               blocks: tuple = ()) -> None:
        """Files the figures of a page under the position of their item.

        The count has to tally, since `group_into` cuts into as many groups as
        asked: fewer drawings than illustrated items lay nothing. On a scan the
        `blocks` come cut at the printed 「◯ばん」 labels and go, in reading order,
        to the illustrated items if their counts match, else to every item if
        those match (the ink wins over the `figure` flag), else nowhere.
        """
        section = _section_of_page(page, starts)
        if section is None:
            return
        illustrated = [item for item in items if item["figure"]]

        if blocks:
            laid = (illustrated if len(blocks) == len(illustrated)
                    else items if len(blocks) == len(items) else [])
            groups = [list(block) for block in blocks]
        else:
            if not illustrated or len(objects.images) < len(illustrated):
                return
            laid = illustrated
            groups = pdf_figures.group_into(list(objects.images), len(illustrated))

        for item, group in zip(laid, groups):
            # The example takes its drawing out of the pairing, and files nothing.
            if not group or item.get("example"):
                continue
            area = pdf_figures.area_of(group, objects.strokes)
            position = Position(section, item["number"])
            if position in self._figures:
                self._claimed.add(section)
            self._figures[position] = (page, area)

    def figure(self, client: AIClient, position: Position) -> bytes | None:
        """The PNG of this exercise, or None if it has no figure."""
        found = self._load(client).get(position)
        if found is None or self._data is None:
            return None
        page, area = found
        return pdf_figures.render_area(self._data, page, area)

    def __len__(self) -> int:
        return len(self._figures or {})


def _extract_pages(pdf_bytes: bytes, pages: list[int]) -> bytes:
    """Subdocument of the useful pages only (pages counted from 1)."""
    from kotogen.generators import pdf_pages

    return pdf_pages.subset(pdf_bytes, [n - 1 for n in pages])
