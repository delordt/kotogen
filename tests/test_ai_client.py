"""Tests of the AI client: what happens when the service stops answering.

The sensitive point is the sorting of the errors: `HTTPError` is a subclass of
`URLError`, and a refused key caught as a network failure would be retried, the
body that says why lost.
"""

import io
import json
import urllib.error

import pytest

from kotogen.ai_client import AIAuthError, AIClient, AITruncatedError, has_key, store_key


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """The pauses between attempts must not slow the suite down."""
    monkeypatch.setattr("kotogen.ai_client.time.sleep", lambda _: None)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    return AIClient(provider="openrouter", model="model/test")


def http_error(code: int, body: str = "") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://openrouter.ai", code, "error", {}, io.BytesIO(body.encode("utf-8")))


def responding(monkeypatch, *outcomes):
    """Makes urlopen answer according to the given list; counts the calls.

    Each item is either an exception to raise or a text to give back."""
    calls: list[int] = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        outcome = outcomes[min(len(calls) - 1, len(outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        payload = json.dumps({"choices": [{"message": {"content": outcome}}]})
        return io.BytesIO(payload.encode("utf-8"))

    monkeypatch.setattr("kotogen.ai_client.urllib.request.urlopen", fake_urlopen)
    return calls


# ── Definitive errors: stop straight away ─────────────────────────────────────

@pytest.mark.parametrize("code", [401, 402, 403])
def test_auth_errors_stop_at_the_first_try(monkeypatch, client, code):
    calls = responding(monkeypatch, http_error(code))
    with pytest.raises(AIAuthError):
        client.chat("sys", "user")
    assert len(calls) == 1  # no attempt wasted on a certain failure


def test_auth_error_holds_in_one_line(monkeypatch, client):
    """One line: what is blocking, and where to fix it.

    The provider's body ("Missing Authentication header") only restates the code."""
    calls = responding(monkeypatch, http_error(
        401, '{"error": {"message": "Missing Authentication header"}}'))
    with pytest.raises(AIAuthError) as excinfo:
        client.chat("sys", "user")
    message = str(excinfo.value)
    assert "\n" not in message
    assert "OPENROUTER_API_KEY API key refused" in message   # what is blocking
    assert "Settings > API key" in message                   # where to fix it
    assert "Missing Authentication header" not in message
    assert len(calls) == 1


def test_auth_error_names_the_account_when_credits_run_out(monkeypatch, client):
    """402: it is not the key that has to be fixed, but the account."""
    calls = responding(monkeypatch, http_error(
        402, '{"error": {"message": "Insufficient credits"}}'))
    with pytest.raises(AIAuthError) as excinfo:
        client.chat("sys", "user")
    message = str(excinfo.value)
    assert message == "not enough openrouter credit - top the account up."
    assert len(calls) == 1


def test_auth_error_details_come_back_in_debug(monkeypatch, client):
    monkeypatch.setenv("KOTOGEN_DEBUG", "1")
    responding(monkeypatch, http_error(
        401, '{"error": {"message": "Missing Authentication header"}}'))
    with pytest.raises(AIAuthError) as excinfo:
        client.chat("sys", "user")
    assert "Missing Authentication header" in str(excinfo.value)


def test_other_client_errors_are_not_retried(monkeypatch, client):
    """An unknown model or an invalid request does not mend itself on a retry."""
    calls = responding(monkeypatch, http_error(400, "model not found"))
    with pytest.raises(RuntimeError) as excinfo:
        client.chat("sys", "user")
    assert not isinstance(excinfo.value, AIAuthError)
    assert "model not found" in str(excinfo.value)
    assert len(calls) == 1


# ── Transient errors: retry ───────────────────────────────────────────────────

def test_rate_limit_is_retried_then_succeeds(monkeypatch, client):
    calls = responding(monkeypatch, http_error(429), "ok")
    assert client.chat("sys", "user") == "ok"
    assert len(calls) == 2


def test_server_errors_are_retried_up_to_the_limit(monkeypatch, client):
    calls = responding(monkeypatch, http_error(503))
    with pytest.raises(RuntimeError) as excinfo:
        client.chat("sys", "user")
    assert not isinstance(excinfo.value, AIAuthError)
    assert len(calls) == 3
    assert "3 attempts" in str(excinfo.value)


def test_network_errors_are_retried(monkeypatch, client):
    calls = responding(monkeypatch, urllib.error.URLError("network unreachable"), "ok")
    assert client.chat("sys", "user") == "ok"
    assert len(calls) == 2


# ── Answers cut off on the token limit ────────────────────────────────────────
# A truncated answer comes back as HTTP 200: without a check of the stop reason
# it would read as "invalid JSON".

def truncating(monkeypatch, reason="length", key="finish_reason"):
    """Makes urlopen answer with a cut-off JSON and the given stop reason."""
    def fake_urlopen(req, timeout=None):
        payload = json.dumps({"choices": [
            {"message": {"content": '[{"Expression": "食[た]べ'}, key: reason}]})
        return io.BytesIO(payload.encode("utf-8"))

    monkeypatch.setattr("kotogen.ai_client.urllib.request.urlopen", fake_urlopen)


@pytest.mark.parametrize("reason, key", [
    ("length", "finish_reason"),              # OpenAI / OpenRouter
    ("max_tokens", "finish_reason"),          # Anthropic via OpenRouter
    ("MAX_TOKENS", "native_finish_reason"),   # Google, native reason passed through
])
def test_truncated_response_is_named_as_such(monkeypatch, client, reason, key):
    truncating(monkeypatch, reason, key)
    with pytest.raises(AITruncatedError) as excinfo:
        client.chat_json("sys", "user")
    assert "cut off" in str(excinfo.value)
    assert "4096" in str(excinfo.value)  # the limit reached, so as to know what to set


def test_truncated_response_is_still_billed(monkeypatch, client):
    """An answer cut off was paid for: it has to count in the summary."""
    from kotogen.ai_client import Usage, reset_run_usage, run_usage

    reset_run_usage()
    # The session total is a global never reset: patched to spare the tests after.
    monkeypatch.setattr("kotogen.ai_client._session_usage", Usage())

    def fake_urlopen(req, timeout=None):
        payload = json.dumps({
            "choices": [{"message": {"content": "cut"}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 4096, "cost": 0.01},
        })
        return io.BytesIO(payload.encode("utf-8"))

    monkeypatch.setattr("kotogen.ai_client.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(AITruncatedError):
        client.chat("sys", "user")
    assert run_usage().calls == 1
    assert run_usage().total_tokens == 5296


def test_normal_stop_reason_passes_through(monkeypatch, client):
    def fake_urlopen(req, timeout=None):
        payload = json.dumps({"choices": [
            {"message": {"content": "ok"}, "finish_reason": "stop"}]})
        return io.BytesIO(payload.encode("utf-8"))

    monkeypatch.setattr("kotogen.ai_client.urllib.request.urlopen", fake_urlopen)
    assert client.chat("sys", "user") == "ok"


def test_sdk_stop_reasons_are_read_from_either_shape():
    """anthropic carries stop_reason, openai choices[0].finish_reason."""
    from types import SimpleNamespace

    from kotogen.ai_client import _sdk_stop_reason

    assert _sdk_stop_reason(SimpleNamespace(stop_reason="max_tokens")) == "max_tokens"
    openai_like = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="length")], stop_reason=None)
    assert _sdk_stop_reason(openai_like) == "length"
    assert _sdk_stop_reason(SimpleNamespace()) == ""


# ── Caching the system prompt ─────────────────────────────────────────────────
# The system prompt is the same on every batch: caching it saves a lot, but a
# refused cache must never stop a card being generated.

LONG_PROMPT = "detailed instruction. " * 200   # above the caching threshold


@pytest.fixture
def cacheable(monkeypatch):
    """A client on a model that can drive the caching by hand."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    return AIClient(provider="openrouter", model="anthropic/model-a")


def capturing(monkeypatch, *outcomes):
    """Like `responding`, but also holds on to the body sent."""
    bodies: list[dict] = []
    calls: list[int] = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        bodies.append(json.loads(req.data.decode("utf-8")))
        outcome = outcomes[min(len(calls) - 1, len(outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        payload = json.dumps({"choices": [{"message": {"content": outcome}}]})
        return io.BytesIO(payload.encode("utf-8"))

    monkeypatch.setattr("kotogen.ai_client.urllib.request.urlopen", fake_urlopen)
    return bodies


def _system_of(body):
    return body["messages"][0]["content"]


def test_long_prompt_is_marked_for_caching(monkeypatch, cacheable):
    bodies = capturing(monkeypatch, "ok")
    cacheable.chat(LONG_PROMPT, "user")
    blocks = _system_of(bodies[0])
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[0]["text"] == LONG_PROMPT


def test_short_prompt_is_left_alone(monkeypatch, cacheable):
    """Below the threshold the cache does not prime: asking brings nothing."""
    bodies = capturing(monkeypatch, "ok")
    cacheable.chat("short instruction", "user")
    assert _system_of(bodies[0]) == "short instruction"


def test_models_without_manual_caching_are_left_alone(monkeypatch):
    """OpenAI caches by itself and exposes nothing: nothing to ask for."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    other = AIClient(provider="openrouter", model="openai/model-a")
    bodies = capturing(monkeypatch, "ok")
    other.chat(LONG_PROMPT, "user")
    assert _system_of(bodies[0]) == LONG_PROMPT


def test_a_refused_cache_is_retried_without_it(monkeypatch, cacheable, capsys):
    bodies = capturing(monkeypatch, http_error(400, "cache_control not supported"), "ok")
    assert cacheable.chat(LONG_PROMPT, "user") == "ok"

    assert isinstance(_system_of(bodies[0]), list)   # 1st try: cached
    assert _system_of(bodies[1]) == LONG_PROMPT      # 2nd try: bare
    assert "would not keep the instructions" in capsys.readouterr().out


def test_the_cache_is_not_asked_again_after_a_refusal(monkeypatch, cacheable):
    """No round trip lost per batch on a saving known to be impossible."""
    bodies = capturing(monkeypatch, http_error(400, "nope"), "ok", "ok")
    cacheable.chat(LONG_PROMPT, "user")
    cacheable.chat(LONG_PROMPT, "user")
    assert len(bodies) == 3
    assert _system_of(bodies[2]) == LONG_PROMPT


def test_a_real_error_still_surfaces_after_the_cache_retry(monkeypatch, cacheable):
    """A refusal that did not come from the cache must not be swallowed.

    Two instances: an HTTPError's body can be read only once, and the call is
    replayed.
    """
    capturing(monkeypatch,
              http_error(400, "model not found"), http_error(400, "model not found"))
    with pytest.raises(RuntimeError) as excinfo:
        cacheable.chat(LONG_PROMPT, "user")
    assert "model not found" in str(excinfo.value)


def test_a_refusal_the_replay_meets_too_is_not_blamed_on_the_cache(
        monkeypatch, cacheable, capsys):
    """Refused with and without it, the request was not refused over the cache:
    nothing says so, and the next call still asks for it."""
    bodies = capturing(monkeypatch, http_error(400, "context too long"),
                       http_error(400, "context too long"), "ok")
    with pytest.raises(RuntimeError, match="context too long"):
        cacheable.chat(LONG_PROMPT, "user")
    assert "would not keep the instructions" not in capsys.readouterr().out
    cacheable.chat(LONG_PROMPT, "short")
    assert isinstance(_system_of(bodies[2]), list)


def test_an_sdk_refusal_the_replay_meets_too_is_not_blamed_on_the_cache(
        monkeypatch, capsys):
    from types import SimpleNamespace

    class Refused(Exception):
        status_code = 400

    client = AIClient.__new__(AIClient)
    client.provider, client.model, client._cache_ok = "anthropic", "claude-test", True
    sent = []

    def build(system):
        sent.append(system)
        if len(sent) < 3:
            raise Refused("context too long")
        return SimpleNamespace(content=[SimpleNamespace(text="ok")], usage=None,
                               stop_reason="end_turn")

    with pytest.raises(Refused):
        client._sdk_chat(LONG_PROMPT, 4096, build)
    assert isinstance(sent[0], list) and sent[1] == LONG_PROMPT
    assert client._cache_ok
    assert "would not keep the instructions" not in capsys.readouterr().out
    client._sdk_chat(LONG_PROMPT, 4096, build)
    assert isinstance(sent[2], list)


def test_a_refused_cache_never_masks_a_key_problem(monkeypatch, cacheable):
    """402 during a cached call is still a credit problem, not a cache one."""
    capturing(monkeypatch, http_error(402, "no credits"))
    with pytest.raises(AIAuthError):
        cacheable.chat(LONG_PROMPT, "user")


def test_cached_tokens_are_reported(monkeypatch, cacheable):
    from kotogen.ai_client import Usage, reset_run_usage, run_usage

    reset_run_usage()
    monkeypatch.setattr("kotogen.ai_client._session_usage", Usage())

    def fake_urlopen(req, timeout=None):
        payload = json.dumps({
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 3000, "completion_tokens": 500, "cost": 0.001,
                      "prompt_tokens_details": {"cached_tokens": 2400}},
        })
        return io.BytesIO(payload.encode("utf-8"))

    monkeypatch.setattr("kotogen.ai_client.urllib.request.urlopen", fake_urlopen)
    cacheable.chat(LONG_PROMPT, "user")

    usage = run_usage()
    assert usage.cached_tokens == 2400
    assert usage.prompt_tokens == 3000   # a share of those sent, not an extra
    # Counted but not printed: the saving shows in the price on the line.
    assert "cache" not in usage.summary()


def test_anthropic_cache_reads_are_folded_into_the_totals():
    """Anthropic counts cache reads apart: folded back in, the totals compare
    across providers."""
    from types import SimpleNamespace

    from kotogen.ai_client import Usage, _record_sdk_usage, reset_run_usage, run_usage

    reset_run_usage()
    saved = __import__("kotogen.ai_client", fromlist=["x"])._session_usage
    saved_usage = Usage()
    try:
        __import__("kotogen.ai_client", fromlist=["x"])._session_usage = saved_usage
        _record_sdk_usage(SimpleNamespace(usage=SimpleNamespace(
            input_tokens=600, output_tokens=400, cache_read_input_tokens=2400)))
    finally:
        __import__("kotogen.ai_client", fromlist=["x"])._session_usage = saved

    assert run_usage().prompt_tokens == 3000
    assert run_usage().cached_tokens == 2400


def test_anthropic_cache_writes_are_counted_with_the_tokens_sent(monkeypatch):
    """The first call of a cached prompt writes it: those tokens are sent and
    billed, outside `input_tokens`, and are no cache read."""
    from types import SimpleNamespace

    from kotogen import ai_client

    monkeypatch.setattr(ai_client, "_session_usage", ai_client.Usage())
    ai_client.reset_run_usage()
    ai_client._record_sdk_usage(SimpleNamespace(usage=SimpleNamespace(
        input_tokens=600, output_tokens=400, cache_read_input_tokens=0,
        cache_creation_input_tokens=2400)))
    assert ai_client.run_usage().prompt_tokens == 3000
    assert ai_client.run_usage().cached_tokens == 0


def test_an_answer_that_does_not_read_says_so_plainly_on_its_first_line(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    client = AIClient(provider="openrouter", model="publisher/model-a")
    monkeypatch.setattr(client, "chat", lambda system, user: "no braces at all")
    with pytest.raises(ValueError) as error:
        client.chat_json("sys", "user")
    first = str(error.value).splitlines()[0]
    assert first == "The AI's answer was not in the form asked for."


def _openai_ceilings(monkeypatch, model: str) -> list[int]:
    """The `max_completion_tokens` a chat then a PDF send to a faked OpenAI."""
    import sys
    import types
    from types import SimpleNamespace

    sent = []

    class Completions:
        def create(self, **kwargs):
            sent.append(kwargs)
            message = SimpleNamespace(content="ok")
            return SimpleNamespace(usage=None, choices=[
                SimpleNamespace(message=message, finish_reason="stop")])

    fake = types.ModuleType("openai")
    fake.OpenAI = lambda api_key: SimpleNamespace(
        chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setitem(sys.modules, "openai", fake)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = AIClient(provider="openai", model=model)
    assert client.chat("sys", "user") == "ok"
    assert client.chat_pdf("sys", "user", b"%PDF-1.4") == "ok"
    assert len(sent) == 2
    assert all("max_tokens" not in call for call in sent)
    return [call["max_completion_tokens"] for call in sent]


def test_openai_is_given_the_ceiling_every_one_of_its_chat_models_takes(monkeypatch):
    """Chat Completions refuses `max_tokens` from its reasoning models and takes
    `max_completion_tokens` from all of them."""
    assert all(ceiling > 0 for ceiling in _openai_ceilings(monkeypatch, "publisher/model-a"))


@pytest.mark.parametrize("model, chat, pdf", [
    ("o4-mini", 16000, 32000),
    ("gpt-5-mini", 16000, 32000),
    ("gpt-4o", 16000, 16000),
    ("gpt-4-turbo", 4096, 8192),
    ("gpt-3.5-turbo", 4096, 8192),
])
def test_a_reasoning_model_of_openai_has_room_for_its_reasoning(monkeypatch, model,
                                                                 chat, pdf):
    """Its reasoning counts in the ceiling: at 4096 an answer comes back cut, its
    content empty. The oldest families keep theirs, which they cannot exceed."""
    assert _openai_ceilings(monkeypatch, model) == [chat, pdf]

# ── The key ───────────────────────────────────────────────────────────────────

@pytest.fixture
def terminal(monkeypatch):
    """Somebody at the keyboard: the key may be asked for, through `getpass`,
    which the tests stand in for, rather than key by key."""
    monkeypatch.setattr("kotogen.system.can_ask", lambda: True)
    monkeypatch.setattr("kotogen.keyboard.available", lambda: False)


def test_without_a_terminal_a_missing_key_says_where_to_set_it(monkeypatch):
    """`getpass` reads the Windows console whatever the input: a script run with
    `< NUL` would wait for ever on a prompt nobody sees."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": pytest.fail("key asked"))
    monkeypatch.setattr("kotogen.system.can_ask", lambda: False)
    with pytest.raises(SystemExit) as stopped:
        AIClient(provider="openrouter", model="model/test")
    said = str(stopped.value)
    assert "OPENROUTER_API_KEY" in said and "secrets.env" in said
    assert "key key" not in said.lower()


def test_prompted_key_is_kept_for_the_session(monkeypatch, terminal):
    """Otherwise the interactive loop would ask for it on every command."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "sk-or-typed")
    assert not has_key("openrouter")

    AIClient(provider="openrouter", model="model/test")
    assert has_key("openrouter")
    # A second client does not ask again: getpass would fail the test.
    monkeypatch.setattr("getpass.getpass", lambda prompt="": pytest.fail("key asked again"))
    AIClient(provider="openrouter", model="model/test")


def test_store_key_ignores_surrounding_spaces(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    store_key("openrouter", "  sk-or-pasted  ")
    client = AIClient(provider="openrouter", model="model/test")
    assert client._api_key == "sk-or-pasted"


# ── Pulling the JSON out of the answer ────────────────────────────────────────
# Brackets are ambiguous in this project: `涼[すず]しい` carries some, and an
# unfenced object answer starts with `{` long after the first `[`.

def extract(text):
    from kotogen.ai_client import _extract_json
    return _extract_json(text)


def test_a_bare_object_carrying_furigana():
    """The commonest case: a single card, with no ```json fence."""
    assert extract('{"Expression": "涼[すず]しい", "Translation": "Frais"}') == {
        "Expression": "涼[すず]しい", "Translation": "Frais"}


def test_a_bare_array_carrying_furigana():
    cards = extract('[{"Expression": "食[た]べる"}, {"Expression": "飲[の]む"}]')
    assert [c["Expression"] for c in cards] == ["食[た]べる", "飲[の]む"]


def test_an_object_preceded_by_text_and_furigana():
    """A chatty preamble carrying brackets must not divert the parsing."""
    assert extract('Here is the card for 涼[すず]しい:\n{"Translation": "Frais"}') == {
        "Translation": "Frais"}


def test_a_markdown_fence_wins():
    assert extract('blabla\n```json\n{"a": 1}\n```\n') == {"a": 1}


def test_a_brace_inside_a_string():
    """A quoted brace defeats naive depth counting."""
    assert extract('{"Notes": "forme en {c1::…}", "Translation": "Frais"}') == {
        "Notes": "forme en {c1::…}", "Translation": "Frais"}


def test_an_answer_with_no_json():
    with pytest.raises(ValueError):
        extract("I cannot generate this card.")


def test_a_client_with_no_model_stops_before_asking_for_the_key(monkeypatch):
    """None is built in: the command says how to choose one, and asks for
    nothing it could not use."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": pytest.fail("key asked"))
    with pytest.raises(SystemExit) as stop:
        AIClient(provider="openrouter", model="")
    assert "No model chosen for openrouter" in str(stop.value)
    assert "--model" in str(stop.value)
