"""Keeping the picture of a video source, or keeping the sound alone.

With the picture kept, each passage is cut from the original video and the card
plays the clip. The choice is asked once per pass, only with a video in play,
unless the setting or `--video` / `--no-video` answers it. What would break
unseen: the `Audio` and `Video` fields filled together, a whole episode let past
the duration bound, a clip cut from the sound track and so without a picture.
"""

from __future__ import annotations

import argparse

import pytest

from kotogen import console, exporter, i18n, video_clip
from kotogen.ai_client import AITruncatedError
from kotogen.generators import audio, audio_files, audio_split, nhk

# ── The setting: command line, session, file ──────────────────────────────────

@pytest.fixture(autouse=True)
def _fresh_session(monkeypatch):
    """No session choice leaks from one test to the next."""
    monkeypatch.setattr(video_clip, "_mode", None)
    monkeypatch.delenv(video_clip.ENV_VAR, raising=False)


@pytest.fixture
def answers(monkeypatch):
    """Replaces the question with an answer, and counts the times it is asked."""
    asked = []

    def _install(answer: str):
        def ask(prompt, choices, **kwargs):
            asked.append(prompt)
            return answer
        monkeypatch.setattr("kotogen.exporter.ask_choice", ask)
        return asked

    return _install


def test_the_question_is_the_default(answers):
    """Neither behaviour is right all the time, so the default is to ask."""
    assert video_clip.mode() == "ask"
    answers("p")
    assert video_clip.resolve(argparse.Namespace(video=None),
                              in_play=True) is True


def test_nothing_is_asked_with_no_picture_to_settle(answers):
    """A folder of mp3 has no picture: asking would only teach answering blind."""
    asked = answers("p")
    assert video_clip.resolve(argparse.Namespace(video=None)) is False
    assert asked == []


def test_sound_alone_answers_for_whoever_cannot(monkeypatch):
    """Outside a terminal, `ask_choice` hands back the last choice: it has to be
    sound alone, so that an unattended script never re-encodes a whole season.
    """
    from kotogen.exporter import ask_choice

    def eof():
        raise EOFError

    monkeypatch.setattr(console, "read_line", eof)
    assert ask_choice("[i] keep the picture  [s] sound only", "is") == "s"


def test_under_yes_the_sound_track_is_kept(monkeypatch):
    """`--yes` answers as a script does; `--video` is how it keeps the picture."""
    def waited():
        raise AssertionError("an answer was waited for")

    monkeypatch.setattr(console, "read_line", waited)
    with exporter.unattended(True):
        assert video_clip.resolve(argparse.Namespace(video=None), in_play=True) is False
        assert video_clip.resolve(argparse.Namespace(video=True), in_play=True) is True


def test_the_flag_answers_in_advance(answers):
    """`--no-video` and `--video` answer without asking."""
    asked = answers("p")
    assert video_clip.resolve(argparse.Namespace(video=False),
                              in_play=True) is False
    assert video_clip.resolve(argparse.Namespace(video=True),
                              in_play=True) is True
    assert asked == []


def test_the_other_two_modes_cut_the_question_off(answers, monkeypatch):
    """`always` and `never` settle the question for good."""
    asked = answers("p")
    monkeypatch.setenv(video_clip.ENV_VAR, "always")
    assert video_clip.resolve(argparse.Namespace(video=None),
                              in_play=True) is True
    monkeypatch.setenv(video_clip.ENV_VAR, "never")
    assert video_clip.resolve(argparse.Namespace(video=None),
                              in_play=True) is False
    assert asked == []


def test_the_old_switch_still_means_something(monkeypatch):
    """`KOTOGEN_VIDEO=1` and `0` are read as always and never."""
    monkeypatch.setenv(video_clip.ENV_VAR, "1")
    assert video_clip.mode() == "always"
    monkeypatch.setenv(video_clip.ENV_VAR, "0")
    assert video_clip.mode() == "never"
    # And a value that means nothing does not make the command fail.
    monkeypatch.setenv(video_clip.ENV_VAR, "whenever")
    assert video_clip.mode() == video_clip.DEFAULT_MODE


def test_the_i_key_goes_round_without_touching_the_file(monkeypatch):
    """Three positions, and the value beside the label says which, in one word."""
    monkeypatch.setenv(video_clip.ENV_VAR, "ask")
    assert video_clip.describe() == "ask"
    assert video_clip.cycle() == "always"
    assert video_clip.describe() == "always"
    assert video_clip.cycle() == "never"
    assert video_clip.describe() == "never"
    assert video_clip.cycle() == "ask"


# ── Who knows there is a picture to settle ────────────────────────────────────
# `run_audio` tells `video_clip` whether a video is in play, once its inputs are
# sorted and before any download.

class _Probe(Exception):
    """Stops the command where the picture choice is settled, and says what it saw."""

    def __init__(self, in_play: bool):
        self.in_play = in_play


def _in_play(monkeypatch, tmp_path, entries: list[str]) -> bool:
    """What `run_audio` answers to `video_clip.resolve` for these entries."""
    def probe(args, *, in_play=False):
        raise _Probe(in_play)

    monkeypatch.setattr(audio.video_clip, "resolve", probe)
    monkeypatch.setattr(audio, "AIClient", lambda **k: object())
    monkeypatch.setattr(audio, "resolve_output_path", lambda *a, **k: tmp_path / "out.tsv")

    args = argparse.Namespace(
        inputs=entries, latest=1, provider="openrouter", model="m",
        output=str(tmp_path / "out.tsv"), send=False, deck="Test", notetype="Audio",
        count=None, level="auto", max_duration=None, whisper_model="small",
        audio_quality=None, split=True, episode=None,
    )
    with pytest.raises(_Probe) as raised:
        audio.run_audio(args)
    return raised.value.in_play


def test_a_local_video_file_puts_a_picture_in_play(monkeypatch, tmp_path):
    """The suffix says so: it is all there is before opening the file."""
    (tmp_path / "course.mkv").write_bytes(b"")
    assert _in_play(monkeypatch, tmp_path, [str(tmp_path / "course.mkv")]) is True


def test_a_folder_of_mp3_puts_none_in_play(monkeypatch, tmp_path):
    """Both answers would do the same thing there: no question."""
    (tmp_path / "one.mp3").write_bytes(b"")
    (tmp_path / "two.mp3").write_bytes(b"")
    assert _in_play(monkeypatch, tmp_path, [str(tmp_path)]) is False


def test_a_youtube_entry_puts_one_in_play_by_nature(monkeypatch, tmp_path):
    """The question decides what is downloaded: it is asked before anything is."""
    from kotogen.generators import sources

    monkeypatch.setattr(sources, "is_youtube", lambda entry: entry == "onomappu")
    monkeypatch.setattr(audio, "_youtube_videos",
                        lambda *a, **k: pytest.fail("downloaded before asking"))
    assert _in_play(monkeypatch, tmp_path, ["onomappu"]) is True


# ── The two fields are mutually exclusive ─────────────────────────────────────

def _answer() -> dict:
    return {"Cards": [{"Question": "Où va-t-il ?", "Answer": "À Kyoto",
                       "Decoys": ["À Osaka", "À Nara", "Il reste"]}],
            "TranscriptLines": ["京都[きょうと]へ 行[い]きます。"],
            "TranslationLines": ["Je vais à Kyoto."]}


def test_a_video_card_leaves_the_audio_field_empty():
    """The template picks its tag on the FILLED field: two filled fields, and the
    card plays a file that was never dropped."""
    cards = audio._post_process(_answer(), "ep_01_a1b2c3d4.webm", "ep_01",
                                "N4", is_video=True)

    assert cards[0]["Video"] == exporter.video_ref("ep_01_a1b2c3d4.webm")
    assert cards[0]["Audio"] == ""


def test_an_audio_card_leaves_the_video_field_empty():
    """An audio card is unchanged: its Video field stays empty."""
    cards = audio._post_process(_answer(), "ep_01_a1b2c3d4.mp3", "ep_01", "N4")

    assert cards[0]["Audio"] == exporter.audio_ref("ep_01_a1b2c3d4.mp3")
    assert cards[0]["Video"] == ""


def test_the_video_field_follows_the_audio_field():
    """A TSV import pairs columns with fields by rank: one field moved shifts
    every column after it."""
    assert audio.FIELDS[:3] == ["ID", "Audio", "Video"]


# ── The extract is cut out of the video, not out of the sound track ───────────

def test_the_clip_is_cut_out_of_the_original_file(monkeypatch, tmp_path):
    """Cut from the extracted sound track, the clip would have no picture."""
    seen: dict = {}

    def fake_clip(src, dest, spans, track=None):
        seen.update(src=src, spans=list(spans))
        dest.write_bytes(b"clip")

    monkeypatch.setattr(nhk, "transcode_spans_to_clip", fake_clip)
    video = tmp_path / "my episode.mkv"
    video.write_bytes(b"")
    block = audio_split.Block((1, 2), ((3.0, 9.0),))

    clip = audio._extract_clip(video, block, 1, tmp_path)

    assert seen["src"] == video
    assert seen["spans"] == [(3.0, 6.0)]
    assert clip.suffix == ".webm"
    # The front puts the file into `src={{Video}}`, without quotes: a space would
    # cut the attribute off and the card would show nothing.
    assert " " not in clip.name
    # The fingerprint is taken on the file PRODUCED: two passages of the same
    # episode cannot end up under the same name in collection.media.
    assert clip.stem.endswith(audio_files.fingerprint(clip))


def test_the_draft_does_not_survive_a_failure(monkeypatch, tmp_path):
    """An interrupted encode must not leave a `.kotogen_*` behind in the TSV folder."""
    def fake_clip(src, dest, spans, track=None):
        dest.write_bytes(b"half done")
        raise RuntimeError("ffmpeg cut out")

    monkeypatch.setattr(nhk, "transcode_spans_to_clip", fake_clip)
    video = tmp_path / "ep.mkv"
    video.write_bytes(b"")

    with pytest.raises(RuntimeError):
        audio._extract_clip(video, audio_split.Block((1,), ((0.0, 4.0),)), 1, tmp_path)

    assert list(tmp_path.glob(".kotogen_*")) == []


# ── The ffmpeg command line ───────────────────────────────────────────────────

def _command(monkeypatch) -> dict:
    seen: dict = {}
    monkeypatch.setattr(nhk, "_ffmpeg_run",
                        lambda inputs, dest, level=None, *, copy=False, output_args=None,
                        stream="a:0":
                        seen.update(inputs=list(inputs), output=list(output_args or [])))
    return seen


def test_a_single_span_is_rescaled_by_vf(monkeypatch, tmp_path):
    """`-t` and not `-to` after an input `-ss`: the meaning of `-to` has changed
    from one ffmpeg version to another, that of `-t` never."""
    seen = _command(monkeypatch)

    nhk.transcode_spans_to_clip(tmp_path / "ep.mkv", tmp_path / "out.webm", [(3.0, 6.0)])

    assert seen["inputs"][:4] == ["-ss", "3.000", "-t", "6.000"]
    assert seen["output"][:2] == ["-vf", video_clip.SCALE]
    assert "libvpx-vp9" in seen["output"]
    # Without `-b:v 0`, the CRF is only a ceiling and libvpx aims at its low
    # default bitrate: the file comes out, ugly.
    assert seen["output"][seen["output"].index("-b:v") + 1] == "0"


def test_several_spans_are_rescaled_inside_the_graph(monkeypatch, tmp_path):
    """An output of a `-filter_complex` cannot take a `-vf`: ffmpeg refuses the line."""
    seen = _command(monkeypatch)

    nhk.transcode_spans_to_clip(tmp_path / "ep.mkv", tmp_path / "out.webm",
                                [(0.0, 4.0), (10.0, 5.0)])

    graph = seen["inputs"][seen["inputs"].index("-filter_complex") + 1]
    assert graph.count(video_clip.SCALE) == 2, "every input is rescaled"
    assert "concat=n=2:v=1:a=1[v][a]" in graph
    assert seen["output"][:4] == ["-map", "[v]", "-map", "[a]"]
    assert "-vf" not in seen["output"]


def test_no_span_is_an_error(tmp_path):
    with pytest.raises(ValueError):
        nhk.transcode_spans_to_clip(tmp_path / "ep.mkv", tmp_path / "out.webm", [])


# ── The duration bound ────────────────────────────────────────────────────────

def _block_of(duration: float):
    return audio_split.Block((1, 2), ((0.0, duration),))


def _passage(monkeypatch, tmp_path, duration: float, clip=None, generate=None):
    """Runs a block of this duration through `_generate_for_block`, in video mode.

    The AI answers nothing and the extractions only record that they ran; `clip`
    and `generate` swap in a failing extraction or AI call.
    """
    done: dict = {}

    def fake_clip(video, block, rank, out_dir):
        done["clip"] = video
        return out_dir / "ep_01_deadbeef.webm"

    def fake_sound(source, *a, **k):
        done["mp3"] = source
        return tmp_path / "ep_01_deadbeef.mp3"

    monkeypatch.setattr(audio, "_extract_clip", clip or fake_clip)
    monkeypatch.setattr(audio, "_extract_span", fake_sound)
    monkeypatch.setattr(audio, "_copy_whole", fake_sound)
    monkeypatch.setattr(audio, "_generate_for_audio",
                        generate or (lambda *a, **k: None))  # no paying call

    video = tmp_path / "ep.mkv"
    track = tmp_path / "ep.m4a"
    for f in (video, track):
        f.write_bytes(b"")
    block = _block_of(duration)
    split = audio_split.Split(audio_split.KIND_WHOLE, [block], [])
    args = argparse.Namespace(count=None, level="N4", deck="D", notetype="N",
                              audio_quality=None, max_duration=None)
    segments = [audio_split.Segment("こんにちは。", 0.0, 1.0),
                audio_split.Segment("はい。", 1.0, duration)]

    audio._generate_for_block(None, args, track, block, 1, split, segments,
                              tmp_path, tmp_path / "out.tsv", [], "", video=video)
    return done


def test_a_short_passage_keeps_its_picture(monkeypatch, tmp_path):
    done = _passage(monkeypatch, tmp_path, video_clip.MAX_SECONDS - 1)

    assert done.get("clip") == tmp_path / "ep.mkv"
    # The mp3 is not produced: the card plays one media only, and the other would
    # linger in the media library with nothing pointing at it.
    assert "mp3" not in done


def test_a_passage_that_is_too_long_falls_back_to_sound_alone(monkeypatch, tmp_path,
                                                              capsys):
    """Without this bound, twenty minutes of drama would land in collection.media."""
    done = _passage(monkeypatch, tmp_path, video_clip.MAX_SECONDS + 1)

    assert "clip" not in done
    assert done.get("mp3") == tmp_path / "ep.m4a"
    # Silently: a bound, not an incident, so the passage keeps its single line.
    assert len(capsys.readouterr().out.splitlines()) == 1


def test_the_help_of_video_says_the_fallback_is_silent():
    """`--help` describes the bound the test above checks, silence included."""
    from kotogen.cli import build_parser

    helps = [inner.help
             for action in build_parser()._actions
             if isinstance(action, argparse._SubParsersAction)
             for parser in action.choices.values()
             for inner in parser._actions if "--video" in inner.option_strings]
    assert helps
    for text in helps:
        assert f"longer than {video_clip.MAX_SECONDS} s" in text
        assert "without a word" in text


# ── The truncated answer ──────────────────────────────────────────────────────
# A truncated answer is retried asking for half as much, all on the line of the
# passage, which stays open for the length of the calls.

def _truncated_then(answer):
    """An AI call that overflows the first time, then hands back `answer`.

    Records the caps asked for: they are what the retry has to change.
    """
    asked: list[int] = []

    def generate(client, name, lines, limit, level, choice=False, figured=False):
        asked.append(limit)
        if len(asked) == 1:
            raise AITruncatedError("answer truncated on the 4096-token limit")
        if isinstance(answer, Exception):
            raise answer
        return answer

    return generate, asked


def test_a_truncated_answer_is_retried_with_fewer_cards(monkeypatch, tmp_path,
                                                        capsys):
    """The passage is not lost: it goes off again, half as greedy."""
    console.watch()   # the open line is only readable through the watcher
    generate, asked = _truncated_then({})   # an answer, with no card to write

    _passage(monkeypatch, tmp_path, 30.0, generate=generate)

    assert len(asked) == 2
    assert asked[1] == asked[0] // 2
    # The retry extends the announcement rather than opening a line. The empty
    # answer writes to stderr, which cuts the line: it is then repeated whole.
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1].endswith("- retried shorter (0 cards)")


def test_a_second_truncation_is_not_paid_for_again(monkeypatch, tmp_path, capsys):
    """Two calls at most: a third would be paying to guess."""
    console.watch()
    generate, asked = _truncated_then(AITruncatedError("truncated again"))

    _passage(monkeypatch, tmp_path, 30.0, generate=generate)

    assert len(asked) == 2
    out = capsys.readouterr().out
    assert len(out.splitlines()) == 1
    assert out.rstrip().endswith("- retried shorter (given up)")


def test_a_failure_does_not_pour_out_the_model_answer(monkeypatch, tmp_path, capsys):
    """Only the sentence of a `chat_json` error is shown; the raw answer under
    it (JSON, the transcript) stays in the exception."""
    console.watch()

    def generate(*a, **k):
        raise ValueError(
            "The AI did not return valid JSON.\n\n"
            'Raw answer:\n```json\n{"cards": [食べ終わったら')

    _passage(monkeypatch, tmp_path, 30.0, generate=generate)

    out = capsys.readouterr().out
    assert out.rstrip().endswith("(failed: The AI did not return valid JSON.)")
    assert "Raw answer" not in out and "json" not in out
    assert "食" not in out, "the line gives away the content of the audio"


def test_an_encoding_failure_does_not_lose_the_passage(monkeypatch, tmp_path, capsys):
    """The picture is an extra: the card is better off without it than not made."""
    def broken_clip(video, block, rank, out_dir):
        raise RuntimeError("codec absent")

    done = _passage(monkeypatch, tmp_path, 30.0, clip=broken_clip)

    assert done.get("mp3") == tmp_path / "ep.m4a"
    assert "picture dropped" in capsys.readouterr().err


@pytest.mark.parametrize("lang", [name for name in i18n.available()
                                  if name != i18n.SOURCE])
def test_every_table_names_each_mode_of_the_video_picture(lang):
    """The settings screen shows the mode in force through `describe`."""
    table = i18n._load(lang)
    assert [mode for mode in video_clip.MODES if mode not in table] == []
