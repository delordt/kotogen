"""The screens that choose what to work on, and the vocabulary and grammar
questions that follow them."""

import re

import pytest

from kotogen import console, i18n, interactive, keyboard
from kotogen.anki.connect import AnkiStatus
from kotogen.generators import grammar
from kotogen.interactive import interactive_argv
from menus import *  # the fixtures every menu test starts from, and its helpers

# ── The source menus hold their matters ───────────────────────────────────────
# The first screen lists matters, not sources: a new catalogue goes into one of
# their submenus. Reading has one more, the text written on the deck.

def _screen(monkeypatch, capsys, function, pressed=("b",)) -> list[str]:
    """The lines of a source menu, left by the run of keys given."""
    feed(monkeypatch, list(pressed))
    with pytest.raises(interactive.screen._Back):
        function()
    return [line.rstrip() for line in capsys.readouterr().out.splitlines()]


def _numbered(lines: list[str]) -> list[str]:
    return [line.strip() for line in lines if re.match(r"\s+\d+\.", line)]


@pytest.mark.parametrize("function, expected", [
    (interactive.audio._audio_source, ["NHK Easy articles", "A programme", "A book",
                                 "Official JLPT past papers", "A local file"]),
    (interactive.reading._reading_source, ["An article", "A book",
                                   "Official JLPT past papers", "A URL",
                                   "A local file", "A tailored text"]),
])
def test_the_first_screen_carries_nothing_but_the_matters(monkeypatch, capsys,
                                                          function, expected):
    lines = _numbered(_screen(monkeypatch, capsys, function))
    assert len(lines) == len(expected)
    for line, label in zip(lines, expected):
        assert line.split(".", 1)[1].strip().startswith(label)


@pytest.mark.parametrize("function", [interactive.audio._audio_source,
                                      interactive.reading._reading_source])
def test_the_first_screen_has_no_subheading(monkeypatch, capsys, function):
    """Five matters need no subheadings, two lines of screen that file nothing."""
    lines = _screen(monkeypatch, capsys, function)
    numbered = [i for i, line in enumerate(lines) if re.match(r"\s+\d+\.", line)]
    # The numbered lines follow each other with nothing in between.
    assert numbered == list(range(min(numbered), max(numbered) + 1))


@pytest.mark.parametrize("function, path, expected", [
    (interactive.audio._audio_source, ["2", "1"], "podcast"),
    (interactive.audio._audio_source, ["2", "2"], "youtube"),
    (interactive.audio._audio_source, ["3", "1"], "irodori"),
    (interactive.audio._audio_source, ["3", "2"], "roudoku"),
    (interactive.audio._audio_source, ["1"], "nhk"),
    (interactive.audio._audio_source, ["4"], "jlpt"),
    (interactive.audio._audio_source, ["5"], "local"),
    (interactive.reading._reading_source, ["2", "1"], "tadoku"),
    (interactive.reading._reading_source, ["2", "2"], "aozora"),
    (interactive.reading._reading_source, ["2", "3"], "irodori"),
    (interactive.reading._reading_source, ["3"], "jlpt"),
    (interactive.reading._reading_source, ["4"], "url"),
    (interactive.reading._reading_source, ["5"], "file"),
])
def test_a_submenu_hands_back_the_key_of_the_source(monkeypatch, function, path,
                                                    expected):
    """The grouping is the screen's business: the rest of the dialogue gets the
    source's key, whatever path led to it."""
    feed(monkeypatch, path)
    assert function() == expected


@pytest.mark.parametrize("function, path", [
    (interactive.audio._audio_source, ["2", "b", "1"]),
    (interactive.audio._audio_source, ["3", "b", "1"]),
    (interactive.reading._reading_source, ["2", "b", "3"]),
])
def test_a_way_back_from_a_submenu_returns_to_the_first_screen(monkeypatch,
                                                               function, path):
    """It has undone only one choice out of two: going up to the main menu would
    lose the first."""
    feed(monkeypatch, path)
    assert function()  # a key, and not a _Back that would go up to the command


def test_the_article_brings_nhk_easy_and_the_press_together(monkeypatch, capsys,
                                                            press_catalogue):
    """One screen, with no "NHK Easy or the press?" step before the catalogue:
    together they form a scale."""
    lines = _numbered(_screen(monkeypatch, capsys, interactive.reading._reading_source,
                              ["1", "b", "b"]))
    assert "1. N5-N4  News      NHK News Web Easy" in lines
    assert any("時事通信" in line for line in lines)


@pytest.mark.parametrize("path, expected", [
    (["1", "1"], "nhk"),
    (["1", "2"], "press:jiji"),
    (["1", "4"], "press:"),
])
def test_the_articles_screen_hands_back_the_site_chosen(monkeypatch, press_catalogue,
                                                        path, expected):
    """"press:<alias>" rather than a URL: `press.catalogue()` alone knows the
    feed's address. A bare "press:" is a site not found there."""
    feed(monkeypatch, path)
    assert interactive.reading._reading_source() == expected


@pytest.mark.parametrize("function, path", [
    (interactive.audio._audio_source, ["2", "b", "b"]),
    (interactive.reading._reading_source, ["2", "b", "b"]),
])
def test_the_right_hand_column_lines_up_despite_the_japanese_labels(
        monkeypatch, capsys, function, path):
    """"青空朗読" takes eight columns for four characters: padded by `len`, it
    would shift its description by four."""
    lines = _numbered(_screen(monkeypatch, capsys, function, path))
    starts = set()
    for line in lines:
        label = line.split(".", 1)[1]
        before, _sep, description = label.rpartition("  ")
        assert description, line
        starts.add(console.width(before))
    # Each screen crossed has its own column: one per screen, not one per line.
    assert len(starts) <= 2
# ── vocab ─────────────────────────────────────────────────────────────────────

def test_vocab_single_word(monkeypatch):
    # menu -> 2 (vocab); source "a word"; word; Anki send -> no (default)
    feed(monkeypatch, ["2", "1", "食べる", ""])
    assert interactive_argv() == ["vocab", "食べる"]


def test_vocab_existing_file_becomes_file_option(monkeypatch, tmp_path):
    words = tmp_path / "words.md"
    words.write_text("たべる\n", encoding="utf-8")
    # source "a file"; path; "list of words" (default); batch; Anki send
    feed(monkeypatch, ["2", "5", str(words), "1", "", "y"])
    assert interactive_argv() == ["vocab", "--file", str(words), "--send"]


def test_vocab_text_file_can_be_mined_instead(monkeypatch, tmp_path):
    """A text file is ambiguous: a list of words, or a text to go through."""
    doc = tmp_path / "chapter.txt"
    doc.write_text("私は毎日日本語を勉強しています。\n", encoding="utf-8")
    # path; "running text"; 10 words (default); batch by default; no send
    feed(monkeypatch, ["2", "5", str(doc), "2", "", "", ""])
    assert interactive_argv() == ["vocab", str(doc)]


def test_vocab_missing_file_is_asked_again(monkeypatch, tmp_path):
    """The path is asked for again instead of being taken for a word to translate."""
    doc = tmp_path / "chapter.txt"
    doc.write_text("私は学生です。\n", encoding="utf-8")
    feed(monkeypatch, ["2", "5", str(tmp_path / "absent.txt"), str(doc),
                       "1", "", ""])
    assert interactive_argv() == ["vocab", "--file", str(doc)]


def test_vocab_nhk_article_is_just_a_pasted_url(monkeypatch):
    """No NHK Easy entry in the menu: the pasted URL is enough."""
    url = "https://www3.nhk.or.jp/news/easy/k10014/k10014.html"
    feed(monkeypatch, ["2", "4", url, "8", ""])
    assert interactive_argv() == ["vocab", url, "--count", "8"]


def test_vocab_jlpt_level(monkeypatch):
    # source "JLPT level"; N4; number of words (default); no send
    feed(monkeypatch, ["2", "2", "2", "", ""])
    assert interactive_argv() == ["vocab", "jlpt", "--level", "N4"]


def test_vocab_theme_offered(monkeypatch):
    # source "a theme"; the first one offered; all levels (default); 20 words; no send
    feed(monkeypatch, ["2", "3", "1", "", "", ""])
    assert interactive_argv() == ["vocab", "--theme", "Food and drink"]


def test_vocab_theme_typed(monkeypatch):
    # source "a theme"; another one, typed; N3; 10 words; no send
    feed(monkeypatch, ["2", "3", "9", "job interview", "3", "10", ""])
    assert interactive_argv() == [
        "vocab", "--theme", "job interview", "--level", "N3", "--count", "10",
    ]


def test_vocab_accepts_any_page(monkeypatch):
    feed(monkeypatch, ["2", "4", "https://ja.wikipedia.org/wiki/寿司", "15", ""])
    assert interactive_argv() == [
        "vocab", "https://ja.wikipedia.org/wiki/寿司", "--count", "15",
    ]


def test_vocab_pdf_default_is_all_words(monkeypatch, tmp_path):
    # a PDF leaves as a positional (not --file); Enter = no word limit
    doc = tmp_path / "papers.pdf"
    doc.write_bytes(b"%PDF-1.7")
    # source "a file"; path; nb of words (Enter = all); batch; send (nothing)
    feed(monkeypatch, ["2", "5", str(doc), "", "", ""])
    assert interactive_argv() == ["vocab", str(doc)]


def test_vocab_pdf_with_word_limit(monkeypatch, tmp_path):
    doc = tmp_path / "papers.pdf"
    doc.write_bytes(b"%PDF-1.7")
    # path; nb of words 50; batch (Enter); Anki send
    feed(monkeypatch, ["2", "5", str(doc), "50", "", "y"])
    assert interactive_argv() == ["vocab", str(doc), "--count", "50", "--send"]


# ── grammar ───────────────────────────────────────────────────────────────────

def test_grammar_all_defaults(monkeypatch):
    # source "one rule"; rule; 5 cards (default); no send
    # (the JLPT level is always detected)
    feed(monkeypatch, ["3", "1", "のに", "", ""])
    assert interactive_argv() == ["grammar", "のに"]


def test_grammar_custom_count(monkeypatch):
    feed(monkeypatch, ["3", "1", "〜たら", "3", "y"])
    assert interactive_argv() == ["grammar", "〜たら", "--count", "3", "--send"]


def _rules(*done: bool):
    """Three N4 rules, `done` saying which are already worked on. The gloss is the
    table's English column, the one an English screen shows."""
    points = [
        {"title": "でも", "level": "N4", "meaning_en": "Or something"},
        {"title": "やすい", "level": "N4", "meaning_en": "Easy to"},
        {"title": "にくい", "level": "N4", "meaning_en": "Difficult to"},
    ]
    return [grammar.Rule(point, is_done)
            for point, is_done in zip(points, done or (False, False, False))]


def test_grammar_jlpt_tickable_list(monkeypatch):
    """The rules ticked leave by name: each is found again in the table at
    generation time, with no extra call, so the "jlpt" keyword is not needed."""
    monkeypatch.setattr(interactive.status, "anki_status",
                        lambda **kw: AnkiStatus(connected=True))
    monkeypatch.setattr(grammar, "rules_of_level",
                        lambda level, notetype, known: _rules())
    # grammar; JLPT level; N4; we tick the 1st and the 3rd; cards; no send
    feed(monkeypatch, ["3", "2", "2", "1 3", "", ""])
    assert interactive_argv() == ["grammar", "でも", "にくい"]


def test_grammar_jlpt_shows_what_is_already_done(monkeypatch, capsys):
    """A rule done is marked, not removed: the list says where one stands, and the
    rule can be taken up again."""
    monkeypatch.setattr(interactive.status, "anki_status",
                        lambda **kw: AnkiStatus(connected=True))
    monkeypatch.setattr(grammar, "rules_of_level",
                        lambda level, notetype, known: _rules(False, True, False))
    feed(monkeypatch, ["3", "2", "2", "2", "", ""])
    # The rule already done stays choosable: it is the one being taken up again.
    assert interactive_argv() == ["grammar", "やすい"]
    screen = capsys.readouterr().out
    assert "1/3 done" in screen
    # The mark has its column before the level: at the end of the line it would
    # read as part of the meaning.
    assert "✓ N4  やすい" in screen
    assert "  N4  でも" in screen


def test_grammar_jlpt_without_anki_leans_on_the_history(monkeypatch, capsys):
    """Anki closed, the screen works all the same: the local history knows."""
    monkeypatch.setattr(interactive.status, "anki_status",
                        lambda **kw: AnkiStatus(connected=False))
    monkeypatch.setattr(grammar, "rules_of_level",
                        lambda level, notetype, known: _rules(True, False, False))
    feed(monkeypatch, ["3", "2", "2", "3", "", ""])
    assert interactive_argv() == ["grammar", "にくい"]
    assert "✓ N4  でも" in capsys.readouterr().out


def _rule(title, level, meaning, done=False, french=""):
    """A point of the table: `meaning` is its English gloss, the one the screen
    shows, and `french` the column beside it, for the tests about the language."""
    return grammar.Rule({"title": title, "level": level,
                         "meaning_en": meaning, "meaning_fr": french}, done)


def test_grammar_jlpt_the_search_reaches_the_other_levels(keys, monkeypatch,
                                                          capsys):
    """A rule searched from the N4 screen may be an N3: the table has its page, so
    it is not reported missing."""
    monkeypatch.setattr(interactive.status, "anki_status",
                        lambda **kw: AnkiStatus(connected=True))
    monkeypatch.setattr(grammar, "rules_of_level", lambda level, notetype, known: [
        _rule("やすい", "N4", "Easy to"),
        _rule("ものの", "N3", "Although, even though"),
    ])
    keys(["3", keyboard.ENTER, "2", keyboard.ENTER, "2", keyboard.ENTER]
         + list("alth") + [keyboard.ENTER])
    feed(monkeypatch, ["", ""])
    assert interactive_argv() == ["grammar", "ものの"]
    screen = _plain(capsys.readouterr().out)
    assert "outside this list" in screen
    # Its real level shows, and it is what tells it from the list.
    assert "N3  ものの" in screen


def test_grammar_jlpt_the_gloss_follows_the_language_of_the_screen(keys,
                                                                  monkeypatch,
                                                                  capsys):
    """The list glosses in the language of the screen, not that of the cards."""
    monkeypatch.setattr(interactive.status, "anki_status",
                        lambda **kw: AnkiStatus(connected=True))
    monkeypatch.setattr(grammar, "rules_of_level", lambda level, notetype, known: [
        _rule("ものの", "N4", "Although, even though",
              french="Bien que, quoique"),
    ])
    i18n.use("fr")
    keys(["3", keyboard.ENTER, "2", keyboard.ENTER, "2", keyboard.ENTER,
          keyboard.ENTER])
    feed(monkeypatch, ["", ""])
    interactive_argv()
    assert "Bien que, quoique" in _plain(capsys.readouterr().out)


def test_grammar_jlpt_two_rules_of_the_same_name_leave_apart(keys, monkeypatch):
    """のに is "despite" in N4 and "in order to" in N3: the table names them
    apart, and it is that name that leaves."""
    monkeypatch.setattr(interactive.status, "anki_status",
                        lambda **kw: AnkiStatus(connected=True))
    monkeypatch.setattr(grammar, "rules_of_level", lambda level, notetype, known: [
        _rule("のに（逆接）", "N4", "Although"),
        _rule("のに（目的）", "N3", "In order to"),
    ])
    keys(["3", keyboard.ENTER, "2", keyboard.ENTER, "2", keyboard.ENTER,
          keyboard.ENTER])
    feed(monkeypatch, ["", ""])
    assert interactive_argv() == ["grammar", "のに（逆接）"]


def test_grammar_jlpt_a_rule_absent_from_the_list_leaves_all_the_same(keys, monkeypatch):
    """A rule missing from the syllabus stays workable: typed text the list does
    not know is offered as it stands, and the analysis names it."""
    monkeypatch.setattr(interactive.status, "anki_status",
                        lambda **kw: AnkiStatus(connected=True))
    monkeypatch.setattr(grammar, "rules_of_level",
                        lambda level, notetype, known: _rules())
    # Everything goes through keys, the way the rules screen is driven.
    keys(["3", keyboard.ENTER,          # command: grammar
          "2", keyboard.ENTER,          # source: a JLPT level
          "2", keyboard.ENTER]          # level: N4
         + list("zutonaru") + [keyboard.ENTER])
    feed(monkeypatch, ["", ""])          # cards per rule, then no send
    assert interactive_argv() == ["grammar", "zutonaru"]


def test_grammar_sheet_asks_for_the_address_only(monkeypatch):
    """It is the page that says the rule: nothing else to enter."""
    # grammar; a page; URL; cards; no send
    feed(monkeypatch, ["3", "3", "https://www.tofugu.com/japanese-grammar/noni/", "", ""])
    assert interactive_argv() == [
        "grammar", "--url", "https://www.tofugu.com/japanese-grammar/noni/"]


def test_grammar_file_of_rules(monkeypatch, tmp_path):
    """A file of rules is read like a list of words, not like a text."""
    listing = tmp_path / "rules.md"
    listing.write_text("のに\n〜たら\n", encoding="utf-8")
    feed(monkeypatch, ["3", "4", str(listing), "", ""])
    assert interactive_argv() == ["grammar", "--file", str(listing)]


def test_the_durations_of_the_readings_hold_one_column(monkeypatch):
    """The library runs from forty seconds to two and a half hours: the column is
    as wide as the longest duration, or the titles after it zigzag."""
    from kotogen.generators.aozora_roudoku import Reading
    from kotogen.interactive import catalogues

    readings = [Reading(f"rd{n:03d}", f"作品{n}", "", "", seconds)
                for n, seconds in enumerate((45, 212, 1200, 9000))]
    shown = []
    monkeypatch.setattr(catalogues, "_menu", lambda *a, **k: "list")
    monkeypatch.setattr(catalogues, "_roudoku_library", lambda: readings)
    monkeypatch.setattr(catalogues, "_tickable_pages",
                        lambda title, entries, count: shown.extend(entries) or [])
    catalogues._chosen_roudoku()
    starts = {console.width(label.split("作品")[0]) for _page, label in shown}
    assert len(shown) == 4 and len(starts) == 1
