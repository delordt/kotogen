"""Cutting the lines of an NHK article into sentences (listening card).

The back of the card shows the transcript line by line, each translation under
its line: a whole paragraph there would face a slab of translation.
"""

from kotogen.generators.nhk import split_sentences


def test_a_paragraph_becomes_one_line_per_sentence():
    lines = split_sentences([
        "今日[きょう]は 雪[ゆき]が 降[ふ]りました。 電車[でんしゃ]が 止[と]まりました。"
    ])
    assert lines == [
        "今日[きょう]は 雪[ゆき]が 降[ふ]りました。",
        "電車[でんしゃ]が 止[と]まりました。",
    ]


def test_questions_and_exclamations_cut_too():
    assert split_sentences(["どうしますか？ 分[わ]かりません！ また 明日[あした]。"]) == [
        "どうしますか？",
        "分[わ]かりません！",
        "また 明日[あした]。",
    ]


def test_closing_punctuation_stays_with_its_sentence():
    # 。 followed by a closing quote: the quoted sentence is not over.
    assert split_sentences(["「 危[あぶ]ないです。」と 言[い]いました。 皆[みんな]が 逃[に]げました。"]) == [
        "「 危[あぶ]ないです。」と 言[い]いました。",
        "皆[みんな]が 逃[に]げました。",
    ]


def test_a_line_with_no_final_punctuation_is_unchanged():
    # Titles and single sentences: nothing to cut.
    assert split_sentences(["東京[とうきょう]の 大[おお]きな 地震[じしん]"]) == [
        "東京[とうきょう]の 大[おお]きな 地震[じしん]"
    ]


def test_ellipses_do_not_cut_in_the_middle():
    assert split_sentences(["ええと…… そうですね。"]) == ["ええと…… そうですね。"]


def test_decimals_are_not_a_boundary():
    # The ASCII dot is never the end of a Japanese sentence: 3.5 stays whole.
    assert split_sentences(["3.5メートルの 雪[ゆき]が 積[つ]もりました。"]) == [
        "3.5メートルの 雪[ゆき]が 積[つ]もりました。"
    ]


def test_empty_lines_disappear():
    assert split_sentences(["", "   ", "はい。"]) == ["はい。"]
