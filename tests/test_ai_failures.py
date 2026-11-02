"""How the generation loops behave when the AI gives up along the way.

A one-off failure (wobbly JSON, a cut connection) skips the item and carries on,
keeping the TSV already written. A definitive failure (key, quota) stops
everything rather than replay a certain failure, retries and pauses included, on
every batch.
"""

import argparse

import pytest

from kotogen.ai_client import AIAuthError, AITruncatedError
from kotogen.generators import vocab


@pytest.fixture(params=[1, 4], ids=["sequential", "parallel"])
def args(request):
    """Each scenario runs sequentially and in parallel, to the same result."""
    return argparse.Namespace(batch_size=1, jobs=request.param,
                              deck="Deck", notetype="Type")


@pytest.fixture
def saved(monkeypatch):
    """Neutralises the disk write, holding on to what would have been saved."""
    batches: list[list[dict]] = []
    monkeypatch.setattr(vocab, "append_cards",
                        lambda path, cards, *a, **k: batches.append(cards))
    monkeypatch.setattr(vocab, "_review_single_kanji", lambda client, cards: (cards, []))
    return batches


ENTRIES = ["一", "二", "三"]


def generating(monkeypatch, outcomes, entries=ENTRIES):
    """`_generate_cards` follows the list: an exception to raise, or a word to
    give back.

    Outcomes are keyed by entry, not drawn from an iterator: parallel batches
    call in any order.
    """
    plan = dict(zip(entries, outcomes))

    def fake(client, batch, system=None):
        outcome = plan[batch[0]]
        if isinstance(outcome, Exception):
            raise outcome
        return [{"Expression": outcome, "Translation": "translation", "Reading": "よみ"}]

    monkeypatch.setattr(vocab, "_generate_cards", fake)


def test_transient_failure_skips_the_batch_and_keeps_going(monkeypatch, args, saved, capsys):
    generating(monkeypatch, ["一", ValueError("invalid JSON"), "三"])
    cards, _ = vocab._process_entries(None, list(ENTRIES), args, DummyPath(), set())
    assert [c["Expression"] for c in cards] == ["一", "三"]
    assert len(saved) == 2                       # both successful batches are on disk
    assert "batch 2" in capsys.readouterr().err


def test_fatal_failure_stops_the_run_but_keeps_what_was_saved(monkeypatch, args, saved):
    generating(monkeypatch, ["一", AIAuthError("key refused"), "three"])
    with pytest.raises(AIAuthError):
        vocab._process_entries(None, list(ENTRIES), args, DummyPath(), set())
    assert len(saved) == 1                       # the first batch is kept
    assert saved[0][0]["Expression"] == "一"


# ── Generating the batches in parallel ────────────────────────────────────────
# The calls go out together, but the results are gathered in batch order: the
# deduplication across batches, the lone-kanji question and the TSV depend on it.

def test_results_keep_the_batch_order_whatever_the_arrival_order(monkeypatch, saved):
    """The slowest batch is the first one: its cards must stay at the head."""
    import time

    def fake(client, batch, system=None):
        delay = {"一": 0.05, "二": 0.02, "三": 0.0}[batch[0]]
        time.sleep(delay)
        return [{"Expression": batch[0], "Translation": "translation"}]

    monkeypatch.setattr(vocab, "_generate_cards", fake)
    args = argparse.Namespace(batch_size=1, jobs=3, deck="Deck", notetype="Type")
    cards, _ = vocab._process_entries(None, list(ENTRIES), args, DummyPath(), set())

    assert [c["Expression"] for c in cards] == ENTRIES
    assert [b[0]["Expression"] for b in saved] == ENTRIES  # the TSV too


def test_batches_really_do_overlap(monkeypatch, saved):
    """Each call waits for another to start: a loaded machine outlasts any sleep.

    Should the calls never overlap, each wait gives up after five seconds.
    """
    import threading

    running = 0
    peak = 0
    lock = threading.Lock()
    overlapped = threading.Event()

    def fake(client, batch, system=None):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
            if running > 1:
                overlapped.set()
        overlapped.wait(timeout=5)
        with lock:
            running -= 1
        return [{"Expression": batch[0], "Translation": "translation"}]

    monkeypatch.setattr(vocab, "_generate_cards", fake)
    args = argparse.Namespace(batch_size=1, jobs=3, deck="Deck", notetype="Type")
    vocab._process_entries(None, list(ENTRIES), args, DummyPath(), set())
    assert peak > 1


def test_jobs_1_keeps_the_calls_one_at_a_time(monkeypatch, saved):
    """--jobs 1 must really serialise (a tight rate limit, debugging)."""
    import threading
    import time

    running = 0
    peak = 0
    lock = threading.Lock()

    def fake(client, batch, system=None):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.02)
        with lock:
            running -= 1
        return [{"Expression": batch[0], "Translation": "translation"}]

    monkeypatch.setattr(vocab, "_generate_cards", fake)
    args = argparse.Namespace(batch_size=1, jobs=1, deck="Deck", notetype="Type")
    vocab._process_entries(None, list(ENTRIES), args, DummyPath(), set())
    assert peak == 1


def test_dedup_between_batches_is_unaffected_by_parallelism(monkeypatch, saved):
    """Two batches give back the same word: the first batch still wins."""
    def fake(client, batch, system=None):
        return [{"Expression": "同[おな]じ", "Translation": f"from {batch[0]}"}]

    monkeypatch.setattr(vocab, "_generate_cards", fake)
    args = argparse.Namespace(batch_size=1, jobs=3, deck="Deck", notetype="Type")
    cards, skipped = vocab._process_entries(None, list(ENTRIES), args, DummyPath(), set())

    assert len(cards) == 1
    assert cards[0]["Translation"] == "from 一"   # batch 1, not the fastest one
    assert len(skipped) == 2


# ── A truncated answer: the batch is cut in two, not thrown away ──────────────
# Replaying the whole batch would pay for the same cut again; half of it fits.

def test_truncated_batch_is_split_in_two(monkeypatch, capsys):
    """A batch of 4 that overflows still produces its 4 cards."""
    seen: list[list[str]] = []

    def fake(client, batch, system=None):
        seen.append(list(batch))
        if len(batch) > 2:
            raise AITruncatedError("answer cut off")
        return [{"Expression": w, "Translation": "translation"} for w in batch]

    monkeypatch.setattr(vocab, "_generate_cards", fake)
    cards = vocab._generate_batch(None, ["一", "二", "三", "四"], "batch 1")

    assert [c["Expression"] for c in cards] == ["一", "二", "三", "四"]
    assert seen == [["一", "二", "三", "四"], ["一", "二"], ["三", "四"]]
    assert "replayed in two" in capsys.readouterr().out


def test_split_recurses_until_it_fits(monkeypatch):
    def fake(client, batch, system=None):
        if len(batch) > 1:
            raise AITruncatedError("answer cut off")
        return [{"Expression": batch[0], "Translation": "translation"}]

    monkeypatch.setattr(vocab, "_generate_cards", fake)
    cards = vocab._generate_batch(None, ["一", "二", "三", "四"], "batch 1")
    assert [c["Expression"] for c in cards] == ["一", "二", "三", "四"]


def test_a_single_entry_that_still_overflows_gives_up(monkeypatch):
    """Nothing left to cut: the error goes up instead of looping."""
    def always_truncates(client, batch, system=None):
        raise AITruncatedError("cut off")

    monkeypatch.setattr(vocab, "_generate_cards", always_truncates)
    with pytest.raises(AITruncatedError):
        vocab._generate_batch(None, ["一"], "batch 1")


def test_one_failing_half_does_not_lose_the_other(monkeypatch, capsys):
    def fake(client, batch, system=None):
        if len(batch) > 1:
            raise AITruncatedError("answer cut off")
        if batch[0] == "二":
            raise ValueError("invalid JSON")
        return [{"Expression": batch[0], "Translation": "translation"}]

    monkeypatch.setattr(vocab, "_generate_cards", fake)
    cards = vocab._generate_batch(None, ["一", "二"], "batch 1")
    assert [c["Expression"] for c in cards] == ["一"]
    assert "half dropped" in capsys.readouterr().err


def test_split_stops_on_a_fatal_error(monkeypatch):
    """Key refused during the splitting: no point trying the next half."""
    calls: list[int] = []

    def fake(client, batch, system=None):
        calls.append(len(batch))
        if len(batch) > 1:
            raise AITruncatedError("answer cut off")
        raise AIAuthError("key refused")

    monkeypatch.setattr(vocab, "_generate_cards", fake)
    with pytest.raises(AIAuthError):
        vocab._generate_batch(None, ["一", "二"], "batch 1")
    assert calls == [2, 1]  # the second half was not attempted


class DummyPath:
    """A dummy output path: only its `.name` is displayed."""
    name = "output.tsv"
