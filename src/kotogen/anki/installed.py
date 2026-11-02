"""What kotogen last wrote into each note type, kept to tell who moved since.

`deck install` compares each face with the text kotogen last wrote there. If
Anki still holds it, only the repository moved and the face is rewritten without
a question; if the repository does, the touch-up made in Anki is kept; if
neither does, both moved and the user is asked, each side's diff shown. The one
silent write is over a text this file holds byte for byte.

Kept in the data folder, by Anki profile and note type ID, since the name may
change. Not in the collection: a comment stamped into a template would break the
rule that the rendering only removes (see `templates`).
"""

from __future__ import annotations

import json
from pathlib import Path

from kotogen import system

FILE = "installed.json"

# Layout version: a file from a later release is neither read (it could be
# misread) nor overwritten (that release would lose its entries).
VERSION = 1


def path() -> Path:
    """Where the file lives: with the backups, among what does not regenerate."""
    return system.data_dir() / FILE


def _read() -> dict | None:
    """The whole file; {} when there is none, None when it is not ours to touch.

    A truncated or unreadable file gives {} too: the next install asks.
    """
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get("version", VERSION) != VERSION:
        return None
    return data


def recall(profile: str, model_id: int) -> dict:
    """What was last written into that note type, or {} if nothing is known.

    `{"cards": {card: {"Front": ..., "Back": ...}}, "css": ...}`, each card under
    its name in the repository, since the one in Anki may be the user's own.
    """
    entry = (_read() or {}).get("profiles", {}).get(profile, {}).get(str(model_id))
    return entry if isinstance(entry, dict) else {}


def remember(profile: str, model_id: int, written: dict) -> None:
    """Files what has just been written into that note type, in place of the old.

    Written whole, so a crash leaves the old file intact. A failed write is
    swallowed: the next install only asks.
    """
    data = _read()
    if data is None:
        return
    data["version"] = VERSION
    data.setdefault("profiles", {}).setdefault(profile, {})[str(model_id)] = written
    try:
        system.write_whole(path(), json.dumps(data, ensure_ascii=False, indent=1))
    except OSError:
        pass
