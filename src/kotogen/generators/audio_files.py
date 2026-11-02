"""The audio files of a listening run: collected, remembered, named in the media library.

A folder may hold a series, a video gives up its sound track, and a past paper's
file names its exercise, hence its figure, its kind of item and its level.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

from kotogen import console, seen
from kotogen.ai_client import AIClient
from kotogen.generators import exam_items
from kotogen.i18n import _

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".opus", ".aac"}

# A video's sound track is extracted on the way in and follows the chain in its
# place: a file handled whole is copied into Anki's media library, and the
# content fingerprint that names the media is better without the picture.
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".ts"}

MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


# ── Naming the files dropped into the media library ───────────────────────────

# Anki's collection.media holds the media of every deck with no namespace: a
# second `01.mp3` silently replaces the first. Names carry a fingerprint of the
# content rather than a random one, so a regenerated extract keeps its name.
FINGERPRINT_LEN = 8

# The readable part of a name is only a landmark, so it is truncated: Windows
# paths cap at 260 characters, and Anki's profile folder is already deep.
READABLE_MAX = 40

_TRAILING_FINGERPRINT_RE = re.compile(rf"_[0-9a-f]{{{FINGERPRINT_LEN}}}$")


def fingerprint(path: Path) -> str:
    """Short fingerprint of a file's content (read in blocks: audio is big)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:FINGERPRINT_LEN]


def _readable(stem: str) -> str:
    """Readable part of a media name, stripped of what would break the card.

    Every media name goes through here, which lets the tags escape nothing
    (`exporter.audio_ref`): a quotation mark would close their `src` attribute
    and mute the card. Japanese stays, as `isalnum` accepts it (`第3回`).
    """
    clean = "".join(c if (c.isalnum() or c in "-_") else "_" for c in stem)
    clean = re.sub(r"_+", "_", clean).strip("_")
    # Drops a fingerprint already there, or a pass replayed over its own output
    # would pile up `01_68bca10e_68bca10e`. A user name that merely ends that way
    # loses those characters, not its uniqueness: the fingerprint follows.
    clean = _TRAILING_FINGERPRINT_RE.sub("", clean)
    # A cut on a separator would leave one the next pass strips.
    return clean[:READABLE_MAX].rstrip("_") or "audio"


# ── Collecting the audio files ────────────────────────────────────────────────

def _collect_audio_files(inputs: list[Path]) -> list[Path]:
    """Expands files + folders into a flat list of audio files.

    A folder is walked down its sub-folders (a shelf of series is a folder of
    folders), in path order, so a series arrives whole and its seasons in order.
    """
    files: list[Path] = []
    for p in inputs:
        if p.is_dir():
            found = sorted(f for f in p.rglob("*")
                           if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS)
            if not found:
                console.failed(_("no audio file in {path}").format(path=p))
            files.extend(found)
        elif p.is_file():
            files.append(p)
        else:
            sys.exit(_("File not found: {path}").format(path=p))
    return files


# The history source of every local file: a file is known by its name and size
# (`_file_id`), not by the folder it was walked from, and a source per folder
# would hand a whole shelf back once that folder is renamed.
FILES_SOURCE = "files"


def _folder_of(audio: Path, roots: list[Path]) -> Path | None:
    """The folder given on the command line this file was walked from, if any.

    None for a file named on its own, which the history leaves out.
    """
    for root in roots:
        if root.is_dir() and audio.is_relative_to(root):
            return root
    return None


def _file_id(audio: Path) -> str:
    """What the history files a local file under: where it sits, and what it weighs.

    Not a content fingerprint, which would read hundreds of gigabytes, nor the
    full path, which a moved folder or a remounted disk changes. A renamed file
    comes back as new.
    """
    try:
        size = audio.stat().st_size
    except OSError:
        size = 0  # unreadable: known by its name alone
    return f"{audio.parent.name}/{audio.name}:{size}"


def _label(audio: Path, roots: list[Path]) -> str:
    """How this file is named: on screen, and in the Source field of its cards.

    A file in a sub-folder of the folder named carries that sub-folder
    (`Series/S01 - ep03.mkv`); any other keeps its own name.
    """
    root = _folder_of(audio, roots)
    if root is None or audio.parent == root:
        return audio.name
    return f"{audio.parent.relative_to(root).as_posix()} - {audio.name}"


def _files_to_do(files: list[Path], roots: list[Path],
                 count: int | None) -> tuple[list[Path], int]:
    """The local files left to handle, and how many the history took out.

    Only a folder's files are skipped once handled, so a weekly run takes up
    where it left off; a file named on its own is made again on demand. `count`
    is `--latest`: without it, a folder goes whole.
    """
    done = seen.load("audio", FILES_SOURCE)
    kept: list[Path] = []
    skipped = 0
    for audio in files:
        if _folder_of(audio, roots) is not None and _file_id(audio) in done:
            skipped += 1
        else:
            kept.append(audio)
    return (kept[:count] if count else kept), skipped


def _mark_handled(audio: Path, remote: dict[Path, tuple],
                  roots: list[Path]) -> None:
    """Records a file the run went through to the end, with cards or without.

    A downloaded one under its source (`remote`), one walked from a folder under
    `FILES_SOURCE`; one named on its own stays out, to be made again on demand.
    """
    if audio in remote:
        module, source, item = remote[audio]
        module.mark_done(source, item)
    elif _folder_of(audio, roots) is not None:
        seen.mark("audio", FILES_SOURCE, _file_id(audio), audio.name)


# ── A series of episodes ──────────────────────────────────────────────────────

# Release marks between brackets, some changing from one episode to the next:
# `[Group] Series - 03 (1080p) [A1B2C3D4].mkv`.
_RELEASE_TAG_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)|【[^】]*】")

# How a file names its episode: `S01E03`, `第3話`, `ep03`, `#3`, `Series - 03`,
# `03 - title`. What precedes the number names the series, season included, or
# two seasons would share their numbers. `3D` and `2024-07-14` are not episodes.
_EPISODE_RES = (
    re.compile(r"(?P<series>.*?)\bs(?P<season>\d{1,2})\s*e(?P<n>\d{1,4})", re.I),
    re.compile(r"(?P<series>.*?)第\s*(?P<n>\d{1,4})\s*[話回]"),
    re.compile(r"(?P<series>.*?)\b(?:ep|episode)\.?\s*(?P<n>\d{1,4})(?!\d)", re.I),
    re.compile(r"(?P<series>.*?)[#＃]\s*(?P<n>\d{1,4})(?!\d)"),
    re.compile(r"(?P<series>.*?)\s-\s(?P<n>\d{1,3})(?=$|[\s._v-])"),
    re.compile(r"^(?P<series>)(?P<n>\d{1,3})(?=$|[\s._v-])"),
)


def _episode(video: Path) -> tuple[str, int] | None:
    """(the series, the number) a video file names itself by, or None."""
    name = _RELEASE_TAG_RE.sub(" ", video.stem)
    for pattern in _EPISODE_RES:
        found = pattern.search(name)
        if found:
            series = re.sub(r"[\W_]+", " ", found.group("series")).strip().casefold()
            season = found.groupdict().get("season") or ""
            return f"{video.parent}|{series}|{season}", int(found.group("n"))
    return None


def is_series(folder: Path) -> bool:
    """Does this folder hold the episodes of a series, rather than videos put together?

    Two videos at least, in one folder, numbered as episodes of the same series.
    Videos only: a folder of numbered MP3 files is a textbook CD, taken whole.
    """
    numbers: dict[str, set[int]] = {}
    for video in folder.rglob("*"):
        if video.suffix.lower() not in VIDEO_EXTENSIONS or not video.is_file():
            continue
        episode = _episode(video)
        if episode is not None:
            numbers.setdefault(episode[0], set()).add(episode[1])
    return any(len(found) >= 2 for found in numbers.values())


def episodes_left(path: Path) -> int | None:
    """How many files this folder still has to give, or None if it holds no series.

    Counted as the run counts them, the history taken out.
    """
    if not path.is_dir() or not is_series(path):
        return None
    left, _done = _files_to_do(_collect_audio_files([path]), [path], None)
    return len(left)


# ── The figure of a past-paper exercise ───────────────────────────────────────

def _exam_figure(client: AIClient, audio: Path, booklets: dict,
                 out_dir: Path) -> Path | None:
    """The PNG of the exercise this FILE is taken from, dropped beside the TSV.

    For a file that is one item, whose name gives its position
    (`N5_sample2018-2_3`) with a booklet of its level beside it; None otherwise,
    at no cost. A downloaded section goes through `_passage_figure`.
    """
    position = exam_items.position_from_name(audio.name)
    if position is None:
        return None
    path = exam_items.companion(audio)
    if path is None:
        return None
    return _figure(client, path, position, booklets, out_dir, audio.stem)


def _passage_figure(client: AIClient, source: tuple | None, block,
                    booklets: dict, out_dir: Path) -> Path | None:
    """The PNG of the exercise this PASSAGE is the conversation of, or None.

    For a downloaded section: the track gives the section (`N5Q1.mp3` is the
    whole 問題1), and the 「3番」 the split heard gives the item, which a count
    of passages would get wrong past the example or a dropped one.
    """
    from kotogen.generators import jlpt_papers

    if not source or source[0] is not jlpt_papers or block.item is None:
        return None
    _module, target, track = source
    try:
        path = jlpt_papers.figures_booklet(target)
    except Exception as exc:
        console.failed(_("listening booklet not found: {reason}").format(
            reason=console.reason(exc)))
        return None
    if path is None:
        return None
    position = exam_items.Position(track.number, block.item)
    return _figure(client, path, position, booklets, out_dir,
                   f"{target.level}_{track.name}_{block.item}")


def _is_choice(audio: Path, source: tuple | None, lines: list[str]) -> bool:
    """Is this passage a prompt followed by three answers to choose from?

    The 発話表現 and 即時応答 items: the generator would take their replies
    for one speaker going on. The section tells for sure; without it (the 2009
    collection in one file, a textbook), the transcript must clearly show it.
    """
    from kotogen.generators import jlpt_papers

    level, section = "", 0
    if source and source[0] is jlpt_papers:
        _module, target, track = source
        if target.collection.per_section:
            level, section = target.level, track.number
    else:
        # A file that is one item names its section (`N5_sample2018-4_3.mp3`).
        position = exam_items.position_from_name(audio.name)
        if position is not None:
            level, section = exam_items.level_from_name(audio.name), position.section
    if level and section:
        return exam_items.is_choice(exam_items.section_type(level, section))
    return exam_items.looks_like_choice(lines)


def _set_level(audio: Path, source) -> str:
    """The JLPT level a past paper is set at, or "" when the file is not one.

    A fact about the card, so it prevails over `--level` and over the estimate,
    which rates a section's opening example, its easiest item, too low. Read
    as in `_is_choice`: the collection named, or a file named as an item.
    """
    from kotogen.generators import jlpt_papers

    if source and source[0] is jlpt_papers:
        return source[1].level
    if exam_items.position_from_name(audio.name) is not None:
        return exam_items.level_from_name(audio.name)
    return ""


def _figure(client: AIClient, path: Path, position: exam_items.Position,
            booklets: dict, out_dir: Path, readable: str) -> Path | None:
    """The figure of that exercise, cut out of that booklet.

    `booklets` keeps the booklets already read: mapping one costs a vision call,
    paid once for all the files or passages of an exam.
    """
    booklet = booklets.get(path)
    if booklet is None:
        booklet = booklets[path] = exam_items.Booklet(path)
        console.item(_("Past-paper booklet: {name}").format(name=path.name))

    console.action(_("Looking for the figure"),
                   among=_("section {section}, item {item}").format(
                       section=position.section, item=position.item))
    try:
        png = booklet.figure(client, position)
    except Exception as exc:
        console.failed(_("figure not found: {reason}").format(reason=exc))
        return None
    if booklet.error:
        # Said once per booklet, not once per file.
        console.failed(_("booklet unusable: {reason}").format(
            reason=console.reason(booklet.error)))
        booklet.error = ""
    if png is None:
        # The context lets French agree the word: `aucune` here, `aucun` on the
        # choice marker of a reading card.
        console.done(_("none", "figure"))
        return None

    # Named by its content, like the audio files (see FINGERPRINT_LEN).
    dest = out_dir / f"{_readable(readable)}_{hashlib.sha256(png).hexdigest()[:FINGERPRINT_LEN]}.png"
    dest.write_bytes(png)
    # Not the name, a fingerprint: the action asked whether there was a figure.
    console.done(_("found", "figure"))
    return dest


# ── From a video file to its sound track ──────────────────────────────────────

def _extract_track(video: Path, work_dir: Path, level) -> tuple[Path, str]:
    """Sound track of a video, dropped into the working folder.

    The Japanese track is chosen here: left alone, ffmpeg takes the one with the
    most channels, often a 5.1 dub. Returned with the words announcing that
    choice, for the line the caller holds open. Named after the video's full
    path, as `S01/01.mkv` and `S02/01.mkv` share a stem; `_readable` drops that
    fingerprint again from the names of the media cut from it.
    """
    from kotogen.generators import nhk as nhk_gen  # late import (avoids a cycle)

    tracks = nhk_gen.probe_audio_tracks(video)
    chosen = nhk_gen.japanese_track(tracks)
    if chosen is None and len(tracks) > 1:
        # The user may know which track is Japanese; silence would leave the
        # card's language to be found out at review time.
        console.aside(_("{count} sound tracks, none declared Japanese: the main "
                        "track is taken").format(count=len(tracks)))
    where = hashlib.sha256(str(video.resolve()).encode("utf-8")).hexdigest()
    track = nhk_gen.extract_audio_track(
        video, work_dir, f"{_readable(video.stem)}_{where[:FINGERPRINT_LEN]}",
        level, chosen)
    return track, (_("Japanese track out of {count}").format(count=len(tracks))
                   if chosen is not None else "")
