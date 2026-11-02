"""Settings shared by the whole test suite.

The machine's `.env` describes its owner's deck, and the tests what the program
does for everyone: letting the two meet gives failures seen on one machine only.
"""

from __future__ import annotations

import os

import pytest

from kotogen import ai_client, console, i18n, memory, prerequisites, prompts, seen, settings, system
from kotogen.anki import connect as anki_connect, deck as anki_deck
from kotogen.known import Known

_PREFIX = "KOTOGEN_"


@pytest.fixture(autouse=True)
def kotogen_isolated_files(tmp_path, monkeypatch):
    """No test writes into the real configuration of the machine.

    The menu tests press keys, and the menu saves what they set: the
    configuration folder goes to a throwaway one, and the repository `.env` is
    hidden so a typed key is not written next to the real one.
    """
    monkeypatch.setattr(system, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(settings, "repo_env", lambda: None)


def _our_variables() -> list[str]:
    """The variables the program reads or sets, as they stand in the
    environment of the process.

    The prefix misses the API keys (`OPENROUTER_API_KEY`): the registry,
    `settings.OPTIONS`, names them all.
    """
    known = set(settings.OPTIONS)
    return [name for name in os.environ
            if name.startswith(_PREFIX) or name in known]


@pytest.fixture(autouse=True)
def kotogen_isolated_env():
    """Every test starts without our variables and leaves none behind.

    The machine's `.env` must not decide a result, and `cli.main()` loads it into
    `os.environ`, where `monkeypatch` restores nothing it did not set itself.
    """
    saved = {name: os.environ[name] for name in _our_variables()}
    for name in saved:
        del os.environ[name]
    yield
    for name in _our_variables():
        del os.environ[name]
    os.environ.update(saved)


@pytest.fixture(autouse=True)
def no_real_keyboard(monkeypatch):
    """A test that fakes a terminal fails rather than wait on the real console.

    `getwch` reads the Windows console whatever `sys.stdin` is, and would wait
    for a key nobody presses, with the whole suite behind it."""
    if system.windows():
        import msvcrt

        monkeypatch.setattr(msvcrt, "getwch",
                            lambda: pytest.fail("the real keyboard was read"))


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """The machine's cache is neither read nor written here.

    It keeps catalogues for a month (Tadoku, 青空文庫, 青空朗読): one written by
    a test would decide the result of every test after it.
    """
    monkeypatch.setattr(system, "cache_dir", lambda: tmp_path / "cache")


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """The machine's data folder is neither read nor written here.

    It holds what does not regenerate: the backups, and the record of what
    `deck install` wrote into each note type. A record shared between tests
    makes them pass or fail with the order of the run.
    """
    monkeypatch.setattr(system, "data_dir", lambda: tmp_path / "data")


@pytest.fixture(autouse=True)
def isolated_history(tmp_path, monkeypatch):
    """The machine's source history is neither read nor written here.

    It does not regenerate: a test calling `mark` (a command played end to end)
    would strike an article off for good.
    """
    monkeypatch.setattr(seen, "FILE", tmp_path / "seen.json")


@pytest.fixture(autouse=True)
def silent_prerequisites(monkeypatch):
    """No test installs packages into the environment running it.

    The first-run pass is silent outside a terminal, but under `pytest -s` a test
    calling `cli.main()` would offer to install torch. Only
    `tests/test_prerequisites.py` exercises the real function.
    """
    monkeypatch.setattr(prerequisites, "on_first_run", lambda: None)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No test leaves the machine, nor reaches the Anki open on it.

    A test that goes online is slow, depends on a site, and can pass for the
    wrong reason. The loopback stays open for the preview server, save the
    AnkiConnect port: Anki may be open during the run, so the port refuses at
    once, as a closed Anki does (Windows retries a silent port for two seconds).
    """
    import socket
    from urllib.parse import urlsplit

    anki = urlsplit(anki_connect.ANKICONNECT_URL).port
    real_connect = socket.socket.connect

    def connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            pytest.fail(f"this test reached the network ({host}): replace the call")
        if isinstance(address, tuple) and address[1] == anki:
            raise ConnectionRefusedError("AnkiConnect is closed during the tests")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)


@pytest.fixture(autouse=True)
def no_real_whisper(monkeypatch):
    """No test loads a real Whisper model.

    It costs seconds of torch and depends on what the machine has downloaded.
    `pytest.fail` is not an `Exception`, so callers that fall back when the
    listening fails (`nhk._listen`) cannot hide it. A transcription test hands
    `_load_whisper` its own fake.
    """
    from kotogen.generators import whisper

    def refuse():
        pytest.fail("this test reached the real Whisper: replace the transcription")

    monkeypatch.setattr(whisper, "_load_whisper", refuse)


@pytest.fixture(autouse=True)
def isolated_deck(monkeypatch):
    """No test queries the machine's deck.

    Anki may be open during the run: the deck answers as a closed Anki, and the
    tests that want a stocked deck replace it. Each test gets a fresh `Deck`, as
    the provenances read for one command are kept for the next
    (`known.Known.sources`).
    """
    def closed(action, **params):
        raise ConnectionError("AnkiConnect unreachable (tests)")

    monkeypatch.setattr(anki_deck, "anki", closed)
    monkeypatch.setattr(anki_deck, "DECK", anki_deck.Deck())
    monkeypatch.setattr(anki_deck, "_announced", set())


@pytest.fixture(autouse=True)
def no_model_of_another_test(monkeypatch):
    """Every test starts with no model set to work.

    The run's models are a module variable (`ai_client.run_models`), named on
    the first line of a JSON Lines file: one test's client would sign the next.
    """
    monkeypatch.setattr(ai_client, "_run_models", [])


@pytest.fixture(autouse=True)
def memory_of_the_deck(monkeypatch, isolated_deck):
    """Every test starts remembering with the deck, and leaves it that way.

    `cli.main()` settles the memory of its run in a module variable: a test
    playing a JSON run would otherwise hand its file to every test after it.
    """
    monkeypatch.setattr(memory, "_known", anki_deck.DECK)


@pytest.fixture(autouse=True)
def console_with_no_open_line():
    """No test inherits an action left open by the one before it.

    The action under way is a module variable: a test stopping halfway leaves
    it open, where in the program the following block always closes it.
    """
    console._step = None
    console._cut = False
    yield
    console._step = None
    console._cut = False


@pytest.fixture(autouse=True)
def isolated_language():
    """Every test reads the source language, and none of them leaks its own.

    The language is held in a module variable for the whole run: a test that
    switches it (the settings screen can) would hand the next a French screen.
    """
    i18n.use(i18n.SOURCE)
    yield
    i18n.use(i18n.SOURCE)


@pytest.fixture(autouse=True)
def isolated_card_language():
    """Same, for the language the CARDS are asked in.

    Left free, it would come from the machine's `templates.env`. Pinned on French
    although `all.lang` ships as `en`: French text goes through `prompts.say` and
    `wording.json`, where English would test the branch that does nothing. Tests
    about English call `prompts.use("en")`.
    """
    prompts.use("fr")
    yield
    prompts.use("fr")


# ── A laboratory Anki ─────────────────────────────────────────────────────────
# Shared by `test_backup.py` and `test_notetypes.py`, which both read a deck and
# write into it: two copies of the fake would drift apart.
#
def anki_note(note_id: int, notetype: str = "Vocabulary", *, tags=(), cards=(),
              **fields) -> dict:
    """A note in `notesInfo` shape, fields given as keywords."""
    return {"noteId": note_id, "modelName": notetype, "tags": list(tags),
            "cards": list(cards) or [note_id * 10],
            "fields": {name: {"value": value, "order": order}
                       for order, (name, value) in enumerate(fields.items())}}


class FakeAnki:
    """AnkiConnect in memory: answers the reads, records the writes."""

    def __init__(self, *notes: dict):
        self.notes = {note["noteId"]: note for note in notes}
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, action: str, **params):
        self.calls.append((action, params))
        if action == "findNotes":
            return sorted(self.notes)
        if action == "notesInfo":
            return [self.notes.get(i, {}) for i in params["notes"]]
        if action == "cardsInfo":
            return [{"cardId": c, "deckName": "Japanese::Vocabulary", "flags": 3,
                     "interval": 12, "lapses": 9, "queue": -1}
                    for c in params["cards"]]
        return None

    def params_for(self, action: str) -> list[dict]:
        """The parameters of every call to that action, in order."""
        return [params for name, params in self.calls if name == action]


# No `anki` fixture here: each test file says which module it patches with a
# `FakeAnki` (see `test_backup.py`, `test_notetypes.py`).


# ── A collection in memory ────────────────────────────────────────────────────
# The generators read a deck through a `known.Known`: a test that wants a
# stocked one hands over a `Held`.

def held_card(card_id=None, *, tags=(), **fields) -> dict:
    """A card as a collection hands it back, fields given as keywords."""
    return {"id": card_id, "fields": dict(fields), "tags": list(tags)}


def as_note(card: dict) -> dict:
    """A card as AnkiConnect hands back its note: what a fake of it answers."""
    return {"noteId": card["id"], "tags": list(card.get("tags") or []),
            "fields": {name: {"value": value} for name, value in card["fields"].items()}}


class Held(Known):
    """A collection in memory: the cards of each note type, and those still
    being learnt when the test says it knows."""

    def __init__(self, cards: dict[str, list[dict]] | None = None, *,
                 learning: dict[str, set] | None = None, reachable: bool = True,
                 live: bool = False) -> None:
        self.by_notetype = cards if cards is not None else {}
        self._learning = learning
        self._reachable = reachable
        self._live = live

    def cards(self, notetype: str) -> list[dict]:
        return list(self.by_notetype.get(notetype, []))

    def learning(self, notetype: str) -> set | None:
        return None if self._learning is None else self._learning.get(notetype, set())

    def reachable(self, notetype: str) -> bool:
        return self._reachable

    def live(self) -> bool:
        return self._live
