"""Maintenance: selecting the targets (--only / --yes) and handling the duplicates."""

import pytest

from conftest import as_note
from kotogen import prompts
from kotogen.anki import connect
from kotogen.anki.connect import EditorOpen
from kotogen.anki.maintain import flag_pass, lone_kanji, marks, review
from kotogen.anki.maintain.review import _parse_auto, _parse_selection
from kotogen.maintenance import kinds
from kotogen.maintenance.review import (
    _STOP_WORDS,
    CATEGORY_TAG_KEPT,
    CATEGORY_TAG_TODO,
    _field,
    _find_duplicate_candidates,
    _identical_words,
    _normalise_proposal,
    _propose_differentiation,
    _proposed_deletion,
    _read_group_proposal,
    _still_told_apart,
    _tokens,
    _translation_group,
    read_category,
)

# ── Selecting the targets ─────────────────────────────────────────────────────

def test_no_selection_processes_everything():
    assert _parse_selection(None) == ([1, 2, 3, 4, 5, 6, 7], True)


def test_colours_numbers_and_leech_are_interchangeable():
    assert _parse_selection(["red", "4", "leech"]) == ([1, 4], True)


def test_unknown_target_stops_the_run():
    with pytest.raises(SystemExit) as err:
        _parse_selection(["crimson"])
    assert "--only" in str(err.value)


def test_without_yes_nothing_is_automatic():
    flags, leech = _parse_selection(None)
    assert _parse_auto(None, flags, leech) == (set(), False)


def test_bare_yes_automates_every_processed_target():
    flags, leech = _parse_selection(["red", "leech"])
    assert _parse_auto([], flags, leech) == ({1}, True)


def test_yes_with_targets_automates_only_those():
    flags, leech = _parse_selection(None)
    assert _parse_auto(["red", "pink"], flags, leech) == ({1, 5}, False)


@pytest.mark.parametrize("yes, expected", [
    (["blue"], (set(), False)),          # flag not handled
    (["leech"], (set(), False)),         # leech not handled
    (["red", "blue"], ({1}, False)),     # only the handled target is kept
])
def test_auto_never_reaches_beyond_the_processed_targets(yes, expected):
    """`--yes blue` while --only does not handle blue must automate nothing."""
    flags, leech = _parse_selection(["red"])
    assert _parse_auto(yes, flags, leech) == expected


# ── Duplicates: tell apart, or turn down the card that has no place ──────────

def _note(note_id: int, expression: str, translation: str) -> dict:
    """A card as the maintenance reads one, the id of its note as its `id`."""
    fields = {"Expression": expression, "Translation": translation, "Notes": ""}
    return {"id": note_id, "tags": [], "fields": fields}


CARD1 = _note(1, "日本語[にほんご]", "Langue japonaise")
CARD2 = _note(2, "日本語[にっぽんご]", "Langue japonaise")


class _Client:
    """Faked AIClient: always hands back the same JSON answer, without the network."""

    def __init__(self, result):
        self.result = result
        self.user = ""

    def chat_json(self, system, user):
        self.user = user
        return self.result


def _answers(monkeypatch, *replies):
    """Successive answers of the user; EOFError once they run out."""
    queue = list(replies)

    def _next(*_args):
        if not queue:
            raise EOFError
        return queue.pop(0)

    monkeypatch.setattr("builtins.input", _next)


def _refuse_deletion(monkeypatch):
    monkeypatch.setattr(marks, "delete_notes",
                        lambda ids: pytest.fail(f"unexpected deletion: {ids}"))


def _one_confirmed_duplicate(monkeypatch):
    """CARD2 is the only candidate, judged a duplicate by the AI."""
    monkeypatch.setattr(flag_pass, "_find_duplicate_candidates",
                        lambda note, all_notes: [(CARD2, ["same reading"], 100)])
    monkeypatch.setattr(flag_pass, "_judge_duplicates",
                        lambda client, note, candidates: {0: ("duplicate", "même mot")})


@pytest.mark.parametrize("raw, expected", [
    (2, 2), ("1", 1), ("card2", 2), ("card 1", 1),   # the model phrases as it likes
    (None, 0), ("", 0), ("none", 0), (0, 0), (3, 0),
])
def test_deletion_target_is_read_from_any_phrasing(raw, expected):
    assert _proposed_deletion({"delete": raw}) == expected


def test_a_distinction_alone_deletes_nothing():
    assert _proposed_deletion({"reason": "…", "card1": {"Notes": "…"}}) == 0


def test_differentiate_still_applies_a_distinction(monkeypatch):
    applied = []
    monkeypatch.setattr(marks, "apply_changes",
                        lambda nid, fields, add, remove: applied.append((nid, fields)))
    _answers(monkeypatch, "y")
    client = _Client({"reason": "lecture emphatique", "card2": {"Notes": "Lecture solennelle"}})
    assert flag_pass._differentiate(client, CARD1, CARD2, auto=False) == "applied"
    assert applied == [(2, {"Notes": "Lecture solennelle"})]


def test_differentiate_deletes_the_extra_card_after_two_confirmations(monkeypatch):
    """When a card has no place, the AI has it turned down rather than inventing a nuance."""
    deleted = []
    monkeypatch.setattr(marks, "delete_notes", deleted.extend)
    _answers(monkeypatch, "d", "y")
    client = _Client({"delete": 2, "reason": "graphie fautive"})
    assert flag_pass._differentiate(client, CARD1, CARD2, auto=False) == "deleted_other"
    assert deleted == [2]


def test_differentiate_signals_that_the_flagged_card_is_gone(monkeypatch):
    """The card too many can be the one carrying the flag: the caller has to know."""
    deleted = []
    monkeypatch.setattr(marks, "delete_notes", deleted.extend)
    _answers(monkeypatch, "d", "y")
    client = _Client({"delete": 1, "reason": "graphie fautive"})
    assert flag_pass._differentiate(client, CARD1, CARD2, auto=False) == "deleted_target"
    assert deleted == [1]


@pytest.mark.parametrize("replies", [("k",), ("d", "n"), ()])
def test_differentiate_keeps_both_cards_unless_explicitly_confirmed(monkeypatch, replies):
    _refuse_deletion(monkeypatch)
    _answers(monkeypatch, *replies)
    client = _Client({"delete": 2, "reason": "graphie fautive"})
    assert flag_pass._differentiate(client, CARD1, CARD2, auto=False) == "none"


def test_auto_never_deletes_and_keeps_the_flag(monkeypatch):
    """A deletion cannot be automated: the flag stays, the decision waits for you."""
    _refuse_deletion(monkeypatch)
    monkeypatch.setattr(marks, "clear_flag",
                        lambda card_id: pytest.fail("flag wrongly removed"))
    _one_confirmed_duplicate(monkeypatch)
    client = _Client({"delete": 2, "reason": "graphie fautive"})
    assert flag_pass._auto_duplicate(7, CARD1, [CARD1, CARD2], client, set()) == (0, 0)


def test_deleting_the_flagged_card_ends_its_examination(monkeypatch):
    """The note deleted, its flag went with it: nothing left to remove."""
    deleted = []
    monkeypatch.setattr(marks, "delete_notes", deleted.extend)
    monkeypatch.setattr(marks, "clear_flag",
                        lambda card_id: pytest.fail("flag wrongly removed"))
    _one_confirmed_duplicate(monkeypatch)
    _answers(monkeypatch, "3", "d", "y")
    client = _Client({"delete": 1, "reason": "graphie fautive"})
    assert flag_pass._process_duplicate(7, CARD1, [CARD1, CARD2], client, auto=False) == (1, 0)
    assert deleted == [1]


# ── Cards out of category (grammar, sentence, fragment) ──────────────────────

GRAMMAR = _note(3, "〜ながら", "Tout en")
GRAMMAR_VERDICT = {"category": {"type": "grammar", "reason": "tournure, pas un mot"}}


def _tagged(note: dict, *tags: str) -> dict:
    return {**note, "tags": list(tags)}


def _capture_tags(monkeypatch) -> list[tuple[int, list[str], list[str]]]:
    """Intercepts the tags laid and removed (no Anki call)."""
    calls: list[tuple[int, list[str], list[str]]] = []
    monkeypatch.setattr(marks, "apply_changes",
                        lambda nid, fields, add, remove: calls.append((nid, add, remove)))
    return calls


@pytest.mark.parametrize("proposal", [
    {},                                              # nothing to report: the normal case
    {"category": None},
    {"category": {"type": "difficult"}},            # type outside the nomenclature
    {"category": "grammar"},                      # not an object
])
def test_a_card_is_only_flagged_on_an_explicit_verdict(proposal):
    """With no usable verdict the card is left alone."""
    assert read_category(GRAMMAR, proposal) is None


def test_the_verdict_carries_its_kind_and_reason():
    assert read_category(GRAMMAR, GRAMMAR_VERDICT) == ("grammar", "tournure, pas un mot")


def test_a_card_you_chose_to_keep_is_never_flagged_again():
    """The `Category::Kept` tag is the trace of a decision: it is not asked again."""
    kept = _tagged(GRAMMAR, CATEGORY_TAG_KEPT)
    assert read_category(kept, GRAMMAR_VERDICT) is None


def test_pending_tag_does_not_silence_the_signal():
    """`Category::ToReview` marks a decision PUT OFF, not taken: the card reports itself again."""
    pending = _tagged(GRAMMAR, CATEGORY_TAG_TODO)
    assert read_category(pending, GRAMMAR_VERDICT) == ("grammar", "tournure, pas un mot")


def test_deleting_a_misplaced_card_takes_two_confirmations(monkeypatch):
    deleted = []
    monkeypatch.setattr(marks, "delete_notes", deleted.extend)
    _capture_tags(monkeypatch)
    _answers(monkeypatch, "d", "y")
    assert lone_kanji.offer_category_fix(_tagged(GRAMMAR), ("grammar", ""), auto=False) == lone_kanji.DELETED
    assert deleted == [3]


@pytest.mark.parametrize("replies, expected_tag, outcome", [
    (("d", "n"), CATEGORY_TAG_TODO, lone_kanji.HELD),   # deletion cancelled
    (("l",), CATEGORY_TAG_TODO, lone_kanji.HELD),       # put off until later
    ((), CATEGORY_TAG_TODO, lone_kanji.HELD),           # EOF (script): the prudent option
    (("k",), CATEGORY_TAG_KEPT, lone_kanji.KEPT),       # kept on purpose
])
def test_a_misplaced_card_is_kept_and_marked_unless_deletion_is_confirmed(
        monkeypatch, replies, expected_tag, outcome):
    """Only a card kept on purpose goes on to be corrected; a held one waits as it is."""
    _refuse_deletion(monkeypatch)
    calls = _capture_tags(monkeypatch)
    _answers(monkeypatch, *replies)
    lone_kanji.held_notes.clear()
    assert lone_kanji.offer_category_fix(_tagged(GRAMMAR), ("grammar", ""), auto=False) == outcome
    assert calls == [(3, [expected_tag], [])]
    assert lone_kanji.held_notes == ({3} if outcome == lone_kanji.HELD else set())


def test_choosing_to_keep_clears_the_pending_mark(monkeypatch):
    """Settling removes the reminder: the two tags would contradict each other."""
    calls = _capture_tags(monkeypatch)
    _answers(monkeypatch, "k")
    pending = _tagged(GRAMMAR, CATEGORY_TAG_TODO)
    lone_kanji.offer_category_fix(pending, ("grammar", ""), auto=False)
    assert calls == [(3, [CATEGORY_TAG_KEPT], [CATEGORY_TAG_TODO])]


def test_automatic_mode_marks_the_card_and_deletes_nothing(monkeypatch):
    """In automatic mode nothing gets deleted, nor corrected: the card waits as it is."""
    _refuse_deletion(monkeypatch)
    calls = _capture_tags(monkeypatch)
    lone_kanji.held_notes.clear()
    assert lone_kanji.offer_category_fix(_tagged(GRAMMAR), ("grammar", ""), auto=True) == lone_kanji.HELD
    assert calls == [(3, [CATEGORY_TAG_TODO], [])]
    assert lone_kanji.held_notes == {3}


def test_a_held_card_keeps_its_flag_and_is_not_corrected(monkeypatch):
    """The correction from the same answer is set aside with the card: applying it
    could be wasted, and clearing the flag would take the card out of the run."""
    monkeypatch.setattr(marks, "find_flagged", lambda notetype, flag: [30])
    monkeypatch.setattr(flag_pass, "anki", lambda action, **kw: (
        [{"cardId": 30, "note": 3}] if action == "cardsInfo" else [as_note(GRAMMAR)]))
    monkeypatch.setattr(lone_kanji, "offer_lone_kanji", lambda *a: lone_kanji.KEPT)
    monkeypatch.setattr(flag_pass, "propose_changes", lambda *a: {
        **GRAMMAR_VERDICT, "fields": {"Translation": "Tout en faisant"}})
    cleared = []
    monkeypatch.setattr(marks, "clear_flag", cleared.append)
    calls = _capture_tags(monkeypatch)
    assert flag_pass.process_flag(None, 1, kinds.VOCAB, True, []) == (0, 0)
    assert calls == [(3, [CATEGORY_TAG_TODO], [])]   # the tag, and nothing else
    assert cleared == []


def test_an_open_editor_stops_the_pass_on_the_first_card(monkeypatch, capsys):
    """Anki refuses every flag while an editing window is open, whatever card it
    shows: the pass stops at the first refusal, said once by `maintain`, rather
    than paying the AI for every card after it."""
    cat, dog = _note(1, "猫[ねこ]", "Chat"), _note(2, "犬[いぬ]", "Chien")
    monkeypatch.setattr(marks, "find_flagged", lambda notetype, flag: [10, 20])

    def anki(action, **kw):
        return ([{"cardId": 10, "note": 1}, {"cardId": 20, "note": 2}] if action == "cardsInfo"
                else [as_note(cat), as_note(dog)] if action == "notesInfo" else None)

    monkeypatch.setattr(flag_pass, "anki", anki)
    monkeypatch.setattr(marks, "anki", anki)
    monkeypatch.setattr(lone_kanji, "offer_lone_kanji", lambda *a: lone_kanji.KEPT)
    asked = []

    def propose(client, action, note, kind):
        asked.append(note["id"])
        return {"changed": True, "reason": "", "fields": {"Translation": "Un chat"}}

    def refuse(card_id):
        raise EditorOpen(connect.EDITOR_OPEN)

    monkeypatch.setattr(flag_pass, "propose_changes", propose)
    monkeypatch.setattr(marks, "clear_flag", refuse)
    with pytest.raises(EditorOpen):
        flag_pass.process_flag(None, 1, kinds.VOCAB, True, [])
    assert asked == [1]
    assert capsys.readouterr().err == ""


def test_anki_closed_mid_pass_stops_it_on_the_first_card(monkeypatch, capsys):
    """Every later write would meet the same closed Anki: no model call is paid
    for a card that can no longer be written."""
    cat, dog = _note(1, "猫[ねこ]", "Chat"), _note(2, "犬[いぬ]", "Chien")
    monkeypatch.setattr(marks, "find_flagged", lambda notetype, flag: [10, 20])

    def anki(action, **kw):
        return ([{"cardId": 10, "note": 1}, {"cardId": 20, "note": 2}] if action == "cardsInfo"
                else [as_note(cat), as_note(dog)] if action == "notesInfo" else None)

    def closed(*a, **k):
        raise ConnectionError(connect.UNREACHABLE)

    monkeypatch.setattr(flag_pass, "anki", anki)
    monkeypatch.setattr(marks, "anki", anki)
    monkeypatch.setattr(lone_kanji, "offer_lone_kanji", lambda *a: lone_kanji.KEPT)
    asked = []
    monkeypatch.setattr(flag_pass, "propose_changes", lambda client, action, note, kind: (
        asked.append(note["id"]) or {"changed": True, "reason": "",
                                     "fields": {"Translation": "Un chat"}}))
    monkeypatch.setattr(marks, "apply_to_passage", closed)
    with pytest.raises(ConnectionError):
        flag_pass.process_flag(None, 1, kinds.VOCAB, True, [])
    assert asked == [1]
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("error", [ConnectionError(connect.UNREACHABLE),
                                   EditorOpen(connect.EDITOR_OPEN)])
def test_a_leech_pass_stops_when_anki_can_no_longer_write(monkeypatch, error):
    from kotogen.anki.maintain import leech as leech_gen

    def card(card_id: int, note_id: int) -> dict:
        fields = {name: {"value": ""} for name in kinds.VOCAB.fields}
        fields["Expression"] = {"value": "学生[がくせい]"}
        return {"cardId": card_id, "note": note_id, "fields": fields}

    def anki(action, **params):
        if action == "cardsInfo":
            return [card(5, 1), card(6, 2)]
        return [] if action == "notesInfo" else None

    def refuse(*a, **k):
        raise error

    asked = []
    monkeypatch.setattr(leech_gen, "anki", anki)
    monkeypatch.setattr(leech_gen, "offer_lone_kanji", lambda *a: lone_kanji.KEPT)
    monkeypatch.setattr(leech_gen, "_propose_simpler", lambda client, note: (
        asked.append(note["id"]) or {"fields": {"Translation": "Élève"}}))
    monkeypatch.setattr(leech_gen, "apply_to_passage", refuse)
    with pytest.raises(type(error)):
        leech_gen._process_true([5, 6], "leech", object(), 21, True, kinds.VOCAB)
    assert asked == [1]


def test_anki_closed_mid_run_still_prints_the_summary(monkeypatch, capsys):
    """What was confirmed before Anki closed is in Anki: the count says so, and the
    run then ends on the reason it stopped."""
    _deck(monkeypatch, {2: 2})
    _without_handling(monkeypatch)

    def closed(*a, **k):
        raise ConnectionError(connect.UNREACHABLE)

    monkeypatch.setattr(flag_pass, "process_flag", closed)
    with pytest.raises(SystemExit) as stop:
        review.run_maintain(_args())
    assert "Done:" in capsys.readouterr().out
    assert "Maintenance interrupted" in str(stop.value)
    assert "AnkiConnect unreachable" in str(stop.value)


def test_the_tags_pass_cannot_erase_a_category_decision():
    """`Category::…` is not in the taxonomy: the pink flag would want to remove it."""
    kept = _tagged(GRAMMAR, CATEGORY_TAG_KEPT, "Noun")
    _fields, add, remove, _reason = _normalise_proposal(kept, {
        "addTags": [CATEGORY_TAG_TODO, "Adverb"],
        "removeTags": [CATEGORY_TAG_KEPT, "Noun"],
    })
    assert add == ["Adverb"]
    assert remove == ["Noun"]


# ── Deletion decided by hand ──────────────────────────────────────────────────

def test_deleting_by_hand_asks_for_confirmation(monkeypatch):
    """The way out of the correction menu, with no AI verdict behind it."""
    deleted = []
    monkeypatch.setattr(marks, "delete_notes", deleted.extend)
    _answers(monkeypatch, "y")
    assert marks.offer_manual_deletion(CARD1) is True
    assert deleted == [1]


@pytest.mark.parametrize("replies", [("n",), ()])   # explicit refusal, then EOF
def test_without_confirmation_the_note_stays(monkeypatch, replies):
    """On a redirected input (EOF), the prudent choice has to win."""
    _refuse_deletion(monkeypatch)
    _answers(monkeypatch, *replies)
    assert marks.offer_manual_deletion(CARD1) is False


# ── Context ───────────────────────────────────────────────────────────────────

def _vocab_note() -> dict:
    fields = {"Expression": "被[かぶ]る", "Translation": "Porter", "Context": "",
              "Notes": "", "Example": "", "ExampleTranslation": ""}
    return {"id": 4, "tags": [], "fields": fields}


def test_the_context_proposed_by_the_ai_is_applied():
    """A field absent from the fields of its kind would be silently thrown away."""
    fields, _add, _remove, _reason = _normalise_proposal(
        _vocab_note(), {"fields": {"Context": "sur la tête"}})
    assert fields == {"Context": "sur la tête"}


def test_the_context_is_not_treated_as_furigana():
    """It is written in the language of the cards, not in Japanese: the furigana
    pipeline would add brackets and spaces to it."""
    fields, *_ = _normalise_proposal(
        _vocab_note(), {"fields": {"Context": "haut du corps"}})
    assert fields["Context"] == "haut du corps"


def test_what_the_ai_proposes_is_stored_as_text():
    """What the model writes comes from an unvetted page: a tag left open reaches
    the field as text, line breaks kept."""
    fields, *_ = _normalise_proposal(_vocab_note(), {"fields": {
        "Notes": "un<br>deux <img src=x onerror=alert(1) "}})
    assert fields["Notes"] == "un<br>deux &lt;img src=x onerror=alert(1) "


def test_an_old_field_is_not_changed_by_its_escaping():
    """A field holding a bare `"`, copied as is by the model, is not a change."""
    note = _vocab_note()
    note["fields"]["Notes"] = 'Dit "porter"'
    fields, *_ = _normalise_proposal(note, {"fields": {"Notes": 'Dit "porter"'}})
    assert fields == {}


def test_a_tag_the_ai_proposes_cannot_end_the_string_it_is_read_in():
    """The templates read `{{Tags}}` between backquotes."""
    _fields, add, _remove, _reason = _normalise_proposal(
        _tagged(GRAMMAR, "Noun"), {"addTags": ["Adverb`${alert(1)}`"]})
    assert add == ["Adverb{alert(1)}"]


@pytest.mark.parametrize("lang", sorted(prompts.languages()))
def test_the_green_flag_knows_it_can_fill_the_context(lang):
    text = (prompts.folder(lang) / "maintain_flag_vocab.md").read_text(encoding="utf-8")
    enrich = text.split("### enrich", 1)[1].split("###", 1)[0]
    assert "Context" in enrich


def _with_context(note: dict, value: str) -> dict:
    note = {**note, "fields": {**note["fields"], "Context": value}}
    return note


def test_the_differentiation_sees_the_context_of_both_cards():
    """Without it in the prompt, the AI proposes one where there already is one."""
    client = _Client({"reason": "…"})
    _propose_differentiation(
        client, _with_context(CARD1, "sur la tête"), _with_context(CARD2, ""))
    assert "sur la tête" in client.user
    assert client.user.count("Context=") == 2   # the missing one counts as much


def test_two_cards_already_told_apart_by_their_context_weigh_less():
    """"Porter" + upper body / on the head no longer asks the same question twice:
    the match stays, its weight does not."""
    def score(ctx1: str, ctx2: str) -> int:
        target = _with_context(_note(1, "着[き]る", "Porter"), ctx1)
        other = _with_context(_note(2, "被[かぶ]る", "Porter"), ctx2)
        (_cand, reasons, points), = _find_duplicate_candidates(target, [other])
        return points

    assert score("", "") > score("haut du corps", "sur la tête")


def test_an_identical_context_tells_nothing_apart():
    target = _with_context(_note(1, "着[き]る", "Porter"), "haut du corps")
    other = _with_context(_note(2, "着用[ちゃくよう]する", "Porter"), "haut du corps")
    (_cand, reasons, _points), = _find_duplicate_candidates(target, [other])
    assert "same translation" in reasons


# ── The language the cards are written in ─────────────────────────────────────
# The translation signal compares two `Translation` fields, written in the
# language of the deck, not of the screen. A French stop list on English text
# keeps `to` and `the`, and two cards asking one question stop looking alike.

def test_the_stop_words_follow_the_language_of_the_cards():
    prompts.use("en")
    assert _tokens("To be hungry") == {"hungry"}
    prompts.use("fr")
    assert _tokens("Avoir faim") == {"avoir", "faim"}


def test_every_language_of_cards_carries_its_stop_words():
    """A language of prompts without a stop list would maintain its decks worse."""
    assert set(prompts.languages()) <= set(_STOP_WORDS)


def test_a_japanese_gloss_is_cut_into_the_words_it_means():
    """No space parts them: the tagger does, keyed by dictionary form so that kana
    and kanji spellings match. Readings, particles and auxiliaries are left out."""
    prompts.use("ja")
    assert _tokens("暑[あつ]くなくて、気持[きも]ちがいい") == {"暑い", "無い", "気持ち", "良い"}
    assert _tokens("たべること") == _tokens("食[た]べること") == {"食べる"}


def _same_translation(target: dict, other: dict) -> list[str]:
    (_cand, reasons, _points), = _find_duplicate_candidates(target, [other])
    return reasons


TO_WORK = _note(1, "勤労[きんろう]", "To work")
WORK_EN = _note(2, "仕事[しごと]", "Work")


def test_an_english_deck_sees_the_same_translation_written_otherwise():
    """`To work` and `Work` are one gloss, hence the same question asked twice."""
    prompts.use("en")
    assert "same translation" in _same_translation(TO_WORK, WORK_EN)


def test_the_french_stop_list_would_only_have_seen_them_close():
    """The same pair on a French list: `to` stays a word, and the glosses differ."""
    prompts.use("fr")
    assert "close translation" in _same_translation(TO_WORK, WORK_EN)


# ── The batch of identical translation (the confusion, opposite of the duplicate) ──

WORK = [
    _note(10, "勤労[きんろう]", "Travail"),
    _note(11, "仕[し]事[ごと]", "Travail"),
    _note(12, "仕事[しごと]", "Travail"),
    _note(13, "作業[さぎょう]", "Travail"),
    _note(14, "労働[ろうどう]", "Travail"),
]
FULLTIME = _note(15, "フルタイム", "Travail à temps plein")


def _contexts(*pairs) -> dict:
    return {"reason": "…", "cards": [{"n": n, "Context": c} for n, c in pairs]}


def test_the_batch_gathers_identical_translations_not_neighbouring_ones():
    """`Travail` and `Travail à temps plein` are told apart by the front already."""
    group = _translation_group(WORK[0], WORK[1:] + [FULLTIME])
    assert [n["id"] for n in group] == [10, 11, 12, 13, 14]


def test_the_batch_reads_the_translation_as_the_front_shows_it():
    """An article, a preposition, a mark or an accent on the front makes another
    question; case and markup do not."""
    see_you = _note(20, "じゃあね", "À plus")
    more = _note(21, "もっと", "Plus")
    cheers = _note(22, "乾杯[かんぱい]", "Santé !")
    health = _note(23, "体調[たいちょう]", "Santé")
    also_more = _note(24, "以上[いじょう]", "<div>plus&nbsp;</div>")
    salty = _note(25, "しょっぱい", "Salé")
    dirty = _note(26, "汚[きたな]い", "Sale")
    notes = [see_you, more, cheers, health, also_more, salty, dirty]
    assert [n["id"] for n in _translation_group(see_you, notes)] == [20]
    assert [n["id"] for n in _translation_group(cheers, notes)] == [22]
    assert [n["id"] for n in _translation_group(more, notes)] == [21, 24]
    assert [n["id"] for n in _translation_group(salty, notes)] == [25]


def test_the_flagged_card_opens_the_batch_and_counts_only_once_in_it():
    group = _translation_group(WORK[0], WORK)
    assert [n["id"] for n in group] == [10, 11, 12, 13, 14]


def test_a_different_furigana_split_is_still_the_same_word():
    """仕[し]事[ごと] and 仕事[しごと]: same reading, same spelling, no call to pay."""
    clusters = _identical_words(WORK)
    assert [[n["id"] for n in c] for c in clusters] == [[11, 12]]


def test_two_homophones_are_not_the_same_word():
    """橋 and 箸 both read はし: it is the spelling that separates them."""
    assert _identical_words([_note(1, "橋[はし]", "Pont"),
                             _note(2, "箸[はし]", "Baguettes")]) == []


def test_the_batch_is_told_apart_in_a_single_call(monkeypatch):
    """Five cards, one call: the contexts only make sense read together."""
    calls = []
    monkeypatch.setattr(marks, "apply_changes", lambda nid, f, a, r: calls.append((nid, f)))
    _answers(monkeypatch, "y")
    client = _Client(_contexts((1, "emploi salarié"), (2, "tâche à accomplir")))
    group = [WORK[0], WORK[3], WORK[4]]
    assert flag_pass._resolve_group(client, group, auto=False) == (2, [], True)
    assert calls == [(10, {"Context": "emploi salarié"}), (13, {"Context": "tâche à accomplir"})]
    for note in group:
        # Every rival in one prompt, so that the contexts exclude one another.
        assert _field(note, "Expression") in client.user


def test_the_batch_is_shown_the_register_badges(monkeypatch):
    """友人 is formal and the question does not say so: the model needs the badge
    to write that into the context."""
    monkeypatch.setattr(marks, "apply_changes", lambda *a: None)
    _answers(monkeypatch, "y")
    badged = dict(WORK[0], tags=["Register::改まった語", "Level::N3"])
    client = _Client(_contexts((2, "tâche")))
    flag_pass._resolve_group(client, [badged, WORK[3]], auto=False)
    assert "Tags=Register::改まった語" in client.user
    assert "Level::N3" not in client.user


def test_a_register_badge_does_not_stand_for_a_context():
    """The badge is on the back: emptying the context of the formal card would
    leave the `Production` front of the batch with two right answers."""
    formal = dict(WORK[0], tags=["Register::改まった語"],
                  fields=dict(WORK[0]["fields"], Context="plus soutenu que 仕事"))
    assert _still_told_apart([formal, WORK[3]], [(formal, {"Context": ""})]) == []


def test_a_duplicate_in_the_batch_is_settled_before_the_contexts(monkeypatch):
    """A context on each of two duplicates would invent a difference."""
    monkeypatch.setattr(marks, "apply_changes",
                        lambda *a: pytest.fail("context laid despite the duplicate"))
    deleted = []
    monkeypatch.setattr(marks, "delete_notes", deleted.extend)
    _answers(monkeypatch, "2", "y")     # keep 仕事[しごと], then confirm
    client = _Client(_contexts((1, "emploi salarié")))
    applied, gone, settled = flag_pass._resolve_group(client, WORK[:3], auto=False)
    assert (applied, gone) == (0, [11])
    assert settled is False             # the batch comes back once the duplicate is settled
    assert deleted == [11]


def test_a_duplicate_left_in_place_suspends_the_batch(monkeypatch):
    _refuse_deletion(monkeypatch)
    monkeypatch.setattr(marks, "apply_changes",
                        lambda *a: pytest.fail("context laid despite the duplicate"))
    _answers(monkeypatch, "l")
    assert flag_pass._resolve_group(_Client({}), WORK[:3], auto=False) == (0, [], False)


def test_in_automatic_mode_a_duplicate_in_the_batch_keeps_the_flag(monkeypatch):
    """No deletion without you, and no context laid over a duplicate."""
    _refuse_deletion(monkeypatch)
    monkeypatch.setattr(marks, "apply_changes",
                        lambda *a: pytest.fail("silent change"))
    assert flag_pass._resolve_group(_Client({}), WORK[:3], auto=True) == (0, [], False)


def test_the_batch_is_also_told_apart_in_automatic_mode(monkeypatch):
    applied = []
    monkeypatch.setattr(marks, "apply_changes", lambda nid, f, a, r: applied.append(nid))
    client = _Client(_contexts((1, "emploi salarié"), (2, "tâche à accomplir")))
    assert flag_pass._resolve_group(client, [WORK[0], WORK[3]], auto=True) == (2, [], True)
    assert applied == [10, 13]


def test_the_batch_never_rewrites_the_expression():
    """Four cards changed at once: a spelling slipped in there would not be seen."""
    changes, _clusters = _read_group_proposal(WORK[:1], {"cards": [
        {"n": 1, "Expression": "勤[つと]め", "Context": "registre soutenu"}]})
    assert [f for _n, f in changes] == [{"Context": "registre soutenu"}]


def test_a_card_translated_too_broadly_leaves_the_batch_by_its_translation():
    """A card translated too broadly is set apart by a right translation, not a context."""
    changes, _clusters = _read_group_proposal(WORK[:1], {"cards": [
        {"n": 1, "Translation": "point essentiel", "Context": ""}]})
    assert [f["Translation"] for _n, f in changes] == ["Point essentiel"]


def test_a_batch_left_with_two_bare_cards_keeps_its_contexts():
    """Dropping both contexts would leave three bare cards with one answer: they stay."""
    told = [dict(WORK[0], fields=dict(WORK[0]["fields"], Context="emploi salarié")),
            dict(WORK[3], fields=dict(WORK[3]["fields"], Context="tâche")),
            WORK[4]]
    changes, _clusters = _read_group_proposal(told, {"cards": [
        {"n": 1, "Context": ""}, {"n": 2, "Context": "", "Notes": "Tâche concrète"}]})
    assert [f for _n, f in changes] == [{"Notes": "Tâche concrète"}]


def test_two_cards_given_one_context_keep_theirs():
    """Two cards given the same context would ask one question twice."""
    told = [dict(n, fields=dict(n["fields"], Context=context))
            for n, context in ((WORK[0], "métal"), (WORK[3], "monnaie"))]
    changes, _clusters = _read_group_proposal(told, {"cards": [
        {"n": 1, "Context": "terme anglais"}, {"n": 2, "Context": "terme anglais"}]})
    assert changes == []


def test_a_card_that_changes_translation_leaves_the_count():
    """A card whose translation changes no longer shares the batch's question."""
    changes, _clusters = _read_group_proposal(WORK[:3], {"cards": [
        {"n": 1, "Translation": "Labeur"}, {"n": 2, "Context": "tâche"}]})
    assert len(changes) == 2


def test_a_translation_in_brackets_is_a_context_moved_not_a_translation():
    """`Travail (salarié)` puts the context into the question: only the context is taken."""
    changes, _clusters = _read_group_proposal(WORK[:1], {"cards": [
        {"n": 1, "Translation": "Travail (salarié)", "Context": "emploi salarié"}]})
    assert [f for _n, f in changes] == [{"Context": "emploi salarié"}]


def test_a_new_translation_is_said_in_automatic_mode(monkeypatch, capsys):
    monkeypatch.setattr(marks, "apply_changes", lambda *a: None)
    client = _Client({"cards": [{"n": 1, "Translation": "Emploi"}, {"n": 2, "Context": "tâche"}]})
    flag_pass._resolve_group(client, [WORK[0], WORK[3]], auto=True)
    assert "Emploi" in capsys.readouterr().out


def test_a_number_outside_the_batch_does_not_lose_the_rest():
    changes, clusters = _read_group_proposal(
        WORK[:2], _contexts((1, "emploi salarié"), (9, "hors sujet"), ("x", "…")))
    assert [n["id"] for n, _f in changes] == [10]
    assert clusters == []


def test_the_ai_can_report_a_duplicate_the_spelling_does_not_betray():
    """仕事 and しごと read alike, spelled differently: the model has to see it."""
    _changes, clusters = _read_group_proposal(
        WORK[:3], {"cards": [], "duplicates": [[2, 3]]})
    assert [[n["id"] for n in c] for c in clusters] == [[11, 12]]


def test_a_settled_batch_spares_the_other_cards_an_examination(monkeypatch):
    """Five cards of "Travail" only ask one question: one call, not five."""
    monkeypatch.setattr(marks, "apply_changes", lambda *a: None)
    monkeypatch.setattr(marks, "clear_flag", lambda card_id: None)
    monkeypatch.setattr(flag_pass, "_find_duplicate_candidates", lambda note, all_notes: [])
    _answers(monkeypatch, "y")
    client = _Client(_contexts((1, "emploi salarié"), (2, "tâche à accomplir")))
    done: set[int] = set()
    group = [WORK[0], WORK[3]]
    flag_pass._process_duplicate(7, WORK[0], group[1:], client, auto=False, done=done)
    assert done == {10, 13}


def test_with_no_rival_the_turquoise_pays_for_no_telling_apart(monkeypatch):
    """One single card for that translation: nothing to tell apart, so nothing to ask."""
    monkeypatch.setattr(flag_pass, "_find_duplicate_candidates", lambda note, all_notes: [])
    monkeypatch.setattr(marks, "clear_flag", lambda card_id: None)
    _answers(monkeypatch, "y")
    client = _Client({"cards": [{"n": 1, "Context": "jamais posé"}]})
    flag_pass._process_duplicate(7, WORK[0], [FULLTIME], client, auto=False)
    assert client.user == ""            # no telling-apart call


# ── The survey (`--scan`), and the silence of the handling ────────────────────

def _deck(monkeypatch, flags: dict[int, int], false: int = 0, real: int = 0) -> None:
    """A faked deck: so many cards per flag, so many leeches of each kind."""
    from kotogen.anki.maintain import leech as leech_gen

    monkeypatch.setattr(marks, "find_flagged",
                        lambda notetype, f: [0] * flags.get(f, 0))
    monkeypatch.setattr(leech_gen, "find_leeches",
                        lambda notetype, tag, mature: ([0] * false, [0] * real))


def _without_handling(monkeypatch) -> None:
    """Neutralises everything after the survey: no safety net, no AI, no writing."""
    from kotogen.anki.maintain import leech as leech_gen

    monkeypatch.setattr("kotogen.anki.backup.before", lambda *a, **k: None)
    monkeypatch.setattr(review, "AIClient", lambda **kwargs: object())
    monkeypatch.setattr(flag_pass, "process_flag", lambda *a, **k: (0, 0))
    monkeypatch.setattr(leech_gen, "process_leeches", lambda *a, **k: (0, 0))


def _args(**overrides):
    import argparse

    base = dict(type=["vocab"], only=None, yes=None, scan=False,
                tag="leech", mature_ivl=21, provider=None, model=None)
    return argparse.Namespace(**{**base, **overrides})


def test_the_survey_shows_the_empty_targets(monkeypatch, capsys):
    """`--scan` shows where the deck stands: a target at zero is an answer too."""
    _deck(monkeypatch, {2: 2})
    review.run_maintain(_args(scan=True))
    out = capsys.readouterr().out
    assert "🟠 orange      to simplify           2" in out
    assert "🔴 red         possible mistake\n" in out
    assert "= 2 cards to handle" in out


def test_the_survey_reads_like_the_list_of_the_dialogue(monkeypatch, capsys):
    """Same names, glosses and columns as the list the targets are typed from."""
    from kotogen import interactive

    _deck(monkeypatch, {2: 2}, false=3, real=1)
    review.run_maintain(_args(scan=True))
    out = capsys.readouterr().out
    counts = {"orange": 2, "leech": 4}
    for line in interactive.maintain._maintain_target_lines({**{c: 0 for c in marks.FLAG_BY_NAME}, **counts}):
        assert line in out


def test_the_survey_says_what_the_leech_count_covers(monkeypatch, capsys):
    """One figure for two jobs: the tag removed in bulk, and the rewriting."""
    _deck(monkeypatch, {}, false=3, real=1)
    review.run_maintain(_args(scan=True))
    out = capsys.readouterr().out
    assert "     leech       failed over and over  4" in out
    assert '3 mastered cards (ivl >= 21): the "leech" tag comes off in bulk' in out
    assert "1 to rework (ivl < 21): rewriting then reset" in out


def test_the_survey_only_shows_the_targets_asked_for(monkeypatch, capsys):
    """`--only` restricts the survey too; the names and glosses keep the columns
    of the whole list."""
    _deck(monkeypatch, {1: 3})
    review.run_maintain(_args(scan=True, only=["red"], yes=[]))
    out = capsys.readouterr().out
    assert "  🔴 red         possible mistake      3   [automatic]" in out
    assert "orange" not in out
    assert "leech" not in out


def test_the_handling_does_not_say_the_state_of_play_again(monkeypatch, capsys):
    """Each task announces its count as it starts, and the dialogue showed the
    counters before the targets were picked."""
    _deck(monkeypatch, {2: 2}, false=3, real=1)
    _without_handling(monkeypatch)
    review.run_maintain(_args())
    out = capsys.readouterr().out
    assert "Maintenance of" not in out
    assert "to simplify" not in out
    assert "False leeches" not in out
    assert "to handle" not in out


def test_a_deck_that_is_already_clean_says_so_all_the_same(monkeypatch, capsys):
    """With no survey in front of it, the handling would otherwise leave without a word."""
    _deck(monkeypatch, {})
    _without_handling(monkeypatch)
    review.run_maintain(_args())
    assert "Nothing to do." in capsys.readouterr().out


# ── The note types gone through ───────────────────────────────────────────────

def _deck_by_type(monkeypatch, flags: dict[str, dict[int, int]],
                  leeches: dict[str, int] | None = None) -> None:
    """A faked deck whose flags differ from one note type to the next."""
    from kotogen.anki.maintain import leech as leech_gen

    monkeypatch.setattr(marks, "find_flagged",
                        lambda notetype, f: [0] * flags.get(notetype, {}).get(f, 0))
    monkeypatch.setattr(leech_gen, "find_leeches", lambda notetype, tag, mature: (
        [], [0] * (leeches or {}).get(notetype, 0)))


def test_without_type_every_note_type_in_use_is_gone_through(monkeypatch):
    monkeypatch.setenv("KOTOGEN_SKIP", "grammar")
    assert [k.command for k in kinds.selected()] == ["vocab", "audio", "reading"]


def test_a_named_type_is_gone_through_even_when_skipped(monkeypatch):
    """`--type` says what is wanted; the order stays that of every other screen."""
    monkeypatch.setenv("KOTOGEN_SKIP", "grammar")
    assert [k.command for k in kinds.selected(["reading", "grammar"])] == [
        "grammar", "reading"]


def test_work_in_one_type_keeps_a_single_column(monkeypatch, capsys):
    """A header over a single column would only name what the title says."""
    _deck_by_type(monkeypatch, {"Vocabulary": {1: 3}})
    review.run_maintain(_args(type=None, scan=True))
    out = capsys.readouterr().out
    assert 'Maintenance of "Vocabulary", "Grammar", "Listening", "Reading":' in out
    assert "  🔴 red         possible mistake      3" in out


def test_work_in_two_types_gets_a_column_each(monkeypatch, capsys):
    import dataclasses

    listening = dataclasses.replace(kinds.LISTENING, actions=frozenset({"error"}))
    monkeypatch.setitem(kinds.KINDS, "audio", listening)
    _deck_by_type(monkeypatch, {"Vocabulary": {1: 3}, "Listening": {1: 12}})
    review.run_maintain(_args(type=None, scan=True))
    out = capsys.readouterr().out
    assert "Vocabulary  Listening" in out
    assert "  🔴 red         possible mistake               3         12" in out
    assert "= 15 cards to handle" in out


def test_a_flag_that_does_not_apply_is_reported_not_counted(monkeypatch, capsys):
    """Purple on a grammar card: said under the list, left out of the total."""
    _deck_by_type(monkeypatch, {"Vocabulary": {1: 3}, "Grammar": {7: 2}})
    review.run_maintain(_args(type=None, scan=True))
    out = capsys.readouterr().out
    assert ("! 2 Grammar cards under purple: nothing handles that for this type, "
            "left as they are") in out
    assert "= 3 cards to handle" in out


def test_the_run_says_what_it_left_alone_after_its_summary(monkeypatch, capsys):
    _deck_by_type(monkeypatch, {"Vocabulary": {1: 3}, "Reading": {7: 1}})
    _without_handling(monkeypatch)
    review.run_maintain(_args(type=None))
    out = capsys.readouterr().out
    summary = out.index("Done:")
    assert out.index("1 Reading card under purple", summary) > summary


def test_a_flag_is_only_handled_where_its_action_applies(monkeypatch):
    _deck_by_type(monkeypatch, {"Vocabulary": {7: 3}, "Grammar": {7: 2, 1: 1}})
    _without_handling(monkeypatch)
    passes = []
    monkeypatch.setattr(flag_pass, "process_flag",
                        lambda client, f, kind, *a: passes.append((f, kind.command)) or (0, 0))
    review.run_maintain(_args(type=None))
    assert passes == [(1, "grammar"), (7, "vocab")]


def test_mastered_leeches_can_be_cleared_by_hand(monkeypatch, capsys):
    """The manual path asks first, and a refusal clears nothing."""
    from kotogen.anki.maintain import leech as leech_gen

    monkeypatch.setattr(leech_gen, "anki", lambda action, **kw: [])
    monkeypatch.setattr(leech_gen, "ask_choice", lambda prompt, keys: "n")
    assert leech_gen._process_false([1, 2], "leech", 21, auto=False) == 0


def test_one_false_leech_cleared_is_counted_in_the_singular(monkeypatch, capsys):
    from kotogen.anki.maintain import leech as leech_gen

    monkeypatch.setattr(leech_gen, "anki", lambda action, **kw: [])
    assert leech_gen._process_false([1], "leech", 21, auto=True) == 1
    assert "1 card cleared (tag removed, unsuspended)" in capsys.readouterr().out


# ── The kanji help of a vocabulary leech ──────────────────────────────────────
# Only a word of two kanji or more gets one: the meaning of a lone kanji is the
# translation, already on the card, whatever the AI sends.

def _vocab_leech(monkeypatch, expression: str, kanji_help: str) -> list[dict]:
    """One vocabulary leech through the automatic rework, the AI proposing a
    kanji help and nothing else; hands back what was written to the note."""
    from kotogen.anki.maintain import leech as leech_gen

    fields = {name: {"value": ""} for name in kinds.VOCAB.fields}
    fields["Expression"] = {"value": expression}
    card = {"cardId": 5, "note": 1, "fields": fields}

    def anki(action, **params):
        if action == "cardsInfo":
            return [card]
        if action == "notesInfo":
            return [{"noteId": 1, "tags": [], "fields": fields}]
        return None

    written = []
    monkeypatch.setattr(leech_gen, "anki", anki)
    monkeypatch.setattr(leech_gen, "offer_lone_kanji", lambda *a: lone_kanji.KEPT)
    monkeypatch.setattr(leech_gen, "_propose_simpler",
                        lambda *a: {"fields": {}, "kanji_help": kanji_help})
    monkeypatch.setattr(leech_gen, "apply_to_passage",
                        lambda note, kind, final, *a: written.append(final))
    leech_gen._process_true([5], "leech", object(), 21, True, kinds.VOCAB)
    return written


def test_a_word_of_several_kanji_is_given_the_meaning_of_each(monkeypatch):
    assert _vocab_leech(monkeypatch, "学生[がくせい]", "学 study + 生 life") == [
        {"Notes": "学 study + 生 life"}]


@pytest.mark.parametrize("expression, kanji_help", [
    ("食[た]べる", "食 eat"),
    # `々` repeats the kanji before it: the word is written with one.
    ("人々[ひとびと]", "人 person + 々 repeat"),
])
def test_a_word_of_one_kanji_is_given_no_kanji_help(monkeypatch, expression, kanji_help):
    assert _vocab_leech(monkeypatch, expression, kanji_help) == []


# ── The summary of a run cut short ────────────────────────────────────────────
# The passes count into `marks.tally` as each card is written: a run that stops
# on Anki, on the key, on `[q]` or on Ctrl+C still says what reached the deck.

def _three_red_cards(monkeypatch, step: str, after: int, error: BaseException):
    """Three red vocabulary cards in automatic mode; the step named raises `error`
    once `after` cards went through it. Hands back the notes it was done to.

    `apply`: a correction written. `unmark`: nothing to correct, the flag taken
    off, a write no `try` holds. `check`: the lone kanji check, before any write.
    """
    notes = [{"id": i, "tags": [], "fields": {"Expression": word, "Translation": "Chat",
                                              "Notes": ""}}
             for i, word in ((1, "猫[ねこ]"), (2, "犬[いぬ]"), (3, "鳥[とり]"))]
    _deck(monkeypatch, {1: 3})
    monkeypatch.setattr("kotogen.anki.backup.before", lambda *a, **k: None)
    monkeypatch.setattr(review, "AIClient", lambda **kwargs: object())

    def anki(action, **params):
        if action == "cardsInfo":
            return [{"cardId": 10, "note": 1}, {"cardId": 20, "note": 2},
                    {"cardId": 30, "note": 3}]
        return [as_note(n) for n in notes] if action == "notesInfo" else None

    done: list[int] = []

    def through(name, value=None):
        def run(*args, **kwargs):
            if step == name and len(done) == after:
                raise error
            if step == name:
                done.append(len(done) + 1)
            return value
        return run

    monkeypatch.setattr(flag_pass, "anki", anki)
    monkeypatch.setattr(lone_kanji, "offer_lone_kanji", through("check", lone_kanji.KEPT))
    proposal = ({"changed": False, "reason": "fine"} if step == "unmark" else
                {"changed": True, "reason": "", "fields": {"Translation": "Autre"}})
    monkeypatch.setattr(flag_pass, "propose_changes", lambda *a, **k: proposal)
    monkeypatch.setattr(marks, "apply_to_passage", through("apply", 0))
    monkeypatch.setattr(marks, "clear_flag", through("unmark"))
    return done


@pytest.mark.parametrize("step, error, done", [
    ("apply", ConnectionError(connect.UNREACHABLE), "2 cards changed, 2 flags removed"),
    ("apply", EditorOpen("close the editor"), "2 cards changed, 2 flags removed"),
    ("unmark", RuntimeError("Anki refused setSpecificValueOfCard: locked"),
     "0 cards changed, 2 flags removed"),
], ids=["anki closed", "editor open", "anki refused"])
def test_a_run_cut_short_counts_the_cards_already_written(monkeypatch, capsys,
                                                          step, error, done):
    _three_red_cards(monkeypatch, step, 2, error)
    with pytest.raises(SystemExit) as stop:
        review.run_maintain(_args(only=["red"], yes=[]))
    assert f"Done: {done}." in capsys.readouterr().out
    assert "Maintenance interrupted" in str(stop.value.code)


def test_ctrl_c_ends_the_run_on_its_summary_and_code_130(monkeypatch, capsys):
    _three_red_cards(monkeypatch, "check", 1, KeyboardInterrupt())
    with pytest.raises(SystemExit) as stop:
        review.run_maintain(_args(only=["red"], yes=[]))
    assert stop.value.code == 130
    out = capsys.readouterr().out
    assert out.index("Interrupted by the user.") < out.index(
        "Done: 1 card changed, 1 flag removed.")


def test_quit_ends_the_run_on_its_summary_without_an_error(monkeypatch, capsys):
    """`[q]` is an answer, not a failure: the run ends as a finished one does."""
    _three_red_cards(monkeypatch, "check", 1, marks.Quit())
    review.run_maintain(_args(only=["red"], yes=[]))
    assert "Done: 1 card changed, 1 flag removed." in capsys.readouterr().out


def test_an_unexpected_error_still_says_what_was_written(monkeypatch, capsys):
    _three_red_cards(monkeypatch, "check", 1, ZeroDivisionError("nobody saw it coming"))
    with pytest.raises(ZeroDivisionError):
        review.run_maintain(_args(only=["red"], yes=[]))
    assert "Done: 1 card changed, 1 flag removed." in capsys.readouterr().out


def test_an_ai_error_on_a_card_is_one_line_on_stderr(monkeypatch, capsys):
    """The raw answer of the model, escapes included, stays in the exception."""
    note = {"id": 11, "tags": [], "fields": {"Expression": "猫[ねこ]", "Translation": "Chat"}}
    monkeypatch.setattr(marks, "find_flagged", lambda notetype, flag: [101])
    monkeypatch.setattr(flag_pass, "anki", lambda action, **params: (
        [{"cardId": 101, "note": 11}] if action == "cardsInfo" else [as_note(note)]))
    monkeypatch.setattr(lone_kanji, "offer_lone_kanji", lambda *a: lone_kanji.KEPT)

    def invalid(*args, **kwargs):
        raise ValueError("The AI's answer was not in the form asked for.\n\nRaw answer:\n"
                         "\x1b[2Jsecond line")

    monkeypatch.setattr(flag_pass, "propose_changes", invalid)
    flag_pass.process_flag(object(), 1, kinds.VOCAB, True, [])
    err = capsys.readouterr().err
    assert err.strip() == ("!! AI error: 猫[ねこ]: The AI's answer was not in the form "
                           "asked for.")


def test_the_labels_of_two_duplicates_are_padded_to_the_widest(monkeypatch, capsys):
    """The alignment is the code's, whatever the length of the labels in a language."""
    monkeypatch.setattr(flag_pass, "_find_duplicate_candidates",
                        lambda note, all_notes: [(CARD2, ["same reading"], 1.0)])
    monkeypatch.setattr(flag_pass, "_judge_duplicates",
                        lambda client, note, candidates: {0: ("duplicate", "the same")})
    monkeypatch.setattr(flag_pass, "_translation_group", lambda note, all_notes: [])
    monkeypatch.setattr(flag_pass, "choose", lambda options, *a, **k: options[-1][0])
    monkeypatch.setattr(flag_pass, "ask_choice", lambda *a, **k: "n")
    flag_pass._process_duplicate(7, CARD1, [CARD1, CARD2], object(), auto=False)
    lines = capsys.readouterr().out.splitlines()
    first = next(line for line in lines if "Card 1 (flagged)" in line)
    second = next(line for line in lines if line.strip().startswith("Card 2"))
    assert first.index(":") == second.index(":")


def test_a_changed_field_is_written_with_one_space_after_its_colon(monkeypatch, capsys):
    from kotogen.anki.maintain import leech as leech_gen

    note = {"id": 1, "tags": [], "fields": {"Expression": "猫[ねこ]", "Translation": "Chat"}}
    leech_gen._show_rework(note, {"Translation": "Félin"}, "", kinds.VOCAB)
    assert "   Translation: Chat  →  Félin" in capsys.readouterr().out


def test_the_marks_of_a_consequence_are_the_house_arrow():
    """`→`, as every screen of the program writes it, not `->`."""
    from pathlib import Path

    folder = Path(flag_pass.__file__).parent
    guilty = [f"{path.name}:{rank}" for path in sorted(folder.glob("*.py"))
              for rank, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
              if '"   -> ' in line or '"      -> ' in line or "  ->  " in line]
    assert not guilty


# ── What the tally counts ─────────────────────────────────────────────────────
# Every card written counts once, the passes alike: the closing line adds them up.

@pytest.fixture
def tally():
    marks.tally.reset()
    yield marks.tally
    marks.tally.reset()


def test_a_distinction_written_on_both_cards_counts_both(monkeypatch, tally):
    monkeypatch.setattr(marks, "apply_changes", lambda *args: None)
    _answers(monkeypatch, "y")
    client = _Client({"reason": "deux registres", "card1": {"Notes": "Écrit"},
                      "card2": {"Notes": "Oral"}})
    assert flag_pass._differentiate(client, CARD1, CARD2, auto=False) == "applied"
    assert tally.changed == 2


def _one_leech(monkeypatch, **faked) -> None:
    """One vocabulary leech through `_process_true`, what the test names faked."""
    from kotogen.anki.maintain import leech as leech_gen

    fields = {name: {"value": ""} for name in kinds.VOCAB.fields}
    fields["Expression"] = {"value": "学生[がくせい]"}
    card = {"cardId": 5, "note": 1, "fields": fields, "interval": 1}

    def anki(action, **params):
        if action == "cardsInfo":
            return [card]
        if action == "notesInfo":
            return [{"noteId": 1, "tags": [], "fields": fields}]
        return None

    monkeypatch.setattr(leech_gen, "anki", anki)
    monkeypatch.setattr(leech_gen, "offer_lone_kanji", lambda *a: lone_kanji.KEPT)
    for name, value in faked.items():
        monkeypatch.setattr(leech_gen, name, value)


@pytest.mark.parametrize("auto, faked", [
    (True, {"offer_lone_kanji": lambda *a: lone_kanji.DELETED}),
    (True, {"_propose_simpler": lambda *a: {"category": {"type": "sentence"}},
            "read_category": lambda note, proposal: {"type": "sentence"},
            "offer_category_fix": lambda *a: lone_kanji.DELETED}),
    (False, {"_propose_simpler": lambda *a: {"fields": {}},
             "choose": lambda *a, **k: "d", "offer_manual_deletion": lambda note: True}),
    (False, {"_propose_simpler": lambda *a: {"fields": {"Translation": "Étudiant"}},
             "_show_rework": lambda *a: None, "choose": lambda *a, **k: "d",
             "offer_manual_deletion": lambda note: True}),
], ids=["lone kanji", "not a word", "nothing proposed", "rework proposed"])
def test_a_leech_deleted_is_counted_as_a_card_changed(monkeypatch, tally, auto, faked):
    """As in the flag passes: a deletion reached the deck, and the summary says so."""
    from kotogen.anki.maintain import leech as leech_gen

    _one_leech(monkeypatch, **faked)
    leech_gen._process_true([5], "leech", object(), 21, auto, kinds.VOCAB)
    assert tally.changed == 1


def test_a_leech_rewritten_counts_the_passage_cards_it_reached(monkeypatch, tally):
    from kotogen.anki.maintain import leech as leech_gen

    _one_leech(monkeypatch,
               _propose_simpler=lambda *a: {"fields": {"Translation": "Étudiant"}},
               apply_to_passage=lambda *a: 2)
    leech_gen._process_true([5], "leech", object(), 21, True, kinds.VOCAB)
    assert (tally.reworked, tally.changed) == (1, 2)


def test_a_question_renewed_counts_the_passage_cards_it_reached(monkeypatch, tally):
    from kotogen.anki.maintain import duplicates

    note = {"id": 7, "tags": [], "fields": {"Question": "なぜ？"}}
    monkeypatch.setattr(duplicates, "propose_changes", lambda *a: {"changed": True})
    monkeypatch.setattr(duplicates, "_normalise_proposal",
                        lambda *a: ({"Question": "いつ？"}, [], [], ""))
    monkeypatch.setattr(duplicates, "passage_of", lambda *a: [])
    monkeypatch.setattr(duplicates, "apply_to_passage", lambda *a: 3)
    assert duplicates._renew(object(), note, kinds.READING, auto=True, known={})
    assert tally.changed == 4


def test_a_yes_aimed_beside_the_targets_is_said_as_an_aside(monkeypatch, capsys):
    """Marked "!" as every deliberate sorting, not prefixed with a word."""
    _deck(monkeypatch, {1: 1})
    review.run_maintain(_args(scan=True, only=["red"], yes=["green"]))
    out = capsys.readouterr().out
    assert "! The targets of --yes are not among those handled" in out
    assert "Note:" not in out


def test_why_a_kanji_is_no_word_cannot_drive_the_terminal(monkeypatch, capsys):
    """The reason is the model's own text, an ESC in it included."""
    monkeypatch.setattr(lone_kanji, "kanji_deck", lambda: None)
    monkeypatch.setattr(lone_kanji, "moving", {})
    monkeypatch.setattr(lone_kanji, "held_notes", set())
    verdict = [{"kanji": "語", "word": False, "reason": "suffix\x1b]0;owned\x07",
                "example": "日本語"}]
    _answers(monkeypatch, "k")
    note = {"id": 42, "tags": [], "fields": {"Expression": "語[ご]"}}
    lone_kanji.offer_lone_kanji(_Client(verdict), note, False)
    shown = capsys.readouterr()
    assert "suffix]0;owned" in shown.out + shown.err
    assert "\x1b" not in shown.out + shown.err and "\x07" not in shown.out + shown.err
