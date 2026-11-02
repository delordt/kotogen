"""Tests of the post-processing of the reading cards (pure logic, no AI call)."""

import argparse
from pathlib import Path

import pytest

from kotogen import i18n, known, prompts
from kotogen.generators import passages, pdf_pages, pdf_source, reading
from kotogen.generators.reading import _emit_pdf, _fetch_web_pdfs, _post_process

LINES = ["東京[とうきょう]で 雨[あめ]が 降[ふ]りました。", "みんな 傘[かさ]を 使[つか]いました。"]
TRANSLATION = ["Il a plu à Tokyo.", "Tout le monde a utilisé un parapluie."]

DECOYS = ["À Osaka", "À Kyoto", "À Hokkaido"]


def _result(cards, level="N4", translation=None):
    out = {"Level": level, "Cards": cards}
    if translation is not None:
        out["TranslationLines"] = translation
    return out


def _multiple_choice(**extra):
    """A valid multiple-choice card, as the model hands it back."""
    return {"Question": "Où a-t-il plu ?", "Answer": "À Tokyo",
            "Decoys": list(DECOYS), **extra}


def _open_question(**extra):
    return {"Question": "Qu'ont-ils utilisé ?", "Answer": "Un parapluie",
            "Decoys": [], **extra}


# ── Format of the options ─────────────────────────────────────────────────────

def test_multiple_choice_card_keeps_decoys_and_shared_text():
    """The right answer has its own field: the note keeps the 3 decoys, and the
    card puts the four options together."""
    cards = _post_process(_result([_multiple_choice()]), LINES, level_arg="auto")
    assert len(cards) == 1
    card = cards[0]
    assert card["Text"] == "\n".join(LINES)
    assert [card["Decoy1"], card["Decoy2"], card["Decoy3"]] == DECOYS
    assert card["Answer"] == "À Tokyo"
    assert card["Tags"] == "Level::N4"


def test_the_answer_handed_back_as_a_decoy_is_removed(capsys):
    """Shown twice, the right answer would give itself away."""
    cards = _post_process(
        _result([_multiple_choice(Decoys=["À Osaka", "À Tokyo", "À Kyoto"])]),
        LINES, level_arg="auto",
    )
    assert [cards[0][f"Decoy{i}"] for i in range(1, 4)] == ["À Osaka", "À Kyoto", ""]
    assert "also appears among the decoys" in capsys.readouterr().err


def test_partial_decoys_keep_a_shorter_multiple_choice(capsys):
    cards = _post_process(_result([_multiple_choice(Decoys=["Oui", "Non"])]),
                          LINES, level_arg="auto")
    assert [cards[0][f"Decoy{i}"] for i in range(1, 4)] == ["Oui", "Non", ""]
    assert "2 decoys instead of 3" in capsys.readouterr().out


def test_the_extra_decoys_are_turned_down(capsys):
    """The note only has three decoy fields: a fourth would be nowhere."""
    cards = _post_process(
        _result([_multiple_choice(Decoys=DECOYS + ["À Nagoya"])]), LINES,
        level_arg="auto")
    assert [cards[0][f"Decoy{i}"] for i in range(1, 4)] == DECOYS
    assert "4 decoys for 3 fields, the last one is dropped" in capsys.readouterr().out


def test_a_card_that_is_not_an_object_is_skipped_not_fatal(capsys):
    """A stray string among the cards must not take the text down with it."""
    cards = _post_process(_result(["Où vont-ils ?", _multiple_choice()]), LINES,
                          level_arg="auto")
    assert len(cards) == 1
    assert "card 1 skipped" in capsys.readouterr().out


def test_a_card_with_no_decoy_is_kept_but_reported(capsys):
    """A defect (the instruction asks for another question), but the card is paid
    for and whole: kept, and said, as no setting can give it options."""
    cards = _post_process(_result([_multiple_choice(Decoys=[])]), LINES,
                          level_arg="auto")
    assert [cards[0][f"Decoy{i}"] for i in range(1, 4)] == ["", "", ""]
    assert cards[0]["Answer"] == "À Tokyo"
    assert "no decoy handed back" in capsys.readouterr().out


def test_incomplete_card_is_skipped():
    cards = _post_process(_result([
        {"Question": "", "Answer": "Oui", "Decoys": []},          # no question
        {"Question": "Question ?", "Answer": "", "Decoys": []},   # no answer
        {"Question": "Question ?", "Answer": "Oui", "Decoys": []},  # valid
    ]), LINES, level_arg="auto")
    assert len(cards) == 1


# ── The rank decides nothing ──────────────────────────────────────────────────
# Every card carries its options; the template decides how many show. Fixing the
# format by rank at generation would make a change of mind cost a pass.

def test_every_card_keeps_its_decoys_whatever_its_rank():
    cards = _post_process(_result([_multiple_choice()] * 3), LINES, level_arg="auto")
    for card in cards:
        assert [card[f"Decoy{i}"] for i in range(1, 4)] == DECOYS


def test_an_open_question_does_not_go_off_as_an_incident(capsys):
    """Reported with "!" on stdout, never with "!!": the card is usable."""
    cards = _post_process(_result([_multiple_choice(), _open_question()]),
                          LINES, level_arg="auto")
    assert [cards[1][f"Decoy{i}"] for i in range(1, 4)] == ["", "", ""]
    assert capsys.readouterr().err == ""


# ── Translation and key line ──────────────────────────────────────────────────
# What the back teaches after a wrong answer, beyond the right one circled.

def test_a_lined_up_translation_is_kept():
    cards = _post_process(_result([_multiple_choice()], translation=TRANSLATION), LINES,
                          level_arg="auto")
    assert cards[0]["Translation"] == "\n".join(TRANSLATION)


def test_a_translation_out_of_line_is_turned_down_wholesale(capsys):
    """Off by one, it reads as though it were right: worse than nothing."""
    cards = _post_process(_result([_multiple_choice()], translation=TRANSLATION[:1]),
                          LINES, level_arg="auto")
    assert cards[0]["Translation"] == ""
    assert "translation not lined up" in capsys.readouterr().err


def test_a_translation_out_of_line_marks_the_cards_of_the_text():
    """The card carries the "!!": proofreading decides its fate at export."""
    from kotogen import proofreading

    cards = _post_process(_result([_multiple_choice(), _multiple_choice()],
                                  translation=TRANSLATION[:1]), LINES, level_arg="auto")
    assert all(proofreading.tags([card]) == [proofreading.TRANSLATION_TAG] for card in cards)
    assert proofreading.reasons(cards) == proofreading.UNALIGNED_TRANSLATION


def test_a_lined_up_translation_marks_nothing():
    from kotogen import proofreading

    cards = _post_process(_result([_multiple_choice()], translation=TRANSLATION), LINES,
                          level_arg="auto")
    assert proofreading.marked(cards) == []


def test_without_a_translation_the_field_stays_empty():
    cards = _post_process(_result([_multiple_choice()]), LINES, level_arg="auto")
    assert cards[0]["Translation"] == ""


def test_the_translation_is_the_same_for_every_card_of_the_text():
    cards = _post_process(_result([_multiple_choice(), _open_question()],
                                  translation=TRANSLATION), LINES, level_arg="auto")
    assert cards[0]["Translation"] == cards[1]["Translation"] == "\n".join(TRANSLATION)


def test_the_key_line_is_kept_as_text():
    cards = _post_process(_result([_multiple_choice(KeyLine=2)]), LINES,
                          level_arg="auto")
    assert cards[0]["KeyLine"] == "2"


def test_a_key_line_out_of_bounds_designates_nothing():
    """Better to highlight nothing than the wrong line."""
    for value in (0, 3, -1, None, "abc", True):
        cards = _post_process(_result([_multiple_choice(KeyLine=value)]), LINES,
                              level_arg="auto")
        assert cards[0]["KeyLine"] == "", value


def test_a_key_line_as_a_string_is_accepted():
    cards = _post_process(_result([_multiple_choice(KeyLine="2")]), LINES,
                          level_arg="auto")
    assert cards[0]["KeyLine"] == "2"


# ── Mini-book ─────────────────────────────────────────────────────────────────

def test_a_mini_book_lays_the_pages_and_leaves_the_text_empty():
    """The card shows the pages: the text beside them would give the reading
    away, and the template forbids it."""
    images = '<img src="reading_tadoku_ab12cd34_p001.jpg">'
    cards = _post_process(_result([_multiple_choice(KeyLine=1)], translation=TRANSLATION),
                          LINES, level_arg="auto", images=images)
    assert cards[0]["Images"] == images
    assert cards[0]["Text"] == ""
    # With no text shown, translation and key line have nothing to sit under
    assert cards[0]["Translation"] == ""
    assert cards[0]["KeyLine"] == ""


def test_a_mini_book_sends_the_answer_to_its_page():
    """The key line, said in pages: the transcription's map turns the model's
    line into the page the back opens at."""
    images = '<img src="a.jpg"><img src="b.jpg">'
    cards = _post_process(_result([_multiple_choice(KeyLine=2)]), LINES,
                          level_arg="auto", images=images, page_of_line=(4, 5))
    assert cards[0]["KeyPage"] == "5"
    # Still nothing to set a rule against: the card carries no line.
    assert cards[0]["KeyLine"] == ""


def test_a_mini_book_whose_pages_were_not_told_apart_names_none():
    """No page map from the transcription: the cards stay whole, only the jump
    is lost."""
    cards = _post_process(_result([_multiple_choice(KeyLine=2)]), LINES,
                          level_arg="auto", images='<img src="a.jpg">')
    assert cards[0]["KeyPage"] == ""


def test_a_key_line_out_of_the_map_designates_no_page():
    """Better the first page than a wrong one, read as the answer's."""
    for value in (0, 3, -1, None, "abc", True):
        cards = _post_process(_result([_multiple_choice(KeyLine=value)]), LINES,
                              level_arg="auto", images='<img src="a.jpg">',
                              page_of_line=(4, 5))
        assert cards[0]["KeyPage"] == "", value


def test_a_card_that_carries_its_text_names_no_page():
    """A composed document shows its transcription on the back, so it points at
    the line, as any text does; it has a single page."""
    cards = _post_process(_result([_multiple_choice(KeyLine=1)], translation=TRANSLATION),
                          LINES, level_arg="auto", images='<img src="a.jpg">',
                          text_on_back=True, page_of_line=(1, 1))
    assert (cards[0]["KeyLine"], cards[0]["KeyPage"]) == ("1", "")


def test_without_a_mini_book_the_images_field_stays_empty():
    cards = _post_process(_result([_multiple_choice()]), LINES, level_arg="auto")
    assert cards[0]["Images"] == ""
    assert cards[0]["Text"] == "\n".join(LINES)


def _book_call(monkeypatch, page_of_line, **extra):
    """Runs a mini-book through `_emit_cards` and hands back (what was asked of
    the model, the cards)."""
    asked: dict = {}

    def generate(client, title, text_lines, limit, level, *, translate=True,
                 locate=True):
        asked.update(lines=list(text_lines), translate=translate, locate=locate)
        return _result([_multiple_choice(KeyLine=2)])

    monkeypatch.setattr(reading, "_generate_for_text", generate)
    monkeypatch.setattr(reading, "append_cards", lambda *a, **k: None)
    args = argparse.Namespace(count=None, level="auto", deck="Test",
                              notetype="Reading", passages=None)
    cards: list[dict] = []
    reading._emit_cards(None, "Rain", LINES, args, None, cards,
                        images='<img src="a.jpg"><img src="b.jpg">', pages=2,
                        page_of_line=page_of_line, **extra)
    return asked, cards


def test_the_page_map_is_numbered_with_the_title(monkeypatch):
    """The title is line 1 of what goes off, and the map counts it, or every
    line would name the page before its own."""
    asked, cards = _book_call(monkeypatch, (4, 5))
    assert asked["lines"] == ["Rain"] + LINES
    # Line 2 of what went off is the first line of the text, read on page 4.
    assert cards[0]["KeyPage"] == "4"


def test_the_key_line_is_asked_for_as_soon_as_it_can_be_placed(monkeypatch):
    """A mini-book asks for no translation, but the key line is worth its
    tokens: it opens the book at the right page."""
    asked, _cards = _book_call(monkeypatch, (4, 5))
    assert (asked["translate"], asked["locate"]) == (False, True)


def test_with_no_page_map_the_key_line_is_not_asked_for(monkeypatch):
    """Nothing to turn it into: asking for it would be paid for and dropped."""
    asked, cards = _book_call(monkeypatch, ())
    assert asked["locate"] is False
    assert cards[0]["KeyPage"] == ""


# ── Composed documents (poster, table, diagram) ───────────────────────────────

def test_a_composed_document_keeps_its_text_for_the_back():
    """The front never shows `Text` when `Images` is filled, and the back needs
    it under the translation and the key line."""
    image = '<img src="reading_n4r_ab12cd34_p008.jpg">'
    cards = _post_process(_result([_multiple_choice(KeyLine=1)], translation=TRANSLATION),
                          LINES, level_arg="auto", images=image, text_on_back=True)

    assert cards[0]["Images"] == image
    assert cards[0]["Text"] == "\n".join(LINES)
    assert cards[0]["Translation"] == "\n".join(TRANSLATION)
    assert cards[0]["KeyLine"] == "1"


def test_a_mini_book_does_not_benefit_from_the_same_lifting():
    """Only a composed document keeps its text: a book's transcription would
    give the reading away."""
    image = '<img src="reading_tadoku_ab12cd34_p001.jpg">'
    cards = _post_process(_result([_multiple_choice(KeyLine=1)], translation=TRANSLATION),
                          LINES, level_arg="auto", images=image)

    assert cards[0]["Text"] == "" and cards[0]["Translation"] == ""


# ── Level ─────────────────────────────────────────────────────────────────────

def test_level_argument_overrides_detected_level():
    cards = _post_process(_result([_multiple_choice()], level="N2"), LINES,
                          level_arg="N5")
    assert cards[0]["Tags"] == "Level::N5"


def test_invalid_detected_level_falls_back_to_n5():
    cards = _post_process(_result([_multiple_choice()], level="X9"), LINES,
                          level_arg="auto")
    assert cards[0]["Tags"] == "Level::N5"


# ── Identifier of the cards ───────────────────────────────────────────────────
# The ID is the FIRST field of the note type, which Anki checks for duplicates:
# it is drawn from the matter read, as on the listening side.

def _emitted(monkeypatch, texts, *, count=False, fail=0, passages=None,
             **extra):
    """Unrolls `_emit_cards` over a list of (title, lines) and hands back the cards.

    `count` hands back the number of AI calls instead; `fail` makes the n-th
    call fail.
    """
    calls = []

    def generate(client, title, text_lines, limit, level, *, translate=True,
                 locate=True):
        calls.append(title)
        if len(calls) == fail:
            raise RuntimeError("model unavailable")
        return _result([
            _multiple_choice(),
            {"Question": "Qui avait un parapluie ?", "Answer": "Tout le monde",
             "Decoys": []},
        ])

    monkeypatch.setattr(reading, "_generate_for_text", generate)
    monkeypatch.setattr(reading, "append_cards", lambda *a, **k: None)

    args = argparse.Namespace(count=None, level="auto", deck="Test",
                              notetype="Reading", passages=passages)
    cards: list[dict] = []
    for title, lines in texts:
        reading._emit_cards(None, title, lines, args, None, cards, **extra)
    return len(calls) if count else cards


def test_the_same_text_gives_the_same_identifiers_back(monkeypatch):
    """A second pass on the same text must not reimport its cards."""
    first = _emitted(monkeypatch, [("Rain", LINES)])
    second = _emitted(monkeypatch, [("Rain", LINES)])
    assert [c["ID"] for c in first] == [c["ID"] for c in second]


def test_a_different_text_gives_other_identifiers(monkeypatch):
    """Otherwise two readings would be taken for one another."""
    rain = _emitted(monkeypatch, [("Rain", LINES)])
    snow = _emitted(monkeypatch, [("Snow", ["北海道[ほっかいどう]で 雪[ゆき]。"])])
    assert not set(c["ID"] for c in rain) & set(c["ID"] for c in snow)


def test_the_identifier_of_an_article_does_not_move_with_the_split(monkeypatch):
    """Hard-coded on purpose, for the decks already built: an article is not
    split, so its fingerprint covers the whole text.
    """
    cards = _emitted(monkeypatch, [("Rain", LINES)])
    assert [c["ID"] for c in cards] == ["RC_d5a1be77_001", "RC_d5a1be77_002"]


def test_the_identifier_names_its_source(monkeypatch):
    """In the Anki browser, the ID says where the card comes from, as a
    listening card's names its medium."""
    cards = _emitted(monkeypatch, [("Rain", LINES)], source="ginga.txt")
    assert [c["ID"] for c in cards] == ["RC_ginga_d5a1be77_001",
                                        "RC_ginga_d5a1be77_002"]


def test_an_address_is_reduced_to_what_it_names(monkeypatch):
    """The host and the last part of the path name the article; flattened
    whole, the address would spend the room on "https_www3_"."""
    article = ("https://www3.nhk.or.jp/news/easy/k10014837511000/"
               "k10014837511000.html")
    cards = _emitted(monkeypatch, [("Rain", LINES)], source=article)
    assert cards[0]["ID"].startswith("RC_nhk_or_jp_k10014837511000_")


def test_the_passages_of_one_text_carry_the_same_name(monkeypatch):
    """Named after the source; the fingerprint tells the passages apart."""
    cards = _emitted(monkeypatch, [("Chapter", LONG)], source="chapter.txt")
    assert all(c["ID"].startswith("RC_chapter_") for c in cards)
    assert len({c["ID"] for c in cards}) == len(cards)


def test_a_source_that_does_not_name_itself_leaves_the_identifier_as_it_was(monkeypatch):
    """With no name, the ID has no name part."""
    cards = _emitted(monkeypatch, [("Rain", LINES)], source="")
    assert cards[0]["ID"] == "RC_d5a1be77_001"


# ── A text too long for one card ──────────────────────────────────────────────
# A long text is split into passages, each the `Text` of its own cards.

SENTENCE = "今日[きょう]は とても いい 天気[てんき]でした。"
LONG = [f"{i}日[にち]目[め]。{SENTENCE}" for i in range(60)]  # ~900 characters


def test_a_long_text_gives_one_card_text_per_passage(monkeypatch):
    cards = _emitted(monkeypatch, [("Chapter", LONG)])
    texts = {c["Text"] for c in cards}
    assert len(texts) > 1
    assert all(t.startswith("Chapter\n") for t in texts)
    assert all(passages.weight(t.split("\n")) <= passages.MAX_SIZE for t in texts)


def test_each_passage_has_its_own_identifiers(monkeypatch):
    """Two passages of one document must not refuse each other at the import: the
    rank starts over at 1 in each, but the fingerprint differs."""
    cards = _emitted(monkeypatch, [("Chapter", LONG)])
    identifiers = [c["ID"] for c in cards]
    assert len(set(identifiers)) == len(identifiers)


def test_two_identical_passages_carry_the_same_identifier(monkeypatch):
    """On purpose: the ID is the identity of the MATTER read, so Anki refuses
    the second of two identical passages, as with two passes on one article."""
    cards = _emitted(monkeypatch, [("Litany", [SENTENCE] * 60)])
    assert len({c["ID"] for c in cards}) < len(cards)


def test_the_provenance_locates_the_passage(monkeypatch):
    """Each card names its passage, not just the chapter."""
    cards = _emitted(monkeypatch, [("Chapter", LONG)], source="chapter.txt")
    total = len({c["Text"] for c in cards})
    assert total > 1
    assert cards[0]["Source"] == f"chapter.txt (passage 1/{total})"
    assert cards[-1]["Source"] == f"chapter.txt (passage {total}/{total})"


@pytest.mark.parametrize("screen", i18n.available())
@pytest.mark.parametrize("lang", prompts.languages())
def test_the_identifiers_of_a_passage_move_with_no_language(monkeypatch, screen, lang):
    """The name part of the ID is drawn from `Source`, which carries the passage:
    an ID that changed with a setting would no longer deduplicate."""
    prompts.use("en")
    english = _emitted(monkeypatch, [("Chapter", LONG)], source="chapter.txt")
    i18n.use(screen)
    prompts.use(lang)
    cards = _emitted(monkeypatch, [("Chapter", LONG)], source="chapter.txt")
    assert [c["ID"] for c in cards] == [c["ID"] for c in english]
    assert all(known.carries(c["Source"], "chapter.txt") for c in cards)


def test_the_passage_is_said_in_the_language_of_the_cards(monkeypatch):
    """`Source` is card content: it follows the deck, not the screen."""
    i18n.use("ja")
    prompts.use("en")
    english = _emitted(monkeypatch, [("Chapter", LONG)], source="chapter.txt")
    i18n.use("en")
    prompts.use("ja")
    japanese = _emitted(monkeypatch, [("Chapter", LONG)], source="chapter.txt")
    assert english[0]["Source"].startswith("chapter.txt (passage 1/")
    assert japanese[0]["Source"].startswith("chapter.txt (部分 1/")


def test_a_text_in_one_piece_keeps_its_provenance_as_it_is(monkeypatch):
    cards = _emitted(monkeypatch, [("Rain", LINES)], source="article.html")
    assert cards[0]["Source"] == "article.html"


def test_the_passage_ceiling_bounds_the_spending(monkeypatch, capsys):
    """What is bounded is the CALLS: the split is free, and goes to the end of
    the text."""
    calls = _emitted(monkeypatch, [("Book", LONG * 10)], count=True)
    assert calls == reading.PASSAGES_MAX
    assert "--passages" in capsys.readouterr().out


def test_the_passage_ceiling_can_be_set(monkeypatch):
    assert _emitted(monkeypatch, [("Book", LONG * 10)], count=True, passages=2) == 2


def test_a_long_text_with_no_history_says_how_to_reach_the_next_batch(
        monkeypatch, capsys):
    """A text with no tracking key (a PDF's) starts again at its first passage
    when run again: only `--from-passage` moves on."""
    _emitted(monkeypatch, [("Book", LONG * 10)])
    out = capsys.readouterr().out
    assert f"--from-passage {reading.PASSAGES_MAX + 1} for the next batch" in out
    assert "replay" not in out


def test_a_long_text_with_a_history_moves_on_when_run_again(monkeypatch, capsys):
    _emitted(monkeypatch, [("Book", LONG * 10)], key="book")
    assert "replay for the next batch" in capsys.readouterr().out


def test_a_passage_that_fails_does_not_take_the_next_ones(monkeypatch, capsys):
    cards = _emitted(monkeypatch, [("Chapter", LONG)], fail=2)
    assert len({c["Text"] for c in cards}) == len(passages.split(LONG)) - 1
    assert "model unavailable" in capsys.readouterr().err


def test_the_rank_is_counted_within_the_text_and_not_over_the_pass(monkeypatch):
    """Numbered across the pass, a text's IDs would depend on what came before."""
    alone = _emitted(monkeypatch, [("Snow", ["北海道[ほっかいどう]で 雪[ゆき]。"])])
    after = _emitted(monkeypatch, [("Rain", LINES),
                                   ("Snow", ["北海道[ほっかいどう]で 雪[ゆき]。"])])
    assert [c["ID"] for c in alone] == [c["ID"] for c in after[2:]]
    assert alone[0]["ID"].endswith("_001") and alone[1]["ID"].endswith("_002")


def test_a_mini_book_identifies_itself_by_its_pages(monkeypatch):
    """Its `Text` stays empty: the page file names carry the document's
    fingerprint."""
    pages = '<img src="reading_kobutori_ab12cd34_p001.jpg">'
    cards = _emitted(monkeypatch, [("Book", ["a line read by the model"])],
                     images=pages)
    others = _emitted(monkeypatch, [("Book", ["the model transcribed otherwise"])],
                      images=pages)
    assert cards[0]["Text"] == ""
    # Same pages, same card: what the model read does not enter the note.
    assert [c["ID"] for c in cards] == [c["ID"] for c in others]


def test_a_composed_document_identifies_itself_by_its_image(monkeypatch):
    """It carries both fields, and the IMAGE identifies it: the model's
    transcription can vary between passes, the cut-out file name cannot."""
    image = '<img src="reading_n4r_ab12cd34_p008.jpg">'
    cards = _emitted(monkeypatch, [("Poster", ["青葉町[あおばちょう]の お知[し]らせ。"])],
                     images=image, text_on_back=True)
    others = _emitted(monkeypatch, [("Poster", ["青葉町[あおばちょう]のおしらせ。"])],
                      images=image, text_on_back=True)

    assert cards[0]["Text"] and cards[0]["Images"] == image
    assert [c["ID"] for c in cards] == [c["ID"] for c in others]


# ── Sources fetched from the web ──────────────────────────────────────────────

BOOK_URL = "https://tadoku.org/japanese/book/6346/"


def test_only_the_tadoku_entry_imposes_the_mini_book(monkeypatch):
    """A Tadoku entry is a picture book; any other PDF URL follows --read-as like
    a file on disk."""
    from kotogen.generators import pdf_web

    monkeypatch.setattr(
        pdf_web, "fetch",
        lambda source: (Path(source.rstrip("/").rsplit("/", 1)[-1] + ".pdf"), ""))
    inputs, books, origins, _titles, _aliases = _fetch_web_pdfs(
        ["nhk", BOOK_URL, "https://example.jp/papers.pdf", "course.pdf"])
    assert inputs == ["nhk", "6346.pdf", "papers.pdf.pdf", "course.pdf"]
    assert books == {"6346.pdf"}
    # The fetched file has a download name: the cards keep its address.
    assert origins == {"6346.pdf": BOOK_URL,
                       "papers.pdf.pdf": "https://example.jp/papers.pdf"}


def test_a_failed_download_does_not_take_the_other_sources(monkeypatch, capsys):
    from kotogen.generators import pdf_web

    def fetch(source):
        raise RuntimeError("this book is not free")

    monkeypatch.setattr(pdf_web, "fetch", fetch)
    inputs, books, origins, _titles, _aliases = _fetch_web_pdfs([BOOK_URL, "nhk"])
    assert inputs == ["nhk"] and not books and not origins
    assert "not free" in capsys.readouterr().err

# ── History of the free books ─────────────────────────────────────────────────
# The menu reports the books handled (test_menu_reading.py) and the storage is
# tested in test_seen.py: here, only the condition, cards actually obtained.

def _run_reading_on_a_book(monkeypatch, tmp_path, cards):
    """Plays `kotogen reading <Tadoku entry>` without network, AI or TSV.

    `cards` is what the mini-book hands back; empty, the book was missed.
    """
    from kotogen.generators import pdf_web

    monkeypatch.setattr(
        reading, "_fetch_web_pdfs",
        lambda inputs: (["6346.pdf"], {"6346.pdf"}, {"6346.pdf": BOOK_URL},
                        {"6346.pdf": "くるみもち"}, {"6346.pdf": BOOK_URL}))
    monkeypatch.setattr(reading, "AIClient", lambda **kwargs: object())
    monkeypatch.setattr(reading, "resolve_output_path",
                        lambda *a, **k: tmp_path / "reading.tsv")
    monkeypatch.setattr(reading, "finish", lambda *a, **k: None)

    def emit(client, source, args, out_path, all_cards, media, **kwargs):
        all_cards.extend(cards)

    monkeypatch.setattr(reading, "_emit_book", emit)
    args = _args(inputs=[BOOK_URL], provider=None, model=None, output=None,
                 send=False, latest=None)
    reading.run_reading(args)
    return pdf_web


def test_a_book_that_gave_cards_enters_the_history(monkeypatch, tmp_path):
    """Under its title, which the menu shows, not the download name."""
    pdf_web = _run_reading_on_a_book(monkeypatch, tmp_path,
                                     [{"ID": "1", "Question": "Où ?"}])
    assert pdf_web.load_seen() == {"6346": "くるみもち"}


def test_a_missed_book_stays_to_be_done(monkeypatch, tmp_path):
    """Nothing is kept without a card, so a failed book can be taken up again."""
    with pytest.raises(SystemExit):  # "No card generated."
        _run_reading_on_a_book(monkeypatch, tmp_path, [])
    from kotogen.generators import pdf_web

    assert pdf_web.load_seen() == {}


# ── Routing of a PDF document ─────────────────────────────────────────────────
# "Text or mini-book" is decided once: checked, the route taken AND the calls
# paid, as the arbitration must add none.

def test_no_source_names_the_keywords_in_the_quotes_of_the_screen(monkeypatch):
    """`nhk` and `deck` are values inside the sentence, quoted by the language."""
    monkeypatch.setattr(reading, "quoted", lambda name: f"<{name}>")
    args = _args(inputs=["涼しい"], provider=None, model=None, output=None,
                 send=False, latest=None)
    with pytest.raises(SystemExit) as raised:
        reading.run_reading(args)
    assert "<nhk>" in str(raised.value) and "<deck>" in str(raised.value)


def _args(**extra):
    defaults = dict(read_as="auto", pages=None, texts=None, count=None,
                    level="auto", passages=None)
    return argparse.Namespace(**{**defaults, **extra})


class _Trace:
    """Replaces everything _emit_pdf calls, and notes what was used."""

    def __init__(self, monkeypatch, tmp_path, mode, arbitration=None):
        self.calls: list[str] = []
        self.reading = None
        doc = tmp_path / "document.pdf"
        doc.write_bytes(b"%PDF-1.7")
        self.path = doc

        monkeypatch.setattr(pdf_source, "load_pdf", lambda path: b"%PDF-1.7")
        monkeypatch.setattr(pdf_pages, "page_count", lambda data: 3)
        monkeypatch.setattr(pdf_pages, "read_mode",
                            lambda data, spec=None: (self._note("measure") or mode, "reason"))
        monkeypatch.setattr(pdf_source, "extract_texts",
                            lambda *a, **k: (self._note("extract_texts")
                                             or [pdf_source.Text("title", ["一行目。"])]))
        monkeypatch.setattr(pdf_source, "extract_mode_and_texts",
                            lambda *a, **k: self._note("arbitration") or arbitration)
        monkeypatch.setattr(reading, "_emit_texts",
                            lambda *a, **k: self._note("text cards"))
        monkeypatch.setattr(reading, "_emit_book", self._book)

    def _note(self, what):
        self.calls.append(what)
        return None

    def _book(self, client, source, args, out_path, all_cards, media,
              reading=None, origin=""):
        self._note("book cards")
        self.reading = reading

    def run(self, args):
        _emit_pdf(None, self.path, args, None, [], [])
        return self.calls


def test_a_text_document_goes_off_as_texts(monkeypatch, tmp_path):
    trace = _Trace(monkeypatch, tmp_path, "text")
    assert trace.run(_args()) == ["measure", "extract_texts", "text cards"]


def test_the_measurement_is_said_as_an_action_and_not_as_an_element(
        monkeypatch, tmp_path, capsys):
    """An action: its label opens the line, its conclusion ends the SAME line."""
    trace = _Trace(monkeypatch, tmp_path, "text")
    trace.run(_args())
    line = next(l for l in capsys.readouterr().out.splitlines() if "Measuring" in l)
    assert line == "   Measuring the pages… (reason)"


def test_a_document_recognised_as_a_book_skips_the_text_extraction(
        monkeypatch, tmp_path):
    trace = _Trace(monkeypatch, tmp_path, "book")
    assert trace.run(_args()) == ["measure", "book cards"]
    # Nothing read yet: _emit_book has the pages read.
    assert trace.reading is None


def test_the_arbitration_hands_back_the_reading_with_its_decision(monkeypatch, tmp_path):
    """One call says "book" AND transcribes the pages: reading them again would
    pay twice."""
    trace = _Trace(monkeypatch, tmp_path, None,
                   arbitration=("book", [pdf_source.Text("かえるの 話[はなし]",
                                                         ["一行目。"], False, (1,))]))
    assert trace.run(_args()) == ["measure", "arbitration", "book cards"]
    # Handed on whole, page map included: it says where the back opens the book.
    assert trace.reading == pdf_source.Text("かえるの 話[はなし]", ["一行目。"], False, (1,))


def test_the_arbitration_can_conclude_on_text(monkeypatch, tmp_path):
    trace = _Trace(monkeypatch, tmp_path, None,
                   arbitration=("text", [pdf_source.Text("手紙[てがみ]", ["一行目。"])]))
    assert trace.run(_args()) == ["measure", "arbitration", "text cards"]


def test_a_composed_document_is_cut_out_before_the_cards(monkeypatch, tmp_path):
    """The model says a 情報検索 page is a document, it is cut out locally, and
    the card gets the image. The cut works on the SUBDOCUMENT sent to the model:
    on the whole PDF, a `--pages` range would shift every page."""
    from kotogen.generators import pdf_documents

    document = tmp_path / "N4R.pdf"
    document.write_bytes(b"%PDF-1.7")
    got = {}

    monkeypatch.setattr(pdf_source, "load_pdf", lambda path: b"%PDF-whole")
    monkeypatch.setattr(pdf_pages, "read_mode", lambda data, spec=None: ("text", "reason"))
    monkeypatch.setattr(pdf_pages, "page_count", lambda data: 8)
    monkeypatch.setattr(pdf_pages, "subset", lambda data, indices: b"%PDF-excerpt")
    monkeypatch.setattr(pdf_pages, "parse_pages", lambda spec, total: [7])
    monkeypatch.setattr(pdf_source, "extract_texts", lambda *a, **k: [
        pdf_source.Text("Article", ["一行目。"]),
        pdf_source.Text("Poster", ["青葉町[あおばちょう]の お知[し]らせ。"], document=True),
    ])
    def cut_out(source, lines):
        got["source"] = source
        return 8, b"PNG"

    monkeypatch.setattr(pdf_documents, "cut_out", cut_out)
    monkeypatch.setattr(pdf_pages, "save_image",
                        lambda data, out, stem, number: Path(f"{stem}_p{number:03}.jpg"))
    monkeypatch.setattr(reading, "_emit_cards",
                        lambda *a, **k: got.setdefault("images", []).append(k.get("images")))

    reading._emit_pdf(None, document, _args(pages="8"), None, [], [])

    # Only the second text is a document, and only it gets an image.
    assert got["images"] == ["", '<img src="N4R_p008.jpg">']
    assert got["source"] == b"%PDF-excerpt"


def test_a_document_that_cannot_be_found_is_made_as_text(monkeypatch, tmp_path):
    """A handwritten memo has no text layer to find it by: made as text, and
    said."""
    from kotogen.generators import pdf_documents

    document = tmp_path / "N4R.pdf"
    document.write_bytes(b"%PDF-1.7")
    seen = []

    monkeypatch.setattr(pdf_source, "load_pdf", lambda path: b"%PDF")
    monkeypatch.setattr(pdf_pages, "read_mode", lambda data, spec=None: ("text", "reason"))
    monkeypatch.setattr(pdf_pages, "page_count", lambda data: 8)
    monkeypatch.setattr(pdf_source, "extract_texts", lambda *a, **k: [
        pdf_source.Text("Memo", ["田村[たむら]さんへ。"], document=True)])
    monkeypatch.setattr(pdf_documents, "cut_out", lambda source, lines: None)
    monkeypatch.setattr(reading, "_emit_cards",
                        lambda *a, **k: seen.append(k.get("images")))

    reading._emit_pdf(None, document, _args(), None, [], [])

    assert seen == [""]


def test_read_as_forces_the_issue_without_measuring(monkeypatch, tmp_path):
    """--read-as stays the last word: the document is not even measured."""
    trace = _Trace(monkeypatch, tmp_path, "text")
    assert trace.run(_args(read_as="book")) == ["book cards"]
