"""What this profile chose about its cards, as `templates.env` keeps it.

Most of the file is the Anki templates' business (`kotogen.anki.templates`), but
`all.lang`, the language of the cards, is read without Anki (`prompts.language`):
where the file is and how it reads are said here, for both layers.
"""

from __future__ import annotations

from pathlib import Path

from kotogen import settings, system

FILE = "templates.env"

# Prefix of the choices that apply to every note type: the palette, the language.
GLOBAL = "all"

# The key of the language of the cards.
LANGUAGE = f"{GLOBAL}.lang"


def file() -> Path:
    """Where the choices about the cards are filed.

    Next to the repository `.env` if the file is already there, otherwise with
    the settings.
    """
    repo = settings.repo_env()
    folder = system.config_dir()
    if repo is not None and (repo.parent / FILE).exists():
        folder = repo.parent
    return folder / FILE


def values() -> dict[str, str]:
    """The choices written in the file, as they stand.

    Read on every call, never cached: the customisation screen writes, then
    redisplays.
    """
    try:
        lines = file().read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return {}
    choices = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _sep, value = line.partition("=")
        value = value.strip()
        choices[key.strip()] = value
    return choices


def language() -> str:
    """The language of the cards as the file names it, "" when it names none.

    Not checked here: whether it is a language shipped is for `prompts.use`.
    """
    return values().get(LANGUAGE, "")
