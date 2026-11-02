"""Tests of the AnkiConnect state, and of where the TSV files are filed."""

import argparse
import json

import pytest

from kotogen import exporter
from kotogen.anki import connect
from kotogen.anki.connect import AnkiStatus


@pytest.fixture(autouse=True)
def no_status_cache(monkeypatch):
    """The state cache must not leak from one test to the next."""
    monkeypatch.setattr(connect, "_status_cache", None)


# ── request() ─────────────────────────────────────────────────────────────────

def test_an_unreachable_anki_is_said_in_one_sentence(monkeypatch):
    """One sentence, the same everywhere: neither the URL nor the OS's message,
    which buries what to do (open Anki)."""
    def boom(*args, **kwargs):
        raise OSError("<urlopen error [WinError 10061] connection refused>")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(ConnectionError) as err:
        connect.request("version")
    assert str(err.value) == connect.UNREACHABLE
    assert "WinError" not in str(err.value)
    assert connect.ANKICONNECT_URL not in str(err.value)
    # The detail stays the cause of the exception, shown with `KOTOGEN_DEBUG=1`.
    assert "WinError" in str(err.value.__cause__)



def fake_urlopen(monkeypatch, answer: dict) -> list:
    """Replaces urlopen: holds on to (url, body sent) and gives back `answer`."""
    sent: list = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def read(self): return json.dumps(answer).encode()

    def urlopen(req, timeout=None):
        sent.append((req.full_url, json.loads(req.data)))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    return sent


def test_the_default_address_is_the_local_addon(monkeypatch):
    sent = fake_urlopen(monkeypatch, {"result": 6, "error": None})
    connect.request("version")
    assert sent[0][0] == "http://127.0.0.1:8765"


def test_a_moved_addon_is_reachable_through_the_env(monkeypatch):
    """The add-on's port is configurable (webBindPort): 8765 may be taken."""
    monkeypatch.setenv("KOTOGEN_ANKICONNECT_URL", "http://127.0.0.1:8766")
    sent = fake_urlopen(monkeypatch, {"result": 6, "error": None})
    connect.request("version")
    assert sent[0][0] == "http://127.0.0.1:8766"


def test_the_scheme_may_be_left_out(monkeypatch):
    """"127.0.0.1:8766" is what one writes; urllib refuses a URL with no scheme,
    which would read as a closed Anki."""
    monkeypatch.setenv("KOTOGEN_ANKICONNECT_URL", "127.0.0.1:8766")
    sent = fake_urlopen(monkeypatch, {"result": 6, "error": None})
    connect.request("version")
    assert sent[0][0] == "http://127.0.0.1:8766"


def test_no_key_is_sent_when_none_is_configured(monkeypatch):
    sent = fake_urlopen(monkeypatch, {"result": 6, "error": None})
    connect.request("version")
    assert "key" not in sent[0][1]


def test_the_key_travels_with_every_request(monkeypatch):
    monkeypatch.setenv("KOTOGEN_ANKICONNECT_KEY", "secret")
    sent = fake_urlopen(monkeypatch, {"result": 6, "error": None})
    connect.request("version")
    assert sent[0][1]["key"] == "secret"


def test_a_refused_key_is_not_said_in_the_words_of_the_action(monkeypatch):
    """The add-on refuses a key alike on every action: naming the action would
    point at the send, which has nothing to do with it."""
    fake_urlopen(monkeypatch, {"error": "valid api key must be provided"})
    with pytest.raises(RuntimeError) as err:
        connect.request("addNotes")
    assert str(err.value) == connect.BAD_KEY
    assert "addNotes" not in str(err.value)


def test_an_open_editor_is_said_once_in_one_sentence(monkeypatch):
    """Anki refuses a flag or a note type while any editing window is open: the
    sentence names the window to close, not the action, and every later write
    fails alike, so it is not one card's failure."""
    fake_urlopen(monkeypatch, {"error": "Close the affected editor before this API "
                                        "write, even if its content is saved."})
    with pytest.raises(connect.EditorOpen) as err:
        connect.request("setSpecificValueOfCard")
    assert str(err.value) == connect.EDITOR_OPEN
    assert "setSpecificValueOfCard" not in str(err.value)
    # Still a RuntimeError, for callers that catch only that.
    assert isinstance(err.value, RuntimeError)


def test_a_refused_action_still_names_it(monkeypatch):
    fake_urlopen(monkeypatch, {"error": "model was not found: Vocabulary"})
    with pytest.raises(RuntimeError) as err:
        connect.request("addNotes")
    assert "addNotes" in str(err.value)
    assert "Vocabulary" in str(err.value)


def test_a_refused_key_is_not_a_closed_anki(monkeypatch):
    """Anki is open and answers: "not connected" would have it restarted for
    nothing."""
    fake_urlopen(monkeypatch, {"error": "valid api key must be provided"})
    state = connect.status(refresh=True)
    assert state == AnkiStatus(connected=False, key_refused=True)


# ── status() ──────────────────────────────────────────────────────────────────

def fake_requests(monkeypatch, answers: dict) -> list[str]:
    """Replaces request(): gives back answers[action], or raises if absent."""
    calls: list[str] = []

    def request(action, *, timeout=60, **params):
        calls.append(action)
        if action not in answers:
            raise ConnectionError("unreachable")
        return answers[action]

    monkeypatch.setattr(connect, "request", request)
    return calls


def test_status_when_anki_is_closed(monkeypatch):
    calls = fake_requests(monkeypatch, {})
    state = connect.status()
    assert state == AnkiStatus(connected=False)
    assert calls == ["version"]  # nothing else is attempted


def test_status_lists_decks_and_notetypes(monkeypatch):
    fake_requests(monkeypatch, {
        "version": 6,
        "getActiveProfile": "User 1",
        "deckNames": ["Japanese::Vocabulary"],
        "modelNames": ["Vocabulary", "Listening"],
    })
    state = connect.status()
    assert state.connected and state.profile == "User 1"
    assert state.decks == frozenset({"Japanese::Vocabulary"})
    assert state.notetypes == frozenset({"Vocabulary", "Listening"})


def test_status_survives_an_unsupported_action(monkeypatch):
    # getActiveProfile absent from an old version of the add-on: an empty
    # profile, and the rest of the state stays usable
    fake_requests(monkeypatch, {"version": 6, "deckNames": [], "modelNames": []})
    state = connect.status()
    assert state.connected and state.profile == ""


def test_status_is_cached_then_refreshed(monkeypatch):
    calls = fake_requests(monkeypatch, {"version": 6, "deckNames": [], "modelNames": []})
    connect.status()
    connect.status()  # served from the cache
    assert calls.count("version") == 1
    connect.status(refresh=True)
    assert calls.count("version") == 2


# ── Where the TSV is filed ────────────────────────────────────────────────────

def run_args(output=None, send=False):
    """The arguments of a generator run, as far as the file of the run cares."""
    return argparse.Namespace(output=output, send=send)


def test_tsv_goes_to_the_cache_when_sending(monkeypatch, tmp_path):
    monkeypatch.delenv("KOTOGEN_OUTPUT_DIR", raising=False)
    monkeypatch.setattr(exporter, "_cache_output_dir", lambda: tmp_path / "cache")
    path = exporter.resolve_output_path(run_args(send=True), "vocab")
    assert path.parent == tmp_path / "cache"


def test_the_cache_beats_the_output_dir_env(monkeypatch, tmp_path):
    """A direct send: nothing lands in the folder chosen for the imports."""
    monkeypatch.setenv("KOTOGEN_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(exporter, "_cache_output_dir", lambda: tmp_path / "cache")
    path = exporter.resolve_output_path(run_args(send=True), "vocab")
    assert path.parent == tmp_path / "cache"


def test_explicit_output_is_untouched(tmp_path):
    target = tmp_path / "cards.tsv"
    assert exporter.resolve_output_path(run_args(str(target), send=True), "vocab") == target
