"""青空文庫: the Japanese public domain, as a catalogue and not as a lone URL.

The catalogue comes from the site's machine-readable index; a work page is read
by the generic route with its `<ruby>` (see `text_source`). Four filters at the
door: 新字新仮名 only (the other orthographies predate the 1946 reform: けふ for
きょう), the 「著者」 role (or a translation would show twice, under its
translator too), a published XHTML page (the text file writes 漢字《かんじ》),
and a work out of copyright (`作品著作権フラグ` is `なし`).

The children's shelf (`NDC K...`) stands apart: short works in modern
orthography and simple syntax, where the rest is N1 adult literature of
1900-1940. The level is estimated per shelf: the index says nothing per work.
"""

from __future__ import annotations

import csv
import io
import json
import re
import time
import urllib.parse
import zipfile
from dataclasses import astuple, dataclass
from pathlib import Path

from kotogen import seen, system
from kotogen.generators import download
from kotogen.i18n import _

INDEX_URL = ("https://www.aozora.gr.jp/index_pages/"
             "list_person_all_extended_utf8.zip")

# The index gains a few dozen works a month, and a month-old list beats an empty
# menu (the same contract as the Tadoku catalogue).
INDEX_MAX_AGE = 30 * 24 * 3600

SOURCE = "aozora"

# The list unpacks to 17 MB from 2 (2026); past this the archive is not the
# index, which a zip of a few megabytes could otherwise unpack to gigabytes.
MAX_INDEX = 100 * 1024 * 1024

# The NDC classmark of children's books: "NDC K913", "NDC K943"...
_CHILDREN_RE = re.compile(r"NDC\s*K", re.IGNORECASE)

_CARD_RE = re.compile(r"aozora\.gr\.jp/cards/\d+/card(\d+)\.html", re.IGNORECASE)
_FILE_RE = re.compile(r'href="([^"]*files/[^"]+\.html)"', re.IGNORECASE)


@dataclass(frozen=True)
class Work:
    """A work of the collection: enough to announce it, read it and find it again."""

    work_id: str       # the work number ("59898"), the history key
    title: str
    author: str
    ndc: str           # the NDC classification as the index writes it
    url: str           # the XHTML page, the one carrying the <ruby>

    @property
    def for_children(self) -> bool:
        return bool(_CHILDREN_RE.match(self.ndc))

    @property
    def label(self) -> str:
        return f"{self.title} - {self.author}"


# The two shelves and their level estimate (see the header). The labels are
# English, translated where displayed: `_()` at module level would resolve the
# language before the settings are loaded.
SHELVES = (
    ("children", "Children", "N3-N2", "tales and stories for children"),
    ("literature", "Literature", "N1", "novels, short stories and essays"),
)


# -- The index ----------------------------------------------------------------

def index_file() -> Path:
    return system.cache_dir() / "aozora-index.json"


def _read_csv(data: bytes) -> list[Work]:
    """The index archive -> the works kept (see the header for the filters)."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        # zipfile unpacks no further than the size the entry declares.
        if not names or archive.getinfo(names[0]).file_size > MAX_INDEX:
            raise RuntimeError(_("the site's list of works could not be read."))
        with archive.open(names[0]) as raw:
            lines = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            entries = list(csv.DictReader(lines))

    works: list[Work] = []
    for entry in entries:
        url = (entry.get("XHTML/HTMLファイルURL") or "").strip()
        if (not url
                or entry.get("文字遣い種別") != "新字新仮名"
                or entry.get("役割フラグ") != "著者"
                or entry.get("作品著作権フラグ") != "なし"):
            continue
        name = " ".join(part for part in ((entry.get("姓") or "").strip(),
                                          (entry.get("名") or "").strip()) if part)
        works.append(Work(
            (entry.get("作品ID") or "").strip(),
            (entry.get("作品名") or "").strip(),
            name,
            (entry.get("分類番号") or "").strip(),
            url,
        ))
    return works


def _read_cache() -> tuple[list[Work], float] | None:
    try:
        data = json.loads(index_file().read_text(encoding="utf-8"))
        return [Work(*entry) for entry in data["works"]], float(data["date"])
    except (OSError, ValueError, KeyError, TypeError):
        # Absent, truncated by a crash or of another layout (an older version's
        # entries carried one more field): treated as absent.
        return None


def _write_cache(works: list[Work], date: float) -> None:
    try:
        system.write_whole(index_file(), json.dumps(
            {"date": date, "works": [astuple(w) for w in works]}, ensure_ascii=False))
    except OSError:
        pass  # full disk, read-only folder: we do without


def catalogue(*, refresh: bool = False) -> list[Work]:
    """The collection kept, from the cache if it is fresh, from the site otherwise.

    Never raises: an unreachable site gives the last list known, or an empty one,
    and the menu falls back on pasting the address of a work.
    """
    kept = _read_cache()
    if not refresh and kept and time.time() - kept[1] < INDEX_MAX_AGE:
        return kept[0]
    try:
        found = _read_csv(download.page(INDEX_URL, timeout=120))
    except Exception:
        return kept[0] if kept else []
    if not found:
        # An index served but unreadable (columns renamed): the cache is kept.
        return kept[0] if kept else []
    _write_cache(found, time.time())
    return found


# -- Filing and searching -----------------------------------------------------

def shelf(works: list[Work], key: str) -> list[Work]:
    """The works of a shelf: "children", or everything else."""
    wanted = key == "children"
    return [work for work in works if work.for_children is wanted]


def level_of(work: Work) -> str:
    """The estimate of the shelf a work stands on - never one of the work itself."""
    key = "children" if work.for_children else "literature"
    return next(level for shelf_key, _name, level, _what in SHELVES
                if shelf_key == key)


def by_shelf(works: list[Work]) -> list[Work]:
    """The whole library, the easier shelf first, each one by title."""
    return sorted(works, key=lambda work: (not work.for_children, work.title))


def by_author(works: list[Work]) -> list[tuple[str, list[Work]]]:
    """The works grouped by author, the best stocked first.

    By count rather than alphabetically: 多読 means staying with one author.
    """
    groups: dict[str, list[Work]] = {}
    for work in works:
        groups.setdefault(work.author, []).append(work)
    for one in groups.values():
        one.sort(key=lambda work: work.title)
    return sorted(groups.items(), key=lambda pair: (-len(pair[1]), pair[0]))


def search(works: list[Work], pattern: str) -> list[Work]:
    """The works whose title or author carries this piece of text.

    A plain substring search, not on the kana readings of the index nor romaji:
    what one types ("賢治", "ごん") is what the screen shows.
    """
    pattern = (pattern or "").strip()
    if not pattern:
        return []
    return [work for work in works
            if pattern in work.title or pattern in work.author]


# -- Recognising the input ----------------------------------------------------

def is_aozora_input(entry: str) -> bool:
    """True if the input is an address of the collection: a card, or a work page."""
    entry = (entry or "").strip().lower()
    return entry.startswith(("http://", "https://")) and "aozora.gr.jp" in entry


def _card_id(url: str) -> str:
    """The work number a card carries, or "" if it is not one."""
    found = _CARD_RE.search(url or "")
    return found.group(1) if found else ""


def _number(work_id: str) -> str:
    """The work number in the form it is compared in.

    The index pads it to six digits (`000628`), the addresses do not
    (`card628.html`, `628_14895.html`).
    """
    return (work_id or "").strip().lstrip("0") or "0"


def resolve(entry: str) -> tuple[str, Work | None]:
    """An address given -> (address of the page to read, catalogue work if known).

    A book card, the page the site links to, is turned into its text page: by the
    index, offline, or by the card itself for a work newer than the cache.
    """
    url = (entry or "").strip()
    work_id = _number(_card_id(url))
    known = {_number(work.work_id): work for work in catalogue()}
    if _card_id(url):
        if work_id in known:
            return known[work_id].url, known[work_id]
        html = download.page(url).decode("cp932", "replace")
        # On the web only: the page is read next by a route that would open a
        # `file://` as readily.
        links = [link for link in (urllib.parse.urljoin(url, found)
                                   for found in _FILE_RE.findall(html))
                 if download.is_web(link)]
        if not links:
            raise RuntimeError(
                _("no text page on this card: {url}. The work may only be "
                  "published as a text file.").format(url=url))
        return links[0], None

    # A work page already: the number opening its file name ("59898_70731.html")
    # finds the work, for the history.
    name = Path(urllib.parse.urlsplit(url).path).name
    return url, known.get(_number(name.split("_", 1)[0]))


# -- Works already read -------------------------------------------------------
# As for the Tadoku books: among ten thousand titles, the catalogue says which
# were read. Nothing is skipped: the box stays tickable, a work can be reread.

def load_seen(mode: str = "reading") -> dict[str, str]:
    """The works already handled by this mode: {work number: title}."""
    return seen.load(mode, SOURCE)


def mark_seen(work: Work | None, mode: str = "reading") -> None:
    """Memorises a work that gave cards.

    Not an address outside the catalogue: it has no work number to compare
    (`seen.mark` tells by the empty identifier).
    """
    if work:
        seen.mark(mode, SOURCE, work.work_id, work.title)


def recognise(trace: str) -> tuple[str, str] | None:
    """A card provenance -> (source key, work number), or None.

    The provenance opens on the address read (`GenericText.provenance`). The
    number drawn from it goes through the catalogue to come back padded, as
    `mark_seen` writes it, or the same work would enter the history twice.
    """
    words = (trace or "").split()
    url = words[0] if words else ""
    if not is_aozora_input(url):
        return None
    # A card or a text page, each holding the number elsewhere (see `resolve`).
    number = _card_id(url) or Path(urllib.parse.urlsplit(url).path).name.split("_", 1)[0]
    if not number.isdigit():
        return None   # the index, an author page: from the site, but not a work
    for work in catalogue():
        if _number(work.work_id) == _number(number):
            return SOURCE, work.work_id
    return None
