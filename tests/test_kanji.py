"""Kanji cards: the facts from the tables, the rest from the model, checked."""

from __future__ import annotations

import argparse

import pytest

from conftest import Held, held_card
from kotogen import dictionary, identity, memory
from kotogen.generators import kanji
from kotogen.generators.kanji import Target


class FakeClient:
    """Faked AI client: hands back the given answers, keeps the messages received."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def chat_json(self, system, user):
        self.prompts.append(user)
        return self.responses.pop(0) if self.responses else []


def note(**fields):
    return held_card(**fields)


VOCABULARY = [
    note(Expression="学生[がくせい]", Translation="étudiant"),
    note(Expression="大学[だいがく]", Translation="université"),
    note(Expression="学[まな]ぶ", Translation="apprendre"),
    note(Expression="先生[せんせい]", Translation="professeur"),
    note(Expression="今日[きょう]", Translation="aujourd'hui"),
    note(Expression="一昨日[おととい]", Translation="avant-hier"),
    note(Expression="一[いち]", Translation="un"),
]


@pytest.fixture
def deck(monkeypatch):
    """A vocabulary deck, and a kanji deck the test fills."""
    carded: list[dict] = []
    monkeypatch.setattr(memory, "_known",
                        Held({"Vocabulary": VOCABULARY, "Kanji": carded}))
    return carded


@pytest.fixture
def vocabulary(deck):
    return kanji.read_vocabulary(memory.known(), "Vocabulary")


def answer(char="学", words=None, **extra):
    item = {"Kanji": char, "Meaning": "étude, apprentissage",
            "Words": words if words is not None else [
                {"word": "大学[だいがく]", "meaning": "université", "reading": "ガク"},
                {"word": "学[まな]ぶ", "meaning": "apprendre", "reading": "まな.ぶ"}],
            "Composition": "⺍ + 冖 + 子 - un enfant sous un toit",
            "LookAlikes": "", "Notes": "", "Decoys": ["字", "覚", "挙"]}
    item.update(extra)
    return item


# ── Which kanji ───────────────────────────────────────────────────────────────

def test_a_word_gives_each_of_its_kanji():
    targets, already = kanji.typed("学生", set())
    assert [t.kanji for t in targets] == ["学", "生"] and already == []


def test_a_kanji_that_has_a_card_is_left_out():
    targets, already = kanji.typed("学生", {"学"})
    assert [t.kanji for t in targets] == ["生"] and already == ["学"]


def test_an_entry_with_no_kanji_goes_to_the_model_as_it_is():
    targets, _already = kanji.typed(" gaku ", set())
    assert targets == [Target(entry="gaku")]


def test_the_deck_ranks_by_level_then_by_the_words_a_kanji_links(vocabulary):
    """学 is in three words of the deck, 生 in two: 学 first."""
    assert kanji.of_deck(vocabulary, set(), "auto")[:2] == ["学", "生"]
    assert "学" not in kanji.of_deck(vocabulary, {"学"}, "auto")


def test_the_deck_counts_the_words_of_each_kanji(vocabulary):
    assert vocabulary.counts["学"] == 3
    assert [w.surface for w in vocabulary.by_kanji["生"]] == ["学生", "先生"]


def test_a_level_keeps_the_joyo_kanji_only():
    """A level is filled with the kanji one reads, never with a name kanji (翔)."""
    n1 = kanji.of_level("N1", set())
    assert "翔" not in n1 and n1
    assert "日" not in kanji.of_level("N5", {"日"})


def test_a_text_gives_its_joyo_kanji_the_easiest_first():
    found = kanji.of_text("翔は鬱陶しい学校に行く。", set(), "auto")
    assert "翔" not in found
    assert found.index("学") < found.index("鬱")


def test_a_level_asked_for_keeps_that_level_only():
    assert kanji.of_text("学校と鬱", set(), "N5") == ["学", "校"]


# ── The words, against the table ──────────────────────────────────────────────

@pytest.mark.parametrize("word, char, reading, holds", [
    ("学生[がくせい]", "学", "ガク", True),
    ("学校[がっこう]", "学", "ガク", True),        # がく doubled into がっ
    ("花火[はなび]", "火", "ひ", True),            # ひ voiced into び
    ("学生[がくせい]", "学", "まな.ぶ", False),
])
def test_a_word_holds_the_reading_it_is_labelled_with(word, char, reading, holds):
    info = kanji.kanji_table.lookup(char)
    labelled = next(r for r in info.readings if r.text == reading)
    assert kanji.carries(word, labelled) is holds


def test_a_card_lays_the_facts_of_the_tables(vocabulary):
    card = kanji.assemble(answer(), vocabulary).card
    assert card["Onyomi"] == "ガク" and card["Kunyomi"] == "まな.ぶ"
    assert card["OtherReadings"] == ""
    assert card["Words"] == ("大学[だいがく]|université|ガク\n"
                             "学[まな]ぶ|apprendre|まな.ぶ")
    assert (card["Strokes"], card["Tags"]) == ("8", "Level::N5")
    assert [card[f"Decoy{n}"] for n in (1, 2, 3)] == ["字", "覚", "挙"]


def test_the_readings_no_word_carries_wait_among_the_others(vocabulary):
    """生 has twelve common readings: the card shows the two its words carry."""
    card = kanji.assemble(answer("生", [
        {"word": "学生[がくせい]", "meaning": "étudiant", "reading": "セイ"},
        {"word": "生[い]きる", "meaning": "vivre", "reading": "い.きる"}]), vocabulary).card
    assert card["Onyomi"] == "セイ" and card["Kunyomi"] == "い.きる"
    others = card["OtherReadings"].split("、")
    assert "ショウ" in others and "なま" in others and len(others) == 10


def test_a_word_that_holds_no_reading_of_the_table_is_dropped(vocabulary):
    checked = kanji.assemble(answer(words=[
        {"word": "学生[かくせい]", "meaning": "étudiant", "reading": "ガク"},
        {"word": "大学[だいがく]", "meaning": "université", "reading": "ガク"}]), vocabulary)
    assert checked.card["Words"] == "大学[だいがく]|université|ガク"


def test_a_reading_the_table_does_not_give_is_dropped(vocabulary):
    checked = kanji.assemble(answer(words=[
        {"word": "学生[かくせい]", "meaning": "étudiant", "reading": "ラク"},
        {"word": "大学[だいがく]", "meaning": "université", "reading": "ガク"}]), vocabulary)
    assert "学生" not in checked.card["Words"]


@pytest.mark.parametrize("char, word, label, reading", [
    ("長", "長[なが]さ", "なが", "なが.い"),       # the okurigana left out
    ("出", "出口[でぐち]", "で", "で.る"),
    ("口", "出口[でぐち]", "ぐち", "くち"),       # as the word voices it
    ("見", "花見[はなみ]", "み", "み.る"),          # three stems み: the first is taken
    ("日", "土曜日[どようび]", "ニチ", "ひ"),        # a label the word does not carry
    ("学", "学生[がくせい]", "まな.ぶ", "ガク"),
])
def test_the_word_names_the_reading_a_label_misses(vocabulary, char, word, label, reading):
    checked = kanji.assemble(answer(char, [
        {"word": word, "meaning": "x", "reading": label}]), vocabulary)
    assert checked.card["Words"].endswith(f"|x|{reading}")


def test_a_reading_given_without_its_dot_or_in_hiragana_still_names_it(vocabulary):
    card = kanji.assemble(answer(words=[
        {"word": "大学[だいがく]", "meaning": "université", "reading": "がく"},
        {"word": "学[まな]ぶ", "meaning": "apprendre", "reading": "まなぶ"}]), vocabulary).card
    assert card["Onyomi"] == "ガク" and card["Kunyomi"] == "まな.ぶ"


def test_a_word_read_as_a_whole_illustrates_no_reading(vocabulary):
    checked = kanji.assemble(answer("今", [
        {"word": "今日[きょう]", "meaning": "aujourd'hui", "reading": "コン"},
        {"word": "今[いま]", "meaning": "maintenant", "reading": "いま"}]), vocabulary)
    assert checked.card["Words"] == "今[いま]|maintenant|いま"


def test_the_first_word_writes_the_kanji_once(vocabulary):
    """It is the word the Production card will hide the kanji in: a word writing
    it twice would leave it on show. (人々 writes it once - 々 is not 人.)"""
    card = kanji.assemble(answer(words=[
        {"word": "学学[がくがく]", "meaning": "étude d'étude", "reading": "ガク"},
        {"word": "大学[だいがく]", "meaning": "université", "reading": "ガク"}]),
        vocabulary).card
    assert card["Words"].startswith("大学")


def test_a_decoy_that_would_make_a_real_word_is_dropped(vocabulary):
    """学生 with 先 in the place of 学 reads 先生: the card would have two answers."""
    card = kanji.assemble(answer(words=[
        {"word": "学生[がくせい]", "meaning": "étudiant", "reading": "ガク"}],
        Decoys=["先", "字", "覚", "挙"]), vocabulary).card
    assert [card.get(f"Decoy{n}") for n in (1, 2, 3)] == ["字", "覚", "挙"]


def test_a_field_too_long_is_left_out(vocabulary):
    checked = kanji.assemble(answer(Composition="x" * 200), vocabulary)
    assert checked.card["Composition"] == ""


def test_a_composition_that_names_no_other_kanji_is_left_out(vocabulary):
    """It would only describe the drawing already on the card."""
    checked = kanji.assemble(answer("一", words=[
        {"word": "一[いち]", "meaning": "un", "reading": "イチ"}],
        Composition="un seul trait horizontal - le nombre un",
        LookAlikes="二 deux - deux traits"), vocabulary)
    assert checked.card["Composition"] == ""
    assert checked.card["LookAlikes"] == "二 deux - deux traits"


def test_the_notes_are_the_whole_words_the_learner_has_met(vocabulary):
    """今日 is in the deck, 今朝 and 今年 are not: the card names 今日 alone."""
    assert kanji.special_notes("今", vocabulary) == " 今日[きょう]"
    assert kanji.special_notes("学", vocabulary) == ""


def test_a_whole_word_met_under_its_ordinary_reading_is_not_named(monkeypatch):
    """五月 learnt as ごがつ says nothing of さつき, and is no note of 月."""
    monkeypatch.setattr(memory, "_known", Held({"Vocabulary": [
        note(Expression="五月[ごがつ]", Translation="mai"),
        note(Expression="五月[さつき]", Translation="mai (ancien)")]}))
    assert kanji.special_notes("月", kanji.read_vocabulary(memory.known(), "Vocabulary")) \
        == " 五月[さつき]"


def test_the_model_writes_no_notes(vocabulary):
    checked = kanji.assemble(answer(Notes="Les compteurs changent le son"), vocabulary)
    assert checked.card["Notes"] == ""


def test_a_kanji_outside_the_joyo_table_is_tagged_for_its_readings(vocabulary):
    card = kanji.assemble(answer("鞄", [
        {"word": "鞄[かばん]", "meaning": "sac", "reading": "かばん"}], Decoys=[]),
        vocabulary).card
    assert card["Kunyomi"] == "かばん" and card["Strokes"] == "14"
    assert card["Tags"] == dictionary.READING_TAG


def test_no_word_that_holds_up_is_no_card(vocabulary):
    checked = kanji.assemble(answer(words=[
        {"word": "先生[せんせい]", "meaning": "professeur", "reading": "ガク"}]), vocabulary)
    assert checked.card is None


# ── What the model is told ────────────────────────────────────────────────────

def test_the_request_gives_the_readings_the_learner_words_and_the_whole_words(vocabulary):
    text = kanji._request([Target("学"), Target("今"), Target(entry="gaku")], vocabulary)
    assert "ガク、まな.ぶ" in text
    assert "学生[がくせい] (étudiant)" in text
    assert "今日 (きょう)" in text                 # read as a whole, said as such
    assert "今日[きょう] (aujourd'hui)" not in text  # and never offered as a word
    assert "gaku" in text


def test_a_deck_word_that_holds_no_reading_of_the_kanji_is_not_offered(vocabulary):
    """一昨日 is おととい: read as a whole, although the appendix does not list it."""
    text = kanji._request([Target("一")], vocabulary)
    assert "一[いち] (un)" in text
    assert "一昨日" not in text


# ── A run ─────────────────────────────────────────────────────────────────────

def make_args(tmp_path, **extra):
    defaults = dict(entry="学", file=None, count=None, level="auto", force=False,
                    batch_size=8, jobs=1, deck="Japanese::Kanji", notetype="Kanji",
                    send=False, output=str(tmp_path / "kanji.tsv"), format=None,
                    provider="openrouter", model="test")
    defaults.update(extra)
    return argparse.Namespace(**defaults)


def test_a_run_writes_the_card(monkeypatch, tmp_path, deck):
    client = FakeClient([answer()])
    monkeypatch.setattr(kanji, "AIClient", lambda **kwargs: client)
    kanji.run_kanji(make_args(tmp_path))
    written = (tmp_path / "kanji.tsv").read_text(encoding="utf-8")
    assert "学\tétude, apprentissage\tガク\tまな.ぶ\t" in written
    # Written as the card reads it: one word per line, no reading on the kanji
    # itself, nor on a component or a decoy.
    assert "大学[だいがく]|université|ガク<br>学[まな]ぶ|apprendre|まな.ぶ" in written
    assert "子[こ]" not in written and "字[じ]" not in written


def test_the_preview_shows_no_control_character_of_the_model(monkeypatch, tmp_path, deck):
    previews = []
    client = FakeClient([answer(Meaning="étude\x1b[31m rouge")])
    monkeypatch.setattr(kanji, "AIClient", lambda **kwargs: client)
    monkeypatch.setattr(kanji, "finish", lambda *a, preview=(), **k: previews.extend(preview))
    kanji.run_kanji(make_args(tmp_path))
    assert previews and not any("\x1b" in line for line in previews)


@pytest.mark.parametrize("todo, count, total, said", [
    ("一二三", 5, None, "(3)"),
    ("一二三", 2, None, "(3, the 2 easiest)"),
    ("一二三", 1, 10, "(3 of 10, the easiest one)"),
    ("一二", 5, 10, "(2 of 10)"),
])
def test_what_was_found_is_said_in_one_sentence(capsys, todo, count, total, said):
    """One sentence per case, its count agreed: no fragment glued on."""
    assert kanji._found(list(todo), count, total=total) == list(todo)[:count]
    assert said in capsys.readouterr().out


def test_a_kanji_that_has_a_card_costs_no_call(monkeypatch, tmp_path, deck):
    deck.append(note(Kanji="学"))
    client = FakeClient([answer()])
    monkeypatch.setattr(kanji, "AIClient", lambda **kwargs: client)
    kanji.run_kanji(make_args(tmp_path))
    assert client.prompts == []


def test_an_entry_resolved_to_a_kanji_that_has_a_card_is_skipped(monkeypatch, tmp_path, deck):
    deck.append(note(Kanji="学"))
    client = FakeClient([answer()])
    monkeypatch.setattr(kanji, "AIClient", lambda **kwargs: client)
    with pytest.raises(SystemExit):
        kanji.run_kanji(make_args(tmp_path, entry="gaku"))
    assert len(client.prompts) == 1


def test_a_pdf_given_as_a_file_is_refused(monkeypatch, tmp_path, deck):
    """The refusal a PDF entry gets, not an error on decoding its bytes."""
    pdf = tmp_path / "lesson.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    monkeypatch.setattr(kanji, "AIClient", lambda **kwargs: FakeClient())
    with pytest.raises(SystemExit) as err:
        kanji.run_kanji(make_args(tmp_path, entry=None, file=pdf))
    assert "PDF" in str(err.value)


def test_a_file_in_shift_jis_is_read(monkeypatch, tmp_path, deck):
    """Read as the other text sources read it, a Japanese file being often Shift-JIS."""
    lesson = tmp_path / "lesson.txt"
    lesson.write_bytes("学ぶ".encode("cp932"))
    client = FakeClient([answer()])
    monkeypatch.setattr(kanji, "AIClient", lambda **kwargs: client)
    kanji.run_kanji(make_args(tmp_path, entry=None, file=lesson))
    assert "## 学" in client.prompts[0]


NHK_URL = "https://news.web.nhk/news/easy/ne2026010112345/ne2026010112345.html"

# What NHK Easy gives a plain HTTP read: the headline and the consent the site asks
# for, which only a browser gets past to the article. Invented lines of that shape.
NHK_OVER_HTTP = """<html><head><title>森の動物の話 | ニュース</title></head><body>
<h1>森の動物の話</h1>
<div><p>記事を読む前に、利用規約を確認して同意してください。</p>
<p>契約について詳しくは案内をお読みください。</p></div></body></html>"""


def test_a_page_that_cannot_be_read_exits_on_a_clean_reason(monkeypatch, tmp_path, deck):
    """An escape sequence from a page title would drive the terminal on stderr."""
    from kotogen.generators import text_source

    def unreachable(url):
        raise RuntimeError("page unreachable\x1b]0;title\x07\nwhat the server said")

    monkeypatch.setattr(text_source, "fetch", unreachable)
    monkeypatch.setattr(kanji, "AIClient", lambda **kwargs: FakeClient())
    with pytest.raises(SystemExit) as err:
        kanji.run_kanji(make_args(tmp_path, entry="https://example.jp/lesson"))
    assert str(err.value).startswith("page unreachable")
    assert "\x1b" not in str(err.value) and "server said" not in str(err.value)


def test_an_nhk_easy_article_is_read_in_the_browser(monkeypatch, tmp_path, deck):
    """Over plain HTTP its kanji would be those of the consent screen: the
    browser reads the article, as `vocab` has it read."""
    from kotogen.generators import nhk, text_source

    monkeypatch.setattr(text_source, "fetch_url", lambda url: (NHK_OVER_HTTP, "text/html"))
    monkeypatch.setattr(nhk, "fetch_article_text", lambda url: (
        "学校[がっこう]の 話[はなし]", ["学校[がっこう]で 学[まな]ぶ。"]))
    client = FakeClient([answer()])
    monkeypatch.setattr(kanji, "AIClient", lambda **kwargs: client)
    kanji.run_kanji(make_args(tmp_path, entry=NHK_URL))
    assert "## 学" in client.prompts[0] and "## 校" in client.prompts[0]
    assert "## 約" not in client.prompts[0]


# ── A lone kanji moved from the vocabulary (`maintain`) ──────────────────────

def test_a_lone_kanji_moved_from_the_vocabulary(monkeypatch, tmp_path):
    """Its card is made and sent, the kanji that had one costs no call, and the
    note being moved is not a word of its own card."""
    carded = [note(Kanji="学")]
    words = VOCABULARY + [note(Expression="語[ご]", Translation="langue"),
                          note(Expression="日本語[にほんご]", Translation="japonais")]
    monkeypatch.setattr(memory, "_known", Held({"Vocabulary": words, "Kanji": carded}))
    monkeypatch.setattr(kanji, "resolve_output_path", lambda args, prefix: tmp_path / "k.tsv")
    sent = []

    def finish(cards, fields, args, out_path, preview):
        sent.extend(cards)
        carded.extend(note(Kanji=card["Kanji"]) for card in cards)
        return len(cards), 0

    monkeypatch.setattr(kanji, "finish", finish)
    client = FakeClient([answer("語", Composition="", Words=[
        {"word": "日本語[にほんご]", "meaning": "japonais", "reading": "ゴ"}])])
    assert kanji.generate_into(client, ["語", "学"], "Japanese::Kanji", "Kanji") == {"語", "学"}
    assert [card["Kanji"] for card in sent] == ["語"]
    assert "日本語[にほんご] (japonais)" in client.prompts[0]
    assert "語[ご] (langue)" not in client.prompts[0]


def test_a_lone_kanji_whose_card_did_not_go_in_is_not_handed_back(monkeypatch, tmp_path):
    monkeypatch.setattr(memory, "_known", Held())
    monkeypatch.setattr(kanji, "resolve_output_path", lambda args, prefix: tmp_path / "k.tsv")
    monkeypatch.setattr(kanji, "finish", lambda *a, **kw: None)
    client = FakeClient([answer("語", Composition="", Words=[
        {"word": "日本語[にほんご]", "meaning": "japonais", "reading": "ゴ"}])])
    assert kanji.generate_into(client, ["語"], "Japanese::Kanji", "Kanji") == set()


# ── Identity ──────────────────────────────────────────────────────────────────

def test_a_kanji_card_is_known_by_its_kanji():
    assert identity.kind_of(kanji.FIELDS) == "kanji"
    assert identity.of("kanji", {"Kanji": "学"}) == "kanji:学"


def test_a_lost_half_does_not_take_the_other_with_it(capsys):
    """A truncated batch is replayed in two halves: when the second fails, the
    first, already paid for, still gives its card."""
    from threading import Event

    from kotogen.ai_client import AITruncatedError

    class Client:
        calls = 0

        def chat_json(self, system, user):
            Client.calls += 1
            if "日" in user and "月" in user:
                raise AITruncatedError("cut")
            if "月" in user:
                raise RuntimeError("HTTP 503")
            return [{"kanji": "日"}]

    answered = kanji._ask_batch(Client(), [Target("日"), Target("月")],
                                kanji.Vocabulary(), Event())

    assert answered == [{"kanji": "日"}]
    assert Client.calls == 3
    assert "half dropped (1 kanji)" in capsys.readouterr().err


def test_a_lost_half_is_said_by_the_loop_under_its_own_batch(monkeypatch, tmp_path, deck):
    """Said from a pool thread, the line would land under whatever batch the
    screen animates at that moment."""
    import threading

    from kotogen.ai_client import AITruncatedError

    class Client:
        def chat_json(self, system, user):
            if "日" in user and "月" in user:
                raise AITruncatedError("cut")
            if "月" in user:
                raise RuntimeError("HTTP 503")
            return [answer("日")]

    said: list[tuple[bool, str]] = []
    monkeypatch.setattr(kanji.console, "failed", lambda text: said.append(
        (threading.current_thread() is threading.main_thread(), text)))
    kanji.generate(Client(), [Target("日"), Target("月")], make_args(tmp_path, jobs=2),
                   tmp_path / "kanji.tsv", kanji.Vocabulary(), set())

    assert [(main, text.startswith("half dropped")) for main, text in said] == [(True, True)]


class _Answering:
    """Hands back the same answer to every call."""

    def __init__(self, answer):
        self.answer = answer

    def chat_json(self, system, user):
        return self.answer


def test_an_answer_of_another_shape_names_its_kind_plainly():
    """The name of the type, not "<class 'str'>"."""
    with pytest.raises(ValueError, match="^unexpected JSON structure: str$"):
        kanji._ask(_Answering("a sentence"), [Target("日")], kanji.Vocabulary())
