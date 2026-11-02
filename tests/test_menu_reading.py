"""The reading questions: NHK, pages and files, the press catalogue and the free
books."""

import pytest

from kotogen import seen
from kotogen.interactive import interactive_argv
from menus import *  # the fixtures every menu test starts from, and its helpers

# ── reading ───────────────────────────────────────────────────────────────────

def test_reading_nhk_defaults(monkeypatch):
    # an article (default); NHK Easy (default); the latest; 4 articles;
    # questions on the content
    feed(monkeypatch, ["5", "", "", "", "", "", ""])
    assert interactive_argv() == ["reading", "nhk"]


def test_reading_a_precise_nhk_article_is_in_the_nhk_entry(monkeypatch):
    """"The latest" and "this one" aim at the same feed: a question, not a second
    menu entry."""
    url = "https://news.web.nhk/news/easy/ne1/ne1.html"
    # an article; NHK Easy; the article; questions on the content; no send
    feed(monkeypatch, ["5", "", "", url, "", ""])
    assert interactive_argv() == ["reading", url]


def test_reading_the_nhk_article_asks_for_a_url_or_the_feed(monkeypatch):
    feed(monkeypatch, ["5", "", "", "the last one on Tuesday",
                       "https://news.web.nhk/news/easy/ne1/ne1.html", "", ""])
    assert interactive_argv() == [
        "reading", "https://news.web.nhk/news/easy/ne1/ne1.html",
    ]


def test_reading_url_with_count(monkeypatch):
    feed(monkeypatch, ["5", "4", "https://news.web.nhk/news/easy/ne1/ne1.html", "5", "y"])
    assert interactive_argv() == [
        "reading", "https://news.web.nhk/news/easy/ne1/ne1.html",
        "--count", "5", "--send",
    ]


def test_reading_accepts_any_page(monkeypatch):
    """Any URL at all, not only an NHK Easy article."""
    feed(monkeypatch, ["5", "4", "https://ja.wikipedia.org/wiki/寿司", "4", ""])
    assert interactive_argv() == [
        "reading", "https://ja.wikipedia.org/wiki/寿司", "--count", "4",
    ]


def test_reading_accepts_a_local_text_file(monkeypatch, tmp_path):
    """A text file has no pages: the question is not asked."""
    doc = tmp_path / "chapter.txt"
    doc.write_text("私は学生です。\n", encoding="utf-8")
    feed(monkeypatch, ["5", "5", str(doc), "", ""])
    assert interactive_argv() == ["reading", str(doc)]


def test_reading_file_must_exist(monkeypatch, tmp_path):
    # invalid path asked for again; pages (Enter = all); questions on the content
    doc = tmp_path / "textbook.pdf"
    doc.write_bytes(b"%PDF-1.7")
    feed(monkeypatch, ["5", "5", str(tmp_path / "absent.pdf"), str(doc), "", "", ""])
    assert interactive_argv() == ["reading", str(doc)]


def test_reading_a_pdf_does_not_say_how_to_read_it(monkeypatch, tmp_path):
    """A PDF gives the same command whether it is read as text or as a mini-book:
    the document settles it."""
    doc = tmp_path / "tadoku.pdf"
    doc.write_bytes(b"%PDF-1.7")
    feed(monkeypatch, ["5", "5", str(doc), "", "", ""])
    assert interactive_argv() == ["reading", str(doc)]


def test_reading_a_pdf_with_a_page_range(monkeypatch, tmp_path):
    """The range holds for both readings: it is asked for without knowing which."""
    doc = tmp_path / "papers.pdf"
    doc.write_bytes(b"%PDF-1.7")
    feed(monkeypatch, ["5", "5", str(doc), "3-18", "6", ""])
    assert interactive_argv() == [
        "reading", str(doc), "--pages", "3-18", "--count", "6",
    ]


def test_reading_a_single_page_is_a_one_page_range(monkeypatch, tmp_path):
    """"A single page" is not a mode of its own but `--pages` on one page; the
    card files what it needs to turn the pages by itself."""
    doc = tmp_path / "papers.pdf"
    doc.write_bytes(b"%PDF-1.7")
    feed(monkeypatch, ["5", "5", str(doc), "12", "", ""])
    assert interactive_argv() == ["reading", str(doc), "--pages", "12"]


def test_reading_an_unreadable_page_range_is_asked_again(monkeypatch, tmp_path):
    doc = tmp_path / "tadoku.pdf"
    doc.write_bytes(b"%PDF-1.7")
    feed(monkeypatch, ["5", "5", str(doc), "from 3 to 18", "3-18", "", ""])
    assert interactive_argv() == ["reading", str(doc), "--pages", "3-18"]


def test_reading_a_folder_of_pictures(monkeypatch, tmp_path):
    """Pages already in pictures: the folder is enough, and nothing to convert."""
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "p01.jpg").write_bytes(b"\xff\xd8")
    feed(monkeypatch, ["5", "5", str(pages), "", "", ""])
    assert interactive_argv() == ["reading", str(pages)]


# ── reading: the press catalogue ──────────────────────────────────────────────

def _feed_item(title, link, published="Mon, 24 Aug 2026 06:00:00 +0900"):
    import xml.etree.ElementTree as ET

    from kotogen.generators import feed as feed_module

    return feed_module.Item(title=title, link=link, published=published,
                            element=ET.Element("item"))


@pytest.fixture
def feed_articles(monkeypatch):
    """The feed answers two articles, whatever site is asked for."""
    from kotogen.generators import press

    read = []

    def articles(url, limit=0):
        read.append(url)
        return [_feed_item("台風[たいふう]のニュース", "https://example.test/a1"),
                _feed_item("経済[けいざい]の話", "https://example.test/a2",
                           published="Sun, 23 Aug 2026 06:00:00 +0900")]

    monkeypatch.setattr(press, "articles", articles)
    return read


def test_reading_press_chooses_a_site_then_an_article(monkeypatch,
                                                      press_catalogue,
                                                      feed_articles):
    """Two goes like the podcasts: the site, then what it publishes this morning."""
    # press source; 1st site (News genre); 2nd article; questions; no send
    feed(monkeypatch, ["5", "1", "2", "2", "", ""])
    assert interactive_argv() == ["reading", "https://example.test/a2"]
    assert feed_articles == ["https://jiji.test/rss"]


def test_reading_press_files_the_sites_by_genre(monkeypatch, press_catalogue,
                                                feed_articles, capsys):
    """NHK Easy opens the scale, then the press from the general to the
    specialised. The level is the first column, the one that sets NHK Easy apart;
    the genre, the second, sorts the sites."""
    feed(monkeypatch, ["5", "1", "2", "1", "", ""])
    interactive_argv()
    lines = [line.strip() for line in capsys.readouterr().out.splitlines()]
    assert "1. N5-N4  News      NHK News Web Easy" in lines
    assert "2. N2-N1  News      時事通信" in lines
    assert "3. N2-N1  Science   GIGAZINE" in lines


def test_reading_press_dates_every_article(monkeypatch, press_catalogue,
                                           feed_articles, capsys):
    """On a news feed the date is part of the choice."""
    feed(monkeypatch, ["5", "1", "2", "1", "", ""])
    interactive_argv()
    lines = [line.strip() for line in capsys.readouterr().out.splitlines()]
    assert "1. [ ] Aug 24 台風[たいふう]のニュース" in lines
    assert "2. [ ] Aug 23 経済[けいざい]の話" in lines


def test_reading_several_articles_of_one_feed(monkeypatch, press_catalogue,
                                              feed_articles):
    """Ticking several articles at once saves a pass through the menu for each."""
    # press source; 1st site; both articles; questions; no send
    feed(monkeypatch, ["5", "1", "2", "1 2", "", ""])
    assert interactive_argv() == ["reading", "https://example.test/a1",
                                  "https://example.test/a2"]


def test_reading_press_accepts_a_feed_outside_the_catalogue(monkeypatch,
                                                            press_catalogue,
                                                            feed_articles):
    """A site absent from the table stays reachable: as for the podcasts, the
    table is a shortcut, not a permission."""
    # press source; last entry; URL of the feed; 1st article; questions
    feed(monkeypatch, ["5", "1", "4", "https://other.test/feed", "1", "", ""])
    assert interactive_argv() == ["reading", "https://example.test/a1"]
    assert feed_articles == ["https://other.test/feed"]


def test_reading_press_a_silent_feed_says_why_and_lets_one_paste(monkeypatch,
                                                                 press_catalogue,
                                                                 capsys):
    """A feed that does not answer must not stop the command: the article aimed at
    may still be reachable by its address."""
    from kotogen.generators import press

    def articles(url, limit=0):
        raise RuntimeError("site unreachable - check your connection.")

    monkeypatch.setattr(press, "articles", articles)
    feed(monkeypatch, ["5", "1", "2", "https://example.test/article", "", ""])
    assert interactive_argv() == ["reading", "https://example.test/article"]
    assert "site unreachable" in capsys.readouterr().out


def test_reading_press_cleans_what_a_feed_says(monkeypatch, press_catalogue, capsys):
    """A title is the feed's own text: what drives a terminal is taken out, and a
    line break would split the menu line in two."""
    from kotogen.generators import press

    monkeypatch.setattr(press, "articles", lambda url, limit=0: [
        _feed_item("台風[たいふう]\x1b[2Jの\nニュース", "https://example.test/a1")])
    feed(monkeypatch, ["5", "1", "2", "1", "", ""])
    interactive_argv()
    out = capsys.readouterr().out
    assert "\x1b[2J" not in out
    assert "1. [ ] Aug 24 台風[たいふう][2Jの ニュース" in [
        line.strip() for line in out.splitlines()]


def test_reading_press_a_feed_failing_on_several_lines_says_its_first(monkeypatch,
                                                                      press_catalogue,
                                                                      capsys):
    from kotogen.generators import press

    def articles(url, limit=0):
        raise RuntimeError("site unreachable\n<html>the whole error page</html>")

    monkeypatch.setattr(press, "articles", articles)
    feed(monkeypatch, ["5", "1", "2", "https://example.test/article", "", ""])
    interactive_argv()
    out = capsys.readouterr().out
    assert "site unreachable" in out and "the whole error page" not in out


# ── reading: the catalogue of free books ──────────────────────────────────────

def _book(level, title, number):
    from kotogen.generators.pdf_web import Book

    return Book(level, title, f"https://tadoku.org/japanese/book/{number}/")


@pytest.fixture
def tadoku_catalogue(monkeypatch):
    """A catalogue of twenty books over three steps, without touching the network."""
    from kotogen.generators import pdf_web

    books = ([_book("l-start", "ちょっと来て！", 100)]
             + [_book("l0", f"やさしい本{n}", 200 + n) for n in range(17)]
             + [_book("l3", "くるみもち", 300), _book("l3", "色の世界", 301)])
    monkeypatch.setattr(pdf_web, "books", lambda **kwargs: list(books))
    return books


def test_reading_a_book_chosen_in_the_catalogue(monkeypatch, tadoku_catalogue):
    """The level, then the book: two menus, no URL to go and find."""
    # source "a book"; Tadoku; Start level; 1st book; pages; questions
    feed(monkeypatch, ["5", "2", "1", "1", "1", "", "", ""])
    assert interactive_argv() == ["reading", "https://tadoku.org/japanese/book/100/"]


def test_reading_a_book_shows_the_jlpt_level_in_a_column(monkeypatch,
                                                         tadoku_catalogue, capsys):
    """"Level 3" is the name of Tadoku's own step; N3 is the scale the user
    knows. The steps below N5 leave the column empty."""
    feed(monkeypatch, ["5", "2", "1", "1", "1", "", "", ""])
    interactive_argv()
    lines = [line.strip() for line in capsys.readouterr().out.splitlines()]
    assert "1.        Start     1 book" in lines
    assert "2.        Level 0  17 books" in lines
    assert "3. N3     Level 3   2 books" in lines


def test_reading_a_book_the_jlpt_level_heads_the_list_too(monkeypatch,
                                                          tadoku_catalogue, capsys):
    feed(monkeypatch, ["5", "2", "1", "3", "1", "", "", ""])
    assert interactive_argv() == ["reading", "https://tadoku.org/japanese/book/300/"]
    assert "Level 3 (N3) - 2 books" in capsys.readouterr().out


def test_reading_a_book_already_handled_is_flagged_without_being_removed(
        monkeypatch, tadoku_catalogue, capsys):
    """The history marks the books that already gave cards without removing them:
    reading one again for other pages is a valid request."""
    seen.mark("reading", "tadoku", "300", "くるみもち")
    feed(monkeypatch, ["5", "2", "1", "3", "1", "", "", ""])
    assert interactive_argv() == ["reading", "https://tadoku.org/japanese/book/300/"]
    out = capsys.readouterr().out
    assert "くるみもち (already handled)" in out
    assert "色の世界 (already handled)" not in out
    # The count of the level says it too, before its list is opened.
    assert "3. N3     Level 3   2 books, 1 already handled" in [
        line.strip() for line in out.splitlines()]


def test_reading_a_book_handled_on_another_machine_is_flagged(monkeypatch,
                                                              tadoku_catalogue,
                                                              capsys):
    """Nothing in the local history, but the card is in the deck: a second
    machine, where the file alone would mislead."""
    from kotogen import memory
    from kotogen.known import Sources as DeckSources

    monkeypatch.setattr(memory.known(), "_sources", DeckSources({
        "reading": frozenset({"https://tadoku.org/japanese/book/300/ (p. 3-)"})}))
    feed(monkeypatch, ["5", "2", "1", "3", "1", "", "", ""])
    interactive_argv()
    assert "くるみもち (already handled)" in capsys.readouterr().out


def test_reading_a_new_level_says_nothing(monkeypatch, tadoku_catalogue, capsys):
    """A level with nothing handled says nothing, rather than "0 already handled"."""
    seen.mark("reading", "tadoku", "300", "くるみもち")
    feed(monkeypatch, ["5", "2", "1", "1", "1", "", "", ""])
    interactive_argv()
    lines = [line.strip() for line in capsys.readouterr().out.splitlines()]
    assert "1.        Start     1 book" in lines


def test_reading_a_long_book_list_turns(monkeypatch, tadoku_catalogue):
    """Seventeen books fit in two screens: the sixteenth is only reachable after
    "see the next ones", and the menu never goes past the screen."""
    # level 0; "see the next 2" (the letter n); 2nd of the next page
    feed(monkeypatch, ["5", "2", "1", "2", "n", "2", "", "", ""])
    assert interactive_argv() == ["reading", "https://tadoku.org/japanese/book/216/"]


def test_reading_a_book_page_turns_both_ways(monkeypatch, tadoku_catalogue, capsys):
    """A page passed can be turned back to, without starting over from the first."""
    # level 0; next page; previous page; the 1st of the list
    feed(monkeypatch, ["5", "2", "1", "2", "n", "p", "1", "", "", ""])
    assert interactive_argv() == ["reading", "https://tadoku.org/japanese/book/200/"]
    out = capsys.readouterr().out
    assert "See the next 2" in out and "See the previous 15 again" in out


def test_reading_several_books_of_one_level(monkeypatch, tadoku_catalogue):
    """Several books make one request, and the pages are not asked: a range aims
    at one document."""
    # level 0; books 1 and 3; questions; no send
    feed(monkeypatch, ["5", "2", "1", "2", "1 3", "", ""])
    assert interactive_argv() == ["reading",
                                  "https://tadoku.org/japanese/book/200/",
                                  "https://tadoku.org/japanese/book/202/"]


def test_reading_the_book_boxes_survive_the_change_of_page(
        monkeypatch, tadoku_catalogue):
    """A level spans more than one screen: the boxes ticked on every page count,
    handed back in the order of the level."""
    # level 0; the 1st ticked then the page turned; the 2nd of the next page
    feed(monkeypatch, ["5", "2", "1", "2", "1 n", "2", "", ""])
    assert interactive_argv() == ["reading",
                                  "https://tadoku.org/japanese/book/200/",
                                  "https://tadoku.org/japanese/book/216/"]


def test_reading_a_pasted_book_url_stays_possible(monkeypatch, tadoku_catalogue):
    """A book outside the catalogue (or a record found elsewhere) always goes
    through."""
    # book source; last entry of the levels menu; URL; pages; questions
    feed(monkeypatch, ["5", "2", "1", "4", "https://tadoku.org/japanese/book/6346/",
                       "3-", "", ""])
    assert interactive_argv() == [
        "reading", "https://tadoku.org/japanese/book/6346/", "--pages", "3-",
    ]


def test_reading_an_unreachable_catalogue_asks_for_the_url(monkeypatch, capsys):
    """Offline, the menu cannot be built: it says so and lets one paste a URL,
    rather than showing an empty list."""
    from kotogen.generators import pdf_web

    monkeypatch.setattr(pdf_web, "books", lambda **kwargs: [])
    feed(monkeypatch, ["5", "2", "1", "https://tadoku.org/japanese/book/6346/",
                       "", "", ""])
    assert interactive_argv() == ["reading", "https://tadoku.org/japanese/book/6346/"]
    assert "Catalogue unreachable" in capsys.readouterr().out


def test_reading_a_tadoku_url_that_is_not_a_book_is_refused(monkeypatch):
    """The list of free books is not a book: it is refused at once, pointing to
    the menu entry that replaces it, rather than read as an empty article."""
    feed(monkeypatch, ["5", "4", "https://tadoku.org/japanese/free-books/",
                       "https://tadoku.org/japanese/book/6346/", "", "", ""])
    assert interactive_argv() == ["reading", "https://tadoku.org/japanese/book/6346/"]


# ── A text written on the deck ────────────────────────────────────────────────

def test_reading_a_text_on_the_deck_defaults_to_one_short_story(monkeypatch):
    # a text on the deck; story; the level of the deck; short; one text;
    # questions on the content
    feed(monkeypatch, ["5", "6", "", "", "", "", "", ""])
    assert interactive_argv() == ["reading", "deck"]


def test_reading_a_text_on_the_deck_says_only_what_differs(monkeypatch):
    """Shape, level and length are paid for: asked here, and written out only
    when they are not the default."""
    feed(monkeypatch, ["5", "6", "2", "3", "2", "2", "", ""])
    assert interactive_argv() == [
        "reading", "deck", "--shape", "exam", "--level", "N3", "--length", "medium",
        "--texts", "2",
    ]


def test_a_level_asked_for_gives_the_lengths_of_that_level():
    """A level asked for has one figure per length (`auto` gets the range across
    the levels), and no 長文 below N3, where the exam sets none."""
    from kotogen.interactive.reading import _deck_story_lengths

    assert [key for key, _name, _size in _deck_story_lengths("N4")] == ["short", "medium"]
    assert [size for _key, _name, size in _deck_story_lengths("N1")] == [
        "about 200 characters", "about 500 characters", "about 1,000 characters"]
    assert len(_deck_story_lengths("auto")) == 3
