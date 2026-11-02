"""Does the documentation announce what the code actually does?

A wrongly documented deck or note type fails only at send time, AFTER the AI
calls are paid; a documented option that does not exist stops a pasted command.
Every `kotogen ...` example of the documentation is replayed against the parser.
"""

from __future__ import annotations

import argparse
import io
import re
import shlex
from contextlib import redirect_stderr
from pathlib import Path

import pytest

from kotogen import settings
from kotogen.cli import _DECK_DEFAULTS, build_parser

ROOT = Path(__file__).resolve().parent.parent

# `KOTOGEN_VOCAB_NOTETYPE=Vocabulary`, commented out or not.
_SETTING_RE = re.compile(r"^#?\s*(KOTOGEN_\w+?_(?:DECK|NOTETYPE))=(.+)$", re.MULTILINE)

# Any setting declared (`KOTOGEN_MODEL=`), commented out or not.
_ANY_SETTING_RE = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=", re.MULTILINE)

# A long option quoted in the text (`--max-duration`). Not a CSS variable of the
# templates documentation (`--correct: 76, 175, 80`, `var(--correct)`), known by
# the colon after it or the `var(` before it, nor the tail of a heading anchor
# (`#keeping-the-picture---video`), glued to the hyphen before it.
_OPTION_RE = re.compile(r"(?<!var\()(?<![\w-])--[a-z][a-z0-9-]+(?![\w:-])")

# Options of other tools that the documentation quotes. An explicit list, so
# that an option really gone from the CLI cannot hide here.
_FOREIGN_OPTIONS = {
    "--with-deps",  # playwright install --with-deps chromium (Linux dependencies)
    # `tests/card_bench.py`, which has its own parser outside the kotogen CLI.
    "--field",
    # `tests/codec_bench.py`, likewise.
    "--remove",
}

# Options the documentation may name before the CLI has them, so a feature can
# be documented ahead of its code. Empty, but kept declared.
_PLANNED_OPTIONS: set[str] = set()


def _doc_files() -> list[Path]:
    """Everything that documents the CLI: the README and the `docs/` pages."""
    return [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]


def _documented(path: Path) -> dict[str, str]:
    """KOTOGEN_*_DECK / _NOTETYPE settings quoted by a documentation file."""
    return {m.group(1): m.group(2).strip() for m in _SETTING_RE.finditer(
        path.read_text(encoding="utf-8"))}


def _expected() -> dict[str, str]:
    """What the code really uses, for want of an override in the .env."""
    values = {}
    for command, (deck, notetype) in _DECK_DEFAULTS.items():
        values[f"KOTOGEN_{command.upper()}_DECK"] = deck
        values[f"KOTOGEN_{command.upper()}_NOTETYPE"] = notetype
    return values


def _examples() -> list[tuple[str, list[str]]]:
    """The `kotogen ...` lines of the ```bash blocks of the documentation, split
    into argv; a bare `kotogen` (the interactive assistant) is left out."""
    found = []
    for path in _doc_files():
        in_bash = False
        for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.startswith("```"):
                in_bash = line.strip() == "```bash"
                continue
            if not in_bash or not line.startswith("kotogen "):
                continue
            argv = shlex.split(line, comments=True)[1:]
            if argv:
                found.append((f"{path.relative_to(ROOT).as_posix()}:{number}", argv))
    return found


def _parser_options() -> list[list[str]]:
    """The options of every subcommand, one entry per option."""
    options: list[list[str]] = []

    def walk(parser: argparse.ArgumentParser) -> None:
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for subparser in action.choices.values():
                    walk(subparser)
            elif (action.option_strings and action.dest != "help"
                  and action.help is not argparse.SUPPRESS):
                options.append(action.option_strings)

    walk(build_parser())
    return options


def test_env_example_matches_code():
    expected = _expected()
    for name, value in _documented(ROOT / ".env.example").items():
        assert value == expected[name], f"{name}: .env.example says {value!r}"


def test_docs_match_code():
    expected = _expected()
    for path in _doc_files():
        for name, value in _documented(path).items():
            assert value == expected[name], f"{name}: {path.name} says {value!r}"


@pytest.mark.parametrize("where, argv", _examples(), ids=lambda v: v if isinstance(v, str) else "")
def test_documented_examples_parse(where, argv):
    parser = build_parser()
    message = io.StringIO()
    try:
        with redirect_stderr(message):
            parser.parse_args(argv)
    except SystemExit:  # argparse refused the line
        pytest.fail(f"{where}: kotogen {shlex.join(argv)}\n{message.getvalue().strip()}")


def test_documented_options_exist():
    # `--help` is offered by argparse itself, not declared like the others.
    known = {"--help", *(name for strings in _parser_options() for name in strings)}
    for path in _doc_files():
        text = path.read_text(encoding="utf-8")
        for option in sorted(set(_OPTION_RE.findall(text))
                             - _FOREIGN_OPTIONS - _PLANNED_OPTIONS):
            assert option in known, f"{path.name} quotes {option}, absent from the CLI"


def test_every_option_is_documented():
    documented = "\n".join(p.read_text(encoding="utf-8") for p in _doc_files())
    cited = set(_OPTION_RE.findall(documented))
    for strings in _parser_options():
        longs = [name for name in strings if name.startswith("--")]
        assert cited.intersection(longs), f"{'/'.join(longs)} is documented nowhere"


# ── The settings registry and the .env.example ───────────────────────────────
# Checked both ways: a setting missing from the example file, and an example
# line that outlived its setting.

def _example_settings() -> set[str]:
    """The settings declared by `.env.example`, commented out or not."""
    return set(_ANY_SETTING_RE.findall(
        (ROOT / ".env.example").read_text(encoding="utf-8")))


def test_every_setting_is_in_the_example():
    for name in sorted(set(settings.OPTIONS) - _example_settings()):
        pytest.fail(f"{name} is described nowhere in .env.example")


def test_the_example_invents_no_setting():
    for name in sorted(_example_settings() - set(settings.OPTIONS)):
        pytest.fail(f".env.example describes {name}, absent from settings.OPTIONS")


def test_registered_defaults_match_the_docs():
    """The registry's default is the one `.env.example` shows."""
    for name, value in _documented(ROOT / ".env.example").items():
        assert settings.default(name) == value, f"{name}: the registry says otherwise"


# ── The links between the pages ──────────────────────────────────────────────
# A rename or a move breaks links that nothing reads until a reader clicks.
# The pages are taken by glob, so a page added later is checked as it appears.

# `[Index](../README.md#documentation)`. An http URL is not ours to check, and
# an anchor alone points into the page it is written on.
_LINK_RE = re.compile(r"\]\(([^)\s]+)\)")

# GitHub's anchor for a heading: lowercased, punctuation dropped, spaces
# hyphenated. Letters outside ASCII stay, as in a heading opening on 青空文庫.
_PUNCTUATION_RE = re.compile(r"[^\w\s-]", re.UNICODE)


def _linking_files() -> list[Path]:
    """Every page that may link to another one: the markdown of the root, the
    `docs/` pages, and the context page of each template folder."""
    return [*sorted(ROOT.glob("*.md")),
            *sorted((ROOT / "docs").glob("*.md")),
            *sorted((ROOT / "templates").rglob("context.md"))]


def _anchors(path: Path) -> set[str]:
    """The anchors a page offers, one per heading outside its fenced blocks."""
    anchors, fenced = set(), False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and line.startswith("#"):
            title = line.lstrip("#").strip().lower()
            anchors.add(_PUNCTUATION_RE.sub("", title).strip().replace(" ", "-"))
    return anchors


@pytest.mark.parametrize("path", _linking_files(),
                         ids=lambda path: path.relative_to(ROOT).as_posix())
def test_documentation_links_resolve(path: Path) -> None:
    """A page may only link to a file that exists, at a heading it really has."""
    for target in _LINK_RE.findall(path.read_text(encoding="utf-8")):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        relative, _, anchor = target.partition("#")
        destination = (path.parent / relative) if relative else path
        assert destination.exists(), f"{path.name} links to {target}, which is nowhere"
        if anchor and destination.suffix == ".md":
            assert anchor.lower() in _anchors(destination), (
                f"{path.name} links to {target}, a heading {destination.name} has not")
