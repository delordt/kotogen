"""The deck of Anki, answering what already exists.

AnkiConnect is replaced: the deck is read as it answers, and the copy kept of
it stands in when Anki is closed.
"""

import argparse

import pytest

from kotogen import memory
from kotogen.anki import connect, deck as anki_deck
from kotogen.exporter import append_cards
from kotogen.generators import vocab


def anki_answers(monkeypatch, *expressions, ids=None):
    """Anki open, holding one vocabulary note per expression."""
    notes = [{"noteId": (ids or range(1, len(expressions) + 1))[i],
              "fields": {"Expression": {"value": e}, "Translation": {"value": "x"}},
              "tags": ["Level::N5"]} for i, e in enumerate(expressions)]
    monkeypatch.setattr(anki_deck, "anki", lambda action, **p: (
        [n["noteId"] for n in notes] if action == "findNotes" else notes))


def anki_closed(monkeypatch):
    def closed(action, **params):
        raise ConnectionError("AnkiConnect unreachable")

    monkeypatch.setattr(anki_deck, "anki", closed)


# ── Reading the deck ──────────────────────────────────────────────────────────

def test_the_notes_are_read_as_cards(monkeypatch):
    anki_answers(monkeypatch, "涼[すず]しい", ids=[1726])
    [card] = anki_deck.DECK.cards("Vocabulary")
    assert card == {"id": 1726, "fields": {"Expression": "涼[すず]しい",
                                           "Translation": "x"},
                    "tags": ["Level::N5"]}


def test_the_words_of_the_deck_are_known(monkeypatch):
    anki_answers(monkeypatch, "涼[すず]しい", "食[た]べる")
    index = anki_deck.DECK.words("Vocabulary")
    assert index.has("涼しい") and index.has("たべる")


def test_an_unknown_notetype_holds_nothing(monkeypatch):
    def boom(action, **params):
        raise RuntimeError("AnkiConnect [findNotes]: model was not found")

    monkeypatch.setattr(anki_deck, "anki", boom)
    assert anki_deck.DECK.cards("Absent") == []


def test_an_empty_deck_holds_nothing(monkeypatch):
    monkeypatch.setattr(anki_deck, "anki", lambda action, **p: [])
    assert anki_deck.DECK.cards("Vocabulary") == []


def test_the_provenances_are_read_by_mode(monkeypatch):
    def anki(action, **params):
        if action == "findNotes":
            return [1] if '"note:Reading"' in params["query"] else []
        return [{"noteId": 1, "fields": {"Source": {"value": "Feed - Ep 7 (p. 3-)"}}}]

    monkeypatch.setattr(anki_deck, "anki", anki)
    found = anki_deck.DECK.sources()
    assert found.knows("reading", "Feed - Ep 7")
    assert not found.knows("audio", "Feed - Ep 7")


@pytest.mark.parametrize("exc", [ConnectionError("Anki closed"),
                                 RuntimeError("model was not found")])
def test_reading_the_deck_never_raises(monkeypatch, exc):
    """Anki closed or notetype absent: nothing comes back, and the filtering
    falls back on the local history alone."""
    def boom(action, **params):
        raise exc

    monkeypatch.setattr(anki_deck, "anki", boom)
    assert not anki_deck.DECK.sources()


# ── What is still being learnt ────────────────────────────────────────────────

def test_the_cards_being_learnt_are_asked_of_anki(monkeypatch):
    asked = []
    monkeypatch.setattr(anki_deck, "anki",
                        lambda action, **p: asked.append(p["query"]) or [3])
    assert anki_deck.DECK.learning("Vocabulary") == {3}
    assert asked == [f'"note:Vocabulary" prop:ivl<{anki_deck.MATURE} -is:new -is:suspended']


def test_with_anki_closed_nobody_can_say(monkeypatch):
    anki_closed(monkeypatch)
    assert anki_deck.DECK.learning("Vocabulary") is None


# ── The copy of the deck ──────────────────────────────────────────────────────

def test_with_anki_closed_the_last_reading_stands_in(monkeypatch, capsys):
    anki_answers(monkeypatch, "涼[すず]しい")
    anki_deck.DECK.words("Vocabulary")
    anki_closed(monkeypatch)
    assert anki_deck.DECK.words("Vocabulary").has("涼しい")
    assert "Anki closed" in capsys.readouterr().out


def test_the_copy_keeps_only_what_a_comparison_reads(monkeypatch):
    anki_answers(monkeypatch, "涼[すず]しい")
    anki_deck.DECK.cards("Vocabulary")
    anki_closed(monkeypatch)
    [card] = anki_deck.DECK.cards("Vocabulary")
    assert set(card["fields"]) == {"Expression"}
    assert card["tags"] == ["Level::N5"]


def test_the_date_of_the_copy_is_said_once(monkeypatch, capsys):
    anki_answers(monkeypatch, "涼[すず]しい")
    anki_deck.DECK.cards("Vocabulary")
    anki_closed(monkeypatch)
    anki_deck.DECK.cards("Vocabulary")
    anki_deck.DECK.cards("Vocabulary")
    assert capsys.readouterr().out.count("Anki closed") == 1


def test_with_no_copy_anki_closed_knows_nothing(monkeypatch):
    anki_closed(monkeypatch)
    assert anki_deck.DECK.cards("Vocabulary") == []


def test_a_new_reading_replaces_the_copy_whole(monkeypatch):
    anki_answers(monkeypatch, "涼[すず]しい")
    anki_deck.DECK.cards("Vocabulary")
    anki_answers(monkeypatch, "暑[あつ]い")
    anki_deck.DECK.cards("Vocabulary")
    anki_closed(monkeypatch)
    index = anki_deck.DECK.words("Vocabulary")
    assert index.has("暑い")
    assert not index.has("涼しい")


def test_the_cards_written_for_the_deck_join_the_copy(monkeypatch, tmp_path):
    anki_answers(monkeypatch, "涼[すず]しい")
    anki_deck.DECK.cards("Vocabulary")
    append_cards(tmp_path / "cards.tsv", [{"Expression": "暑[あつ]い"}],
                 vocab.FIELDS, "Japanese", "Vocabulary")
    anki_closed(monkeypatch)
    index = anki_deck.DECK.words("Vocabulary")
    assert index.has("涼しい")
    assert index.has("暑い")


def test_cards_written_with_no_copy_make_none(monkeypatch, tmp_path):
    """Those cards alone would pass for a deck that holds nothing else."""
    append_cards(tmp_path / "cards.tsv", [{"Expression": "暑[あつ]い"}],
                 vocab.FIELDS, "Japanese", "Vocabulary")
    anki_closed(monkeypatch)
    assert anki_deck.DECK.cards("Vocabulary") == []


def test_a_json_file_does_not_touch_the_copy_of_the_deck(monkeypatch, tmp_path):
    anki_answers(monkeypatch, "涼[すず]しい")
    anki_deck.DECK.cards("Vocabulary")
    append_cards(tmp_path / "set.jsonl", [{"Expression": "暑[あつ]い"}],
                 vocab.FIELDS, "Japanese", "Vocabulary")
    anki_closed(monkeypatch)
    assert not anki_deck.DECK.words("Vocabulary").has("暑い")


def test_a_copy_lets_a_jlpt_source_run_with_anki_closed(monkeypatch):
    monkeypatch.setattr(connect, "status",
                        lambda **k: argparse.Namespace(connected=False))
    assert not anki_deck.DECK.reachable("Vocabulary")
    anki_answers(monkeypatch, "涼[すず]しい")
    anki_deck.DECK.cards("Vocabulary")
    assert anki_deck.DECK.reachable("Vocabulary")


def test_the_provenances_are_kept_for_anki_closed(monkeypatch):
    notes = [{"noteId": 1, "fields": {"Source": {"value": "Feed - Ep 7 (p. 3-)"}}}]
    monkeypatch.setattr(anki_deck, "anki", lambda action, **p: (
        [1] if action == "findNotes" else notes))
    anki_deck.DECK.sources()
    anki_closed(monkeypatch)
    assert anki_deck.Deck().sources().knows("reading", "Feed - Ep 7")


def test_the_deck_keeps_the_history_of_this_machine(tmp_path):
    assert anki_deck.DECK.history(tmp_path / "seen.json") == tmp_path / "seen.json"
    assert memory.known() is anki_deck.DECK
