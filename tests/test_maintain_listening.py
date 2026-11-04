"""Maintenance: a listening card heard again (the purple flag).

Whisper, ffmpeg and Anki are faked: what is pinned is what the pass decides.
"""

from pathlib import Path

import pytest

from kotogen.anki.maintain import listening as listening_pass
from kotogen.generators import jlpt_papers
from kotogen.generators.audio_split import Block, Segment, Word
from kotogen.maintenance import kinds, listening


def _note(note_id: int, **values) -> dict:
    """A card as the maintenance reads one, the id of its note as its `id`."""
    fields = {name: "" for name in (*kinds.LISTENING.fields, "ID", "Audio", "Video",
                                    "Timecodes", "Source")}
    fields.update(values)
    return {"id": note_id, "tags": [], "fields": fields}


class _Client:
    def __init__(self, result):
        self.result = result
        self.user = ""

    def chat_json(self, system, user):
        self.user = user
        return self.result


SOUND = '<audio controls src="episode_12_03_abcd1234.mp3"></audio>'
SOURCE = "Podcast - Episode 12 (01:10 → 01:40) https://example.org/12"
TRANSCRIPT = "A：はい。<br>B：そうですね。"
CARD = _note(1, ID="episode_12_03_abcd1234_001", Audio=SOUND, Source=SOURCE,
             Transcript=TRANSCRIPT, Translation="Yes.<br>Right.",
             Timecodes="0.20 1.50", Question="Does B agree?", Answer="Yes", KeyLine="2")
OTHER = _note(2, ID="episode_12_03_abcd1234_002", Audio=SOUND, Source=SOURCE,
              Transcript=TRANSCRIPT, Translation="Yes.<br>Right.",
              Timecodes="0.20 1.50", Question="Who speaks first?", Answer="A", KeyLine="1")


# ── Where the extract comes from ──────────────────────────────────────────────

def test_the_bounds_are_read_off_the_source_and_written_back():
    assert listening.bounds_of(SOURCE) == (70.0, 100.0)
    assert listening.with_bounds(SOURCE, 65.4, 103.0) == (
        "Podcast - Episode 12 (01:05 → 01:43) https://example.org/12")
    assert listening.bounds_of("a file taken whole") is None


def test_the_name_of_an_extract_says_its_recording_and_its_rank():
    media = listening.media_of(CARD)
    assert (media.field, media.name, media.readable, media.rank) == (
        "Audio", "episode_12_03_abcd1234.mp3", "episode_12", "03")
    whole = listening.media_of(_note(3, Audio='<audio controls src="track_1f2e3d4c.m4a"></audio>'))
    assert (whole.readable, whole.rank) == ("track", "")
    clip = listening.media_of(_note(4, Video='<video controls src="drama_01_0000abcd.webm"></video>'))
    assert clip.video and clip.rank == "01"


def test_the_recording_is_found_in_the_cache_by_its_readable_name(monkeypatch, tmp_path):
    folder = tmp_path / "podcasts" / "feed"
    folder.mkdir(parents=True)
    (folder / "episode 12.mp3").write_bytes(b"")
    (folder / "episode 13.mp3").write_bytes(b"")
    monkeypatch.setattr(listening_pass.system, "cache_dir", lambda: tmp_path)
    assert listening_pass.locate(listening.media_of(CARD), []) == folder / "episode 12.mp3"


def test_a_video_extract_needs_the_video(monkeypatch, tmp_path):
    (tmp_path / "drama.mp3").write_bytes(b"")
    monkeypatch.setattr(listening_pass.system, "cache_dir", lambda: tmp_path)
    clip = listening.media_of(_note(4, Video='<video controls src="drama_01_0000abcd.webm"></video>'))
    assert listening_pass.locate(clip, []) is None
    (tmp_path / "drama.mkv").write_bytes(b"")
    assert listening_pass.locate(clip, []) == tmp_path / "drama.mkv"


# ── Where the new cut falls ───────────────────────────────────────────────────

def _segment(text: str, start: float, end: float) -> Segment:
    return Segment(text, start, end, (Word(text, start + 0.1, end - 0.1),))


WINDOW = [_segment("前の話。", 0.0, 13.0),
          _segment("今日は暑いですね。", 13.5, 16.5),   # the old cut (15.0) went through it
          _segment("ええ、本当に。", 17.0, 44.0),
          _segment("次の話。", 44.5, 50.0)]


def test_a_sentence_the_cut_went_through_is_taken_whole():
    block = listening.recut(WINDOW, 15.0, 44.0, [])
    assert block.lines == (2, 3)
    assert block.start < 13.6 and block.end > 43.9


def test_the_new_cut_takes_nothing_of_the_sentences_around():
    block = listening.recut(WINDOW, 15.0, 44.0, [])
    assert block.start >= 13.0 and block.end <= 44.5


def test_the_instants_of_a_field_worked_out_again_are_compared_to_the_second():
    assert listening.same_instants("0.21 1.48", "0.20 1.50")
    assert not listening.same_instants("0.20 3.10", "0.20 1.50")
    assert not listening.same_instants("0.20", "0.20 1.50")
    assert listening.same_instants("", "0.20 1.50")


# ── What the model hands back ─────────────────────────────────────────────────

HEARD = listening.Heard(Path("window.mp3"), 55.0, None, WINDOW,
                        Block((2, 3), ((13.4, 44.1),)), moved=True)


def test_the_model_reads_what_was_heard_and_the_questions():
    client = _Client({"changed": False, "reason": "right"})
    assert listening.ask_transcript(client, HEARD, [CARD, OTHER]) is None
    assert "今日は暑いですね。" in client.user
    assert "Who speaks first?" in client.user


def test_a_transcript_is_taken_with_its_furigana_and_its_key_lines():
    client = _Client({"changed": True, "reason": "whole sentence",
                      "TranscriptLines": ["A：今日は暑いですね。", "B：ええ、本当に。"],
                      "TranslationLines": ["Hot today.", "Yes, really."],
                      "KeyLines": {"1": 2, "2": 9}, "lost": [2, "x", 7]})
    rewrite = listening.ask_transcript(client, HEARD, [CARD, OTHER])
    assert "今日[きょう]は" in rewrite.transcript[0]
    assert rewrite.key_lines == {1: "2", 2: ""}
    assert rewrite.lost == [2]
    assert rewrite.refused == []


def test_a_translation_gets_the_readings_of_the_export():
    """On a deck in Japanese it is Japanese, and the export lays its readings
    (`exporter.plain_field`): heard again, it keeps them."""
    client = _Client({"changed": True, "reason": "whole sentence",
                      "TranscriptLines": ["A：今日は暑いですね。", "B：ええ、本当に。"],
                      "TranslationLines": ["A：今日はとても暑いね。", "B：うん、本当だね。"]})
    rewrite = listening.ask_transcript(client, HEARD, [CARD])
    assert "今日[きょう]" in rewrite.translation[0]


def test_a_translation_that_is_not_lined_up_is_turned_down():
    client = _Client({"TranscriptLines": ["A：はい。", "B：ええ。"],
                      "TranslationLines": ["Yes. Yes."]})
    assert listening.ask_transcript(client, HEARD, [CARD]).refused


# ── The pass ──────────────────────────────────────────────────────────────────

def _run(monkeypatch, answer, *, heard=HEARD, auto=True, stamps="0.40 2.10",
         pieced=False, card=CARD, hear=None):
    """One purple card of a two-card passage, everything outside faked."""
    import copy

    card, other = copy.deepcopy(card), copy.deepcopy(OTHER)
    writes, cleared, anki_calls = [], [], []
    monkeypatch.setattr(listening_pass, "locate", lambda media: Path("episode 12.mp3"))
    monkeypatch.setattr(listening_pass, "in_pieces", lambda media, bounds: pieced)
    monkeypatch.setattr(listening_pass, "hear", hear or (lambda *a: heard))
    monkeypatch.setattr(listening_pass, "passage_of", lambda note, kind, known: [other])
    monkeypatch.setattr(listening_pass.timecodes, "for_lines",
                        lambda lines, segments, block, whole=False: stamps)
    monkeypatch.setattr(listening_pass, "_encode", lambda *a: Path("episode_12_03_ffff0000.mp3"))
    monkeypatch.setattr(listening_pass, "_trim", lambda *a: Path("episode_12_03_eeee0000.mp3"))
    monkeypatch.setattr(listening_pass, "_install", lambda path: path.name)
    monkeypatch.setattr(listening_pass, "apply_changes",
                        lambda nid, fields, add, remove: writes.append((nid, fields)))
    # The pass itself asks Anki nothing: what it writes goes through `apply_changes`.
    monkeypatch.setattr(listening_pass, "anki",
                        lambda action, **p: anki_calls.append((action, p)), raising=False)
    monkeypatch.setattr(listening_pass, "unmark", cleared.append)
    monkeypatch.setattr(listening_pass, "ask_choice", lambda prompt, keys: "y")
    result = listening_pass.process(_Client(answer), [{"cardId": 100, "note": 1}],
                               {1: card, 2: other}, kinds.LISTENING, auto)
    return result, writes, cleared, anki_calls


ANSWER = {"changed": True, "reason": "whole sentence",
          "TranscriptLines": ["A：はい。", "B：そうですね。", "A：じゃあ。"],
          "TranslationLines": ["Yes.", "Right.", "Well then."],
          "KeyLines": {"1": 2, "2": 1}, "lost": []}


def test_the_new_extract_reaches_every_card_of_the_passage(monkeypatch):
    result, writes, cleared, anki_calls = _run(monkeypatch, ANSWER)
    assert result == (2, 1)
    assert [nid for nid, _fields in writes] == [1, 2]
    for _nid, fields in writes:
        assert fields["Audio"] == '<audio controls src="episode_12_03_ffff0000.mp3"></audio>'
        assert fields["Source"] == "Podcast - Episode 12 (01:08 → 01:39) https://example.org/12"
        assert fields["Timecodes"] == "0.40 2.10"
        assert fields["Transcript"].count("<br>") == 2
    assert "KeyLine" not in writes[0][1] and "KeyLine" not in writes[1][1]
    assert cleared == [100]


def test_the_old_extract_stays_for_a_restore_to_play(monkeypatch):
    """The snapshot taken before the run plays the old file: deleting it would
    leave a restored card silent. Anki's Check Media takes it once unused."""
    _result, _writes, _cleared, anki_calls = _run(monkeypatch, ANSWER)
    assert anki_calls == []


def test_a_question_that_loses_its_answer_waits_for_you(monkeypatch):
    result, writes, cleared, _calls = _run(monkeypatch, {**ANSWER, "lost": [2]})
    assert result == (0, 0)
    assert writes == [] and cleared == []


def test_an_extract_heard_right_only_loses_its_flag(monkeypatch):
    heard = listening.Heard(Path("extract.mp3"), 0.0, None, WINDOW, None)
    result, writes, cleared, anki_calls = _run(
        monkeypatch, {"changed": False, "reason": "right"}, heard=heard,
        stamps="0.22 1.48")
    assert result == (0, 1)
    assert writes == [] and anki_calls == [] and cleared == [100]


def test_instants_that_drifted_are_laid_again_on_their_own(monkeypatch):
    """The third way an extract is badly heard: the transcript is right, the
    seconds its lines jump to are not."""
    heard = listening.Heard(Path("extract.mp3"), 0.0, None, WINDOW, None)
    result, writes, cleared, anki_calls = _run(
        monkeypatch, {"changed": False, "reason": "right"}, heard=heard)
    assert result == (2, 1)
    assert [fields for _nid, fields in writes] == [{"Timecodes": "0.40 2.10"}] * 2
    assert anki_calls == []   # the same extract: no file to replace


def test_a_recording_found_but_not_matched_says_so(monkeypatch, capsys):
    """The recording was there: what failed is finding the extract in it."""
    heard = listening.Heard(Path("extract.mp3"), 0.0, None, WINDOW, None)
    _run(monkeypatch, {"changed": False, "reason": "right"}, heard=heard, stamps="0.22 1.48")
    out = capsys.readouterr().out
    assert "not found again in its recording" in out
    assert "recording not found" not in out


def test_a_source_without_bounds_says_so(monkeypatch, capsys):
    heard = listening.Heard(Path("extract.mp3"), 0.0, None, WINDOW, None)
    monkeypatch.setattr(listening_pass, "bounds_of", lambda source: None)
    _run(monkeypatch, {"changed": False, "reason": "right"}, heard=heard, stamps="0.22 1.48")
    out = capsys.readouterr().out
    assert "the Source field gives no bounds" in out
    assert "recording not found" not in out


def test_a_failure_that_is_not_the_model_is_not_called_an_ai_error(monkeypatch, capsys):
    """FFmpeg or Whisper missing, or Anki refusing the new extract: an "AI error"
    would send one to look at the key and the model."""
    def broken(*args):
        raise RuntimeError("ffmpeg not found")

    monkeypatch.setattr(listening_pass, "hear", broken)
    monkeypatch.setattr(listening_pass, "locate", lambda media: Path("episode 12.mp3"))
    monkeypatch.setattr(listening_pass, "in_pieces", lambda media, bounds: False)
    listening_pass.process(_Client(ANSWER), [{"cardId": 100, "note": 1}],
                           {1: CARD, 2: OTHER}, kinds.LISTENING, True)
    err = capsys.readouterr().err
    assert "ffmpeg not found" in err and "AI error" not in err


def test_a_model_that_fails_is_still_called_an_ai_error(monkeypatch, capsys):
    def refused(*args):
        raise RuntimeError("the model answered nothing")

    monkeypatch.setattr(listening_pass, "ask_transcript", refused)
    _run(monkeypatch, ANSWER)
    assert "AI error" in capsys.readouterr().err


# ── A past paper's reading time left inside the extract ───────────────────────

# Silences measured on such an extract: the scene-setting fades at 3.77, the
# reading time runs to 15.40, the bell to 17.83, and the voice comes in at 19.27.
PAPER_LENGTH = 45.94
PAPER_SILENCES = [(3.77, 15.4), (17.83, 19.27), (19.98, 20.61), (22.14, 22.82), (25.0, 25.66)]
PAPER = [
    Segment("先生と学生が話しています", 0.06, 3.7,
            (Word("先生と学生が", 0.06, 2.0), Word("話しています", 2.0, 3.6))),
    Segment("はい", 6.0, 6.8, (Word("はい", 6.0, 6.8),)),             # written in the blank
    # The first word laid inside the blank, the second over the bell.
    Segment("佐藤さん 旅行はどうだった", 7.0, 22.1,
            (Word("佐", 7.0, 7.0), Word("藤", 7.0, 19.6), Word("さん", 19.6, 19.98),
             Word(" 旅行はどうだった", 20.61, 22.1))),
    Segment("うん 楽しかったよ", 22.82, 25.0, (Word("うん", 22.82, 23.2), Word(" 楽しかったよ", 23.4, 25.0))),
]
PAPER_SOURCE = "JLPT 公式問題集 (2012) - N4 - 問題2 (02:29 → 03:29)"


def test_a_past_paper_extract_loses_the_reading_time_and_the_bell_left_in_it():
    block = listening.without_reading_time(PAPER, PAPER_SILENCES, PAPER_LENGTH)
    assert block.lines == (1, 3, 4)
    assert block.ranges == ((0.0, pytest.approx(4.07)), (pytest.approx(19.12), PAPER_LENGTH))


def test_a_bell_written_as_a_number_goes_with_the_reading_time():
    segments = [PAPER[0], Segment("2", 15.5, 16.2, (Word("2", 15.5, 16.2),)),
                Segment("佐藤さん 旅行はどうだった", 19.3, 22.1,
                        (Word("佐藤さん", 19.3, 19.98), Word(" 旅行はどうだった", 20.61, 22.1))),
                PAPER[3]]
    block = listening.without_reading_time(segments, PAPER_SILENCES, PAPER_LENGTH)
    assert block.lines == (1, 3, 4)
    assert block.ranges[1][0] == pytest.approx(19.12)


def test_an_extract_with_no_reading_time_inside_is_left_as_it_is():
    assert listening.without_reading_time(PAPER, PAPER_SILENCES[1:], PAPER_LENGTH) is None
    # A blank at either end is no reading time: the extract's bounds hold it.
    assert listening.without_reading_time(PAPER, [(0.0, 5.0), (40.0, PAPER_LENGTH)],
                                          PAPER_LENGTH) is None


def test_a_past_paper_is_told_by_its_source():
    assert jlpt_papers.names_a_paper(PAPER_SOURCE)
    assert not jlpt_papers.names_a_paper(SOURCE)


def test_the_recording_is_found_whatever_case_anki_gave_the_extract(monkeypatch, tmp_path):
    """Anki lowercases the name it stores, the cache keeps the downloaded one."""
    folder = tmp_path / "papers" / "jlpt2012-n4"
    folder.mkdir(parents=True)
    (folder / "N4_問題2.mp3").write_bytes(b"")
    monkeypatch.setattr(listening_pass.system, "cache_dir", lambda: tmp_path)
    media = listening.media_of(_note(5, Audio='<audio controls src="n4_問題2_02_3ff170ed.mp3"></audio>'))
    assert listening_pass.locate(media, []) == folder / "N4_問題2.mp3"


def test_an_extract_shorter_than_its_bounds_is_made_of_pieces(monkeypatch):
    from kotogen.generators import nhk

    monkeypatch.setattr(listening_pass, "_media_path", lambda media: Path("extract.mp3"))
    media = listening.media_of(CARD)
    monkeypatch.setattr(nhk, "probe_duration", lambda path: PAPER_LENGTH)
    assert listening_pass.in_pieces(media, (149.0, 209.0))
    monkeypatch.setattr(nhk, "probe_duration", lambda path: 59.4)   # the bounds' rounding
    assert not listening_pass.in_pieces(media, (149.0, 209.0))
    monkeypatch.setattr(nhk, "probe_duration", lambda path: None)
    assert not listening_pass.in_pieces(media, (149.0, 209.0))
    assert not listening_pass.in_pieces(media, None)


TRIMMED = listening.Heard(Path("extract.mp3"), 0.0, None, PAPER,
                          Block((1, 3, 4), ((0.0, 4.07), (19.12, PAPER_LENGTH))), trimmed=True)


def test_an_extract_made_of_pieces_is_heard_as_it_stands(monkeypatch, capsys):
    """Cut again in one span from its recording, it would get back the exam
    question the split left out between its pieces."""
    asked = []

    def hear(media, bounds, recording, work, models, paper):
        asked.append((recording, paper))
        return TRIMMED

    card = {**CARD, "fields": {**CARD["fields"], "Source": PAPER_SOURCE}}
    _run(monkeypatch, {"changed": False, "reason": "right"}, card=card, pieced=True, hear=hear)
    assert asked == [(None, True)]
    # The reading time cut out is the fix: nothing to warn about.
    assert "made of pieces" not in capsys.readouterr().out


def test_an_extract_made_of_pieces_with_nothing_to_cut_says_its_bounds_hold(monkeypatch, capsys):
    heard = listening.Heard(Path("extract.mp3"), 0.0, None, WINDOW, None)
    _run(monkeypatch, {"changed": False, "reason": "right"}, heard=heard, pieced=True)
    assert "made of pieces" in capsys.readouterr().out


def test_the_extract_without_its_reading_time_reaches_every_card(monkeypatch, capsys):
    result, writes, cleared, anki_calls = _run(
        monkeypatch, {"changed": False, "reason": "right"}, heard=TRIMMED, pieced=True)
    assert result == (2, 1) and cleared == [100]
    for _nid, fields in writes:
        assert fields["Audio"] == '<audio controls src="episode_12_03_eeee0000.mp3"></audio>'
        assert fields["Timecodes"] == "0.40 2.10"
        assert "Source" not in fields              # its bounds in the recording hold
    assert "00:04 → 00:19" in capsys.readouterr().out


def test_the_other_cards_of_the_passage_are_named_before_the_question_only(monkeypatch, capsys):
    """In automatic mode the closing line counts them already."""
    _run(monkeypatch, ANSWER)
    assert "other card of the passage changes" not in capsys.readouterr().out
    _run(monkeypatch, ANSWER, auto=False)
    assert "1 other card of the passage changes with it" in capsys.readouterr().out
