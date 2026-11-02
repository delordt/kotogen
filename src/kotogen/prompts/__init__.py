"""The instructions sent to the model, taken out of the Python code.

One markdown file per instruction, shipped as package data, so that a prompt is
edited and diffed apart from the code. An instruction that asks for card text is
written in the language of the cards: one folder per language (`en/`, `fr/`,
`ja/`), each with the same twenty-two, none borrowing from another. The thirteen
that hand back STRUCTURE (JSON: where to cut an audio, which rule a page
teaches...) have one English copy in `structure/`, which is not a language and
which `languages()` does not list. `load` looks in the language of the cards,
then in `structure/`, then fails.

The JSON keys and protocol values the model answers with stay English in every
language: the note type's field names (`Translation`, `Decoy1`), the values the
code compares against (`duplicate`, `grammar`) and a few other keys (`Decoys`,
`TranscriptLines`, `TranslationLines`).

A prompt includes another on a line of its own, as the five PDF extractions
share their error contract:

    {{include:pdf_error_contract}}

What the code builds around a prompt (the user message, an instruction composed
on the spot) is prompt too: written in English at its call site and translated
by `say` through `<lang>/wording.json`, into the language of the CARDS rather
than the screen's.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

from kotogen import choices
from kotogen.i18n import _, quoted as _quoted

DIR = Path(__file__).parent

# The folder of the instructions that have no language: a folder name rather
# than a language code, read only for what the language of the cards lacks.
STRUCTURE = "structure"

# The language the code writes its fragments in: what `say` hands back
# untranslated and what an unknown language of cards falls back on, as
# `i18n.SOURCE` does for the screens.
SOURCE = "en"

_INCLUDE_RE = re.compile(r"^\{\{include:([\w-]+)\}\}[ \t]*\n?", re.MULTILINE)

_language: str | None = None


def languages() -> list[str]:
    """The languages the cards can be asked for, `SOURCE` first.

    `structure/` is left out, or the menu would offer it as a language of cards.
    """
    folders = sorted(path.name for path in DIR.iterdir()
                     if path.is_dir() and path.name != STRUCTURE
                     and any(path.glob("*.md")))
    return [SOURCE] + [name for name in folders if name != SOURCE]


def language() -> str:
    """The language the cards are written in, resolved once.

    From the `all.lang` template setting, read through `choices`, which needs no
    Anki. Once per run, so that no run mixes two languages, and per profile,
    since there is no `--deck`. `use` overrides it for the run.
    """
    if _language is None:
        use(choices.language())
    return _language or SOURCE


def use(name: str) -> str:
    """Switch to `name`. Returns the language actually used.

    An unknown name falls back on `SOURCE` rather than failing: a profile naming
    a language nobody ships gets English cards instead of none.
    """
    global _language
    _language = name if name in languages() else SOURCE
    return _language


def folder(lang: str | None = None) -> Path:
    """Where the instructions of that language sit."""
    return DIR / (lang or language())


def load(name: str) -> str:
    """Instruction `name` (without the .md), includes resolved.

    Looked for in the language of the cards, then in `STRUCTURE`. Raises
    RuntimeError if neither has it, and never falls back on another language: a
    deck quietly filled in the wrong language costs more than a broken install.
    """
    return _read(name, language())


@cache
def _read(name: str, lang: str) -> str:
    path = folder(lang) / f"{name}.md"
    if not path.exists():
        path = DIR / STRUCTURE / f"{name}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            _("instruction {name} not found ({path}). The package "
              "installation is incomplete: reinstall it (pip install -e .).")
            .format(name=_quoted(name), path=path)
        ) from exc
    # Text mode already reads CRLF as \n; normalised anyway, since a stray \r
    # would reach the model as is.
    text = text.replace("\r\n", "\n")
    return _INCLUDE_RE.sub(lambda m: _read(m.group(1), lang), text)


def names(lang: str | None = None) -> list[str]:
    """Every instruction shipped, in alphabetical order.

    Without `lang`, what the program can load (the languages and `STRUCTURE`);
    with it, what that folder holds itself, which tells how much is translated.
    """
    if lang is not None:
        return sorted(p.stem for p in folder(lang).glob("*.md"))
    return sorted({p.stem for name in [*languages(), STRUCTURE]
                   for p in folder(name).glob("*.md")})


def say(text: str) -> str:
    """The `text` in the language of the CARDS, or `text` itself untranslated.

    Keyed by the English like `i18n.translate`, but answering for the deck, not
    the screen. Everything composed around an instruction goes through it: the
    user message, the ceiling said in words, the fields laid out for the model.
    """
    if language() == SOURCE:
        return text
    return _wording(language()).get(text, text)


@cache
def _wording(lang: str) -> dict[str, str]:
    """The table of composed fragments for that language, or an empty one.

    An unreadable table is empty rather than a crash: the fragments go out in
    English, a poor prompt but a prompt.
    """
    try:
        data = json.loads((folder(lang) / "wording.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {key: value for key, value in data.items()
            if isinstance(value, str) and value}
