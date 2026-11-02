"""The settings: what they are worth, where they are written, how they are read.

`OPTIONS` is the one list of what the program accepts, every setting read the
same way; `tests/test_docs.py` checks it against `.env.example` both ways.
Preferences live in the platform's configuration folder (`~/.config/kotogen` on
Linux), API keys in the repository's `.env` when the program runs from one, else
beside the preferences in a file of their own. The keys' file is written 0600,
and every write goes through a temporary file renamed into place: an
interruption must not leave a truncated file, that is a lost key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from kotogen import system

# -- The registry -------------------------------------------------------------

@dataclass(frozen=True)
class Option:
    """A setting: its name, what it does, how to read it, where to write it."""

    name: str
    doc: str
    kind: str = "text"       # text | flag | list | path
    default: object = ""     # "" = the caller is the one that knows the default
    secret: bool = False     # a key: separate file, closed permissions


# Deck and note type per command: the program's defaults, which the
# documentation copies and a test checks. English in EVERY language of the
# cards, being the collection's schema; anybody may write their own in these
# settings before their first `deck install`, the one moment it is free.
DECK_DEFAULTS = {
    "kanji": ("Japanese::Kanji", "Kanji"),
    "vocab": ("Japanese::Vocabulary", "Vocabulary"),
    "grammar": ("Japanese::Grammar", "Grammar"),
    "audio": ("Japanese::Listening", "Listening"),
    "reading": ("Japanese::Reading", "Reading"),
}

def _deck_options() -> list[Option]:
    """The three settings every deck command carries, spelled out."""
    options = []
    for command, (deck, notetype) in DECK_DEFAULTS.items():
        upper = command.upper()
        options += [
            Option(f"KOTOGEN_{upper}_DECK",
                   f"Anki deck of the {command} command", default=deck),
            Option(f"KOTOGEN_{upper}_NOTETYPE",
                   f"Note type of the {command} command", default=notetype),
            Option(f"KOTOGEN_{upper}_CARDS",
                   f"Cards of that note type this profile installs ({command}), "
                   "empty = all of them", kind="list"),
        ]
    return options


OPTIONS: dict[str, Option] = {option.name: option for option in [
    # API keys: no default, never displayed, typed blind in the menu and filed in
    # the secrets file.
    Option("OPENROUTER_API_KEY", "OpenRouter key (the default provider)", secret=True),
    Option("ANTHROPIC_API_KEY", "Anthropic key (--provider anthropic)", secret=True),
    Option("OPENAI_API_KEY", "OpenAI key (--provider openai)", secret=True),

    # Choice of the model called without --provider / --model.
    Option("KOTOGEN_PROVIDER", "Provider called without --provider", default="openrouter"),
    Option("KOTOGEN_MODEL", "Model called without --model, at that provider"),

    # Prerequisites. Missing optional modules are installed on the first run in
    # a given environment (see `prerequisites`).
    Option("KOTOGEN_INSTALL",
           "Missing optional modules: ask, always, never"),

    # Display and comfort.
    Option("KOTOGEN_LANG",
           "Interface language: en, or the code of a table of locales/ "
           "(default: en)",
           default="en"),
    Option("KOTOGEN_GETTING_STARTED",
           "Treat the next launch in a terminal as the first: the getting-started "
           "guide opens if the key or Anki is missing, and the setting turns "
           "itself off either way",
           kind="flag", default=True),
    Option("KOTOGEN_CURRENCY", "Currency costs are displayed in (default: dollars)"),
    Option("KOTOGEN_CURRENCY_RATE", "A pinned rate instead of the day's, per dollar"),
    Option("KOTOGEN_VERBOSE", "Verbose mode: echo the equivalent command",
           kind="flag", default=False),
    Option("KOTOGEN_NO_RAW_KEYS", "Numbered input in the menus, without the arrows",
           kind="flag", default=False),
    Option("KOTOGEN_DEBUG", "Full traceback of an unexpected error",
           kind="flag", default=False),

    # Output and sending.
    Option("KOTOGEN_OUTPUT_DIR", "Folder of the TSVs and MP3s produced", kind="path"),
    Option("KOTOGEN_AUTO_SEND", "Send the cards to Anki without asking",
           kind="flag", default=False),
    Option("KOTOGEN_FORMAT", "What the cards are written as: tsv, json",
           default="tsv"),
    Option("KOTOGEN_AUDIO_QUALITY", "Audio compression: none, light, medium, strong"),
    Option("KOTOGEN_VIDEO",
           "Picture of video sources: ask, always, never"),
    Option("KOTOGEN_PROOFREAD",
           "Cards returned damaged (the \"!!\" lines): ask, keep, tag, drop"),

    # Anki.
    Option("KOTOGEN_MEDIA_DIR", "The collection.media folder, if detection fails",
           kind="path"),
    Option("KOTOGEN_ANKICONNECT_URL", "Where the addon listens, if not the usual port"),
    Option("KOTOGEN_ANKICONNECT_KEY", "The key the addon demands, if it demands one",
           secret=True),

    # Backups.
    Option("KOTOGEN_BACKUP", "Automatic backup before maintain / ask / deck install",
           kind="flag", default=True),
    Option("KOTOGEN_BACKUP_DIR", "Where to file the backups", kind="path"),

    # What this profile installs.
    Option("KOTOGEN_SKIP", "Unused commands: out of the menu and of deck install",
           kind="list"),
    Option("KOTOGEN_FLAGS",
           "What the flags of maintain ask for, where it differs from the default: "
           "pink=renew,star=derive (none = no action)", kind="list"),

    *_deck_options(),
]}


# -- Reading a setting --------------------------------------------------------
# Always from `os.environ`, never cached: the menu changes a setting mid-session
# and the next command must see it. The files are poured into it once, at startup.

_TRUTHY = {"1", "true", "yes", "y", "on"}
_FALSY = {"0", "false", "no", "n", "off"}


def _option(name: str) -> Option:
    """The setting of that name: an unknown one is a typo in the code, raised at once."""
    try:
        return OPTIONS[name]
    except KeyError:
        raise KeyError(f"unknown setting: {name} (to be declared in settings.OPTIONS)") from None


def default(name: str) -> object:
    """What this setting is worth when nobody has set it."""
    return _option(name).default


def raw(name: str) -> str:
    """The value as it is written, without default or interpretation."""
    return os.environ.get(_option(name).name, "").strip()


def text(name: str) -> str:
    """The value, or the registry default if it is absent or empty."""
    value = raw(name)
    return value or str(_option(name).default or "")


def flag(name: str) -> bool:
    """A boolean, with the same vocabulary for every setting.

    An unreadable value (`KOTOGEN_BACKUP=maybe`) gives the declared default
    rather than an error.
    """
    value = raw(name).lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    return bool(_option(name).default)


def items(name: str) -> list[str]:
    """A list written with commas, blanks and empties removed."""
    return [part.strip() for part in raw(name).split(",") if part.strip()]


def folder(name: str) -> Path | None:
    """A folder, or None if it is not set (for the caller to fall back)."""
    value = raw(name)
    return Path(value).expanduser() if value else None


# -- Where the files live -----------------------------------------------------
# A `.env` carries secrets, and preferences such as a display currency live apart:
#
#   the settings   <config>/settings.env   always, repository or not
#   the keys       the repository `.env` if there is one, else <config>/secrets.env
#
# The order of priority, when reading:
#
#   1. the real environment   `export KOTOGEN_MODEL=...` in a ~/.bashrc wins
#   2. the repository `.env`  what was written there by hand keeps its value
#   3. the profile files      settings.env, then secrets.env

SETTINGS_FILE = "settings.env"
SECRETS_FILE = "secrets.env"

# The root of the sources the running code was loaded from (`src/kotogen` sits
# two folders under it). For an installed wheel it is `site-packages`' parent:
# `pyproject.toml` tells the two apart.
ROOT = Path(__file__).resolve().parents[2]


def repo_env() -> Path | None:
    """The `.env` at the root of the repository the program runs from, if any.

    That root only: a `.env` found from the current folder may be another
    project's, which would receive the keys typed in the menu and pour its lines
    into the environment pip and git run in.
    """
    if not (ROOT / "pyproject.toml").is_file():
        return None
    candidate = ROOT / ".env"
    return candidate if candidate.is_file() else None


def config_path() -> Path:
    """The file of the ordinary settings."""
    return system.config_dir() / SETTINGS_FILE


def secrets_path() -> Path:
    """The file of the API keys.

    The repository `.env` when there is one: it is already out of Git.
    """
    return repo_env() or (system.config_dir() / SECRETS_FILE)


def _declares(path: Path | None, name: str) -> bool:
    """True if this file carries an active line for this setting.

    Active means uncommented: a `.env` copied from `.env.example` carries thirty
    commented ones.
    """
    if path is None:
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return any(line.strip().startswith(f"{name}=") for line in lines)


def path_for(name: str) -> Path:
    """The file this setting is written to, to be announced before engraving it.

    Where it already lives, if anywhere: a copy left in a file of higher priority
    would quietly override the one written. Failing that, the keys with the keys,
    the settings with the settings.
    """
    for path in (repo_env(), config_path(), secrets_path()):
        if _declares(path, name):
            return path
    return secrets_path() if _option(name).secret else config_path()


# -- Reading the files back ---------------------------------------------------

def _load_file(path: Path) -> None:
    """Pour the settings a file holds into the process environment.

    Only the names of `OPTIONS`: pip, git and ffmpeg run in this environment, and
    a `PIP_INDEX_URL` or a `GIT_SSH_COMMAND` read from a file would change what
    they fetch and run.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return  # file absent or unreadable
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _sep, value = line.partition("=")
        if key.strip() not in OPTIONS:
            continue
        # setdefault: what is already set wins, hence the order of priority above.
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load() -> None:
    """Load the settings available, from the highest priority to the lowest."""
    seen = set()
    for path in (repo_env(), config_path(), secrets_path()):
        if path is None or path in seen:
            continue
        seen.add(path)
        _load_file(path)


# -- Writing a setting --------------------------------------------------------

def _restrict(path: Path, mode: int) -> None:
    """Close a file or a folder to the other accounts on the machine.

    Nothing on Windows: `chmod` there only toggles "read only", which would fail
    the next rewrite, and profile folders are private already.
    """
    if system.windows():
        return
    try:
        os.chmod(path, mode)
    except OSError:
        pass  # a file system without permissions (a FAT mount)


def write_private(path: Path, content: str) -> None:
    """Write the file in one go, 0600, never leaving half of it behind.

    Rewriting in place can lose an API key on a Ctrl+C; see `system.write_whole`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent == system.config_dir():
        # Our own folder only: for a repository `.env`, it would put the sources
        # in 0700.
        _restrict(path.parent, 0o700)
    system.write_whole(path, content, private=True, durable=True)


def write(name: str, value: str) -> Path:
    """Engrave `name=value` in its file, and return the file written.

    Replaces the existing line, even a commented one (that is how a setting
    offered as an example is switched on), else appends it.
    """
    option = _option(name)
    path = path_for(name)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    new_line = f"{option.name}={value}"
    for index, line in enumerate(lines):
        stripped = line.lstrip("# ").strip()
        if stripped.startswith(f"{option.name}="):
            lines[index] = new_line
            break
    else:
        lines.append(new_line)
    write_private(path, "\n".join(lines) + "\n")
    return path
