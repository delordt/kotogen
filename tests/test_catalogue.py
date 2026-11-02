"""The models served: the OpenRouter catalogue (filtering, sorting, disk cache
and network failures), and the lists Anthropic and OpenAI give a key.

None of these tests touches the network: the answers are faked, and the cache is
diverted to a temporary folder.
"""

from __future__ import annotations

import json
import time
import urllib.error

import pytest

from kotogen import catalogue


def _model(model_id: str, *, prompt="0.000003", completion="0.000015",
           inputs=("text", "file"), outputs=("text",), cache=True, context=200_000):
    """One catalogue entry, in the exact shape of the OpenRouter answer."""
    pricing = {"prompt": prompt, "completion": completion}
    if cache:
        pricing["input_cache_read"] = "0.0000003"
    return {
        "id": model_id,
        "name": model_id.upper(),
        "context_length": context,
        "architecture": {"input_modalities": list(inputs),
                         "output_modalities": list(outputs)},
        "pricing": pricing,
    }


class _FakeResponse:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def cache_in_tmp(monkeypatch, tmp_path):
    """The disk cache of the catalogue never leaves the test's folder."""
    monkeypatch.setattr(catalogue, "cache_dir", lambda: tmp_path)


def serve(monkeypatch, models: list[dict]) -> list[int]:
    """Makes the endpoint answer; returns the counter of network calls."""
    calls: list[int] = []

    def urlopen(req, timeout=None):
        calls.append(1)
        return _FakeResponse({"data": models})

    monkeypatch.setattr(catalogue.urllib.request, "urlopen", urlopen)
    return calls


def fail(monkeypatch, exc: Exception) -> None:
    def urlopen(req, timeout=None):
        raise exc

    monkeypatch.setattr(catalogue.urllib.request, "urlopen", urlopen)


# ── Filtering ─────────────────────────────────────────────────────────────────

def test_only_models_that_every_command_can_use_are_kept(monkeypatch):
    """A model that does not read files would pass the vocabulary and fail on a
    PDF."""
    serve(monkeypatch, [
        _model("good/model"),
        _model("text/only", inputs=("text",)),
        _model("image/output", outputs=("image",)),
    ])
    assert [m["id"] for m in catalogue.load().models] == ["good/model"]


def test_free_models_are_left_out(monkeypatch):
    """The free variants are capped at a few requests a minute, whereas one
    generation chains dozens of them."""
    serve(monkeypatch, [_model("free/model", prompt="0", completion="0"),
                        _model("paid/model")])
    assert [m["id"] for m in catalogue.load().models] == ["paid/model"]


def test_models_are_sorted_by_the_price_of_a_generation(monkeypatch):
    """Sorted on the cost of a typical command, not on the price of the token
    sent: a model that is cheap on input can be the dearest on output."""
    serve(monkeypatch, [
        _model("dear/on-output", prompt="0.0000001", completion="0.001"),
        _model("middling/throughout", prompt="0.000003", completion="0.000015"),
        _model("cheap/one", prompt="0.0000001", completion="0.0000004"),
    ])
    assert [m["id"] for m in catalogue.load().models] == [
        "cheap/one", "middling/throughout", "dear/on-output"]


def test_a_broken_entry_does_not_lose_the_whole_catalogue(monkeypatch):
    """A missing or unreadable field drops its model, not the others."""
    broken = _model("broken/model")
    broken["pricing"]["prompt"] = "free?"
    serve(monkeypatch, [broken, _model("good/model")])
    assert [m["id"] for m in catalogue.load().models] == ["good/model"]


def test_command_cost_uses_both_directions():
    model = {"prompt": 0.000003, "completion": 0.000015}
    expected = (catalogue.REFERENCE_PROMPT_TOKENS * 0.000003
                + catalogue.REFERENCE_COMPLETION_TOKENS * 0.000015)
    assert catalogue.command_cost(model) == pytest.approx(expected)


# ── The disk cache ────────────────────────────────────────────────────────────

def test_second_call_reads_the_cache_instead_of_the_network(monkeypatch):
    calls = serve(monkeypatch, [_model("good/model")])
    catalogue.load()
    catalogue.load()
    assert len(calls) == 1


def test_refresh_asks_again(monkeypatch):
    calls = serve(monkeypatch, [_model("good/model")])
    catalogue.load()
    catalogue.load(refresh=True)
    assert len(calls) == 2


def test_a_stale_cache_is_refreshed(monkeypatch):
    calls = serve(monkeypatch, [_model("good/model")])
    catalogue.load()
    old = json.loads(catalogue.cache_file().read_text(encoding="utf-8"))
    old["fetched"] = time.time() - catalogue.MAX_AGE_SECONDS - 1
    catalogue.cache_file().write_text(json.dumps(old), encoding="utf-8")
    catalogue.load()
    assert len(calls) == 2


def test_a_corrupt_cache_is_treated_as_absent(monkeypatch):
    """A write interrupted by a crash: download again, do not crash."""
    calls = serve(monkeypatch, [_model("good/model")])
    catalogue.cache_file().write_text("{trunca", encoding="utf-8")
    assert catalogue.load().models
    assert len(calls) == 1


# ── No network ────────────────────────────────────────────────────────────────

def test_offline_falls_back_to_the_stale_cache(monkeypatch):
    """Last week's prices still rank the models; the screen says where they
    come from."""
    serve(monkeypatch, [_model("good/model")])
    catalogue.load()
    old = json.loads(catalogue.cache_file().read_text(encoding="utf-8"))
    old["fetched"] = time.time() - catalogue.MAX_AGE_SECONDS - 1
    catalogue.cache_file().write_text(json.dumps(old), encoding="utf-8")

    fail(monkeypatch, urllib.error.URLError("getaddrinfo failed"))
    result = catalogue.load()
    assert [m["id"] for m in result.models] == ["good/model"]
    # A plain reason, not the system's "[WinError 10061]..." message.
    assert result.error == "no answer"


def test_offline_without_cache_returns_nothing_but_never_raises(monkeypatch):
    fail(monkeypatch, urllib.error.URLError("getaddrinfo failed"))
    result = catalogue.load()
    assert result.models == []
    assert result.fetched is None
    assert result.error


def test_an_http_error_is_reported_by_its_code(monkeypatch):
    fail(monkeypatch, urllib.error.HTTPError(
        catalogue.MODELS_URL, 503, "Service Unavailable", {}, None))
    assert "503" in catalogue.load().error


def test_an_unwritable_cache_dir_does_not_break_the_screen(monkeypatch, tmp_path):
    """Disk full or folder read-only: do without the cache."""
    monkeypatch.setattr(catalogue, "cache_dir", lambda: tmp_path / "file" / "subfolder")
    (tmp_path / "file").write_text("I am not a folder", encoding="utf-8")
    serve(monkeypatch, [_model("good/model")])
    assert [m["id"] for m in catalogue.load().models] == ["good/model"]


# ── The lists of Anthropic and OpenAI ─────────────────────────────────────────
# Read to the key, never cached: the answers are faked in the shape of each API.

def _answering(monkeypatch, payload: dict) -> list:
    """Makes the list answer; hands back the requests sent."""
    sent: list = []

    def urlopen(req, timeout=None):
        sent.append(req)
        return _FakeResponse(payload)

    monkeypatch.setattr(catalogue.urllib.request, "urlopen", urlopen)
    return sent


def test_anthropic_lists_its_models_to_the_key_in_its_own_order(monkeypatch):
    sent = _answering(monkeypatch, {"data": [
        {"type": "model", "id": "claude-new", "display_name": "Claude New",
         "created_at": "2026-09-01T00:00:00Z"},
        {"type": "model", "id": "claude-old", "display_name": "Claude Old",
         "created_at": "2025-01-01T00:00:00Z"}], "has_more": False})
    result = catalogue.served("anthropic", "sk-ant-test")
    assert result.models == [{"id": "claude-new", "name": "Claude New"},
                             {"id": "claude-old", "name": "Claude Old"}]
    assert sent[0].get_header("X-api-key") == "sk-ant-test"
    assert sent[0].get_header("Anthropic-version")
    assert not result.error


def test_openai_lists_its_models_newest_first(monkeypatch):
    sent = _answering(monkeypatch, {"object": "list", "data": [
        {"id": "gpt-old", "object": "model", "created": 1_600_000_000, "owned_by": "openai"},
        {"id": "gpt-new", "object": "model", "created": 1_700_000_000, "owned_by": "openai"}]})
    result = catalogue.served("openai", "sk-oa-test")
    assert [m["id"] for m in result.models] == ["gpt-new", "gpt-old"]
    assert sent[0].get_header("Authorization") == "Bearer sk-oa-test"


def test_openai_lists_only_the_models_that_can_chat(monkeypatch):
    """Its list carries every model of the account: one that only embeds, speaks
    or draws would fail the first command run with it."""
    ids = ["chat-large", "text-embedding-big", "voice-tts-hd", "whisper-two",
           "dall-e-four", "omni-moderation-next", "chat-image-one", "chat-audio-mini",
           "chat-realtime-mini", "chat-mini-transcribe", "chat-search-mini", "chat-small"]
    _answering(monkeypatch, {"object": "list", "data": [
        {"id": model, "object": "model", "created": 1_700_000_000 - rank}
        for rank, model in enumerate(ids)]})
    result = catalogue.served("openai", "sk-oa-test")
    assert [m["id"] for m in result.models] == ["chat-large", "chat-small"]


def test_an_id_that_could_not_be_typed_is_left_out(monkeypatch):
    """Chosen, an id goes into the settings file, where a line break in it would
    write a second setting."""
    _answering(monkeypatch, {"object": "list", "data": [
        {"id": "chat-large", "created": 2}, {"id": "chat\nKOTOGEN_X=1", "created": 1},
        {"id": "chat two", "created": 0}]})
    assert [m["id"] for m in catalogue.served("openai", "sk-oa-test").models] == [
        "chat-large"]


def test_openai_leaves_out_the_families_chat_completions_does_not_serve(monkeypatch):
    """`ai_client` calls the Chat Completions API: an older completion model, a
    video model or one served by the Responses API alone would fail its first call."""
    ids = ["chat-large", "chat-instruct", "davinci-three", "babbage-three",
           "sora-two", "computer-use-preview", "chat-codex-mini", "chat-deep-research",
           "chat-large-pro", "chat-small"]
    _answering(monkeypatch, {"object": "list", "data": [
        {"id": model, "object": "model", "created": 1_700_000_000 - rank}
        for rank, model in enumerate(ids)]})
    result = catalogue.served("openai", "sk-oa-test")
    assert [m["id"] for m in result.models] == ["chat-large", "chat-small"]


@pytest.mark.parametrize("code, said", [(401, "anthropic refuses the key"),
                                        (500, "anthropic answered 500")])
def test_a_list_refused_says_why_and_never_raises(monkeypatch, code, said):
    fail(monkeypatch, urllib.error.HTTPError(
        catalogue.SERVED_URLS["anthropic"], code, "", {}, None))
    result = catalogue.served("anthropic", "sk-ant-old")
    assert result.models == [] and result.error == said
