"""Sending the cards into Anki: the notes, their media, the names Anki keeps.

AnkiConnect is replaced: what is checked is what the deck is handed, and what
the run says of it.
"""

import argparse
from pathlib import Path

import pytest

from kotogen import memory
from kotogen.anki import connect, deck as anki_deck, media, send
from kotogen.exporter import append_cards, finish

FIELDS = ["Expression", "Translation", "Notes"]


class FakeStatus:
    def __init__(self, connected):
        self.connected = connected


def anki_open(monkeypatch, answer=lambda action, **p: None):
    """Anki open, answering every request with `answer`."""
    monkeypatch.setattr(connect, "status", lambda **k: FakeStatus(True))
    monkeypatch.setattr(send, "anki", answer)
    monkeypatch.setattr(media, "anki", answer)


def args_for(send_it=True, deck="Japanese::Vocabulary", notetype="Vocabulary"):
    return argparse.Namespace(send=send_it, deck=deck, notetype=notetype)


# ── The notes ─────────────────────────────────────────────────────────────────

def test_the_send_builds_the_notes(monkeypatch):
    calls = []
    anki_open(monkeypatch, lambda action, **params: calls.append((action, params))
              or ([1] if action == "addNotes" else None))
    send.send_cards(
        [{"Expression": "水[みず]", "Translation": "Eau", "Tags": "Noun::Nature Level::N5"}],
        FIELDS, "Japanese::Vocabulary", "Vocabulary")

    actions = dict(calls)
    assert actions["createDeck"]["deck"] == "Japanese::Vocabulary"
    note = actions["addNotes"]["notes"][0]
    assert note["modelName"] == "Vocabulary"
    assert note["fields"]["Expression"] == "水[みず]"
    assert note["tags"] == ["Noun::Nature", "Level::N5"]
    assert note["options"]["allowDuplicate"] is False


def test_a_note_says_what_the_file_says(monkeypatch, tmp_path):
    """The same cleaning and furigana: the file and the deck never differ."""
    notes = []
    anki_open(monkeypatch, lambda action, **p: notes.extend(p.get("notes", [])) or [1])
    card = {"Expression": "彼[かれ]は今日[きょう]", "Translation": "<b>un</b>\ndeux"}
    send.send_cards([card], FIELDS, "d", "n")
    path = tmp_path / "out.tsv"
    append_cards(path, [card], FIELDS, "d", "n")
    row = path.read_text(encoding="utf-8").splitlines()[-1].split("\t")
    assert list(notes[0]["fields"].values()) == row[:-1]


def test_a_refused_note_is_a_duplicate_not_a_failure(monkeypatch):
    anki_open(monkeypatch, lambda action, **p: [1, None] if action == "addNotes" else None)
    sent, blocked = send.send_cards([{"Expression": "水[みず]"}] * 2, FIELDS, "d", "n")
    assert sent == (1, 1) and blocked == ""


def test_a_closed_anki_does_not_end_in_an_error(monkeypatch):
    """The cards are already in the file: a failed send is not an error."""
    monkeypatch.setattr(connect, "status", lambda **k: FakeStatus(False))
    sent, blocked = send.send_cards([{"Expression": "水[みず]"}], FIELDS, "d", "n")
    assert sent is None
    assert blocked == "Anki was not connected"


def test_a_failure_during_the_send_is_caught(monkeypatch):
    def boom(action, **params):
        raise RuntimeError("notetype not found")

    anki_open(monkeypatch, boom)
    sent, blocked = send.send_cards([{"Expression": "水[みず]"}], FIELDS, "d", "n")
    assert sent is None
    assert "notetype not found" in blocked


def test_anki_closed_along_the_way_is_said_as_such(monkeypatch):
    def gone(action, **params):
        raise ConnectionError("AnkiConnect unreachable")

    anki_open(monkeypatch, gone)
    assert send.send_cards([{"Expression": "水[みず]"}], FIELDS, "d", "n") == (
        None, "Anki was no longer connected")


# ── The names Anki keeps ──────────────────────────────────────────────────────

def test_the_fields_follow_the_name_that_was_kept():
    cards = [{"ID": "N5_A_01_dead", "Audio": '<audio controls src="N5_A_01_dead.mp3"></audio>',
              "Image": '<img src="N5_A_01_beef.png">', "Question": "何ですか"}]
    send.follow_renames(cards, {"N5_A_01_dead.mp3": "n5_a_01_dead.mp3"})
    assert cards[0]["Audio"] == '<audio controls src="n5_a_01_dead.mp3"></audio>'
    # What was not renamed stays, and so does the ID, the duplicate key.
    assert cards[0]["Image"] == '<img src="N5_A_01_beef.png">'
    assert cards[0]["ID"] == "N5_A_01_dead"


def test_the_media_go_in_before_the_notes(monkeypatch, tmp_path):
    """The media, the fields of the type checked, then the notes."""
    order = []
    answers = {"storeMediaFile": lambda p: p["filename"],
               "modelFieldNames": lambda p: FIELDS}
    anki_open(monkeypatch, lambda action, **p: order.append(action)
              or answers.get(action, lambda p: [1])(p))
    source = tmp_path / "a.mp3"
    source.write_bytes(b"x")
    send.take([{"Expression": "水"}], FIELDS, "d", "n", [source])
    # The folder is asked the name it kept, case included (`media._name_kept`).
    assert order == ["storeMediaFile", "getMediaFilesNames", "modelFieldNames",
                     "createDeck", "addNotes"]


# ── The fields the note type lacks ────────────────────────────────────────────

def _type_with(fields, calls):
    """An Anki whose note type holds `fields`, recording every request."""
    def answer(action, **params):
        calls.append((action, params))
        if action == "modelFieldNames":
            return list(fields)
        return [1] if action == "addNotes" else None
    return answer


def test_a_field_the_type_lacks_is_added_before_the_notes(monkeypatch):
    """AnkiConnect drops the value of a field the type lacks, without an error:
    the field is added first, at its rank, as `deck install` adds it."""
    calls = []
    anki_open(monkeypatch, _type_with(["Expression", "Notes"], calls))
    taken = send.take([{"Expression": "水", "Translation": "Eau"}], FIELDS,
                      "d", "Vocabulary", [])

    assert taken.fields_added == ["Translation"]
    actions = [action for action, _params in calls]
    assert actions.index("modelFieldAdd") < actions.index("addNotes")
    (moved,) = [p for a, p in calls if a == "modelFieldReposition"]
    assert (moved["fieldName"], moved["index"]) == ("Translation", 1)


def test_a_type_that_has_every_field_is_left_alone(monkeypatch):
    calls = []
    anki_open(monkeypatch, _type_with(FIELDS, calls))
    taken = send.take([{"Expression": "水"}], FIELDS, "d", "Vocabulary", [])
    assert taken.fields_added == []
    assert not [a for a, _p in calls if a.startswith("modelField") and a != "modelFieldNames"]


def test_a_type_anki_does_not_have_is_left_to_the_send(monkeypatch):
    """`modelFieldNames` refuses a type that does not exist: nothing is added,
    and the send says what is wrong in its own words."""
    def answer(action, **params):
        if action == "modelFieldNames":
            raise RuntimeError("model was not found: Vocabulary")
        if action == "addNotes":
            raise RuntimeError("model was not found: Vocabulary")
        return None

    anki_open(monkeypatch, answer)
    taken = send.take([{"Expression": "水"}], FIELDS, "d", "Vocabulary", [])
    assert taken.fields_added == [] and taken.sent is None
    assert "model was not found" in taken.blocked


def test_the_closing_block_names_the_field_added_and_the_gesture_left(
        monkeypatch, capsys):
    """A field added is a change made to the collection; the card templates that
    show it are not there until `deck install` lays them down."""
    anki_open(monkeypatch, _type_with(["Expression", "Notes"], []))
    finish([{"Expression": "水[みず]"}], FIELDS, args_for(), Path("out.tsv"), preview=[])
    out = capsys.readouterr().out
    assert ('→ field Translation added to "Vocabulary": `kotogen deck install` '
            "brings its card templates up to date") in out


# ── Through the deck of the run ───────────────────────────────────────────────

def test_the_file_already_written_follows_the_rename(monkeypatch, tmp_path):
    """The row already written carries the earlier name: it is rewritten."""
    tsv = tmp_path / "out.tsv"
    fields = ["Expression", "Audio", "Notes"]   # "Audio" carries HTML, hence the tag
    card = {"Expression": "水", "Audio": '<audio controls src="A_01.mp3"></audio>',
            "Notes": ""}
    append_cards(tsv, [card], fields, "Japanese::Vocabulary", "Vocabulary")
    anki_open(monkeypatch, lambda action, **p: (
        p["filename"].lower() if action == "storeMediaFile" else [1]))
    source = tmp_path / "A_01.mp3"
    source.write_bytes(b"x")
    finish([card], fields, args_for(), tsv, preview=[], media=[source])
    assert 'src="a_01.mp3"' in tsv.read_text(encoding="utf-8")
    assert 'src="A_01.mp3"' not in tsv.read_text(encoding="utf-8")


def test_a_send_makes_the_deck_read_again(monkeypatch):
    """What was read of the deck is stale once the send has changed it."""
    deck = anki_deck.DECK
    deck.sources()
    assert deck._sources is not None
    anki_open(monkeypatch, lambda action, **p: [1] if action == "addNotes" else None)
    finish([{"Expression": "水[みず]"}], FIELDS, args_for(), Path("out.tsv"), preview=[])
    assert deck._sources is None


def test_a_send_that_did_not_happen_keeps_what_was_read(monkeypatch):
    deck = anki_deck.DECK
    deck.sources()
    monkeypatch.setattr(connect, "status", lambda **k: FakeStatus(False))
    finish([{"Expression": "水[みず]"}], FIELDS, args_for(), Path("out.tsv"), preview=[])
    assert deck._sources is not None


def test_the_deck_says_where_media_go_by_hand(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("KOTOGEN_MEDIA_DIR", str(tmp_path / "collection.media"))
    assert memory.known() is anki_deck.DECK
    finish([{"Expression": "水[みず]"}], FIELDS, args_for(send_it=False), Path("out.tsv"),
           preview=[], media=[tmp_path / "a.mp3"], media_label="audio")
    assert f"to copy into {tmp_path / 'collection.media'}:" in capsys.readouterr().out


@pytest.mark.parametrize("taken", [True, False])
def test_the_deck_is_an_outlet_only_for_the_runs_aimed_at_it(tmp_path, taken):
    from kotogen import exporter

    memory.follow(argparse.Namespace(format="tsv" if taken else "json",
                                     output=str(tmp_path / "x.jsonl") if not taken else None),
                  deck=anki_deck.DECK)
    assert (exporter._outlet() is anki_deck.DECK) is taken
