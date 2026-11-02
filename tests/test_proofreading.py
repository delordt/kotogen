"""The cards the model gave back damaged: what becomes of them.

A card kept under a "!!" was paid for but is missing something: an unaligned
translation, a transcript, the right answer repeated among the decoys. The
setting keeps, tags or drops it, or asks. Guarded here: the file agreeing with
the summary, an earlier pass surviving in a shared file, no question where no
one can answer, and a tag reaching a line already written.
"""

from __future__ import annotations

import argparse
import json

import pytest

from kotogen import console, exporter, i18n, proofreading
from kotogen.anki import connect, send
from kotogen.exporter import append_cards, finish

FIELDS = ["Expression", "Translation"]

UNALIGNED = proofreading.UNALIGNED_TRANSLATION


@pytest.fixture(autouse=True)
def _fresh_session(monkeypatch):
    """No choice of the session leaks from one test to the next."""
    monkeypatch.setattr(proofreading, "_mode", None)
    monkeypatch.delenv(proofreading.ENV_VAR, raising=False)


class FakeStatus:
    def __init__(self, connected):
        self.connected = connected


def args_for(send=False, deck="Japanese::Reading", notetype="Reading"):
    return argparse.Namespace(send=send, deck=deck, notetype=notetype)


def build_parser_args(command: str) -> argparse.Namespace:
    """The minimal argv of that command, with `--proofread drop`."""
    from kotogen.cli import build_parser

    inputs = {"vocab": "水", "grammar": "は", "audio": "nhk", "reading": "nhk"}
    return build_parser().parse_args(
        [command, inputs[command], "--proofread", "drop"])


def card(expression: str, translation: str = "") -> dict:
    return {"Expression": expression, "Translation": translation}


def batch() -> list[dict]:
    """Three cards, two of them landing on the same unaligned translation."""
    cards = [card("みず"), card("ひ"), card("き")]
    proofreading.mark(cards[:2], proofreading.TRANSLATION_TAG, UNALIGNED)
    return cards


# ── The setting: command line, session, file ──────────────────────────────────

def test_asking_is_the_default():
    """Nothing set: ask rather than decide for the user."""
    assert proofreading.mode() == "ask"


def test_the_setting_of_the_file_applies(monkeypatch):
    monkeypatch.setenv(proofreading.ENV_VAR, "drop")
    assert proofreading.mode() == "drop"


def test_a_stale_setting_does_not_block_the_command(monkeypatch):
    """A value that cannot be read gives the default, never an error."""
    monkeypatch.setenv(proofreading.ENV_VAR, "maybe")
    assert proofreading.mode() == "ask"


def test_the_words_of_the_switches_are_understood(monkeypatch):
    """"yes" and "no" are typed from memory, and must not fall on the default."""
    for value, expected in (("yes", "keep"), ("on", "keep"), ("always", "keep"),
                            ("no", "drop"), ("off", "drop"), ("never", "drop")):
        monkeypatch.setenv(proofreading.ENV_VAR, value)
        assert proofreading.mode() == expected


def test_the_session_wins_over_the_file(monkeypatch):
    """That is what `--proofread` does: one pass, writing nothing."""
    monkeypatch.setenv(proofreading.ENV_VAR, "drop")
    proofreading.set_mode("keep")
    assert proofreading.mode() == "keep"


def test_the_option_wins_over_the_setting(monkeypatch):
    from kotogen.cli import build_parser

    monkeypatch.setenv(proofreading.ENV_VAR, "drop")
    args = build_parser().parse_args(["reading", "nhk", "--proofread", "keep"])
    assert proofreading.resolve(args) == "keep"


def test_without_the_option_the_setting_applies(monkeypatch):
    from kotogen.cli import build_parser

    monkeypatch.setenv(proofreading.ENV_VAR, "drop")
    assert proofreading.resolve(build_parser().parse_args(["reading", "nhk"])) == "drop"


@pytest.mark.parametrize("command", ["vocab", "grammar", "audio", "reading"])
def test_the_four_card_commands_carry_the_option(command):
    """All of them produce cards, all of them can give one back damaged."""
    args = build_parser_args(command)
    assert args.proofread == "drop"


def test_a_command_without_the_option_falls_back_on_the_setting():
    """`maintain` writes straight into Anki: no TSV, no output option."""
    assert proofreading.resolve(argparse.Namespace()) == "ask"


def test_the_four_positions_go_round():
    assert [proofreading.cycle() for _ in range(5)] == [
        "keep", "tag", "drop", "ask", "keep"]


# ── Marking a card ────────────────────────────────────────────────────────────

def test_marking_does_not_touch_the_tags_field():
    """The defect is held, not set, until the sorting decides."""
    c = {"Expression": "みず", "Tags": "Level::N5"}
    proofreading.mark([c], proofreading.TRANSLATION_TAG, UNALIGNED)
    assert c["Tags"] == "Level::N5"
    assert proofreading.tags([c]) == [proofreading.TRANSLATION_TAG]


def test_the_tag_is_set_beside_the_others():
    """The Level tag of the card is not wiped: the defect is added."""
    c = {"Expression": "みず", "Tags": "Level::N5"}
    proofreading.mark([c], proofreading.TRANSLATION_TAG, UNALIGNED)
    proofreading.apply_tags([c])
    assert c["Tags"] == f"Level::N5 {proofreading.TRANSLATION_TAG}"


def test_two_defects_make_two_tags_not_the_same_one_twice():
    c = {"Expression": "みず"}
    proofreading.mark([c], proofreading.TRANSLATION_TAG, UNALIGNED)
    proofreading.mark([c], proofreading.TRANSLATION_TAG, UNALIGNED)
    proofreading.mark([c], proofreading.CHOICES_TAG, "right answer duplicated")
    proofreading.apply_tags([c])
    assert c["Tags"] == f"{proofreading.TRANSLATION_TAG} {proofreading.CHOICES_TAG}"


def test_a_repeated_reason_is_said_only_once():
    """Fifteen cards landing on the same translation have only one reason."""
    assert proofreading.reasons(batch()) == UNALIGNED


def test_a_sound_card_carries_nothing():
    cards = batch()
    assert proofreading.marked(cards) == cards[:2]
    assert "Tags" not in cards[2]


# ── The sorting ───────────────────────────────────────────────────────────────

def test_nothing_to_decide_asks_nothing(monkeypatch):
    """The "ask" mode only puts its question when it has an object."""
    monkeypatch.setattr(exporter, "choose",
                        lambda *a, **k: pytest.fail("nothing to ask about"))
    cards = [card("みず"), card("ひ")]
    assert proofreading.sort_out(cards) == (cards, [])


def test_kept_they_all_go_out_and_without_a_tag(monkeypatch):
    """"keep" taken literally: nothing dropped, and no tag written."""
    monkeypatch.setenv(proofreading.ENV_VAR, "keep")
    cards = batch()
    assert proofreading.sort_out(cards) == (cards, [])
    assert all("Tags" not in c for c in cards)


def test_tagged_they_go_out_with_the_defect(monkeypatch):
    monkeypatch.setenv(proofreading.ENV_VAR, "tag")
    cards = batch()
    assert proofreading.sort_out(cards) == (cards, [])
    assert [c.get("Tags", "") for c in cards] == [
        proofreading.TRANSLATION_TAG, proofreading.TRANSLATION_TAG, ""]


def test_dropped_they_leave_the_batch(monkeypatch):
    monkeypatch.setenv(proofreading.ENV_VAR, "drop")
    cards = batch()
    kept, dropped = proofreading.sort_out(cards)
    assert [c["Expression"] for c in kept] == ["き"]
    assert [c["Expression"] for c in dropped] == ["みず", "ひ"]


def test_the_question_says_how_many_and_why(monkeypatch, capsys):
    """The count and the reasons head the question, the options follow."""
    monkeypatch.setattr(console, "read_line", lambda: "k")
    kept, dropped = proofreading.sort_out(batch())
    assert len(kept) == 3 and dropped == []
    assert all("Tags" not in c for c in kept)
    asked = capsys.readouterr().out
    assert f"2 cards to proofread ({UNALIGNED})" in asked
    assert "d. drop them\n     k. keep them\n     t. tag them" in asked


def test_the_question_can_be_answered_with_tag(monkeypatch):
    monkeypatch.setattr(console, "read_line", lambda: "t")
    cards = batch()
    assert proofreading.sort_out(cards) == (cards, [])
    assert proofreading.TRANSLATION_TAG in cards[0]["Tags"]


def test_outside_a_terminal_they_are_tagged(monkeypatch):
    """No one to answer: nothing paid for is dropped, and as no one read the
    "!!" either, the cards are tagged rather than just kept."""
    def eof():
        raise EOFError

    monkeypatch.setattr(console, "read_line", eof)
    cards = batch()
    assert proofreading.sort_out(cards) == (cards, [])
    assert proofreading.TRANSLATION_TAG in cards[0]["Tags"]


def test_under_yes_they_are_tagged_as_well(monkeypatch):
    """`--yes` has nobody reading the "!!" either: the same answer."""
    def waited():
        raise AssertionError("an answer was waited for")

    monkeypatch.setattr(console, "read_line", waited)
    cards = batch()
    with exporter.unattended(True):
        assert proofreading.sort_out(cards) == (cards, [])
    assert proofreading.TRANSLATION_TAG in cards[0]["Tags"]


# ── The summary ───────────────────────────────────────────────────────────────

def test_the_summary_names_the_tag_and_the_reason():
    cards = batch()
    proofreading.apply_tags(cards)
    assert proofreading.summary(cards, []) == [
        f'   2 cards to proofread, tagged "{proofreading.TRANSLATION_TAG}" '
        f"({UNALIGNED})"]


def test_the_summary_says_when_nothing_is_tagged():
    """With no tag, the summary is the only place naming those cards: it must not
    announce a tag the deck lacks."""
    assert proofreading.summary(batch(), []) == [
        f"   2 cards to proofread, kept without a tag ({UNALIGNED})"]


def test_the_reasons_and_their_fragments_are_said_on_the_screen_language(monkeypatch):
    """A reason is recorded in English and translated where it is said; the
    fragment agrees with the count, as French does (`gardée`, `gardées`)."""
    i18n.use("fr")
    monkeypatch.setitem(i18n._catalogue, "one|kept without a tag", "gardée sans tag")
    monkeypatch.setitem(i18n._catalogue, "many|kept without a tag", "gardées sans tag")
    cards = batch()

    assert proofreading.reasons(cards) == "traduction non alignée"
    assert "gardée sans tag (traduction non alignée)" in proofreading.summary(cards[:1], [])[0]
    assert "gardées sans tag (traduction non alignée)" in proofreading.summary(cards, [])[0]


@pytest.mark.parametrize("lang", [name for name in i18n.available()
                                  if name != i18n.SOURCE])
def test_every_reason_a_card_is_marked_for_has_its_translation(lang):
    """Held in English and translated by `reasons` through a variable, which the
    scan of `tests/test_i18n.py` cannot see: listed here by hand."""
    from kotogen.generators import audio, deck_story

    table = i18n._load(lang)
    wanted = [proofreading.UNALIGNED_TRANSLATION, proofreading.DUPLICATED_ANSWER,
              audio.MISSING_TRANSCRIPT, deck_story.TOO_HARD]
    assert [reason for reason in wanted if reason not in table] == []


def test_the_summary_says_what_was_dropped():
    cards = batch()
    assert proofreading.summary([cards[2]], cards[:2]) == [
        f"   2 cards to proofread dropped ({UNALIGNED})"]


def test_with_no_defect_the_summary_stays_silent():
    assert proofreading.summary([card("みず")], []) == []


# ── The TSV, which is what gets imported ──────────────────────────────────────

def test_a_dropped_card_leaves_the_file_too(monkeypatch, tmp_path, capsys):
    """Otherwise the file holds cards the summary does not count."""
    monkeypatch.setenv(proofreading.ENV_VAR, "drop")
    tsv = tmp_path / "reading.tsv"
    cards = batch()
    append_cards(tsv, cards, FIELDS, "Japanese::Reading", "Reading")

    finish(cards, FIELDS, args_for(), tsv, preview=[])

    lines = [l for l in tsv.read_text(encoding="utf-8").splitlines()
             if not l.startswith("#")]
    assert [l.split("\t")[0] for l in lines] == ["き"]
    assert "1 card ->" in capsys.readouterr().out


def test_the_cards_of_an_earlier_pass_survive(monkeypatch, tmp_path):
    """`--output` may name a file cards were APPENDED to: earlier ones stay."""
    monkeypatch.setenv(proofreading.ENV_VAR, "drop")
    tsv = tmp_path / "shared.tsv"
    earlier = [card("そら"), card("やま")]
    append_cards(tsv, earlier, FIELDS, "Japanese::Reading", "Reading")
    cards = batch()
    append_cards(tsv, cards, FIELDS, "Japanese::Reading", "Reading")

    finish(cards, FIELDS, args_for(), tsv, preview=[])

    lines = [l for l in tsv.read_text(encoding="utf-8").splitlines()
             if not l.startswith("#")]
    assert [l.split("\t")[0] for l in lines] == ["そら", "やま", "き"]


def test_a_missing_file_does_not_fail_the_pass(monkeypatch, tmp_path):
    """No batch written (a direct send, a failure on the first call): nothing to
    take out."""
    monkeypatch.setenv(proofreading.ENV_VAR, "drop")
    exporter.remove_cards(tmp_path / "never-written.tsv", batch(), FIELDS)


# ── The closing block ─────────────────────────────────────────────────────────

def test_the_dropped_ones_do_not_go_into_anki(monkeypatch, tmp_path, capsys):
    sent: list = []

    monkeypatch.setenv(proofreading.ENV_VAR, "drop")
    monkeypatch.setattr(connect, "status", lambda **k: FakeStatus(True))
    monkeypatch.setattr(send, "anki",
                        lambda action, notes=None, **p: sent.extend(notes or []) or [1])
    finish(batch(), FIELDS, args_for(send=True), tmp_path / "out.tsv", preview=[])

    assert [n["fields"]["Expression"] for n in sent] == ["き"]
    assert "2 cards to proofread dropped" in capsys.readouterr().out


def test_the_kept_ones_go_out_without_a_tag(monkeypatch, tmp_path, capsys):
    sent: list = []

    monkeypatch.setenv(proofreading.ENV_VAR, "keep")
    monkeypatch.setattr(connect, "status", lambda **k: FakeStatus(True))
    monkeypatch.setattr(send, "anki",
                        lambda action, notes=None, **p: sent.extend(notes or []) or [1, 2, 3])
    finish(batch(), FIELDS, args_for(send=True), tmp_path / "out.tsv", preview=[])

    assert [n["tags"] for n in sent] == [[], [], []]
    assert "kept without a tag" in capsys.readouterr().out


def test_the_tagged_ones_go_out_tagged(monkeypatch, tmp_path, capsys):
    sent: list = []

    monkeypatch.setenv(proofreading.ENV_VAR, "tag")
    monkeypatch.setattr(connect, "status", lambda **k: FakeStatus(True))
    monkeypatch.setattr(send, "anki",
                        lambda action, notes=None, **p: sent.extend(notes or []) or [1, 2, 3])
    finish(batch(), FIELDS, args_for(send=True), tmp_path / "out.tsv", preview=[])

    assert [n["tags"] for n in sent] == [
        [proofreading.TRANSLATION_TAG], [proofreading.TRANSLATION_TAG], []]
    assert proofreading.TRANSLATION_TAG in capsys.readouterr().out


def test_the_preview_shows_only_what_goes_out(monkeypatch, tmp_path, capsys):
    """A card dropped late is in neither the file nor the preview."""
    monkeypatch.setenv(proofreading.ENV_VAR, "drop")
    finish(batch(), FIELDS, args_for(), tmp_path / "out.tsv",
           preview=lambda cards: [f"  {c['Expression']}" for c in cards])
    shown = capsys.readouterr().out
    assert "き" in shown
    assert "みず" not in shown


def test_the_marking_does_not_go_out_in_the_field(monkeypatch, tmp_path):
    """The defect lives on the card, not in the note: an underscored key is not
    a field, and the TSV keeps no trace of it."""
    monkeypatch.setenv(proofreading.ENV_VAR, "keep")
    tsv = tmp_path / "out.tsv"
    cards = batch()
    append_cards(tsv, cards, FIELDS, "Japanese::Reading", "Reading")
    content = tsv.read_text(encoding="utf-8")
    assert proofreading.KEY_REASON not in content
    assert proofreading.KEY_TAGS not in content
    assert UNALIGNED not in content
    assert proofreading.TAG_PREFIX not in content


def test_the_tag_asked_for_reaches_the_file_already_written(monkeypatch, tmp_path):
    """The line was written before the sorting set the tag: the file is gone back
    over, and the cards of an earlier pass do not move."""
    monkeypatch.setenv(proofreading.ENV_VAR, "tag")
    tsv = tmp_path / "shared.tsv"
    earlier = [card("そら")]
    append_cards(tsv, earlier, FIELDS, "Japanese::Reading", "Reading")
    cards = batch()
    append_cards(tsv, cards, FIELDS, "Japanese::Reading", "Reading")

    finish(cards, FIELDS, args_for(), tsv, preview=[])

    lines = [l for l in tsv.read_text(encoding="utf-8").splitlines()
             if not l.startswith("#")]
    assert [l.split("\t")[0] for l in lines] == ["そら", "みず", "ひ", "き"]
    assert [l.split("\t")[-1] for l in lines] == [
        "", proofreading.TRANSLATION_TAG, proofreading.TRANSLATION_TAG, ""]


def _json_cards(path) -> list[dict]:
    """The cards of a JSON Lines file, its header line left out."""
    return [json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()[1:]]


def test_a_dropped_card_leaves_a_json_file_too(monkeypatch, tmp_path):
    """Written as it goes like the TSV, JSON Lines is gone back over too."""
    monkeypatch.setenv(proofreading.ENV_VAR, "drop")
    out = tmp_path / "reading.jsonl"
    cards = batch()
    append_cards(out, cards, FIELDS, "Japanese::Reading", "Reading")

    finish(cards, FIELDS, args_for(), out, preview=[])

    assert [c["fields"]["Expression"] for c in _json_cards(out)] == ["き"]


def test_the_tag_asked_for_reaches_a_json_file_too(monkeypatch, tmp_path):
    monkeypatch.setenv(proofreading.ENV_VAR, "tag")
    out = tmp_path / "shared.jsonl"
    append_cards(out, [card("そら")], FIELDS, "Japanese::Reading", "Reading")
    cards = batch()
    append_cards(out, cards, FIELDS, "Japanese::Reading", "Reading")

    finish(cards, FIELDS, args_for(), out, preview=[])

    assert [c["tags"] for c in _json_cards(out)] == [
        [], [proofreading.TRANSLATION_TAG], [proofreading.TRANSLATION_TAG], []]


def test_kept_the_file_does_not_move(monkeypatch, tmp_path):
    """Nothing to go back over: what was written along the way is right."""
    monkeypatch.setenv(proofreading.ENV_VAR, "keep")
    tsv = tmp_path / "out.tsv"
    cards = batch()
    append_cards(tsv, cards, FIELDS, "Japanese::Reading", "Reading")
    written = tsv.read_text(encoding="utf-8")

    finish(cards, FIELDS, args_for(), tsv, preview=[])

    assert tsv.read_text(encoding="utf-8") == written


@pytest.mark.parametrize("lang", [name for name in i18n.available()
                                  if name != i18n.SOURCE])
def test_every_table_names_each_mode_of_the_proofreading(lang):
    """The settings screen shows the mode in force through `describe`."""
    table = i18n._load(lang)
    assert [mode for mode in proofreading.MODES if mode not in table] == []
