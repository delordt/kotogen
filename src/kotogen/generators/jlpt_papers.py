"""The official JLPT past papers, as jlpt.jp publishes them.

Three free sample collections (問題例集 2009, 公式問題集 2012 and 2018), each with
the PDF booklets and the 聴解 audio of the five levels, for personal use. This
module is a table of addresses and a cache: `reading` reads a booklet, and
`audio` cuts a section (`N3Q1.mp3` is a whole 問題) into one card per item, whose
rank is read from the audio (「3番」) rather than guessed from the file name. The
level is part of the alias (`jlpt-n3`): `--level` is the level of the cards.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from kotogen import memory, seen, system
from kotogen.generators import download
from kotogen.i18n import _, listed, quoted
from kotogen.jlpt import LEVELS
from kotogen.known import NO_SOURCES

ROOT = "https://www.jlpt.jp/samples/"


@dataclass(frozen=True)
class Collection:
    """A published collection: its booklets, its listening sections, where it all is.

    `sections` is per level, the beginner levels having no 統合理解 file.
    `elsewhere` maps a (level, section) to an address outside the root.
    """

    key: str
    name: str
    folder: str                         # subfolder of ROOT, "" for the root
    reading: str                        # template of the reading booklet
    listening: str                      # template of a listening section
    sections: dict[str, tuple[int, ...]]
    elsewhere: dict[tuple[str, int], str] = field(default_factory=dict)
    # Template of the 聴解 booklet, where the exercises are drawn; "" when none is
    # usable (see jlpt2009 below).
    listening_booklet: str = ""
    # Whether one track is one section. Not in 2009, whose single file carries the
    # whole exam: its track number names no section, so neither the kind of
    # exercise nor the booklet page may be deduced from it.
    per_section: bool = True

    def base(self) -> str:
        return ROOT + (f"{self.folder}/" if self.folder else "")

    def booklet(self, level: str) -> str:
        """The address of the booklet the reading texts are drawn from."""
        return self.base() + self.reading.format(level=level)

    def figures_booklet(self, level: str) -> str:
        """The address of the 聴解 booklet, or "" if this collection has none usable."""
        if not self.listening_booklet:
            return ""
        return self.base() + self.listening_booklet.format(level=level)

    def tracks(self, level: str) -> tuple[tuple[int, str], ...]:
        """The listening sections of this level: ((number, address)...)."""
        return tuple(
            (number, self.elsewhere.get((level, number))
             or self.base() + self.listening.format(level=level, number=number))
            for number in self.sections.get(level, ()))


# The three collections, newest first. Every address was copied from the site.
COLLECTIONS: dict[str, Collection] = {
    "jlpt": Collection(
        "jlpt", "JLPT 公式問題集 第二集 (2018)", "sample2018",
        "pdf/{level}R.pdf", "mp3/{level}Q{number}.mp3",
        {"N5": (1, 2, 3, 4), "N4": (1, 2, 3, 4),
         "N3": (1, 2, 3, 4, 5), "N2": (1, 2, 3, 4, 5), "N1": (1, 2, 3, 4, 5)},
        listening_booklet="pdf/{level}L.pdf"),
    # Section 2 was republished in 2017 under its own root (`elsewhere`). The
    # listening booklets are scans: `pdf_figures.scanned_items` finds their
    # figures in the ink, and each goes to the model whole, which costs more.
    "jlpt2012": Collection(
        "jlpt2012", "JLPT 公式問題集 (2012)", "sample2012",
        "pdf/{level}R.pdf", "mp3/{level}Q{number}.mp3",
        {"N5": (1, 2, 3, 4), "N4": (1, 2, 3, 4),
         "N3": (1, 2, 3, 4, 5), "N2": (1, 2, 3, 4, 5), "N1": (1, 2, 3, 4, 5)},
        {(level, 2): f"{ROOT}sample2017/mp3/{level}Q2.mp3"
         for level in LEVELS},
        listening_booklet="pdf/{level}L.pdf"),
    # The oldest, in one piece: one booklet, and one audio for the whole exam. No
    # listening booklet, though a scan is readable: figures are filed under
    # `Position(section, item)`, the section comes from the track number (1 here)
    # and the 「◯ばん」 restart in each section, so items would get wrong figures.
    "jlpt2009": Collection(
        "jlpt2009", "JLPT 問題例集 (2009)", "",
        "pdf/{level}-mondai.pdf", "mp3/{level}Sample.mp3",
        {level: (1,) for level in LEVELS}, per_section=False),
}

DEFAULT = "jlpt"


def names_a_paper(source: str) -> bool:
    """Whether a card's `Source` names one of these collections.

    The extraction writes `JLPT 公式問題集 (2012) - N4 - 問題2 (02:29 → 03:29)`
    (see `Target.name`).
    """
    return any(source.startswith(f"{collection.name} - ")
               for collection in COLLECTIONS.values())


@dataclass(frozen=True)
class Target:
    """What an alias names: a collection, at a level."""

    collection: Collection
    level: str

    @property
    def key(self) -> str:
        """History and cache key: a level is followed independently of the others."""
        return f"{self.collection.key}-{self.level.lower()}"

    @property
    def name(self) -> str:
        return f"{self.collection.name} - {self.level}"


@dataclass(frozen=True)
class Track:
    """A listening section: the file, and which 問題 it is."""

    number: int
    url: str

    @property
    def name(self) -> str:
        return f"問題{self.number}"


# -- Recognising the input ----------------------------------------------------

def _split(entry: str) -> tuple[str, str]:
    """"jlpt2012-n3" -> ("jlpt2012", "N3"). Returns ("", "") if it is not one.

    `jlpt` alone gives ("jlpt", ""): it names this source, so that `resolve` asks
    for the level rather than the word being taken for a missing local file.
    """
    word = (entry or "").strip().lower()
    if not word:
        return "", ""
    stem, _, suffix = word.rpartition("-")
    if stem in COLLECTIONS and suffix.upper() in LEVELS:
        return stem, suffix.upper()
    return (word, "") if word in COLLECTIONS else ("", "")


def is_jlpt_input(entry: str) -> bool:
    """True if the input names the official past papers: "jlpt", "jlpt2012-n3"..."""
    return bool(_split(entry)[0])


def resolve(entry: str) -> Target:
    """An alias to a resolved target. An incomplete alias says what exists.

    No default level: a wrong guess would download fifty megabytes for nothing.
    """
    key, level = _split(entry)
    if not key:
        raise ValueError(_("unknown past-paper collection: {entry}.")
                         .format(entry=quoted(entry)))
    if level:
        return Target(COLLECTIONS[key], level)
    examples = listed(f"{key}-{n.lower()}" for n in LEVELS)
    others = listed(other for other in COLLECTIONS if other != key)
    raise ValueError(
        _("{name}: at which level? The level is part of the alias.\n"
          "   Take your pick: {examples}\n"
          "   Other collections: {others}").format(
              name=COLLECTIONS[key].name, examples=examples, others=others))


# -- What is drawn from it ----------------------------------------------------

def cache_folder(target: Target) -> Path:
    """Where the booklets and the sections of a level live between two passes."""
    folder = system.cache_dir() / "papers" / target.key
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# The booklet's identifier in the history and its name on the card. One reading
# booklet per level, so it is constant; the mode tells it from the sections
# filed under the same key.
BOOKLET = "読解"


def booklet_provenance(target: Target) -> str:
    """Where the cards of the booklet come from, as the Source field will keep it."""
    return f"{target.name} ({BOOKLET})"


def booklet(target: Target) -> tuple[Path, str]:
    """The reading booklet, brought back: (local file, name to announce it by).

    The file name keeps the level (`N3R.pdf`): `exam_items.level_from_name` reads
    it, and the card keeps it if nothing more readable replaces it.
    """
    url = target.collection.booklet(target.level)
    dest = cache_folder(target) / download.name_from(url, f"{target.level}.pdf")
    return download.file(url, dest), booklet_provenance(target)


def figures_booklet(target: Target) -> Path | None:
    """The 聴解 booklet of this level, brought back, or None if there is none.

    A file apart from `booklet`, which holds no listening page. None is silent,
    the cards being made without images; a failed download raises, for the caller
    to catch.
    """
    url = target.collection.figures_booklet(target.level)
    if not url:
        return None
    dest = cache_folder(target) / download.name_from(url, f"{target.level}L.pdf")
    return download.file(url, dest)


def tracks(target: Target, *, skip_seen: bool = True,
           mode: str = "audio") -> tuple[list[Track], int]:
    """(listening sections left to do, how many have already been through).

    Sections done are skipped, as podcast episodes are: downloading them again
    would only give duplicates Anki refuses.
    """
    done = seen.load(mode, target.key) if skip_seen else {}
    # The deck too, which knows what other machines did, matched by provenance:
    # it names the collection, the level and the section.
    deck = memory.known().sources() if skip_seen else NO_SOURCES
    every = [Track(number, url) for number, url in target.collection.tracks(target.level)]
    left = [track for track in every
            if track.name not in done
            and not deck.knows(mode, provenance(target, track))]
    return left, len(every) - len(left)


def mark_read(target: Target) -> None:
    """Memorises that the reading booklet of a level gave cards."""
    seen.mark("reading", target.key, BOOKLET, booklet_provenance(target))


def is_read(target: Target) -> bool:
    """True if the reading booklet of this level has already been through.

    The local history first, free and offline, then the deck, which knows what
    other machines did.
    """
    return (BOOKLET in seen.load("reading", target.key)
            or memory.known().sources().knows("reading", booklet_provenance(target)))


def fetch(target: Target, track: Track) -> Path:
    """The section on disk, taken from the cache if it is already there."""
    dest = cache_folder(target) / f"{target.level}_{track.name}.mp3"
    return download.file(track.url, dest)


# -- What the rest of the listening chain asks of a distant source ------------
# The same five names as `podcast` and `youtube`: `audio.run_audio` calls them
# without knowing which source it holds.

def provenance(target: Target, track: Track) -> str:
    """Where these cards come from, as the Source field will keep it."""
    return f"{target.name} - {track.name}"


def link(target: Target, track: Track, start: float = 0.0) -> str:
    """The address of the file, which is also that of the page publishing it.

    Returned empty, as for a podcast: a click would download the mp3 again.
    """
    return ""


def mark_done(target: Target, track: Track, mode: str = "audio") -> None:
    """Memorises a section handled, with cards or without."""
    seen.mark(mode, target.key, track.name, provenance(target, track))


# -- Reading a provenance back ------------------------------------------------
# The counterpart of `provenance` and `booklet_provenance`, with which
# `seen.recover` fills in a fresh machine's history from the deck.

# The collection name holds a parenthesis ("... (2018)"), so the capture stops
# at the first "- Nx", the level. Anchored at the head: `provenance` only appends.
_SECTION_RE = re.compile(r"^(.+?) - (N[1-5]) - (問題\d+)")
_BOOKLET_RE = re.compile(rf"^(.+?) - (N[1-5]) \({BOOKLET}\)")


def recognise(trace: str) -> tuple[str, str] | None:
    """A card provenance -> (history key, identifier), or None.

    None unless it begins with the name of a known collection: nothing is guessed.
    """
    trace = (trace or "").strip()
    for pattern, fixed in ((_SECTION_RE, ""), (_BOOKLET_RE, BOOKLET)):
        found = pattern.match(trace)
        if not found:
            continue
        for collection in COLLECTIONS.values():
            if collection.name == found.group(1):
                return (Target(collection, found.group(2)).key,
                        fixed or found.group(3))
    return None


def cleanup(target: Target, keep: int = 0) -> None:
    """Does nothing, and that is deliberate.

    A collection is closed (five sections, fifty megabytes), unlike a podcast,
    whose cache keeps three episodes. Kept, the sections make a rerun with other
    cutting settings free; the cache folder is wiped whole when room is wanted.
    """
