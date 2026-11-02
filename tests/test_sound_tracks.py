"""Which of a video's sound tracks goes into the card.

An episode or a film often carries its original version AND a dub. Without
`-map`, ffmpeg takes the track with THE MOST CHANNELS: an English 5.1 dub beats
a Japanese stereo track. Nothing fails: the language only shows in review, once
the calls are paid for.
"""

from __future__ import annotations

import json

import pytest

from kotogen import audio_quality, video_clip
from kotogen.generators import audio_files, nhk

# ── What ffprobe hands back, and what we read of it ───────────────────────────

def _ffprobe(monkeypatch, streams: list[dict], *, present: bool = True):
    """Makes ffprobe answer what a file of these streams would carry."""
    monkeypatch.setattr(nhk.shutil, "which",
                        lambda name: "ffprobe" if present else None)

    class Answer:
        stdout = json.dumps({"streams": streams}).encode("utf-8")

    monkeypatch.setattr(nhk.subprocess, "run", lambda *a, **k: Answer())


def test_the_rank_is_that_of_the_sound_tracks_not_the_file_index(monkeypatch):
    """`-map 0:a:N` counts the SOUND tracks; `index` counts every stream.

    The first sound track usually has index 1, after the picture: confusing the
    two would pick the next track.
    """
    _ffprobe(monkeypatch, [{"index": 1, "tags": {"language": "eng"}},
                           {"index": 2, "tags": {"language": "jpn"}}])

    tracks = nhk.probe_audio_tracks("ep.mkv")

    assert tracks == [("eng", ""), ("jpn", "")]
    assert nhk.japanese_track(tracks) == 1


def test_a_track_with_no_label_still_counts(monkeypatch):
    """An untagged stream keeps its place: the ranks after it depend on it."""
    _ffprobe(monkeypatch, [{"index": 1}, {"index": 2, "tags": {"language": "jpn"}}])

    assert nhk.japanese_track(nhk.probe_audio_tracks("ep.mkv")) == 1


def test_a_missing_ffprobe_does_not_bring_the_pass_down(monkeypatch):
    """Knowing nothing of the tracks leaves the choice to ffmpeg."""
    _ffprobe(monkeypatch, [], present=False)

    assert nhk.probe_audio_tracks("ep.mkv") == []
    assert nhk.japanese_track([]) is None


# ── The choice itself ─────────────────────────────────────────────────────────

def test_a_single_track_is_not_chosen():
    """Nothing to settle: the ffmpeg line carries no track choice."""
    assert nhk.japanese_track([("eng", "")]) is None
    assert nhk.map_args(None) == []


def test_the_japanese_track_beats_the_dub():
    """Two tracks, the Japanese one not the main one."""
    assert nhk.japanese_track([("eng", "English 5.1"), ("jpn", "日本語")]) == 1


@pytest.mark.parametrize("label", ["jpn", "ja", "JPN", "ja-JP"])
def test_every_labelling_convention_is_read(label):
    """ISO 639-2, 639-1, any case, a regional variant: extractors write each."""
    assert nhk.japanese_track([("eng", ""), (label, "")]) == 1


def test_no_japanese_track_is_not_guessed_at():
    """Neither track declared Japanese: no guess, the choice stays ffmpeg's."""
    assert nhk.japanese_track([("eng", ""), ("fre", "")]) is None


def test_the_title_does_not_second_guess_the_labels():
    """"English (translated from Japanese)" carries the word and is not the track.

    Once ONE language label exists in the file, labels alone count: titles are
    free-form.
    """
    tracks = [("eng", "English (translated from Japanese)"), ("und", "Commentary")]
    assert nhk.japanese_track(tracks) is None


def test_the_title_serves_when_nothing_is_labelled():
    """On a container without a single label, it is the only clue left."""
    assert nhk.japanese_track([("", "English dub"), ("", "Japanese")]) == 1


# ── What goes out to ffmpeg ───────────────────────────────────────────────────

def _extraction(monkeypatch, tracks: list[tuple[str, str]], tmp_path):
    """Runs a video of these tracks through `_extract_track`, without ffmpeg."""
    seen: dict = {}

    def fake_write(input_args, probe_src, out_dir, stem, level, *, stream="a:0"):
        seen.update(args=list(input_args), stream=stream)
        return out_dir / f"{stem}.m4a"

    monkeypatch.setattr(nhk, "probe_audio_tracks", lambda src: tracks)
    monkeypatch.setattr(nhk, "_write_audio", fake_write)
    video = tmp_path / "ep.mkv"
    video.write_bytes(b"")
    _, seen["mention"] = audio_files._extract_track(video, tmp_path,
                                                    audio_quality.by_code("none"))
    return seen


def test_the_chosen_track_goes_out_to_ffmpeg(monkeypatch, tmp_path):
    seen = _extraction(monkeypatch, [("eng", ""), ("jpn", "")], tmp_path)

    assert "-map" in seen["args"]
    assert seen["args"][seen["args"].index("-map") + 1] == "0:a:1"


def test_the_probed_codec_is_that_of_the_track_written(monkeypatch, tmp_path):
    """With no compression the codec decides the container: probing another
    track than the one copied would make the copy fail and force a re-encode."""
    seen = _extraction(monkeypatch, [("eng", ""), ("jpn", "")], tmp_path)

    assert seen["stream"] == "a:1"


def test_a_file_with_one_track_takes_it_without_a_word(monkeypatch, tmp_path):
    seen = _extraction(monkeypatch, [("jpn", "")], tmp_path)

    assert seen["args"] == ["-i", str(tmp_path / "ep.mkv"), "-vn"]
    assert seen["stream"] == "a:0"
    assert seen["mention"] == "", "nothing to say when there is nothing to choose"


# ── What the screen says about it ─────────────────────────────────────────────

def test_the_choice_hangs_onto_the_extraction_line(monkeypatch, tmp_path):
    """The track choice ends the extraction's line rather than opening its own."""
    seen = _extraction(monkeypatch, [("eng", ""), ("jpn", "")], tmp_path)

    assert seen["mention"] == "Japanese track out of 2"


def test_the_indecision_is_said(monkeypatch, tmp_path, capsys):
    """The user may know the right track: better said than found in review."""
    _extraction(monkeypatch, [("eng", ""), ("fre", "")], tmp_path)

    assert "! 2 sound tracks, none declared Japanese" in capsys.readouterr().out


# ── The video clip carries the same track as the transcription ────────────────

def _clip(monkeypatch, spans, track):
    """The ffmpeg line a video extract would produce for this track."""
    seen: dict = {}
    monkeypatch.setattr(nhk, "_ffmpeg_run",
                        lambda inputs, dest, level=None, *, copy=False,
                        output_args=None:
                        seen.update(inputs=list(inputs),
                                    output=list(output_args or [])))
    nhk.transcode_spans_to_clip("ep.mkv", "out.webm", spans, track)
    return seen


def test_the_clip_names_the_track_and_the_picture(monkeypatch):
    """One `-map` turns off ffmpeg's automatic selection: naming the sound track
    means naming the picture too, or the clip has none."""
    seen = _clip(monkeypatch, [(3.0, 6.0)], 1)

    assert seen["output"][:6] == ["-vf", video_clip.SCALE,
                                  "-map", "0:v:0", "-map", "0:a:1"]


def test_the_filter_graph_names_the_track_too(monkeypatch):
    """`[0:a]` on a two-track file silently takes the richest track, the dub:
    the clip would play English under a Japanese transcript."""
    seen = _clip(monkeypatch, [(0.0, 4.0), (10.0, 5.0)], 1)

    graph = seen["inputs"][seen["inputs"].index("-filter_complex") + 1]
    assert "[v0][0:a:1][v1][1:a:1]concat=" in graph


def test_with_no_choice_the_clip_does_not_change(monkeypatch):
    """A one-track file produces the line with no track choice."""
    seen = _clip(monkeypatch, [(3.0, 6.0)], None)

    assert seen["output"][:2] == ["-vf", video_clip.SCALE]
    assert "-map" not in seen["output"]
