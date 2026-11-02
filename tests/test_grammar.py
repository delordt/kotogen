"""Tests of the grammar generator, with no network or model call."""

from unittest.mock import patch

import pytest

from conftest import Held, held_card
from kotogen import grammar_table, prompts
from kotogen.cli import build_parser
from kotogen.generators import grammar
from kotogen.generators.grammar import (
    RULES_SOURCE,
    _deck_rules,
    _detect_info,
    _mark_done,
    _normalise_cloze,
    _post_process,
    _read_rules,
    _to_type,
    _without_spaces,
    rules_of_level,
)

# A table of four points, two of which share a form: what the tests below read
# instead of the shipped one, whose lines are corrected by hand.
TABLE = [
    {"title": "だ", "level": "N5", "tier": "1",
     "meaning_en": "To be (copula)", "meaning_fr": "Être (copule)"},
    {"title": "のに（逆接）", "level": "N4", "tier": "1",
     "meaning_en": "Although, even though", "meaning_fr": "Bien que, alors que"},
    {"title": "やすい", "level": "N4", "tier": "2",
     "meaning_en": "Easy to", "meaning_fr": "Facile à"},
    {"title": "のに（目的）", "level": "N3", "tier": "2",
     "meaning_en": "In order to", "meaning_fr": "Pour, afin de"},
]


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setattr(grammar_table, "load", lambda: TABLE)


# ── _normalise_cloze ──────────────────────────────────────────────────────────

def test_single_c1_cloze_is_kept_unchanged():
    cards = [{"Sentence": "この 薬[くすり]を{{c1:: 飲[の]めば}}、 治[なお]ります。"}]
    out = _normalise_cloze(cards)
    assert out == cards


def test_an_item_that_is_no_card_is_left_out():
    """A stray string in the model's list would stop the whole rule on `.get`."""
    card = {"Sentence": "雨[あめ]が{{c1:: 降[ふ]れば}}、 行[い]きません。"}
    assert _normalise_cloze([card, "a stray string", None]) == [card]


def test_cloze_number_is_renumbered_to_c1():
    cards = [{"Sentence": "毎日[まいにち]{{c2:: 走[はし]る}}ことにしています。"}]
    out = _normalise_cloze(cards)
    assert out[0]["Sentence"] == "毎日[まいにち]{{c1:: 走[はし]る}}ことにしています。"


def test_inline_hint_is_moved_to_its_own_field():
    cards = [{"Sentence": "雨[あめ]が{{c1:: 降[ふ]れば::降る}}、 行[い]きません。", "Hint": ""}]
    out = _normalise_cloze(cards)
    assert out[0]["Sentence"] == "雨[あめ]が{{c1:: 降[ふ]れば}}、 行[い]きません。"
    assert out[0]["Hint"] == "降る"


def test_inline_hint_does_not_overwrite_existing_hint():
    cards = [{"Sentence": "{{c1::食べれば::たべる}}いいよ。", "Hint": "食[た]べる"}]
    out = _normalise_cloze(cards)
    assert out[0]["Sentence"] == "{{c1::食べれば}}いいよ。"
    assert out[0]["Hint"] == "食[た]べる"


# ── The hole tightened on the form ───────────────────────────────────────────
# The punctuation belongs to the sentence, not to the rule. Left in the hole, it
# is revealed in green on the back and has to be typed to get the card right.

def test_the_final_punctuation_leaves_the_hole():
    cards = [{"Sentence": "雨[あめ]が{{c1:: 降[ふ]れば}}、"}]
    assert _normalise_cloze(cards)[0]["Sentence"] == "雨[あめ]が{{c1:: 降[ふ]れば}}、"

    cards = [{"Sentence": "雨[あめ]が{{c1:: 降[ふ]れば、}}"}]
    assert _normalise_cloze(cards)[0]["Sentence"] == "雨[あめ]が{{c1:: 降[ふ]れば}}、"


def test_the_opening_marks_are_pushed_in_front_of_the_hole():
    cards = [{"Sentence": "彼[かれ]は{{c1::「やめる」と}} 言[い]った。"}]
    assert _normalise_cloze(cards)[0]["Sentence"] == "彼[かれ]は「{{c1::やめる」と}} 言[い]った。"


def test_the_leading_space_stays_in_the_hole():
    """It is the anchor of the first furigana group, not a layout blank: out of
    the hole, Anki's filter would lay the reading over what precedes it.
    """
    cards = [{"Sentence": "音楽[おんがく]を{{c1:: 聞[き]きながら}} "}]
    assert _normalise_cloze(cards)[0]["Sentence"] == "音楽[おんがく]を{{c1:: 聞[き]きながら}} "


def test_a_hole_of_punctuation_alone_is_left_as_it_is():
    """Tightening it would empty it."""
    cards = [{"Sentence": "行[い]く{{c1::。}}"}]
    assert _normalise_cloze(cards)[0]["Sentence"] == "行[い]く{{c1::。}}"


def test_card_without_cloze_is_dropped(capsys):
    cards = [
        {"Sentence": "トウが 立[た]つ。"},
        {"Sentence": "行く{{c1::なら}}、 教[おし]えて。"},
    ]
    out = _normalise_cloze(cards)
    assert len(out) == 1
    assert "{{c1::なら}}" in out[0]["Sentence"]
    # A sorting, not a failure: said on stdout, marked "!".
    assert "turned down" in capsys.readouterr().out


# ── _post_process ─────────────────────────────────────────────────────────────

def test_post_process_sets_url_and_tags():
    cards = [{"Sentence": "a"}, {"Sentence": "b"}]
    out = _post_process(cards, "N4", "ながら", "https://example.jp/x")
    assert all(c["URL"] == "https://example.jp/x" for c in out)
    assert all(c["Tags"] == "Grammar::N4::ながら" for c in out)


def test_post_process_keeps_register_tags_only():
    cards = [{"Sentence": "a", "Tags": "Register::丁寧体 Other::rubbish"}]
    out = _post_process(cards, "N3", "のに", "")
    assert out[0]["Tags"] == "Grammar::N3::のに Register::丁寧体"


def test_the_register_of_the_ai_becomes_a_tag():
    """The model's register becomes a tag, filtered on and read by the badge; no
    field repeats it. Keigo is filed under `敬語`, to find both halves at once.
    """
    cards = [{"Sentence": "a", "Register": "謙譲語"}]
    out = _post_process(cards, "N3", "拝見する", "")
    assert out[0]["Tags"] == "Grammar::N3::拝見する Register::敬語::謙譲語"


def test_an_unknown_register_lays_no_tag():
    """Better no badge than a tag nothing recognises."""
    cards = [{"Sentence": "a", "Register": "very polite"}]
    assert _post_process(cards, "N4", "ください", "")[0]["Tags"] == "Grammar::N4::ください"


def test_post_process_lays_the_rule_and_the_answer_to_type():
    """Two fields the model never writes: the rule, the canonical name found by
    the analysis, and the answer, the hole rid of its readings as one types it.
    """
    cards = [{"Sentence": " 雨[あめ]が{{c1:: 降[ふ]れば}}、 中止[ちゅうし]です。"}]
    out = _post_process(cards, "N4", "ば", "https://example.jp/x")
    assert out[0]["Rule"] == "ば"
    assert out[0]["Answer"] == "降れば"


def test_the_answer_to_type_loses_readings_and_anchors():
    """`{{type:…}}` compares to the character: one types `降れば`, not `降[ふ]れば`."""
    assert _to_type("{{c1:: 食[た]べれば}}いい。") == "食べれば"
    assert _to_type("これ{{c1::に 対[たい]して}}") == "に対して"
    assert _to_type("no hole here") == ""


# ── The target, coloured inside the translation ───────────────────────────────
# An exact extract of the translation, found again by the card to colour it in
# place: one not found would silently colour nothing.

def test_the_target_is_kept_when_it_is_in_the_translation():
    cards = [{"Sentence": "{{c1::ながら}}", "Target": "en écoutant",
              "Translation": "Je fais mes devoirs en écoutant de la musique."}]
    assert _post_process(cards, "N4", "ながら", "")[0]["Target"] == "en écoutant"


def test_the_target_survives_the_case_and_the_curly_apostrophe():
    cards = [{"Sentence": "{{c1::ば}}", "Target": "S’il pleut",
              "Translation": "S'il pleut, le match est annulé."}]
    assert _post_process(cards, "N4", "ば", "")[0]["Target"] == "S’il pleut"


def test_a_target_outside_the_translation_is_erased(capsys):
    cards = [{"Sentence": "{{c1::ば}}", "Target": "si jamais",
              "Translation": "S'il pleut, le match est annulé."}]
    assert _post_process(cards, "N4", "ば", "")[0]["Target"] == ""
    said = capsys.readouterr().out
    assert "target outside the translation" in said and "si jamais" in said


def test_the_dropped_targets_are_counted_instead_of_unrolled(capsys):
    """One line for the batch, not one per card: a model that rephrases instead
    of copying does so for the whole batch."""
    cards = [{"Sentence": "{{c1::ば}}", "Target": f"hors sujet {i}",
              "Translation": "S'il pleut, le match est annulé."} for i in range(3)]
    out = _post_process(cards, "N4", "ば", "")
    assert all(c["Target"] == "" for c in out)
    said = capsys.readouterr().out.strip()
    assert said.count("target") == 1 and "3 targets" in said
    assert len(said.splitlines()) == 1


# ── A text is not a source of rules ──────────────────────────────────────────

@pytest.mark.parametrize("source", ["nhk", "https://example.jp/article",
                                    "chapter.txt", "course.pdf"])
def test_a_text_is_refused_rather_than_taken_for_a_rule(monkeypatch, tmp_path,
                                                        source):
    """`grammar` works on named rules: a text stops before any call, rather than
    go to the analysis as the name of a rule."""
    if not source.startswith("http") and source != "nhk":
        (tmp_path / source).write_bytes(b"%PDF-1.7" if source.endswith(".pdf")
                                        else "私は学生です。\n".encode())
        source = str(tmp_path / source)

    def no_client(**kwargs):
        raise AssertionError("no AI call for a text")

    monkeypatch.setattr(grammar, "AIClient", no_client)
    with pytest.raises(SystemExit) as stop:
        grammar.run_grammar(build_parser().parse_args(["grammar", source]))
    assert "kotogen grammar jlpt --level N4" in str(stop.value.code)


# ── The "jlpt" source: what the level holds, minus what the deck has ─────────

def test_a_name_typed_with_a_blank_loses_it_to_tag():
    """Anki tags are separated by the space: 「くらい （程度）」 would make two."""
    assert _without_spaces("くらい （程度）") == "くらい（程度）"
    cards = _post_process([{"Sentence": "{{c1::行く}}"}], "N3", "くらい （程度）", "")
    assert cards[0]["Tags"].split() == ["Grammar::N3::くらい（程度）"]
    # The readable name stays as given.
    assert cards[0]["Rule"] == "くらい （程度）"


def test_the_uses_of_one_form_stay_distinct():
    """のに（逆接） done does not make のに（目的） acquired: two points, two meanings."""
    assert grammar_table.key("のに（逆接）") != grammar_table.key("のに（目的）")
    # But the decoration settles nothing: 〜ば and ば are the same one.
    assert grammar_table.key("〜ば") == grammar_table.key("ば")


def test_the_rules_of_the_deck_are_read_in_the_field_and_in_the_tag():
    """A card with an empty `Rule` field only carries its name in its tag:
    sticking to the field would declare the whole level to do."""
    deck = Held({"Grammar": [
        held_card(1, tags=["Grammar::N5::ている（進行）"], Rule="ている（進行）", URL=""),
        # Empty field, full tag: a card filled in by hand, for instance.
        held_card(2, tags=["Grammar::N4::ながら", "Register::丁寧体"], Rule="", URL=""),
    ]})
    names = _deck_rules(deck, "Grammar")
    assert grammar_table.key("ながら") in names
    assert grammar_table.key("ている（進行）") in names
    # Neither the neighbouring use nor the register tag gets in there.
    assert grammar_table.key("ている（結果）") not in names
    assert grammar_table.key("丁寧体") not in names


def test_two_uses_of_one_form_are_not_confused(table):
    """のに is "despite" in N4 and "in order to" in N3: two points, two names,
    two series of cards."""
    deck = Held({"Grammar": [
        held_card(1, tags=["Grammar::N4::のに（逆接）"], Rule="のに（逆接）", URL="")]})
    with patch("kotogen.seen.load", return_value={}):
        rules = rules_of_level("auto", "Grammar", deck)
    assert [(r.title, r.done) for r in rules] == [
        ("だ", False), ("のに（逆接）", True), ("やすい", False), ("のに（目的）", False)]


# ── The table before the model ───────────────────────────────────────────────

class SilentClient:
    """A client refusing to be called: the test is that it is not."""

    def chat_json(self, system, user):  # pragma: no cover - must not run
        raise AssertionError("AI call for a rule the table knows")


def test_a_rule_of_the_table_costs_no_call(table):
    """The table names, levels and glosses やすい: no call is paid for it."""
    info = _detect_info(SilentClient(), "〜やすい")
    assert info == {"level": "N4", "rule_tag": "やすい",
                    "meaning": "Facile à"}


def test_the_gloss_of_a_rule_follows_the_language_of_the_cards(table):
    """The meaning goes to the model, so it is read in the language of the cards;
    the assistant's rule list reads it in the language of the screen."""
    prompts.use("en")
    english = _detect_info(SilentClient(), "のに（目的）")["meaning"]
    prompts.use("fr")
    french = _detect_info(SilentClient(), "のに（目的）")["meaning"]
    assert (english, french) == ("In order to", "Pour, afin de")


def test_the_full_name_picks_one_use_and_the_bare_form_the_first(table):
    """"のに（目的）" names one rule; "のに" names two, and the table settles it by
    level, the easiest first."""
    assert _detect_info(SilentClient(), "のに（目的）")["level"] == "N3"
    bare = _detect_info(SilentClient(), "のに")
    assert (bare["rule_tag"], bare["level"]) == ("のに（逆接）", "N4")


def test_a_rule_outside_the_table_goes_back_through_the_model(table):
    """"younitanomu" is not in the table: the model resolves it."""
    class Client:
        def chat_json(self, system, user):
            return {"rule_tag": "ように頼む", "level": "N3"}

    info = _detect_info(Client(), "younitanomu")
    assert info["rule_tag"] == "ように頼む"
    assert info["level"] == "N3"


def test_a_name_from_the_model_is_spelt_as_the_table_spells_its_own(table):
    """No 〜 at either end, as in the table: the tag reads Grammar::N3::ように頼む
    like those of the table's rules. A 〜 inside holds a slot and stays."""
    class Client:
        def __init__(self, name):
            self.name = name

        def chat_json(self, system, user):
            return {"rule_tag": self.name, "level": "N3"}

    assert _detect_info(Client("〜ように頼む"), "younitanomu")["rule_tag"] == "ように頼む"
    assert _detect_info(Client("〜ばかりか〜も"), "bakarika")["rule_tag"] == "ばかりか〜も"
    # Anki splits tags on spaces: the name shown, kept and tagged is one word.
    assert _detect_info(Client("〜ように 頼む"), "younitanomu")["rule_tag"] == "ように頼む"


def test_a_target_count_agrees_with_itself(capsys):
    """Several targets the translation lacks are counted on one line."""
    cards = [{"Sentence": "{{c1::雨}}が降る。", "Translation": "Il pleut.",
              "Target": target} for target in ("neige", "vent")]
    grammar._post_process(cards, "N4", "が", "")
    assert "2 targets outside the translation, ignored" in capsys.readouterr().out


def test_the_rule_a_page_documents_is_spelt_as_the_table_spells_its_own(monkeypatch,
                                                                         tmp_path):
    """The model reads 〜のに on the page: the cards are filed under のに."""
    from kotogen.generators import text_source

    class Client:
        def chat_json(self, system, user):
            return {"rule": "〜のに", "level": "N3", "meaning": "in order to"}

    worked = []
    monkeypatch.setattr(grammar, "AIClient", lambda **kwargs: Client())
    monkeypatch.setattr(text_source, "page_text", lambda url: ("のに", "..."))
    monkeypatch.setattr(grammar, "_cards_for_rules",
                        lambda client, rules, *rest: worked.extend(rules))
    with pytest.raises(SystemExit):
        grammar.run_grammar(build_parser().parse_args(
            ["grammar", "--url", "https://example.jp/noni",
             "--output", str(tmp_path / "grammar.tsv")]))
    assert worked[0]["rule"] == "のに"


def test_a_page_that_documents_no_rule_exits_on_a_clean_reason(monkeypatch, tmp_path):
    """The reason is the model's: an escape sequence in it would drive the
    terminal on its way to stderr."""
    from kotogen.generators import text_source

    class Client:
        def chat_json(self, system, user):
            return {"error": "a list of rules\x1b]0;title\x07"}

    monkeypatch.setattr(grammar, "AIClient", lambda **kwargs: Client())
    monkeypatch.setattr(text_source, "page_text", lambda url: ("index", "..."))
    with pytest.raises(SystemExit) as err:
        grammar.run_grammar(build_parser().parse_args(
            ["grammar", "--url", "https://example.jp/index",
             "--output", str(tmp_path / "grammar.tsv")]))
    assert "a list of rules" in str(err.value)
    assert "\x1b" not in str(err.value) and "\x07" not in str(err.value)


@pytest.mark.parametrize("failing", ["_detect_info", "_generate_cards"])
def test_a_failed_call_exits_on_the_first_line_of_its_reason(monkeypatch, tmp_path,
                                                             failing):
    """The error of a model call carries its raw answer below the first line."""
    def fail(*args, **kwargs):
        raise RuntimeError('unreadable answer\n{"cards": "the raw answer"}')

    monkeypatch.setattr(grammar, "AIClient", lambda **kwargs: object())
    monkeypatch.setattr(grammar, "_detect_info", lambda client, source: {
        "rule_tag": "のに", "level": "N4", "meaning": "although"})
    monkeypatch.setattr(grammar, failing, fail)
    with pytest.raises(SystemExit) as err:
        grammar.run_grammar(build_parser().parse_args(
            ["grammar", "のに", "--output", str(tmp_path / "grammar.tsv")]))
    assert "unreadable answer" in str(err.value)
    assert "raw answer" not in str(err.value)


def test_a_typed_rule_reaches_the_model_under_its_name_and_its_use(table, monkeypatch,
                                                                  tmp_path):
    """のに typed alone is のに（逆接） in the table: the model is told that name and
    that use, as for a rule drawn from a level, not the form typed."""
    asked = []

    class Client:
        def chat_json(self, system, user):
            asked.append(user)
            return []

    monkeypatch.setattr(grammar, "AIClient", lambda **kwargs: Client())
    with pytest.raises(SystemExit, match="No card generated"):
        grammar.run_grammar(build_parser().parse_args(
            ["grammar", "のに", "--output", str(tmp_path / "grammar.tsv")]))
    assert len(asked) == 1
    assert "のに（逆接）" in asked[0] and "Bien que, alors que" in asked[0]


# ── A rule file ──────────────────────────────────────────────────────────────

def test_a_rule_file_is_read_line_by_line(tmp_path):
    listing = tmp_path / "rules.md"
    listing.write_text("# ce qu'il me reste\nのに\n\n  〜たら  \nyounitanomu\n",
                       encoding="utf-8")
    assert _read_rules(listing) == ["のに", "〜たら", "younitanomu"]


def test_an_empty_file_says_so_instead_of_generating(tmp_path):
    listing = tmp_path / "empty.md"
    listing.write_text("# nothing but notes\n\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="No rule in"):
        _read_rules(listing)


# ── The local trace of what is done ──────────────────────────────────────────

def test_a_rule_that_is_done_stays_in_the_list_marked(table):
    """Marked, not removed: the list shows where one stands, and a rule can be
    taken up again for more cards."""
    with patch("kotogen.seen.load", return_value={"やすい": "やすい"}):
        rules = rules_of_level("N4", "Grammar", Held())
    assert [(r.title, r.done) for r in rules] == [("のに（逆接）", False), ("やすい", True)]


def test_the_history_keeps_the_canonical_name():
    with patch("kotogen.seen.mark") as marked:
        _mark_done("〜のに（目的）")
    marked.assert_called_once_with("grammar", RULES_SOURCE, "のに目的", "〜のに（目的）")


def test_a_rule_held_under_the_name_typed_is_known(monkeypatch):
    """A card may carry a name the table spells otherwise: one named 〜てください
    holds て形＋ください, and `maintain` does not propose the rule again."""
    monkeypatch.setattr(grammar_table, "load", lambda: [
        {"title": "て形＋ください", "level": "N5", "tier": "1", "meaning_en": "please do"}])
    monkeypatch.setattr(grammar, "_rules_seen", lambda: set())
    assert grammar.knows_rule("〜てください", {grammar_table.key("〜てください")})
    assert grammar.knows_rule("〜てください", {grammar_table.key("て形＋ください")})
    assert not grammar.knows_rule("〜てください", set())


class _Answering:
    """Hands back the same answer to every call."""

    def __init__(self, answer):
        self.answer = answer

    def chat_json(self, system, user):
        return self.answer


def test_an_answer_of_another_shape_names_its_kind_plainly():
    """The name of the type, not "<class 'int'>"."""
    with pytest.raises(ValueError, match="^unexpected JSON structure: int$"):
        grammar._generate_cards(_Answering(3), "ながら", "N4", 1)


@pytest.mark.parametrize("given", [[], ["nhk"]])
def test_the_usage_types_the_rule_as_the_shell_takes_it(given):
    """The quotes of a command line are the shell's: the screen's own, French
    guillemets say, would not run once pasted."""
    args = build_parser().parse_args(["grammar", *given])
    with pytest.raises(SystemExit) as err:
        grammar.run_grammar(args)
    assert 'kotogen grammar "〜てください"' in str(err.value)
