"""The official JLPT past papers: recognising the alias, addresses, history.

No network: what is checked is the table of addresses, where a mistake would
cost a 404 in the middle of a batch.
"""

from __future__ import annotations

import pytest

from kotogen import seen
from kotogen.generators import jlpt_papers as papers, sources

# -- Recognising the input ----------------------------------------------------

@pytest.mark.parametrize("entry", [
    "jlpt", "jlpt-n3", "JLPT-N3", "jlpt2012-n5", "jlpt2009-n1",
])
def test_it_recognises_the_aliases(entry):
    assert papers.is_jlpt_input(entry)


@pytest.mark.parametrize("entry", [
    "", "jlpt-n9", "jlpt2020-n3", "teppei", "nhk", "papers.pdf",
    "https://example.test/rss",
])
def test_it_ignores_what_is_not_one(entry):
    assert not papers.is_jlpt_input(entry)


def test_the_podcast_does_not_pick_up_the_past_paper_aliases():
    """`is_podcast_input` takes any lone word that is not a file for an alias:
    "jlpt-n3" needs an explicit refusal, or it goes to the RSS parser."""
    from kotogen.generators import podcast
    assert not podcast.is_podcast_input("jlpt-n3")
    assert not sources.is_podcast("jlpt-n3")
    assert sources.is_jlpt("jlpt-n3")


# -- Resolving ----------------------------------------------------------------

def test_the_level_is_part_of_the_alias():
    target = papers.resolve("jlpt-n3")
    assert target.level == "N3"
    assert target.collection.key == "jlpt"
    assert target.key == "jlpt-n3"


def test_an_alias_without_a_level_says_what_can_be_typed():
    # No default: choosing one would pull fifty megabytes of the wrong level. So
    # the message has to carry the complete aliases.
    with pytest.raises(ValueError) as raised:
        papers.resolve("jlpt")
    message = str(raised.value)
    assert "jlpt-n5" in message and "jlpt-n1" in message
    assert "jlpt2012" in message


def test_the_levels_are_followed_separately():
    """Two levels of the same collection share neither cache nor history."""
    assert papers.resolve("jlpt-n3").key != papers.resolve("jlpt-n4").key


# -- The addresses composed ---------------------------------------------------

def test_the_reading_booklet_is_the_one_of_its_level():
    assert papers.COLLECTIONS["jlpt"].booklet("N3") == (
        "https://www.jlpt.jp/samples/sample2018/pdf/N3R.pdf")


def test_the_2009_collection_has_a_template_of_its_own():
    # A booklet in one piece, at the root of the site and not in a subfolder.
    assert papers.COLLECTIONS["jlpt2009"].booklet("N4") == (
        "https://www.jlpt.jp/samples/pdf/N4-mondai.pdf")


def test_the_figures_booklet_is_not_the_reading_one():
    """`N3R.pdf` is the 読解 and carries no listening page; the listening
    exercises are drawn in `N3L.pdf`, published beside it."""
    collection = papers.COLLECTIONS["jlpt"]
    assert collection.figures_booklet("N3") == (
        "https://www.jlpt.jp/samples/sample2018/pdf/N3L.pdf")
    assert collection.figures_booklet("N3") != collection.booklet("N3")


def test_the_2009_collection_has_no_figures_booklet():
    """Not for want of an address: that booklet is a scan whose text layer holds
    only the header and the folio, so a vision call on it would be paid for nothing."""
    assert papers.COLLECTIONS["jlpt2009"].figures_booklet("N5") == ""


def test_a_collection_without_a_figures_booklet_downloads_nothing(monkeypatch):
    """None without a word: the cards are made without an image."""
    def never(*args, **kwargs):
        raise AssertionError("no download should be attempted")

    monkeypatch.setattr(papers.download, "file", never)
    assert papers.figures_booklet(papers.resolve("jlpt2009-n5")) is None


def test_the_figures_booklet_is_brought_back_apart_from_the_reading_one(
        monkeypatch, tmp_path):
    """Both live in the same cache, under their own name: failing which the
    second would crush the first, and reading would give back listening pages."""
    asked = []

    def fake(url, dest, **kwargs):
        asked.append((url, dest.name))
        dest = tmp_path / dest.name
        dest.write_bytes(b"%PDF-1.4")
        return dest

    monkeypatch.setattr(papers.download, "file", fake)
    target = papers.resolve("jlpt-n4")
    papers.booklet(target)
    papers.figures_booklet(target)
    assert asked == [
        ("https://www.jlpt.jp/samples/sample2018/pdf/N4R.pdf", "N4R.pdf"),
        ("https://www.jlpt.jp/samples/sample2018/pdf/N4L.pdf", "N4L.pdf"),
    ]


def test_the_beginner_levels_have_fewer_sections():
    """N4 and N5 have no fifth 問題: composing its address would give a 404."""
    numbers = [number for number, _url in papers.COLLECTIONS["jlpt"].tracks("N5")]
    assert numbers == [1, 2, 3, 4]
    assert [n for n, _url in papers.COLLECTIONS["jlpt"].tracks("N1")] == [1, 2, 3, 4, 5]


def test_the_section_republished_in_2017_is_taken_at_its_own_root():
    """The one collection published in two places: the table of exceptions wins
    over the template, or the ポイント理解 is missing."""
    addresses = dict(papers.COLLECTIONS["jlpt2012"].tracks("N3"))
    assert addresses[2] == "https://www.jlpt.jp/samples/sample2017/mp3/N3Q2.mp3"
    assert addresses[1] == "https://www.jlpt.jp/samples/sample2012/mp3/N3Q1.mp3"


# -- History ------------------------------------------------------------------

def test_a_handled_section_does_not_come_back():
    target = papers.resolve("jlpt-n5")
    left, done = papers.tracks(target)
    assert len(left) == 4 and done == 0

    papers.mark_done(target, left[0])
    left, done = papers.tracks(target)
    assert [t.name for t in left] == ["問題2", "問題3", "問題4"]
    assert done == 1


def test_the_reading_booklet_is_followed_apart_from_the_sections():
    """The booklet (reading) and the sections (listening) share a key: the mode
    tells them apart."""
    target = papers.resolve("jlpt-n5")
    assert not papers.is_read(target)
    papers.mark_read(target)
    assert papers.is_read(target)
    # Listening knows nothing of it: its four sections are still to do.
    left, done = papers.tracks(target)
    assert len(left) == 4 and done == 0


def test_the_provenance_names_the_collection_and_the_section():
    target = papers.resolve("jlpt-n3")
    track = papers.Track(2, "https://example.test/N3Q2.mp3")
    assert papers.provenance(target, track) == (
        "JLPT 公式問題集 第二集 (2018) - N3 - 問題2")


def test_no_pointer_to_the_file_one_is_already_listening_to():
    # Like a podcast: the link would aim at the mp3 the card carries, and would
    # download it again on a click.
    target = papers.resolve("jlpt-n3")
    assert papers.link(target, papers.Track(1, "https://example.test/x.mp3")) == ""


def test_the_cleanup_throws_nothing_away():
    """A closed collection: its cache makes resuming free, and never grows."""
    target = papers.resolve("jlpt-n3")
    folder = papers.cache_folder(target)
    (folder / "N3_問題1.mp3").write_bytes(b"x")
    papers.cleanup(target)
    assert (folder / "N3_問題1.mp3").exists()


def test_the_history_is_filed_under_a_readable_name():
    """The settings screen lists the sources by their key: it has to read."""
    target = papers.resolve("jlpt2012-n2")
    papers.mark_done(target, papers.Track(1, "https://example.test/x.mp3"))
    assert [trace.source for trace in seen.inventory()] == ["jlpt2012-n2"]


# -- Wiring into the reading route --------------------------------------------

def test_the_booklet_is_brought_back_like_a_distant_document(monkeypatch, tmp_path):
    """The rest of `reading` knows nothing but files: the collection has to enter
    it like a Tadoku page, with its name for the screen and for the card."""
    from kotogen.generators import reading

    fake = tmp_path / "N3R.pdf"
    fake.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(papers.download, "file",
                        lambda url, dest, **kwargs: fake)

    inputs, books, origins, titles, alias = reading._fetch_web_pdfs(["jlpt-n3"])
    assert inputs == [str(fake)] and not books
    # The name of the collection, and not "jlpt-n3": it is what the card keeps.
    assert origins[str(fake)] == "JLPT 公式問題集 第二集 (2018) - N3 (読解)"
    assert titles[str(fake)] == origins[str(fake)]
    # The alias typed survives apart, to memorise once the cards are made.
    assert alias[str(fake)] == "jlpt-n3"


def test_a_missing_level_is_said_without_carrying_off_the_batch(monkeypatch, capsys):
    from kotogen.generators import reading

    inputs, _books, _origins, _titles, _alias = reading._fetch_web_pdfs(
        ["jlpt", "course.pdf"])
    assert inputs == ["course.pdf"]
    assert "at which level" in capsys.readouterr().err


# -- The deck as a second memory ----------------------------------------------
# The local history knows only this machine: on a second one, or after a
# "forget everything", the deck says what is already done.

def _deck(*traces: str, mode: str = "audio"):
    from kotogen.known import Sources as DeckSources
    return DeckSources({mode: frozenset(traces)})


def test_a_section_the_deck_already_carries_does_not_come_back(monkeypatch):
    from kotogen import memory

    target = papers.resolve("jlpt2012-n3")
    monkeypatch.setattr(memory.known(), "_sources", _deck(
        "JLPT 公式問題集 (2012) - N3 - 問題2 (00:12 → 00:45)"))
    left, done = papers.tracks(target)
    assert [track.name for track in left] == ["問題1", "問題3", "問題4", "問題5"]
    assert done == 1


def test_the_deck_confuses_neither_two_collections_nor_two_levels(monkeypatch):
    """Three collections publish a 問題1: the collection and the level in the
    provenance tell them apart."""
    from kotogen import memory

    monkeypatch.setattr(memory.known(), "_sources",
                        _deck("JLPT 公式問題集 (2012) - N3 - 問題1"))
    for alias in ("jlpt-n3", "jlpt2012-n5", "jlpt2009-n3"):
        left, done = papers.tracks(papers.resolve(alias))
        assert done == 0 and "問題1" in [track.name for track in left]


def test_a_booklet_already_read_shows_in_the_deck_too(monkeypatch):
    from kotogen import memory

    target = papers.resolve("jlpt2012-n3")
    assert not papers.is_read(target)
    monkeypatch.setattr(memory.known(), "_sources", _deck(
        "JLPT 公式問題集 (2012) - N3 (読解) (p. 3-)", mode="reading"))
    assert papers.is_read(target)


@pytest.mark.parametrize("trace, expected", [
    ("JLPT 公式問題集 (2012) - N3 - 問題2 (00:12 → 00:45)", ("jlpt2012-n3", "問題2")),
    ("JLPT 公式問題集 第二集 (2018) - N5 (読解) (p. 3-)", ("jlpt-n5", "読解")),
    ("JLPT 問題例集 (2009) - N1 - 問題1", ("jlpt2009-n1", "問題1")),
    # An unknown collection, an unknown level, another source.
    ("JLPT 公式問題集 (2015) - N3 - 問題1", None),
    ("JLPT 公式問題集 (2012) - N9 - 問題1", None),
    ("Nihongo con Teppei - Ep 700", None),
    ("", None),
])
def test_a_provenance_says_which_collection_it_comes_from(trace, expected):
    """`recognise` reads back what `provenance` writes, which lets a new machine
    pick up from the deck."""
    assert papers.recognise(trace) == expected


def test_what_recognise_returns_is_what_the_history_files(monkeypatch):
    """The key and the identifier have to be the ones `mark_done` writes, failing
    which the same section would enter the history twice."""
    target = papers.resolve("jlpt2012-n3")
    track = papers.Track(2, "https://example.test/x.mp3")
    papers.mark_done(target, track)
    assert papers.recognise(papers.provenance(target, track)) == \
        (target.key, next(iter(seen.load("audio", target.key))))


# -- The menu: the level, then the collection -------------------------------

def _menu_answers(monkeypatch, answers):
    """Drives `_chosen_exam_papers` and hands back what each screen showed."""
    screens: list[tuple[str, list[str], dict]] = []
    replies = iter(answers)

    def fake_menu(title, options, **kwargs):
        screens.append((title, [label for _key, label in options], kwargs))
        return next(replies)

    _replace_menu(monkeypatch, fake_menu)
    return screens


def _replace_menu(monkeypatch, fake_menu):
    """The level is asked by the catalogue, the collection by `_submenu`,
    which reads the menu of `screen`: both are replaced."""
    from kotogen import interactive

    for module in (interactive.catalogues, interactive.screen):
        monkeypatch.setattr(module, "_menu", fake_menu)


def test_the_level_is_asked_first_and_the_collection_after(monkeypatch):
    """The level is what one knows of oneself; the year is the second question."""
    from kotogen import interactive

    screens = _menu_answers(monkeypatch, ["N3", "jlpt2012-n3"])
    assert interactive.catalogues._chosen_exam_papers("audio") == "jlpt2012-n3"

    levels, collections = screens[0], screens[1]
    assert levels[1] == list(papers.LEVELS)
    # No collection on that screen: no name in the title, no way out to another.
    assert not any(collection.name in levels[0] for collection in papers.COLLECTIONS.values())
    assert "N3" in collections[0]
    assert [label.split("  ")[0] for label in collections[1]] ==         [collection.name for collection in papers.COLLECTIONS.values()]


def test_every_collection_is_offered_at_the_level_just_chosen(monkeypatch):
    """The three set the same exam: one picks a year for the level already given."""
    from kotogen import interactive

    keys: list[str] = []
    replies = iter(["N5", "jlpt2009-n5"])

    def fake_menu(title, options, **kwargs):
        keys.append([key for key, _label in options])
        return next(replies)

    _replace_menu(monkeypatch, fake_menu)
    assert interactive.catalogues._chosen_exam_papers("reading") == "jlpt2009-n5"
    assert keys[1] == ["jlpt-n5", "jlpt2012-n5", "jlpt2009-n5"]


def test_the_collection_screen_opens_on_the_default_collection(monkeypatch):
    """The one the bare alias `jlpt` names, so the menu and the command line
    agree, not the first line of the table, which only happens to match."""
    from kotogen import interactive

    screens = _menu_answers(monkeypatch, ["N1", "jlpt-n1"])
    interactive.catalogues._chosen_exam_papers("audio")
    assert screens[1][2]["default"] == f"{papers.DEFAULT}-n1"


def test_a_collection_announces_what_is_left_to_do_at_that_level(monkeypatch):
    """That is what the choice of a year turns on: the exercise is the same in
    all three, only what is left differs."""
    from kotogen import interactive

    target = papers.resolve("jlpt2012-n3")
    papers.mark_done(target, papers.Track(1, "https://example.test/x.mp3"))
    screens = _menu_answers(monkeypatch, ["N3", "jlpt-n3"])
    interactive.catalogues._chosen_exam_papers("audio")
    done = [label for label in screens[1][1] if "JLPT 公式問題集 (2012)" in label]
    assert "already handled" in done[0]


# ── What the download says ────────────────────────────────────────────────────

def _download(monkeypatch, tmp_path, done: int) -> str:
    import contextlib
    import io

    from kotogen.generators import audio

    tracks = [papers.Track(number, f"https://example.test/N3Q{number}.mp3")
              for number in (1, 2)]

    def fetch(target, track):
        path = tmp_path / f"{track.name}.mp3"
        path.write_bytes(b"0" * 1024)
        return path

    monkeypatch.setattr(papers, "tracks", lambda target: (tracks, done))
    monkeypatch.setattr(papers, "fetch", fetch)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        audio._jlpt_sections(["jlpt2012-n3"], 0)
    return out.getvalue()


def test_the_sections_are_counted_by_their_list_alone(monkeypatch, tmp_path):
    """The list names them one per line and the download counts its files: a
    "2 sections" above would say it a third time."""
    out = _download(monkeypatch, tmp_path, done=0)
    assert "2 sections" not in out
    assert "問題1" in out and "問題2" in out


def test_the_sections_left_out_are_still_said(monkeypatch, tmp_path):
    """The sections skipped as handled, which the list does not show, keep a line."""
    out = _download(monkeypatch, tmp_path, done=3)
    assert "already handled" in out
