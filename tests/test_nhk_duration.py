"""Length limit of the NHK audios (--max-duration): an article that is too long
is dropped before the stream is downloaded and before the slightest AI call."""

import argparse

import pytest

from kotogen import i18n
from kotogen.cli import build_parser, seconds
from kotogen.generators import nhk

M3U8 = "https://media.vd.st.nhk/news/easy/easy_audio/ne1/index.m3u8?hdnts=token"


def args_with(limit):
    return argparse.Namespace(max_duration=limit, audio_quality=None,
                              count=3, level="auto")


# -- Reading the option -------------------------------------------------------

def test_seconds_with_or_without_a_unit():
    assert seconds("180") == seconds("180s") == 180


@pytest.mark.parametrize("value", ["0", "-1", "2.5", "three"])
def test_seconds_refuses_impossible_values(value):
    with pytest.raises(argparse.ArgumentTypeError):
        seconds(value)


def test_the_option_is_absent_by_default():
    """Optional: without it nothing is filtered (and nothing is measured)."""
    args = build_parser().parse_args(["audio", "nhk"])
    assert args.max_duration is None
    assert nhk.max_duration_seconds(args) is None


def test_the_option_is_read_in_seconds():
    args = build_parser().parse_args(["audio", "nhk", "--max-duration", "180"])
    assert nhk.max_duration_seconds(args) == 180


# -- check_duration -----------------------------------------------------------

def test_no_limit_means_no_measurement(monkeypatch):
    monkeypatch.setattr(nhk, "probe_duration",
                        lambda src: pytest.fail("ffprobe run for nothing"))
    nhk.check_duration(M3U8, None)


def test_an_audio_too_long_is_dropped(monkeypatch):
    monkeypatch.setattr(nhk, "probe_duration", lambda src: 245.0)
    with pytest.raises(nhk.AudioTooLong) as exc:
        nhk.check_duration(M3U8, 180)
    assert "4 min 05 s" in str(exc.value)  # the measured length is said


def test_an_audio_within_the_limit_goes_through(monkeypatch):
    monkeypatch.setattr(nhk, "probe_duration", lambda src: 180.0)
    nhk.check_duration(M3U8, 180)  # exactly the limit: accepted


def test_tenths_of_a_second_do_not_cause_a_refusal(monkeypatch):
    """Refusing "3 min 00 s" against a "3 min 00 s" limit would look like a bug:
    durations are compared as they are shown."""
    monkeypatch.setattr(nhk, "probe_duration", lambda src: 180.4)
    nhk.check_duration(M3U8, 180)


def test_an_unmeasurable_length_lets_the_article_through(monkeypatch):
    """ffprobe missing or silent: we generate anyway rather than lose the
    article without a word."""
    monkeypatch.setattr(nhk, "probe_duration", lambda src: None)
    nhk.check_duration(M3U8, 60)


def test_format_duration():
    assert nhk.format_duration(45) == "45 s"
    assert nhk.format_duration(180) == "3 min 00 s"
    assert nhk.format_duration(245.4) == "4 min 05 s"


def test_a_duration_is_said_in_the_units_of_the_screen(monkeypatch):
    """`min` and `s` are words: a Japanese screen writes 分 and 秒."""
    monkeypatch.setattr(i18n, "_language", "ja")
    monkeypatch.setattr(i18n, "_catalogue", {"{seconds} s": "{seconds}秒",
                                             "{minutes} min {seconds} s": "{minutes}分{seconds}秒"})
    assert nhk.format_duration(212) == "3分32秒"
    assert nhk.format_duration(45) == "45秒"


# -- The whole pipeline of an article -----------------------------------------

class _NoAI:
    def chat_json(self, *a, **k):
        pytest.fail("no AI call should be paid for a dropped article")


def test_an_article_too_long_costs_neither_download_nor_ai(monkeypatch, tmp_path):
    monkeypatch.setattr(nhk, "fetch_article",
                        lambda *a, **k: ("Title", ["日本[にほん]。"], None, "", M3U8))
    monkeypatch.setattr(nhk, "probe_duration", lambda src: 600.0)
    monkeypatch.setattr(nhk, "transcode_url",
                        lambda *a: pytest.fail("stream downloaded despite the limit"))
    monkeypatch.setattr(nhk, "mark_seen",
                        lambda *a, **k: pytest.fail("article remembered as done"))

    with pytest.raises(nhk.AudioTooLong):
        nhk.generate_for_url("https://news.web.nhk/news/easy/ne1/ne1.html",
                             args_with(180), _NoAI(), tmp_path)
    assert list(tmp_path.iterdir()) == []  # no MP3 left behind


# -- Reading the stream -------------------------------------------------------

def test_a_remote_stream_cannot_lead_ffmpeg_to_a_file_of_this_machine():
    """The playlist is read on the web, and so are its segments: one naming a
    local file would have it read into the extract."""
    args = nhk._remote_input_args(M3U8)
    allowed = args[args.index("-protocol_whitelist") + 1].split(",")
    assert "file" not in allowed
    assert {"https", "crypto"} <= set(allowed)
