"""Maintenance: which action each mark triggers, the star, and `--only` by action."""

import pytest

from kotogen.anki.maintain import flag_pass, marks
from kotogen.anki.maintain.marks import STAR
from kotogen.anki.maintain.review import _parse_selection
from kotogen.maintenance import kinds


@pytest.fixture
def flags(monkeypatch):
    """Writes the setting of the flags for one test."""
    def write(value: str) -> None:
        monkeypatch.setenv(marks.FLAGS_SETTING, value)
    return write


# ── Reading the setting ───────────────────────────────────────────────────────

def test_with_no_setting_the_defaults_hold():
    assert marks.flag_actions() == marks.DEFAULT_FLAG_ACTIONS
    assert STAR not in marks.active_marks()


def test_a_written_mark_changes_its_action(flags):
    flags("pink=renew,star=derive")
    actions = marks.flag_actions()
    assert actions[5] == "renew"
    assert actions[STAR] == "derive"


def test_a_written_action_leaves_the_default_that_held_it(flags):
    """An action answers one mark at most: the default gives it up."""
    flags("star=error")
    actions = marks.flag_actions()
    assert actions[STAR] == "error"
    assert actions[1] == ""


def test_between_two_written_marks_the_first_one_wins(flags):
    flags("pink=renew,purple=renew")
    actions = marks.flag_actions()
    assert actions[5] == "renew"
    assert actions[7] == "audio"


def test_none_leaves_a_flag_alone(flags):
    flags("purple=none")
    assert marks.flag_actions()[7] == ""
    assert 7 not in marks.active_marks()


def test_a_pair_one_cannot_read_is_passed_over(flags):
    flags("crimson=error,pink=explode,, blue = TEXT ,green")
    assert marks.flag_actions() == marks.DEFAULT_FLAG_ACTIONS


# ── Writing it ────────────────────────────────────────────────────────────────

def test_an_action_taken_from_another_mark_swaps_the_two():
    actions = marks.assign(marks.DEFAULT_FLAG_ACTIONS, 5, "audio")
    assert actions[5] == "audio"
    assert actions[7] == "derive"


def test_an_action_given_to_the_star_leaves_the_mark_that_held_it_empty():
    actions = marks.assign(marks.DEFAULT_FLAG_ACTIONS, STAR, "derive")
    assert actions[STAR] == "derive"
    assert actions[5] == ""


def test_only_the_differences_are_written():
    assert marks.write_flag_actions(marks.DEFAULT_FLAG_ACTIONS) == ""
    actions = marks.assign(marks.DEFAULT_FLAG_ACTIONS, STAR, "renew")
    assert marks.write_flag_actions(actions) == "star=renew"


@pytest.mark.parametrize("mark, action", [(5, "audio"), (STAR, "derive"), (7, ""),
                                          (STAR, "renew"), (1, "renew")])
def test_what_is_written_reads_back_the_same(flags, mark, action):
    actions = marks.assign(marks.DEFAULT_FLAG_ACTIONS, mark, action)
    flags(marks.write_flag_actions(actions))
    assert marks.flag_actions() == actions


# ── Choosing the targets ──────────────────────────────────────────────────────

def test_without_only_every_mark_with_an_action_is_handled(flags):
    flags("purple=none,star=renew")
    assert _parse_selection(None) == ([1, 2, 3, 4, 5, 6, STAR], True)


def test_an_action_names_the_mark_that_triggers_it(flags):
    flags("star=renew")
    assert _parse_selection(["renew", "error"]) == ([1, STAR], False)


def test_an_action_no_mark_triggers_says_where_to_assign_it():
    with pytest.raises(SystemExit) as err:
        _parse_selection(["renew"])
    assert "Corrections > Marks" in str(err.value)


def test_a_mark_with_no_action_says_where_to_give_it_one():
    with pytest.raises(SystemExit) as err:
        _parse_selection(["star"])
    assert "triggers no action" in str(err.value)


def test_the_star_has_a_name_and_no_number(flags):
    """The numbers are Anki's flags; the star is not one of them."""
    flags("star=renew")
    with pytest.raises(SystemExit):
        _parse_selection([str(STAR)])


def test_the_header_follows_the_setting(flags):
    flags("pink=renew")
    assert marks.flag_header(5) == "🌸  Pink - to renew"


def test_the_list_shows_the_marks_with_an_action_only(flags):
    flags("pink=none,star=derive")
    names = [name for name, _emoji, _label in marks.targets()]
    assert names == ["red", "orange", "green", "blue", "turquoise", "purple", "star",
                     "leech"]


def test_the_columns_do_not_move_with_the_setting(flags):
    """The survey keeps its columns when turquoise, the longest name, triggers
    nothing, so that two runs line up."""
    before = marks.target_lines()[0]
    flags("turquoise=none")
    assert marks.target_lines()[0] == before


# ── The leech ─────────────────────────────────────────────────────────────────

def test_the_leeches_are_handled_by_default():
    assert marks.handles_leeches()
    assert _parse_selection(None) == ([1, 2, 3, 4, 5, 6, 7], True)


def test_leeches_left_alone_leave_the_run_and_the_list(flags):
    flags("leech=none")
    assert not marks.handles_leeches()
    assert _parse_selection(None) == ([1, 2, 3, 4, 5, 6, 7], False)
    assert "leech" not in [name for name, _emoji, _label in marks.targets()]


def test_leeches_left_alone_say_where_to_handle_them_again(flags):
    flags("leech=none")
    with pytest.raises(SystemExit) as err:
        _parse_selection(["leech"])
    assert "Corrections > Marks" in str(err.value)


def test_the_leech_is_no_mark_of_the_table(flags):
    """Written beside the flags, it gives none of them its action."""
    flags("leech=none,pink=renew")
    assert marks.flag_actions() == marks.assign(marks.DEFAULT_FLAG_ACTIONS, 5, "renew")


@pytest.mark.parametrize("leeches", [True, False])
def test_the_leech_reads_back_the_same(flags, leeches):
    actions = marks.assign(marks.DEFAULT_FLAG_ACTIONS, STAR, "derive")
    flags(marks.write_flag_actions(actions, leeches))
    assert marks.flag_actions() == actions
    assert marks.handles_leeches() == leeches


# ── The star ──────────────────────────────────────────────────────────────────

def test_the_star_is_found_once_per_note(monkeypatch):
    """It marks the note: a note of two cards is worked on, and paid for, once."""
    asked = []

    def fake(action, **params):
        asked.append((action, params))
        if action == "findCards":
            return [11, 12, 21]
        return [{"cardId": 11, "note": 1}, {"cardId": 12, "note": 1},
                {"cardId": 21, "note": 2}]

    monkeypatch.setattr(marks, "anki", fake)
    assert marks.find_flagged("Vocabulary", STAR) == [11, 21]
    assert asked[0][1]["query"] == '"note:Vocabulary" tag:marked'


def test_a_star_pass_takes_the_star_off_the_note(monkeypatch):
    calls = []

    def fake(action, **params):
        calls.append((action, params))
        return [{"cardId": 11, "note": 1}] if action == "cardsInfo" else None

    monkeypatch.setattr(flag_pass, "anki", fake)
    monkeypatch.setattr(marks, "clear_flag", lambda card_id: pytest.fail("a flag"))
    monkeypatch.setattr(flag_pass, "_pass_mark", STAR)
    flag_pass.unmark(11)
    assert calls[-1] == ("removeTags", {"notes": [1], "tags": "marked"})


def test_a_flag_pass_takes_the_flag_off_the_card(monkeypatch):
    cleared = []
    monkeypatch.setattr(marks, "clear_flag", cleared.append)
    monkeypatch.setattr(flag_pass, "_pass_mark", 5)
    flag_pass.unmark(11)
    assert cleared == [11]


def test_the_pass_forgets_its_mark_when_it_ends(monkeypatch):
    """What `ask` clears afterwards is a flag, whatever pass ran before it."""
    monkeypatch.setattr(flag_pass, "_process_flag", lambda *a: (_ for _ in ()).throw(KeyError))
    with pytest.raises(KeyError):
        flag_pass.process_flag(object(), STAR, kinds.VOCAB, True, [])
    assert flag_pass._pass_mark == 0
