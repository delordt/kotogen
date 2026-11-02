"""Opening the cards in a browser, as Anki will show them.

The templates hold behaviour no Python test covers: the shuffled choices, the
grouped speaking turns, the click that replays a line, the mini-book's pages.
This script serves `kotogen.anki.preview`, which renders the real templates,
while one works on `templates/`:

    python tests/card_bench.py                     # every sample
    python tests/card_bench.py audio               # one only
    python tests/card_bench.py audio --field Timecodes=          # see the degradation
    python tests/card_bench.py audio --field "Timecodes=0.5 - 4.2 7.1"

The page is served until the script stops, and a refresh reads the templates
again. Not a test: pytest does not collect it.
"""

from __future__ import annotations

import argparse
import sys
import threading
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from kotogen.anki import notetypes, preview  # after adding the path


def _warn(chosen) -> None:
    """Says the fields a sample lacks, and that the card will display empty.

    An empty field looks like a template that ignores it: the warning keeps the
    samples up with the generators' `FIELDS`.
    """
    for sample in chosen:
        spec = next(s for s in notetypes.SPECS if s.command == sample.command)
        missing = [f for f in spec.fields if f not in sample.fields]
        if missing:
            print(f"{sample.key}: fields with no test value (to be added in "
                  f"kotogen/anki/preview.py): {', '.join(missing)}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Serve the preview of the repository cards in a browser.")
    parser.add_argument("sample", nargs="?", default="",
                        choices=["", *[s.key for s in preview.SAMPLES]],
                        help="open only that one (default: all of them)")
    parser.add_argument("--field", action="append", default=[], metavar="NAME=VALUE",
                        help="replace a field (empty to erase it). Repeatable.")
    args = parser.parse_args()

    keys = (args.sample,) if args.sample else ()
    try:
        chosen = preview.samples(keys)
    except preview.Unavailable as exc:
        sys.exit(str(exc))

    if args.field:
        if len(chosen) > 1:
            sys.exit("--field does not know which card to address: name a sample ("
                     + ", ".join(s.key for s in chosen) + ").")
        fields = dict(chosen[0].fields)
        for raw in args.field:
            name, _sep, value = raw.partition("=")
            name = name.strip()
            if name not in fields:
                sys.exit(f'Unknown field: "{name}". Those of this card: '
                         f"{', '.join(sorted(fields))}")
            fields[name] = value
        chosen = (replace(chosen[0], fields=fields),)

    _warn(chosen)
    try:
        open_ = preview.serve(chosen)
    except preview.Unavailable as exc:
        sys.exit(str(exc))
    print(open_.url)
    for note in open_.notes:
        print(f"   {note}", file=sys.stderr)
    print("   Refreshing the page reads the templates again. Ctrl+C to stop.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        open_.stop()


if __name__ == "__main__":
    main()
