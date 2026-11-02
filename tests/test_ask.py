"""`kotogen ask`: what its tools refuse, and what the net guarantees.

AnkiConnect and the model are faked; everything between them runs: the fence
around the scope, the furigana pass on the way in, the confirmation, the snapshot
at the first accepted write. Each is pinned on its own, as a happy path would
pass with any two of them working.
"""

from __future__ import annotations

import json
import re
import sys

import pytest

from conftest import FakeAnki, anki_note
from kotogen import console
from kotogen.ai_client import Reply, ToolCall
from kotogen.anki import ask
from kotogen.anki.ask import Session

NOTETYPES = {"Vocabulary": "Japanese::Vocabulary", "Grammar": "Japanese::Grammar"}


@pytest.fixture
def deck(monkeypatch):
    """A deck of three notes, one of them outside the scope."""
    fake = FakeAnki(
        anki_note(1, "Vocabulary", Expression="食[た]べる", Translation="To eat",
                  Example="", ExampleTranslation="", tags=["N4"]),
        anki_note(2, "Vocabulary", Expression="猫[ねこ]", Translation="Cat",
                  Example="", ExampleTranslation="", tags=["N5", "N4"]),
        anki_note(3, "Cooking", Expression="a card of another deck",
                  Translation="not ours"),
    )
    monkeypatch.setattr(ask, "anki", fake)
    return fake


@pytest.fixture
def session():
    return Session(notetypes=dict(NOTETYPES), auto=True)


@pytest.fixture(autouse=True)
def no_backup(monkeypatch):
    """The net answers yes without touching the disk, unless a test says otherwise."""
    monkeypatch.setattr(ask, "_net", lambda session: True)


def run(session, name, **arguments):
    """One tool call, as the loop makes it: the arguments arrive as JSON text."""
    return ask.run_tool(session, name, json.dumps(arguments))


# -- The scope ----------------------------------------------------------------

def test_a_search_is_held_inside_the_scope(deck, session):
    """The model's query goes INSIDE the fence, never beside it.

    Beside it, an `or` would spill out at the first term, to notes the snapshot
    does not cover.
    """
    run(session, "search_notes", query="tag:N4 or tag:N5")
    query = deck.params_for("findNotes")[0]["query"]
    assert query.startswith('("note:Vocabulary" OR "note:Grammar")')
    assert query.endswith("(tag:N4 or tag:N5)")


def test_a_note_outside_the_scope_cannot_be_read(deck, session):
    answer, _line = run(session, "read_notes", note_ids=[1, 3])
    assert [note["note_id"] for note in answer["notes"]] == [1]
    assert answer["out_of_scope"] == [3]


def test_a_note_outside_the_scope_cannot_be_written(deck, session):
    """An id can reach a write tool without a search, from the model's memory of
    an earlier run."""
    answer, _line = run(session, "edit_note", note_id=3,
                        fields={"Translation": "rewritten"})
    assert answer["applied"] is False
    assert not deck.params_for("updateNoteFields")


def test_an_empty_search_is_answered_not_run(deck, session):
    answer, _line = run(session, "search_notes", query="   ")
    assert "error" in answer
    assert not deck.params_for("findNotes")


@pytest.mark.parametrize("query, nested", [
    ("tag:N4 or tag:N5", True),
    ("(tag:N4 or tag:N5) -is:suspended", True),
    ('"Translation:*(*"', True),
    (r"Expression:\(", True),
    ("x) OR (deck:*", False),
    ("(tag:N4", False),
    ('"unclosed', False),
])
def test_a_query_closes_what_it_opens(query, nested):
    """A bracket inside quotes, or after a backslash, is text to Anki."""
    assert ask._nested(query) is nested


def test_a_query_cannot_close_the_fence(deck, session):
    """`x) OR (deck:*` balances its own brackets and still ends the fence at its
    first character: what follows the OR would search the whole collection."""
    answer, _line = run(session, "search_notes", query="x) OR (deck:*")
    assert "error" in answer
    assert not deck.params_for("findNotes")


def test_a_search_lists_no_note_outside_the_scope(deck, session):
    """Checked again on the way out, as the writes are: whatever Anki answers,
    a label of another deck is not read to the model."""
    answer, _line = run(session, "search_notes", query="tag:N4")
    assert [note["note_id"] for note in answer["notes"]] == [1, 2]


# -- What is written ----------------------------------------------------------

def test_the_japanese_written_is_normalised_before_being_stored(deck, session):
    """The AI writes the Japanese it knows; the spacing is not its job."""
    run(session, "edit_note", note_id=1,
        fields={"Example": "毎朝[まいあさ]魚[さかな]を食[た]べます。"})
    written = deck.params_for("updateNoteFields")[0]["note"]["fields"]["Example"]
    assert written == "毎朝[まいあさ] 魚[さかな]を 食[た]べます。"


def test_a_field_with_a_media_tag_is_left_whole(deck, session):
    """`[sound:…]` is a filename, not a sentence to de-space."""
    tag = "[sound:rec 01.mp3]"
    run(session, "edit_note", note_id=1, fields={"Example": tag})
    assert deck.params_for("updateNoteFields")[0]["note"]["fields"]["Example"] == tag


@pytest.mark.parametrize("notetype, name, value", [
    ("Grammar", "Answer", "降ったら"),
    ("Grammar", "Target", "雨の場合"),
    ("Vocabulary", "Context", "目上の人に"),
    ("Kanji", "Composition", "木 + 木 - two trees"),
])
def test_a_field_the_export_writes_plain_is_stored_as_written(deck, notetype, name, value):
    """The rule of the export, note type by note type (`exporter.plain_field`):
    a reading laid on a grammar `Answer` would have to be typed too."""
    deck.notes[4] = anki_note(4, notetype, **{name: ""})
    session = Session(notetypes={notetype: "Japanese::Deck"}, auto=True)
    run(session, "edit_note", note_id=4, fields={name: value})
    assert deck.params_for("updateNoteFields")[0]["note"]["fields"] == {name: value}


def test_the_answer_of_a_reading_card_gets_its_readings(deck):
    """The same field, another rule: the answer of a reading card is shown among
    decoys that carry theirs."""
    deck.notes[4] = anki_note(4, "Reading", Answer="")
    session = Session(notetypes={"Reading": "Japanese::Reading"}, auto=True)
    run(session, "edit_note", note_id=4, fields={"Answer": "駅で待ちます"})
    written = deck.params_for("updateNoteFields")[0]["note"]["fields"]["Answer"]
    assert "駅[えき]" in written


def test_what_the_model_writes_is_stored_as_text(deck, session):
    """A note can carry an instruction planted in its source page, and the model
    may follow it: what it writes reaches the card as text, an open tag included."""
    run(session, "edit_note", note_id=1,
        fields={"Translation": "To eat <img src=x onerror=alert(1) "})
    written = deck.params_for("updateNoteFields")[0]["note"]["fields"]["Translation"]
    assert "<" not in written
    assert written.startswith("To eat &lt;img")


def test_a_media_field_can_be_emptied_but_not_written(deck, session):
    """The player is built by the program, from the file it put down."""
    deck.notes[1]["fields"]["Audio"] = {"value": '<audio controls src="a.mp3"></audio>',
                                        "order": 9}
    run(session, "edit_note", note_id=1,
        fields={"Audio": '<img src=x onerror="alert(1)">'})
    assert not deck.params_for("updateNoteFields")

    run(session, "edit_note", note_id=1, fields={"Audio": ""})
    assert deck.params_for("updateNoteFields")[0]["note"]["fields"] == {"Audio": ""}


def test_an_old_note_is_not_changed_by_its_escaping(deck, session):
    """A note written before the fields were escaped holds a bare `"`: the
    model's copy of it says the same, and is no change."""
    deck.notes[1]["fields"]["Translation"]["value"] = 'To "eat"'
    answer, _line = run(session, "edit_note", note_id=1,
                        fields={"Translation": 'To "eat"'})
    assert answer["applied"] is False


def test_a_tag_cannot_end_the_string_the_templates_read_it_in(deck, session):
    """The templates read `{{Tags}}` between backquotes."""
    run(session, "tag_notes", note_ids=[1], add_tags=["Level::N3`${alert(1)}`"])
    assert deck.params_for("addTags")[0]["tags"] == "Level::N3{alert(1)}"


def test_a_field_the_note_type_has_not_is_dropped(deck, session):
    """`updateNoteFields` would take it in silence and put it nowhere visible."""
    run(session, "edit_note", note_id=1,
        fields={"Translation": "To eat something", "Invented": "x"})
    assert deck.params_for("updateNoteFields")[0]["note"]["fields"] == {
        "Translation": "To eat something"}


def test_writing_what_the_note_already_says_changes_nothing(deck, session):
    answer, _line = run(session, "edit_note", note_id=1,
                        fields={"Translation": "To eat"})
    assert answer["applied"] is False
    assert not deck.params_for("updateNoteFields")


def test_a_tag_already_there_is_not_laid_again(deck, session):
    answer, _line = run(session, "edit_note", note_id=1, add_tags=["N4"])
    assert answer["applied"] is False
    assert not deck.params_for("addTags")


def test_tagging_a_batch_is_one_call_for_every_note(deck, session):
    run(session, "tag_notes", note_ids=[1, 2], add_tags=["Cooking"],
        remove_tags=["N4"])
    assert deck.params_for("addTags")[0] == {"notes": [1, 2], "tags": "Cooking"}
    assert deck.params_for("removeTags")[0] == {"notes": [1, 2], "tags": "N4"}


# -- What refuses to be written -----------------------------------------------

def test_scan_does_not_declare_the_writing_tools():
    """Not declared rather than refused: the model spends a paid turn on any tool
    it can see."""
    declared = {tool["function"]["name"] for tool in ask.write_tools()}
    assert declared == ask.WRITE_NAMES
    assert not declared & {tool["function"]["name"]
                           for tool in ask.read_tools()}


def test_a_writing_tool_called_under_scan_is_refused(deck, session):
    session.scan = True
    answer, _line = run(session, "edit_note", note_id=1,
                        fields={"Translation": "x"})
    assert "--scan" in answer["error"]
    assert not deck.params_for("updateNoteFields")


def test_yes_never_answers_a_deletion(deck, session, monkeypatch):
    """No command deletes a note without the user, and `ask` is no exception."""
    asked = []
    monkeypatch.setattr(ask, "ask_choice",
                        lambda *a, **k: asked.append(a) or "n")
    answer, _line = run(session, "delete_notes", note_ids=[1], reason="no place")
    assert asked, "a deletion was applied without asking, under --yes"
    assert answer["applied"] is False
    assert not deck.params_for("deleteNotes")


def test_a_deletion_the_user_accepts_goes_through(deck, session, monkeypatch):
    monkeypatch.setattr(ask, "ask_choice", lambda *a, **k: "y")
    run(session, "delete_notes", note_ids=[1, 2], reason="no place")
    assert deck.params_for("deleteNotes")[0] == {"notes": [1, 2]}
    assert session.deleted == 2


def test_a_refused_write_is_counted_and_told_to_the_model(deck, session, monkeypatch):
    """A refusal is the user's answer, not an error: told so, the model does not
    propose the same write again."""
    session.auto = False
    monkeypatch.setattr(ask, "ask_choice", lambda *a, **k: "n")
    answer, _line = run(session, "edit_note", note_id=1, fields={"Example": "犬[いぬ]"})
    assert answer["applied"] is False
    assert session.refused == 1
    assert not deck.params_for("updateNoteFields")


def test_a_flag_is_read_off_the_card_and_not_off_the_note(deck, session, monkeypatch):
    """The decision comes from `cardsInfo`, where a flag actually lives.

    A flag sits on one card of a note: taken off the note's card list, its cards
    with no flag would be counted as cleared, which Anki accepts silently.
    """
    cleared: list[int] = []
    monkeypatch.setattr("kotogen.anki.maintain.marks.clear_flag", cleared.append)

    answer, _line = run(session, "clear_flag", note_ids=[1, 2])
    assert answer["applied"] is True
    assert cleared == [10, 20]
    assert deck.params_for("cardsInfo"), "the flags were read off the notes"


def test_notes_whose_cards_carry_no_flag_are_left_alone(deck, session, monkeypatch):
    def unflagged(action, **params):
        if action == "cardsInfo":
            return [{"cardId": card, "note": card // 10, "flags": 0}
                    for card in params["cards"]]
        return deck(action, **params)

    monkeypatch.setattr(ask, "anki", unflagged)
    monkeypatch.setattr("kotogen.anki.maintain.marks.clear_flag",
                        lambda card_id: pytest.fail("a card with no flag was cleared"))
    answer, _line = run(session, "clear_flag", note_ids=[1, 2])
    assert answer["applied"] is False


def _cards(ords: dict[int, int], flags: dict[int, int] | None = None):
    """A `cardsInfo` that knows the rank of each card in its note and its flag."""
    def cards_info(deck):
        def answer(action, **params):
            if action == "cardsInfo":
                return [{"cardId": card, "ord": ords.get(card, 0),
                         "flags": (flags or {}).get(card, 0)} for card in params["cards"]]
            return deck(action, **params)
        return answer
    return cards_info


def test_a_flag_is_laid_on_the_first_card_of_each_note(deck, session, monkeypatch):
    """`maintain` handles every card flagged: both cards of one note would be
    reworked, and paid for, twice."""
    deck.notes[2]["cards"] = [21, 20]
    monkeypatch.setattr(ask, "anki", _cards({20: 0, 21: 1})(deck))
    laid: list[tuple[int, int]] = []
    monkeypatch.setattr("kotogen.anki.maintain.marks.set_flag",
                        lambda card, flag: laid.append((card, flag)))

    answer, _line = run(session, "flag_cards", note_ids=[1, 2], flag="green")
    assert answer["applied"] is True
    assert laid == [(10, 3), (20, 3)]
    assert session.flagged == 2


def test_a_colour_the_protocol_does_not_know_is_refused(deck, session, monkeypatch):
    monkeypatch.setattr("kotogen.anki.maintain.marks.set_flag",
                        lambda card, flag: pytest.fail("a flag was laid"))
    answer, _line = run(session, "flag_cards", note_ids=[1], flag="vert")
    assert answer["applied"] is False
    assert "green" in answer["error"]


def test_notes_already_carrying_the_flag_are_left_alone(deck, session, monkeypatch):
    monkeypatch.setattr(ask, "anki", _cards({}, {10: 3, 20: 3})(deck))
    monkeypatch.setattr("kotogen.anki.maintain.marks.set_flag",
                        lambda card, flag: pytest.fail("a flag was laid twice"))
    answer, _line = run(session, "flag_cards", note_ids=[1, 2], flag="green")
    assert answer["applied"] is False


def test_a_batch_larger_than_a_search_goes_by_its_query(deck, session, monkeypatch):
    """A search lists the model 80 notes at most: by id, a large batch would take
    one confirmation per slice. The query reaches them all, confirmed once."""
    monkeypatch.setattr(ask, "anki", _cards({})(deck))
    laid: list[int] = []
    monkeypatch.setattr("kotogen.anki.maintain.marks.set_flag",
                        lambda card, flag: laid.append(card))

    answer, _line = run(session, "flag_cards", query="-tag:Noun::*", flag="green")
    assert answer["applied"] is True
    assert laid == [10, 20]                     # note 3 is outside the scope
    searched = deck.params_for("findNotes")[0]["query"]
    assert "note:Vocabulary" in searched and "(-tag:Noun::*)" in searched


def test_a_query_that_does_not_close_is_refused_before_anything(deck, session,
                                                                monkeypatch):
    monkeypatch.setattr("kotogen.anki.maintain.marks.set_flag",
                        lambda card, flag: pytest.fail("a flag was laid"))
    answer, _line = run(session, "tag_notes", query='"tag:N4', add_tags=["x"])
    assert answer["applied"] is False
    assert "close" in answer["error"]


def test_an_open_editor_stops_the_flags_on_the_first_card(deck, session, monkeypatch,
                                                          capsys):
    """Anki refuses every card the same way while an editing window is open:
    said once, and the model is told why nothing went through."""
    from kotogen.anki.connect import EditorOpen

    monkeypatch.setattr(ask, "anki", _cards({})(deck))

    def refuse(card, flag):
        raise EditorOpen("close the editor")

    monkeypatch.setattr("kotogen.anki.maintain.marks.set_flag", refuse)
    answer, _line = run(session, "flag_cards", note_ids=[1, 2], flag="red")
    assert answer["applied"] is False
    assert answer["error"] == "close the editor"
    assert capsys.readouterr().err.count("close the editor") == 1


# -- The net -------------------------------------------------------------------

def test_the_snapshot_is_taken_at_the_first_accepted_write(deck, monkeypatch):
    """Not at launch: a request that only looks leaves nothing behind it."""
    taken = []
    monkeypatch.setattr(ask, "_net",
                        lambda session: taken.append(session.wrote) or True)
    session = Session(notetypes=dict(NOTETYPES), auto=True)

    run(session, "search_notes", query="tag:N4")
    run(session, "read_notes", note_ids=[1])
    assert not taken, "a snapshot was taken for a run that only looked"

    run(session, "edit_note", note_id=1, fields={"Translation": "To eat up"})
    assert taken == [0], "the snapshot is taken before the write, not after"


def test_a_write_is_dropped_when_no_snapshot_could_be_taken(deck, session, monkeypatch):
    """Elsewhere a failed backup only warns; here the model writes, which is what
    the net is for."""
    monkeypatch.setattr(ask, "_net", lambda session: False)
    answer, _line = run(session, "edit_note", note_id=1, fields={"Example": "犬[いぬ]"})
    assert answer["applied"] is False
    assert not deck.params_for("updateNoteFields")


def test_the_report_carries_the_line_that_undoes_everything(deck, session, capsys):
    session.stamp = "2026-09-14_143012"
    run(session, "tag_notes", note_ids=[1, 2], add_tags=["Cooking"])
    ask._report(session)
    assert "kotogen backup --restore 2026-09-14_143012" in capsys.readouterr().out


def test_a_run_that_changed_nothing_says_so(session, capsys):
    ask._report(session)
    out = capsys.readouterr().out
    assert "Nothing was changed" in out
    assert "--restore" not in out


def test_a_write_that_failed_half_way_still_says_how_to_go_back(deck, session,
                                                                monkeypatch, capsys):
    """The fields went in before the tags failed: nothing was counted, but the
    deck moved, and the snapshot taken for it is the way back."""
    def net(session):
        session.stamp = "2026-09-14_143012"
        return True

    def anki(action, **params):
        if action == "addTags":
            raise RuntimeError("Anki refused addTags")
        return deck(action, **params)

    monkeypatch.setattr(ask, "_net", net)
    monkeypatch.setattr(ask, "anki", anki)
    answer, _line = run(session, "edit_note", note_id=1,
                        fields={"Translation": "To eat up"}, add_tags=["Cooking"])
    assert answer["applied"] is False and deck.params_for("updateNoteFields")
    ask._report(session)
    out = capsys.readouterr().out
    assert "Nothing was changed" not in out
    assert "kotogen backup --restore 2026-09-14_143012" in out


def test_flags_cut_short_by_ctrl_c_stop_at_the_next_card(monkeypatch):
    """The thread that lays them is not waited for: it must not write on behind
    the report that says how to go back."""
    laid = []
    calls = []

    def ctrl_c_then_carry_on(work, detail=None):
        # The main thread is interrupted; the work goes on with the next card.
        calls.append(work)
        raise KeyboardInterrupt

    monkeypatch.setattr("kotogen.anki.maintain.marks.set_flag",
                        lambda card, flag: laid.append(card))
    monkeypatch.setattr(console, "while_working", ctrl_c_then_carry_on)
    with pytest.raises(KeyboardInterrupt):
        ask._write_flags(Session(notetypes=dict(NOTETYPES)), [10, 20, 30], 1)
    calls[0]()   # what the thread does once the main thread has gone on
    assert laid == []


@pytest.mark.parametrize("cut", [ConnectionError("AnkiConnect unreachable"),
                                 KeyboardInterrupt()], ids=["Anki closed", "Ctrl+C"])
def test_flags_written_before_the_cut_are_in_the_report(deck, monkeypatch, capsys, cut):
    """Two of four flags taken off, then Anki closes or Ctrl+C: the report counts
    the two, where "Nothing was changed." would be false (KOTOGEN_BACKUP=0)."""
    notes = [{"noteId": n, "cards": [n * 10], "fields": {}} for n in (1, 2, 3, 4)]
    monkeypatch.setattr(ask, "_batch", lambda session, args: (notes, [], ""))
    monkeypatch.setattr(ask, "anki", lambda action, **params: [
        {"cardId": n * 10, "note": n, "flags": 1} for n in (1, 2, 3, 4)])
    monkeypatch.setattr(ask, "_label", lambda note: str(note["noteId"]))
    cleared = []

    def clear(card):
        if len(cleared) == 2:
            raise cut
        cleared.append(card)

    monkeypatch.setattr("kotogen.anki.maintain.marks.clear_flag", clear)
    session = Session(notetypes=dict(NOTETYPES), auto=True)
    with pytest.raises(type(cut)):
        run(session, "clear_flag", note_ids=[1, 2, 3, 4])
    capsys.readouterr()
    ask._report(session)
    out = capsys.readouterr().out
    assert session.unflagged == 2
    assert "Nothing was changed" not in out
    assert "2 flags removed" in out


def test_the_control_characters_of_the_model_never_reach_the_terminal(deck, session,
                                                                      capsys):
    """A tool argument can carry `\\u001b`, which JSON decodes to an ESC: in a
    reason, in a field, in the last word, it would drive the terminal."""
    run(session, "edit_note", note_id=1, fields={"Translation": "To\u001b[2J eat up"},
        reason="clearer\u001b]0;owned\u0007 now")
    ask._speak("Done\u001b[31m in red\u009b")
    out = capsys.readouterr().out
    assert "\u001b" not in out and "\u0007" not in out and "\u009b" not in out
    assert "clearer]0;owned now" in out
    assert "Done[31m in red" in out
    stored = deck.params_for("updateNoteFields")[0]["note"]["fields"]["Translation"]
    assert "\u001b" not in stored


# -- A tool that goes wrong ----------------------------------------------------

def test_unreadable_arguments_are_an_answer_not_a_crash(session):
    """A tool that throws would end the conversation on a traceback, having
    perhaps already written half a plan into the deck."""
    answer, _line = ask.run_tool(session, "edit_note", "{not json")
    assert "error" in answer


def test_an_unknown_tool_is_told_the_ones_that_exist(session):
    answer, _line = ask.run_tool(session, "reset_progress", "{}")
    assert "reset_progress" in answer["error"]
    assert "edit_note" in answer["error"]


def test_a_search_anki_refuses_goes_back_to_the_model(deck, session, monkeypatch):
    def refuse(action, **params):
        if action == "findNotes":
            raise RuntimeError("invalid search")
        return deck(action, **params)

    monkeypatch.setattr(ask, "anki", refuse)
    answer, _line = run(session, "search_notes", query="prop:ivl>")
    assert "invalid search" in answer["error"]


# -- The conversation ----------------------------------------------------------

class FakeClient:
    """A model that plays a written-down list of turns."""

    def __init__(self, *turns: Reply):
        self.turns = list(turns)
        self.histories: list[int] = []

    def conversation(self, system, messages, tools, **kwargs):
        self.histories.append(len(messages))
        return self.turns.pop(0)


def reply(text="", *calls):
    return Reply(text, tuple(calls), {"role": "assistant", "content": text})


def test_the_ceiling_stops_a_model_going_round_in_circles(deck, monkeypatch, capsys):
    """Beyond it the model is going round in circles and every turn is paid for."""
    monkeypatch.setattr(ask, "MAX_TURNS", 3)
    call = ToolCall("id", "search_notes", json.dumps({"query": "tag:N4"}))
    client = FakeClient(*[reply("", call) for _ in range(3)])
    monkeypatch.setattr(ask, "AIClient", lambda **kwargs: client)
    monkeypatch.setattr(ask, "scope", lambda: dict(NOTETYPES))

    ask.run_ask(_args(request="do something"))
    assert "3 turns" in capsys.readouterr().out
    assert not client.turns, "the loop stopped before spending its ceiling"


def test_a_turn_with_no_tool_call_hands_the_screen_the_last_word(deck, monkeypatch,
                                                                 capsys):
    """Only the model's last word is written: the commentary between two tools
    says nothing the turn line has not already said."""
    call = ToolCall("id", "search_notes", json.dumps({"query": "tag:N4"}))
    client = FakeClient(reply("I will look at the scope first.", call),
                        reply("Two cards carry N4, nothing to do."))
    monkeypatch.setattr(ask, "AIClient", lambda **kwargs: client)
    monkeypatch.setattr(ask, "scope", lambda: dict(NOTETYPES))
    monkeypatch.setattr(ask, "_ask_again", lambda first=False: "")

    ask.run_ask(_args(request="which cards are N4?"))
    out = capsys.readouterr().out
    assert "Two cards carry N4" in out
    assert "I will look at the scope first" not in out


def test_an_answer_picks_the_conversation_up_where_it_was(deck, monkeypatch):
    """The answer goes into the SAME history: a restart would make the model pay
    again to read what it has read."""
    client = FakeClient(reply("Do I tell them apart, or delete one?"),
                        reply("Told apart."))
    answers = iter(["tell them apart", ""])
    monkeypatch.setattr(ask, "AIClient", lambda **kwargs: client)
    monkeypatch.setattr(ask, "scope", lambda: dict(NOTETYPES))
    monkeypatch.setattr(ask, "_ask_again", lambda first=False: next(answers))

    ask.run_ask(_args(request="sort my duplicates out"))
    # One message in at the first turn, three at the second: the request, what
    # the model said, and the answer typed.
    assert client.histories == [1, 3]


def test_the_ceiling_starts_again_when_the_user_takes_the_hand_back(deck, monkeypatch):
    """The ceiling stops a model looping on its own, not a long exchange."""
    monkeypatch.setattr(ask, "MAX_TURNS", 2)
    call = ToolCall("id", "search_notes", json.dumps({"query": "tag:N4"}))
    # Four turns under a ceiling of two: it holds only if answering resets the count.
    client = FakeClient(reply("", call), reply("First half done."),
                        reply("", call), reply("Second half done."))
    answers = iter(["carry on", ""])
    monkeypatch.setattr(ask, "AIClient", lambda **kwargs: client)
    monkeypatch.setattr(ask, "scope", lambda: dict(NOTETYPES))
    monkeypatch.setattr(ask, "_ask_again", lambda first=False: next(answers))

    ask.run_ask(_args(request="a long job"))
    assert not client.turns, "the ceiling counted the turns of the whole session"


def test_a_provider_that_drives_no_tool_is_refused_before_anything_is_loaded():
    with pytest.raises(SystemExit) as err:
        ask.run_ask(_args(request="x", provider="anthropic"))
    assert "openrouter" in str(err.value)


def test_an_empty_request_says_what_to_type():
    with pytest.raises(SystemExit) as err:
        ask.run_ask(_args(request="   "))
    assert "kotogen ask" in str(err.value)


def test_the_command_to_type_keeps_its_shell_quotes_in_every_language():
    """The language quotes its prose its own way; a shell reads only `"`."""
    from kotogen import i18n

    i18n.use("fr")
    with pytest.raises(SystemExit) as err:
        ask.run_ask(_args(request=""))
    assert 'kotogen ask "' in str(err.value)
    assert "«" not in str(err.value)


class _Failing(FakeClient):
    """Turns as given; an exception among them is raised at its turn."""

    def conversation(self, system, messages, tools, **kwargs):
        turn = self.turns.pop(0)
        if isinstance(turn, BaseException):
            raise turn
        return turn


def _written_then(monkeypatch, failure: BaseException):
    """A first turn that edits a note, then `failure` at the next one."""
    def edited(session, name, raw):
        session.edited += 1
        session.stamp = "2026-11-01_120000"
        session.lines.append("note 1: Translation")
        return {"applied": True}, ""

    client = _Failing(reply("", ToolCall("c1", "edit_note", "{}")), failure)
    monkeypatch.setattr(ask, "AIClient", lambda **kwargs: client)
    monkeypatch.setattr(ask, "scope", lambda: dict(NOTETYPES))
    monkeypatch.setattr(ask, "run_tool", edited)


@pytest.mark.parametrize("failure", [RuntimeError("Failed after 3 attempts: timed out."),
                                     ValueError("The AI's answer was not in the form asked "
                                                "for.\n\nRaw answer:\nsecond line")],
                         ids=["no answer", "invalid answer"])
def test_a_failure_after_a_write_still_says_how_to_go_back(monkeypatch, capsys, failure):
    _written_then(monkeypatch, failure)
    with pytest.raises(SystemExit) as stop:
        ask.run_ask(_args(request="fix it", yes=True))
    out = capsys.readouterr().out
    assert "kotogen backup --restore 2026-11-01_120000" in out
    assert str(stop.value.code).startswith("Interrupted: ")
    assert "\n" not in str(stop.value.code)


def test_ctrl_c_ends_the_conversation_on_its_report_and_code_130(monkeypatch, capsys):
    _written_then(monkeypatch, KeyboardInterrupt())
    with pytest.raises(SystemExit) as stop:
        ask.run_ask(_args(request="fix it", yes=True))
    assert stop.value.code == 130
    assert "kotogen backup --restore 2026-11-01_120000" in capsys.readouterr().out


def test_a_closed_anki_stops_the_conversation_rather_than_pay_more_turns(session,
                                                                        monkeypatch):
    """Every later call would fail the same way, each one a paid turn."""
    def closed(action, **params):
        raise ConnectionError("AnkiConnect unreachable.")

    monkeypatch.setattr(ask, "anki", closed)
    with pytest.raises(ConnectionError):
        run(session, "search_notes", query="tag:N4")


def test_the_request_is_the_command_and_not_an_option_of_maintain():
    """Two commands, sharing neither targets nor scope: `maintain` reads one note
    type, `ask` those the backup covers. As an option of `maintain`, a request
    would take `--only`, `--tag` and `--mature-ivl` without reading them."""
    from kotogen.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["ask", "take the N4 tag off the mature cards", "--yes"])
    assert (args.command, args.request, args.yes, args.scan) == (
        "ask", "take the N4 tag off the mature cards", True, False)

    with pytest.raises(SystemExit):
        parser.parse_args(["maintain", "--request", "anything"])


# -- What the screen says ------------------------------------------------------
# The shape, not the wording: the indent has a parent, what is asked of the user
# is a block of its own, and nothing is wider than the terminal.

def _screen(capsys) -> list[str]:
    """What was written, the empty lines kept and the erasures applied."""
    out = re.sub(r"\033\[[0-9;?]*[ -/]*[@-~]", "", capsys.readouterr().out)
    lines = []
    for raw in out.split("\n"):
        line = ""
        for part in raw.split("\r"):
            line = part + line[len(part):]
        lines.append(line.rstrip())
    return lines


def test_the_work_names_the_run_and_the_lines_hang_under_it(deck, monkeypatch,
                                                            capsys):
    """An indent with no parent reads as decoration: the work of the AI heads the
    lines it writes. Not the scope: it is every note type, at every request."""
    call = ToolCall("id", "search_notes", json.dumps({"query": "tag:N4"}))
    client = FakeClient(reply("", call), reply("Two cards carry N4."))
    monkeypatch.setattr(ask, "AIClient", lambda **kwargs: client)
    monkeypatch.setattr(ask, "scope", lambda: dict(NOTETYPES))
    monkeypatch.setattr(ask, "_ask_again", lambda first=False: "")

    ask.run_ask(_args(request="which cards are N4?"))
    written = [line for line in _screen(capsys) if line.strip()]
    assert written[0] == "What the AI does"
    assert written[1].startswith("   ")
    assert not any("Vocabulary" in line for line in written)


def test_what_the_prompt_takes_is_said_the_first_time_right_above_it(monkeypatch,
                                                                     capsys):
    monkeypatch.setattr(console, "read_line", lambda: "")
    ask._ask_again(first=True)
    ask._ask_again()
    shown = [line for line in _screen(capsys) if line]
    assert shown == ["Answer to carry on, Enter alone to finish.", ">", ">"]


def test_a_call_says_what_it_was_looking_for_and_not_that_it_was_thinking(
        deck, monkeypatch, capsys):
    """A wait is not a fact: a "Thinking" line, the same at every turn, says
    nothing about the deck."""
    call = ToolCall("id", "search_notes", json.dumps({"query": "tag:N4"}))
    client = FakeClient(reply("", call), reply("Two cards carry N4."))
    monkeypatch.setattr(ask, "AIClient", lambda **kwargs: client)
    monkeypatch.setattr(ask, "scope", lambda: dict(NOTETYPES))
    monkeypatch.setattr(ask, "_ask_again", lambda first=False: "")
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)

    ask.run_ask(_args(request="which cards are N4?"))
    written = [line for line in _screen(capsys) if line.strip()]
    assert any(re.fullmatch(r'   Searching "tag:N4"… \(\d+ notes?\)', line)
               for line in written), written
    assert not any("Thinking" in line for line in written)


def test_what_the_ai_answers_hangs_under_a_line_that_names_it(deck, monkeypatch,
                                                              capsys):
    """The answer takes the screen's shape: a name at the margin, the text one
    notch in, behind a bar the lines of the turn do not carry. The price is not
    its title: the bill comes once, when the command ends."""
    from kotogen import ai_client

    # Both totals: the module-level counters would carry this into the next test.
    monkeypatch.setattr(ai_client, "_run_usage", ai_client.Usage())
    monkeypatch.setattr(ai_client, "_session_usage", ai_client.Usage())
    ai_client.record_usage(12_000, 3_400, 0.0412)
    call = ToolCall("id", "search_notes", json.dumps({"query": "tag:N4"}))
    client = FakeClient(reply("", call), reply("Two cards carry N4."))
    monkeypatch.setattr(ask, "AIClient", lambda **kwargs: client)
    monkeypatch.setattr(ask, "scope", lambda: dict(NOTETYPES))
    monkeypatch.setattr(ask, "_ask_again", lambda first=False: "")

    ask.run_ask(_args(request="which cards are N4?"))
    written = [line for line in _screen(capsys) if line.strip()]
    head = written.index("The AI answers")
    assert written[head + 1] == "   │ Two cards carry N4."
    assert not any("AI call" in line for line in written[:head + 2])


def test_the_hand_comes_back_on_the_prompt_of_the_menus(monkeypatch, capsys):
    """The same gesture, the same sign, and no wording repeated at every turn."""
    monkeypatch.setattr(console, "read_line", lambda: "tell them apart")
    assert ask._ask_again() == "tell them apart"
    assert _screen(capsys)[-1] == ">"  # rstripped by the helper


@pytest.mark.parametrize("typed", ["", "b", "q", "quit", "\x1b"])
def test_every_way_out_finishes_the_session(typed, monkeypatch):
    """Enter on an empty line, the menus' two letters, Escape: none is announced,
    all of them leave."""
    monkeypatch.setattr(console, "read_line", lambda: typed)
    assert ask._ask_again() == ""


def test_a_change_to_confirm_is_a_block_and_not_one_more_line_of_the_run(
        deck, session, capsys):
    """Detached and named in the margin, or the question reads as a detail of
    the line above it."""
    console.watch()
    console.action("Thinking")
    run(session, "tag_notes", note_ids=[1, 2], add_tags=["Cooking"], reason="food")
    written = _screen(capsys)
    head = written.index("Tags to change")
    assert written[head - 1] == "", "the block opens on a breathing line"
    assert all(line.startswith("   ") for line in written[head + 1:] if line.strip())


def test_the_diff_reads_the_old_line_above_the_new_one_with_the_html_off(
        deck, session, capsys):
    """Two Japanese sentences overflow one line, and no console renders the HTML
    Anki stores."""
    console.watch()
    note = anki_note(1, "Vocabulary", Expression="食[た]べる",
                     Example="<div>古[ふる]い&nbsp;例[れい]</div>")
    ask._show_fields(note, {"Example": "新[あたら]しい 例[れい]"})
    written = [line.strip() for line in _screen(capsys) if line.strip()]
    assert written == ["Example", "- 古[ふる]い 例[れい]", "+ 新[あたら]しい 例[れい]"]


def test_nothing_is_written_wider_than_the_terminal_it_is_written_in(
        deck, session, monkeypatch, capsys):
    """A kanji takes two columns: a cut counted in characters lets a line wrap
    back to column zero, losing the indent of its block."""
    console.watch()
    monkeypatch.setattr(console, "columns", lambda: 40)
    note = anki_note(1, "Vocabulary", Expression="食[た]べる", Example="")
    ask._show_fields(note, {"Example": "毎朝[まいあさ] 魚[さかな]を 食[た]べます。" * 3})
    for line in _screen(capsys):
        assert console.width(line) <= 40, line


def test_the_report_is_folded_to_the_screen_and_the_markdown_taken_off(
        monkeypatch, capsys):
    """Printed as it comes, the report would wrap mid-word under no margin, with
    the stars of an emphasis nothing renders."""
    console.watch()
    monkeypatch.setattr(console, "columns", lambda: 40)
    ask._speak("The **N4 tag** is off the three of them, and nothing else "
               "was touched at all.")
    written = [line for line in _screen(capsys) if line.strip()]
    assert "*" not in "".join(written)
    assert len(written) > 1, "a line wider than the screen was folded"
    for line in written:
        assert console.width(line) < 40, line


def test_a_write_turned_back_before_it_showed_anything_says_so_under_the_block(
        deck, monkeypatch, capsys):
    """With no block of its own and no open line, a silent refusal would pass for
    a write done."""
    call = ToolCall("id", "edit_note",
                    json.dumps({"note_id": 3, "fields": {"Translation": "x"}}))
    client = FakeClient(reply("", call), reply("That note is not mine to touch."))
    monkeypatch.setattr(ask, "AIClient", lambda **kwargs: client)
    monkeypatch.setattr(ask, "scope", lambda: dict(NOTETYPES))
    monkeypatch.setattr(ask, "_ask_again", lambda first=False: "")

    ask.run_ask(_args(request="rewrite note 3"))
    assert any(line.strip().startswith("! ") for line in _screen(capsys))


class _args:  # lower case: it stands for a Namespace, and reads as one at the call site
    def __init__(self, *, request="", provider="openrouter", model="m",
                 scan=False, yes=False):
        self.request, self.provider, self.model = request, provider, model
        self.scan, self.yes = scan, yes


@pytest.fixture(autouse=True)
def quiet_console():
    """No step line left open from one test to the next."""
    yield
    console._step = None
    console._cut = False
