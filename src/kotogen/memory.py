"""Where a run remembers what it has already made: the deck, or a file.

A run aimed at Anki skips what the deck or `seen.json` (this machine's history)
already holds. A JSON Lines run (see `exporter.is_json`) may feed a set that
never saw the deck, so it remembers with its own file instead
(`known.JsonlFile`): its cards stand for the deck, `<name>.seen.json` beside it
for `seen.json`. With no file named it remembers nothing (`known.Nothing`).

Settled once per run by `follow`, before any generator asks `known()`. The
command line hands the deck in: only the adapter (`kotogen.anki.deck`) can name it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from kotogen.known import JsonlFile, Known, Nothing

_known: Known = Nothing()


def follow(args: argparse.Namespace, deck: Known | None = None) -> Known:
    """Settle what this run remembers with, from its format and its `--output`.

    `deck` is what a run aimed at the deck remembers with: the deck of Anki on
    the command line, nothing for a program that keeps none.
    """
    global _known
    if getattr(args, "format", None) == "json":
        output = getattr(args, "output", None)
        _known = JsonlFile(Path(output)) if output else Nothing()
    else:
        _known = deck if deck is not None else Nothing()
    return _known


def known() -> Known:
    """What the current run remembers with."""
    return _known
