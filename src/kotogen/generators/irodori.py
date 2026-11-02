"""いろどり 生活の日本語: the free textbook of the Japan Foundation.

Four volumes of eighteen lessons, in PDF and MP3 with no account: graded
everyday dialogues with an exact transcription. A lesson is the unit of work, as
an episode is for a podcast, and only its dialogues are kept (聞く `kiku`, 会話
`kaiwa`): the other tracks are drills, such as word lists and conjugation
tables. The tracks are read off the lesson page, their numbering varying
between lessons, and so are its topic and its title, kept in the cache: nothing
of the textbook is shipped, not even its titles.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from kotogen import memory, seen, system
from kotogen.generators import download, levels as jlpt_levels
from kotogen.i18n import _, convention

SITE = "https://www.irodori.jpf.go.jp"

# The tracks that carry a dialogue, and those alone (see the header).
DIALOGUES = ("kiku", "kaiwa")

_TRACK_RE = re.compile(r'src="(/assets/data/[^"]+\.mp3)"')
# "Y_[09-17]_hanasu3-1.mp3": the rank inside the lesson, then what the track is.
# Matched whole: the name becomes a path in the cache, where `..` or a `\` would
# lead out of it.
_NAME_RE = re.compile(r"[A-Z]+_\[\d+-(\d+)\]_([a-z]+)[\w-]*\.mp3", re.ASCII)
# The <h1> of a lesson page: its topic, then "第N課" and its title. A copy of the
# second label follows in a comment, hence the first match.
_TOPIC_RE = re.compile(r'<label class="topic_label">.*?<span>トピック</span>\s*'
                       r'<span[^>]*>(.*?)</span>', re.S)
_TITLE_RE = re.compile(r'<label class="lesson_label">\s*<span>第\d+課</span>\s*'
                       r'<span[^>]*>(.*?)</span>', re.S)


@dataclass(frozen=True)
class Volume:
    """One of the four volumes: its name, its folder on the site, its prefix."""

    name: str
    folder: str
    prefix: str
    levels: tuple[str, ...] = ()


# The JLPT levels are an estimate: the Japan Foundation files its volumes on the
# JF Standard scale (A1/A2/B1). 入門 is below N5 and has none.
VOLUMES: dict[str, Volume] = {
    "irodori-nyumon": Volume("いろどり 入門 (A1)", "starter", "X"),
    "irodori-shokyu1": Volume("いろどり 初級1 (A2)", "elementary01", "Y", ("N5",)),
    "irodori-shokyu2": Volume("いろどり 初級2 (A2)", "elementary02", "Z", ("N5", "N4")),
    "irodori-shochukyu": Volume("いろどり 初中級 (A2/B1)", "pre-intermediate", "ZZ",
                                ("N4", "N3")),
}

DEFAULT = "irodori-shokyu1"

# Every volume has eighteen lessons.
LESSON_COUNT = 18

level_label = jlpt_levels.label


@dataclass(frozen=True)
class Lesson:
    """A lesson: its volume, its rank, and the topic and title its page gives.

    An empty title is a lesson whose page could not be read: it goes by its number.
    """

    volume: Volume
    alias: str
    rank: int
    theme: str = ""
    title: str = ""
    # The lesson page, when reading the heading has brought it: `tracks` reads it
    # rather than download it again.
    markup: str = field(default="", compare=False, repr=False)

    @property
    def name(self) -> str:
        """The name the lesson announces itself under: "第3課" and its title."""
        return f"第{self.rank}課 {self.title}" if self.title else f"第{self.rank}課"

    @property
    def page(self) -> str:
        """The page listing the tracks of the lesson."""
        return f"{SITE}/{self.volume.folder}/audio/lesson{self.rank:02d}.html"

    @property
    def pdf(self) -> str:
        """The PDF of the lesson, as the textbook cuts it up."""
        return (f"{SITE}/assets/data/{self.volume.folder}/pdf/"
                f"{self.volume.prefix}_L{self.rank:02d}.pdf")


# -- Recognising the input ----------------------------------------------------

def is_irodori_input(entry: str) -> bool:
    """True if the input names いろどり: a volume alias, or "irodori"."""
    word = (entry or "").strip().lower()
    return word == "irodori" or word in VOLUMES


def resolve(entry: str) -> Volume:
    """An alias to a volume. "irodori" alone lists the four, picking none.

    No default, as with the past papers: picking a volume would pick a level.
    """
    word = (entry or "").strip().lower()
    if word in VOLUMES:
        return VOLUMES[word]
    colon = convention("colon", ": ")
    lines = [f"   {(level_label(volume.levels) or '-'):>5}{colon}{alias} - {volume.name}"
             for alias, volume in VOLUMES.items()]
    raise ValueError(_("いろどり: which volume? It is part of the alias.")
                     + "\n" + "\n".join(lines))


def alias_of(volume: Volume) -> str:
    """The alias this volume is named by."""
    return next(alias for alias, known in VOLUMES.items() if known is volume)


# -- The headings, read off the site ------------------------------------------

def heading(page: str) -> tuple[str, str] | None:
    """(topic, title) as a lesson page names them, or None if it names no title."""
    title = _TITLE_RE.search(page)
    if not title:
        return None
    topic = _TOPIC_RE.search(page)
    return (html.unescape(topic.group(1)).strip() if topic else "",
            html.unescape(title.group(1)).strip())


def _headings_file() -> Path:
    return system.cache_dir() / "irodori" / "lessons.json"


def _headings() -> dict[str, dict[str, list[str]]]:
    """The headings read so far: {folder: {rank: [topic, title]}}."""
    try:
        known = json.loads(_headings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(known, dict):
        return {}
    # A volume of another shape is dropped, its headings read off the site again.
    return {folder: ranks for folder, ranks in known.items() if isinstance(ranks, dict)}


def _named(lesson: Lesson) -> Lesson:
    """The lesson with its topic and title: from the cache, else off its page.

    Without the site and the cache, it keeps its number alone: what needs the
    site next (its tracks, its PDF) says why.
    """
    known = _headings()
    cached = known.get(lesson.volume.folder, {}).get(str(lesson.rank))
    if isinstance(cached, list) and len(cached) == 2:
        return replace(lesson, theme=cached[0], title=cached[1])
    try:
        markup = download.page(lesson.page).decode("utf-8", "replace")
    except (RuntimeError, OSError):
        return lesson
    found = heading(markup)
    if not found:
        return replace(lesson, markup=markup)
    known.setdefault(lesson.volume.folder, {})[str(lesson.rank)] = list(found)
    try:
        system.write_whole(_headings_file(),
                           json.dumps(known, ensure_ascii=False, indent=1))
    except OSError:
        pass  # a cache that cannot be written: the heading is read again next time
    return replace(lesson, theme=found[0], title=found[1], markup=markup)


# -- The lessons left to do ---------------------------------------------------

def _key(volume: Volume) -> str:
    """History and cache key: a volume is followed independently of the others."""
    return alias_of(volume)


def lessons(volume: Volume, count: int, *, from_lesson: int | None = None,
            mode: str = "audio") -> tuple[list[Lesson], int]:
    """(lessons to handle, how many have already been through).

    Without `from_lesson`, the first `count` lessons not done yet, in textbook
    order. With it, the `count` lessons from that one on, done or not.
    """
    alias = _key(volume)
    total = LESSON_COUNT
    if from_lesson is not None:
        if not 1 <= from_lesson <= total:
            raise ValueError(_("{volume}: lessons 1 to {total}, no. {asked} does "
                               "not exist.").format(volume=volume.name, total=total,
                                                    asked=from_lesson))
        ranks = range(from_lesson, min(total, from_lesson + count - 1) + 1)
        return [_named(Lesson(volume, alias, rank)) for rank in ranks], 0

    done = set(seen.load(mode, alias))
    # The deck too, which knows the lessons done on other machines: by the lesson
    # its provenance names, with or without a title.
    done |= {found[1] for trace in memory.known().sources().traces(mode)
             if (found := recognise(trace)) and found[0] == alias}
    left = [rank for rank in range(1, total + 1) if str(rank) not in done]
    return ([_named(Lesson(volume, alias, rank)) for rank in left[:count]],
            total - len(left))


def tracks(lesson: Lesson) -> list[tuple[str, str]]:
    """The dialogues of the lesson: [(file name, address)], in textbook order.

    Read off the lesson page, the track numbering following no rule. The other
    tracks are dropped before any download (see the header).
    """
    text = lesson.markup or download.page(lesson.page).decode("utf-8", "replace")
    kept: list[tuple[str, str]] = []
    for path in dict.fromkeys(_TRACK_RE.findall(text)):
        name = path.rsplit("/", 1)[-1]
        found = _NAME_RE.fullmatch(name)
        if found and found.group(2) in DIALOGUES:
            kept.append((name, SITE + path))
    if not kept:
        raise RuntimeError(
            _("no dialogue on the page of the lesson: {page}. The site may have "
              "changed the way it names its tracks.").format(page=lesson.page))
    return kept


# -- Downloading and cache ----------------------------------------------------

def cache_folder(lesson: Lesson) -> Path:
    """Where the tracks of a lesson and their transcriptions live between passes."""
    folder = system.cache_dir() / "irodori" / lesson.alias / f"L{lesson.rank:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def fetch(lesson: Lesson) -> list[Path]:
    """The dialogues of the lesson on disk, taken from the cache if already there."""
    return [download.file(url, cache_folder(lesson) / name)
            for name, url in tracks(lesson)]


def booklet(lesson: Lesson) -> tuple[Path, str]:
    """The PDF of the lesson, brought back: (local file, name to announce it by)."""
    dest = cache_folder(lesson) / download.name_from(lesson.pdf, "lesson.pdf")
    return download.file(lesson.pdf, dest), f"{lesson.volume.name} - {lesson.name}"


# -- What the listening chain asks of a distant source ------------------------
# The same five names as `podcast`, `youtube` and `jlpt_papers`. The lesson is
# both the source and the item: it is marked handled as a whole.

def provenance(lesson: Lesson, track: Path | None = None) -> str:
    """Where these cards come from, as the Source field will keep it.

    `track` is not read: the provenance is the lesson's, shared by its reading
    booklet, and `recognise` reads the lesson back from it.
    """
    return f"{lesson.volume.name} - {lesson.name}"


def link(lesson: Lesson, track: Path, start: float = 0.0) -> str:
    """The page of the lesson: it carries the dialogue, its brief and its answers."""
    return lesson.page


def mark_done(lesson: Lesson, track: Path | None = None,
              mode: str = "audio") -> None:
    """Memorises a lesson handled: the next pass in this mode moves on.

    `track` is not read, the lesson being the unit: it is there for the signature
    the listening chain shares, and reading does not pass it.
    """
    seen.mark(mode, lesson.alias, str(lesson.rank), lesson.name)


# -- Reading a provenance back ------------------------------------------------

# "いろどり 初級1 (A2) - 第3課 <title>": the volume name, its parenthesis
# included, runs up to the first "- 第N課". Anchored at the head; the title is
# missing from a lesson whose page could not be read.
_TRACE_RE = re.compile(r"^(.+?) - 第(\d+)課(?: |$)")


def recognise(trace: str) -> tuple[str, str] | None:
    """A card provenance -> (volume alias, lesson rank), or None.

    The counterpart of `provenance`. A rank the textbook lacks gives None rather
    than a history entry that nothing would read back.
    """
    found = _TRACE_RE.match((trace or "").strip())
    if not found:
        return None
    for alias, volume in VOLUMES.items():
        if volume.name == found.group(1):
            rank = int(found.group(2))
            if 1 <= rank <= LESSON_COUNT:
                return alias, str(rank)
            return None
    return None


def cleanup(lesson: Lesson, keep: int = 0) -> None:
    """Does nothing: a textbook is closed, its eighteen lessons will not move.

    As in `jlpt_papers.cleanup`: a cached lesson (a few megabytes) makes picking
    up again free, and the cache folder is wiped whole when room is wanted.
    """
