"""Accounting for the AI calls: tokens and cost really consumed.

The count is kept in the client, which every call goes through.
"""

import io
import json

import pytest

from kotogen import ai_client
from kotogen.ai_client import AIClient, Usage


@pytest.fixture(autouse=True)
def fresh_counters(monkeypatch):
    """Every test starts back from blank counters (they are module globals)."""
    monkeypatch.setattr(ai_client, "_run_usage", Usage())
    monkeypatch.setattr(ai_client, "_session_usage", Usage())
    monkeypatch.setattr(ai_client, "_run_started", None)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    return AIClient(provider="openrouter", model="model/test")


def answering(monkeypatch, payload: dict):
    """Makes urlopen answer with the given payload; gives back the bodies sent."""
    sent: list[dict] = []

    def fake_urlopen(req, timeout=None):
        sent.append(json.loads(req.data.decode("utf-8")))
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr("kotogen.ai_client.urllib.request.urlopen", fake_urlopen)
    return sent


def openrouter_reply(usage: dict | None = None) -> dict:
    payload: dict = {"choices": [{"message": {"content": "ok"}}]}
    if usage is not None:
        payload["usage"] = usage
    return payload


# ── The reading on the OpenRouter side ────────────────────────────────────────

def test_the_cost_is_asked_for_in_the_request(monkeypatch, client):
    """Without `usage.include`, OpenRouter does not price the call."""
    sent = answering(monkeypatch, openrouter_reply())
    client.chat("sys", "user")
    assert sent[0]["usage"] == {"include": True}


def test_tokens_and_cost_add_up(monkeypatch, client):
    answering(monkeypatch, openrouter_reply(
        {"prompt_tokens": 1200, "completion_tokens": 300, "cost": 0.0042}))
    client.chat("sys", "user")
    client.chat("sys", "user")

    usage = ai_client.run_usage()
    assert usage.calls == 2
    assert usage.prompt_tokens == 2400
    assert usage.completion_tokens == 600
    assert usage.total_tokens == 3000
    assert usage.cost == pytest.approx(0.0084)
    assert usage.priced


def test_an_answer_with_no_usage_breaks_nothing(monkeypatch, client):
    """A silent counter must never fail a generation that succeeded."""
    answering(monkeypatch, openrouter_reply())
    assert client.chat("sys", "user") == "ok"
    assert ai_client.run_usage().calls == 0


def test_an_incomplete_usage_counts_what_is_known(monkeypatch, client):
    answering(monkeypatch, openrouter_reply({"prompt_tokens": 500}))
    client.chat("sys", "user")

    usage = ai_client.run_usage()
    assert (usage.prompt_tokens, usage.completion_tokens) == (500, 0)
    assert not usage.priced  # no cost announced: no pretending to know it


# ── The reading on the native SDKs side ───────────────────────────────────────

class FakeUsage:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeResponse:
    def __init__(self, usage=None):
        self.usage = usage


def test_anthropic_usage(monkeypatch):
    ai_client._record_sdk_usage(
        FakeResponse(FakeUsage(input_tokens=800, output_tokens=120)))
    usage = ai_client.run_usage()
    assert (usage.prompt_tokens, usage.completion_tokens) == (800, 120)
    assert not usage.priced  # the SDK does not price


def test_openai_usage(monkeypatch):
    ai_client._record_sdk_usage(
        FakeResponse(FakeUsage(prompt_tokens=640, completion_tokens=90)))
    usage = ai_client.run_usage()
    assert (usage.prompt_tokens, usage.completion_tokens) == (640, 90)


def test_an_sdk_answer_with_no_usage(monkeypatch):
    ai_client._record_sdk_usage(FakeResponse())
    assert ai_client.run_usage().calls == 0


# ── Scopes: one command, and the session ──────────────────────────────────────

def test_reset_does_not_touch_the_session_total():
    ai_client.record_usage(100, 10, 0.001)
    ai_client.reset_run_usage()
    ai_client.record_usage(200, 20, 0.002)

    assert ai_client.run_usage().prompt_tokens == 200
    assert ai_client.session_usage().prompt_tokens == 300
    assert ai_client.session_usage().calls == 2


def test_a_command_knows_the_models_it_set_to_work(monkeypatch):
    """Each once, in order - and the next command starts with none."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    for model in ("model/a", "model/b", "model/a"):
        AIClient(provider="openrouter", model=model)
    assert ai_client.run_models() == ["model/a", "model/b"]
    ai_client.reset_run_usage()
    assert ai_client.run_models() == []


# ── Formatting ────────────────────────────────────────────────────────────────

def test_the_summary_is_empty_with_no_call():
    assert Usage().summary() == ""


def test_the_summary_with_a_cost():
    """The calls and what they cost, and nothing beside them."""
    usage = Usage()
    usage.add(12_000, 3_400, 0.0182)
    assert usage.summary() == "1 AI call ($0.02)"


def test_the_summary_leaves_out_what_it_cannot_be_read_for():
    """No tokens, sent/received split or cache share: they serve for tuning,
    looked at once, not at the end of every command."""
    usage = Usage()
    usage.add(12_000, 3_400, 0.0182, cached=9_000)
    usage.seconds = 74.0
    said = usage.summary()
    assert "tokens" not in said and "sent" not in said and "cache" not in said
    assert said == "1 AI call ($0.02, 1 min 14 s)"


def test_a_summary_with_no_cost_shows_no_price():
    """A "$0.00" would suggest the run had been free."""
    usage = Usage()
    usage.add(1_000, 200, None)
    assert "$" not in usage.summary()


def test_a_tiny_cost_is_not_rounded_to_zero():
    """"$0.00" would read as "free": below half a cent, it is bounded."""
    usage = Usage()
    usage.add(10, 2, 0.000012)
    assert "< $0.01" in usage.summary()


def test_a_cost_above_a_dollar_in_two_decimals():
    usage = Usage()
    usage.add(1_000_000, 200_000, 3.4567)
    assert "$3.46" in usage.summary()


# ── Duration ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seconds, expected", [
    (0.42, "0.4 s"),
    (4.25, "4.2 s"),
    (9.99, "10.0 s"),   # below ten seconds, the decimal stays
    (10.4, "10 s"),
    (59.6, "1 min 00 s"),
    (125.0, "2 min 05 s"),
    (4_320.0, "1 h 12 min"),
])
def test_a_readable_duration(seconds, expected):
    assert ai_client.format_duration(seconds) == expected


def test_the_summary_ends_with_the_duration():
    usage = Usage()
    usage.add(12_000, 3_400, 0.0182)
    usage.seconds = 74.0
    assert usage.summary().endswith("($0.02, 1 min 14 s)")


def test_the_tokens_stand_in_where_nothing_is_priced():
    """The native SDKs give no cost, so the tokens are counted instead, with
    the English thousands separator."""
    usage = Usage()
    usage.add(12_000, 3_400, None)
    assert usage.summary() == "1 AI call (15,400 tokens)"


def test_no_duration_until_the_clock_has_been_stopped():
    """The summary does not claim to know a duration it was never given."""
    usage = Usage()
    usage.add(100, 10, None)
    # No duration, so no segment of the summary ends in " s".
    assert not any(part.strip().endswith(" s")
                   for part in usage.summary().split(","))


def test_the_duration_feeds_the_command_and_the_session(monkeypatch):
    clock = iter([100.0, 103.0])
    monkeypatch.setattr(ai_client.time, "monotonic", lambda: next(clock))
    ai_client.reset_run_usage()
    ai_client.record_usage(100, 10, 0.001)

    assert ai_client.finish_run().seconds == pytest.approx(3.0)
    assert ai_client.session_usage().seconds == pytest.approx(3.0)


def test_the_clock_does_not_count_twice(monkeypatch):
    """A summary redrawn (or never started) does not add any duration."""
    clock = iter([100.0, 102.0])
    monkeypatch.setattr(ai_client.time, "monotonic", lambda: next(clock))
    ai_client.reset_run_usage()
    ai_client.finish_run()

    assert ai_client.finish_run().seconds == pytest.approx(2.0)
    assert ai_client.session_usage().seconds == pytest.approx(2.0)
