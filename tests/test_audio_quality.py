"""Compressing the audio: none by default, and what each step writes.

The default is under test: re-encoding an already compressed stream (NHK Easy's)
adds a second loss to the sound the card trains on, which only shows by ear.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from kotogen import audio_quality
from kotogen.cli import build_parser
from kotogen.generators import nhk


@pytest.fixture(autouse=True)
def default_level(monkeypatch):
    """The step is module state: every test starts back from the default."""
    monkeypatch.setattr(audio_quality, "_code", None)


# ── The step in force ─────────────────────────────────────────────────────────

def test_no_compression_by_default():
    assert audio_quality.code() == "none"
    assert audio_quality.current().bitrate is None


def test_the_env_gives_the_starting_step(monkeypatch):
    monkeypatch.setenv("KOTOGEN_AUDIO_QUALITY", "strong")
    assert audio_quality.current().bitrate == "48k"


def test_an_unknown_step_in_the_env_breaks_nothing(monkeypatch):
    """A stale `.env` does not stop the command."""
    monkeypatch.setenv("KOTOGEN_AUDIO_QUALITY", "maximum")
    assert audio_quality.code() == audio_quality.DEFAULT_CODE


def test_the_choice_of_the_session_covers_the_env(monkeypatch):
    monkeypatch.setenv("KOTOGEN_AUDIO_QUALITY", "strong")
    audio_quality.set_code("light")
    assert audio_quality.code() == "light"


def test_the_key_goes_round_and_comes_back_to_the_start():
    """Four positions, in the order displayed, then back to the first step."""
    round_trip = [audio_quality.cycle().code for _ in audio_quality.LEVELS]
    assert round_trip == ["light", "medium", "strong", "none"]


def test_the_option_wins_over_the_setting():
    audio_quality.set_code("strong")
    args = build_parser().parse_args(["audio", "nhk", "--audio-quality", "light"])
    assert audio_quality.resolve(args).bitrate == "96k"


def test_without_the_option_the_setting_applies():
    audio_quality.set_code("medium")
    args = build_parser().parse_args(["audio", "nhk"])
    assert audio_quality.resolve(args).bitrate == "64k"


def test_a_command_without_the_option_falls_back_on_the_setting():
    """The NHK pipeline also serves commands that do not carry the option."""
    assert audio_quality.resolve(argparse.Namespace()).code == "none"


# ── What is asked of ffmpeg ───────────────────────────────────────────────────

def test_without_compression_the_stream_is_copied_across():
    args = audio_quality.encoder_args(audio_quality.by_code("none"), copy=True)
    assert "-c:a" in args and args[args.index("-c:a") + 1] == "copy"
    # Nothing re-encodes, and no switch to mono: the sound is untouched.
    assert "-ac" not in args and "libmp3lame" not in args


def test_without_compression_but_with_a_cut_the_bitrate_is_generous():
    """A cut forces a re-encode, which must not skimp."""
    args = audio_quality.encoder_args(audio_quality.by_code("none"), copy=False)
    assert args[args.index("-b:a") + 1] == audio_quality.UNCOMPRESSED_BITRATE
    assert "copy" not in args


@pytest.mark.parametrize("code, bitrate", [("light", "96k"), ("medium", "64k"),
                                           ("strong", "48k")])
def test_each_step_has_its_bitrate_in_mono(code, bitrate):
    args = audio_quality.encoder_args(audio_quality.by_code(code), copy=True)
    assert args[args.index("-b:a") + 1] == bitrate
    assert args[args.index("-ac") + 1] == "1"


class _ok:
    """What Popen gives back when ffmpeg went well: nothing to say, code 0."""

    returncode = 0
    stdout = ()  # no progress report: the command is over

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_the_ffmpeg_line_of_the_default_does_not_re_encode(monkeypatch, tmp_path):
    """End to end: what really goes to ffmpeg when nothing is set."""
    lines = []
    monkeypatch.setattr(nhk.shutil, "which", lambda name: name)
    monkeypatch.setattr(nhk.subprocess, "Popen",
                        lambda cmd, **k: lines.append(cmd) or _ok())
    nhk._ffmpeg_run(["-i", "source.m4a"], tmp_path / "out.m4a",
                    audio_quality.current(), copy=True)
    assert "-c:a" in lines[0] and lines[0][lines[0].index("-c:a") + 1] == "copy"
    assert "libmp3lame" not in lines[0]


# ── The extension follows the stream, not the other way round ─────────────────

@pytest.mark.parametrize("codec, extension", [
    ("aac", ".m4a"), ("mp3", ".mp3"), ("opus", ".opus"), ("flac", ".flac"),
])
def test_the_container_is_the_one_that_takes_the_stream(monkeypatch, codec, extension):
    monkeypatch.setattr(nhk, "probe_codec", lambda src, stream="a:0": codec)
    assert nhk.copy_extension("no matter what") == extension


def test_an_unknown_codec_is_not_copied_across(monkeypatch):
    """Exotic codec, or ffprobe silent: re-encode rather than chance it."""
    monkeypatch.setattr(nhk, "probe_codec", lambda src, stream="a:0": None)
    assert nhk.copy_extension("no matter what") is None


def test_without_compression_the_file_carries_the_extension_of_the_stream(
        monkeypatch, tmp_path):
    monkeypatch.setattr(nhk, "probe_codec", lambda src, stream="a:0": "aac")
    monkeypatch.setattr(nhk, "_ffmpeg_run",
                        lambda inputs, dest, level, copy=False: dest.write_bytes(b"x"))
    dest = nhk._write_audio(["-i", "x"], "x", tmp_path, "nhk_ne1",
                            audio_quality.by_code("none"))
    assert dest == tmp_path / "nhk_ne1.m4a"


def test_with_compression_the_file_is_an_mp3(monkeypatch, tmp_path):
    monkeypatch.setattr(nhk, "probe_codec",
                        lambda src, stream="a:0": pytest.fail("codec probed for nothing"))
    monkeypatch.setattr(nhk, "_ffmpeg_run",
                        lambda inputs, dest, level, copy=False: dest.write_bytes(b"x"))
    dest = nhk._write_audio(["-i", "x"], "x", tmp_path, "nhk_ne1",
                            audio_quality.by_code("strong"))
    assert dest == tmp_path / "nhk_ne1.mp3"


def test_a_refused_copy_falls_back_on_a_re_encode(monkeypatch, tmp_path, capsys):
    """A fussy container must not cost the article: re-encode, and say so."""
    monkeypatch.setattr(nhk, "probe_codec", lambda src, stream="a:0": "aac")

    def ffmpeg(inputs, dest: Path, level, copy=False):
        if copy:
            dest.write_bytes(b"truncated")  # ffmpeg started then gave up
            raise RuntimeError("could not find tag for codec")
        dest.write_bytes(b"mp3")

    monkeypatch.setattr(nhk, "_ffmpeg_run", ffmpeg)
    dest = nhk._write_audio(["-i", "x"], "x", tmp_path, "nhk_ne1",
                            audio_quality.by_code("none"))
    assert dest == tmp_path / "nhk_ne1.mp3"
    # The started .m4a is removed, and the fallback announced.
    assert not (tmp_path / "nhk_ne1.m4a").exists()
    assert "re-encoded" in capsys.readouterr().err


def test_a_failed_re_encode_leaves_no_audio_behind(monkeypatch, tmp_path):
    """The half-written MP3 would sit beside the TSV and in the next pass's way."""
    def ffmpeg(inputs, dest: Path, level, copy=False):
        dest.write_bytes(b"half an mp3")
        raise RuntimeError("Connection reset by peer")

    monkeypatch.setattr(nhk, "_ffmpeg_run", ffmpeg)
    with pytest.raises(RuntimeError):
        nhk._write_audio(["-i", "x"], "x", tmp_path, "nhk_ne1",
                         audio_quality.by_code("strong"))
    assert not (tmp_path / "nhk_ne1.mp3").exists()


def test_an_interrupted_encode_still_says_it_was_interrupted(monkeypatch, tmp_path):
    """After a Ctrl+C, Windows may refuse to delete what ffmpeg still holds
    (WinError 32): that refusal must not replace the interruption."""
    def interrupted(inputs, dest: Path, level, copy=False):
        dest.write_bytes(b"half")
        raise KeyboardInterrupt

    monkeypatch.setattr(nhk, "_ffmpeg_run", interrupted)

    def held(self, missing_ok=False):
        raise PermissionError(32, "in use by another process")

    monkeypatch.setattr(Path, "unlink", held)
    with pytest.raises(KeyboardInterrupt):
        nhk._write_audio(["-i", "x"], "x", tmp_path, "nhk_ne1",
                         audio_quality.by_code("strong"))
