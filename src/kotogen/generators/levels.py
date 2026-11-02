"""The JLPT level of a source, and how to file a catalogue by level.

Used by the podcast and YouTube catalogues, on any entry with a `levels`
attribute, along with the form their aliases are compared in. The level only
files a source: it reaches neither the splitting nor the model, and `--level
auto` still judges each passage. A source may cover a range ("N3-N2"), or have
no level at all.
"""

from __future__ import annotations

import re

from kotogen import console, i18n
from kotogen.i18n import _, convention
from kotogen.jlpt import LEVELS

# The widest label of a range, "N5-N4".
LABEL_COLUMNS = 5


def alias_key(entry: str) -> str:
    """The form a catalogue alias is compared in: "Teppei" and "teppei" are one."""
    return (entry or "").strip().lower()


def ordered(levels) -> tuple[str, ...]:
    """Known levels, without duplicates or case, from the easiest to the hardest.

    Anything else is dropped rather than refused, a typo in a hand-written entry
    included.
    """
    seen = {str(level).strip().upper() for level in levels or ()}
    return tuple(level for level in LEVELS if level in seen)


def label(levels) -> str:
    """The level as it is shown: "N4", "N5-N4", or nothing.

    Only the bounds of a range: "N5-N3", never "N5-N4-N3".
    """
    levels = ordered(levels)
    if not levels:
        return ""
    return levels[0] if len(levels) == 1 else f"{levels[0]}-{levels[-1]}"


def written(value) -> tuple[str, ...]:
    """The `levels` field of a user file, written however it comes.

    `["N4", "N3"]`, `"N4-N3"`, `"n4, n3"` and `"N4"` are all read alike.
    """
    if isinstance(value, str):
        value = re.split(r"[^A-Za-z0-9]+", value)
    return ordered(value) if isinstance(value, (list, tuple)) else ()


def by_level(known: dict) -> list[tuple[str, list[tuple[str, object]]]]:
    """The catalogue grouped: [(label, [(alias, entry)...])...], easiest first.

    Grouped by whole label ("N5-N4"), so that a show appears once in a menu. The
    unclassified come last under an empty label, for the caller to name.
    """
    groups: dict[str, list[tuple[str, object]]] = {}
    for alias, entry in sorted(known.items()):
        groups.setdefault(label(entry.levels), []).append((alias, entry))

    def rank(pair: tuple[str, list]) -> tuple[int, int]:
        levels = ordered(pair[0].split("-"))
        if not levels:  # unclassified: after everything else
            return (len(LEVELS), len(LEVELS))
        return (LEVELS.index(levels[0]), LEVELS.index(levels[-1]))

    return sorted(groups.items(), key=rank)


def listed(known: dict) -> list[str]:
    """The aliases of a catalogue, one line per level, for the error of an unknown alias.

    The labels are right-aligned in screen columns, a translated one included.
    """
    lines = []
    for level, entries in by_level(known):
        name = level or _("level not stated")
        lines.append("   " + " " * max(0, LABEL_COLUMNS - console.width(name)) + name
                     + convention("colon", ": ")
                     + i18n.listed(alias for alias, _entry in entries))
    return lines
