"""The listening questions - NHK, podcasts, YouTube, local files - down to the
argv they build."""

import pytest

from kotogen import video_clip
from kotogen.generators import podcast, youtube
from kotogen.interactive import interactive_argv
from menus import *  # the fixtures every menu test starts from, and its helpers

# ── audio ─────────────────────────────────────────────────────────────────────

def test_audio_nhk_defaults(monkeypatch):
    # source nhk (default); the latest articles (default); 4 articles (default);
    # no max duration (default); cards by default; no send
    feed(monkeypatch, ["4", "", "", "", "", "", ""])
    assert interactive_argv() == ["audio", "nhk"]


def test_audio_nhk_max_duration(monkeypatch):
    """The max duration is asked, and Enter leaves it out: it is optional, and
    changes nothing unless given."""
    feed(monkeypatch, ["4", "", "", "", "150", "", ""])
    assert interactive_argv() == ["audio", "nhk", "--max-duration", "150"]


def test_audio_nhk_precise_url(monkeypatch):
    """A pasted URL replaces the feed, under the same menu entry. The number of
    articles is then not asked, a URL naming only one; the max duration still is."""
    feed(monkeypatch, ["4", "", "not-a-url",
                       "https://news.web.nhk/news/easy/ne1/ne1.html", "180s", "", ""])
    assert interactive_argv() == [
        "audio", "https://news.web.nhk/news/easy/ne1/ne1.html", "--max-duration", "180",
    ]


def test_audio_local_path_must_exist(monkeypatch, tmp_path):
    audio = tmp_path / "k23.mp3"
    audio.write_bytes(b"")
    feed(monkeypatch, ["4", "5", str(tmp_path / "absent.mp3"), str(audio), "5", ""])
    assert interactive_argv() == ["audio", str(audio), "--count", "5"]


@pytest.fixture
def built_in_catalogue(tmp_path, monkeypatch):
    """The menu lists the built-in table only: a local `podcasts.json` would
    shift the numbers.

    Handed back flat, in menu order: these tests check the numbering, not the
    filing (see `test_podcast.py`).
    """
    monkeypatch.setattr(podcast, "catalogue_file", lambda: tmp_path / "absent.json")
    return [alias for _level, entries in podcast.by_level(podcast.PODCASTS)
            for alias, _entry in entries]


def test_audio_podcast_first_alias(monkeypatch, built_in_catalogue):
    # podcast source; first alias of the catalogue; latest episode (default);
    # 1 episode (default); no max duration; cards by default; no send
    feed(monkeypatch, ["4", "2", "1", "1", "", "", "", "", ""])
    assert interactive_argv() == ["audio", built_in_catalogue[0]]


def test_audio_podcast_precise_number(monkeypatch, built_in_catalogue):
    """A number typed replaces the latest episode, so an archive can be taken up
    from its start."""
    feed(monkeypatch, ["4", "2", "1", "1", "42", "", "", "", ""])
    assert interactive_argv() == ["audio", built_in_catalogue[0], "--episode", "42"]


def test_audio_podcast_number_then_several_episodes(monkeypatch, built_in_catalogue):
    feed(monkeypatch, ["4", "2", "1", "1", "42", "3", "", "", ""])
    assert interactive_argv() == [
        "audio", built_in_catalogue[0], "--episode", "42", "--latest", "3",
    ]


def test_audio_podcast_shows_the_level_in_a_column(monkeypatch, built_in_catalogue,
                                                   capsys):
    """The level is a column before each name rather than a heading per group,
    which would push the menu past one screen."""
    feed(monkeypatch, ["4", "2", "1", "1", "", "", "", "", ""])
    interactive_argv()
    lines = [line for line in capsys.readouterr().out.splitlines()
             if "SAKURA TIPS" in line]
    assert lines and lines[0].split(".", 1)[1] == " N5-N4  SAKURA TIPS｜Listen to Japanese"


def test_audio_podcast_feed_url(monkeypatch, built_in_catalogue):
    """A podcast outside the catalogue works without being added to it: the
    aliases are shortcuts, not a permission."""
    last = len(built_in_catalogue) + 1  # "Another podcast...", after the aliases
    feed(monkeypatch, ["4", "2", "1", str(last), "https://example.test/rss",
                       "", "", "", "", ""])
    assert interactive_argv() == ["audio", "https://example.test/rss"]


def test_audio_podcast_several_episodes_and_max_duration(monkeypatch,
                                                         built_in_catalogue):
    feed(monkeypatch, ["4", "2", "1", "1", "", "2", "90", "", ""])
    assert interactive_argv() == [
        "audio", built_in_catalogue[0], "--latest", "2", "--max-duration", "90",
    ]


@pytest.fixture
def built_in_channels(tmp_path, monkeypatch):
    """The menu lists the built-in channels only: a local `channels.json` would
    shift the numbers.
    """
    monkeypatch.setattr(youtube, "catalogue_file", lambda: tmp_path / "absent.json")
    return [alias for _level, entries in youtube.by_level(youtube.CHANNELS)
            for alias, _entry in entries]


def test_audio_youtube_first_channel(monkeypatch, built_in_channels):
    # YouTube source; first channel; no picture; 1 video (default);
    # no max duration; cards by default; no send
    feed(monkeypatch, ["4", "2", "2", "1", "n", "", "", "", ""])
    assert interactive_argv() == ["audio", built_in_channels[0], "--no-video"]


def test_the_picture_is_asked_with_the_other_questions(monkeypatch, capsys,
                                                       built_in_channels):
    """Asked in the dialogue, between the channel and the number of videos: left
    to the pipeline, as on the command line, it would come after the last answer.
    """
    feed(monkeypatch, ["4", "2", "2", "1", "n", "", "", "", ""])
    interactive_argv()
    out = capsys.readouterr().out
    # One line: the wording needs no explaining sentence above it.
    assert "Keep the picture (otherwise the sound track alone) (y/n) [n]: " in out
    assert out.index("Keep the picture") < out.index("Number of recent videos")


def test_audio_youtube_always_writes_its_picture_choice(monkeypatch,
                                                        built_in_channels):
    """Both answers are written, the refusal included: the default is to ask, so
    a command without the answer would ask again when replayed elsewhere.
    """
    feed(monkeypatch, ["4", "2", "2", "1", "y", "", "", "", ""])
    assert interactive_argv() == ["audio", built_in_channels[0], "--video"]


@pytest.mark.parametrize("mode, flag", [("always", "--video"),
                                        ("never", "--no-video")])
def test_a_setting_that_has_settled_it_no_longer_asks(
        monkeypatch, built_in_channels, mode, flag):
    """"always" and "never" skip the question and leave in the command."""
    monkeypatch.setenv(video_clip.ENV_VAR, mode)
    feed(monkeypatch, ["4", "2", "2", "1", "", "", "", ""])
    assert interactive_argv() == ["audio", built_in_channels[0], flag]


@pytest.mark.parametrize("picture, medium", [("y", "video"), ("n", "audio")])
def test_the_max_duration_speaks_of_the_medium_of_the_card(monkeypatch, capsys,
                                                           built_in_channels,
                                                           picture, medium):
    """"Max duration of the video" when the picture is kept, "of the audio"
    otherwise: what is bounded is the medium of the card, not the source (that is
    `--max-video`, on the command line).
    """
    feed(monkeypatch, ["4", "2", "2", "1", picture, "", "", "", ""])
    interactive_argv()
    assert f"Max duration of the {medium}, in seconds" in capsys.readouterr().out


def test_a_local_video_file_asks_the_question_too(monkeypatch, tmp_path):
    """A `.mkv` must not lose its picture silently. The question comes after the
    path, which tells whether there is a picture at all.
    """
    video = tmp_path / "course.mkv"
    video.write_bytes(b"")
    # local source; the path; the picture; cards by default; no send
    feed(monkeypatch, ["4", "5", str(video), "y", "", ""])
    assert interactive_argv() == ["audio", str(video), "--video"]


def test_a_folder_with_no_video_asks_nothing(monkeypatch, tmp_path, capsys):
    """Both answers would do the same thing there: the question would be noise."""
    (tmp_path / "one.mp3").write_bytes(b"")
    feed(monkeypatch, ["4", "5", str(tmp_path), "", ""])
    assert interactive_argv() == ["audio", str(tmp_path)]
    assert "Keep the picture" not in capsys.readouterr().out


def _series(folder, count=3):
    for number in range(1, count + 1):
        (folder / f"Series - {number:02d}.mkv").write_bytes(b"x")


def test_a_series_is_asked_how_many_episodes_and_how_long_a_passage(
        monkeypatch, tmp_path, capsys):
    """A whole series would otherwise go in one pass, in passages of whatever
    length the splitting finds."""
    _series(tmp_path)
    # local source; the path; the picture; 2 episodes; 30 s; cards by default;
    # no send
    feed(monkeypatch, ["4", "5", str(tmp_path), "n", "2", "30", "", ""])
    assert interactive_argv() == ["audio", str(tmp_path), "--latest", "2",
                                  "--max-duration", "30", "--no-video"]
    assert "(3 left)" in capsys.readouterr().out


def test_a_series_takes_one_episode_by_default(monkeypatch, tmp_path):
    """An episode costs minutes of transcription, and a folder with no `--latest`
    goes whole, so the answer is written."""
    _series(tmp_path)
    feed(monkeypatch, ["4", "5", str(tmp_path), "n", "", "", "", ""])
    assert interactive_argv() == ["audio", str(tmp_path), "--latest", "1",
                                  "--no-video"]


def test_videos_put_together_are_not_asked_about_episodes(monkeypatch, tmp_path,
                                                          capsys):
    """Videos with nothing in common are a folder: they go whole, without the
    questions of a series."""
    for name in ("vacances.mp4", "IMG_2034.mp4", "anniversaire.mkv"):
        (tmp_path / name).write_bytes(b"x")
    feed(monkeypatch, ["4", "5", str(tmp_path), "n", "", ""])
    assert interactive_argv() == ["audio", str(tmp_path), "--no-video"]
    output = capsys.readouterr().out
    assert "Number of episodes" not in output
    assert "Max duration" not in output


def test_audio_youtube_several_videos_and_max_duration(monkeypatch, built_in_channels):
    """The duration bounds the audio of the card, as for a podcast, not the source
    video: a twenty-minute video still hands back one-minute passages."""
    feed(monkeypatch, ["4", "2", "2", "1", "n", "3", "60", "", ""])
    assert interactive_argv() == [
        "audio", built_in_channels[0], "--latest", "3", "--max-duration", "60",
        "--no-video",
    ]


def test_audio_youtube_pasted_url(monkeypatch, built_in_channels):
    """The URL is an entry of the channels' screen, and the only way to reach a
    single video."""
    last = len(built_in_channels) + 1
    feed(monkeypatch, ["4", "2", "2", str(last),
                       "https://www.youtube.com/watch?v=abc12345678",
                       "n", "", "", "", ""])
    assert interactive_argv() == [
        "audio", "https://www.youtube.com/watch?v=abc12345678", "--no-video",
    ]


def test_audio_youtube_url_refuses_what_is_not_an_address(monkeypatch,
                                                          built_in_channels):
    last = len(built_in_channels) + 1
    feed(monkeypatch, ["4", "2", "2", str(last), "onomappu",
                       "https://www.youtube.com/@x", "n", "", "", "", ""])
    assert interactive_argv() == [
        "audio", "https://www.youtube.com/@x", "--no-video",
    ]


def test_audio_youtube_shows_the_level_in_a_column(monkeypatch, built_in_channels,
                                                   capsys):
    feed(monkeypatch, ["4", "2", "2", "1", "n", "", "", "", ""])
    interactive_argv()
    lines = [line for line in capsys.readouterr().out.splitlines()
             if "Onomappu" in line]
    assert lines and lines[0].split(".", 1)[1] == " N3-N2  Onomappu"


def test_the_listening_menu_names_the_source_not_the_way_of_aiming_at_it(
        monkeypatch, capsys):
    """"A YouTube video", not "a channel": a channel is one way to reach a video,
    a pasted address another. The label is on the second screen."""
    feed(monkeypatch, ["4", "2", "b", "b", "q"])
    interactive_argv()
    out = capsys.readouterr().out
    assert "A YouTube video" in out
    assert "A YouTube channel" not in out
