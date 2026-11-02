"""いろどり: the four volumes, the lesson as a unit, and the sorting of tracks.

No network: the page of a lesson is a string written here, shaped like the
site's. The sorting matters most: of a lesson's up to thirty-five tracks, most
would make no card. The lesson titles are invented ones, of the shape of the
textbook's: no test depends on what the textbook says.
"""

from __future__ import annotations

import pytest

from kotogen.generators import irodori, sources

# The lessons the tests name, by (folder, rank); every other one is numbered.
_NAMED = {
    ("elementary01", 1): ("今の生活", "駅の近くに住んでいます"),
    ("elementary01", 3): ("天気の話", "あしたは雪が降りそうです"),
    ("pre-intermediate", 5): ("毎日のごはん", "どこで食べましょうか？"),
}


def _heading_of(folder: str, rank: int) -> tuple[str, str]:
    """Two lessons a topic, as in the textbook."""
    return _NAMED.get((folder, rank), (f"話題{(rank + 1) // 2}", f"会話{rank}をしましょう"))


def lesson_page(topic: str, title: str, rank: int) -> str:
    """The <h1> of a lesson page as the site writes it, its commented copy included."""
    return f"""
<h1>
    <label class="elementary_label"><a class="c1" href="/x/pdf.html">初級１</a></label>
    <label class="topic_label">
        <span>トピック</span>
        <span class="c1t2">{topic}</span>
    </label>
    <label class="lesson_label">
        <span>第{rank}課</span>
        <span>{title}</span>
    </label>
    <!-- <label class="lesson_label">
        <span>第{rank}課</span>
        <span>古い題</span>
    </label> -->
</h1>
"""


@pytest.fixture(autouse=True)
def site(monkeypatch):
    """The lesson pages of an invented textbook; `site.asked` lists the pages read."""
    class Site:
        asked: list[str] = []
        up = True

    def page(url, **kwargs):
        if not Site.up:
            raise RuntimeError("site unreachable - check your connection.")
        Site.asked.append(url)
        folder = url.split("/")[3]
        rank = int(url.rsplit("lesson", 1)[1][:2])
        return lesson_page(*_heading_of(folder, rank), rank).encode("utf-8")

    Site.asked = []
    monkeypatch.setattr(irodori.download, "page", page)
    return Site


PAGE = """
<h1>初級１ トピック 話題5 第9課 会話9をしましょう</h1>
<audio src="/assets/data/elementary01/audio/09/Y_[09-01]_kiku1.mp3"></audio>
<audio src="/assets/data/elementary01/audio/09/Y_[09-05]_katachi.mp3"></audio>
<audio src="/assets/data/elementary01/audio/09/Y_[09-06]_hanasu.mp3"></audio>
<audio src="/assets/data/elementary01/audio/09/Y_[09-07]_kotoba1.mp3"></audio>
<audio src="/assets/data/elementary01/audio/09/Y_[09-10]_kaiwa.mp3"></audio>
<audio src="/assets/data/elementary01/audio/09/Y_[09-11]_strategy.mp3"></audio>
"""


# -- Recognising and resolving ------------------------------------------------

@pytest.mark.parametrize("entry", [
    "irodori", "irodori-nyumon", "IRODORI-SHOKYU1", "irodori-shochukyu",
])
def test_it_recognises_the_aliases(entry):
    assert irodori.is_irodori_input(entry)


@pytest.mark.parametrize("entry", ["", "irodori-n3", "teppei", "nhk"])
def test_it_ignores_what_is_not_one(entry):
    assert not irodori.is_irodori_input(entry)


def test_the_podcast_does_not_pick_up_the_textbook_aliases():
    from kotogen.generators import podcast
    assert not podcast.is_podcast_input("irodori")
    assert sources.is_irodori("irodori-shokyu2")


def test_an_alias_without_a_volume_lists_the_four():
    with pytest.raises(ValueError) as raised:
        irodori.resolve("irodori")
    message = str(raised.value)
    for alias in irodori.VOLUMES:
        assert alias in message


def test_a_lesson_knows_how_to_name_itself_and_where_it_lives():
    lesson = irodori.lessons(irodori.VOLUMES["irodori-shokyu1"], 1, from_lesson=3)[0][0]
    assert lesson.name == "第3課 あしたは雪が降りそうです"
    assert lesson.theme == "天気の話"
    assert lesson.page == "https://www.irodori.jpf.go.jp/elementary01/audio/lesson03.html"
    assert lesson.pdf.endswith("/elementary01/pdf/Y_L03.pdf")


# -- The headings, read off the site ------------------------------------------

def test_the_heading_is_the_first_of_the_page_and_not_its_commented_copy():
    assert irodori.heading(lesson_page("天気の話", "雪が降りそうです", 3)) == (
        "天気の話", "雪が降りそうです")
    assert irodori.heading("<html>nothing</html>") is None


def test_a_heading_read_once_is_kept_in_the_cache(site):
    volume = irodori.VOLUMES["irodori-shokyu1"]
    irodori.lessons(volume, 1, from_lesson=3)
    site.up = False
    lesson = irodori.lessons(volume, 1, from_lesson=3)[0][0]
    assert lesson.title == "あしたは雪が降りそうです"
    assert len(site.asked) == 1


def test_a_cache_of_another_shape_is_read_again_off_the_site(site):
    """A volume filed as a list, by a crash or by hand, must not stop the run."""
    irodori._headings_file().parent.mkdir(parents=True, exist_ok=True)
    irodori._headings_file().write_text('{"elementary01": ["今の生活"]}', encoding="utf-8")

    lesson = irodori.lessons(irodori.VOLUMES["irodori-shokyu1"], 1, from_lesson=3)[0][0]

    assert lesson.title == "あしたは雪が降りそうです"
    assert len(site.asked) == 1


def test_only_the_lessons_handed_back_are_named(site):
    """Eighteen lessons are sorted, but only the one picked has its page read."""
    irodori.lessons(irodori.VOLUMES["irodori-shokyu2"], 1)
    assert len(site.asked) == 1


def test_the_page_read_for_the_heading_also_gives_the_tracks(monkeypatch):
    """The heading and the tracks are on one page: it is read once, not twice."""
    asked: list[str] = []

    def page(url, **kwargs):
        asked.append(url)
        return (lesson_page(*_heading_of("elementary01", 9), 9) + PAGE).encode("utf-8")

    monkeypatch.setattr(irodori.download, "page", page)
    lesson = irodori.lessons(irodori.VOLUMES["irodori-shokyu1"], 1, from_lesson=9)[0][0]

    assert [name for name, _url in irodori.tracks(lesson)] == [
        "Y_[09-01]_kiku1.mp3", "Y_[09-10]_kaiwa.mp3"]
    assert len(asked) == 1


def test_a_cache_that_cannot_be_written_does_not_lose_the_lesson(site, monkeypatch):
    """A read-only cache folder: the heading is not kept, the lesson still goes."""
    def read_only(path, text):
        raise PermissionError(13, "read-only file system")

    monkeypatch.setattr(irodori.system, "write_whole", read_only)
    lesson = irodori.lessons(irodori.VOLUMES["irodori-shokyu1"], 1, from_lesson=3)[0][0]
    assert lesson.title == "あしたは雪が降りそうです"


def test_without_the_site_a_lesson_goes_by_its_number(site):
    site.up = False
    lesson = irodori.lessons(irodori.VOLUMES["irodori-shokyu1"], 1, from_lesson=3)[0][0]
    assert lesson.name == "第3課" and lesson.theme == ""
    assert irodori.provenance(lesson) == "いろどり 初級1 (A2) - 第3課"
    assert irodori.recognise(irodori.provenance(lesson)) == ("irodori-shokyu1", "3")


# -- The sorting of tracks ----------------------------------------------------

def test_only_the_dialogues_are_kept(monkeypatch):
    """kotoba is a list of words, katachi a conjugation table, hanasu a model
    sentence, strategy a piece of guidance: none of them makes a card."""
    monkeypatch.setattr(irodori.download, "page",
                        lambda url, **kwargs: PAGE.encode("utf-8"))
    lesson = irodori.Lesson(irodori.VOLUMES["irodori-shokyu1"], "irodori-shokyu1", 9)
    names = [name for name, _url in irodori.tracks(lesson)]
    assert names == ["Y_[09-01]_kiku1.mp3", "Y_[09-10]_kaiwa.mp3"]


def test_the_addresses_are_absolute(monkeypatch):
    monkeypatch.setattr(irodori.download, "page",
                        lambda url, **kwargs: PAGE.encode("utf-8"))
    lesson = irodori.Lesson(irodori.VOLUMES["irodori-shokyu1"], "irodori-shokyu1", 9)
    _name, url = irodori.tracks(lesson)[0]
    assert url == ("https://www.irodori.jpf.go.jp/assets/data/elementary01/"
                   "audio/09/Y_[09-01]_kiku1.mp3")


def test_a_track_name_that_would_leave_the_cache_is_dropped(monkeypatch):
    """The name read off the page becomes a path in the cache folder: a backslash
    or a `..` in it would write the file anywhere on the disk."""
    page = PAGE + ('<audio src="/assets/data/elementary01/audio/09/'
                   'Y_[09-12]_kaiwa\\..\\..\\outside.mp3"></audio>'
                   '<audio src="/assets/data/elementary01/audio/09/'
                   'Y_[09-13]_kaiwa..mp3"></audio>')
    monkeypatch.setattr(irodori.download, "page", lambda url, **kwargs: page.encode("utf-8"))
    lesson = irodori.Lesson(irodori.VOLUMES["irodori-shokyu1"], "irodori-shokyu1", 9)
    names = [name for name, _url in irodori.tracks(lesson)]
    assert names == ["Y_[09-01]_kiku1.mp3", "Y_[09-10]_kaiwa.mp3"]


def test_a_page_with_no_dialogue_says_so(monkeypatch):
    monkeypatch.setattr(irodori.download, "page",
                        lambda url, **kwargs: b"<html>nothing</html>")
    lesson = irodori.Lesson(irodori.VOLUMES["irodori-shokyu1"], "irodori-shokyu1", 9)
    with pytest.raises(RuntimeError, match="no dialogue"):
        irodori.tracks(lesson)


# -- The lesson as the unit of work -------------------------------------------

def test_a_textbook_is_climbed_in_order():
    volume = irodori.VOLUMES["irodori-shokyu1"]
    lessons, done = irodori.lessons(volume, 2)
    assert [lesson.rank for lesson in lessons] == [1, 2]
    assert done == 0


def test_a_handled_lesson_does_not_come_back():
    volume = irodori.VOLUMES["irodori-shokyu1"]
    first = irodori.lessons(volume, 1)[0][0]
    irodori.mark_done(first)
    lessons, done = irodori.lessons(volume, 1)
    assert lessons[0].rank == 2 and done == 1


def test_a_number_typed_by_hand_ignores_the_history():
    volume = irodori.VOLUMES["irodori-shokyu1"]
    irodori.mark_done(irodori.Lesson(volume, "irodori-shokyu1", 7))
    lessons, done = irodori.lessons(volume, 1, from_lesson=7)
    assert lessons[0].rank == 7 and done == 0


def test_a_number_outside_the_textbook_is_refused():
    volume = irodori.VOLUMES["irodori-shokyu1"]
    with pytest.raises(ValueError, match="lessons 1 to 18"):
        irodori.lessons(volume, 1, from_lesson=19)


def test_the_history_is_its_own_for_each_mode():
    """A lesson done in listening is still to do in reading, like an NHK article."""
    volume = irodori.VOLUMES["irodori-shokyu2"]
    irodori.mark_done(irodori.Lesson(volume, "irodori-shokyu2", 1), mode="audio")
    assert irodori.lessons(volume, 1, mode="audio")[0][0].rank == 2
    assert irodori.lessons(volume, 1, mode="reading")[0][0].rank == 1


def test_the_provenance_names_the_volume_and_the_lesson():
    volume = irodori.VOLUMES["irodori-shochukyu"]
    lesson = irodori.lessons(volume, 1, from_lesson=5)[0][0]
    assert irodori.provenance(lesson, None) == (
        "いろどり 初中級 (A2/B1) - 第5課 どこで食べましょうか？")


def test_the_pointer_points_at_the_lesson_and_not_at_the_file():
    """Unlike a podcast's, the page carries the dialogue, its brief and its answers."""
    lesson = irodori.Lesson(irodori.VOLUMES["irodori-shokyu1"], "irodori-shokyu1", 3)
    assert irodori.link(lesson, None) == lesson.page


def test_the_jlpt_level_is_given_for_what_it_is():
    # 入門 is below N5: its cell stays empty rather than inventing a step.
    assert irodori.level_label(irodori.VOLUMES["irodori-nyumon"].levels) == ""
    assert irodori.level_label(irodori.VOLUMES["irodori-shochukyu"].levels) == "N4-N3"


# -- Wiring into the reading route --------------------------------------------

def test_the_next_lesson_is_brought_back_as_a_pdf(monkeypatch, tmp_path):
    from kotogen.generators import reading

    fake = tmp_path / "Y_L01.pdf"
    fake.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(irodori.download, "file",
                        lambda url, dest, **kwargs: fake)

    inputs, _books, origins, _titles, alias = reading._fetch_web_pdfs(
        ["irodori-shokyu1"])
    assert inputs == [str(fake)]
    assert origins[str(fake)] == (
        "いろどり 初級1 (A2) - 第1課 駅の近くに住んでいます")
    assert alias[str(fake)] == "irodori-shokyu1"


def test_an_exhausted_volume_says_so_instead_of_going_round_in_circles(
        monkeypatch, capsys):
    from kotogen.generators import reading

    volume = irodori.VOLUMES["irodori-shokyu1"]
    for rank in range(1, 19):
        irodori.mark_done(irodori.Lesson(volume, "irodori-shokyu1", rank),
                          mode="reading")
    inputs, _books, _origins, _titles, _alias = reading._fetch_web_pdfs(
        ["irodori-shokyu1"])
    assert inputs == []
    assert "already been handled in reading" in capsys.readouterr().err


# -- The deck as a second memory ----------------------------------------------

def _deck(*traces: str, mode: str = "audio"):
    from kotogen.known import Sources as DeckSources
    return DeckSources({mode: frozenset(traces)})


def test_a_lesson_the_deck_already_carries_does_not_come_back(monkeypatch):
    """A second machine: the local history is empty there, the deck is not."""
    from kotogen import memory

    volume = irodori.VOLUMES["irodori-shokyu1"]
    monkeypatch.setattr(memory.known(), "_sources", _deck(
        "いどりどり - 第1課 x",   # a provenance that only half looks like it
        "いろどり 初級1 (A2) - 第1課 駅の近くに住んでいます (00:12 → 00:45)"))
    lessons, done = irodori.lessons(volume, 1)
    assert lessons[0].rank == 2 and done == 1


def test_the_deck_knows_a_lesson_by_its_number_whatever_title_it_carries(monkeypatch):
    """A card made while the site was down carries no title; one made before the
    site retitled a lesson carries the old one."""
    from kotogen import memory

    volume = irodori.VOLUMES["irodori-shokyu1"]
    monkeypatch.setattr(memory.known(), "_sources", _deck(
        "いろどり 初級1 (A2) - 第1課",
        "いろどり 初級1 (A2) - 第2課 古い題 (00:12 → 00:45)"))
    lessons, done = irodori.lessons(volume, 1)
    assert lessons[0].rank == 3 and done == 2


def test_the_deck_does_not_confuse_two_volumes(monkeypatch):
    """The four volumes number their lessons from 1 to 18: it is the name of the
    volume, carried by the provenance, that tells them apart."""
    from kotogen import memory

    monkeypatch.setattr(memory.known(), "_sources", _deck(
        "いろどり 初級1 (A2) - 第1課 駅の近くに住んでいます"))
    for alias in ("irodori-nyumon", "irodori-shokyu2", "irodori-shochukyu"):
        lessons, done = irodori.lessons(irodori.VOLUMES[alias], 1)
        assert lessons[0].rank == 1 and done == 0


@pytest.mark.parametrize("trace, expected", [
    ("いろどり 初級1 (A2) - 第9課 この字はどう読みますか？ (00:12 → 00:45)",
     ("irodori-shokyu1", "9")),
    ("いろどり 初中級 (A2/B1) - 第5課 どこで食べましょうか？",
     ("irodori-shochukyu", "5")),
    ("いろどり 初級1 (A2) - 第3課", ("irodori-shokyu1", "3")),
    # A rank outside the textbook, an unknown volume, another source: nothing.
    ("いろどり 初級1 (A2) - 第99課 x", None),
    ("いろどり 初級1 (A2) - 第3課目", None),
    ("いろどり 上級 (C1) - 第1課 x", None),
    ("Nihongo con Teppei - Ep 700", None),
    ("", None),
])
def test_a_provenance_says_which_lesson_it_comes_from(trace, expected):
    assert irodori.recognise(trace) == expected


def test_what_recognise_returns_is_what_the_history_files():
    """The key and the identifier have to be the ones `mark_done` writes."""
    lesson = irodori.lessons(irodori.VOLUMES["irodori-shokyu2"], 1)[0][0]
    irodori.mark_done(lesson)
    assert irodori.recognise(irodori.provenance(lesson)) == \
        (lesson.alias, str(lesson.rank))
