"""青空朗読: the Japanese public domain, read aloud.

The sound counterpart of `aozora`: works of the collection read by announcers
and amateurs, free and with no account. Readings run from under a minute to two
and a half hours, so they are taken from the shortest up, as the site files
them. The cards are made on the Whisper transcription, the published text not
being aligned with the sound. The level is N2-N1, except on the children's shelf.

Personal use, like the Tadoku books: the site forbids rebroadcasting, not
listening, and the cards stay in their maker's collection.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import astuple, dataclass
from pathlib import Path

from kotogen import memory, seen, system
from kotogen.generators import download, podcast
from kotogen.known import carries

SITE = "https://aozoraroudoku.jp"

# The page that files the collection by duration, not by title (see the header).
CATALOGUE_URL = f"{SITE}/kensaku/kensaku-05.html"

# The collection gains about one reading a day: asked again past a month.
CATALOGUE_MAX_AGE = 30 * 24 * 3600

SOURCE = "roudoku"
ALIAS = ("roudoku", "aozora-roudoku")

_ENTRY_RE = re.compile(
    r'<a href="\.\./voice/rdp/(rd[\w-]+)\.html"[^>]*>\s*'
    r'<span class="listTitle">(.*?)</span>\s*'
    r'<span class="listData">著者：(.*?)　読み手：(.*?)　時間：(.*?)</span>',
    re.S)
_DURATION_RE = re.compile(r"(?:(\d+)時間)?(?:(\d+)分)?(?:(\d+)秒)?")
_TAG_RE = re.compile(r"<[^>]+>")
_PAGE_RE = re.compile(r"aozoraroudoku\.jp/voice/rdp/(rd[\w-]+)\.html", re.IGNORECASE)


def _duration(text: str) -> float:
    """"2時間34分56秒" -> 9296.0. Returns 0 for what cannot be read."""
    found = _DURATION_RE.match((text or "").strip())
    if not found:
        return 0.0
    hours, minutes, seconds = (int(part or 0) for part in found.groups())
    return float(hours * 3600 + minutes * 60 + seconds)


@dataclass(frozen=True)
class Reading:
    """A reading of the collection: the work, who reads it, and how long it runs."""

    reading_id: str    # "rd020", which names the page as well as the file
    title: str
    author: str
    reader: str
    duration: float

    @property
    def page(self) -> str:
        return f"{SITE}/voice/rdp/{self.reading_id}.html"

    @property
    def mp3(self) -> str:
        return f"{SITE}/voice/mp3/{self.reading_id}.mp3"

    @property
    def label(self) -> str:
        return f"{self.title} - {self.author}"


@dataclass(frozen=True)
class Library:
    """The collection itself, which stands as the source for the listening chain."""

    key: str = SOURCE
    name: str = "青空朗読"


# -- The catalogue ------------------------------------------------------------

def catalogue_file() -> Path:
    return system.cache_dir() / "aozora-roudoku.json"


def parse(html: str) -> list[Reading]:
    """The page of the collection -> its readings, in site order (shortest first)."""
    readings: list[Reading] = []
    for reading_id, title, author, reader, duration in _ENTRY_RE.findall(html):
        readings.append(Reading(
            reading_id,
            " ".join(_TAG_RE.sub("", title).split()),
            " ".join(_TAG_RE.sub("", author).split()),
            " ".join(_TAG_RE.sub("", reader).split()),
            _duration(duration),
        ))
    return readings


def _read_cache() -> tuple[list[Reading], float] | None:
    try:
        data = json.loads(catalogue_file().read_text(encoding="utf-8"))
        return [Reading(*entry) for entry in data["readings"]], float(data["date"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_cache(readings: list[Reading], date: float) -> None:
    try:
        system.write_whole(catalogue_file(), json.dumps(
            {"date": date, "readings": [astuple(x) for x in readings]},
            ensure_ascii=False))
    except OSError:
        pass


def catalogue(*, refresh: bool = False) -> list[Reading]:
    """The collection, from the cache if it is fresh, from the site otherwise.

    Never raises."""
    kept = _read_cache()
    if not refresh and kept and time.time() - kept[1] < CATALOGUE_MAX_AGE:
        return kept[0]
    try:
        found = parse(download.page(CATALOGUE_URL, timeout=60)
                      .decode("utf-8", "replace"))
    except Exception:
        return kept[0] if kept else []
    if not found:
        return kept[0] if kept else []
    _write_cache(found, time.time())
    return found


# -- Recognising the input ----------------------------------------------------

def is_roudoku_input(entry: str) -> bool:
    """True if the input names the collection: its alias, or a reading address."""
    word = (entry or "").strip().lower()
    return word in ALIAS or bool(_PAGE_RE.search(word))


def resolve(entry: str) -> tuple[Library, Reading | None]:
    """(the collection, the reading aimed at if the input names one).

    A pasted address names one reading and one only; the alias names the
    collection, out of which `to_do` draws what is left to listen to.
    """
    found = _PAGE_RE.search((entry or "").strip())
    if not found:
        return Library(), None
    reading_id = found.group(1)
    for reading in catalogue():
        if reading.reading_id == reading_id:
            return Library(), reading
    # Newer than the cache, or the catalogue unreachable: the file follows from
    # the address, and only the title and the duration are lost.
    return Library(), Reading(reading_id, reading_id, "", "", 0.0)


def to_do(count: int, *, limit: float | None = None,
          mode: str = "audio") -> tuple[list[Reading], int, int]:
    """(the `count` shortest readings left to do, done, discarded).

    `limit`, the longest duration asked for, applies HERE rather than after the
    download, the catalogue giving the duration of every reading.
    """
    done_ids = seen.load(mode, SOURCE)
    # The deck's memory too, which holds other machines' work, counted with the
    # done ones: the menu asks what is left, not where it was recorded.
    deck = memory.known().sources()
    library = Library()
    kept: list[Reading] = []
    done = discarded = 0
    for reading in catalogue():
        if (reading.reading_id in done_ids
                or deck.knows(mode, provenance(library, reading))):
            done += 1
            continue
        if limit and reading.duration and reading.duration > limit:
            discarded += 1
            continue
        kept.append(reading)
        if len(kept) >= count:
            break
    return kept, done, discarded


# -- Downloading and cache ----------------------------------------------------

def cache_folder(library: Library) -> Path:
    """Where the mp3s and their transcriptions live between two passes."""
    folder = system.cache_dir() / "roudoku"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def fetch(library: Library, reading: Reading) -> Path:
    """The reading on disk, taken from the cache if it is already there.

    Capped as a podcast episode is: the longest readings, two and a half hours,
    weigh 93 MB (2026), past the default cap.
    """
    return download.file(
        reading.mp3, cache_folder(library) / f"{reading.reading_id}.mp3",
        limit=podcast.MAX_EPISODE)


# -- What the listening chain asks of a distant source ------------------------

def provenance(library: Library, reading: Reading) -> str:
    """Where these cards come from, as the Source field will keep it."""
    part = f" - {reading.author}" if reading.author else ""
    return f"{library.name} - {reading.title}{part}"


def link(library: Library, reading: Reading, start: float = 0.0) -> str:
    """The page of the reading: it carries the text of the work under the player."""
    return reading.page


def mark_done(library: Library, reading: Reading, mode: str = "audio") -> None:
    """Memorises a reading handled, with cards or without."""
    seen.mark(mode, SOURCE, reading.reading_id, reading.title)


# -- Reading a provenance back ------------------------------------------------

def recognise(trace: str) -> tuple[str, str] | None:
    """A card provenance -> (source key, identifier), or None.

    Through the catalogue, since the card carries "青空朗読 - title - author" and
    no identifier (`rd1234`): None when it is unreachable. The prefix is checked
    first, so that another provenance does not load the catalogue.
    """
    trace = (trace or "").strip()
    library = Library()
    if not trace.startswith(f"{library.name} - "):
        return None
    for reading in catalogue():
        if carries(trace, provenance(library, reading)):
            return SOURCE, reading.reading_id
    return None


def cleanup(library: Library, keep: int = 3) -> None:
    """Keeps only the `keep` most recently pulled readings.

    As with the podcasts, not the past papers: a reading can run two hours, none
    is replayed, and what goes would download again.
    """
    from kotogen.generators.whisper import _cache_key

    folder = system.cache_dir() / "roudoku"
    if not folder.is_dir():
        return
    mp3 = sorted((f for f in folder.iterdir()
                  if f.is_file() and f.suffix.lower() == ".mp3"),
                 key=lambda f: f.stat().st_mtime, reverse=True)
    for old in mp3[keep:]:
        (folder / _cache_key(old)).unlink(missing_ok=True)
        old.unlink(missing_ok=True)
