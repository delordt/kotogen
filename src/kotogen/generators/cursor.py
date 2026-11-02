"""Pick a long reading up where it was left off.

The counterpart of `--episode` for reading: the shared history (`seen`) holds
one key per work and the fingerprint of each passage handled. A fingerprint
rather than a rank, so that a text gaining a line skips or redoes nothing: an
unchanged passage stays handled, a changed one comes back. How many passages
are taken is up to `reading`, and where the text is cut up to `passages`.
"""

from __future__ import annotations

import hashlib
import re
import urllib.parse
from pathlib import Path

from kotogen import seen
from kotogen.i18n import _, counted

MODE = "reading"


def key_for(origin: str) -> str:
    """The key under which this work is followed in the history.

    Readable, since the settings screen shows it to forget a reading
    ("aozora-59898"). A URL becomes its host plus a fingerprint, as one site
    serves many texts. An empty key means no cursor: every pass starts over.
    """
    origin = (origin or "").strip()
    if not origin:
        return ""
    if origin.lower().startswith(("http://", "https://")):
        host = urllib.parse.urlsplit(origin).hostname or "web"
        host = re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-")
        return f"{host}-{_hash(origin)}"
    return re.sub(r"[^\w.-]+", "_", Path(origin).name, flags=re.UNICODE) or ""


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def fingerprint(block: list[str]) -> str:
    """The identifier of a passage: what it contains, and nothing else.

    It stays the same across passes, and when the text moves above the passage.
    """
    return _hash("\n".join(block))


def remaining(key: str, blocks: list[list[str]], *, mode: str = MODE
              ) -> tuple[list[tuple[int, list[str]]], int]:
    """(passages left to do, with their original rank; how many are done).

    The rank counts from 1 in the whole text, not in the day's window: it is the
    "passage 7/42" of the Source field. Without a key every passage is returned.
    """
    numbered = list(enumerate(blocks, 1))
    if not key:
        return numbered, 0
    done = seen.load(mode, key)
    left = [(rank, block) for rank, block in numbered
            if fingerprint(block) not in done]
    return left, len(blocks) - len(left)


def from_rank(blocks: list[list[str]], rank: int) -> list[tuple[int, list[str]]]:
    """The passages from the n-th one on, history ignored.

    As with `--episode`, a rank typed by hand is redone even if already handled.
    """
    if rank < 1:
        raise ValueError(_("passage expected from 1 on, got {rank}.").format(rank=rank))
    if rank > len(blocks):
        said = counted(len(blocks),
                       "this text only has {count} passage, no. {rank} is not in it.",
                       "this text only has {count} passages, no. {rank} is not in it.")
        raise ValueError(said.format(count=len(blocks), rank=rank))
    return list(enumerate(blocks, 1))[rank - 1:]


def mark(key: str, block: list[str], rank: int, total: int, *,
         mode: str = MODE) -> None:
    """Memorise a passage whose cards are made.

    The rank is kept as a label only to make the file readable: the fingerprint
    is what identifies.
    """
    if key:
        seen.mark(mode, key, fingerprint(block), f"passage {rank}/{total}")
