"""Maintenance: what each flag asks for, and the `derive` action of the pink one."""

import re

import pytest

from conftest import Held, as_note, held_card
from kotogen import known, memory, prompts
from kotogen.anki.maintain import derive as derive_pass, flag_pass, lone_kanji, marks
from kotogen.maintenance import derive, kinds, review
from kotogen.maintenance.derive import Proposal

# ── The flags and their actions ───────────────────────────────────────────────

def test_every_mark_triggers_a_known_action_by_default():
    assert set(marks.DEFAULT_FLAG_ACTIONS) == set(marks.FLAG_COLOURS)
    assert set(marks.DEFAULT_FLAG_ACTIONS.values()) <= set(review.ACTIONS) | {""}


def test_no_action_answers_two_flags_by_default():
    """Two flags on one action would give two lines of the survey for one job."""
    actions = [a for a in marks.DEFAULT_FLAG_ACTIONS.values() if a]
    assert len(actions) == len(set(actions))


def _sections(lang: str, kind) -> set[str]:
    """The actions the instruction of a kind has a section for, in one language."""
    text = (prompts.folder(lang) / f"maintain_flag_{kind.command}.md").read_text(
        encoding="utf-8")
    return set(re.findall(r"^### (\w+) - ", text, re.M))


@pytest.mark.parametrize("lang", sorted(prompts.languages()))
@pytest.mark.parametrize("kind", list(kinds.KINDS.values()), ids=list(kinds.KINDS))
def test_every_action_of_a_kind_is_written_in_its_instruction(lang, kind):
    """`derive` and `duplicate` have passes of their own. Every other action of a
    kind has its section, and only those: any other would be read and never asked."""
    assert _sections(lang, kind) == set(kind.actions) - kind.passes


@pytest.mark.parametrize("action", ["error", "enrich"])
def test_a_wrong_or_missing_tag_is_asked_with_the_taxonomy(action):
    """Red corrects the wrong tags, green adds the missing ones: both need the
    list of tag names."""
    client = _Client({"changed": False, "reason": "ok"})
    review.propose_changes(client, action, _note(1, "猫[ねこ]", "Cat"), kinds.VOCAB)
    assert kinds.VOCAB_TAXONOMY in client.user


@pytest.mark.parametrize("action", ["simplify", "text", "audio", "renew"])
def test_the_other_actions_do_not_carry_the_taxonomy(action):
    client = _Client({"changed": False, "reason": "ok"})
    review.propose_changes(client, action, _note(1, "猫[ねこ]", "Cat"), kinds.VOCAB)
    assert kinds.VOCAB_TAXONOMY not in client.user


@pytest.mark.parametrize("action, sent", [("error", True), ("enrich", False)])
def test_only_red_reads_the_tags_of_a_use(action, sent):
    """A wrong register teaches something false at every review, a missing one
    does not; green, looking for what is missing, would add one to almost any word."""
    client = _Client({"changed": False, "reason": "ok"})
    review.propose_changes(client, action, _note(1, "猫[ねこ]", "Cat"), kinds.VOCAB)
    assert (kinds.VOCAB_USES in client.user) is sent


@pytest.mark.parametrize("action, kept", [("error", True), ("enrich", False)])
def test_green_neither_lays_nor_lifts_the_tags_of_a_use(action, kept):
    """What the model answers all the same is turned down, its other tags kept."""
    note = _note(1, "自宅[じたく]", "Home")
    note["tags"] = ["Register::改まった語"]
    _fields, add, remove, _reason = review._normalise_proposal(note, {
        "addTags": ["Noun::Places", "Speaker::男性語", "Dialect::関西弁"],
        "removeTags": ["Register::改まった語"]}, kinds.VOCAB, action=action)
    assert add == (["Noun::Places", "Speaker::男性語", "Dialect::関西弁"] if kept
                   else ["Noun::Places"])
    assert remove == (["Register::改まった語"] if kept else [])


def test_a_grammar_card_is_still_given_its_register_by_green():
    """There the register decides the form of the gap: without it, the card has
    two right answers."""
    client = _Client({"changed": False, "reason": "ok"})
    fields = dict.fromkeys(kinds.GRAMMAR.fields, "")
    gap = {"id": 2, "tags": [], "fields": fields | {
        "Sentence": "音楽[おんがく]を 聞[き]き{{c1::ながら}}", "Rule": "ながら"}}
    review.propose_changes(client, "enrich", gap, kinds.GRAMMAR)
    assert kinds.GRAMMAR_TAXONOMY in client.user
    _fields, add, _remove, _reason = review._normalise_proposal(
        gap, {"addTags": ["Register::丁寧体"]}, kinds.GRAMMAR, action="enrich")
    assert add == ["Register::丁寧体"]


def test_the_message_names_the_action_and_the_instruction_says_it():
    """What each action means lives in the instruction; the message only names it."""
    client = _Client({"changed": False, "reason": "ok"})
    review.propose_changes(client, "renew", _note(1, "猫[ねこ]", "Cat"), kinds.VOCAB)
    assert client.user.splitlines()[0].endswith("renew")
    assert "### renew" in client.system


def test_the_header_of_a_pass_names_the_colour_and_the_action():
    assert marks.flag_header(5) == "🌸  Pink - to derive"


def test_the_blue_flag_still_checks_the_bare_kanji(monkeypatch):
    """Blue covers the whole Japanese text, furigana first: a kanji left without
    a reading is still pointed out to the model."""
    client = _Client({"changed": False, "reason": "ok"})
    review.propose_changes(client, "text", _note(1, "漢字[かんじ]の 字", "Kanji"))
    assert "字" in client.user.split("\n")[-1]


# ── derive: what the model proposes ──────────────────────────────────────────

def _note(note_id: int, expression: str, translation: str) -> dict:
    """A card as the maintenance reads one, the id of its note as its `id`."""
    fields = {"Expression": expression, "Translation": translation, "Context": "",
              "Notes": "", "Example": "", "ExampleTranslation": ""}
    return {"id": note_id, "tags": [], "fields": fields}


class _Client:
    """Faked AIClient: always hands back the same JSON answer, without the network."""

    def __init__(self, result):
        self.result = result
        self.user = ""
        self.system = ""

    def chat_json(self, system, user):
        self.system, self.user = system, user
        return self.result


def test_the_proposals_are_read_bare_and_once():
    client = _Client({"words": [
        {"word": "開[あ]く", "relation": "pair", "gloss": "s'ouvrir"},
        {"word": "開く", "relation": "pair", "gloss": "s'ouvrir"},          # twice
        {"word": "開ける", "relation": "family", "gloss": "ouvrir"},        # the card itself
        {"word": "閉める", "relation": "opposite", "gloss": "fermer"},      # off the protocol
        {"relation": "family"},                                           # no word
    ]})
    found = derive.propose(client, _note(1, "開[あ]ける", "Ouvrir"))
    assert found == [Proposal("開く", "pair", "s'ouvrir"), Proposal("閉める", "", "fermer")]


def test_the_proposals_stop_at_four():
    client = _Client({"words": [{"word": w, "relation": "family", "gloss": ""}
                                for w in ("日本語", "英語", "言語", "語学", "単語")]})
    assert len(derive.propose(client, _note(1, "語[ご]", "Langue"))) == derive.MAX_WORDS


def test_a_bare_list_is_read_as_the_words():
    client = _Client([{"word": "安い", "relation": "antonym", "gloss": "bon marché"}])
    assert derive.propose(client, _note(1, "高[たか]い", "Cher")) == [
        Proposal("安い", "antonym", "bon marché")]


def test_an_answer_that_is_not_a_list_fails_the_card():
    with pytest.raises(ValueError):
        derive.propose(_Client({"reason": "rien"}), _note(1, "高[たか]い", "Cher"))


def test_the_card_goes_to_the_model_field_by_field():
    client = _Client({"words": []})
    derive.propose(client, _note(1, "高[たか]い", "Cher"))
    assert client.system == prompts.load("maintain_derive")
    assert "Expression : 高[たか]い" in client.user


@pytest.mark.parametrize("name, relations", [
    ("maintain_derive", derive._WORD_RELATIONS),
    ("maintain_derive_grammar", derive._RULE_RELATIONS),
])
def test_every_relation_of_the_code_is_one_the_instruction_names(name, relations):
    """The keys are the protocol: a relation the prompt does not name is never
    handed back, and one the code does not know is shown without a label."""
    for lang in prompts.languages():
        text = (prompts.folder(lang) / f"{name}.md").read_text(encoding="utf-8")
        for relation in relations:
            assert f"`{relation}`" in text, (lang, relation)
            assert relation in derive.RELATIONS


# ── derive: what the deck already holds ──────────────────────────────────────

def test_a_word_of_the_deck_or_of_the_pass_is_not_proposed_again():
    index = known.words_of(["閉[し]める"])
    new, held = derive.fresh(
        [Proposal("開く", "pair", ""), Proposal("閉める", "antonym", ""),
         Proposal("閉まる", "antonym", "")], index, taken={"閉まる"})
    assert [p.word for p in new] == ["開く"]
    assert [p.word for p in held] == ["閉める", "閉まる"]


def test_a_proposal_reads_with_its_gloss_and_its_relation():
    assert derive.describe(Proposal("開く", "pair", "s'ouvrir")) == \
        "開く - s'ouvrir (transitive or intransitive twin)"
    assert derive.describe(Proposal("開く", "", "")) == "開く"


# ── derive: the pass ──────────────────────────────────────────────────────────

def _pass(monkeypatch, *, sent=True, deck=("閉[し]める",)):
    """Two flagged cards, the deck, and the send faked. Hands back what was
    generated and the flags removed."""
    generated: list[tuple[list[str], str]] = []
    cleared: list[int] = []
    monkeypatch.setattr(memory, "_known", Held({"Vocabulary": [
        held_card(i, Expression=word) for i, word in enumerate(deck)]}))
    monkeypatch.setattr(derive_pass.vocab, "generate_into",
                        lambda client, words, deck, notetype:
                        generated.append((list(words), deck)) or sent)
    monkeypatch.setattr(derive_pass.grammar, "generate_into",
                        lambda client, rules, deck, notetype, count:
                        generated.append((list(rules), deck)) or sent)
    monkeypatch.setattr(derive_pass, "unmark", cleared.append)
    return generated, cleared


CARDS = [{"cardId": 10, "note": 1, "deckName": "Japanese::Vocabulary"},
         {"cardId": 20, "note": 2, "deckName": "Japanese::Vocabulary"}]
NOTES = {1: _note(1, "開[あ]ける", "Ouvrir"), 2: _note(2, "始[はじ]める", "Commencer")}


class _PerCard:
    """One answer per card, keyed by the expression the user message carries."""

    def __init__(self, answers: dict[str, list[dict]]):
        self.answers = answers

    def chat_json(self, system, user):
        for expression, words in self.answers.items():
            if expression in user:
                return {"words": words}
        return {"words": []}


ANSWERS = {
    "開[あ]ける": [{"word": "開く", "relation": "pair", "gloss": "s'ouvrir"},
                  {"word": "閉める", "relation": "antonym", "gloss": "fermer"}],
    "始[はじ]める": [{"word": "始まる", "relation": "pair", "gloss": "commencer"},
                    {"word": "開く", "relation": "family", "gloss": "s'ouvrir"}],
}


def test_the_automatic_pass_generates_the_new_words_together(monkeypatch):
    """One batch for the whole pass, the deck's words and the words already
    picked taken out; every flag comes off once Anki has taken it."""
    generated, cleared = _pass(monkeypatch)
    result = derive_pass.process(_PerCard(ANSWERS), CARDS, NOTES, kinds.VOCAB, auto=True)
    assert generated == [(["開く", "始まる"], "Japanese::Vocabulary")]
    assert cleared == [10, 20]
    assert result == (0, 2)


def test_a_send_anki_did_not_take_leaves_every_flag(monkeypatch, capsys):
    generated, cleared = _pass(monkeypatch, sent=False)
    derive_pass.process(_PerCard(ANSWERS), CARDS, NOTES, kinds.VOCAB, auto=True)
    assert generated and cleared == []
    assert "the flags stay" in capsys.readouterr().out


def test_a_batch_turned_down_takes_the_flags_off(monkeypatch, capsys):
    """Every card turned down and nothing failed: a new run would pay for the
    same refusal, so the flags come off, and it is not said as a failed send."""
    generated, cleared = _pass(monkeypatch, sent=None)
    derive_pass.process(_PerCard(ANSWERS), CARDS, NOTES, kinds.VOCAB, auto=True)
    out = capsys.readouterr().out
    assert generated and cleared == [10, 20]
    assert "every derived card was turned down, the flags come off" in out
    assert "did not reach Anki" not in out


def test_a_card_with_nothing_new_loses_its_flag_in_automatic_mode(monkeypatch):
    generated, cleared = _pass(monkeypatch)
    answers = {"開[あ]ける": [{"word": "閉める", "relation": "antonym", "gloss": ""}]}
    derive_pass.process(_PerCard(answers), CARDS[:1], NOTES, kinds.VOCAB, auto=True)
    assert generated == []
    assert cleared == [10]


def _answers(monkeypatch, *replies):
    queue = list(replies)

    def _next(*_args):
        if not queue:
            raise EOFError
        return queue.pop(0)

    monkeypatch.setattr("builtins.input", _next)


def test_the_dialogue_creates_only_the_words_picked(monkeypatch):
    generated, cleared = _pass(monkeypatch, deck=())
    _answers(monkeypatch, "n", "y")
    derive_pass.process(_PerCard(ANSWERS), CARDS[:1], NOTES, kinds.VOCAB, auto=False)
    assert generated == [(["閉める"], "Japanese::Vocabulary")]
    assert cleared == [10]


def test_a_redirected_input_generates_nothing(monkeypatch):
    """EOF keeps the last choice, `[n] no`, then keeps the flag: nothing is
    paid for unasked, and the card comes back on the next run."""
    generated, cleared = _pass(monkeypatch, deck=())
    _answers(monkeypatch)
    derive_pass.process(_PerCard(ANSWERS), CARDS[:1], NOTES, kinds.VOCAB, auto=False)
    assert generated == []
    assert cleared == []


PASSAGE_CARDS = [{"cardId": 10, "note": 1, "deckName": "Japanese::Reading"},
                 {"cardId": 20, "note": 2, "deckName": "Japanese::Reading"}]


def _passage_notes() -> dict[int, dict]:
    """Two questions on one invented text, as the reading deck files them."""
    def note(note_id: int) -> dict:
        fields = {name: "" for name in (*kinds.READING.shown, *kinds.READING.fields)}
        fields.update(ID=f"RC_book_abcd1234_00{note_id}",
                      Text="今日[きょう]は 公園[こうえん]に 行[い]きます。")
        return {"id": note_id, "tags": [], "fields": fields}

    return {1: note(1), 2: note(2)}


@pytest.mark.parametrize("unflag, cleared_after", [("n", []), ("y", [10, 20])])
def test_the_other_cards_of_a_passage_follow_the_flag_of_the_first(
        monkeypatch, unflag, cleared_after):
    """Every proposal turned down: the text is asked once, and what was answered
    for the flag of its first card holds for the others."""
    generated, cleared = _pass(monkeypatch, deck=())
    monkeypatch.setattr(flag_pass, "unmark", cleared.append)  # the question's own
    _answers(monkeypatch, "n", unflag)
    client = _Client({"words": [{"word": "公園", "gloss": "parc"}], "rules": []})
    derive_pass.process(client, PASSAGE_CARDS, _passage_notes(), kinds.READING, auto=False)
    assert generated == []
    assert cleared == cleared_after


def test_a_derived_card_goes_to_the_deck_of_its_card(monkeypatch):
    generated, _cleared = _pass(monkeypatch)
    cards = [{**CARDS[0], "deckName": "Japanese::Vocabulary::N4"}, CARDS[1]]
    derive_pass.process(_PerCard(ANSWERS), cards, NOTES, kinds.VOCAB, auto=True)
    assert generated == [(["開く"], "Japanese::Vocabulary::N4"),
                         (["始まる"], "Japanese::Vocabulary")]


def test_the_pink_pass_derives_without_asking_about_lone_kanji(monkeypatch):
    """語 is precisely the card 日本語 is derived from."""
    monkeypatch.setattr(marks, "find_flagged", lambda notetype, flag: [10])
    monkeypatch.setattr(flag_pass, "anki", lambda action, **params: (
        [CARDS[0]] if action == "cardsInfo" else [as_note(NOTES[1])]))
    monkeypatch.setattr(lone_kanji, "offer_lone_kanji",
                        lambda *a: pytest.fail("the lone kanji check ran"))
    called = []

    def derived(*args):
        called.append(args)
        marks.tally.cleared += 1  # what the pass counts as it takes a flag off

    monkeypatch.setattr(derive_pass, "process", derived)
    assert flag_pass.process_flag(object(), 5, kinds.VOCAB, True, []) == (0, 1)
    assert called


# ── derive: the generation it hands the words to ─────────────────────────────

def test_the_words_go_through_the_vocab_pipeline_and_into_the_deck(monkeypatch, tmp_path):
    from kotogen.generators import vocab

    seen = {}
    monkeypatch.setattr(vocab, "resolve_output_path", lambda args, prefix: tmp_path / "v.tsv")
    monkeypatch.setattr(memory, "_known", Held())
    monkeypatch.setattr(vocab, "_process_entries",
                        lambda client, entries, args, out, seen_expr, index, failed:
                        seen.update(entries=entries, args=args) or ([{"Expression": "開く"}], []))
    monkeypatch.setattr(vocab, "finish", lambda cards, fields, args, out, **kw: (1, 0))
    assert vocab.generate_into(object(), ["開く"], "Japanese::Vocabulary", "Vocabulary")
    assert seen["entries"] == ["開く"]
    assert seen["args"].send and seen["args"].deck == "Japanese::Vocabulary"


@pytest.mark.parametrize("call_failed, expected", [(False, None), (True, False)])
def test_nothing_generated_is_not_a_send(monkeypatch, tmp_path, call_failed, expected):
    """No card: every word turned down (None), or a call that failed (False),
    which a new run may get through."""
    from kotogen.generators import vocab

    def process(client, entries, args, out, seen_expr, index, failed):
        if call_failed:
            failed.extend(entries)
        return [], [] if call_failed else [{"_skip": True}]

    monkeypatch.setattr(vocab, "resolve_output_path", lambda args, prefix: tmp_path / "v.tsv")
    monkeypatch.setattr(memory, "_known", Held())
    monkeypatch.setattr(vocab, "_process_entries", process)
    monkeypatch.setattr(vocab, "finish", lambda *a, **k: pytest.fail("nothing to send"))
    assert vocab.generate_into(object(), ["開く"], "Japanese::Vocabulary",
                               "Vocabulary") is expected


@pytest.mark.parametrize("analysed, generated, expected",
                         [(False, False, False), (True, False, False), (True, True, None)])
def test_rules_that_make_no_card_are_not_a_send(monkeypatch, tmp_path, analysed, generated,
                                                expected):
    """A rule whose analysis or generation fails leaves nothing to send and is a
    failure; one whose cards are all turned down is not."""
    from kotogen.generators import grammar

    def detect(client, rule):
        if not analysed:
            raise ValueError("no level")
        return {"rule_tag": rule, "level": "N4"}

    def cards_for(client, rules, args, out, all_cards, tags_done, failed):
        if not generated:
            failed.extend(info["rule"] for info in rules)
        return False

    monkeypatch.setattr(grammar, "_detect_info", detect)
    monkeypatch.setattr(grammar, "resolve_output_path", lambda args, prefix: tmp_path / "g.tsv")
    monkeypatch.setattr(grammar, "_cards_for_rules", cards_for)
    monkeypatch.setattr(grammar, "finish", lambda *a, **k: pytest.fail("nothing to send"))
    assert grammar.generate_into(object(), ["〜ながら"], "Japanese::Grammar", "Grammar",
                                 3) is expected
