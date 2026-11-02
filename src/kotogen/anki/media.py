"""Anki's media library: where it is, and how a file gets into it.

Cards name files they expect in the profile's `collection.media` folder. Cards
sent to Anki take their files along (`install_media_files`); for a TSV imported
by hand, the closing block says where to drop them (`media_dir_hint`).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from kotogen import settings, system
from kotogen.anki import connect
from kotogen.anki.connect import request as anki


def _anki_base_dirs() -> list[Path]:
    """The possible Anki profile folders on this system (one folder per profile).

    On Linux a native install and a Flatpak (HOME under `~/.var/app`) may both be
    there: native first, and `media_dir` takes the collection modified last.
    """
    if system.windows():
        appdata = os.environ.get("APPDATA")
        return [Path(appdata) / "Anki2"] if appdata else []
    if system.macos():
        return [Path.home() / "Library" / "Application Support" / "Anki2"]
    # Anki puts its data under XDG_DATA_HOME when the variable is set.
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return [
        data_home / "Anki2",
        Path.home() / ".var" / "app" / "net.ankiweb.Anki" / "data" / "Anki2",
    ]


def media_dir() -> Path | None:
    """Anki's `collection.media` folder, or None if it stays untraceable.

    In order: `KOTOGEN_MEDIA_DIR`, the path AnkiConnect gives (the profile open),
    then the local profile whose collection was modified last.
    """
    if env_dir := settings.folder("KOTOGEN_MEDIA_DIR"):
        return env_dir

    # getMediaDirPath exists only in recent versions of the add-on (RuntimeError).
    if connect.status().connected:
        try:
            path = anki("getMediaDirPath", timeout=5)
        except (ConnectionError, RuntimeError):
            path = None
        if path:
            return Path(path)

    profiles = [
        profile
        for base in _anki_base_dirs() if base.is_dir()
        for profile in base.iterdir() if (profile / "collection.anki2").is_file()
    ]
    if not profiles:
        return None
    newest = max(profiles, key=lambda p: (p / "collection.anki2").stat().st_mtime)
    media = newest / "collection.media"
    return media if media.is_dir() else None


def media_dir_hint() -> str:
    """Where to drop a file by hand, said in the terms of THIS system.

    The detected path, else the platform's usual one with the profile left blank.
    """
    found = media_dir()
    if found is not None:
        return str(found)
    if system.windows():
        return "%APPDATA%\\Anki2\\<profile>\\collection.media"
    if system.macos():
        return "~/Library/Application Support/Anki2/<profile>/collection.media"
    return "~/.local/share/Anki2/<profile>/collection.media"


# -- The name Anki keeps is not always the one it is given ---------------------
#
# `storeMediaFile` returns the name it kept, which may not be the one offered:
# Anki 26.8 lowercases it, normalises it to NFC, removes forbidden characters and
# truncates it to 120 bytes, cutting the fingerprint off a Japanese name. A field
# left on the offered name asks for a missing file, so the fields follow the name
# returned (see `send.follow_renames`) rather than guess rules that have changed.


def _name_kept(kept: str) -> str:
    """The name the media folder holds for a file stored as `kept`, case included.

    When the folder already holds the same bytes AnkiConnect returns the name
    offered, and Windows does not tell `N3_…` from `n3_…`, so a phone would miss
    the file. The folder is searched case-blind; `kept` stands unless exactly one
    name comes back.
    """
    pattern = "".join(f"[{c.lower()}{c.upper()}]" if c.lower() != c.upper()
                      else f"[{c}]" if c in "[]*?" else c for c in kept)
    try:
        found = anki("getMediaFilesNames", pattern=pattern)
    except Exception:
        return kept
    if (isinstance(found, list) and len(found) == 1 and isinstance(found[0], str)
            and found[0].lower() == kept.lower()):
        return found[0]
    return kept


def store_media_files(paths: list[Path],
                      renamed: dict[str, str] | None = None) -> list[Path]:
    """Copy files into collection.media through AnkiConnect (storeMediaFile).

    Returns the files NOT copied, for the caller to have copied by hand; never
    fails, and prints nothing. `renamed`, if given, fills with `{name offered:
    name kept}` for the names Anki changed, for the caller to carry to its cards.
    """
    failed: list[Path] = []
    for i, path in enumerate(paths):
        try:
            # `deleteExisting=False`: AnkiConnect's default first deletes the file
            # of that name, which older cards may still play. Without it, Anki keeps
            # identical bytes under their name, or stores others under a free name.
            kept = anki("storeMediaFile", filename=path.name,
                        path=str(path.resolve()), deleteExisting=False)
        except ConnectionError:
            # Anki unreachable: no point retrying the following files
            failed.extend(paths[i:])
            break
        except RuntimeError:
            failed.append(path)
        else:
            if renamed is not None and kept:
                kept = _name_kept(str(kept))
                if kept != path.name:
                    renamed[path.name] = kept
    return failed


def _copy_media_files(paths: list[Path], target: Path) -> list[Path]:
    """Direct copy into the media folder; returns the files that failed."""
    failed: list[Path] = []
    for path in paths:
        try:
            shutil.copy2(path, target / path.name)
        except OSError:
            failed.append(path)
    return failed


def install_media_files(paths: list[Path],
                        renamed: dict[str, str] | None = None) -> list[Path]:
    """Put the files into Anki's media library; return those left outside.

    Anki open: storeMediaFile, since writing into collection.media while Anki runs
    desynchronises its media database. Anki closed: a direct copy, which Anki
    adopts under its own name at its next start, so only the first fills `renamed`.
    """
    if not paths:
        return []
    if connect.status(refresh=True).connected:
        return store_media_files(paths, renamed)
    target = media_dir()
    if target is None:
        return list(paths)
    return _copy_media_files(paths, target)
