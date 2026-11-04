"""Texts written on the deck: the measure, the targets, and the rewrite."""

import pytest

from conftest import Held, held_card
from kotogen import coverage, i18n, known, proofreading, seen
from kotogen.cli import build_parser
from kotogen.furigana import get_tagger
from kotogen.generators import deck_story

needs_mecab = pytest.mark.skipif(get_tagger() is None, reason="MeCab unavailable")


def _index(*words):
    return known.words_of(words)


# ── The measure ───────────────────────────────────────────────────────────────

@needs_mecab
def test_only_the_content_words_are_counted():
    """Particles, auxiliaries and the いる of ている are grammar, not words."""
    measured = coverage.measure(["友達と話していました。"], lambda word: True)
    # 友達, 話す: the と, the て, the いる, the ます and the た weigh nothing.
    assert measured.words == 2
    assert measured.ratio == 1.0


@needs_mecab
def test_a_word_is_asked_for_in_its_dictionary_form():
    asked = []
    coverage.measure(["駅まで行きました。"], lambda word: asked.append(word) or True)
    assert "行く" in asked and "行き" not in asked


@needs_mecab
def test_the_unknown_words_are_listed_once_in_order():
    measured = coverage.measure(["猫が犬を見た。犬は猫を見た。"],
                                lambda word: word == "見る")
    assert measured.unknown == ("猫", "犬")
    assert (measured.words, measured.known) == (6, 2)


@needs_mecab
def test_a_compound_of_the_deck_is_one_known_word():
    """unidic cuts 日本語 in two; the deck holds it whole."""
    measured = coverage.measure(["日本語を勉強します。"],
                                lambda word: word in {"日本語", "勉強"})
    assert measured.unknown == ()
    assert measured.known == measured.words


@needs_mecab
def test_uses_finds_a_word_under_any_of_its_forms():
    measured = coverage.measure(["毎朝パンを食べました。"], lambda word: True)
    assert measured.uses("食べる")
    assert not measured.uses("飲む")


@needs_mecab
@pytest.mark.parametrize("line", ["車を運転して駅に行きました。", "毎日運転しています。",
                                  "弟に運転させた。", "もう運転できます。"])
def test_uses_finds_a_suru_verb_of_the_deck_conjugated(line):
    """unidic cuts 運転して into 運転 and する: the deck holds 運転する."""
    assert coverage.measure([line], lambda word: True).uses("運転する")


@needs_mecab
def test_a_noun_without_its_suru_is_not_the_verb():
    measured = coverage.measure(["運転が好きです。"], lambda word: True)
    assert measured.uses("運転")
    assert not measured.uses("運転する")


def test_without_mecab_there_is_no_figure(monkeypatch):
    monkeypatch.setattr(coverage, "get_tagger", lambda: None)
    assert coverage.measure(["猫"], lambda word: True) is None


def test_what_the_learner_knows_is_the_deck_and_the_levels_below():
    known = deck_story.knows(_index("醤油"), "N4")
    assert known("醤油")          # in the deck, whatever its level
    assert known("食べる")        # N5, below the text
    assert not known("経験")      # N4 itself: where the new words come from


# ── Lengths ───────────────────────────────────────────────────────────────────

def test_a_long_text_does_not_exist_below_n3():
    assert deck_story.characters("N4", "long") == deck_story.characters("N4", "medium")
    assert deck_story.exam_name("N4", "long") == "中文"
    assert deck_story.exam_name("N2", "long") == "長文"


# ── The targets ───────────────────────────────────────────────────────────────

def _note(note_id, word, *tags):
    return held_card(note_id, tags=tags, Expression=word)


@pytest.fixture
def deck(monkeypatch) -> Held:
    """A deck of four words, one leech and one young card among them."""
    monkeypatch.setattr(deck_story, "_notetype",
                        lambda command: {"vocab": "Vocabulary", "grammar": "Grammar"}[command])
    return Held({"Vocabulary": [
        _note(1, "机", "Level::N5"),
        _note(2, "経験", "Level::N4", "leech"),
        _note(3, "予定", "Level::N4"),
        _note(4, "趣味", "Level::N4"),
    ], "Grammar": []}, learning={"Vocabulary": {3}})


def test_leeches_come_first_then_the_young_cards(deck):
    planned, intervals = deck_story.plan(1, "auto", "short", deck)
    assert intervals
    assert planned[0].words[:2] == ("経験", "予定")


def test_two_texts_of_one_run_share_no_word(deck):
    deck.by_notetype["Vocabulary"] += [_note(i, word, "Level::N4")
                                       for i, word in enumerate("春夏秋冬雨雪", start=10)]
    planned, _ = deck_story.plan(2, "N4", "short", deck)
    assert len(planned) == 2
    assert not set(planned[0].words) & set(planned[1].words)


def test_the_level_follows_the_targets(deck):
    planned, _ = deck_story.plan(1, "auto", "short", deck)
    assert planned[0].level == "N4"


def test_the_words_that_waited_longest_go_first(deck):
    # No leech and no young card: the history alone decides.
    deck.by_notetype["Vocabulary"][1]["tags"] = ["Level::N4"]
    deck._learning = {}
    seen.mark("reading", deck_story.HISTORY_SOURCE, "経験", "2026-09-01")
    seen.mark("reading", deck_story.HISTORY_SOURCE, "予定", "2026-09-10")
    seen.mark("reading", deck_story.HISTORY_SOURCE, "趣味", "2026-09-12")
    planned, _ = deck_story.plan(1, "N4", "short", deck)
    assert planned[0].words == ("机", "経験", "予定")


def test_anki_closed_draws_from_the_whole_deck(deck):
    deck._learning = None   # what a deck that cannot say answers
    planned, intervals = deck_story.plan(1, "N4", "short", deck)
    assert not intervals
    assert planned[0].words[0] == "経験"      # a leech is a tag: the copy has it


def test_an_empty_deck_says_there_is_nothing_to_write_on(deck):
    deck.by_notetype["Vocabulary"].clear()
    with pytest.raises(RuntimeError, match="no vocabulary card"):
        deck_story.plan(1, "auto", "short", deck)


def test_a_level_asked_for_leaves_the_words_above_it_for_later(deck):
    """A leech goes first, but not into a text below its level: it waits for a
    text where the rest of the words may be as hard as it is."""
    deck.by_notetype["Vocabulary"][1]["tags"] = ["Level::N2", "leech"]
    planned, _ = deck_story.plan(1, "N4", "short", deck)
    assert "経験" not in planned[0].words
    assert planned[0].words[0] == "予定"


def test_with_the_level_of_the_deck_the_words_come_as_they_are(deck):
    """The words are what sets the level: holding back the one above the others
    would hold it back at every run."""
    deck.by_notetype["Vocabulary"][1]["tags"] = ["Level::N2", "leech"]
    planned, _ = deck_story.plan(1, "auto", "short", deck)
    assert planned[0].level == "N4"
    assert planned[0].words[0] == "経験"


def test_a_level_the_deck_has_no_word_for_says_so(deck):
    with pytest.raises(RuntimeError, match="at N5 or below"):
        deck_story.plan(1, "N5", "short", _without(deck, "机"))


def _without(deck: Held, word: str) -> Held:
    deck.by_notetype["Vocabulary"] = [card for card in deck.by_notetype["Vocabulary"]
                                      if card["fields"]["Expression"] != word]
    return deck


def test_rules_above_the_level_are_left_for_later(deck):
    deck.by_notetype["Grammar"] += [
        held_card(tags=["Grammar::N4::ながら"], Rule="ながら"),
        held_card(tags=["Grammar::N2::にもかかわらず"], Rule="にもかかわらず"),
    ]
    planned, _ = deck_story.plan(1, "N4", "medium", deck)
    assert planned[0].rules == ("ながら",)


# ── Writing, measuring, rewriting ─────────────────────────────────────────────

class _Client:
    """Hands back the texts it is given, one per call, and keeps the requests."""

    def __init__(self, *texts):
        self.texts = list(texts)
        self.requests = []

    def chat_json(self, system, user):
        self.requests.append(user)
        return {"title": "猫", "lines": [self.texts.pop(0)]}


def _story(client, index=None):
    targets = deck_story.Targets(("経験",), (), "N4")
    return deck_story.DeckStory(client, targets, "story", "short",
                                index or _index("経験", "猫"))


@needs_mecab
def test_a_text_at_the_level_is_written_once():
    client = _Client("猫と行く経験をした。")
    story = _story(client)
    title, lines = story.fetch()
    assert len(client.requests) == 1
    assert not story.rewritten and not story.too_hard
    assert lines and title


@needs_mecab
def test_a_text_too_hard_is_rewritten_with_its_unknown_words():
    client = _Client("猫を見る経験をした。憂鬱な霧雨だった。", "猫と行く経験をした。")
    story = _story(client)
    story.fetch()
    assert len(client.requests) == 2
    assert "憂鬱" in client.requests[1] and "Rewrite" in client.requests[1]
    assert story.rewritten and not story.too_hard


@needs_mecab
def test_a_text_still_too_hard_marks_its_cards():
    hard = "憂鬱な霧雨の経験。"
    story = _story(_Client(hard, hard))
    story.fetch()
    assert story.too_hard
    cards = [{"ID": "RC_1"}]
    story.check(cards)
    assert proofreading.tags(cards) == [deck_story.COVERAGE_TAG]


@needs_mecab
def test_a_failed_rewrite_keeps_the_text_already_written(capsys):
    """The first text is paid for: a rewrite that fails keeps it, its cards
    filed as too hard, rather than losing the whole source."""
    class Failing(_Client):
        def chat_json(self, system, user):
            if self.requests:
                self.requests.append(user)
                raise ValueError("The AI did not return valid JSON.")
            return super().chat_json(system, user)

    story = _story(Failing("憂鬱な霧雨の経験。"))
    _title, lines = story.fetch()

    assert "霧雨" in lines[0]
    assert story.too_hard and not story.rewritten
    story.report()
    assert "rewrite failed" in capsys.readouterr().err


@needs_mecab
def test_the_rewrite_is_kept_only_if_it_reads_better():
    story = _story(_Client("猫の経験と憂鬱。", "憂鬱な霧雨の靄。"))
    _title, lines = story.fetch()
    assert "猫" in lines[0]


@needs_mecab
def test_only_the_words_really_used_wait_their_turn_again():
    targets = deck_story.Targets(("経験", "予定"), (), "N4")
    story = deck_story.DeckStory(_Client("猫と行く経験をした。"), targets,
                                 "story", "short", _index("経験", "予定", "猫"))
    story.fetch()
    story.mark_done("猫")
    assert set(seen.load("reading", deck_story.HISTORY_SOURCE)) == {"経験"}


def test_the_source_field_says_the_deck_wrote_it_at_that_size():
    """Card content, so it follows the suite's French deck. The name is never
    translated, and the level and exam size read the same in every language."""
    story = _story(_Client())
    assert story.provenance == "Kotogen - écrit d'après le deck (N4, récit, 短文)"


def test_such_a_provenance_is_read_back_by_the_name_that_opens_it():
    """By the name alone: the rest changes with the language setting, and the
    deck would stop recognising its own texts."""
    assert (deck_story.recognise(_story(_Client()).provenance)
            == (deck_story.HISTORY_SOURCE, ""))
    assert (deck_story.recognise("Kotogen - written on the deck (N4, story, 短文)")
            == (deck_story.HISTORY_SOURCE, ""))
    assert deck_story.recognise("my_course.pdf (p. 2)") is None


# ── The command line ──────────────────────────────────────────────────────────

def test_the_command_line_defaults_to_one_short_story():
    args = build_parser().parse_args(["reading", "deck"])
    assert (args.shape, args.length, args.texts) == ("story", "short", None)


def test_shape_and_length_are_checked_by_the_parser():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["reading", "deck", "--length", "huge"])


def test_the_ids_of_its_cards_open_on_a_short_name():
    assert _story(_Client()).name == "deck_N4"


@pytest.mark.parametrize("lang", [name for name in i18n.available()
                                  if name != i18n.SOURCE])
def test_every_table_names_each_shape_of_text(lang):
    """A shape is an English word of the command line, said under the `shape`
    context on the summary of the text."""
    table = i18n._load(lang)
    wanted = [f"shape|{shape}" for shape in deck_story.SHAPES]
    assert [key for key in wanted if key not in table] == []


class _Answering:
    """Hands back the same answer to every call."""

    def __init__(self, answer):
        self.answer = answer

    def chat_json(self, system, user):
        return self.answer


def test_an_answer_of_another_shape_names_its_kind_plainly():
    """The name of the type, not "<class 'list'>"."""
    targets = deck_story.Targets(("経験",), (), "N4")
    with pytest.raises(ValueError, match="^unexpected JSON structure: list$"):
        deck_story._written(_Answering([]), targets, "story", "short")
