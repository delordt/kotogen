"""What every test of the menus shares: the answers typed, the state they start
from, and the helpers that read the screen.

The menus keep module state (the last command, each menu's choice, Anki's
state), and the machine's `.env` sets the rest: the fixtures here reset both.
A test module takes them with `from menus import *`, which lets pytest see the
autouse fixtures; `__all__` says what that brings.
"""

import builtins
import contextlib
import re

import pytest

from kotogen import audio_quality, choices, interactive, keyboard, menu, prefs, video_clip
from kotogen.anki.connect import AnkiStatus

__all__ = [
    "MODEL",
    "CONNECTED",
    "_fake_status",
    "anki_connected",
    "forget_anki_state",
    "silent_deck",
    "fresh_menus",
    "auto_send_off",
    "verbose_off",
    "audio_quality_default",
    "video_mode_default",
    "api_key_set",
    "model_chosen",
    "anki_down",
    "_MAINTAIN_COUNTS",
    "feed",
    "keys",
    "_highlighted",
    "_plain",
    "_status_bar",
    "press_catalogue",
    "templates_profile",
]

# The model the tests start from. None is built in, and without one the
# commands that call the AI are dimmed.
MODEL = "publisher/model"

# Anki open, with every deck and note type expected. The names are the
# collection's schema, one set for every language.
CONNECTED = AnkiStatus(
    connected=True,
    profile="Test",
    decks=frozenset({"Japanese::Vocabulary", "Japanese::Grammar",
                     "Japanese::Listening", "Japanese::Reading", "Japanese::Kanji"}),
    notetypes=frozenset({"Vocabulary", "Grammar", "Listening", "Reading", "Kanji"}),
)


def _fake_status(state: AnkiStatus):
    return lambda *, refresh=False, timeout=2: state


@pytest.fixture(autouse=True)
def anki_connected(monkeypatch):
    """AnkiConnect answers by default; the tests of the disconnected case override."""
    monkeypatch.setattr("kotogen.interactive.status.anki_status", _fake_status(CONNECTED))


@pytest.fixture(autouse=True)
def forget_anki_state(monkeypatch):
    """Every test probes Anki afresh: its state is held for the whole session."""
    monkeypatch.setattr("kotogen.interactive.status._anki", None)


@pytest.fixture(autouse=True)
def silent_deck(monkeypatch):
    """The maintenance dialogue counts nothing until a test says so.

    Otherwise it queries AnkiConnect, and an open Anki's own cards would decide
    what the list shows."""
    monkeypatch.setattr(interactive.maintain, "_maintain_counts", lambda: None)


@pytest.fixture(autouse=True)
def fresh_menus(monkeypatch):
    """Every test starts from a session that has opened nothing: the menus hold
    the command launched and the choice made in each."""
    monkeypatch.setattr(interactive, "_last_command", None)
    monkeypatch.setattr(interactive.screen, "_remembered_choices", {})


@pytest.fixture(autouse=True)
def auto_send_off(monkeypatch):
    """Auto-send is off unless a test says otherwise (module state)."""
    monkeypatch.setattr(prefs, "_auto_send", False)


@pytest.fixture(autouse=True)
def verbose_off(monkeypatch):
    """Verbose mode off (its default) whatever the machine's `.env` says."""
    monkeypatch.setattr(prefs, "_verbose", False)


@pytest.fixture(autouse=True)
def audio_quality_default(monkeypatch):
    """Compression at the default (none) whatever the `.env`: it is module state."""
    monkeypatch.setattr(audio_quality, "_code", None)


@pytest.fixture(autouse=True)
def video_mode_default(monkeypatch):
    """Video picture at the default (ask) whatever the `.env`: it is module state."""
    monkeypatch.setattr(video_clip, "_mode", None)
    monkeypatch.delenv(video_clip.ENV_VAR, raising=False)


@pytest.fixture(autouse=True)
def api_key_set(monkeypatch):
    """An AI key is available by default; the test of the absent case takes it away."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")


@pytest.fixture(autouse=True)
def model_chosen(monkeypatch):
    """A model chosen at OpenRouter, whatever the machine's `.env` says; the tests
    of the case with none take it away. What the "m" setting writes into
    `os.environ` is undone after every test."""
    monkeypatch.setenv("KOTOGEN_PROVIDER", "openrouter")
    monkeypatch.setenv("KOTOGEN_MODEL", MODEL)


def anki_down(monkeypatch) -> None:
    monkeypatch.setattr("kotogen.interactive.status.anki_status",
                        _fake_status(AnkiStatus(connected=False)))


# The real counter `silent_deck` replaces, kept for the test that exercises it.
_MAINTAIN_COUNTS = interactive.maintain._maintain_counts


def feed(monkeypatch, answers: list) -> None:
    """Makes input() hand back the answers given, in order.

    An exception in the list (KeyboardInterrupt) is raised instead: a Ctrl+C at a
    precise moment."""
    it = iter(answers)

    def answer(prompt: str = "") -> str:
        value = next(it)
        if isinstance(value, type) and issubclass(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(builtins, "input", answer)


@pytest.fixture
def keys(monkeypatch):
    """Makes the menus believe they run on a terminal, and types for them."""
    def press(sequence: list[str]) -> None:
        source = iter(sequence)
        monkeypatch.setenv("COLUMNS", "120")  # no line truncated
        monkeypatch.setattr(menu, "raw_ready", lambda: True)
        monkeypatch.setattr(keyboard, "raw_mode", contextlib.nullcontext)
        monkeypatch.setattr(keyboard, "read_key", lambda: next(source))
        # Nothing waits in the queue (`pending()`), and typing never pauses inside
        # a number (`pending(delay)`): a test that wants either says so itself.
        monkeypatch.setattr(keyboard, "pending", lambda timeout=0.0: timeout > 0)

    return press


def _highlighted(out: str) -> str:
    """The last line highlighted by the redraw."""
    return re.findall(r"\033\[7m(.*?)\033\[0m", out)[-1]


def _plain(out: str) -> str:
    """The output without what drives the terminal: what is left is what reads."""
    return re.sub(r"\033\[[0-9;]*[A-Za-z]", "", out).replace("\r", "")


def _status_bar(out: str) -> str:
    """The last status line drawn (AI and Anki together): the current state."""
    return [line for line in out.splitlines() if line.startswith("AI [")][-1]


@pytest.fixture
def press_catalogue(monkeypatch):
    """Two sites of different genres, without touching the network."""
    from kotogen.generators import press

    sites = {
        "gigazine": press.Site("GIGAZINE", "https://gigazine.test/rss", "Science"),
        "jiji": press.Site("時事通信", "https://jiji.test/rss", "News"),
    }
    monkeypatch.setattr(press, "catalogue", lambda: dict(sites))
    return sites


@pytest.fixture
def templates_profile(tmp_path, monkeypatch):
    target = tmp_path / choices.FILE
    monkeypatch.setattr(choices, "file", lambda: target)
    return target
