"""Reading a podcast feed, the alias catalogue and the episode cache.

No network: the feeds are byte strings written here. The tests guard adding a
show without touching the code, and the variety of real feeds across hosts.
"""

from __future__ import annotations

import json

import pytest

from kotogen.generators import download, levels, podcast
from kotogen.jlpt import LEVELS


def rss_feed(items: str, title: str = "My podcast") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>{title}</title>
    {items}
  </channel>
</rss>""".encode()


ITEM = """<item>
  <title>Episode 1</title>
  <guid>guid-1</guid>
  <pubDate>Mon, 17 Aug 2026 11:28:51 +0000</pubDate>
  <itunes:duration>13:43</itunes:duration>
  <enclosure url="https://example.test/ep1.mp3" type="audio/mpeg" length="1"/>
</item>"""


# -- Reading the feed ---------------------------------------------------------

def test_it_reads_a_complete_item():
    name, episodes = podcast.read_feed(rss_feed(ITEM))
    assert name == "My podcast"
    assert len(episodes) == 1
    episode = episodes[0]
    assert episode.guid == "guid-1"
    assert episode.title == "Episode 1"
    assert episode.url == "https://example.test/ep1.mp3"
    assert episode.duration == 823.0


def test_a_missing_guid_falls_back_on_the_url_of_the_file():
    # The history needs a stable identifier, and the file URL is always there.
    item = """<item>
      <title>No guid</title>
      <enclosure url="https://example.test/ep9.mp3" type="audio/mpeg"/>
    </item>"""
    _name, episodes = podcast.read_feed(rss_feed(item))
    assert episodes[0].guid == "https://example.test/ep9.mp3"


def test_an_item_with_no_audio_file_is_not_an_episode():
    item = """<item><title>Show note</title></item>"""
    with pytest.raises(ValueError, match="no audio episode"):
        podcast.read_feed(rss_feed(item))


def test_an_enclosure_off_the_web_is_not_an_episode():
    """The feed is someone else's, and `urllib` opens a `file://` like a page: it
    would copy a local file into the cache."""
    item = """<item>
      <title>Local</title><guid>g</guid>
      <enclosure url="file:///etc/passwd" type="audio/mpeg"/>
    </item>"""
    with pytest.raises(ValueError, match="no audio episode"):
        podcast.read_feed(rss_feed(item))


def test_it_picks_the_audio_enclosure_among_several():
    item = """<item>
      <title>Two attachments</title>
      <guid>g</guid>
      <enclosure url="https://example.test/ep.pdf" type="application/pdf"/>
      <enclosure url="https://example.test/ep.mp3" type="audio/mpeg"/>
    </item>"""
    _name, episodes = podcast.read_feed(rss_feed(item))
    assert episodes[0].url == "https://example.test/ep.mp3"


def test_it_accepts_an_enclosure_with_no_type_but_an_audio_extension():
    item = """<item>
      <title>Missing type</title><guid>g</guid>
      <enclosure url="https://example.test/ep.m4a"/>
    </item>"""
    _name, episodes = podcast.read_feed(rss_feed(item))
    assert episodes[0].url == "https://example.test/ep.m4a"


def test_a_url_with_parameters_is_still_recognised_by_its_extension():
    # The hosts stick a long tracking tail behind the file.
    item = """<item>
      <title>Tracking</title><guid>g</guid>
      <enclosure url="https://example.test/ep.mp3?source=rss&amp;id=42"/>
    </item>"""
    _name, episodes = podcast.read_feed(rss_feed(item))
    assert episodes[0].url.startswith("https://example.test/ep.mp3?")


def test_an_unreadable_feed_names_its_url():
    with pytest.raises(ValueError, match="unreadable RSS feed: https://example.test/rss"):
        podcast.read_feed(b"<rss><channel", "https://example.test/rss")


def test_a_web_page_is_not_a_feed():
    # The most likely mistake: pasting the address of the site instead of the RSS.
    page = b"<html><body><h1>My podcast</h1></body></html>"
    with pytest.raises(ValueError, match="no audio episode"):
        podcast.read_feed(page, "https://example.test/")


# -- Order of the episodes ----------------------------------------------------

def _item(guid: str, date: str) -> str:
    return f"""<item><title>{guid}</title><guid>{guid}</guid>
      <pubDate>{date}</pubDate>
      <enclosure url="https://example.test/{guid}.mp3" type="audio/mpeg"/></item>"""


def test_it_sorts_from_the_newest_to_the_oldest():
    feed = rss_feed(_item("old", "Mon, 10 Aug 2026 10:00:00 +0000")
                    + _item("new", "Mon, 17 Aug 2026 10:00:00 +0000"))
    _name, episodes = podcast.read_feed(feed)
    assert [e.guid for e in episodes] == ["new", "old"]


def test_it_keeps_the_order_of_the_feed_if_a_date_is_missing():
    # Sorting on half-absent dates would do worse than not sorting at all.
    feed = rss_feed(_item("first", "")
                    + _item("second", "Mon, 17 Aug 2026 10:00:00 +0000"))
    _name, episodes = podcast.read_feed(feed)
    assert [e.guid for e in episodes] == ["first", "second"]


# -- Announced duration -------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("823", 823.0),
    ("13:43", 823.0),
    ("1:02:03", 3723.0),
    ("", None),
    (None, None),
    ("soon", None),
])
def test_the_itunes_duration(text, expected):
    assert podcast._duration(text) == expected


# -- Catalogue ----------------------------------------------------------------

@pytest.fixture
def empty_catalogue(tmp_path, monkeypatch):
    """Isolates the user's catalogue: the one on the machine is not read."""
    path = tmp_path / "podcasts.json"
    monkeypatch.setattr(podcast, "catalogue_file", lambda: path)
    return path


def test_the_built_in_aliases_are_feed_urls():
    for alias, entry in podcast.PODCASTS.items():
        assert alias == alias.lower(), "an alias is compared in lower case"
        assert entry.feed_url.startswith("https://"), alias
        assert entry.name, alias


def test_the_built_in_aliases_announce_a_level():
    # A level-less alias goes last in the menu: fine for a user entry, not here.
    for alias, entry in podcast.PODCASTS.items():
        assert entry.levels, alias
        assert levels.ordered(entry.levels) == entry.levels, (
            f"{alias}: the levels are written from the simplest to the hardest")


def test_the_user_file_adds_an_alias(empty_catalogue):
    empty_catalogue.write_text(json.dumps(
        {"my-teacher": {"name": "My teacher",
                        "feed": "https://example.test/teacher.xml"}}),
        encoding="utf-8")
    known = podcast.catalogue()
    assert known["my-teacher"].feed_url == "https://example.test/teacher.xml"
    assert "teppei" in known, "the built-in table stays there"


def test_a_user_file_saved_with_a_bom_is_read(empty_catalogue):
    """Notepad's "UTF-8 with BOM" and PowerShell 5 open the file on a BOM, which
    `json.loads` refuses: the whole file would be ignored without a word."""
    empty_catalogue.write_text(json.dumps(
        {"mine": {"name": "Mine", "feed": "https://example.test/rss"}}),
        encoding="utf-8-sig")
    assert "mine" in podcast.catalogue()


def test_the_user_file_wins_over_the_built_in_table(empty_catalogue):
    # A podcast that moves can be fixed in the user's file.
    empty_catalogue.write_text(json.dumps(
        {"teppei": {"name": "Teppei", "feed": "https://example.test/new.xml"}}),
        encoding="utf-8")
    assert podcast.catalogue()["teppei"].feed_url == "https://example.test/new.xml"


@pytest.mark.parametrize("content", ['{"broken":', '[]', '{"x": "not an object"}',
                                     '{"x": {"name": "no feed"}}'])
def test_a_damaged_user_catalogue_does_not_lose_the_built_in_table(
        empty_catalogue, content):
    empty_catalogue.write_text(content, encoding="utf-8")
    assert "teppei" in podcast.catalogue()


# -- Levels -------------------------------------------------------------------

@pytest.mark.parametrize("written, expected", [
    (["N4", "N3"], ("N4", "N3")),
    (["N3", "N4"], ("N4", "N3")),      # filed from the simplest to the hardest
    ("N4-N3", ("N4", "N3")),
    ("n4, n3", ("N4", "N3")),
    ("N4", ("N4",)),
    (["N4", "N4"], ("N4",)),           # a duplicate does not make two levels
    (["N4", "N7"], ("N4",)),           # what does not exist goes, the rest lives
    ("beginner", ()),
    (None, ()),
    (42, ()),
])
def test_levels_written_by_hand(written, expected):
    assert levels.written(written) == expected


@pytest.mark.parametrize("given, expected", [
    (("N4",), "N4"),
    (("N5", "N4"), "N5-N4"),
    (("N5", "N4", "N3"), "N5-N3"),     # the bounds only
    ((), ""),
])
def test_the_level_label(given, expected):
    assert levels.label(given) == expected


def test_the_user_file_declares_a_level(empty_catalogue):
    empty_catalogue.write_text(json.dumps(
        {"my-teacher": {"name": "My teacher",
                        "feed": "https://example.test/teacher.xml",
                        "levels": "N4-N3"}}), encoding="utf-8")
    assert podcast.catalogue()["my-teacher"].levels == ("N4", "N3")


def test_a_podcast_with_no_level_stays_usable(empty_catalogue):
    empty_catalogue.write_text(json.dumps(
        {"my-teacher": {"name": "My teacher",
                        "feed": "https://example.test/teacher.xml"}}),
        encoding="utf-8")
    known = podcast.catalogue()
    assert known["my-teacher"].levels == ()
    last, entries = podcast.by_level(known)[-1]
    assert last == "", "the unclassified ones bring up the rear"
    assert [alias for alias, _entry in entries] == ["my-teacher"]


def test_by_level_goes_from_the_simplest_to_the_hardest():
    labels = [level for level, _entries in podcast.by_level(podcast.PODCASTS)]
    assert labels[0].startswith("N5")
    assert labels[-1] == "N1"
    firsts = [LEVELS.index(e.split("-")[0]) for e in labels]
    assert firsts == sorted(firsts)


def test_by_level_quotes_a_show_only_once():
    # Filed under each of its levels, a show with a range would be pickable twice
    # in the same menu.
    known = {
        "wide": podcast.Podcast("Wide", "https://x.test/a", ("N5", "N4", "N3")),
        "narrow": podcast.Podcast("Narrow", "https://x.test/b", ("N4",)),
    }
    groups = podcast.by_level(known)
    assert [(level, [alias for alias, _entry in entries])
            for level, entries in groups] == [("N5-N3", ["wide"]), ("N4", ["narrow"])]


def test_two_shows_of_the_same_range_share_their_group():
    known = {
        "a": podcast.Podcast("A", "https://x.test/a", ("N3", "N2")),
        "b": podcast.Podcast("B", "https://x.test/b", ("N3", "N2")),
    }
    assert podcast.by_level(known) == [
        ("N3-N2", [("a", known["a"]), ("b", known["b"])])]


# -- Resolving ----------------------------------------------------------------

def test_resolving_an_alias(empty_catalogue):
    channel = podcast.resolve("Teppei")  # case does not count
    assert channel.key == "teppei"
    assert channel.url == podcast.PODCASTS["teppei"].feed_url


def test_resolving_a_url_with_no_alias(empty_catalogue):
    channel = podcast.resolve("https://example.test/rss")
    assert channel.url == "https://example.test/rss"
    assert "example-test" in channel.key


def test_two_feeds_of_the_same_host_have_distinct_keys(empty_catalogue):
    # Otherwise two shows of one host would share their history.
    a = podcast.resolve("https://anchor.fm/s/aaa/podcast/rss")
    b = podcast.resolve("https://anchor.fm/s/bbb/podcast/rss")
    assert a.key != b.key


def test_an_unknown_alias_lists_the_ones_that_exist(empty_catalogue):
    with pytest.raises(ValueError, match="teppei"):
        podcast.resolve("podcast-that-does-not-exist")


def test_a_catalogued_show_pasted_as_its_feed_keeps_its_alias(empty_catalogue):
    """Otherwise one show would have two histories, two caches, and cards named
    after the host of its feed."""
    show = podcast.PODCASTS["teppei"]
    pasted = podcast.resolve(show.feed_url.rstrip("/"))
    assert (pasted.key, pasted.name) == ("teppei", show.name)


def test_the_levels_of_the_aliases_line_up_in_screen_columns(empty_catalogue,
                                                             monkeypatch):
    """A kanji takes two columns where `len` counts one: a translated label is
    aligned on what the screen shows."""
    empty_catalogue.write_text(json.dumps(
        {"mine": {"name": "Mine", "feed": "https://example.test/rss"}}),
        encoding="utf-8")
    monkeypatch.setattr(levels, "_", lambda text: "不明")
    with pytest.raises(ValueError) as error:
        podcast.resolve("podcast-that-does-not-exist")
    lines = str(error.value).splitlines()
    unstated = next(line for line in lines if "mine" in line)
    assert unstated.startswith("    不明: ")
    assert any(line.startswith("      N1: ") for line in lines)


# -- Recognising the inputs ---------------------------------------------------

@pytest.mark.parametrize("entry, expected", [
    ("teppei", True),
    ("TEPPEI", True),
    ("https://example.test/rss", True),
    ("https://news.web.nhk/news/easy/ne2026/ne2026.html", False),  # NHK keeps its route
    ("nhk", False),          # the keyword too, and it is a lone word like an alias
    # NHK's bulletin feed is a podcast: only the path tells it from NHK Easy.
    ("https://www.nhk.or.jp/s-media/news/podcast/list/v1/all.xml", True),
    ("nhk-radio", True),     # the same one, by its alias
    ("K23_01.mp3", False),   # a missing file stays a missing file
    ("./my_audios", False),
    ("", False),
])
def test_is_podcast_input(empty_catalogue, entry, expected):
    assert podcast.is_podcast_input(entry) is expected


def test_a_mistyped_alias_stays_a_podcast(empty_catalogue):
    """Taken for a file, "teppie" would end on "File not found", without the
    list of aliases."""
    assert podcast.is_podcast_input("teppie") is True
    with pytest.raises(ValueError, match="Known aliases"):
        podcast.resolve("teppie")


def test_a_file_that_exists_is_not_an_alias(empty_catalogue, tmp_path, monkeypatch):
    # An audio file with no extension stays a file.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "teachers_podcast").write_bytes(b"")
    assert podcast.is_podcast_input("teachers_podcast") is False


# -- One precise episode ------------------------------------------------------

@pytest.mark.parametrize("title, expected", [
    ("#512「夏休みの思い出→秋」", 512),
    ("318. 天気 Weather", 318),
    ("【N4-N3】Ep87 Let's go shopping!!", 87),
    ("episode96「はじめての料理(N4)」", 96),
    ("No 141 - Learning To Rest On Sundays", 141),
    # A leading number that is not the episode's: none, and the rank takes over.
    ("5％ Better every morning", None),
    ("【12-3】第4回江戸の町と商人たち", None),
    ("Why rainy days are good", None),
    ("", None),
])
def test_the_announced_number(title, expected):
    assert podcast.announced_number(title) == expected


def _numbered_feed(monkeypatch, titles: list[str]) -> podcast.Feed:
    """A feed returned from the newest to the oldest, with no network."""
    episodes = [podcast.Episode(guid=f"g{n}", title=title,
                                url=f"https://example.test/{n}.mp3",
                                published="", duration=None)
                for n, title in enumerate(titles)]
    monkeypatch.setattr(podcast, "fetch_feed",
                        lambda channel: ("My podcast", episodes))
    return podcast.Feed("my-podcast", "My podcast", "https://example.test/rss")


def test_the_number_of_the_title_wins_over_the_rank(monkeypatch):
    # A special among the numbered episodes: no. 3 is the one that says so, not
    # the third from the end, which is the special.
    channel = _numbered_feed(monkeypatch, ["#5 five", "#4 four", "#3 three", "Special",
                                           "#2 two", "#1 one"])
    _name, episodes = podcast.from_number(channel, 3)
    assert [e.title for e in episodes] == ["#3 three"]


def test_with_no_numbered_title_no_1_is_the_oldest(monkeypatch):
    channel = _numbered_feed(monkeypatch, ["Four", "Three", "Two", "One"])
    assert [e.title for e in podcast.from_number(channel, 1)[1]] == ["One"]
    assert [e.title for e in podcast.from_number(channel, 4)[1]] == ["Four"]


def test_a_number_carried_twice_falls_back_on_the_rank(monkeypatch):
    # A number carried twice is ambiguous; the rank always names one episode.
    channel = _numbered_feed(monkeypatch, ["#2 two", "#2 two (repeat)", "#1 one"])
    assert [e.title for e in podcast.from_number(channel, 2)[1]] == ["#2 two (repeat)"]


def test_several_episodes_in_a_row_go_towards_the_recent_ones(monkeypatch):
    channel = _numbered_feed(monkeypatch, ["#5 five", "#4 four", "#3 three",
                                           "#2 two", "#1 one"])
    _name, episodes = podcast.from_number(channel, 2, 3)
    assert [e.title for e in episodes] == ["#2 two", "#3 three", "#4 four"]


def test_the_run_stops_at_the_last_episode(monkeypatch):
    channel = _numbered_feed(monkeypatch, ["#3 three", "#2 two", "#1 one"])
    _name, episodes = podcast.from_number(channel, 2, 5)
    assert [e.title for e in episodes] == ["#2 two", "#3 three"]


def test_a_number_outside_the_feed_says_so_with_the_count(monkeypatch):
    channel = _numbered_feed(monkeypatch, ["Two", "One"])
    with pytest.raises(ValueError, match="2 episode"):
        podcast.from_number(channel, 9)


def test_a_zero_number_is_refused(monkeypatch):
    channel = _numbered_feed(monkeypatch, ["Two", "One"])
    with pytest.raises(ValueError, match="from 1 on"):
        podcast.from_number(channel, 0)


def test_a_number_asked_for_ignores_the_history(monkeypatch):
    """`latest` skips the history; a number typed by hand does not, so one
    episode can be made again."""
    channel = _numbered_feed(monkeypatch, ["Two", "One"])
    monkeypatch.setattr(podcast.seen, "load", lambda mode, source: {"g0": "Two",
                                                                   "g1": "One"})
    assert podcast.latest(channel, 1)[1] == []
    assert [e.title for e in podcast.from_number(channel, 2)[1]] == ["Two"]


def test_an_episode_already_in_the_deck_is_skipped(monkeypatch):
    """The deck holds an episode's label, not its `guid`: the label is enough."""
    from kotogen import memory
    from kotogen.known import Sources as DeckSources

    channel = _numbered_feed(monkeypatch, ["Two", "One"])
    monkeypatch.setattr(memory.known(), "_sources", DeckSources({
        "audio": frozenset({"My podcast - Two (00:12 → 00:45)"})}))
    _name, episodes, skipped = podcast.latest(channel, 2)
    assert [e.title for e in episodes] == ["One"] and skipped == 1


# -- File name and cache ------------------------------------------------------

def _channel() -> podcast.Feed:
    return podcast.Feed("teppei", "Teppei", "https://example.test/rss")


def test_a_readable_and_unique_file_name():
    ep = podcast.Episode("guid-1", "#318「駅前のパン屋さん」", "https://x.test/a.mp3",
                         "", None)
    name = podcast._file_name(_channel(), ep)
    assert name.startswith("teppei_")
    assert name.endswith(".mp3")
    # Two episodes of the same title stay two files: the guid tells them apart.
    other = podcast.Episode("guid-2", ep.title, ep.url, "", None)
    assert podcast._file_name(_channel(), other) != name


def test_a_file_name_with_no_title_stays_valid():
    ep = podcast.Episode("guid-1", "", "https://x.test/a.mp3", "", None)
    name = podcast._file_name(_channel(), ep)
    assert name.startswith("teppei_") and name.endswith(".mp3")


class _Endless:
    """A server that never stops sending, read block by block."""

    headers: dict[str, str] = {}

    def __init__(self) -> None:
        self.sent = 0

    def read(self, size: int = -1) -> bytes:
        assert size > 0, "read whole, it would never return"
        self.sent += size
        assert self.sent < 8 * 1024 * 1024, "the reading never stopped"
        return b"x" * size

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_a_feed_that_never_ends_is_refused(monkeypatch):
    monkeypatch.setattr(download, "MAX_FEED", 1024)
    monkeypatch.setattr(download, "open_url", lambda url, timeout, headers=None: _Endless())
    with pytest.raises(ValueError, match="outsized answer"):
        podcast.fetch_feed(_channel())


def test_an_episode_that_never_ends_stops_and_leaves_nothing(tmp_path, monkeypatch):
    """A cut or endless download must not pass for the episode next time."""
    from kotogen import system

    monkeypatch.setattr(system, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(podcast, "MAX_EPISODE", 1024 * 1024)
    monkeypatch.setattr(download, "open_url", lambda url, timeout, headers=None: _Endless())
    episode = podcast.Episode("g", "T", "https://x.test/a.mp3", "", None)

    with pytest.raises(RuntimeError, match="outsized file"):
        podcast.fetch(_channel(), episode)
    assert list(podcast.cache_folder(_channel()).iterdir()) == []


def test_an_unknown_extension_falls_back_on_mp3():
    ep = podcast.Episode("g", "T", "https://x.test/feed?id=42", "", None)
    assert podcast._file_name(_channel(), ep).endswith(".mp3")


def test_the_cleanup_keeps_the_newest_ones(tmp_path, monkeypatch):
    from kotogen import system
    from kotogen.generators.whisper import _cache_key

    monkeypatch.setattr(system, "cache_dir", lambda: tmp_path)
    channel = _channel()
    folder = podcast.cache_folder(channel)

    audios = []
    for n in range(5):
        audio = folder / f"ep{n}.mp3"
        audio.write_bytes(b"x")
        # Increasing mtime: ep4 is the newest.
        import os
        os.utime(audio, (1_700_000_000 + n, 1_700_000_000 + n))
        (folder / _cache_key(audio)).write_text("[]", encoding="utf-8")
        audios.append(audio)

    podcast.cleanup(channel, keep=2)

    left = sorted(f.name for f in folder.glob("*.mp3"))
    assert left == ["ep3.mp3", "ep4.mp3"]
    # The transcription goes with its audio.
    assert not (folder / _cache_key(audios[0])).exists()
    assert (folder / _cache_key(audios[4])).exists()


def test_the_cleanup_on_a_missing_folder_does_not_break(tmp_path, monkeypatch):
    from kotogen import system
    monkeypatch.setattr(system, "cache_dir", lambda: tmp_path)
    podcast.cleanup(podcast.Feed("never-seen", "X", "https://x.test/rss"))
