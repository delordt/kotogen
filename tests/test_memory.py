"""Where a run remembers: the deck for Anki, its own file for JSON Lines."""

import argparse

import pytest

from kotogen import memory, seen
from kotogen.anki import connect, deck as anki_deck
from kotogen.exporter import append_cards
from kotogen.generators import reading, vocab
from kotogen.known import JsonlFile, Nothing


def run(**options) -> argparse.Namespace:
    return argparse.Namespace(**({"format": "tsv", "output": None} | options))


def written(path, *expressions, notetype="Vocabulary"):
    """A JSON Lines file holding one vocabulary card per expression."""
    append_cards(path, [{"Expression": e, "Translation": "x"} for e in expressions],
                 vocab.FIELDS, "Japanese", notetype)


@pytest.fixture
def anki_untouchable(monkeypatch):
    """Any question to Anki fails the test: a JSON run has none to ask."""
    def refuse(action, **params):
        raise AssertionError(f"Anki asked {action!r} during a JSON run")

    monkeypatch.setattr(anki_deck, "anki", refuse)
    monkeypatch.setattr(connect, "status", lambda **k: pytest.fail("asked Anki"))


# ── Settling the memory of a run ──────────────────────────────────────────────

def test_a_run_for_anki_remembers_with_the_deck_it_is_handed():
    deck = anki_deck.Deck()
    assert memory.follow(run(format="tsv", output="cards.tsv"), deck=deck) is deck
    assert memory.known() is deck
    assert memory.known().history(seen.FILE) == seen.FILE


def test_a_run_handed_no_deck_remembers_nothing():
    """A program that only wants cards has no deck to remember with."""
    assert isinstance(memory.follow(run(format="tsv")), Nothing)


def test_a_json_run_remembers_with_its_file(tmp_path):
    memory.follow(run(format="json", output=str(tmp_path / "set.jsonl")),
                  deck=anki_deck.Deck())
    assert isinstance(memory.known(), JsonlFile)
    assert memory.known().name("Japanese") == "set.jsonl"
    assert memory.known().history(seen.FILE) == tmp_path / "set.seen.json"


def test_a_json_run_with_no_file_remembers_nothing():
    memory.follow(run(format="json"), deck=anki_deck.Deck())
    assert isinstance(memory.known(), Nothing)
    assert memory.known().history(seen.FILE) is None
    assert memory.known().cards("Vocabulary") == []


def test_a_file_answers_without_anki(tmp_path, anki_untouchable):
    memory.follow(run(format="json", output=str(tmp_path / "absent.jsonl")))
    assert memory.known().reachable("Vocabulary")


# ── Reading the file as a deck ────────────────────────────────────────────────

def test_the_words_of_the_file_are_known_and_not_those_of_the_deck(
        tmp_path, anki_untouchable):
    path = tmp_path / "set.jsonl"
    written(path, "涼[すず]しい")
    memory.follow(run(format="json", output=str(path)))
    index = memory.known().words("Vocabulary")
    assert index.has("涼しい")
    assert not index.has("暑い")


def test_the_provenances_of_the_file_are_its_sources(tmp_path, anki_untouchable):
    path = tmp_path / "set.jsonl"
    append_cards(path, [{"Text": "x", "Source": "Feed - Ep 7 (p. 3-)"}],
                 reading.FIELDS, "Japanese", "Reading")
    memory.follow(run(format="json", output=str(path)))
    found = memory.known().sources()
    assert found.knows("reading", "Feed - Ep 7")
    assert not found.knows("audio", "Feed - Ep 7")


# ── The history of handled sources ────────────────────────────────────────────

def test_a_json_run_keeps_its_history_beside_its_file(tmp_path):
    memory.follow(run(format="json", output=str(tmp_path / "set.jsonl")))
    seen.mark("reading", "nhk", "ne2026", "An article")
    assert (tmp_path / "set.seen.json").exists()
    assert not seen.FILE.exists()
    assert seen.load("reading", "nhk") == {"ne2026": "An article"}


def test_the_history_of_the_deck_is_not_the_one_of_the_file(tmp_path):
    seen.mark("reading", "nhk", "ne2026", "Handled for the deck")
    memory.follow(run(format="json", output=str(tmp_path / "set.jsonl")))
    assert seen.load("reading", "nhk") == {}


def test_a_json_run_with_no_file_writes_no_history():
    memory.follow(run(format="json"))
    seen.mark("reading", "nhk", "ne2026")
    assert not seen.FILE.exists()
    assert seen.load("reading", "nhk") == {}
