"""Maintenance of the cards that are not words: grammar, reading, listening.

The instructions say what each action means; these tests pin what the code
holds around the answer: one gap, a text's lines, a passage corrected whole.
"""

import pytest

from conftest import Held, as_note
from kotogen import memory
from kotogen.anki.maintain import (
    derive as derive_pass,
    duplicates as duplicates_pass,
    flag_pass,
    leech,
    marks,
)
from kotogen.maintenance import derive, duplicates, kinds, review
from kotogen.maintenance.derive import Proposal


def _note(note_id: int, kind, tags=(), **values) -> dict:
    """A card as the maintenance reads one, the id of its note as its `id`."""
    fields = {name: "" for name in (*kind.shown, *kind.fields, "ID", "Answer")}
    fields.update(values)
    return {"id": note_id, "tags": list(tags), "fields": fields}


class _Client:
    def __init__(self, result):
        self.result = result
        self.system = self.user = ""

    def chat_json(self, system, user):
        self.system, self.user = system, user
        return self.result


# ── Which kind a note is ──────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", list(kinds.KINDS.values()), ids=list(kinds.KINDS))
def test_a_note_is_known_by_its_fields(kind):
    assert kinds.of_note(_note(1, kind)) is kind


# ── Grammar: one gap, and what the program draws from it ──────────────────────

GAP = _note(1, kinds.GRAMMAR, tags=["Grammar::N4::ながら"],
            Rule="ながら", Sentence="音楽[おんがく]を 聞[き]き{{c1::ながら}} 勉強[べんきょう]する。",
            Translation="I study while listening to music.", Target="while listening",
            Answer="ながら")


def test_a_sentence_with_two_gaps_is_turned_down():
    refused = []
    fields = review._changed_fields(
        GAP, {"Sentence": "{{c1::a}}と{{c2::b}}"}, kinds.GRAMMAR, refused)
    assert "Sentence" not in fields
    assert refused and refused[0].startswith("Sentence")


def test_the_answer_follows_a_new_gap():
    fields = review._changed_fields(
        GAP, {"Sentence": "歩[ある]き{{c3::ながら}}、話[はな]す。"}, kinds.GRAMMAR)
    assert "{{c1::ながら}}" in fields["Sentence"]
    assert "Answer" not in fields   # the same form: nothing to type differently


def test_a_target_outside_the_translation_is_turned_down():
    refused = []
    fields = review._changed_fields(GAP, {"Target": "while eating"}, kinds.GRAMMAR, refused)
    assert fields == {}
    assert refused


def test_a_translation_that_leaves_its_target_behind_drops_it():
    fields = review._changed_fields(
        GAP, {"Translation": "I study with music on."}, kinds.GRAMMAR)
    assert fields["Target"] == ""


def test_a_grammar_answer_stays_plain():
    """`{{type:Answer}}` compares what is typed character by character, and the
    export writes the `Nuance` plain as well: no reading on either."""
    fields = review._changed_fields(
        GAP, {"Sentence": "雨[あめ]が {{c1::降[ふ]ったら}}、出[で]かけない。",
              "Nuance": "雨の日だけ"}, kinds.GRAMMAR)
    assert fields["Answer"] == "降ったら"
    assert fields["Nuance"] == "雨の日だけ"


def test_only_the_register_tags_are_the_models_on_a_grammar_card():
    fields, add, remove, _reason = review._normalise_proposal(GAP, {
        "addTags": ["Register::丁寧体", "Level::N3"],
        "removeTags": ["Grammar::N4::ながら"]}, kinds.GRAMMAR)
    assert add == ["Register::丁寧体"]
    assert remove == []


def test_a_grammar_card_is_sent_with_its_rule_and_the_registers():
    client = _Client({"changed": False, "reason": "ok"})
    review.propose_changes(client, "error", GAP, kinds.GRAMMAR)
    assert "Rule" in client.user and "ながら" in client.user
    assert kinds.GRAMMAR_TAXONOMY in client.user
    assert "### renew" in client.system and "Expression" not in client.system


# ── Reading and listening: a text keeps its lines ─────────────────────────────

TEXT = "今日[きょう]は 晴[は]れです。<br>公園[こうえん]に 行[い]きます。"
PAGE = _note(10, kinds.READING, ID="RC_book_abcd1234_001", Text=TEXT,
             Translation="It is sunny today.<br>I go to the park.",
             Question="Where does the person go?", Answer="To the park", KeyLine="2")


def test_the_text_goes_to_the_model_numbered():
    client = _Client({"changed": False, "reason": "ok"})
    review.propose_changes(client, "text", PAGE, kinds.READING)
    assert "1. 今日[きょう]は 晴[は]れです。" in client.user
    assert "2. 公園[こうえん]に 行[い]きます。" in client.user


def test_a_translation_of_as_many_lines_is_taken():
    fields = review._changed_fields(
        PAGE, {"Translation": ["The weather is fine today.", "I go to the park."]},
        kinds.READING)
    assert fields == {"Translation": "The weather is fine today.<br>I go to the park."}


def test_a_translation_of_another_count_is_turned_down():
    refused = []
    fields = review._changed_fields(
        PAGE, {"Translation": ["It is sunny today and I go to the park."]},
        kinds.READING, refused)
    assert fields == {}
    assert "1 lines for 2" in refused[0]


def test_a_key_line_that_does_not_exist_is_turned_down():
    refused = []
    assert review._changed_fields(PAGE, {"KeyLine": 5}, kinds.READING, refused) == {}
    assert refused
    assert review._changed_fields(PAGE, {"KeyLine": 1}, kinds.READING) == {"KeyLine": "1"}


def test_a_corrected_answer_gets_its_readings():
    """Its decoys got theirs at export (`exporter.plain_field`): an answer without
    them would give itself away on a deck in Japanese."""
    fields = review._changed_fields(PAGE, {"Answer": "公園に行きます"}, kinds.READING)
    assert "公園[こうえん]" in fields["Answer"]


def test_no_tag_of_a_reading_card_is_the_models():
    _fields, add, remove, _reason = review._normalise_proposal(
        PAGE, {"addTags": ["Level::N5"], "removeTags": []}, kinds.READING)
    assert add == []


# ── The cards of one passage ──────────────────────────────────────────────────

def _passage(monkeypatch) -> tuple[dict, dict, dict, list]:
    sibling = _note(11, kinds.READING, ID="RC_book_abcd1234_002", Text=TEXT,
                    Translation="It is sunny today.<br>I go to the park.")
    edited = _note(12, kinds.READING, ID="RC_book_abcd1234_003", Text="手[て]で 直[なお]した。",
                   Translation="Fixed by hand.")
    stranger = _note(13, kinds.READING, ID="RC_book_abcd12349_001", Text=TEXT)
    writes = []

    def anki(action, **params):
        if action == "findNotes":
            return [10, 11, 12, 13]
        if action == "notesInfo":
            return [as_note(n) for n in (PAGE, sibling, edited, stranger)]
        writes.append((action, params))
        return None

    monkeypatch.setattr(marks, "anki", anki)
    return sibling, edited, stranger, writes


def test_the_passage_is_told_by_the_stem_of_its_identifier(monkeypatch):
    sibling, edited, _stranger, _writes = _passage(monkeypatch)
    assert marks.passage_of(PAGE, kinds.READING) == [sibling, edited]


def test_a_card_with_no_rank_in_its_identifier_is_alone(monkeypatch):
    monkeypatch.setattr(marks, "anki", lambda *a, **k: pytest.fail("Anki was asked"))
    assert marks.passage_of(_note(1, kinds.READING, ID="lonely"), kinds.READING) == []


def test_a_shared_correction_reaches_the_passage_and_nothing_else(monkeypatch):
    """The text goes to every card that still carries it; the question, the tags
    and a sibling edited by hand stay their own."""
    import copy

    sibling, edited, _stranger, writes = _passage(monkeypatch)
    passage = copy.deepcopy([sibling, edited])
    fixed = TEXT.replace("晴[は]れ", "晴[は]れ ")
    reached = marks.apply_to_passage(
        PAGE, kinds.READING, {"Text": fixed, "Question": "Where?"},
        ["Check::Reading"], [], passage)
    assert reached == 1
    updates = [p["note"] for action, p in writes if action == "updateNoteFields"]
    assert updates == [{"id": 10, "fields": {"Text": fixed, "Question": "Where?"}},
                       {"id": 11, "fields": {"Text": fixed}}]
    tagged = [p["notes"] for action, p in writes if action == "addTags"]
    assert tagged == [[10]]
    assert passage[0]["fields"]["Text"] == fixed   # the pass sees it


def test_the_diff_says_how_many_cards_of_the_passage_change(capsys):
    marks.show_diff(PAGE, {"Text": TEXT.replace("晴", "曇")}, [], [], "", reached=2)
    out = capsys.readouterr().out
    assert "1 - 今日[きょう]は 晴[は]れです。" in out
    assert "2 -" not in out   # the line that does not move is not shown
    assert "2 other cards of the passage carry the same text" in out


def test_the_diff_shows_the_model_without_its_control_characters(capsys):
    """A reason or a field from the model carrying an ESC would drive the terminal."""
    marks.show_diff(PAGE, {"Question": "Where\u001b[2J?"}, [], [],
                    "clearer\u001b]0;title\u0007 now")
    out = capsys.readouterr().out
    assert "\u001b" not in out and "\u0007" not in out
    assert "clearer]0;title now" in out
    assert "+ Where[2J?" in out


def test_an_automatic_pass_corrects_the_passage_and_says_so(monkeypatch, capsys):
    sibling, _edited, _stranger, writes = _passage(monkeypatch)
    real = marks.anki

    def anki(action, **params):
        if action == "cardsInfo":
            return [{"cardId": 100, "note": 10}]
        if action == "notesInfo" and params.get("notes") == [10]:
            return [as_note(PAGE)]
        return real(action, **params)

    monkeypatch.setattr(flag_pass, "anki", anki)
    monkeypatch.setattr(marks, "anki", anki)
    monkeypatch.setattr(marks, "find_flagged", lambda notetype, flag: [100])
    monkeypatch.setattr(marks, "clear_flag", lambda card_id: None)
    monkeypatch.setattr(flag_pass, "propose_changes", lambda *a: {
        "changed": True, "reason": "typo",
        "fields": {"Text": ["今日[きょう]は 晴[は]れでした。", "公園[こうえん]に 行[い]きます。"]}})
    assert flag_pass.process_flag(None, 4, kinds.READING, True, []) == (2, 1)
    assert "1 other card of the passage too" in capsys.readouterr().out


# ── Leeches of every kind ─────────────────────────────────────────────────────

def test_a_grammar_leech_is_simplified_through_its_own_instruction(monkeypatch):
    card = {"cardId": 5, "note": 1, "fields": as_note(GAP)["fields"]}
    calls = []

    def anki(action, **params):
        calls.append(action)
        if action == "cardsInfo":
            return [card]
        if action == "notesInfo":
            return [as_note(GAP)]
        return None

    monkeypatch.setattr(leech, "anki", anki)
    monkeypatch.setattr(marks, "anki", anki)
    asked = []
    monkeypatch.setattr(leech, "propose_changes", lambda client, action, note, kind:
                        asked.append((action, kind.command)) or
                        {"fields": {"Nuance": "at the same time"}})
    monkeypatch.setattr(leech, "_propose_simpler",
                        lambda *a: pytest.fail("the vocabulary rework ran"))
    assert leech._process_true([5], "leech", object(), 21, True, kinds.GRAMMAR) == (0, 1)
    assert asked == [("simplify", "grammar")]
    assert "forgetCards" in calls


# ── A leech the interval sorted wrong ─────────────────────────────────────────
# `ivl < 21` sends a card to the rework, but halfway to maturity it may be known
# and only caught by a bad week: such a card can be kept as it stands.

def _leech(monkeypatch, answer: str = "", auto: bool = False,
           proposal: dict | None = None, **numbers):
    """One grammar leech through the rework, answering `answer` at its menu.

    Hands back what `_process_true` returned, the Anki actions it asked for and
    the menus it showed; the AI proposes `proposal`, a simplification failing it.
    """
    if proposal is None:
        proposal = {"fields": {"Nuance": "at the same time"}}
    card = {"cardId": 5, "note": 1, "fields": as_note(GAP)["fields"], **numbers}
    calls, menus = [], []

    def anki(action, **params):
        calls.append(action)
        if action == "cardsInfo":
            return [card]
        if action == "notesInfo":
            return [as_note(GAP)]
        return None

    monkeypatch.setattr(leech, "anki", anki)
    monkeypatch.setattr(marks, "anki", anki)
    monkeypatch.setattr(leech, "propose_changes", lambda *a: proposal)
    monkeypatch.setattr(leech, "choose",
                        lambda options, *a, **k: menus.append(dict(options)) or answer)
    counted = leech._process_true([5], "leech", object(), 21, auto, kinds.GRAMMAR)
    return counted, calls, menus


def test_a_leech_halfway_to_maturity_can_be_kept_as_it_stands(monkeypatch, capsys):
    """`m`: the tag comes off and nothing else moves - no rewrite, no reset."""
    counted, calls, menus = _leech(monkeypatch, "m", interval=12, lapses=2)
    assert counted == (1, 0)
    assert menus[0]["m"] == "mastered"
    # The figures are what the choice leans on, hence on the card's own line.
    assert "(ivl 12, 2 lapses)" in capsys.readouterr().out
    assert "removeTags" in calls and "unsuspend" in calls
    assert "forgetCards" not in calls


def test_a_leech_kept_by_hand_counts_with_the_false_ones(monkeypatch):
    """The tally counts the card as the user sorted it, not as the threshold did."""
    class _Args:
        tag, mature_ivl, provider, model = "leech", 21, None, None

    monkeypatch.setattr(leech, "_process_true", lambda *a, **k: (1, 0))
    assert leech.process_leeches([], [5], _Args(), client=object()) == (1, 0)


def test_a_young_leech_is_not_offered_to_be_kept(monkeypatch, capsys):
    """Below half the threshold there is no choice for the figures to inform, so
    they are not shown."""
    counted, calls, menus = _leech(monkeypatch, "s", interval=3, lapses=9)
    assert counted == (0, 0)
    assert "m" not in menus[0]
    assert "ivl 3" not in capsys.readouterr().out
    assert "removeTags" not in calls


def test_a_leech_the_ai_cannot_simplify_can_be_put_back_as_it_is(monkeypatch):
    """`r`: the reset of a rework without its rewrite, so the card is learned
    again rather than lost for want of a better wording."""
    counted, calls, menus = _leech(monkeypatch, "r", proposal={"fields": {}},
                                   interval=3, lapses=9)
    assert counted == (0, 1)
    assert "r" in menus[0] and "m" not in menus[0]
    assert {"removeTags", "unsuspend", "forgetCards"} <= set(calls)
    assert "updateNoteFields" not in calls


def test_the_automatic_mode_reworks_a_leech_it_could_have_kept(monkeypatch):
    """Keeping a card is a judgement, and the automatic mode has none to make."""
    counted, calls, menus = _leech(monkeypatch, auto=True, interval=18, lapses=1)
    assert counted == (0, 1)
    assert menus == []
    assert "forgetCards" in calls


# ── Duplicates: grammar ───────────────────────────────────────────────────────

def _gap(note_id: int, sentence: str, translation: str, rule: str = "ながら", **more) -> dict:
    return _note(note_id, kinds.GRAMMAR, Rule=rule, Sentence=sentence,
                 Translation=translation, **more)


def test_the_same_sentence_under_other_readings_is_a_candidate():
    other = _gap(2, "音楽を聞き{{c1::ながら}}、勉強する", "Something else entirely.")
    found = duplicates.grammar_candidates(GAP, [GAP, other])
    assert [(n["id"], reasons) for n, reasons in found] == [
        (2, ["same sentence", "same rule"])]


def test_the_same_rule_on_another_sentence_is_not_a_candidate():
    """A rule is learned on several sentences: its series is not its duplicates."""
    other = _gap(2, "歩[ある]き{{c1::ながら}} 話[はな]す。", "I talk as I walk.")
    assert duplicates.grammar_candidates(GAP, [other]) == []


def test_the_same_translation_under_another_rule_is_a_candidate():
    other = _gap(3, "音楽[おんがく]を 聞[き]き{{c1::つつ}} 勉強[べんきょう]した。",
                 "I study while listening to music.", rule="つつ")
    assert duplicates.grammar_candidates(GAP, [other])[0][1] == ["same translation"]


def _grammar_run(monkeypatch, verdicts, replies=()):
    """A turquoise grammar pass against a faked model and a faked Anki."""
    other = _gap(2, "音楽を聞き{{c1::ながら}}、勉強する", "I study while listening to music.")
    writes, cleared = [], []
    monkeypatch.setattr(marks, "anki", lambda action, **p: writes.append((action, p)))
    monkeypatch.setattr(duplicates_pass, "delete_notes", lambda ids: writes.append(("delete", ids)))
    monkeypatch.setattr(duplicates_pass, "apply_changes",
                        lambda nid, fields, add, remove: writes.append(("update", nid, fields)))
    monkeypatch.setattr(duplicates_pass, "unmark", cleared.append)
    answers = iter(replies)
    monkeypatch.setattr(duplicates_pass, "ask_choice", lambda prompt, keys: next(answers))
    monkeypatch.setattr(duplicates_pass, "choose", lambda options, *a, **k: next(answers))
    client = _Client({"verdicts": verdicts})
    return client, other, writes, cleared


def test_a_grammar_duplicate_waits_for_you_in_automatic_mode(monkeypatch):
    client, other, writes, cleared = _grammar_run(
        monkeypatch, [{"index": 0, "verdict": "duplicate", "reason": "same"}])
    assert duplicates_pass.process(client, 100, GAP, [GAP, other], kinds.GRAMMAR, True, {}) == (0, 0)
    assert writes == [] and cleared == []


def test_confusable_cards_are_told_apart_by_their_hints(monkeypatch):
    client, other, writes, cleared = _grammar_run(monkeypatch, [{
        "index": 0, "verdict": "confusable", "reason": "same hints",
        "card": {"Nuance": "two actions at once", "Sentence": "rewritten"},
        "other": {"Nuance": "formal"}}])
    assert duplicates_pass.process(client, 100, GAP, [GAP, other], kinds.GRAMMAR, True, {}) == (2, 1)
    assert writes == [("update", 1, {"Nuance": "two actions at once"}),
                      ("update", 2, {"Nuance": "formal"})]
    assert cleared == [100]


def test_keeping_the_flagged_card_deletes_the_other_after_confirmation(monkeypatch):
    client, other, writes, cleared = _grammar_run(
        monkeypatch, [{"index": 0, "verdict": "duplicate"}], replies=["1", "y"])
    assert duplicates_pass.process(client, 100, GAP, [GAP, other], kinds.GRAMMAR, False, {}) == (1, 1)
    assert ("delete", [2]) in writes and cleared == [100]


def test_deleting_the_flagged_card_takes_its_flag_with_it(monkeypatch):
    client, other, writes, cleared = _grammar_run(
        monkeypatch, [{"index": 0, "verdict": "duplicate"}], replies=["2", "y"])
    assert duplicates_pass.process(client, 100, GAP, [GAP, other], kinds.GRAMMAR, False, {}) == (1, 0)
    assert ("delete", [1]) in writes and cleared == []


# ── Duplicates: passages and their questions ──────────────────────────────────

def test_a_text_that_came_in_twice_is_a_twin_passage():
    again = _note(20, kinds.READING, ID="RC_other_ffff0000_001", Text=TEXT.replace(" ", ""))
    sibling = _note(11, kinds.READING, ID="RC_book_abcd1234_002", Text=TEXT)
    elsewhere = _note(21, kinds.READING, ID="RC_x_00000000_001", Text="別[べつ]の 文[ぶん]。")
    twins = duplicates.twin_passages(PAGE, [PAGE, again, sibling, elsewhere], kinds.READING)
    assert list(twins) == ["RC_other_ffff0000"]


def test_an_extract_cut_twice_plays_the_same_file():
    sound = '<audio controls src="talk_01_abcd1234.mp3"></audio>'
    one = _note(1, kinds.LISTENING, ID="talk_01_abcd1234_001", Audio=sound, Transcript="A：はい。")
    two = _note(2, kinds.LISTENING, ID="talk_01_beef0000_001", Audio=sound, Transcript="A：はい、そう。")
    assert list(duplicates.twin_passages(one, [one, two], kinds.LISTENING)) == [
        "talk_01_beef0000"]


def test_only_the_other_questions_of_the_passage_are_read_back():
    other = _note(11, kinds.READING, Question="What is at the park?")
    client = _Client({"duplicates": [{"n": 1}, {"n": 2, "reason": "same fact"}, {"n": 9}]})
    assert duplicates.same_questions(client, PAGE, kinds.READING, [other]) == [
        (other, "same fact")]
    assert client.user.endswith(": 1")   # the flagged question is named first


def test_a_question_asked_twice_is_renewed_in_automatic_mode(monkeypatch):
    other = _note(11, kinds.READING, ID="RC_book_abcd1234_002", Text=TEXT,
                  Question="What is at the park?")
    monkeypatch.setattr(duplicates_pass, "twin_passages", lambda *a: {})
    monkeypatch.setattr(duplicates_pass, "passage_of", lambda *a: [other])
    monkeypatch.setattr(duplicates_pass, "same_questions", lambda *a: [(other, "same fact")])
    monkeypatch.setattr(duplicates_pass, "propose_changes", lambda *a: {
        "fields": {"Question": "What is the weather like?", "Answer": "Sunny",
                   "KeyLine": 1}})
    applied, cleared = [], []
    monkeypatch.setattr(duplicates_pass, "apply_to_passage",
                        lambda note, kind, fields, *a: applied.append(fields) or 0)
    monkeypatch.setattr(duplicates_pass, "unmark", cleared.append)
    assert duplicates_pass.process(None, 100, PAGE, [PAGE, other], kinds.READING, True, {}) == (1, 1)
    assert applied == [{"Question": "What is the weather like?", "Answer": "Sunny",
                        "KeyLine": "1"}]
    assert cleared == [100]


def _asked_twice(monkeypatch, proposal):
    """A reading question the AI finds asked twice in its passage; renewing it
    proposes `proposal`, or fails when it is an exception. Hands back the flags
    taken off and the questions written."""
    other = _note(11, kinds.READING, ID="RC_book_abcd1234_002", Text=TEXT,
                  Question="What is at the park?")
    monkeypatch.setattr(duplicates_pass, "twin_passages", lambda *a: {})
    monkeypatch.setattr(duplicates_pass, "passage_of", lambda *a: [other])
    monkeypatch.setattr(duplicates_pass, "same_questions", lambda *a: [(other, "same fact")])

    def renew(*args):
        if isinstance(proposal, Exception):
            raise proposal
        return proposal

    monkeypatch.setattr(duplicates_pass, "propose_changes", renew)
    cleared, applied = [], []
    monkeypatch.setattr(duplicates_pass, "unmark", cleared.append)
    monkeypatch.setattr(duplicates_pass, "apply_to_passage",
                        lambda note, kind, fields, *a: applied.append(fields) or 0)
    return other, cleared, applied


@pytest.mark.parametrize("proposal", [ValueError("The AI's answer was not in the form asked for."),
                                      {"fields": {}}],
                         ids=["the model failed", "nothing new proposed"])
def test_a_question_asked_twice_and_not_renewed_keeps_its_flag(monkeypatch, capsys, proposal):
    """Automatic mode only renews: with nothing renewed the duplicate stands, and
    its flag waits for a run by hand."""
    other, cleared, applied = _asked_twice(monkeypatch, proposal)
    assert duplicates_pass.process(None, 100, PAGE, [PAGE, other], kinds.READING, True,
                                   {}) == (0, 0)
    assert cleared == []
    assert applied == []
    assert "flag kept" in capsys.readouterr().out


def test_a_renewal_declined_by_hand_asks_about_the_flag(monkeypatch):
    """Declining is not settling: the flag is the user's to keep or take off."""
    other, cleared, _applied = _asked_twice(monkeypatch, {
        "fields": {"Question": "What is the weather like?", "Answer": "Sunny"}})
    monkeypatch.setattr(duplicates_pass, "choose", lambda options, *a, **k: "r")
    monkeypatch.setattr(duplicates_pass, "show_diff", lambda *a, **k: None)
    asked = []
    monkeypatch.setattr(duplicates_pass, "ask_choice", lambda prompt, keys, **k: "n")
    monkeypatch.setattr(duplicates_pass, "_resolve_flag_only",
                        lambda card_id: asked.append(card_id) or False)
    assert duplicates_pass.process(None, 100, PAGE, [PAGE, other], kinds.READING, False,
                                   {}) == (0, 0)
    assert asked == [100]
    assert cleared == []


# ── Derive: what a grammar card and a text call for ───────────────────────────

def test_a_grammar_card_calls_for_rules_and_never_its_own():
    client = _Client({"rules": [
        {"rule": "〜つつ", "relation": "contrast", "gloss": "while (formal)"},
        {"rule": "ながら", "relation": "family", "gloss": "itself"},
        {"rule": "ている", "relation": "sideways", "gloss": ""},
        {"rule": "a"}, {"rule": "b"}, {"rule": "c"}]})
    found = derive.propose(client, GAP, kinds.GRAMMAR)
    assert found[:2] == [Proposal("〜つつ", "contrast", "while (formal)", "grammar"),
                         Proposal("ている", "", "", "grammar")]
    assert len(found) == derive.MAX_RULES
    assert client.system == derive.prompts.load("maintain_derive_grammar")


def test_a_text_calls_for_words_and_rules_in_one_call():
    page = {**PAGE, "tags": ["Level::N4"]}
    client = _Client({"words": [{"word": "晴[は]れる", "gloss": "to clear up"}],
                      "rules": [{"rule": "〜ます", "gloss": "polite"}]})
    found = derive.propose(client, page, kinds.READING)
    assert found == [Proposal("晴れる", "word", "to clear up", "vocab"),
                     Proposal("〜ます", "rule", "polite", "grammar")]
    assert "1. 今日[きょう]は 晴[は]れです。" in client.user
    assert "N4" in client.user
    assert derive.describe(found[0]) == "晴れる - to clear up (word of the text)"


def test_a_rule_the_deck_holds_is_not_proposed_again(monkeypatch):
    class RulesOnly(Held):
        def words(self, notetype, field_name="Expression"):
            pytest.fail("the vocabulary was read for rules")

    monkeypatch.setattr(memory, "_known", RulesOnly())
    monkeypatch.setattr(derive.grammar, "deck_rules", lambda known, notetype: set())
    monkeypatch.setattr(derive.grammar, "knows_rule",
                        lambda rule, held: rule == "〜ながら")
    new, already = derive.fresh(
        [Proposal("〜ながら", "rule", "", "grammar"), Proposal("〜つつ", "rule", "", "grammar")],
        derive.Held(memory.known()), set())
    assert [p.word for p in new] == ["〜つつ"]
    assert [p.word for p in already] == ["〜ながら"]


def test_the_grammar_deck_knows_a_rule_by_its_name(monkeypatch):
    from kotogen.generators import grammar

    monkeypatch.setattr(grammar, "_rules_seen", lambda: set())
    monkeypatch.setattr(grammar.grammar_table, "find", lambda rule: None)
    held = {grammar.grammar_table.key("つつ")}
    assert grammar.knows_rule("つつ", held)
    assert not grammar.knows_rule("ように", held)


def _derive_pass(monkeypatch, sent=True):
    generated, cleared = [], []
    monkeypatch.setattr(derive_pass, "fresh", lambda proposals, known, taken: (
        [p for p in proposals if p.word not in taken], []))
    monkeypatch.setattr(derive_pass.vocab, "generate_into", lambda client, words, deck, notetype:
                        generated.append(("vocab", list(words), deck)) or True)
    monkeypatch.setattr(derive.grammar, "generate_into",
                        lambda client, rules, deck, notetype, count:
                        generated.append(("grammar", list(rules), deck)) or sent)
    monkeypatch.setattr(derive_pass, "unmark", cleared.append)
    monkeypatch.setenv("KOTOGEN_VOCAB_DECK", "Japanese::Vocabulary")
    monkeypatch.setenv("KOTOGEN_GRAMMAR_DECK", "Japanese::Grammar")
    return generated, cleared


class _Counting(_Client):
    def __init__(self, result):
        super().__init__(result)
        self.calls = 0

    def chat_json(self, system, user):
        self.calls += 1
        return super().chat_json(system, user)


SIBLING = _note(11, kinds.READING, ID="RC_book_abcd1234_002", Text=TEXT)
READING_CARDS = [{"cardId": 100, "note": 10, "deckName": "Japanese::Reading"},
                 {"cardId": 110, "note": 11, "deckName": "Japanese::Reading"}]


def test_a_passage_is_read_once_and_its_cards_go_to_their_own_decks(monkeypatch):
    generated, cleared = _derive_pass(monkeypatch)
    client = _Counting({"words": [{"word": "公園", "gloss": "park"}],
                        "rules": [{"rule": "〜に行く", "gloss": "go to"}]})
    derive_pass.process(client, READING_CARDS, {10: PAGE, 11: SIBLING}, kinds.READING, auto=True)
    assert client.calls == 1
    assert generated == [("vocab", ["公園"], "Japanese::Vocabulary"),
                         ("grammar", ["〜に行く"], "Japanese::Grammar")]
    assert sorted(cleared) == [100, 110]


def test_a_passage_the_model_failed_on_is_not_paid_for_again(monkeypatch, capsys):
    """Its other card would ask the same text the same question: it waits, flag
    kept, for the next run."""
    generated, cleared = _derive_pass(monkeypatch)

    class Failing(_Counting):
        def chat_json(self, system, user):
            self.calls += 1
            raise ValueError("The AI's answer was not in the form asked for.")

    client = Failing({})
    derive_pass.process(client, READING_CARDS, {10: PAGE, 11: SIBLING}, kinds.READING, auto=True)
    assert client.calls == 1
    assert generated == []
    assert cleared == []
    assert capsys.readouterr().err.count("AI error") == 1


def test_half_a_derivation_keeps_the_flags(monkeypatch):
    """The words went in, the rules did not: the passage still has one to finish."""
    generated, cleared = _derive_pass(monkeypatch, sent=False)
    client = _Client({"words": [{"word": "公園", "gloss": "park"}],
                      "rules": [{"rule": "〜に行く", "gloss": "go to"}]})
    derive_pass.process(client, READING_CARDS, {10: PAGE, 11: SIBLING}, kinds.READING, auto=True)
    assert len(generated) == 2
    assert cleared == []


def test_a_rule_derived_from_a_grammar_card_stays_in_its_deck(monkeypatch):
    generated, cleared = _derive_pass(monkeypatch)
    client = _Client({"rules": [{"rule": "〜つつ", "relation": "contrast", "gloss": ""}]})
    cards = [{"cardId": 5, "note": 1, "deckName": "Japanese::Grammar::N3"}]
    derive_pass.process(client, cards, {1: GAP}, kinds.GRAMMAR, auto=True)
    assert generated == [("grammar", ["〜つつ"], "Japanese::Grammar::N3")]
    assert cleared == [5]
