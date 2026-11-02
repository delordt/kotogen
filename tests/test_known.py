"""What already exists: what is known must not go back to the AI.

A collection (the deck, a file, or nothing) hands back its cards; the
comparisons are made here, the same for all three.
"""

import json
from pathlib import Path

import pytest

from conftest import Held, held_card
from kotogen import known
from kotogen.known import JsonlFile, Nothing, Sources, Words


def make_index(*expressions: str) -> Words:
    """Words built from expressions as a collection holds them."""
    return known.words_of(expressions)


# ── Recognising a word ────────────────────────────────────────────────────────

def test_an_identical_spelling_is_recognised():
    index = make_index("涼[すず]しい")
    assert index.has("涼しい")


def test_the_furigana_of_the_entry_are_ignored():
    index = make_index("食[た]べる")
    assert index.has("食[た]べる")


def test_kana_alone_find_the_kanji_spelling():
    index = make_index("食[た]べる")
    assert index.has("たべる")
    assert index.has("タベル")


def test_a_kanji_homophone_is_not_confused():
    """箸 must not be dropped because 橋 is in the deck (same reading)."""
    index = make_index("橋[はし]")
    assert not index.has("箸")


@pytest.mark.parametrize("deck, entry", [
    ("入[い]り口[ぐち]", "入口"),
    ("出掛[でか]ける", "出かける"),
    ("箇所[かしょ]", "個所"),
    ("なかなか", "中々"),
])
def test_another_spelling_of_the_same_word_is_recognised(deck, entry):
    """Same reading, and the dictionary files both spellings as one word or the
    deck writes it without a kanji."""
    assert make_index(deck).has(entry)


def test_the_same_kanji_with_other_kana_is_the_same_word():
    """真中 is 真ん中 with its kana left out. Out of context the dictionary
    reads it マナカ; the kanji, in order, already say it is one word."""
    assert make_index("真[ま]ん中[なか]").has("真中")


@pytest.mark.parametrize("deck, entry", [
    ("化学[かがく]", "科学"),
    ("機会[きかい]", "機械"),
    ("公園[こうえん]", "公演"),
    ("風[かぜ]", "風邪"),
])
def test_a_homophone_sharing_a_kanji_stays_apart(deck, entry):
    """Same reading and a kanji in common, still two words: 化学 in the deck
    must not keep 科学 from being generated."""
    assert not make_index(deck).has(entry)


def test_without_the_dictionary_a_shared_kanji_proves_nothing(monkeypatch):
    """What cannot be told apart is generated: a duplicate shows, a missing word
    does not."""
    from kotogen import dictionary

    monkeypatch.setattr(dictionary, "get_tagger", lambda: None)
    assert not make_index("出掛[でか]ける").has("出かける")
    assert make_index("真[ま]ん中[なか]").has("真中")


def test_a_homophone_sharing_no_kanji_stays_apart():
    """会う and 合う read あう alike and share nothing written: two words."""
    assert not make_index("合[あ]う").has("会う")


def test_two_spellings_with_no_kanji_in_common_stay_apart():
    """丸い and 円い are one word, but nothing written tells it from 会う and
    合う: both go through rather than drop a word."""
    assert not make_index("丸[まる]い").has("円い")


def test_a_shared_kanji_with_another_reading_stays_apart():
    """後ろ shares 後 with 後, but not its reading: another word."""
    assert not make_index("後[うし]ろ").has("後")


def test_an_absent_word():
    assert not make_index("涼[すず]しい").has("暑い")


def test_no_words_know_nothing():
    assert not known.NO_WORDS.has("涼しい")
    assert not known.NO_WORDS


def test_the_readings_and_their_spellings_are_kept():
    index = make_index("食[た]べる", "橋[はし]", "箸[はし]")
    assert index.readings == {"たべる", "はし"}
    assert index.spellings["はし"] == {"橋", "箸"}


# ── Raw entries ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("entry", [
    "涼しい",
    "涼しい - cool",
    "* 涼しい suzushii, cool (weather)",
    "涼[すず]しい",
])
def test_the_word_is_extracted_from_a_raw_entry(entry):
    assert make_index("涼[すず]しい").match(entry) == "涼しい"


def test_an_entry_with_no_japanese_is_never_dropped():
    """A romaji draft cannot be matched against the deck without the AI."""
    assert make_index("涼[すず]しい").match("suzushii - cool") == ""


def test_a_multi_word_entry_is_kept_if_only_one_is_known():
    index = make_index("行[い]く")
    assert index.match("行く、来る") == ""


def test_a_multi_word_entry_is_dropped_if_all_are_known():
    index = make_index("行[い]く", "来[く]る")
    assert index.match("行く、来る") == "行く、来る"


# ── Splitting a list ──────────────────────────────────────────────────────────

def test_split_known_separates_and_documents():
    index = make_index("涼[すず]しい")
    todo, held = known.split_known(["涼しい", "暑い"], index)
    assert todo == ["暑い"]
    assert held == [("涼しい", "涼しい")]


def test_split_known_with_no_words_keeps_everything():
    todo, held = known.split_known(["涼しい", "暑い"], known.NO_WORDS)
    assert todo == ["涼しい", "暑い"]
    assert held == []


# ── The words of a collection ─────────────────────────────────────────────────

def test_the_words_are_read_off_the_cards_of_the_note_type():
    deck = Held({"Vocabulary": [held_card(1, Expression="涼[すず]しい"),
                                held_card(2, Expression="食[た]べる")],
                 "Grammar": [held_card(3, Expression="暑[あつ]い")]})
    index = deck.words("Vocabulary")
    assert index.has("涼しい") and index.has("たべる")
    assert not index.has("暑い")


@pytest.mark.parametrize("value", [
    "<div>回[まわ]る</div>",
    "回[まわ]る<br>",
    "&nbsp;回[まわ]る",
])
def test_the_markup_of_the_anki_editor_is_not_part_of_the_word(value):
    index = Held({"Vocabulary": [held_card(1, Expression=value)]}).words("Vocabulary")
    assert index.has("回る")
    assert index.has("まわる")


def test_empty_or_absent_fields_hold_no_word():
    deck = Held({"Vocabulary": [held_card(1, Expression=""), held_card(2)]})
    assert not deck.words("Vocabulary")


def test_another_field_can_be_read():
    deck = Held({"Kanji": [held_card(1, Kanji="学")]})
    assert deck.words("Kanji", "Kanji").has("学")


# ── The sources already handled ───────────────────────────────────────────────

ARTICLE = "https://news.web.nhk/news/easy/ne2026071201/ne2026071201.html"
BOOK = "https://tadoku.org/japanese/book/6346/"
EPISODE = "Nihongo con Teppei 波! - Ep 700"
VIDEO = "Onomappu - なんとか (00:12 → 00:45) https://youtu.be/AbCd1234xyz"


def index(*traces: str, mode: str = "audio") -> Sources:
    return Sources({mode: frozenset(traces)})


def test_the_field_carries_the_trace_as_it_stands():
    assert index(ARTICLE).knows("audio", ARTICLE)


def test_what_locates_the_passage_does_not_get_in_the_way():
    """The bounds of an extract or the page range `provenance` appends to a
    source do not change the source."""
    assert index(f"{BOOK} (p. 3-)", mode="reading").knows("reading", BOOK)
    assert index(f"{EPISODE} (00:12 → 00:45)").knows("audio", EPISODE)
    assert index(f"{VIDEO}").knows("audio", "Onomappu - なんとか")


def test_two_numbered_episodes_are_not_taken_for_one_another():
    """"Ep 7" starts "Ep 70": without the expected continuation, one episode
    would drop the other unnoticed."""
    assert not index("Feed - Ep 70 (00:12 → 00:45)").knows("audio", "Feed - Ep 7")


def test_the_mode_partitions_the_way_the_history_does():
    """An article handled for listening is still to do for reading: the note
    type of the card tells which."""
    deck = index(ARTICLE)
    assert deck.knows("audio", ARTICLE)
    assert not deck.knows("reading", ARTICLE)


def test_an_empty_trace_knows_nothing():
    """An empty trace begins every source, so it would drop everything."""
    assert not index(ARTICLE).knows("audio", "")
    assert not index(ARTICLE).knows_id("audio", "  ")


def test_an_identifier_is_looked_for_wherever_it_sits():
    """The ID of a video sits behind its title, and the news_id of an article
    survives a change of domain on the site."""
    assert index(VIDEO).knows_id("audio", "youtu.be/AbCd1234xyz")
    assert index("https://www3.nhk.or.jp/news/easy/ne2026071201/ne2026071201.html") \
        .knows_id("audio", "ne2026071201")


def _sourced(**by_notetype: list[str]) -> Held:
    return Held({notetype: [held_card(i, Source=trace) for i, trace in enumerate(traces)]
                 for notetype, traces in by_notetype.items()})


def test_the_provenances_are_filed_by_mode():
    deck = _sourced(Listening=[EPISODE], Reading=[BOOK, ARTICLE]).sources()
    assert deck.traces("audio") == frozenset({EPISODE})
    assert deck.knows("reading", BOOK) and not deck.knows("audio", BOOK)


def test_empty_or_absent_sources_are_left_out():
    deck = Held({"Listening": [held_card(1, Source="  "), held_card(2)]})
    assert not deck.sources()


def test_the_sources_are_read_once_then_forgotten_by_a_send():
    reads = []

    class Counted(Held):
        def cards(self, notetype):
            reads.append(notetype)
            return super().cards(notetype)

    deck = Counted({"Listening": [held_card(1, Source=ARTICLE)]})
    assert deck.sources().knows("audio", ARTICLE)
    deck.sources()
    assert len(reads) == 2          # one command reads the deck once: two modes
    deck.forget()                   # what a send calls: the deck has changed
    deck.sources()
    assert len(reads) == 4


# ── Nothing, and a file ───────────────────────────────────────────────────────

def test_nothing_holds_nothing_and_says_so():
    nothing = Nothing()
    assert nothing.cards("Vocabulary") == []
    assert not nothing.words("Vocabulary") and not nothing.sources()
    assert nothing.reachable("Vocabulary")      # "nothing" is an answer
    assert nothing.learning("Vocabulary") is None
    assert nothing.history(Path("seen.json")) is None
    assert nothing.name("Japanese") == "Japanese"


def _jsonl(path, notetype, *lines: dict | str) -> None:
    header = {"format": "kotogen", "version": 1, "deck": "Japanese", "notetype": notetype}
    path.write_text("\n".join([json.dumps(header, ensure_ascii=False),
                               *(line if isinstance(line, str)
                                 else json.dumps(line, ensure_ascii=False)
                                 for line in lines)]) + "\n", encoding="utf-8")


def test_the_cards_of_a_file_are_read_as_a_deck_hands_them_back(tmp_path):
    path = tmp_path / "set.jsonl"
    _jsonl(path, "Vocabulary", {"id": "vocab:涼しい:すずしい",
                                "fields": {"Expression": "涼[すず]しい"},
                                "tags": ["Level::N5"]})
    [card] = JsonlFile(path).cards("Vocabulary")
    assert card == {"id": "vocab:涼しい:すずしい", "kind": None,
                    "fields": {"Expression": "涼[すず]しい"}, "tags": ["Level::N5"]}


def test_the_kind_of_a_card_is_read_off_its_fields_when_its_line_says_none(tmp_path):
    from kotogen.generators import vocab

    path = tmp_path / "set.jsonl"
    _jsonl(path, "Vocabulary", {"fields": {name: "" for name in vocab.FIELDS}})
    assert [card["kind"] for card in JsonlFile(path).cards("Vocabulary")] == ["vocab"]


def test_a_file_of_another_note_type_holds_nothing_of_this_one(tmp_path):
    path = tmp_path / "set.jsonl"
    _jsonl(path, "Vocabulary", {"fields": {"Expression": "涼[すず]しい"}})
    assert JsonlFile(path).cards("Grammar") == []


def test_a_broken_line_is_one_card_fewer(tmp_path):
    path = tmp_path / "set.jsonl"
    _jsonl(path, "Vocabulary", {"fields": {"Expression": "涼[すず]しい"}},
           '{"fields": ', {"fields": {"Expression": "暑[あつ]い"}})
    assert len(JsonlFile(path).cards("Vocabulary")) == 2


def test_a_file_not_written_yet_holds_nothing_and_answers(tmp_path):
    absent = JsonlFile(tmp_path / "absent.jsonl")
    assert absent.cards("Vocabulary") == []
    assert absent.reachable("Vocabulary")


def test_a_file_keeps_its_history_beside_it(tmp_path):
    path = tmp_path / "set.jsonl"
    assert JsonlFile(path).history(tmp_path / "seen.json") == tmp_path / "set.seen.json"
    assert JsonlFile(path).name("Japanese") == "set.jsonl"
