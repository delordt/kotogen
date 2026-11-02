"""The "lone kanji that is not a word" filter: the deterministic pre-filter, and
the AI verdict read from a faked client."""

import pytest

from kotogen import kanji_word


class FakeClient:
    """Fakes AIClient: returns a canned JSON result and records the calls."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def chat_json(self, system, user):
        self.calls.append({"system": system, "user": user})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class NoClient:
    """A client that fails if called: proves no candidate was ever sent."""

    def chat_json(self, system, user):  # pragma: no cover - must never be called
        raise AssertionError("the AI should not have been asked")


# ── The deterministic pre-filter ──────────────────────────────────────────────

@pytest.mark.parametrize("expression", [
    "語",
    "語[ご]",
    "  語[ご]  ",
    "<b>語[ご]</b>",
    "々",
])
def test_is_single_kanji_accepts_lone_kanji(expression):
    assert kanji_word.is_single_kanji(expression)


@pytest.mark.parametrize("expression", [
    "日本語[にほんご]",
    "食[た]べる",
    "かさ",
    "ローマ 字[じ]",
    "A",
    "",
])
def test_is_single_kanji_rejects_words(expression):
    assert not kanji_word.is_single_kanji(expression)


def test_not_words_skips_ai_without_candidates():
    assert kanji_word.not_words(NoClient(), ["食[た]べる", "かさ"]) == {}


# ── The AI verdict ────────────────────────────────────────────────────────────

def test_not_words_keeps_only_the_non_words():
    client = FakeClient([
        {"kanji": "語", "word": False, "reason": "suffixe", "example": "日本語"},
        {"kanji": "木", "word": True, "reason": "", "example": ""},
    ])
    flagged = kanji_word.not_words(client, ["語[ご]", "木[き]", "食[た]べる"])
    assert flagged == {"語[ご]": ("suffixe", "日本語")}
    assert len(client.calls) == 1
    assert "語" in client.calls[0]["user"] and "木" in client.calls[0]["user"]
    assert "食" not in client.calls[0]["user"]


def test_not_words_ignores_unjudged_candidates():
    """A kanji missing from the answer is not judged: nothing is offered."""
    client = FakeClient([{"kanji": "語", "word": False, "reason": "suffixe", "example": ""}])
    flagged = kanji_word.not_words(client, ["語[ご]", "的[てき]"])
    assert list(flagged) == ["語[ご]"]


def test_not_words_treats_missing_verdict_key_as_a_word():
    client = FakeClient([{"kanji": "語", "reason": "…"}])
    assert kanji_word.not_words(client, ["語[ご]"]) == {}


def test_not_words_returns_nothing_when_the_ai_fails(capsys):
    client = FakeClient(RuntimeError("timeout"))
    assert kanji_word.not_words(client, ["語[ご]"]) == {}
    assert "timeout" in capsys.readouterr().err


def test_not_words_flags_every_form_of_the_same_kanji():
    client = FakeClient([{"kanji": "語", "word": False, "reason": "suffixe", "example": "日本語"}])
    flagged = kanji_word.not_words(client, ["語", "語[ご]"])
    assert set(flagged) == {"語", "語[ご]"}


# ── Integration: generation and review ────────────────────────────────────────

SUFFIX_VERDICT = [{"kanji": "語", "word": False, "reason": "suffixe", "example": "日本語"}]

CARDS = [
    {"Expression": "語[ご]", "Translation": "Langue"},
    {"Expression": "木[き]", "Translation": "Arbre"},
]


def _answers(monkeypatch, *replies):
    """Fakes the user's successive answers; EOFError once they run out."""
    queue = list(replies)
    monkeypatch.setattr("builtins.input", lambda *a: queue.pop(0) if queue else _eof())


def _eof():
    raise EOFError


def test_generation_drops_the_card_on_demand(monkeypatch):
    from kotogen.generators import vocab

    _answers(monkeypatch, "r")
    kept, dropped = vocab._review_single_kanji(FakeClient(SUFFIX_VERDICT), CARDS)
    assert [c["Expression"] for c in kept] == ["木[き]"]
    assert dropped[0]["_reason"] == "lone kanji, not a word"


def test_generation_keeps_the_card_if_asked(monkeypatch):
    from kotogen.generators import vocab

    _answers(monkeypatch, "c")
    kept, dropped = vocab._review_single_kanji(FakeClient(SUFFIX_VERDICT), CARDS)
    assert [c["Expression"] for c in kept] == ["語[ご]", "木[き]"]
    assert dropped == []


def test_generation_drops_the_card_without_a_dialog(monkeypatch):
    """Input redirected (a script, a pipe): the card is dropped, not made."""
    from kotogen.generators import vocab

    _answers(monkeypatch)
    kept, _ = vocab._review_single_kanji(FakeClient(SUFFIX_VERDICT), CARDS)
    assert [c["Expression"] for c in kept] == ["木[き]"]


def test_generation_says_why_the_kanji_is_no_word(monkeypatch, capsys):
    """The reason and the example the model gave, on the line that asks."""
    from kotogen.generators import vocab

    _answers(monkeypatch, "r")
    vocab._review_single_kanji(FakeClient(SUFFIX_VERDICT), CARDS)
    assert "not a vocabulary word (suffixe, e.g. 日本語)" in capsys.readouterr().err


def test_a_long_example_stays_off_the_line():
    assert kanji_word.explained("suffix", "日本語") == "suffix, e.g. 日本語"
    assert kanji_word.explained("suffix", "日本語の文法を学ぶ本") == "suffix"
    assert kanji_word.explained("", "日本語") == ""


def _note(expression="語[ご]", note_id=42):
    return {"id": note_id, "tags": [], "fields": {"Expression": expression}}


@pytest.fixture
def lone_kanji(monkeypatch):
    """The lone kanji module with nowhere to move a kanji to, and a run of its own."""
    from kotogen.anki.maintain import lone_kanji

    monkeypatch.setattr(lone_kanji, "kanji_deck", lambda: None)
    monkeypatch.setattr(lone_kanji, "moving", {})
    monkeypatch.setattr(lone_kanji, "held_notes", set())
    return lone_kanji


def _kanji_deck(monkeypatch, lone_kanji, carded=()):
    """A profile with a kanji deck, holding the cards of `carded`."""
    monkeypatch.setattr(lone_kanji, "kanji_deck", lambda: ("Japanese::Kanji", "Kanji"))
    monkeypatch.setattr(lone_kanji.kanji_cards, "carded", lambda known, notetype: set(carded))


def test_review_deletes_the_note_after_confirmation(monkeypatch, lone_kanji):
    deleted = []
    monkeypatch.setattr(lone_kanji.marks, "delete_notes", deleted.extend)

    _answers(monkeypatch, "d", "y")
    assert (lone_kanji.offer_lone_kanji(FakeClient(SUFFIX_VERDICT), _note(), False)
            == lone_kanji.DELETED)
    assert deleted == [42]


@pytest.mark.parametrize("replies", [("k",), ("d", "n"), ()])
def test_review_keeps_the_note_unless_explicitly_confirmed(monkeypatch, lone_kanji, replies):
    monkeypatch.setattr(lone_kanji.marks, "delete_notes",
                        lambda ids: pytest.fail("unexpected deletion"))

    _answers(monkeypatch, *replies)
    assert (lone_kanji.offer_lone_kanji(FakeClient(SUFFIX_VERDICT), _note(), False)
            == lone_kanji.KEPT)


@pytest.mark.parametrize("replies", [("k",), ("d", "n")])
def test_a_card_kept_no_longer_waits_for_a_decision(monkeypatch, lone_kanji, replies):
    """The `Category::ToReview` of an automatic run comes off with the answer;
    a card that never had it is left alone."""
    removed = []
    monkeypatch.setattr(lone_kanji.marks, "apply_changes",
                        lambda note_id, fields, add, remove: removed.append((note_id, remove)))
    held = {**_note(), "tags": [lone_kanji.CATEGORY_TAG_TODO]}
    for note in (held, _note(note_id=43)):
        _answers(monkeypatch, *replies)
        assert (lone_kanji.offer_lone_kanji(FakeClient(SUFFIX_VERDICT), note, False)
                == lone_kanji.KEPT)
    assert removed == [(42, [lone_kanji.CATEGORY_TAG_TODO])]


@pytest.mark.parametrize("replies", [("k",), ("d", "n")])
def test_a_card_kept_then_put_off_is_tagged_again(monkeypatch, lone_kanji, replies):
    """The note can come back in the same run under another flag: once its
    `Category::ToReview` is off in Anki, a `[l] later` has to lay it again."""
    calls = []
    monkeypatch.setattr(lone_kanji.marks, "apply_changes",
                        lambda note_id, fields, add, remove: calls.append((add, remove)))
    note = {**_note(), "tags": [lone_kanji.CATEGORY_TAG_TODO]}
    _answers(monkeypatch, *replies)
    assert (lone_kanji.offer_lone_kanji(FakeClient(SUFFIX_VERDICT), note, False)
            == lone_kanji.KEPT)
    _answers(monkeypatch, "l")
    assert lone_kanji.offer_category_fix(note, ("grammar", ""), False) == lone_kanji.HELD
    assert calls[-1] == ([lone_kanji.CATEGORY_TAG_TODO], [])
    assert note["tags"] == [lone_kanji.CATEGORY_TAG_TODO]


def test_tagging_a_category_keeps_the_tags_of_the_note_in_step(monkeypatch, lone_kanji):
    monkeypatch.setattr(lone_kanji.marks, "apply_changes", lambda *a: None)
    note = {**_note(), "tags": ["N4", lone_kanji.CATEGORY_TAG_TODO]}
    lone_kanji._tag_category(note, lone_kanji.CATEGORY_TAG_KEPT)
    assert note["tags"] == ["N4", lone_kanji.CATEGORY_TAG_KEPT]
    _answers(monkeypatch, "l")
    lone_kanji.offer_category_fix(note, ("grammar", ""), False)
    assert note["tags"] == ["N4", lone_kanji.CATEGORY_TAG_TODO]


def test_auto_mode_holds_the_note_without_a_kanji_deck(monkeypatch, lone_kanji):
    """Nowhere to move the kanji: the deletion still waits for you, the note
    tagged and counted like the other cards held."""
    monkeypatch.setattr(lone_kanji.marks, "delete_notes",
                        lambda ids: pytest.fail("unexpected deletion"))
    tags = _capture_tags(monkeypatch, lone_kanji)
    assert lone_kanji.offer_lone_kanji(FakeClient(SUFFIX_VERDICT), _note(), True) == lone_kanji.HELD
    assert lone_kanji.held_notes == {42}
    assert tags == [(42, [lone_kanji.CATEGORY_TAG_TODO])]
    assert lone_kanji.moving == {}


def test_review_ignores_real_words(lone_kanji):
    assert lone_kanji.offer_lone_kanji(NoClient(), _note("日本語[にほんご]"), False) == lone_kanji.KEPT


def test_review_says_why_the_kanji_is_no_word(monkeypatch, lone_kanji, capsys):
    _answers(monkeypatch, "k")
    lone_kanji.offer_lone_kanji(FakeClient(SUFFIX_VERDICT), _note(), False)
    assert "on its own (suffixe, e.g. 日本語)" in capsys.readouterr().out


# ── Moving a lone kanji to the kanji deck ─────────────────────────────────────

def test_review_moves_the_kanji_on_confirmation(monkeypatch, lone_kanji, capsys):
    """The card is queued for the end of the run, and the note stays until then."""
    _kanji_deck(monkeypatch, lone_kanji)
    monkeypatch.setattr(lone_kanji.marks, "delete_notes",
                        lambda ids: pytest.fail("deleted too soon"))

    _answers(monkeypatch, "m", "y")
    assert (lone_kanji.offer_lone_kanji(FakeClient(SUFFIX_VERDICT), _note(), False)
            == lone_kanji.MOVED)
    assert lone_kanji.moving == {"語": [42]}
    assert "m. move it to the kanji deck" in capsys.readouterr().out


@pytest.mark.parametrize("replies", [("m", "n"), ("k",), ()])
def test_review_moves_nothing_unless_confirmed(monkeypatch, lone_kanji, replies):
    _kanji_deck(monkeypatch, lone_kanji)
    _answers(monkeypatch, *replies)
    assert (lone_kanji.offer_lone_kanji(FakeClient(SUFFIX_VERDICT), _note(), False)
            == lone_kanji.KEPT)
    assert lone_kanji.moving == {}


def test_review_offers_no_move_for_a_kanji_with_a_card(monkeypatch, lone_kanji, capsys):
    """Its card is in the kanji deck already: deleting the note loses nothing."""
    _kanji_deck(monkeypatch, lone_kanji, carded={"語"})
    _answers(monkeypatch)
    assert (lone_kanji.offer_lone_kanji(FakeClient(SUFFIX_VERDICT), _note(), False)
            == lone_kanji.KEPT)
    out = capsys.readouterr().out
    assert "already in the kanji deck" in out
    assert "[m]" not in out


def _capture_tags(monkeypatch, lone_kanji):
    calls = []
    monkeypatch.setattr(lone_kanji.marks, "apply_changes",
                        lambda note_id, fields, add, remove: calls.append((note_id, add)))
    return calls


def test_auto_mode_makes_the_card_and_holds_the_note(monkeypatch, lone_kanji):
    """A card made is easy to undo, a deleted note is not."""
    _kanji_deck(monkeypatch, lone_kanji)
    tags = _capture_tags(monkeypatch, lone_kanji)
    assert lone_kanji.offer_lone_kanji(FakeClient(SUFFIX_VERDICT), _note(), True) == lone_kanji.HELD
    assert lone_kanji.moving == {"語": []}
    assert lone_kanji.held_notes == {42}
    assert tags == [(42, [lone_kanji.CATEGORY_TAG_TODO])]


def test_auto_mode_holds_a_kanji_with_a_card_and_makes_none(monkeypatch, lone_kanji):
    _kanji_deck(monkeypatch, lone_kanji, carded={"語"})
    _capture_tags(monkeypatch, lone_kanji)
    assert lone_kanji.offer_lone_kanji(FakeClient(SUFFIX_VERDICT), _note(), True) == lone_kanji.HELD
    assert lone_kanji.moving == {}
    assert lone_kanji.held_notes == {42}


def test_the_move_deletes_only_the_notes_whose_kanji_went_in(monkeypatch, lone_kanji, capsys):
    _kanji_deck(monkeypatch, lone_kanji)
    lone_kanji.moving.update({"語": [42], "的": [43, 44], "勉": []})
    asked = []
    monkeypatch.setattr(lone_kanji.kanji_cards, "generate_into",
                        lambda client, chars, deck, notetype: asked.append(chars) or {"語", "勉"})
    deleted = []
    monkeypatch.setattr(lone_kanji.marks, "delete_notes", deleted.extend)

    assert lone_kanji.move_to_kanji_deck(object()) == 1
    assert asked == [["語", "的", "勉"]]
    assert deleted == [42]
    assert lone_kanji.moving == {}
    assert "的" in capsys.readouterr().out


def test_the_move_costs_nothing_without_a_kanji(monkeypatch, lone_kanji):
    monkeypatch.setattr(lone_kanji.kanji_cards, "generate_into",
                        lambda *a: pytest.fail("the model was asked"))
    assert lone_kanji.move_to_kanji_deck(object()) == 0
