"""Channel catalogue, Atom feed reading, probe and cache of YouTube videos.

No network and no yt-dlp: the feeds are written here and the probe is stubbed.
A channel can be added without code, the routing sends each URL to the right
module, and what is not a listening source is refused.
"""

from __future__ import annotations

import io
import json
import sys

import pytest

from kotogen.generators import download, podcast, youtube
from kotogen.jlpt import LEVELS


def atom_feed(entries: str, title: str = "My channel") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns="http://www.w3.org/2005/Atom">
  <title>{title}</title>
  {entries}
</feed>""".encode()


def entry(video_id: str = "abc12345678", title: str = "A video",
          published: str = "2026-08-21T09:00:00+00:00") -> str:
    return f"""<entry>
    <yt:videoId>{video_id}</yt:videoId>
    <title>{title}</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v={video_id}"/>
    <published>{published}</published>
  </entry>"""


@pytest.fixture
def empty_catalogue(tmp_path, monkeypatch):
    """Isolates the user's catalogue: the one on the machine is not read."""
    path = tmp_path / "channels.json"
    monkeypatch.setattr(youtube, "catalogue_file", lambda: path)
    return path


# -- Reading the feed ---------------------------------------------------------

def test_it_reads_a_complete_entry():
    name, videos = youtube.read_feed(atom_feed(entry()))
    assert name == "My channel"
    assert len(videos) == 1
    assert videos[0].id == "abc12345678"
    assert videos[0].title == "A video"
    assert videos[0].url == "https://www.youtube.com/watch?v=abc12345678"


def test_an_entry_with_no_identifier_is_not_a_video():
    # An announced live stream, a damaged entry: no identifier, nothing to probe.
    no_id = """<entry><title>Upcoming live</title></entry>"""
    with pytest.raises(ValueError, match="no video"):
        youtube.read_feed(atom_feed(no_id))


def test_it_sorts_from_the_newest_to_the_oldest():
    old = entry("aaaaaaaaaaa", "Old", "2026-08-01T09:00:00+00:00")
    new = entry("bbbbbbbbbbb", "New", "2026-08-20T09:00:00+00:00")
    _name, videos = youtube.read_feed(atom_feed(old + new))
    assert [v.title for v in videos] == ["New", "Old"]


def test_an_unreadable_feed_names_its_url():
    with pytest.raises(ValueError, match="unreadable"):
        youtube.read_feed(b"<not xml", "https://example.test/feed")


# -- The catalogue ------------------------------------------------------------

def test_the_built_in_channels_are_atom_feeds():
    for alias, channel in youtube.CHANNELS.items():
        assert alias == alias.lower(), "an alias is compared in lower case"
        assert channel.feed_url.startswith(
            "https://www.youtube.com/feeds/videos.xml?"), alias
        assert channel.name, alias


def test_the_built_in_channels_announce_a_level():
    # The level is how a channel is chosen before downloading a minute of it.
    for alias, channel in youtube.CHANNELS.items():
        assert channel.levels, alias
        assert set(channel.levels) <= set(LEVELS), alias


def test_no_built_in_channel_doubles_a_podcast():
    """One show must not be pickable in two menus.

    Teppei, Shun and Miku publish on both sides: listed twice, the same content
    would be paid for twice.
    """
    podcast_names = " ".join(p.name.lower() for p in podcast.PODCASTS.values())
    for alias, channel in youtube.CHANNELS.items():
        assert alias not in podcast.PODCASTS, alias
        # The proper name of the show, not the commonest word of its title.
        brand = channel.name.lower().split("(")[0].strip()
        assert brand not in podcast_names, alias


def test_the_user_file_adds_a_channel(empty_catalogue):
    empty_catalogue.write_text(json.dumps({
        "teacher": {"name": "My teacher", "feed": "UCaaaaaaaaaaaaaaaaaaaaaa",
                    "levels": "N4-N3"}
    }), encoding="utf-8")
    known = youtube.catalogue()
    assert known["teacher"].name == "My teacher"
    assert known["teacher"].feed_url.endswith("channel_id=UCaaaaaaaaaaaaaaaaaaaaaa")
    assert known["teacher"].levels == ("N4", "N3")


def test_a_user_file_saved_with_a_bom_is_read(empty_catalogue):
    """A BOM, as Notepad and PowerShell 5 write it, would lose the whole file."""
    empty_catalogue.write_text(json.dumps({
        "teacher": {"name": "My teacher", "feed": "UCaaaaaaaaaaaaaaaaaaaaaa"}
    }), encoding="utf-8-sig")
    assert "teacher" in youtube.catalogue()


def test_the_user_file_accepts_a_whole_url(empty_catalogue):
    url = "https://www.youtube.com/feeds/videos.xml?channel_id=UCbbbbbbbbbbbbbbbbbbbbbb"
    empty_catalogue.write_text(json.dumps({"teacher": {"feed": url}}), encoding="utf-8")
    assert youtube.catalogue()["teacher"].feed_url == url


def test_the_user_file_accepts_a_playlist_identifier(empty_catalogue):
    empty_catalogue.write_text(
        json.dumps({"course": {"feed": "PLzzzzzzzz"}}), encoding="utf-8")
    assert youtube.catalogue()["course"].feed_url.endswith("playlist_id=PLzzzzzzzz")


def test_the_user_file_wins_over_the_built_in_table(empty_catalogue):
    # A channel that changes identifier can be fixed locally, before a release.
    empty_catalogue.write_text(json.dumps({
        "onomappu": {"name": "Onomappu (fixed)", "feed": "UCnewnewnewnewnewnewnewn"}
    }), encoding="utf-8")
    assert youtube.catalogue()["onomappu"].name == "Onomappu (fixed)"


def test_a_damaged_user_catalogue_does_not_lose_the_built_in_table(empty_catalogue):
    empty_catalogue.write_text("{ not json", encoding="utf-8")
    assert "onomappu" in youtube.catalogue()


def test_an_entry_with_no_usable_feed_is_ignored(empty_catalogue):
    empty_catalogue.write_text(json.dumps({
        "empty": {"name": "No feed"},
        "odd": {"name": "Unknown identifier", "feed": "XYZ123"},
    }), encoding="utf-8")
    known = youtube.catalogue()
    assert "empty" not in known and "odd" not in known


def test_by_level_goes_from_the_simplest_to_the_hardest():
    labels = [level for level, _entries in youtube.by_level(youtube.CHANNELS)]
    assert labels[0].startswith("N5")
    assert labels[-1].endswith("N1")


# -- Recognising the inputs ---------------------------------------------------

@pytest.mark.parametrize("entry_, expected", [
    ("onomappu", True),
    ("ONOMAPPU", True),
    ("https://www.youtube.com/watch?v=abc12345678", True),
    ("https://youtu.be/abc12345678", True),
    ("https://m.youtube.com/watch?v=abc12345678", True),
    ("https://www.youtube.com/@a-channel", True),
    # An unknown word is NOT claimed: YouTube is routed first, and a mistyped
    # podcast alias would get the list of channels instead of shows.
    ("teppie", False),
    ("teppei", False),
    ("https://a-podcast.example/rss", False),
    ("", False),
])
def test_is_youtube_input(empty_catalogue, entry_, expected):
    assert youtube.is_youtube_input(entry_) is expected


def test_the_podcast_does_not_claim_what_belongs_to_youtube(empty_catalogue):
    """The routing order must not be the only safeguard.

    Without an explicit refusal, `is_podcast_input` would take a video address
    for a feed and a channel alias for a mistyped show alias.
    """
    assert podcast.is_podcast_input("https://www.youtube.com/watch?v=abc12345678") is False
    assert podcast.is_podcast_input("onomappu") is False
    assert podcast.is_podcast_input("https://a-podcast.example/rss") is True


# -- Resolving ----------------------------------------------------------------

def test_resolving_an_alias(empty_catalogue):
    source = youtube.resolve("onomappu")
    assert source.key == "onomappu"
    assert source.feed_url.endswith("channel_id=UCLuymDHiOySsAQ9Nc-4NoEQ")
    assert not source.video


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=abc12345678",
    "https://youtu.be/abc12345678",
    "https://www.youtube.com/shorts/abc12345678",
    "https://www.youtube.com/embed/abc12345678",
    "https://m.youtube.com/watch?v=abc12345678&t=42s",
])
def test_resolving_an_isolated_video(empty_catalogue, url):
    source = youtube.resolve(url)
    assert source.video == "abc12345678"
    assert not source.feed_url


def test_a_video_inside_a_playlist_stays_a_video(empty_catalogue):
    # The video is what the page showed when the link was copied, not the playlist.
    source = youtube.resolve(
        "https://www.youtube.com/watch?v=abc12345678&list=PLzzz")
    assert source.video == "abc12345678"


def test_resolving_a_playlist(empty_catalogue):
    source = youtube.resolve("https://www.youtube.com/playlist?list=PLzzz")
    assert source.feed_url.endswith("playlist_id=PLzzz")
    assert source.key.startswith("playlist-")


def test_a_catalogue_channel_pasted_as_a_url_finds_its_alias(empty_catalogue):
    """Otherwise one channel would have two histories and two caches."""
    source = youtube.resolve(
        "https://www.youtube.com/channel/UCLuymDHiOySsAQ9Nc-4NoEQ")
    assert source.key == "onomappu"


def test_two_channels_outside_the_catalogue_have_distinct_keys(empty_catalogue):
    one = youtube.resolve("https://www.youtube.com/channel/UCaaaaaaaaaaaaaaaaaaaaaa")
    two = youtube.resolve("https://www.youtube.com/channel/UCbbbbbbbbbbbbbbbbbbbbbb")
    assert one.key != two.key


def test_an_unknown_alias_lists_the_ones_that_exist(empty_catalogue):
    with pytest.raises(ValueError) as error:
        youtube.resolve("onomapu")
    message = str(error.value)
    assert "onomapu" in message
    assert "onomappu" in message
    assert "N3-N2" in message


def test_an_unrecognised_youtube_address_says_what_is_accepted(empty_catalogue):
    with pytest.raises(ValueError, match="not recognised"):
        youtube.resolve("https://www.youtube.com/results?search_query=x")


def _handle_in_the_user_file(catalogue_path) -> None:
    catalogue_path.write_text(json.dumps({
        "teacher": {"name": "My teacher", "feed": "https://www.youtube.com/@teacher"}
    }), encoding="utf-8")


def test_a_handle_in_the_user_file_is_read_off_its_page(empty_catalogue, monkeypatch):
    """Kept as the feed, the handle would hand back a web page, not an Atom feed.
    The page is read when the channel is used, not when the catalogue is: every
    routing reads the catalogue, offline included."""
    _handle_in_the_user_file(empty_catalogue)
    channel_id = "UC" + "h" * 22
    opened: list[str] = []

    def page(url, timeout, headers=None):
        opened.append(url)
        return io.BytesIO(f'{{"externalId":"{channel_id}"}}'.encode())

    monkeypatch.setattr(download, "open_url", page)

    assert youtube.is_youtube_input("teacher")
    assert opened == []

    source = youtube.resolve("teacher")
    assert source.key == "teacher"
    assert source.feed_url == youtube.CHANNEL_FEED.format(channel_id)
    assert opened == ["https://www.youtube.com/@teacher/videos"]


def test_the_button_to_look_for_is_quoted_by_the_language(empty_catalogue, monkeypatch):
    """The name of YouTube's button is a value inside the sentence: quoted the
    way the screen's language quotes, not with the English pair typed in."""
    monkeypatch.setattr(download, "open_url",
                        lambda url, timeout, headers=None: io.BytesIO(b"<html></html>"))
    monkeypatch.setattr(youtube, "quoted", lambda name: f"<{name}>")
    with pytest.raises(ValueError, match="<Share channel>"):
        youtube.resolve("https://www.youtube.com/@teacher")


def test_a_handle_that_cannot_be_read_refuses_its_channel(empty_catalogue, monkeypatch):
    """With the reason, rather than a feed that fails further on."""
    _handle_in_the_user_file(empty_catalogue)

    def offline(url, timeout, headers=None):
        raise OSError("no route to host")

    monkeypatch.setattr(download, "open_url", offline)

    with pytest.raises(ValueError, match="unreadable channel.*@teacher"):
        youtube.resolve("teacher")


def test_a_feed_that_never_ends_is_refused(empty_catalogue, monkeypatch):
    class Endless(io.RawIOBase):
        def read(self, size=-1):
            assert size > 0, "read whole, it would never return"
            return b"x" * size

    monkeypatch.setattr(download, "MAX_FEED", 1024)
    monkeypatch.setattr(download, "open_url", lambda url, timeout, headers=None: Endless())
    with pytest.raises(ValueError, match="outsized answer"):
        youtube.fetch_feed(youtube.resolve("onomappu"))


# -- The candidates -----------------------------------------------------------

def _stub_feed(monkeypatch, entries: str) -> None:
    monkeypatch.setattr(youtube, "fetch_feed",
                        lambda source: youtube.read_feed(atom_feed(entries)))


def test_candidates_returns_everything_that_is_left(monkeypatch, empty_catalogue):
    """And not the count asked for: a video is judged only once probed, and the
    latest upload may be a Short."""
    _stub_feed(monkeypatch, "".join(
        entry(f"video{n:06d}", f"N{n}", f"2026-08-{n:02d}T09:00:00+00:00")
        for n in (1, 2, 3)))
    monkeypatch.setattr("kotogen.seen.load", lambda mode, source: {})
    _name, videos, _skipped = youtube.candidates(youtube.resolve("onomappu"))
    assert len(videos) == 3


def test_candidates_skips_what_is_already_handled(monkeypatch, empty_catalogue, capsys):
    _stub_feed(monkeypatch, entry("aaaaaaaaaaa") + entry("bbbbbbbbbbb"))
    monkeypatch.setattr("kotogen.seen.load",
                        lambda mode, source: {"aaaaaaaaaaa": "already seen"})
    _name, videos, skipped = youtube.candidates(youtube.resolve("onomappu"))
    assert [v.id for v in videos] == ["bbbbbbbbbbb"]
    # The count is returned, not said: it is the source announcement that carries it.
    assert skipped == 1
    assert capsys.readouterr().out == ""


def test_a_video_already_in_the_deck_is_skipped(monkeypatch, empty_catalogue):
    """Matched by the ID in the short address, not by the label: a retitled
    video must not be paid for again."""
    from kotogen import memory
    from kotogen.known import Sources as DeckSources

    _stub_feed(monkeypatch, entry("aaaaaaaaaaa") + entry("bbbbbbbbbbb"))
    monkeypatch.setattr("kotogen.seen.load", lambda mode, source: {})
    monkeypatch.setattr(memory.known(), "_sources", DeckSources({
        "audio": frozenset({"Onomappu - another title (00:12 → 00:45) "
                            "https://youtu.be/aaaaaaaaaaa"})}))
    _name, videos, skipped = youtube.candidates(youtube.resolve("onomappu"))
    assert [v.id for v in videos] == ["bbbbbbbbbbb"] and skipped == 1


def test_an_isolated_video_ignores_the_history(monkeypatch, empty_catalogue):
    # An address pasted by hand is wanted: skipping it would leave no way to redo it.
    monkeypatch.setattr("kotogen.seen.load",
                        lambda mode, source: {"abc12345678": "already seen"})
    source = youtube.resolve("https://youtu.be/abc12345678")
    _name, videos, _skipped = youtube.candidates(source)
    assert [v.id for v in videos] == ["abc12345678"]


# -- The probe ----------------------------------------------------------------

def _probed(title="A video !", identifier="abc12345678", duration=600.0,
            subtitle=True, language="") -> youtube.ProbedVideo:
    return youtube.ProbedVideo(id=identifier, title=title, duration=duration,
                               ja_subtitle=subtitle, language=language)


@pytest.mark.parametrize("language, japanese", [
    ("", True),         # nothing declared: the doubt goes to the video
    ("ja", True),
    ("ja-JP", True),
    ("en-US", False),   # the Ask Japanese case: manual `ja` track, English sound
    ("ko", False),
])
def test_the_language_of_the_sound_is_read_off_what_youtube_declares(language,
                                                                    japanese):
    assert youtube.japanese_sound(_probed(language=language)) is japanese


# -- File names and cache -----------------------------------------------------


def test_a_readable_and_unique_stem(empty_catalogue):
    stem = youtube._stem(youtube.resolve("onomappu"), _probed())
    assert stem.startswith("onomappu_")
    assert stem.endswith("_abc12345678")
    assert " " not in stem and "!" not in stem


def test_a_stem_with_no_title_stays_valid(empty_catalogue):
    stem = youtube._stem(youtube.resolve("onomappu"), _probed(title=""))
    assert stem == "onomappu_abc12345678"


def test_the_cleanup_keeps_the_newest_ones(tmp_path, monkeypatch, empty_catalogue):
    monkeypatch.setattr("kotogen.system.cache_dir", lambda: tmp_path)
    folder = tmp_path / "youtube" / "onomappu"
    folder.mkdir(parents=True)
    for n in range(5):
        media = folder / f"v{n}.mp3"
        media.write_bytes(b"x")
        # The subtitle goes with its medium: kept alone it would serve nothing.
        (folder / f"v{n}.ja.vtt").write_text("WEBVTT", encoding="utf-8")
        import os
        os.utime(media, (1000 + n, 1000 + n))

    youtube.cleanup(youtube.resolve("onomappu"), keep=2)
    left = sorted(f.name for f in folder.iterdir())
    assert left == ["v3.ja.vtt", "v3.mp3", "v4.ja.vtt", "v4.mp3"]


def test_the_cleanup_on_a_missing_folder_does_not_break(tmp_path, monkeypatch,
                                                        empty_catalogue):
    monkeypatch.setattr("kotogen.system.cache_dir", lambda: tmp_path)
    youtube.cleanup(youtube.resolve("onomappu"))


# -- The label (Source field of the cards) ------------------------------------

def test_the_label_carries_the_channel_and_the_video(empty_catalogue):
    source = youtube.resolve("onomappu")
    assert youtube.provenance(source, _probed()) == "Onomappu - A video !"


def test_a_label_with_no_title_falls_back_on_the_identifier(empty_catalogue):
    source = youtube.resolve("onomappu")
    assert youtube.provenance(source, _probed(title="")) == "Onomappu - abc12345678"


def test_the_link_reopens_the_video_at_the_second_the_passage_starts(empty_catalogue):
    source = youtube.resolve("onomappu")
    assert youtube.link(source, _probed(), 192.7) == "https://youtu.be/abc12345678?t=192"


def test_no_timestamp_in_the_link_when_the_passage_opens_the_video(empty_catalogue):
    """`?t=0` would say nothing more: the video opens there anyway."""
    source = youtube.resolve("onomappu")
    assert youtube.link(source, _probed()) == "https://youtu.be/abc12345678"


def test_a_podcast_episode_points_nowhere():
    """Its `enclosure` is the mp3 the card already carries: clicking on it would
    download it again instead of showing anything."""
    channel = podcast.Feed("teppei", "Teppei", "https://example.jp/rss")
    episode = podcast.Episode("g1", "#123", "https://example.jp/123.mp3",
                              "2026-08-20", 300.0)
    assert podcast.link(channel, episode, 42.0) == ""


def test_both_distant_sources_expose_the_same_interface():
    """`audio.run_audio` calls these names without knowing which module it holds:
    a divergence would only show at run time."""
    for name in ("cache_folder", "provenance", "link", "mark_done", "cleanup"):
        assert callable(getattr(podcast, name)), name
        assert callable(getattr(youtube, name)), name


# -- Sorting the candidates (audio._youtube_videos) ---------------------------

@pytest.fixture
def run(monkeypatch, empty_catalogue, tmp_path):
    """A stubbed YouTube pass: no network, no yt-dlp, no disk.

    Returns a function that serves the given probe results and returns the ids
    downloaded, to test the sorting in `audio._youtube_videos`.
    """
    from kotogen.generators import audio

    def launch(probes: list[youtube.ProbedVideo], count: int = 1, **kwargs):
        videos = [youtube.Video(id=p.id, title=p.title, published="") for p in probes]
        by_id = {p.id: p for p in probes}
        monkeypatch.setattr(youtube, "candidates",
                            lambda source, **_: ("My channel", videos, 0))
        monkeypatch.setattr(youtube, "probe", lambda video: by_id[video.id])
        monkeypatch.setattr(youtube, "fetch",
                            lambda source, probed, **_: tmp_path / f"{probed.id}.mp3")
        taken = audio._youtube_videos(["onomappu"], count, image=False, **kwargs)
        return [probed.id for _path, _source, probed in taken]

    return launch


def test_the_shorts_are_discarded(run, capsys):
    """A channel feed mixes videos and Shorts without telling them apart."""
    taken = run([_probed("A Short", "short000000", duration=46.0),
                 _probed("A video", "video000000", duration=780.0)])
    assert taken == ["video000000"]
    assert "too short" in capsys.readouterr().out


def test_a_video_that_does_not_speak_japanese_is_discarded(run, capsys):
    """The manual track does not prove the language of the sound: it can be a
    translation."""
    taken = run([_probed("Translated", "translated0", duration=900.0,
                         subtitle=True, language="en-US"),
                 _probed("Japanese", "japanese000", duration=900.0,
                         subtitle=True, language="ja")])
    assert taken == ["japanese000"]
    assert "not in Japanese" in capsys.readouterr().out


def test_the_count_bears_on_the_videos_kept(run):
    """A channel that just published a Short still gives its latest video: the
    candidates are walked down, not truncated in advance."""
    taken = run([_probed("Short 1", "shortaaaaaa", duration=30.0),
                 _probed("Short 2", "shortbbbbbb", duration=50.0),
                 _probed("The video", "videoaaaaaa", duration=600.0)], count=1)
    assert taken == ["videoaaaaaa"]


def test_max_video_discards_before_the_download(run, capsys):
    taken = run([_probed("Too long", "longue00000", duration=3600.0),
                 _probed("Good size", "courte00000", duration=600.0)],
                limit=900)
    assert taken == ["courte00000"]
    assert "longer than" in capsys.readouterr().out


def test_it_stops_once_the_count_is_reached(run):
    taken = run([_probed("A", "aaaaaaaaaaa", duration=600.0),
                 _probed("B", "bbbbbbbbbbb", duration=600.0),
                 _probed("C", "ccccccccccc", duration=600.0)], count=2)
    assert taken == ["aaaaaaaaaaa", "bbbbbbbbbbb"]


def test_a_transcription_already_done_is_announced_before_the_download(run, capsys):
    """It is the only piece of information from the probe that changes what the
    run will cost: learning it after Whisper would serve nothing."""
    run([_probed("Subtitled", "avecst00000", duration=600.0, subtitle=True)])
    assert "Japanese subtitles provided" in capsys.readouterr().out


def test_with_no_manual_track_the_transcription_is_announced_as_to_be_done(run,
                                                                          capsys):
    run([_probed("Bare", "sansst00000", duration=600.0, subtitle=False)])
    assert "transcription to be done" in capsys.readouterr().out


def test_a_video_with_no_known_duration_gets_through(run):
    """An unknown duration does not discard the video: missing information is
    not a verdict."""
    assert run([_probed("Unknown duration", "inconnu0000", duration=None)]) \
        == ["inconnu0000"]


def test_the_cache_tells_the_sound_alone_from_the_video(tmp_path):
    """Sound alone and video share a stem, not an extension: confused, a
    `--video` run would silently reuse the mp3 and make cards with no picture."""
    (tmp_path / "stem.mp3").write_bytes(b"x")
    assert youtube._media_on_disk(tmp_path, "stem", image=False).suffix == ".mp3"
    assert youtube._media_on_disk(tmp_path, "stem", image=True) is None

    (tmp_path / "stem.mp4").write_bytes(b"x")
    assert youtube._media_on_disk(tmp_path, "stem", image=True).suffix == ".mp4"
    assert youtube._media_on_disk(tmp_path, "stem", image=False).suffix == ".mp3"


def test_an_empty_medium_does_not_count_as_downloaded(tmp_path):
    # A download cut off mid-way would otherwise leave a file the next pass would
    # take for the good one.
    (tmp_path / "stem.mp3").write_bytes(b"")
    assert youtube._media_on_disk(tmp_path, "stem", image=False) is None


def test_a_missing_yt_dlp_names_the_extra_as_zsh_takes_it(monkeypatch):
    """The install is from a clone, and macOS's shell refuses bare brackets."""
    monkeypatch.setitem(sys.modules, "yt_dlp", None)
    with pytest.raises(SystemExit) as raised:
        youtube._yt_dlp()
    assert 'pip install -e ".[youtube]"' in str(raised.value)
    assert "kotogen folder" in str(raised.value)
