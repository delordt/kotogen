"""Finding, for each line of the card, the second where it starts.

The lines of the card are not the lines of the source (the model glues, splits,
corrects, labels and adds furigana), so the matching is done on the text. A line
not found is placed on its reading, then pro rata of its text, but always between
its neighbours, and nothing is placed when no line was recognised. The moment is
then brought back to the time of the piece, which differs from the file's once
something is cut from its middle.
"""

from __future__ import annotations

from kotogen.generators import timecodes
from kotogen.generators.audio_split import Block, Segment, Word


def seg(text: str, start: float, end: float, words=()) -> Segment:
    return Segment(text, start, end, tuple(Word(t, d, f) for t, d, f in words))


# A "Whisper" source: words timestamped one by one.
WITH_WORDS = [
    seg("すみません、駅はどこですか。", 0.5, 2.4,
        [("すみません", 0.5, 1.1), ("駅", 1.2, 1.4), ("は", 1.5, 1.6),
         ("どこ", 1.7, 1.9), ("ですか", 2.0, 2.4)]),
    seg("まっすぐ行ってください。", 3.0, 4.4,
        [("まっすぐ", 3.0, 3.4), ("行って", 3.5, 3.9), ("ください", 4.0, 4.4)]),
]

# A "subtitle" source: no words, only the bounds of the cue.
WITHOUT_WORDS = [
    seg("すみません、駅はどこですか。", 0.5, 2.4),
    seg("まっすぐ行ってください。", 3.0, 4.4),
]

# What the model hands back: speaker labels and furigana on top.
LINES = ["A：すみません、 駅[えき]はどこですか。", "B：まっすぐ 行[い]ってください。"]


def everything(segments):
    """The block taking every segment, dropping nothing."""
    return Block(tuple(range(1, len(segments) + 1)), ((0.0, 60.0),))


# ── Finding the line again ────────────────────────────────────────────────────

def test_timestamped_words_give_the_moment_to_the_mora(monkeypatch):
    field = timecodes.for_lines(LINES, WITH_WORDS, everything(WITH_WORDS), whole=True)

    assert field == "0.50 3.00"


def test_a_subtitle_gives_the_moment_of_the_cue():
    """Coarser, and right: the start of the cue is where one wants to listen again."""
    field = timecodes.for_lines(LINES, WITHOUT_WORDS, everything(WITHOUT_WORDS), whole=True)

    assert field == "0.50 3.00"


def test_label_reading_and_punctuation_do_not_get_in_the_way():
    """None of that exists in the source: "店員：" is laid by the model, so are
    the furigana, and the punctuation does not survive Whisper."""
    segments = [seg("いらっしゃいませ", 7.0, 8.0)]
    lines = ["店員[てんいん]：いらっしゃいませ！"]

    assert timecodes.for_lines(lines, segments, everything(segments), whole=True) == "7.00"


def test_the_model_glues_two_segments_into_one_line():
    """Whisper cuts at a breath and the model glues the sentence back: the moment
    is that of the first piece, where the sentence starts."""
    segments = [seg("今日は", 1.0, 1.5), seg("いい天気ですね", 1.6, 3.0)]

    field = timecodes.for_lines(["今日[きょう]はいい 天気[てんき]ですね"],
                                segments, everything(segments), whole=True)

    assert field == "1.00"


# ── Not finding it in the wrong place ─────────────────────────────────────────

def test_a_repeated_cue_follows_the_order_of_the_lines():
    """「はい」 comes back three times: without a cursor, all three lines would
    take the first one's moment, silently."""
    segments = [seg("はい", 1.0, 1.4), seg("そうですね", 2.0, 2.8),
                seg("はい", 5.0, 5.4), seg("わかりました", 6.0, 7.0),
                seg("はい", 9.0, 9.4)]
    lines = ["A：はい", "B：そうですね", "A：はい", "B：わかりました", "A：はい"]

    field = timecodes.for_lines(lines, segments, everything(segments), whole=True)

    assert field == "1.00 2.00 5.00 6.00 9.00"


def test_a_line_that_cannot_be_found_files_itself_pro_rata_of_its_text():
    """A line rewritten past recognition is placed between its neighbours by the
    share of its text: two texts of one length over three seconds, half each."""
    segments = [seg("おはようございます", 1.0, 2.0), seg("いい天気ですね", 3.0, 4.0)]
    lines = ["おはようございます", "まったく別の文です"]

    field = timecodes.for_lines(lines, segments, everything(segments), whole=True)

    assert field == "1.00 2.50"


def test_a_rescued_moment_never_doubles_a_neighbour():
    """The safeguard of the rescue: between its neighbours, strictly."""
    segments = [seg("おはようございます", 1.0, 2.0), seg("いい天気ですね", 5.0, 6.0)]
    lines = ["おはようございます", "まったく別の文です", "いい天気ですね"]

    moments = [float(m) for m in
               timecodes.marks(lines, segments, everything(segments), whole=True)]

    assert moments[0] < moments[1] < moments[2]


def test_the_pro_rata_says_that_it_is_pro_rata():
    """The field cannot tell a recognised moment from a spread one; the log can,
    and the generation reports it from there."""
    segments = [seg("おはようございます", 1.0, 2.0), seg("いい天気ですね", 3.0, 4.0)]
    lines = ["おはようございます", "まったく別の文です"]

    log: list[str] = []
    timecodes.for_lines(lines, segments, everything(segments), whole=True, log=log)

    assert log == [timecodes.EXACT, timecodes.PRORATA]


def test_a_word_corrected_at_the_end_of_a_line_does_not_lose_the_line():
    """`自信` for 地震: the model corrects the end, so the line is shortened until
    it matches rather than thrown away."""
    segments = [seg("昨日の夜に自信がありました", 5.0, 8.0)]
    lines = ["昨日[きのう]の 夜[よる]に 地震[じしん]がありました"]

    assert timecodes.for_lines(lines, segments, everything(segments), whole=True) == "5.00"


def test_no_line_found_hands_back_an_empty_field():
    """A row of dashes would say no more than an empty field."""
    segments = [seg("おはようございます", 1.0, 2.0)]

    assert timecodes.for_lines(["まったく別", "something else again"],
                               segments, everything(segments), whole=True) == ""


def test_with_no_timestamped_source_the_field_is_empty():
    """No transcribed sound: nothing to timestamp."""
    assert timecodes.for_lines(LINES, [], None) == ""
    assert timecodes.for_lines([], WITH_WORDS, None) == ""


# ── Matching on the reading, when the spellings diverge ───────────────────────

# The NHK Easy case: Whisper hears kanji, the article is written in kana, and the
# two spellings of one sentence are not found inside each other.
HEARD = [seg("今日は雨が降りました。", 0.0, 4.0),
         seg("電車が止まりました。", 5.0, 8.0)]
WRITTEN = ["きょうは 雨[あめ]が 降[ふ]りました。", "電車[でんしゃ]が 止[と]まりました。"]


def test_a_word_added_at_the_head_of_a_line_does_not_lose_the_line():
    """The model adds a barely audible 「はい。」 up front: cropping from the end
    would keep precisely the faulty start."""
    segments = [seg("電車が止まりました。", 0.0, 4.0)]

    assert timecodes._match(["はい。電車が止まりました。"], segments)[0] == ["0.00"]


def test_a_line_does_not_match_by_its_conjugation_alone():
    """The crop keeps an ending, and 「まりました」 runs through any text in the
    past: half the line must match, not its last five characters."""
    segments = [seg("電車が止まりました。", 0.0, 4.0)]
    foreign = ["あさはやくいえをでたのにバスがとまりました。"]

    assert timecodes._match(foreign, segments)[0] == [timecodes.UNKNOWN]


def test_a_divergence_at_the_head_of_a_line_is_crossed_by_cropping_the_start():
    """「きょう」 for 「今日」: cropping the start catches the intact end, and the
    moment is read back that many characters upstream, at the start of the cue."""
    assert timecodes._match(WRITTEN, HEARD)[0] == ["0.00", "5.00"]


# The same text all in kana: no five-character piece survives the comparison of
# spellings (「降りました」 against 「ふりました」); only the reading matches them.
ALL_KANA = ["きょうはあめがふりました。", "でんしゃがとまりました。"]


def test_the_reading_rescues_what_the_spelling_missed():
    """Even unasked, the unused comparator serves as a rescue, either way round."""
    assert timecodes._match(ALL_KANA, HEARD)[0] == [timecodes.UNKNOWN] * 2

    log: list[str] = []
    assert timecodes.marks(ALL_KANA, HEARD, log=log) == ["0.00", "5.00"]
    assert log == [timecodes.READING, timecodes.READING]


def test_the_reading_finds_both_spellings():
    assert timecodes.for_lines(WRITTEN, HEARD, None, reading=True) == "0.00 5.00"


# ── What the audio does not say ───────────────────────────────────────────────

def test_the_tail_the_sound_does_not_say_is_dropped():
    """The voice file stops before the end of the article: the rest is dropped."""
    lines = [*WRITTEN, "あしたも 雨[あめ]でしょう。", "天気[てんき]の 話[はなし]"]

    kept, silent = timecodes.spoken_lines(lines, HEARD, reading=True)

    assert kept == WRITTEN
    assert len(silent) == 2


def test_a_sound_still_speaking_makes_nothing_be_dropped():
    """The last line is not found, but the sound goes on as long: the matching
    failed (a reading settled otherwise), the sound is not missing."""
    heard = [*HEARD, seg("明日も雨でしょう。", 9.0, 12.0)]
    lines = [*WRITTEN, "あしたも 雨[あめ]でしょう。"]

    kept, silent = timecodes.spoken_lines(lines, heard, reading=True)

    assert kept == lines
    assert silent == []


def test_a_gap_in_the_middle_is_never_dropped():
    """Only the tail goes: a missing line in the middle is a misheard word."""
    lines = [WRITTEN[0], "まったく 別[べつ]の 文[ぶん]です。", WRITTEN[1]]

    kept, silent = timecodes.spoken_lines(lines, HEARD, reading=True)

    assert kept == lines
    assert silent == []


def test_no_line_at_all_in_the_sound_keeps_nothing():
    """Audio unrelated to the text: the caller recognises it by the empty list."""
    kept, silent = timecodes.spoken_lines(
        ["まったく 別[べつ]の 記事[きじ]です。"], HEARD, reading=True)

    assert kept == []
    assert len(silent) == 1


# ── Bringing the moment back to the time of the piece ─────────────────────────

def test_an_extract_is_rebased_on_its_start():
    """A piece cut from 10 s into the file: a line at 10 s is at 0 s of the piece."""
    segments = [seg("おはよう", 10.0, 11.0), seg("こんにちは", 14.0, 15.0)]
    block = Block((1, 2), ((10.0, 16.0),))

    field = timecodes.for_lines(["おはよう", "こんにちは"], segments, block)

    assert field == "0.00 4.00"


def test_a_gap_in_the_middle_of_the_passage_is_deducted():
    """The split may drop something in the middle (an exam question between two
    exchanges): everything after the gap moves back by its length."""
    segments = [seg("おはよう", 10.0, 11.0), seg("こんにちは", 32.0, 33.0)]
    #        kept: 10->12 (2 s)   dropped: 12->30   kept: 30->35
    block = Block((1, 2), ((10.0, 12.0), (30.0, 35.0)))

    field = timecodes.for_lines(["おはよう", "こんにちは"], segments, block)

    assert field == "0.00 4.00", "2 s of first range, then 32-30"


def test_a_whole_file_is_never_rebased():
    """The original file joins the media library as it is: its time is already right."""
    segments = [seg("おはよう", 10.0, 11.0)]
    block = Block((1,), ((0.0, 11.0),))

    assert timecodes.for_lines(["おはよう"], segments, block, whole=True) == "10.00"


def test_the_block_only_looks_at_its_own_lines():
    """A collection: the second passage must not match on the first, whose text
    is nonetheless in the same `segments`."""
    segments = [seg("はい", 1.0, 2.0), seg("いいえ", 20.0, 21.0)]
    block = Block((2,), ((20.0, 22.0),))

    assert timecodes.for_lines(["いいえ"], segments, block) == "0.00"


def test_a_moment_is_never_negative():
    """A slightly generous range bound (the attack margin) can place the first
    word before the declared start of the piece."""
    segments = [seg("おはよう", 9.9, 11.0)]
    block = Block((1,), ((10.0, 12.0),))

    assert timecodes.for_lines(["おはよう"], segments, block) == "0.00"


def test_the_first_line_lands_on_the_speech_and_not_on_the_silence():
    """An unrecognised opening line takes the moment of the first word, not zero:
    otherwise a jingle opening the passage would be replayed before the sentence."""
    segments = [seg("おはようございます", 2.0, 3.0,
                    [("おはよう", 2.0, 2.5), ("ございます", 2.6, 3.0)]),
                seg("いい天気ですね", 4.0, 5.0,
                    [("いい", 4.0, 4.4), ("天気ですね", 4.5, 5.0)])]
    lines = ["まったく別の文です", "いい天気ですね"]

    field = timecodes.for_lines(lines, segments, everything(segments), whole=True)

    assert field.split()[0] == "2.00"


def test_without_a_timestamped_word_the_first_line_takes_the_cue_start():
    """A subtitle source has no words: the bound is the cue."""
    segments = [seg("おはようございます", 2.0, 3.0), seg("いい天気ですね", 4.0, 5.0)]
    lines = ["まったく別の文です", "いい天気ですね"]

    assert timecodes.for_lines(lines, segments, everything(segments),
                               whole=True).split()[0] == "2.00"


def test_nothing_recognised_is_not_spread():
    """With no anchor at all, the field stays empty rather than spreading the text."""
    segments = [seg("おはようございます", 1.0, 2.0)]

    assert timecodes.for_lines(["まったく別", "something else again"],
                               segments, everything(segments), whole=True) == ""
