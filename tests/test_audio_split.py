"""Splitting a collection without letting in what is not the conversation.

A piece must hold only the exchange: an announced number, a bell or a clipped
first mora spoils the card, and only shows at review, once the AI call is paid.
A doubtful answer from the model is dropped, never repaired, and the log never
quotes the audio. The fixtures keep timings and silences measured on real
recordings; their words are invented stand-ins of the same shape.
"""

from __future__ import annotations

import argparse
import builtins
import math
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from kotogen import console, i18n
from kotogen.ai_client import AITruncatedError
from kotogen.generators import announcements, audio, audio_split, cuts, quota, whisper

# Any Japanese character: none may show in the splitting's output.
JAPANESE = re.compile(r"[぀-ヿ㐀-鿿]")


def seg(text: str, start: float, end: float, words=()) -> audio_split.Segment:
    return audio_split.Segment(
        text, start, end,
        tuple(audio_split.Word(t, d, f) for t, d, f in words))


# Six lines: a title, two exchanges, the exam question.
SEGMENTS = [
    seg("セクション10", 0.0, 2.0),
    seg("ねえ、見て。", 4.0, 5.5),
    seg("わー、大きい荷物だ。どこ行くの?", 6.0, 8.5),
    seg("明日から、友達と山に登るんだ。上着持ったほうがいいんじゃない?", 9.0, 13.0),
    seg("すみません、電車に切符を忘れてきちゃったんですけど。", 20.0, 24.0),
    seg("男の人はこのあと何をしますか。", 30.0, 32.0),
]

SILENCES = [(2.0, 4.0), (13.0, 20.0), (24.0, 30.0), (32.0, math.inf)]


# ── Real silences ─────────────────────────────────────────────────────────────

def test_reading_the_silencedetect_output(monkeypatch):
    output = (
        b"[silencedetect @ 0x1] silence_start: 3.5\n"
        b"[silencedetect @ 0x1] silence_end: 5.25 | silence_duration: 1.75\n"
        b"[silencedetect @ 0x1] silence_start: 40.125\n"
    )
    monkeypatch.setattr(cuts.shutil, "which", lambda name: "ffmpeg")
    monkeypatch.setattr(cuts.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(stderr=output))

    silences = cuts.detect_silences(Path("x.mp3"))

    assert silences[0] == (3.5, 5.25)
    # A file ending in silence: ffmpeg opens the silence and never closes it.
    # An infinite end is right, the tail margin bounding the trail.
    assert silences[1][0] == 40.125 and math.isinf(silences[1][1])


def test_without_ffmpeg_the_splitting_carries_on_degraded(monkeypatch, capsys):
    """A less clean cut is worth more than a lost file."""
    monkeypatch.setattr(cuts.shutil, "which", lambda name: None)
    assert cuts.detect_silences(Path("x.mp3")) == []
    assert "ffmpeg" in capsys.readouterr().err


# ── Where the cut falls ───────────────────────────────────────────────────────

def test_the_cut_falls_in_the_silence_before_it():
    """Neither before its start - the bell would come in - nor after the attack -
    a mora would be clipped."""
    cut = cuts.cut_start(7.2, [(5.0, 7.0)])
    assert 5.0 < cut < 7.2


def test_the_cut_never_goes_back_over_the_silence():
    """Whatever happens, what precedes the silence (number, bell) stays out."""
    for silence in [(5.0, 5.4), (5.0, 7.0), (5.0, 30.0)]:
        assert cuts.cut_start(silence[1] + 0.1, [silence]) >= silence[0]


def test_with_no_silence_the_cut_falls_back_on_a_margin():
    cut = cuts.cut_start(7.2, [])
    assert 7.0 < cut <= 7.2


def test_the_cut_does_not_encroach_on_the_previous_block():
    assert cuts.cut_start(7.2, [(5.0, 7.0)], floor=6.9) == 6.9


def test_a_silence_already_begun_is_the_right_silence():
    """Whisper stretches a segment's bound into the gap after it, so the
    fade-out falls inside the silence. A silence required to start after the
    fade-out would be the next one, past the announcement."""
    silences = [(13.67, 15.71), (15.92, 17.01)]     # the announcement sits between

    assert cuts.cut_end(14.0, silences) < 15.71, \
        "the cut jumps over the announcement, into the silence after it"
    # A real trail, without crossing two seconds of gap onto the digit.
    assert 14.0 <= cuts.cut_end(14.0, silences) <= 14.5

    # Symmetrical: a silence already begun serves to open too.
    assert 15.92 < cuts.cut_start(17.0, [(15.92, 17.01)]) <= 17.0


def test_a_cut_that_fell_inside_the_number_is_pushed_back():
    """Whisper declares the conversation at 6.58 s, inside the announced digit,
    and the piece would open mid-syllable. The signal separates them: the
    announcement at 6.34-6.95, a 0.68 s gap, then speech at 7.63."""
    silences = [(4.80, 6.34), (6.95, 7.63), (8.26, 8.96)]
    cut = cuts.cut_start(6.58, silences, floor=6.58)

    assert cut >= 6.95, "the piece opens in the middle of the announced digit"
    assert cut <= 7.63, "the first mora is clipped"


def test_an_announcement_welded_to_the_speech_is_left_alone():
    """With no gap between the digit and the conversation (a 3.7 s run of
    sound), pushing the cut back would swallow a whole line, worse than a
    slightly short start. The length of the run decides."""
    silences = [(59.93, 61.19), (64.87, 65.76)]
    assert cuts.cut_start(61.52, silences, floor=61.52) == 61.52


def test_the_end_stays_short_of_the_next_sound():
    """Symmetrical: the trail is left, the next announcement is not."""
    end = cuts.cut_end(19.8, [(20.0, 23.0)])
    assert 19.8 <= end < 23.0


def test_a_silent_end_of_file_does_not_blow_the_bound_up():
    end = cuts.cut_end(31.9, [(32.0, math.inf)])
    assert math.isfinite(end) and 31.9 <= end < 33.0


# ── Subtitle bounds, with no per-word timestamps ──────────────────────────────

# A YouTube track's cues run end to end: a cue ends when the next is DISPLAYED,
# not on its last syllable. The signal puts the speech at 11.2-13.9, between two
# measured silences.
CUE = seg("明日から、友達と山に登るんだ。上着持ったほうがいいんじゃない?", 10.0, 14.5)
CUES = [seg("前の会話です。", 2.0, 10.0), CUE, seg("わー、大きい荷物だ。", 14.5, 20.0)]
CUE_SILENCES = [(9.5, 11.2), (13.9, 14.6)]

# The same text timestamped by Whisper: the working path, which none of these
# tests may move by a hundredth.
WORDS = seg("明日から、友達と山に登るんだ。", 10.0, 14.5,
           [("明日から、友達と", 10.4, 12.0), ("山に登るんだ。", 12.0, 13.5)])


def test_a_cue_end_fallen_in_the_silence_comes_back_to_the_speech():
    """A cue ends when the subtitle disappears, not when the sentence does. As
    `cut_end` never closes BEFORE the fade-out it is given, the extract would
    cross the pause onto the next line."""
    assert cuts._spoken_end(CUE, CUE_SILENCES) == 13.9
    assert cuts._spoken_end(CUE) == 14.5, "with no measured silence, the bound holds"


def test_a_cue_shown_before_the_sentence_opens_on_the_speech():
    """Symmetrical: a cue shown 1.2 s early would open the extract on a gap."""
    assert cuts._spoken_start(CUE, CUE_SILENCES) == 11.2
    assert cuts._spoken_start(CUE) == 10.0


def test_a_cue_laid_on_silence_keeps_its_bounds():
    """A badly aligned cue has no speech under it: realigning would empty the
    segment, and an empty range drops the block. The declared bound stays."""
    assert cuts._spoken_start(CUE, [(9.0, 20.0)]) == 10.0
    assert cuts._spoken_end(CUE, [(9.0, 20.0)]) == 14.5


def test_a_timestamped_segment_never_looks_at_the_signal():
    """Word timestamps already fit the speech: the silences move nothing."""
    assert cuts._spoken_end(WORDS, [(0.0, 100.0)]) == 13.5
    assert cuts._spoken_start(WORDS, [(0.0, 100.0)]) == 10.4
    assert cuts._margin(WORDS) == cuts.NO_SILENCE_MARGIN


def test_with_no_measured_silence_a_cue_bound_keeps_more_room():
    """Under opening or closing music `silencedetect` finds nothing, and the
    fallback margin alone separates the cut from the speech. A cue bound, laid
    by hand, errs more than a word timestamp, so it gets the wider margin."""
    assert cuts._margin(CUE) == cuts.NO_WORDS_MARGIN
    assert cuts.NO_WORDS_MARGIN > cuts.NO_SILENCE_MARGIN
    cut = cuts.cut_start(10.0, [], margin=cuts.NO_WORDS_MARGIN)
    assert cut == pytest.approx(10.0 - cuts.NO_WORDS_MARGIN)


def test_the_floor_of_a_cue_does_not_remove_the_attack_margin():
    """The floor is the end of the previous line, which for cues laid end to end
    is this one's start: no attack margin is left, and a cue a tenth late clips
    the first mora. Realigned on the signal, that end is an end of speech."""
    bound = cuts.bound_before(11.2, CUE, CUES, 2, 0.0, CUE_SILENCES)
    assert bound <= 9.5 + cuts.EDGE_MARGIN, "the floor sticks to the attack"


def test_a_subtitle_extract_holds_inside_the_speech():
    """End to end: the extract holds inside the speech (11.2-13.9), not between
    the display of the cue and of the next one (10.0-14.5)."""
    split = audio_split._read_answer(
        {"kind": "stream",
         "blocks": [{"keep": False, "lines": [[1, 1]], "pattern": "off topic"},
                   {"keep": True, "lines": [[2, 2]]},
                   {"keep": False, "lines": [[3, 3]], "pattern": "off topic"}]},
        CUES, CUE_SILENCES)

    block = split.blocks[0]
    assert 11.0 <= block.start <= 11.2, "the extract opens on a gap"
    assert 13.9 <= block.end <= 14.5, "the extract spills onto the next line"
    assert block.start > CUE.start and block.end < CUE.end


# ── The marker glued to the first line ────────────────────────────────────────

# Whisper gives `4 あっそれ` back as ONE segment, number included.
GLUED = seg("4 あっそれ", 10.0, 12.0,
            [("4", 10.0, 10.4), ("あっ", 10.9, 11.2), ("それ", 11.2, 12.0)])


def test_the_announced_number_stays_out():
    """Without word timestamps the cut would start at 10.0 s, on the number:
    what `start_word` is for."""
    silences = [(10.4, 10.9)]

    attack = cuts.word_moment(GLUED, "あっ")
    assert attack == 10.9

    with_marker = cuts.cut_start(attack, silences)
    without_marker = cuts.cut_start(GLUED.start, silences)
    assert with_marker > 10.4 >= without_marker   # the number ends at 10.4 s
    assert with_marker < 10.9                     # and the speech is not clipped


def test_the_word_is_looked_for_on_the_glued_text_not_token_by_token():
    """Whisper splits Japanese words arbitrarily: the word the model gives back
    may cover several tokens or half of one."""
    assert cuts.word_moment(GLUED, "あっそれ") == 10.9
    assert cuts.word_moment(GLUED, "それ", end=True) == 12.0


def test_what_counts_as_an_announcement_number():
    """A number counts in any spelling Whisper gives it; an ordinary word that
    starts with a digit's reading (にほん, さんぽ) does not."""
    for text in ("4", "10", "１", "に", "さん", "じゅういち",
                  "1番", "第4問", "問題2", "5番目"):
        assert announcements.is_marker(text), text
    for text in ("", "そうですか", "にほん", "さんぽ", "ごはん", "くるま",
                  "しごと", "第一印象", "4時に会いましょう"):
        assert not announcements.is_marker(text), text


def test_the_number_counts_in_kanji_and_katakana_too():
    """A number announced alone is exactly where Whisper writes 「二」 or 「ニ」
    rather than 「に」."""
    for text in ("一", "二", "三", "十", "第三問", "十二",
                  "イチ", "ニ", "サン", "ナンバー4", "その2"):
        assert announcements.is_marker(text), text
    # And what carries a number without being an announcement stays out.
    for text in ("一昨日", "十分だと思う", "二人で行った", "三日月"):
        assert not announcements.is_marker(text), text


def test_kana_readings_do_not_chain_freely():
    """「いちご」 is a strawberry, not "one-five": chaining readings freely would
    take it for an announcement and clip the conversation's first word."""
    for text in ("じゅういち", "にじゅう", "にじゅうさん", "ジュウニ"):
        assert announcements.is_marker(text), text
    for text in ("いちご", "ごろく", "しちご", "ろくに"):
        assert not announcements.is_marker(text), text


def test_an_announcement_scattered_over_tokens_goes_out_whole():
    """Whisper splits an announcement in several ways: reading only the first
    token would leave 「ばん」 or 「問」 at the head of the card."""
    scattered = seg("第4問 あっそれ", 10.0, 13.0,
                 [("第", 10.0, 10.2), ("4", 10.2, 10.5), ("問", 10.5, 10.8),
                  ("あっ", 11.3, 11.6), ("それ", 11.6, 13.0)])
    assert announcements.head_announcement(scattered.words) == 3
    assert announcements.attack_after_marker(scattered) == 11.3

    ban = seg("に番 昨日の話", 20.0, 24.0,
              [("に", 20.0, 20.3), ("番", 20.3, 20.6), ("昨日の", 21.2, 24.0)])
    assert announcements.attack_after_marker(ban) == 21.2

    # The punctuation after the number belongs to the number, not to the speech.
    punctuated = seg("1. ねえこれ", 10.0, 13.0,
                  [("1", 10.0, 10.4), ("。", 10.4, 10.4), ("ねえ", 10.9, 13.0)])
    assert announcements.head_announcement(punctuated.words) == 2
    assert announcements.attack_after_marker(punctuated) == 10.9


def test_a_head_that_is_not_an_announcement_trims_nothing():
    ordinary = seg("そうですか", 0.0, 2.0,
                    [("そう", 0.0, 1.0), ("ですか", 1.0, 2.0)])
    assert announcements.head_announcement(ordinary.words) is None
    # A segment that is ONLY the announcement has no speech to open on: the
    # whole line leaves the block, elsewhere.
    alone = seg("4", 10.0, 10.5, [("4", 10.0, 10.5)])
    assert announcements.attack_after_marker(alone, collection=True) is None


def test_a_glued_number_is_spotted_without_the_model():
    """The model sometimes leaves `start_word` out: the gap after the number is
    enough to recognise it."""
    assert announcements.attack_after_marker(GLUED) == 10.9

    # The spoken numbers Whisper writes in kana: に = 2, さん = 3.
    kana = seg("に 昨日の野球の試合見た", 20.0, 24.0,
               [("に", 20.0, 20.3), ("昨日の", 21.0, 21.6), ("野球", 21.6, 24.0)])
    assert announcements.attack_after_marker(kana) == 21.0


def test_a_katakana_mora_is_not_a_number():
    """Whisper splits katakana mora by mora, and ク or シ reads as a digit: the
    net would eat the card's first mora. Hiragana is not split that way, and
    「に」 or 「さん」 do announce passages on a shadowing book, so it stays."""
    kurisu = seg("クララさんの国は", 100.02, 103.54,
                 [("ク", 100.02, 100.30), ("ラ", 100.30, 100.50),
                  ("ラ", 100.50, 100.58)])
    single = seg("シルクのシャツはいくらですか?", 16.66, 18.98,
                 [("シ", 16.66, 17.04), ("ル", 17.04, 17.28), ("ク", 17.28, 17.44)])
    for segment in (kurisu, single):
        assert announcements.attack_after_marker(segment, collection=True) is None

    assert announcements.attack_after_marker(GLUED) == 10.9          # a digit
    kana = seg("に 昨日の話", 20.0, 24.0,
               [("に", 20.0, 20.3), ("昨日の", 21.0, 21.6)])
    assert announcements.attack_after_marker(kana) == 21.0           # hiragana


def test_a_digit_of_the_conversation_is_not_an_announcement_number():
    """「4」「時に」 is an appointment at four o'clock, not passage number four:
    the counter that follows decides, even inside a collection."""
    appointment = seg("4時に会いましょう", 10.0, 12.0,
                      [("4", 10.0, 10.2), ("時に", 10.2, 10.8),
                       ("会いましょう", 10.8, 12.0)])
    assert announcements.attack_after_marker(appointment, collection=True) is None
    assert announcements.attack_after_marker(seg("こんにちは", 0.0, 1.0)) is None


def test_in_a_collection_the_gap_is_not_required():
    """Outside a collection a gap must separate the number from the speech; in
    one, passages ARE announced and the gap is often too short to measure."""
    tight = seg("に 昨日の話", 20.0, 24.0,
                [("に", 20.0, 20.3), ("昨日の", 20.4, 21.0), ("話", 21.0, 24.0)])
    assert announcements.attack_after_marker(tight) is None          # a 0.1 s gap
    assert announcements.attack_after_marker(tight, collection=True) == 20.4


# ── The cut never goes back over what was excluded ────────────────────────────

def test_the_cut_does_not_go_back_over_the_announced_number():
    """Silence, the number, then a 0.2 s gap too short for `silencedetect`: the
    silence nearest the attack is the one BEFORE the number, and the cut must
    not land there, however right the model's answer."""
    silences = [(19.0, 21.5)]           # the big silence BEFORE the number
    number = audio_split.Word("に", 21.5, 21.8)
    opening = audio_split.Segment("に 昨日の話", 21.5, 26.0,
                                (number, audio_split.Word("昨日の", 22.0, 22.6)))
    previous = audio_split.Segment("前の会話", 10.0, 19.0)

    bound = cuts.bound_before(22.0, opening, [previous, opening], 2, 0.0)
    cut = cuts.cut_start(22.0, silences, bound)

    assert cut >= number.end, "the announced number is inside the piece"
    assert cut <= 22.0, "the first mora is clipped"


def test_the_cut_does_not_go_down_over_the_next_number():
    """The mirror case: the fade-out, a 0.2 s gap too short for `silencedetect`,
    then the next number. The silence nearest the fade-out is the one after that
    number, where `cut_end` would land without a ceiling."""
    silences = [(26.5, 29.0)]           # the big silence AFTER the number
    closing = audio_split.Segment("それはよかったね", 20.0, 26.0,
                                (audio_split.Word("それは", 20.0, 23.0),
                                 audio_split.Word("よかったね", 23.0, 26.0)))
    next_line = audio_split.Segment("さん", 26.2, 26.5,
                                  (audio_split.Word("さん", 26.2, 26.5),))

    bound = cuts.bound_after(26.0, closing, [closing, next_line], 1, math.inf)
    cut = cuts.cut_end(26.0, silences, bound)

    assert cut <= next_line.start, "the number of the next passage closes the card"
    assert cut >= 26.0, "the last syllable is clipped"


def test_the_ceiling_never_falls_short_of_the_fade_out():
    """Otherwise the cut would close before the last syllable."""
    closing = audio_split.Segment("あ", 10.0, 12.0,
                                (audio_split.Word("あ", 10.0, 12.0),))
    assert cuts.bound_after(12.0, closing, [closing], 1, ceiling=0.0) == 12.0


def test_an_announcement_glued_to_the_line_end_is_cut_away():
    """Whisper sometimes closes the last line of the passage on the number of
    the next one."""
    glued = seg("それはよかったね さん", 20.0, 26.5,
                [("それは", 20.0, 23.0), ("よかったね", 23.0, 26.0),
                 ("さん", 26.4, 26.5)])
    assert announcements.tail_announcement(glued.words) == 2
    assert announcements.fade_before_marker(glued) == 26.0

    # An announcement scattered over tokens is cut away whole, suffix included.
    scattered = seg("よかったね 第三問", 20.0, 27.0,
                 [("よかったね", 20.0, 26.0), ("第", 26.5, 26.6),
                  ("三", 26.6, 26.8), ("問", 26.8, 27.0)])
    assert announcements.tail_announcement(scattered.words) == 1
    assert announcements.fade_before_marker(scattered) == 26.0


def test_the_tail_net_does_not_rely_on_a_gap_whisper_never_writes():
    """Whisper's timestamps come from an alignment, not from the signal: its
    words follow each other with no hole even over a one-second breath, so a gap
    before the number can never be required."""
    contiguous = seg("それはよかったね さん", 20.0, 26.4,
                   [("それは", 20.0, 23.0), ("よかったね", 23.0, 26.0),
                    ("さん", 26.0, 26.4)])          # no hole at all: 26.0 = 26.0
    assert announcements.tail_announcement(contiguous.words) == 2, "the number is seen"
    assert announcements.fade_before_marker(contiguous, collection=True) == 26.0


def test_a_verb_ending_is_not_taken_for_a_number():
    """Whisper may isolate the 「く」 of 「行く」 as the last token, and く reads as
    9: with no gap to decide, the net would cut the conversation's last mora. A
    written digit is still cut away."""
    verb = seg("ドライブでも行く?", 96.96, 97.52,
                [("でも", 96.96, 97.12), ("行", 97.12, 97.34), ("く?", 97.34, 97.52)])
    assert announcements.tail_announcement(verb.words) == 2, "the 「く」 does look like a 9"
    assert announcements.fade_before_marker(verb, collection=True) is None

    digit = seg("よかったね 3", 20.0, 26.4,
                  [("よかったね", 20.0, 26.0), ("3", 26.0, 26.4)])
    assert announcements.fade_before_marker(digit, collection=True) == 26.0


def test_the_adverb_ichiban_is_not_cut_away():
    """「一番」 meaning "the most" is written like the number 1. At the head the
    counter that follows decides; at the tail nothing follows, so the last word
    is kept rather than risked."""
    for words in ([("これが", 20.0, 22.5), ("一番", 22.5, 23.0)],
                 [("これが", 20.0, 22.5), ("一番", 23.5, 24.0)]):
        adverb = seg("これが一番", 20.0, words[-1][2], words)
        assert announcements.fade_before_marker(adverb, collection=True) is None


def test_an_announcement_line_at_the_block_tail_leaves_it_too():
    """The model often files the next passage's announcement with the
    conversation just ended; it must leave the sound AND the transcript."""
    segments = [
        seg("ねえ、見て。わー、大きい荷物だ。", 2.0, 5.0),
        seg("明日から、友達と山に登るんだ。", 5.5, 9.0),
        seg("上着持ったほうがいいんじゃない?", 9.5, 13.0),
        seg("さん", 14.0, 14.5),
    ]
    split = audio_split._read_answer(
        {"kind": "collection", "blocks": [{"keep": True, "lines": [[1, 4]]}]},
        segments, [(13.0, 14.0)])

    block = split.blocks[0]
    assert block.lines == (1, 2, 3)
    assert block.end <= 14.0            # the next announcement starts at 14.0 s
    assert "さん" not in "".join(block.texts(segments))


def test_an_overflowing_segment_bound_does_not_cross_the_ceiling():
    """Whisper may close a segment right onto the next announcement. `cut_end`
    and `bound_after` never close BEFORE the fade-out they are given, so neither
    can correct a wrong one."""
    segments = [
        audio_split.Segment(
            "ねえ、見て。わー、大きい荷物だ。どこ行くの? 上着持ったほうがいいんじゃない?",
            10.0, 27.8,                       # 27.8 s declared: past the number
            (audio_split.Word("ねえ、見て。わー、大きい荷物だ。どこ行くの?", 10.0, 20.0),
             audio_split.Word("上着持ったほうがいいんじゃない?", 20.0, 26.0))),
        audio_split.Segment("さん", 27.5, 27.9,
                            (audio_split.Word("さん", 27.5, 27.9),)),
    ]
    split = audio_split._read_answer(
        {"kind": "collection",
         "blocks": [{"keep": True, "lines": [[1, 1]]},
                   {"keep": False, "lines": [[2, 2]], "pattern": "number"}]},
        segments, [(26.0, 27.5), (27.9, 29.5)])

    assert split.blocks[0].end <= 27.5, "the next announcement closes the card"
    assert split.blocks[0].end >= 26.0, "the last syllable is clipped"


def test_an_announcement_that_lasts_too_long_is_not_one():
    """「第三問」 holds in one second. A first token that stretches over three
    seconds is a sentence, and skipping it would clip the conversation."""
    slow = seg("に 昨日の話", 20.0, 26.0,
               [("に", 20.0, 23.5), ("昨日の", 24.0, 26.0)])
    assert announcements.attack_after_marker(slow, collection=True) is None


def test_the_floor_sets_on_the_speech_not_on_the_segment_bound():
    """Whisper closes a segment after its last syllable, into the silence. Taken
    as the floor, that bound eats the gap before the attack, and the piece opens
    right on the first mora."""
    number = audio_split.Segment("に", 21.0, 22.5,       # 1.5 s declared...
                                 (audio_split.Word("に", 21.0, 21.4),))  # ...0.4 s spoken
    opening = audio_split.Segment("昨日の話", 22.6, 26.0,
                                (audio_split.Word("昨日の", 22.6, 26.0),))

    bound = cuts.bound_before(22.6, opening, [number, opening], 2, 0.0)
    assert bound == pytest.approx(21.4), "the silence Whisper declares acts as the floor"

    cut = cuts.cut_start(22.6, [], bound)
    assert cut < 22.6, "the piece opens right on the first mora"


def test_an_announcement_whisper_places_inside_the_speech_is_no_floor():
    """Whisper puts the "6" at 61.04-61.52, inside the speech; the signal has a
    short sound at 59.56-59.93, a 1.3 s gap, then the conversation at 61.19. The
    floor steps back only when the declared bound sits in a run too long for an
    announcement and a short sound is found just before the gap."""
    silences = [(57.82, 59.56), (59.93, 61.19), (64.87, 65.76)]
    announcing = audio_split.Segment("6", 61.04, 61.52,
                                  (audio_split.Word("6", 61.04, 61.52),))
    opening = audio_split.Segment("友達でも、言えないことはあるよ", 61.52, 65.02,
                                (audio_split.Word("友", 61.52, 61.52),
                                 audio_split.Word("達", 61.52, 61.82)))
    previous = audio_split.Segment("おいしかったんだよ", 54.02, 59.22,
                                    (audio_split.Word("よ", 57.54, 59.22),))

    bound = cuts.bound_before(61.52, opening, [previous, announcing, opening],
                              3, 0.0, silences)
    cut = cuts.cut_start(61.52, silences, bound)

    assert cut <= 61.19, "the first words of the conversation are lost"
    assert cut >= 59.93, "the announcement comes into the piece"


def test_a_word_of_zero_length_does_not_raise_the_floor():
    """Whisper writes them when it laid a boundary too late. Such a word "ends
    before the attack" without preceding anything: counted, it would raise the
    floor onto the attack itself."""
    opening = audio_split.Segment("友達", 61.52, 65.02,
                                (audio_split.Word("友", 61.52, 61.52),
                                 audio_split.Word("達", 61.52, 61.82)))
    assert cuts.bound_before(61.52, opening, [opening], 1, 0.0) == 0.0

    # A word really before the attack still counts.
    assert cuts.bound_before(10.9, GLUED, [GLUED], 1, 0.0) == 10.4


def test_the_bound_never_goes_past_the_attack():
    """Otherwise the piece would open in the middle of the first syllable."""
    opening = audio_split.Segment("あ", 10.0, 12.0,
                                (audio_split.Word("あ", 10.0, 11.9),))
    assert cuts.bound_before(10.5, opening, [opening], 1, floor=99.0) == 10.5


def test_a_number_alone_on_its_line_leaves_the_block():
    """Filed with the conversation rather than dropped, it would go out in the
    sound AND in the transcript sent to the generator."""
    segments = [
        seg("4", 0.0, 0.5),
        seg("ねえ、見て。わー、大きい荷物だ。", 2.0, 5.0),
        seg("明日から、友達と山に登るんだ。", 5.5, 9.0),
        seg("上着持ったほうがいいんじゃない?", 9.5, 13.0),
    ]
    split = audio_split._read_answer(
        {"kind": "collection", "blocks": [{"keep": True, "lines": [[1, 4]]}]},
        segments, [(0.5, 2.0)])

    block = split.blocks[0]
    assert block.lines == (2, 3, 4)
    assert block.start >= 0.5          # the number fades at 0.5 s
    assert "4" not in "".join(block.texts(segments))


def test_a_start_marker_that_keeps_the_number_is_not_taken_at_its_word():
    """The model often gives `"4あっ"` where `"あっ"` is expected. Taken at its
    word, it would put the number back in the card and bypass the deterministic
    net, which finds it."""
    segments = [
        seg("前の会話です。", 0.0, 8.0),
        seg("4 あっそれ、明日から、友達と山に登るんだ。",
            10.0, 20.0,
            [("4", 10.0, 10.4), ("あっ", 10.9, 11.2), ("それ", 11.2, 20.0)]),
        seg("わー、大きい荷物だ。上着持ったほうがいいんじゃない?", 20.5, 26.0),
    ]
    split = audio_split._read_answer(
        {"kind": "collection",
         "blocks": [{"keep": False, "lines": [[1, 1]], "pattern": "transition"},
                   {"keep": True, "lines": [[2, 3]], "start_word": "4あっ"}]},
        segments, [(8.0, 10.0), (10.4, 10.9)])

    assert split.blocks[0].start >= 10.4, "the announced number is inside the piece"
    assert split.blocks[0].start <= 10.9, "the first mora is clipped"


def test_an_absent_word_leads_to_no_guessing():
    assert cuts.word_moment(GLUED, "こんにちは") is None
    assert cuts.word_moment(GLUED, "") is None
    assert cuts.word_moment(seg("あっそれ", 10.0, 12.0), "あっ") is None


# ── The rank of the item, read off the announced number ───────────────────────
# The number also says which item a passage comes from, which no official file
# name says: `N5Q1.mp3` carries the whole 問題1, its items one after another.


def announcing(text: str, *words) -> audio_split.Segment:
    """A segment opened by an announcement, split into words as Whisper does."""
    return seg(text, 0.0, 5.0, [(m, 0.5 * i, 0.5 * i + 0.4)
                                 for i, m in enumerate(words)])


@pytest.mark.parametrize("text,value", [
    ("1", 1), ("１", 1), ("三", 3), ("十二", 12), ("じゅうに", 12),
    ("に", 2), ("サン", 3), ("きゅう", 9), ("", None), ("こんにちは", None),
])
def test_the_value_of_a_number_reads_in_all_three_spellings(text, value):
    """Whisper spells the same number as a digit, kana or kanji."""
    assert announcements.number_value(text) == value


def test_the_rank_reads_at_the_head_of_the_setting_up():
    """The commonest form: Whisper glues the number to the sentence after it."""
    segment = announcing("3番 友達から電話がありました", "3", "番", " 友", "達", "から")
    assert announcements.announced_item(segment) == 3


def test_a_section_number_is_not_an_item_rank():
    """「問題1」 opens a whole section: read as item 1, it would put the first
    item's figure on another item's conversation."""
    assert announcements.announced_item(announcing("問題1", "問題", "1")) is None


def test_a_bare_number_is_not_an_item_rank():
    """Whisper may write the bell between two items as a digit: without the
    「ばん」, nothing tells it apart from an announced number."""
    assert announcements.announced_item(announcing("2", "2")) is None


def test_the_rank_is_not_looked_for_mid_line():
    """A 「1番」 inside the worked example's answer is no announcement: only the
    tokens recognised as the announcement, those taken out of the sound, are
    read."""
    segment = announcing("最も良いものは1番です", "最も", "良い", "ものは", "1", "番", "です")
    assert announcements.announced_item(segment) is None


def test_the_superlative_of_the_instruction_is_not_item_one():
    """The instruction opening every past-paper section uses 「一番」 as an
    adverb. Read as item 1, it would announce that rank several times per file,
    and a rank announced twice is not placed: item 1 would lose its figure."""
    segment = announcing("一番いいものを一つ選んでください",
                         "一番", "いい", "ものを", "一つ", "選んで", "ください")
    assert announcements.announced_item(segment) is None


def test_the_answer_of_the_example_is_not_item_one_either():
    """The worked example's answer opens on the same adverb, which Whisper may
    write 「1番」 in the same file."""
    segment = announcing("1番いいものは 3番です", "1", "番", "いい", "ものは", "3", "番", "です")
    assert announcements.announced_item(segment) is None


def test_item_one_still_reads_when_its_conversation_follows():
    """What separates the two is the word after it: an announced item is
    followed by the setting up of its conversation, which is a noun."""
    segment = announcing("一番 男の人と女の人が話しています",
                         "一番", " 男", "の人", "と女", "の人", "が話", "しています")
    assert announcements.announced_item(segment) == 1


def test_a_rank_announced_twice_is_not_read():
    """Whisper may repeat an announcement over the bell that ends the reading
    time, in front of ANOTHER item's conversation: between two occurrences,
    nothing says which is the real one."""
    segments = [announcing("1番", "1", "番"), seg("会話", 1.0, 2.0),
                announcing("2番", "2", "番"), seg("会話", 3.0, 4.0),
                announcing("2番", "2", "番"), seg("会話", 5.0, 6.0)]
    assert announcements.unique_items(segments) == frozenset({1})


def test_the_rank_reads_on_the_line_before_too():
    """An announcement alone on its line gives its rank to the block opened by
    the next line."""
    segments = [announcing("4番", "4", "番"), seg("すみません", 1.0, 2.0)]
    uniques = announcements.unique_items(segments)
    assert announcements.block_item(segments, [2], uniques) == 4


def test_nothing_is_looked_for_higher_than_the_line_before():
    """Two lines up is already another item's announcement, and a wrong figure
    is worse than none."""
    segments = [announcing("4番", "4", "番"), seg("会話", 1.0, 2.0),
                seg("会話", 3.0, 4.0)]
    uniques = announcements.unique_items(segments)
    assert announcements.block_item(segments, [3], uniques) is None


def test_the_rank_of_the_block_is_never_a_fallback():
    """The worked example and the dropped passages shift the count, so the first
    block kept is rarely item 1: with no announcement read, no rank."""
    split = audio_split._read_answer(
        {"kind": "collection", "blocks": [{"keep": True, "lines": [[2, 4]]}]},
        SEGMENTS, SILENCES)
    assert split.blocks[0].item is None


def test_the_rank_survives_the_removal_of_the_announcement_line():
    """The announcement line leaves the block, so its rank is read first."""
    segments = [seg("title", 0.0, 1.0),
                announcing("2番", "2", "番"),
                seg("男の人と女の人が話しています。どうしますか。", 6.0, 12.0),
                seg("そうですね、じゃあそうしましょう。", 13.0, 18.0)]
    split = audio_split._read_answer(
        {"kind": "collection", "blocks": [{"keep": True, "lines": [[2, 4]]}]},
        segments, [(1.0, 5.0), (18.0, math.inf)])
    block = split.blocks[0]
    assert block.lines == (3, 4), "the announcement line stayed in the block"
    assert block.item == 2


# ── The exam question, taken out without the model ────────────────────────────
# A past-paper item runs: setting up, question, exchange, the question again.
# The model should keep the setting up and the exchange, but when nothing
# separates them it returns one block, and the card would play the question.


def item(question: str, repeat: str | None = None) -> list[audio_split.Segment]:
    """An item of 課題理解, as Whisper gives it back: the announcement glued to
    the setting up, the question on its own line, the conversation, the question
    repeated."""
    return [
        announcing("1番 男の人と女の人が話しています", "1", "番", " 男の人", "と女の人", "が話しています"),
        seg(question, 6.0, 10.0),
        seg("図書館に行きたいんですけど、どうやって行けばいいですか。", 11.0, 16.0),
        seg("歩くと20分ですよ。バスには乗れますか。", 17.0, 22.0),
        seg("はい。じゃあバスの方が早いですよ。", 23.0, 28.0),
        seg(repeat if repeat is not None else question, 30.0, 34.0),
    ]


SILENCES_ITEM = [(5.0, 6.0), (10.0, 11.0), (16.0, 17.0), (22.0, 23.0),
                 (28.0, 30.0), (34.0, math.inf)]


def test_the_exam_question_leaves_the_block():
    """The card asks its own question, and the audio's would steer the
    listening. The sound keeps two pieces: the setting up, then the exchange."""
    question = "男の人はどうやって図書館へ行きますか。"
    segments = item(question)
    split = audio_split._read_answer(
        {"kind": "collection", "blocks": [{"keep": True, "lines": [[1, 5]]}]},
        segments, SILENCES_ITEM)

    block = split.blocks[0]
    assert block.lines == (1, 3, 4, 5), "the question stayed in the block"
    assert len(block.ranges) == 2, "the hole of the question was not dug"
    assert question not in "".join(block.texts(segments))
    assert "話しています" in "".join(block.texts(segments)), "the setting up went with it"


def test_the_question_repeated_after_the_exchange_leaves_too():
    """The model files the repeat with the conversation just ended."""
    question = "男の人はどうやって図書館へ行きますか。"
    segments = item(question)
    split = audio_split._read_answer(
        {"kind": "collection", "blocks": [{"keep": True, "lines": [[2, 6]]}]},
        segments, SILENCES_ITEM)

    assert split.blocks[0].lines == (3, 4, 5)


def test_a_question_said_only_once_stays():
    """Only the repetition marks a line as the exam question."""
    segments = item("男の人はどうやって図書館へ行きますか。", repeat="では、次の問題です。")
    split = audio_split._read_answer(
        {"kind": "collection", "blocks": [{"keep": True, "lines": [[1, 5]]}]},
        segments, SILENCES_ITEM)

    assert split.blocks[0].lines == (1, 2, 3, 4, 5)


def test_an_announced_prompt_stays_even_when_doubled():
    """A 即時応答 item is a prompt and three replies: the prompt IS the exercise.
    Whisper may double it, and an announced line is never cut as a repeat."""
    prompt_line = "眠いのでちょっと休んでもいいですか"
    segments = [
        announcing(f"4番 {prompt_line}", "4", "番", " 眠いので", "ちょっと休んでも", "いいですか"),
        seg("1 じゃあ急ぎましょう。", 6.0, 10.0),
        seg("2 ええ、どうぞ。", 11.0, 16.0),
        seg("3 いいえ、こちらこそ。", 17.0, 22.0),
        seg(f"4番 {prompt_line}", 24.0, 30.0),
    ]
    split = audio_split._read_answer(
        {"kind": "collection", "blocks": [{"keep": True, "lines": [[1, 4]]}]},
        segments, [(5.0, 6.0), (10.0, 11.0), (16.0, 17.0), (22.0, 24.0), (30.0, math.inf)])

    assert prompt_line in "".join(split.blocks[0].texts(segments))


def test_the_question_of_the_next_item_makes_no_twin():
    """A 発話表現 item's question is the same in every item and IS the exercise:
    the repeat is looked for only within the item, between the kept blocks."""
    def exercise(situation: str, start: float) -> list[audio_split.Segment]:
        return [seg(situation, start, start + 4.0),
                seg("何と言いますか。", start + 5.0, start + 8.0),
                seg("1 あ、久しぶり。元気?", start + 9.0, start + 13.0),
                seg("2 じゃあ、またね。", start + 14.0, start + 18.0)]

    segments = exercise("道で友達に会いました。", 0.0)         + exercise("週末、友達と海に行きたいです。", 30.0)
    split = audio_split._read_answer(
        {"kind": "collection",
         "blocks": [{"keep": True, "lines": [[1, 4]]},
                   {"keep": True, "lines": [[5, 8]]}]},
        segments, [])

    assert split.blocks[0].lines == (1, 2, 3, 4)
    assert split.blocks[1].lines == (5, 6, 7, 8)


def test_on_a_stream_a_repeated_sentence_stays_a_repeated_sentence():
    """The net only holds for a collection: a podcast has no examiner, and a
    question put again there belongs to the exchange."""
    question = "どうしてそう思いますか。"
    segments = item(question)
    split = audio_split._read_answer(
        {"kind": "stream", "blocks": [{"keep": True, "lines": [[1, 5]]}]},
        segments, SILENCES_ITEM)

    assert split.blocks[0].lines == (1, 2, 3, 4, 5)


# ── The line that opens the item, set aside with its number ───────────────────
# The model may set aside a whole line that opens an item with its number glued
# to it: the card would lose its setting up or its prompt.

# A 即時応答 item as Whisper hands it back: the number glued to the prompt, then
# the three replies to choose from.
PROMPTED = [
    seg("4番 暑いのでちょっと窓を開けてもいいですか", 190.4, 196.66,
        [("4", 190.4, 191.04), ("番", 191.04, 191.68), (" 暑い", 192.02, 192.58),
         ("ので", 192.58, 193.2), ("ちょっと窓を開けてもいいですか", 193.2, 196.66)]),
    seg("1 じゃあ閉めましょう", 198.4, 201.82,
        [("1", 198.4, 199.2), (" じゃあ", 199.2, 200.38), ("閉めましょう", 200.38, 201.82)]),
    seg("2 ええいいですよ", 203.02, 207.02,
        [("2", 203.02, 203.6), (" ええ", 203.6, 204.5), ("いいですよ", 204.5, 207.02)]),
    seg("3 いいえけっこうです", 208.08, 212.36,
        [("3", 208.08, 208.6), (" いいえ", 208.6, 209.5), ("けっこうです", 209.5, 212.36)]),
]
PROMPTED_SILENCES = [(186.0, 190.4), (196.66, 198.4), (201.82, 203.02),
                     (207.02, 208.08), (212.36, 219.0)]


def test_a_prompt_set_aside_with_its_number_comes_back_at_the_head():
    """The number leaves the sound, the prompt stays, and reply 1 keeps its
    number, since it does not head the block."""
    split = audio_split._read_answer(
        {"kind": "collection", "blocks": [
            {"keep": False, "lines": [[1, 1]], "pattern": "number"},
            {"keep": True, "lines": [[2, 4]], "start_word": "じゃあ"},
        ]}, PROMPTED, PROMPTED_SILENCES)

    block = split.blocks[0]
    assert block.lines == (1, 2, 3, 4)
    assert 191.68 <= block.start <= 192.02      # after 「番」, before 「暑い」
    assert block.ranges == ((block.start, block.end),)   # reply 1 whole, in one piece
    assert split.dropped == []                  # nothing left but the line rescued
    assert block.texts(PROMPTED)[0] == "暑いのでちょっと窓を開けてもいいですか"
    assert block.texts(PROMPTED)[1] == "1 じゃあ閉めましょう"


def test_only_the_opening_line_comes_back_and_the_exam_question_stays_out():
    """The example of a 問題1: 「例」 glued to the setting up, then the exam
    question, which the model set aside rightly. The passage is heard in two
    pieces, the question cut out between them."""
    segments = [
        seg("例 駅で学生の男の人と女の人が話しています", 76.32, 82.36,
            [("例", 76.32, 76.72), (" 駅で", 76.72, 78.02),
             ("学生の男の人と女の人が話しています", 78.02, 82.36)]),
        seg("女の人は何時の電車に乗りますか", 82.36, 88.62,
            [("女の人は何時の電車に乗りますか", 82.36, 88.62)]),
        seg("じゃあ10時の電車で行きましょう", 90.94, 95.86,
            [("じゃあ10時の電車で行きましょう", 90.94, 95.86)]),
        seg("この駅から空港まで電車でどのぐらいかかりますか", 97.28, 104.04,
            [("この駅から空港まで電車でどのぐらいかかりますか", 97.28, 104.04)]),
    ]
    split = audio_split._read_answer(
        {"kind": "collection", "blocks": [
            {"keep": False, "lines": [[1, 2]], "pattern": "exam question"},
            {"keep": True, "lines": [[3, 4]]},
        ]}, segments, [(72.3, 76.32), (88.62, 90.94), (95.86, 97.28)])

    block = split.blocks[0]
    assert block.lines == (1, 3, 4)
    assert block.start >= 76.72                 # 「例」 stays out of the sound
    assert len(block.ranges) == 2
    assert block.ranges[0][1] <= 82.36          # and the question with it
    # Out of the text too: handed 「例 駅で…」, the card model drops 「駅で」 with it.
    assert block.texts(segments)[0] == "駅で学生の男の人と女の人が話しています"


def test_the_text_handed_on_is_the_one_heard():
    """The sound opens on `start_word`, so the text must too: handed 「1番 大学で…」,
    the card model drops the line as an announcement, and the card plays a
    scene-setting its transcript lacks."""
    segments = [
        seg("1番 大学で女の人と男の人が話しています", 155.0, 161.26,
            [("1", 155.0, 155.58), ("番", 155.58, 156.2), (" 大学で", 156.6, 157.6),
             ("女の人と男の人が話しています", 157.6, 161.26)]),
        seg("来週の発表について話したいんですが いつがいいですか", 170.0, 176.0,
            [("来週の発表について話したいんですが いつがいいですか", 170.0, 176.0)]),
    ]
    split = audio_split._read_answer(
        {"kind": "collection", "blocks": [
            {"keep": True, "lines": [[1, 2]], "start_word": "大学で"}]},
        segments, [(150.0, 155.0), (161.26, 170.0)])

    assert split.blocks[0].texts(segments) == [
        "大学で女の人と男の人が話しています",
        "来週の発表について話したいんですが いつがいいですか"]


def test_a_block_that_opens_its_item_takes_nothing_from_before():
    """Reply 3 of the item before is a numbered line set aside, never an
    opening: a bare number is an option, not an announcement."""
    segments = [
        seg("3 道が混んでいたんです", 176.2, 179.7,
            [("3", 176.2, 176.6), (" 道が", 176.6, 177.5), ("混んでいたんです", 177.5, 179.7)]),
        *PROMPTED,
    ]
    split = audio_split._read_answer(
        {"kind": "collection", "blocks": [
            {"keep": False, "lines": [[1, 1]], "pattern": "answer options"},
            {"keep": True, "lines": [[2, 5]], "start_word": "疲れた"},
        ]}, segments, [(179.7, 190.4), *PROMPTED_SILENCES[1:]])

    assert split.blocks[0].lines == (2, 3, 4, 5)


def test_on_a_stream_nothing_is_brought_back():
    split = audio_split._read_answer(
        {"kind": "stream", "blocks": [
            {"keep": False, "lines": [[1, 1]], "pattern": "number"},
            {"keep": True, "lines": [[2, 4]]},
        ]}, PROMPTED, PROMPTED_SILENCES)

    assert split.blocks[0].lines == (2, 3, 4)


# ── What nobody said ──────────────────────────────────────────────────────────
# A past paper leaves twenty seconds to read the options, and Whisper writes
# something in them: kept, those lines bring the blank into the card.

def _reading_time(*blank_lines):
    """Scene-setting, the exam question, what Whisper wrote in the reading time,
    the bell, the conversation."""
    lines = [
        seg("女の人と男の人が公園で話しています", 47.0, 51.4,
            [("女の人と男の人が", 47.0, 49.0), ("公園で話しています", 49.0, 51.4)]),
        seg("男の人はどうして毎朝公園に来ますか", 51.94, 56.18,
            [("男の人はどうして毎朝公園に来ますか", 51.94, 56.18)]),
        *blank_lines,
        seg("2", 75.86, 76.5, [("2", 75.86, 76.5)]),
        seg("あら 山本くん 散歩?", 81.36, 84.7,
            [("あら", 81.36, 82.52), (" 山本くん 散歩?", 82.94, 84.7)]),
        seg("うん 犬と歩くのが好きでね", 85.24, 87.1, [("うん", 85.24, 85.72), (" 犬と歩くのが好きでね", 86.02, 87.1)]),
        seg("毎朝? 雨の日も?", 87.6, 92.0, [("毎朝? 雨の日も?", 87.6, 92.0)]),
        seg("男の人はどうして毎朝公園に来ますか", 117.12, 123.08,
            [("男の人はどうして毎朝公園に来ますか", 117.12, 123.08)]),
    ]
    return lines


READING_SILENCES = [(43.62, 46.96), (56.3, 75.7), (76.6, 81.2), (92.1, 117.0)]


def test_the_lines_written_in_the_reading_time_leave_with_its_blank():
    segments = _reading_time(
        seg("男の人の方が好きな方がいいです", 62.34, 69.54,
            [("男の人の方が", 62.34, 63.52), ("好きな方がいいです", 63.52, 69.54)]),
        seg("男の人の方が好きな方がいいです", 69.54, 75.86,
            [("男の人の方が", 69.54, 69.54), ("好きな方がいいです", 69.54, 75.86)]))
    split = audio_split._read_answer(
        {"kind": "collection", "blocks": [{"keep": True, "lines": [[1, 7]]}]},
        segments, READING_SILENCES)

    block = split.blocks[0]
    assert block.lines == (1, 6, 7)            # no question, no blank, no bell
    assert len(block.ranges) == 2
    assert block.ranges[1][0] >= 76.5           # the bell stays out of the sound


def test_a_blank_with_nothing_written_in_it_is_cut_out_too():
    """With nothing written in the reading time, its twenty seconds still sit
    between the scene-setting and the bell."""
    segments = _reading_time()
    # The exam question glued to the scene-setting.
    segments[1:2] = []
    split = audio_split._read_answer(
        {"kind": "collection", "blocks": [{"keep": True, "lines": [[1, 4]]}]},
        segments, READING_SILENCES)

    block = split.blocks[0]
    assert block.lines == (1, 3, 4)
    assert block.ranges[0][1] <= 56.3
    assert block.ranges[1][0] >= 76.5


def test_the_bell_written_as_a_number_goes_where_the_question_was_cut():
    """The blank falls where the exam question is cut; the bell after it, which
    Whisper writes as the last number heard, must not open the conversation."""
    segments = [
        seg("駅で女の人と駅員が話しています。", 462.9, 468.28,
            [("駅で", 462.9, 464.0), ("女の人と駅員が話しています。", 464.0, 468.28)]),
        seg("女の人はまず何をしなければなりませんか?", 469.4, 473.54,
            [("女の人はまず何をしなければなりませんか?", 469.4, 473.2)]),
        seg("4番", 495.08, 495.88, [("4", 495.08, 495.48), ("番", 495.48, 495.88)]),
        seg("あの、切符をなくしたんですが。", 496.84, 500.62,
            [("あの、", 496.84, 498.5), ("切符をなくしたんですが。", 498.96, 500.62)]),
        seg("はい、どうぞ。", 501.12, 502.28, [("はい、どうぞ。", 501.12, 502.28)]),
        seg("女の人はまず何をしなければなりませんか?", 530.0, 534.0,
            [("女の人はまず何をしなければなりませんか?", 530.0, 534.0)]),
    ]
    split = audio_split._read_answer(
        {"kind": "collection", "blocks": [{"keep": True, "lines": [[1, 5]]}]},
        segments, [(473.27, 493.47), (495.73, 497.38), (502.3, 529.9)])

    block = split.blocks[0]
    assert block.lines == (1, 4, 5)
    assert block.ranges[1][0] >= 495.73         # the bell rang until 495.73


def test_a_first_word_laid_over_the_bell_starts_after_it():
    """The second word read from 292.48 to 296.56: over the bell, and over the
    silence after it. The voice comes in at 296.14."""
    opening = seg("田中さん、ギターを始めたそうですね", 292.1, 299.52,
                  [("田", 292.1, 292.48), ("中", 292.48, 296.56), ("さん、", 296.56, 297.26),
                   ("ギターを始めたそうですね", 297.66, 299.52)])
    silences = [(272.09, 292.28), (294.54, 296.14), (296.93, 297.66)]
    assert announcements.after_the_bell(opening, silences) == 296.14
    # A first word that holds no silence is where the voice starts.
    clean = seg("ねえ 木村くん", 81.36, 84.7, [("ねえ", 81.36, 82.52), (" 木村くん", 82.94, 84.7)])
    assert announcements.after_the_bell(clean, [(55.94, 76.15), (78.39, 80.16)]) is None


def test_what_whisper_writes_between_the_bell_and_the_voice_was_not_said():
    """A line written in the 1.5 s of blank between the bell and the voice."""
    ghost = seg("2人は、女の人と男の人の話をしています", 186.48, 187.72,
                [("2", 186.48, 187.1), ("人", 187.1, 187.72), ("は、", 187.72, 187.72)])
    assert announcements.unheard(ghost, [(163.86, 184.05), (186.3, 187.89)])
    # The same line far from any reading time is a line.
    assert not announcements.unheard(ghost, [(150.0, 160.0), (186.3, 187.89)])


def test_a_short_pause_is_no_blank():
    """「2 あのー」 opens a reply of a 発話表現 item: Whisper spread its words
    over the pauses, which last under a second and a half."""
    reply = seg("2 あのー", 107.98, 110.06,
                [("2", 107.98, 108.58), (" あ", 108.58, 109.18), ("の", 109.18, 109.78),
                 ("ー", 109.78, 110.06)])
    assert not announcements.unheard(reply, [(108.1, 108.9), (109.3, 110.0)])
    assert announcements.unheard(reply, [(100.0, 112.0)])


def test_an_announcement_alone_on_its_line_hands_its_item_the_next_one():
    """「6番」 alone, then the scene-setting, then the question: the model set
    the three aside, and Whisper's 「7番」 and 「スーパー」, written in the reading
    time, sat between them and the conversation."""
    segments = [
        seg("6番", 660.36, 661.32, [("6", 660.36, 660.84), ("番", 660.84, 661.32)]),
        seg("ラジオで女の人が自分の仕事について話しています。", 661.32, 666.54,
            [("ラジオで女の人が", 661.32, 663.3), ("自分の仕事について話しています。", 663.8, 666.54)]),
        seg("女の人は、何が大変だと言っていますか?", 667.48, 671.58,
            [("女の人は、何が大変だと言っていますか?", 667.48, 671.0)]),
        seg("7番", 683.32, 683.82, [("7", 683.32, 683.82), ("番", 683.82, 683.82)]),
        seg("スーパー", 683.82, 685.36, [("スーパー", 683.82, 685.36)]),
        seg("スーパー", 690.56, 694.54, [("スーパー", 690.56, 694.54)]),   # over the bell
        seg("私は駅前のスーパーでパンを焼いています。", 695.1, 699.3,
            [("私は駅前の", 695.1, 697.5), ("スーパーでパンを焼いています。", 697.5, 699.3)]),
        seg("毎朝、四時に起きます。", 700.04, 703.56,
            [("毎朝、四時に起きます。", 700.04, 703.56)]),
    ]
    split = audio_split._read_answer(
        {"kind": "collection", "blocks": [
            {"keep": False, "lines": [[1, 3]], "pattern": "exam question"},
            {"keep": True, "lines": [[4, 8]]},
        ]}, segments, [(658.15, 660.11), (671.03, 691.23), (693.49, 695.05)])

    block = split.blocks[0]
    assert block.lines == (2, 7, 8)
    assert block.start >= 661.32                # 「6番」 stays out


@pytest.mark.parametrize("words, opens", [
    ([("4", 0.0, 0.64), ("番", 0.64, 1.28), (" 疲れた", 1.6, 2.0)], True),
    ([("5", 0.0, 0.48), ("番", 0.48, 4.76), (" お客様", 4.76, 5.4)], True),  # stretched
    ([("例", 0.0, 0.4), (" 駅で", 0.4, 1.7)], True),
    ([("0", 0.0, 1.12), (" すみません", 1.12, 2.6)], True),      # 例, read れい
    ([("1", 0.0, 0.8), (" じゃあ", 0.8, 2.0)], False),           # a reply, not an item
    ([("例", 0.0, 0.3), ("えば", 0.3, 0.6), ("駅", 0.6, 1.0)], False),
    ([("4", 0.0, 0.3), ("番", 0.3, 0.6)], False),               # nothing to open on
])
def test_what_opens_an_item(words, opens):
    segment = seg("".join(text for text, _s, _e in words), 0.0, words[-1][2], words)
    assert (announcements.item_opening(segment) is not None) == opens


# ── Reading the answer of the model ───────────────────────────────────────────

def read_answer(blocks, kind="collection"):
    return audio_split._read_answer({"kind": kind, "blocks": blocks}, SEGMENTS, SILENCES)


def test_only_the_lines_kept_make_sound():
    split = read_answer([
        {"keep": False, "lines": [[1, 1]], "pattern": "title"},
        {"keep": True, "lines": [[2, 4]]},
        {"keep": False, "lines": [[6, 6]], "pattern": "exam question"},
    ])
    assert split.kind == "collection"
    assert len(split.blocks) == 1
    assert [e.reason for e in split.dropped] == ["title", "exam question"]

    block = split.blocks[0]
    assert block.lines == (2, 3, 4)
    # The title ends at 2.0 s and the question starts at 30.0 s.
    assert block.start > 2.0 and block.end < 30.0


def test_a_single_range_given_flat_is_accepted():
    """`[2, 4]` and `[[2, 4]]` say the same thing; refusing the first would lose
    a file over a comma."""
    assert read_answer([{"keep": True, "lines": [2, 4]}]).blocks[0].lines == (2, 3, 4)


def test_a_removal_in_the_middle_gives_two_ranges_of_sound():
    """Otherwise the outer bounds would take back what is thrown away."""
    block = read_answer([{"keep": True, "lines": [[2, 3], [5, 5]]}]).blocks[0]
    assert len(block.ranges) == 2
    assert block.lines == (2, 3, 5)
    # Line 4 (9.0 to 13.0 s) must be covered by no range at all.
    assert all(not (start < 11.0 < end) for start, end in block.ranges)
    assert block.duration < block.end - block.start


def test_lines_outside_the_file_get_the_block_dropped():
    """An index out of bounds says the model has lost the thread: a block
    rebuilt crooked would cost a call for a wrong card."""
    split = read_answer([{"keep": True, "lines": [[2, 99]]}])
    assert split.blocks == []
    assert split.unreadable == 1


def test_two_overlapping_blocks_are_not_taken_twice():
    split = read_answer([
        {"keep": True, "lines": [[2, 4]]},
        {"keep": True, "lines": [[3, 5]]},
    ])
    assert len(split.blocks) == 1
    assert split.unreadable == 1


def test_an_unreadable_block_is_said_without_being_recounted():
    """It may have lost a conversation, so the summary counts it, without a
    line of its own."""
    split = read_answer([
        {"keep": True, "lines": [[2, 4]]},
        {"keep": True, "lines": [[3, 5]]},
    ])
    assert "1 unreadable block" in audio_split.summary(split)


def test_an_unknown_reason_does_not_go_through_as_it_stands():
    """The reason is displayed: no Japanese sentence may slip into it."""
    dropped = read_answer([{"keep": False, "lines": [[1, 1]],
                    "pattern": "これは面白い会話です"}]).dropped[0]
    assert dropped.reason == "outside the content"


def _many_blocks(kind: str, how_many: int):
    """A file that gives back `how_many` keepable passages, to measure the
    ceiling."""
    # Two lines per block, heavy enough to pass the floor of substance.
    segments = [seg("明日から、友達と山に登るんだ。上着持ったほうがいいんじゃない?",
                    i * 10.0, i * 10.0 + 5.0) for i in range(2 * how_many)]
    blocks = [{"keep": True, "lines": [[2 * i - 1, 2 * i]]}
             for i in range(1, how_many + 1)]
    return audio_split._read_answer({"kind": kind, "blocks": blocks}, segments, [])


def test_the_blocks_of_a_collection_are_capped():
    """A spending safeguard: every passage kept costs a generation call."""
    split = _many_blocks("collection", audio_split.MAX_BLOCKS + 4)
    assert len(split.blocks) == audio_split.MAX_BLOCKS
    assert [e.reason for e in split.dropped] == ["past the ceiling"] * 4


def test_a_stream_is_capped_far_lower_than_a_collection():
    """A podcast has only changes of subject, and nothing there bounds what a
    generous model offers: four extracts of an episode are enough."""
    assert audio_split.MAX_STREAM_BLOCKS < audio_split.MAX_BLOCKS
    too_many = audio_split.MAX_STREAM_BLOCKS + 3
    split = _many_blocks("stream", too_many)
    assert len(split.blocks) == audio_split.MAX_STREAM_BLOCKS
    assert [e.reason for e in split.dropped] == ["past the ceiling"] * 3


def test_a_fiction_is_capped_between_the_two():
    """A fiction's scenes bound its passages as a collection's items do, so four
    would waste them; twelve would be too many generation calls."""
    assert (audio_split.MAX_STREAM_BLOCKS < audio_split.MAX_FICTION_BLOCKS
            < audio_split.MAX_BLOCKS)
    too_many = audio_split.MAX_FICTION_BLOCKS + 2

    split = _many_blocks("fiction", too_many)

    assert len(split.blocks) == audio_split.MAX_FICTION_BLOCKS
    assert [e.reason for e in split.dropped] == ["past the ceiling"] * 2


def test_a_kind_nobody_could_read_keeps_the_widest_ceiling():
    """The file was split all the same; only its kind is in doubt."""
    split = _many_blocks("a nature of its own", audio_split.MAX_BLOCKS)

    assert split.kind == "unknown"
    assert len(split.blocks) == audio_split.MAX_BLOCKS


def test_the_trappings_of_a_series_are_named_as_they_are():
    """The theme song, the story so far and the next episode come back every
    week: the screen names them rather than saying "outside the content"."""
    segments = [seg("ラララ 夢の続きへ 走っていこう", 0.0, 8.0),
                seg("明日から、友達と山に登るんだ。上着持ったほうがいい?", 10.0, 20.0)]

    split = audio_split._read_answer(
        {"kind": "fiction",
         "blocks": [{"keep": False, "lines": [[1, 1]], "pattern": "theme song"},
                    {"keep": True, "lines": [[2, 2]]}]},
        segments, [])

    assert [e.reason for e in split.dropped] == ["theme song"]


def test_every_reason_has_a_label_and_its_french():
    """The patterns reach the screen through a variable, which the scan of
    `_("literal")` misses. A label agrees with its count (`label_for`), so each
    table needs one entry per form it counts in."""
    from kotogen import i18n

    assert not [r for r in audio_split.REASONS if r not in audio_split.LABELS]
    for lang in i18n.available():
        table = i18n._load(lang)
        assert not [key for forms in audio_split.LABELS.values()
                    for key in i18n.counted_keys(*forms, table=table)
                    if table and key not in table], lang


def test_every_rank_of_a_retry_has_its_french():
    """The rank of an attempt reaches the screen through a variable too."""
    from kotogen import i18n

    for lang in i18n.available():
        table = i18n._load(lang)
        assert not [rank for rank in audio_split.RANKS if table and rank not in table], lang


# ── The duration instruction ──────────────────────────────────────────────────

def _window(instruction: str) -> tuple[int, int]:
    """The two bounds of the window announced, read back from the sentence."""
    match = re.search(r"of (\d+) to (\d+) s", instruction)
    assert match, instruction
    return int(match.group(1)), int(match.group(2))


def test_a_fiction_aims_at_the_window_like_a_stream():
    """A scene outlasts the window, so it is cut inside, and the instruction
    must say so."""
    assert "stream or a fiction" in audio_split._duration_instruction(None)


def test_the_target_window_is_announced_to_the_model():
    instruction = audio_split._duration_instruction(None)
    assert str(audio_split.STREAM_MIN_DURATION) in instruction
    assert str(audio_split.STREAM_MAX_DURATION) in instruction
    # With no limit asked for, nothing mentions a dropped passage.
    assert "set aside" not in instruction


def test_the_limit_asked_for_is_said_before_the_splitting():
    """Otherwise the splitting call pays for passages thrown away just after."""
    instruction = audio_split._duration_instruction(60)
    assert "60 s" in instruction
    assert "set aside" in instruction


def test_the_message_carries_the_duration_instruction():
    segments = [seg("こんにちは", 0.0, 2.0), seg("おはよう", 3.0, 5.0)]
    assert "over 60 s will be set aside" in audio_split._message(
        "a.mp3", segments, [], 60)
    assert "set aside" not in audio_split._message("a.mp3", segments, [], None)


def test_the_limit_narrows_the_window_instead_of_adding_to_it():
    """Stated after a wider window, the limit reads as a caveat, and the model
    anchors on the top of the window."""
    instruction = audio_split._duration_instruction(60)
    assert "of 20 to 60 s" in instruction
    assert str(audio_split.STREAM_MAX_DURATION) not in instruction


def test_a_limit_wider_than_the_window_does_not_widen_it():
    instruction = audio_split._duration_instruction(600)
    assert (f"of {audio_split.STREAM_MIN_DURATION} to "
            f"{audio_split.STREAM_MAX_DURATION} s") in instruction


def test_a_very_short_limit_takes_the_floor_down_with_it():
    """A floor left in place closes the window on one value ("from 20 to 20 s"),
    and the model then refuses every passage."""
    assert "of 8 to 20 s" in audio_split._duration_instruction(20)
    assert "of 4 to 10 s" in audio_split._duration_instruction(10)


def test_the_window_never_closes_on_a_single_value():
    """From 2 s upwards: a one-second limit holds no speech, and no window
    could give it any."""
    for limit in (None, 2, 5, 10, 20, 30, 45, 60, 90, 600):
        bottom, top = _window(audio_split._duration_instruction(limit))
        assert 1 <= bottom < top, limit


def test_the_ceiling_bounds_the_cut_and_not_the_choice():
    """A subject longer than the limit is windowed, not thrown away: a short
    limit asks for shorter passages, not fewer."""
    instruction = audio_split._duration_instruction(20)
    assert "bounds where you CUT" in instruction
    assert "a window is taken inside it" in instruction


# ── The ceiling instruction ───────────────────────────────────────────────────

def test_the_ceiling_is_announced_to_the_model():
    """Truncating keeps the FIRST blocks; told the ceiling, the model can choose
    the best ones."""
    instruction = audio_split._ceiling_instruction()
    assert str(audio_split.MAX_BLOCKS) in instruction
    assert str(audio_split.MAX_FICTION_BLOCKS) in instruction
    assert str(audio_split.MAX_STREAM_BLOCKS) in instruction


def test_the_message_carries_the_ceiling_instruction():
    segments = [seg("こんにちは", 0.0, 2.0), seg("おはよう", 3.0, 5.0)]
    assert audio_split._ceiling_instruction() in audio_split._message("a.mp3", segments, [], None)


# ── The duration asked for, applied before the ceiling ────────────────────────

def _blocks_of_durations(durations, limit=None):
    """A stream whose n-th kept passage lasts `durations[n]` seconds."""
    segments, blocks, start = [], [], 0.0
    for i, duration in enumerate(durations):
        segments.append(seg("明日から、友達と山に登るんだ。", start, start + duration / 2))
        segments.append(seg("上着持ったほうがいいんじゃない?", start + duration / 2, start + duration))
        blocks.append({"keep": True, "lines": [[2 * i + 1, 2 * i + 2]]})
        start += duration + 5.0
    return audio_split._read_answer({"kind": "stream", "blocks": blocks}, segments, [], limit)


def test_a_passage_longer_than_asked_for_is_dropped_at_reading_time():
    """Dropped before the ceiling applies, so it takes no place under it."""
    split = _blocks_of_durations([120.0, 30.0], limit=60)
    assert len(split.blocks) == 1
    assert split.blocks[0].duration == pytest.approx(30.0, abs=1.0)
    assert [e.reason for e in split.dropped] == ["too long"]


def test_over_long_passages_do_not_eat_the_ceiling():
    """Otherwise the first passages, all too long, would fill the ceiling, and
    the shorter ones after them fall past it: zero cards."""
    too_long = [150.0] * audio_split.MAX_STREAM_BLOCKS
    bearable = [40.0] * audio_split.MAX_STREAM_BLOCKS
    split = _blocks_of_durations(too_long + bearable, limit=60)
    assert len(split.blocks) == audio_split.MAX_STREAM_BLOCKS
    assert all(b.duration <= 60 for b in split.blocks)
    assert "past the ceiling" not in [e.reason for e in split.dropped]


def test_with_no_limit_asked_for_no_duration_is_refused():
    split = _blocks_of_durations([300.0])
    assert len(split.blocks) == 1


def test_an_unknown_kind_does_not_pass_itself_off_as_a_whole_file():
    split = read_answer([{"keep": True, "lines": [[2, 4]]}], kind="no idea")
    assert split.kind == "unknown"
    assert not split.whole


# ── The floor of substance ────────────────────────────────────────────────────

def test_a_passage_with_no_substance_is_dropped_with_no_ai_call():
    """Two short lines weigh less than MIN_CHARS, too little for a question: the
    passage is refused here, with no AI call."""
    short_lines = [seg("そうですか", 0.0, 1.5), seg("はい そうです", 2.0, 3.5)]
    split = audio_split._read_answer(
        {"kind": "collection", "blocks": [{"keep": True, "lines": [[1, 2]]}]},
        short_lines, [])
    assert split.blocks == []
    assert [e.reason for e in split.dropped] == ["too short"]
    assert not quota.carries_a_question([s.text for s in short_lines])


# ── When the call is not paid for ─────────────────────────────────────────────

class ForbiddenClient:
    def chat_json(self, *a, **k):
        raise AssertionError("the splitting should not have called the AI")


def test_a_short_file_pays_for_no_splitting():
    """Three lines or forty seconds do not make a collection."""
    short_segments = [seg("あ", 0.0, 1.0), seg("い", 1.0, 2.0), seg("う", 2.0, 3.0)]
    split = audio_split.split_audio(ForbiddenClient(), Path("x.mp3"), short_segments)
    assert split.whole and len(split.blocks) == 1


def test_no_split_short_circuits_everything():
    split = audio_split.split_audio(ForbiddenClient(), Path("x.mp3"), SEGMENTS, active=False)
    assert split.whole


# ── A track that announces itself, without being a collection ─────────────────
# いろどり opens every track on its number read aloud. Too short to call the
# model, such a track still goes through the deterministic net, which costs no
# call.

# The number, 1.1 s of gap, then the dialogue: the timings of a real track, in
# words of our own.
TRACK = [
    seg("1。", 0.52, 0.94, [("1", 0.52, 0.94)]),
    seg("あの、山本さんですか。", 2.04, 4.6,
        [("あの", 2.04, 3.1), ("山本さんですか", 3.2, 4.6)]),
    seg("はい、山本です。", 5.2, 6.6, [("はい", 5.2, 5.7), ("山本です", 5.9, 6.6)]),
    seg("先月、東京に引っこしました。", 7.1, 10.4,
        [("先月", 7.1, 7.9), ("東京に引っこしました", 8.1, 10.4)]),
]
GAPS = [(0.0, 0.52), (0.94, 2.04), (4.6, 5.2), (6.6, 7.1), (10.4, 18.7)]


def test_a_short_track_loses_its_number_without_paying_a_call(monkeypatch):
    """Too short for the model, it would otherwise keep its announcement."""
    monkeypatch.setattr(cuts, "detect_silences", lambda p: GAPS)
    split = audio_split.split_audio(ForbiddenClient(), Path("Z_[01-01]_kiku1.mp3"), TRACK)

    assert split.kind == audio_split.KIND_TRIMMED
    assert not split.whole            # there is sound to re-encode
    assert split.blocks[0].lines == (2, 3, 4)
    start, end = split.blocks[0].ranges[0]
    assert 0.94 <= start <= 2.04         # in the gap, after the number
    assert end >= 10.4                   # nothing of the conversation is clipped


def test_the_number_welded_to_the_first_line_goes_out_too(monkeypatch):
    """Whisper regularly files the number and the first line in the same
    segment: the line cannot leave, so the cut falls inside it."""
    monkeypatch.setattr(cuts, "detect_silences", lambda p: GAPS)
    welded = [seg("1あの、山本さんですか。", 0.52, 4.6,
                 [("1", 0.52, 0.94), ("あの", 2.04, 3.1),
                  ("山本さんですか", 3.2, 4.6)])] + TRACK[2:]

    split = audio_split.split_audio(ForbiddenClient(), Path("x.mp3"), welded)

    assert split.kind == audio_split.KIND_TRIMMED
    assert split.blocks[0].ranges[0][0] >= 0.94


def test_a_track_that_opens_on_speech_does_not_even_measure_its_silences(monkeypatch):
    """The commonest case stays free: with no announcement to take out, the
    original sound goes out as it is, with no ffmpeg pass."""
    def forbidden(path):
        raise AssertionError("no silence to measure on an untouched file")

    monkeypatch.setattr(cuts, "detect_silences", forbidden)
    split = audio_split.split_audio(ForbiddenClient(), Path("x.mp3"), TRACK[1:])

    assert split.whole and split.blocks[0].ranges == ((0.0, 10.4),)


def test_no_split_keeps_the_number_with_the_rest():
    """`--no-split` means the file as it is, whatever it holds."""
    split = audio_split.split_audio(ForbiddenClient(), Path("x.mp3"), TRACK, active=False)
    assert split.whole and split.blocks[0].lines == (1, 2, 3, 4)


def test_a_file_that_is_only_a_number_does_not_empty_itself():
    """Taking out the only line would leave an empty transcript: the file is
    given back as it is."""
    split = audio_split.whole_block([seg("1。", 0.5, 0.9, [("1", 0.5, 0.9)])])
    assert split.whole and split.blocks[0].lines == (1,)


def test_a_trimmed_track_drags_no_bounds_along(monkeypatch):
    """Bounds tell which extract of a collection a card comes from; a trimmed
    track is still a single piece."""
    monkeypatch.setattr(cuts, "detect_silences", lambda p: GAPS)
    split = audio_split.split_audio(ForbiddenClient(), Path("x.mp3"), TRACK)
    assert split.one_piece and not split.whole


def test_the_log_says_the_trimming_without_quoting_the_content(capsys, monkeypatch):
    """"the whole file" is wrong, "1 passage" would suggest a splitting."""
    monkeypatch.setattr(cuts, "detect_silences", lambda p: GAPS)
    audio_split.show(audio_split.split_audio(ForbiddenClient(), Path("x.mp3"), TRACK))

    output = capsys.readouterr().out
    assert output == "   Splitting… (whole file, minus its announcement)\n"
    assert not JAPANESE.search(output)


def test_two_unreadable_answers_are_worth_a_third_attempt(capsys, monkeypatch):
    """A failure is almost always one stray comma in an otherwise right answer,
    and the model may repeat the slip: a retry costs less than a wasted pass."""
    monkeypatch.setattr(cuts, "detect_silences", lambda p: [])
    good = {"kind": "collection",
             "blocks": [{"keep": False, "lines": [[1, 1]], "pattern": "title"},
                       {"keep": True, "lines": [[2, 4]]}]}

    class Hesitant:
        def __init__(self):
            self.calls = 0

        def chat_json(self, *a, **k):
            self.calls += 1
            if self.calls < 3:
                raise ValueError("The AI did not return valid JSON.")
            return good

    client = Hesitant()
    long_run = SEGMENTS + [seg("おわり", 50.0, 60.0)]   # long enough to pay for the call
    split = audio_split.split_audio(client, Path("x.mp3"), long_run)

    assert client.calls == 3
    assert len(split.blocks) == 1 and not split.whole
    output = capsys.readouterr().out
    assert "second attempt" in output and "third attempt" in output


def test_the_failure_log_does_not_explain_the_breakage(capsys, monkeypatch):
    """No reason in brackets: it would come from the message of `chat_json`,
    which carries the raw answer and so leaks the content."""
    monkeypatch.setattr(cuts, "detect_silences", lambda p: [])

    class Broken:
        def chat_json(self, *a, **k):
            raise ValueError("The AI did not return valid JSON.")

    long_run = SEGMENTS + [seg("おわり", 50.0, 60.0)]
    audio_split.split_audio(Broken(), Path("x.mp3"), long_run)

    output = capsys.readouterr()
    assert "(" not in output.out + output.err
    assert "JSON" not in output.out + output.err


def test_a_failed_splitting_drops_the_file(capsys, monkeypatch):
    """Only a collection candidate gets here: one card for the whole file would
    cover ten exchanges with no audio extract, a call paid for a wrong card."""
    monkeypatch.setattr(cuts, "detect_silences", lambda p: [])

    class Broken:
        def chat_json(self, *a, **k):
            raise ValueError("The AI did not return valid JSON.")

    long_run = SEGMENTS + [seg("おわり", 50.0, 60.0)]
    split = audio_split.split_audio(Broken(), Path("x.mp3"), long_run)

    assert split.kind == audio_split.KIND_FAILED
    assert split.blocks == [] and not split.whole
    assert "file turned down" in capsys.readouterr().err


def test_an_answer_of_unreadable_blocks_only_is_an_unreadable_answer(monkeypatch):
    """Every block out of the file: the model lost its thread. Taken whole, the
    collection would cost one card for ten exchanges, with no extract."""
    monkeypatch.setattr(cuts, "detect_silences", lambda p: [])

    class Lost:
        calls = 0

        def chat_json(self, *a, **k):
            Lost.calls += 1
            return {"kind": "collection",
                    "blocks": [{"keep": True, "lines": [[2, 99]]},
                               {"keep": True, "lines": [[40, 41]]}]}

    long_run = SEGMENTS + [seg("おわり", 50.0, 60.0)]
    split = audio_split.split_audio(Lost(), Path("x.mp3"), long_run)

    assert split.kind == audio_split.KIND_FAILED and not split.whole
    assert Lost.calls == audio_split.ATTEMPTS


def test_blocks_that_are_not_a_list_are_an_unreadable_answer(monkeypatch):
    """Retried like any answer that does not read, not raised as a bug."""
    monkeypatch.setattr(cuts, "detect_silences", lambda p: [])

    class Counting:
        calls = 0

        def chat_json(self, *a, **k):
            Counting.calls += 1
            return {"kind": "collection", "blocks": 3}

    long_run = SEGMENTS + [seg("おわり", 50.0, 60.0)]
    split = audio_split.split_audio(Counting(), Path("x.mp3"), long_run)

    assert split.kind == audio_split.KIND_FAILED
    assert Counting.calls == audio_split.ATTEMPTS


def test_a_range_far_past_the_file_is_not_walked_line_by_line(monkeypatch):
    """`[[1, 10**12]]` would hold the run for hours before being turned down."""
    walked: list[int] = []

    def measured(*bounds):
        # Cut short, so that a walk of the whole range is measured, not made.
        whole = builtins.range(*bounds)
        walked.append(len(whole))
        return whole[:100]

    monkeypatch.setattr(audio_split, "range", measured, raising=False)
    answer = {"kind": "collection",
              "blocks": [{"keep": False, "lines": [[1, 10 ** 12]]},
                         {"keep": True, "lines": [[3, 4]]}]}
    audio_split._rescued_openings(answer, SEGMENTS)

    assert walked and max(walked) <= len(SEGMENTS)


@pytest.mark.parametrize("failure", [
    AITruncatedError("answer cut off at the 4096 token limit"),
    RuntimeError("HTTP 503 after the client's own retries"),
    TypeError("a bug in the reading of the answer"),
])
def test_only_an_unreadable_answer_is_paid_for_again(monkeypatch, failure):
    """A cut answer would be cut again, the network has had its retries in the
    client, and a bug repeats: a second call would be paid for nothing."""
    monkeypatch.setattr(cuts, "detect_silences", lambda p: [])

    class Failing:
        calls = 0

        def chat_json(self, *a, **k):
            Failing.calls += 1
            raise failure

    long_run = SEGMENTS + [seg("おわり", 50.0, 60.0)]
    with pytest.raises(type(failure)):
        audio_split.split_audio(Failing(), Path("x.mp3"), long_run)
    assert Failing.calls == 1


def test_a_split_that_raises_drops_the_file_not_the_run(tmp_path, monkeypatch, capsys):
    """The split's failure is the file's: the next files still get their cards."""
    first, second = tmp_path / "a.mp3", tmp_path / "b.mp3"
    for path in (first, second):
        path.write_bytes(b"")
    split = audio_split.Split("collection", [], [])
    answers = iter([AITruncatedError("answer cut off"), split])

    def split_audio(*a, **k):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(audio, "AIClient", lambda **k: object())
    monkeypatch.setattr(whisper, "_transcribe", lambda *a, **k: SEGMENTS)
    monkeypatch.setattr(audio_split, "split_audio", split_audio)
    monkeypatch.setattr(audio, "resolve_output_path", lambda *a, **k: tmp_path / "out.tsv")

    args = _args(tmp_path, first)
    args.inputs = [str(first), str(second)]
    audio.run_audio(args)

    assert next(answers, None) is None, "the second file was not split"
    err = capsys.readouterr().err
    assert "cannot split" in err and "answer cut off" in err


def test_a_failure_never_dumps_the_answer_of_the_model(capsys, monkeypatch):
    """`chat_json` attaches the raw answer to its message: shown here, it would
    fill the screen with JSON and give the transcript away."""
    monkeypatch.setattr(cuts, "detect_silences", lambda p: [])

    class Chatty:
        def chat_json(self, *a, **k):
            raise ValueError(
                "The AI did not return valid JSON.\n\nRaw answer:\n"
                '{"blocks": [{"lines": [[1, 2]]}}]}\n何これ?食べ終わったら片付けなさい')

    long_run = SEGMENTS + [seg("おわり", 50.0, 60.0)]
    audio_split.split_audio(Chatty(), Path("x.mp3"), long_run)

    output = capsys.readouterr()
    whole_output = output.out + output.err
    assert "Raw answer" not in whole_output
    assert '"blocks"' not in whole_output
    assert not JAPANESE.search(whole_output), "the log gives the audio content away"


# ── The display gives nothing away ────────────────────────────────────────────

def test_the_display_never_quotes_the_content(capsys):
    split = read_answer([
        {"keep": False, "lines": [[1, 1]], "pattern": "title"},
        {"keep": True, "lines": [[2, 4]]},
        {"keep": False, "lines": [[6, 6]], "pattern": "exam question"},
    ])
    audio_split.show(split)

    output = capsys.readouterr().out
    assert "title" in output and "exam question" in output
    assert not JAPANESE.search(output), "the log gives the audio content away"


def test_the_splitting_holds_on_one_line(capsys):
    """A shadowing book yields twenty refusals: one line, not twenty."""
    dropped_list = ([audio_split.Dropped(i, i + 1, "number") for i in range(10)]
               + [audio_split.Dropped(i, i + 1, "too short") for i in range(9)]
               + [audio_split.Dropped(0.0, 8.0, "title")])
    audio_split.show(audio_split.Split("collection", [], dropped_list))

    output = capsys.readouterr().out
    assert output.splitlines() == [
        "   Splitting… (no usable passage, "
        "20 refusals: 10 numbers, 9 too short, 1 title)"
    ]


def test_the_summary_announces_what_is_kept(capsys):
    split = audio_split.Split(
        "collection",
        [audio_split.Block((2, 3), ((4.0, 9.0),))],
        [audio_split.Dropped(10.0, 12.0, "exam question")])
    audio_split.show(split)

    output = capsys.readouterr().out
    assert output.splitlines() == [
        "   Splitting… (1 passage, 1 refusal: 1 exam question)"]


def test_an_unsplit_file_says_so_without_listing_anything(capsys):
    """Said even with nothing to cut: otherwise a skipped splitting looks the
    same."""
    audio_split.show(audio_split.whole_block(SEGMENTS))
    assert capsys.readouterr().out == "   Splitting… (whole file)\n"


def test_the_timestamp():
    assert audio_split.timestamp(72.4) == "01:12"
    assert audio_split.timestamp(3800) == "1:03:20"


# ── End to end, on stand-ins ──────────────────────────────────────────────────

def _args(tmp_path: Path, source: Path) -> argparse.Namespace:
    return argparse.Namespace(
        inputs=[str(source)], latest=4, provider="openrouter", model="m",
        output=str(tmp_path / "out.tsv"), send=False, deck="Test", notetype="Audio",
        count=None, level="auto", max_duration=None, whisper_model="small",
        audio_quality=None, split=True,
    )


def _ai_result(*_a, **_k) -> dict:
    return {
        "Level": "N4",
        "TranscriptLines": ["ねえ、見て。", "わー、大きい荷物だ。"],
        "TranslationLines": ["Regarde.", "Ouah, quel gros sac."],
        # A speaker label gets the card refused (tests/test_audio_cards.py).
        "Cards": [{"Question": "Qu'est-ce qui est montré ?", "Answer": "Un gros sac",
                   "Decoys": ["Une photo", "Un livre", "Une clé"], "KeyLine": 2}],
    }


def test_every_passage_gives_its_card_and_its_audio(tmp_path, monkeypatch, capsys):
    """Three conversations in one file: three generation calls, three audio
    files, and nothing of the content on the output."""
    source = tmp_path / "collection.mp3"
    source.write_bytes(b"")

    split = audio_split.Split(
        "collection",
        [audio_split.Block((2, 3), ((4.0, 9.0),)),
         audio_split.Block((4,), ((9.0, 14.0),)),
         audio_split.Block((5,), ((20.0, 25.0),))],
        [audio_split.Dropped(0.0, 2.0, "title")],
    )

    calls: list[str] = []
    extracts: list[Path] = []

    def extract(src, block, rank, out_dir, bitrate):
        path = out_dir / f"{src.stem}_{rank:02d}.mp3"
        path.write_bytes(b"")
        extracts.append(path)
        return path

    def generate(client, name, lines, limit, level, choice=False, figured=False):
        calls.append(name)
        return _ai_result()

    monkeypatch.setattr(audio, "AIClient", lambda **k: object())
    monkeypatch.setattr(whisper, "_transcribe", lambda *a, **k: SEGMENTS)
    monkeypatch.setattr(audio_split, "split_audio", lambda *a, **k: split)
    monkeypatch.setattr(audio, "_extract_span", extract)
    monkeypatch.setattr(audio, "_generate_for_audio", generate)
    monkeypatch.setattr(audio, "append_cards", lambda *a, **k: None)
    monkeypatch.setattr(audio, "resolve_output_path", lambda *a, **k: tmp_path / "out.tsv")

    seen_kwargs: dict = {}
    monkeypatch.setattr(audio, "_finish_audio",
                        lambda cards, tsv, media, args, refused=0, failures=0: seen_kwargs.update(cards=cards, media=media))

    audio.run_audio(_args(tmp_path, source))

    assert calls == ["collection_01.mp3", "collection_02.mp3", "collection_03.mp3"]
    assert len(seen_kwargs["cards"]) == 3
    assert seen_kwargs["media"] == extracts          # the extracts follow the cards
    assert source not in seen_kwargs["media"]        # the original file does not

    output = capsys.readouterr().out
    assert not JAPANESE.search(output), "the log gives the audio content away"


def test_an_unsplit_file_keeps_its_own_sound(tmp_path, monkeypatch):
    """No re-encoding, but a name of our own: `collection.media` has a single
    namespace, and any other collection may carry a `simple.mp3`."""
    source = tmp_path / "simple.mp3"
    source.write_bytes(b"some sound")

    def forbidden(*a, **k):
        raise AssertionError("an unsplit file has nothing to re-encode")

    monkeypatch.setattr(audio, "AIClient", lambda **k: object())
    monkeypatch.setattr(whisper, "_transcribe", lambda *a, **k: SEGMENTS)
    monkeypatch.setattr(audio_split, "split_audio",
                        lambda *a, **k: audio_split.whole_block(SEGMENTS))
    monkeypatch.setattr(audio, "_extract_span", forbidden)
    monkeypatch.setattr(audio, "_generate_for_audio", _ai_result)
    monkeypatch.setattr(audio, "append_cards", lambda *a, **k: None)
    monkeypatch.setattr(audio, "resolve_output_path", lambda *a, **k: tmp_path / "out.tsv")

    seen_kwargs: dict = {}
    monkeypatch.setattr(audio, "_finish_audio",
                        lambda cards, tsv, media, args, refused=0, failures=0: seen_kwargs.update(media=media))

    audio.run_audio(_args(tmp_path, source))

    (media,) = seen_kwargs["media"]
    assert media != source                       # the bare name does not enter Anki
    assert media.read_bytes() == b"some sound"       # but the sound is intact
    assert media.name.startswith("simple_")      # and stays recognisable
    assert source.exists()                       # the user's file is theirs


def test_two_files_of_the_same_name_do_not_share_a_transcript(tmp_path, monkeypatch):
    """`01.mp3` opens every past-paper collection: a cache keyed on the stem
    alone would serve the second file the transcript of the first."""
    texts = iter(["いちばん", "にばん"])

    class Model:
        def transcribe(self, path, **kwargs):
            return {"segments": [{"text": next(texts), "start": 0.0, "end": 1.0,
                                  "words": []}]}

    monkeypatch.setattr(whisper, "_load_whisper",
                        lambda: SimpleNamespace(load_model=lambda name: Model()))

    work_dir = tmp_path / "cache"
    work_dir.mkdir()
    first, second = tmp_path / "a", tmp_path / "b"
    for folder in (first, second):
        folder.mkdir()
        (folder / "01.mp3").write_bytes(b"")

    cache: dict = {}
    a = whisper._transcribe(first / "01.mp3", "small", cache, work_dir)
    b = whisper._transcribe(second / "01.mp3", "small", cache, work_dir)

    assert [s.text for s in a] != [s.text for s in b]
    assert len(list(work_dir.iterdir())) == 2


def _extracting_tracks(monkeypatch) -> None:
    """Fakes ffmpeg: the track `extract_audio_track` writes holds the video's bytes."""
    from kotogen.generators import nhk

    def extract(src, out_dir, stem, level, track=None):
        dest = out_dir / f"{stem}.m4a"
        dest.write_bytes(src.read_bytes())
        return dest

    monkeypatch.setattr(nhk, "probe_audio_tracks", lambda video: [])
    monkeypatch.setattr(nhk, "extract_audio_track", extract)


def _whisper_reading_the_file(monkeypatch) -> list[str]:
    """Fakes Whisper: it hears the bytes of the file; hands back what it transcribed."""
    heard: list[str] = []

    class Model:
        def transcribe(self, path, **kwargs):
            text = Path(path).read_bytes().decode()
            heard.append(text)
            return {"segments": [{"text": text, "start": 0.0, "end": 1.0, "words": []}]
                    if text else []}

    monkeypatch.setattr(whisper, "_load_whisper",
                        lambda: SimpleNamespace(load_model=lambda name: Model()))
    return heard


def test_two_videos_of_the_same_name_do_not_share_a_transcript(tmp_path, monkeypatch):
    """`S01/01.mkv` and `S02/01.mkv`: their tracks, extracted into one folder,
    must not land on the same file, nor their transcripts under the same key."""
    from kotogen.generators import audio_files

    _extracting_tracks(monkeypatch)
    _whisper_reading_the_file(monkeypatch)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    heard = {}
    for season in ("S01", "S02"):
        video = tmp_path / season / "01.mkv"
        video.parent.mkdir()
        video.write_bytes(season.encode())
        track, _ = audio_files._extract_track(video, work_dir, None)
        heard[season] = whisper._transcribe(track, "small", {}, work_dir,
                                            source=video)[0].text

    assert heard == {"S01": "S01", "S02": "S02"}
    # The media cut from the track are named after the video, as before.
    assert audio_files._readable(track.stem) == "01"


def test_a_video_transcript_is_filed_under_the_video(tmp_path, monkeypatch):
    """A downloaded video's track is extracted into each run's temporary folder:
    filed under the track, its transcript would be made again at every run, and
    the cleanup of the source, which deletes `_cache_key(<video>)`, would leave
    it behind."""
    heard = _whisper_reading_the_file(monkeypatch)
    cache = tmp_path / "cache"
    cache.mkdir()
    video = cache / "episode.webm"
    video.write_bytes(b"")
    for run in ("run1", "run2"):
        track = tmp_path / run / "episode_0123abcd.m4a"
        track.parent.mkdir()
        track.write_bytes("ことば".encode())
        whisper._transcribe(track, "small", {}, cache, source=video)

    assert heard == ["ことば"], "the second run transcribed again"
    assert (cache / whisper._cache_key(video)).is_file()


def test_an_empty_transcript_is_not_made_again(tmp_path, monkeypatch):
    """A file where Whisper hears nothing: without its empty transcript filed,
    every pass would pay minutes of computation to hear nothing again."""
    heard = _whisper_reading_the_file(monkeypatch)
    audio_path = tmp_path / "music.mp3"
    audio_path.write_bytes(b"")

    first = whisper._transcribe(audio_path, "small", {}, tmp_path)
    second = whisper._transcribe(audio_path, "small", {}, tmp_path)

    assert first == second == []
    assert heard == [""]


def test_the_transcripts_are_filed_whole_or_not_at_all(tmp_path, monkeypatch):
    """The file holds every model's transcript: cut by a Ctrl+C half written, it
    would lose the ones already paid for in minutes of computation."""
    _whisper_counting(monkeypatch)
    audio_path = tmp_path / "01.mp3"
    audio_path.write_bytes(b"")
    written: list[Path] = []
    monkeypatch.setattr(whisper.system, "write_whole",
                        lambda path, text: written.append(path))

    whisper._transcribe(audio_path, "small", {}, tmp_path)

    assert written == [tmp_path / whisper._cache_key(audio_path)]


def _transcribed_as(tmp_path, monkeypatch, transcribe) -> tuple[dict, list[Path]]:
    """Runs one file through `transcribe`; gives the summary's counts and the files
    marked handled."""
    source = tmp_path / "lesson.mp3"
    source.write_bytes(b"")
    monkeypatch.setattr(audio, "AIClient", lambda **k: object())
    monkeypatch.setattr(whisper, "_transcribe", transcribe)
    monkeypatch.setattr(audio, "resolve_output_path", lambda *a, **k: tmp_path / "out.tsv")
    counts: dict = {}
    monkeypatch.setattr(audio, "_finish_audio",
                        lambda cards, tsv, media, args, refused=0, failures=0:
                        counts.update(refused=refused, failures=failures))
    marked: list[Path] = []
    monkeypatch.setattr(audio.audio_files, "_mark_handled",
                        lambda audio_path, remote, roots: marked.append(audio_path))

    audio.run_audio(_args(tmp_path, source))
    return counts, marked


def test_a_file_lost_at_its_transcription_is_a_breakdown(tmp_path, monkeypatch):
    """The summary of the run must count it with the other breakdowns, and the
    file stays to do."""
    def transcribe(*a, **k):
        raise RuntimeError("Failed to load audio")

    counts, marked = _transcribed_as(tmp_path, monkeypatch, transcribe)

    assert counts == {"refused": 0, "failures": 1}
    assert marked == []


def test_a_file_that_hears_nothing_is_handled_and_left_behind(tmp_path, monkeypatch):
    """Its empty transcript is filed: offered again, the file would hold
    `podcast --latest 1` on it at every run."""
    counts, marked = _transcribed_as(tmp_path, monkeypatch, lambda *a, **k: [])

    assert counts == {"refused": 1, "failures": 0}
    assert [path.name for path in marked] == ["lesson.mp3"]


def _whisper_counting(monkeypatch, refused: tuple[str, ...] = ()) -> list[str]:
    """Fakes Whisper; hands back the names of the models that transcribed."""
    used: list[str] = []

    class Model:
        def __init__(self, name):
            self.name = name

        def transcribe(self, path, **kwargs):
            used.append(self.name)
            return {"segments": [{"text": f"{self.name}のことば", "start": 0.0,
                                  "end": 1.0, "words": []}]}

    def load_model(name):
        if name in refused:
            raise RuntimeError("not enough memory")
        return Model(name)

    monkeypatch.setattr(whisper, "_load_whisper",
                        lambda: SimpleNamespace(load_model=load_model))
    return used


def test_a_transcript_serves_only_the_model_that_made_it(tmp_path, monkeypatch):
    """`small` transcribes less faithfully: its transcript is no answer to a
    `--whisper-model large` run, which is what the larger model is asked for."""
    used = _whisper_counting(monkeypatch)
    audio_path = tmp_path / "01.mp3"
    audio_path.write_bytes(b"")

    whisper._transcribe(audio_path, "small", {}, tmp_path)
    large = whisper._transcribe(audio_path, "large", {}, tmp_path)
    again = whisper._transcribe(audio_path, "small", {}, tmp_path)

    assert used == ["small", "large"]
    assert large[0].text == "largeのことば" and again[0].text == "smallのことば"


def test_a_fallback_transcript_is_filed_under_the_fallback(tmp_path, monkeypatch):
    """`medium` would not load and `small` did the work: a later run where
    `medium` loads must not take that transcript for its own."""
    audio_path = tmp_path / "01.mp3"
    audio_path.write_bytes(b"")

    used = _whisper_counting(monkeypatch, refused=("medium",))
    whisper._transcribe(audio_path, "medium", {}, tmp_path)
    used = _whisper_counting(monkeypatch)
    segments = whisper._transcribe(audio_path, "medium", {}, tmp_path)

    assert used == ["medium"]
    assert segments[0].text == "mediumのことば"


def test_after_a_fallback_a_transcript_of_the_model_asked_for_still_serves(
        tmp_path, monkeypatch):
    """`medium` fell back on `small` for one file of the run: another, which an
    earlier run transcribed with `medium`, keeps that transcript."""
    earlier, fresh = tmp_path / "earlier.mp3", tmp_path / "fresh.mp3"
    earlier.write_bytes(b"")
    fresh.write_bytes(b"")
    _whisper_counting(monkeypatch)
    whisper._transcribe(earlier, "medium", {}, tmp_path)

    used = _whisper_counting(monkeypatch, refused=("medium",))
    models: dict = {}
    whisper._transcribe(fresh, "medium", models, tmp_path)
    segments = whisper._transcribe(earlier, "medium", models, tmp_path)

    assert used == ["small"]
    assert segments[0].text == "mediumのことば"


def test_a_transcript_that_cannot_be_filed_still_serves(tmp_path, monkeypatch, capsys):
    _whisper_counting(monkeypatch)

    def full(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(whisper.system, "write_whole", full)
    segments = whisper._transcribe(tmp_path / "01.mp3", "small", {}, tmp_path)

    assert segments[0].text == "smallのことば"
    assert "No space left on device" in capsys.readouterr().err


def test_a_transcript_of_an_unknown_shape_is_made_again(tmp_path, monkeypatch):
    """A cache entry that is not filed by model, or does not read, is ignored."""
    used = _whisper_counting(monkeypatch)
    audio_path = tmp_path / "01.mp3"
    audio_path.write_bytes(b"")
    (tmp_path / whisper._cache_key(audio_path)).write_text(
        '[{"text": "むかし", "start": 0.0, "end": 1.0}]', encoding="utf-8")

    assert whisper._transcribe(audio_path, "small", {}, tmp_path)[0].text == "smallのことば"
    assert used == ["small"]


def test_a_file_with_no_substance_is_not_a_breakage(tmp_path, monkeypatch, capsys):
    """A shadowing book has no comprehension to check: zero cards is the right
    result, with no error and no non-zero exit code."""
    source = tmp_path / "shadowing.mp3"
    source.write_bytes(b"")

    nothing = audio_split.Split("collection", [], [audio_split.Dropped(0.0, 2.0, "number")])
    monkeypatch.setattr(audio, "AIClient", lambda **k: object())
    monkeypatch.setattr(whisper, "_transcribe", lambda *a, **k: SEGMENTS)
    monkeypatch.setattr(audio_split, "split_audio", lambda *a, **k: nothing)
    monkeypatch.setattr(audio, "resolve_output_path", lambda *a, **k: tmp_path / "out.tsv")

    audio.run_audio(_args(tmp_path, source))  # must not raise SystemExit

    output = capsys.readouterr().out
    assert "No card: these audio files carry no comprehension" in output
    assert "Error" not in output
    # Said once by the per-file verdict, not again by the run's conclusion.
    assert output.count("no usable passage") == 1


def test_a_breakage_is_still_a_breakage(tmp_path, monkeypatch):
    """With no explicit refusal, zero cards still means something broke, and the
    output has to say so."""
    with pytest.raises(SystemExit):
        audio._finish_audio([], tmp_path / "out.tsv", [],
                            argparse.Namespace(send=False), refused=0)


def test_whisper_does_not_unroll_its_progress_bar(tmp_path, monkeypatch):
    """`verbose=False` still shows Whisper's tqdm bar; only None hides it."""
    passed: dict = {}

    class Model:
        def transcribe(self, path, **kwargs):
            passed.update(kwargs)
            return {"segments": [{"text": "はい", "start": 0.0, "end": 1.0, "words": []}]}

    monkeypatch.setattr(whisper, "_load_whisper",
                        lambda: SimpleNamespace(load_model=lambda name: Model()))
    whisper._transcribe(tmp_path / "x.mp3", "small", {}, tmp_path)

    assert passed["verbose"] is None
    assert passed["word_timestamps"] is True


def test_the_counter_reads_how_far_whisper_has_got():
    """The tqdm bar is the only place Whisper says how far it has got.

    It counts frames of 10 ms, turned into the audio time on the waiting line;
    without it a long transcription looks hung.
    """
    counter = whisper._Counter()
    # Nothing to show until Whisper gives the total length.
    assert counter.status() == ""

    counter(total=9 * 60 * whisper.FRAMES_PER_SECOND, unit="frames", disable=True)
    counter.update(60 * whisper.FRAMES_PER_SECOND)

    assert counter.status() == "01:00 of 09:00"


def test_the_download_of_the_weights_is_said_at_the_end_of_the_line(monkeypatch, capsys):
    """The first transcription spends minutes downloading the model. Said on a
    line of its own, it would reopen "Transcribing…" below it: it goes at the
    end of the action line, and is erased from there."""
    seen: list[str] = []
    fake = SimpleNamespace()
    slot = object()
    fake.tqdm = slot

    def load_model(name):
        # What Whisper does when the weights are missing: it opens its bar, feeds
        # it byte by byte, then closes it.
        with fake.tqdm(total=1_527_000_000, unit="iB") as bar:
            bar.update(700_000_000)
            seen.append(bar.status())
        seen.append(bar.status())
        return "model"

    fake.load_model = load_model
    monkeypatch.setattr(whisper, "_load_whisper", lambda: fake)

    assert whisper._load("medium") == ("model", "medium")
    assert seen[0] == "model to download once only, 667.6 MB of 1.4 GB"
    # The bar closed, the detail goes: checking and loading the weights is not
    # network, and has no figure to show.
    assert seen[1] == ""
    # Nothing on a line of its own: all of it went to the end of the open
    # action, which the spinner erases before the result.
    assert capsys.readouterr().out == ""
    # And the original tqdm is put back.
    assert fake.tqdm is slot


def test_a_whisper_with_no_bar_loads_all_the_same(monkeypatch):
    """A module with no tqdm costs a silent waiting line, never the model."""
    monkeypatch.setattr(whisper, "_load_whisper",
                        lambda: SimpleNamespace(load_model=lambda name: "model"))

    assert whisper._load("medium") == ("model", "medium")


def test_a_window_that_will_not_pass_stops_the_transcription():
    """Whisper may bring its cursor back and decode the same window for ever:
    zero frames of progress is the only sign, and three in a row settle it."""
    counter = whisper._Counter()
    counter(total=1000)

    for _ in range(whisper.STALL_MAX - 1):
        counter.update(0)
    counter.update(300)  # it got out by itself: the count starts again at zero

    for _ in range(whisper.STALL_MAX - 1):
        counter.update(0)
    with pytest.raises(whisper._Trapped):
        counter.update(0)


def test_a_transcription_that_stalls_retries_with_no_context(tmp_path, capsys):
    """The context Whisper carries from one window to the next is what traps it:
    the retry drops it, and says so, since it costs the time again."""
    contexts: list[bool] = []

    class Model:
        def transcribe(self, path, **kwargs):
            contexts.append(kwargs["condition_on_previous_text"])
            if kwargs["condition_on_previous_text"]:
                raise whisper._Trapped("Whisper is going back over the same window at 02:30")
            return {"segments": [{"text": "はい", "start": 0.0, "end": 1.0}]}

    result = whisper._watched_transcribe(Model(), tmp_path / "x.mp3")

    assert contexts == [True, False]
    assert result["segments"]
    assert "retrying without context" in capsys.readouterr().out


def test_a_stall_that_lasts_drops_the_file(tmp_path):
    """A second stall raises: the file is dropped, the next ones go through."""
    class Model:
        def transcribe(self, path, **kwargs):
            raise whisper._Trapped("Whisper is going back over the same window at 02:30")

    with pytest.raises(whisper._Trapped):
        whisper._watched_transcribe(Model(), tmp_path / "x.mp3")


def test_a_whisper_model_too_heavy_falls_back_and_says_so(monkeypatch, capsys):
    """`medium` needs 1.5 GB and memory. The run falls back on `small`, saying
    so: a less faithful transcript means wrong cards."""
    loaded: list[str] = []

    def load_model(name):
        loaded.append(name)
        if name == "medium":
            raise RuntimeError("not enough memory")
        return "model"

    monkeypatch.setattr(whisper, "_load_whisper",
                        lambda: SimpleNamespace(load_model=load_model))

    assert whisper._load_model("medium") == ("model", whisper.WHISPER_FALLBACK)
    assert loaded == ["medium", whisper.WHISPER_FALLBACK]
    assert "falling back on" in capsys.readouterr().err


def test_a_fallback_that_fails_in_turn_does_not_stay_silent(monkeypatch):
    """Otherwise the real error would be replaced by a second vain attempt."""
    def load_model(name):
        raise RuntimeError("no room left on the disk")

    monkeypatch.setattr(whisper, "_load_whisper",
                        lambda: SimpleNamespace(load_model=load_model))
    with pytest.raises(RuntimeError, match="no room"):
        whisper._load_model(whisper.WHISPER_FALLBACK)


def test_the_output_does_not_open_on_an_empty_line(tmp_path, monkeypatch, capsys):
    """The interactive dialogue already ends on an empty line. The output
    watcher is installed as `cli.main()` does: it knows no line came before."""
    console.watch()
    source = tmp_path / "simple.mp3"
    source.write_bytes(b"")

    monkeypatch.setattr(audio, "AIClient", lambda **k: object())
    monkeypatch.setattr(whisper, "_transcribe", lambda *a, **k: SEGMENTS)
    monkeypatch.setattr(audio_split, "split_audio",
                        lambda *a, **k: audio_split.whole_block(SEGMENTS))
    monkeypatch.setattr(audio, "_generate_for_audio", _ai_result)
    monkeypatch.setattr(audio, "append_cards", lambda *a, **k: None)
    monkeypatch.setattr(audio, "resolve_output_path", lambda *a, **k: tmp_path / "out.tsv")
    monkeypatch.setattr(audio, "_finish_audio", lambda *a, **k: None)

    audio.run_audio(_args(tmp_path, source))

    output = capsys.readouterr().out
    assert output.startswith("Audio files\n")
    # One empty line separates two blocks; never two, and never at the head.
    assert "\n\n\n" not in output


def test_a_passage_that_is_too_long_is_dropped(tmp_path, monkeypatch, capsys):
    """`--max-duration` bears on the piece that ends up on the card."""
    source = tmp_path / "collection.mp3"
    source.write_bytes(b"")

    split = audio_split.Split(
        "collection",
        [audio_split.Block((2, 3), ((0.0, 300.0),)),
         audio_split.Block((4,), ((300.0, 320.0),))],
        [],
    )

    calls: list[str] = []
    monkeypatch.setattr(audio, "AIClient", lambda **k: object())
    monkeypatch.setattr(whisper, "_transcribe", lambda *a, **k: SEGMENTS)
    monkeypatch.setattr(audio_split, "split_audio", lambda *a, **k: split)
    monkeypatch.setattr(audio, "_extract_span",
                        lambda src, block, rank, out_dir, bitrate: out_dir / f"x_{rank}.mp3")
    monkeypatch.setattr(audio, "_generate_for_audio",
                        lambda client, name, *a, **k: calls.append(name) or _ai_result())
    monkeypatch.setattr(audio, "append_cards", lambda *a, **k: None)
    monkeypatch.setattr(audio, "resolve_output_path", lambda *a, **k: tmp_path / "out.tsv")
    monkeypatch.setattr(audio, "_finish_audio", lambda *a, **k: None)

    args = _args(tmp_path, source)
    args.max_duration = 60
    audio.run_audio(args)

    assert calls == ["x_2.mp3"]
    assert "beyond" in capsys.readouterr().out


@pytest.mark.parametrize("lang", [name for name in i18n.available()
                                  if name != i18n.SOURCE])
def test_every_table_says_how_a_file_was_taken_whole(lang):
    """`KIND_WHOLE` and `KIND_TRIMMED` close the splitting line, translated
    where `show` says them: the scan of the literals does not see them."""
    table = i18n._load(lang)
    wanted = [audio_split.KIND_WHOLE, audio_split.KIND_TRIMMED]
    assert [key for key in wanted if key not in table] == []
