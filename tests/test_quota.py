"""The number of questions is a ceiling, never a quota.

It follows the content, stays bounded (never zero cards, never fifty), and gives
way to an explicit `--count`.
"""

from __future__ import annotations

import argparse

import pytest

from kotogen.cli import build_parser, card_count
from kotogen.generators import quota

# Two sentences, some thirty characters: a short audio.
SHORT = ["東京[とうきょう]で 雨[あめ]が 降[ふ]りました。", "みんな 傘[かさ]を 使[つか]いました。"]

# A dozen sentences: the order of magnitude of a real NHK Easy article (180 to
# 240 characters of Japanese, furigana excluded).
ARTICLE = ["今日[きょう]は 東京[とうきょう]で 大[おお]きな 祭[まつ]りが 開[ひら]かれました。"] * 12

# A long text, like a narrative from a JLPT past paper.
LONG = ARTICLE * 5


# ── Reading the option ────────────────────────────────────────────────────────

def test_auto_is_the_default_value():
    """Without --count, the content decides."""
    for command in ("audio", "reading"):
        args = build_parser().parse_args([command, "source"])
        assert args.count is None


def test_auto_can_also_be_given_explicitly():
    assert card_count("auto") is None
    assert card_count(" AUTO ") is None


def test_a_number_stays_a_number():
    assert card_count("4") == 4


@pytest.mark.parametrize("value", ["0", "-2", "3.5", "lots"])
def test_impossible_values_are_refused(value):
    with pytest.raises(argparse.ArgumentTypeError):
        card_count(value)


# ── The ceiling deduced from the content ──────────────────────────────────────

def test_furigana_do_not_inflate_the_content():
    """`降[ふ]りました` weighs its Japanese, not its readings."""
    with_readings = quota.japanese_chars(["降[ふ]りました"])
    without = quota.japanese_chars(["降りました"])
    assert with_readings == without == 5


def test_punctuation_and_labels_do_not_count():
    assert quota.japanese_chars(["A：はい。"]) == quota.japanese_chars(["はい"]) == 2


def test_thin_content_stays_at_the_floor():
    """Two sentences do not carry fifteen questions, but the floor still allows
    a few."""
    assert quota.auto_max(SHORT) == quota.FLOOR


def test_an_article_is_worth_several_questions():
    """Set above real sources on purpose: an NHK Easy article comes out at 7
    where 2 were asked for by hand. A ceiling, not a target."""
    assert quota.japanese_chars(ARTICLE) == pytest.approx(216, abs=40)
    assert quota.auto_max(ARTICLE) == 7


def test_rich_content_is_worth_more():
    assert quota.auto_max(LONG) > quota.auto_max(ARTICLE) > quota.auto_max(SHORT)


def test_the_ceiling_never_goes_past_the_maximum():
    """A spending safeguard: an endless source does not give back a whole deck."""
    assert quota.auto_max(LONG * 50) == quota.CEILING


def test_a_small_book_counts_its_pages_too():
    """Little text, but a picture book's pages still lift it above the floor."""
    assert quota.auto_max(SHORT, pages=24) > quota.auto_max(SHORT)


def test_the_floor_never_comes_down_to_one_question():
    """Even on a nearly empty source: it is a ceiling, not an order."""
    assert quota.auto_max([]) == quota.FLOOR
    assert quota.FLOOR >= 2


def test_an_explicit_count_wins_over_the_calculation():
    assert quota.resolve(6, SHORT) == 6
    assert quota.resolve(None, SHORT) == quota.auto_max(SHORT)


# ── The floor: below it, the AI is not called at all ──────────────────────────

# Two lines of shadowing: a sentence to repeat, with nothing to ask about it.
SHADOWING = ["そうですか", "はい そうです"]

# A conversation the size of the shortest N3 ones: four times heavier, and it
# carries a question.
CONVERSATION = [
    "ねえ、聞いて。", "どうしたの?", "来週から、駅前のパン屋で働くんだ。",
    "へえ、朝早いんじゃない?", "うん、でも楽しみなんだ。",
]


def test_a_shadowing_exchange_carries_no_question():
    """The automatic splitting makes these by the dozen: without this check, each
    would still be asked for up to FLOOR cards, all to throw away."""
    assert quota.japanese_chars(SHADOWING) == 11
    assert not quota.carries_a_question(SHADOWING)


def test_a_real_conversation_passes_the_floor():
    assert quota.japanese_chars(CONVERSATION) == 45
    assert quota.carries_a_question(CONVERSATION)


def test_the_floor_sits_between_the_two():
    """Well clear of both, so an approximate transcript does not tip it."""
    assert (quota.japanese_chars(SHADOWING) < quota.MIN_CHARS
            < quota.japanese_chars(CONVERSATION))


# Complete N5 exchanges (a question, its answer, a fact to remember), each
# under 30 characters.
N5 = [
    ["すみません、駅はどこですか?", "あそこです。銀行の隣です。"],
    ["この本はいくらですか?", "800円です。", "じゃあ、これをください。"],
    ["昨日、どこへ行きましたか?", "友達と映画を見ました。"],
    ["キムさんは何を飲みますか?", "コーヒーをお願いします。"],
    ["山田さん、明日は暇ですか?", "明日?", "うーん、午後なら。"],
    ["日本語の勉強はどうですか?", "漢字がとても難しいです。"],
    ["ここで写真を撮ってもいいですか?", "はい、どうぞ。"],
]


def test_a_short_but_complete_exchange_passes_the_floor():
    """A beginner exchange weighs 18 to 30 characters: a threshold of 30 would
    drop most of them without a call."""
    for lines in N5:
        assert quota.carries_a_question(lines), quota.japanese_chars(lines)


def test_the_floor_still_lets_the_dip_through():
    """Between the shadowing and the shortest complete exchange, almost a factor
    of two is left."""
    shortest = min(quota.japanese_chars(l) for l in N5)
    assert quota.japanese_chars(SHADOWING) < quota.MIN_CHARS < shortest


def test_empty_content_never_goes_to_the_ai():
    assert not quota.carries_a_question([])
    assert not quota.carries_a_question(["   ", "A："])


# ── What is sent to the model, and what comes back ────────────────────────────

def test_the_instruction_says_a_ceiling_and_not_a_target():
    # It follows the language of the cards: French here, pinned by `conftest`.
    instruction = quota.instruction(3)
    assert "AU PLUS 3" in instruction
    assert "exactement" not in instruction.lower()


def test_the_cards_in_excess_are_dropped():
    """The model has the last word on the number, not on going over."""
    cards = [{"Question": f"Q{i}"} for i in range(5)]
    assert quota.enforce(cards, 2) == cards[:2]


def test_the_count_dropped_agrees_with_itself(capsys):
    """One card past the ceiling is not "the last 1 are dropped"."""
    quota.enforce([{"Question": f"Q{i}"} for i in range(4)], 3)
    assert "the last one is dropped" in capsys.readouterr().out
    quota.enforce([{"Question": f"Q{i}"} for i in range(5)], 3)
    assert "the last 2 are dropped" in capsys.readouterr().out


def test_below_the_ceiling_nothing_is_touched():
    cards = [{"Question": "Q1"}]
    assert quota.enforce(cards, 3) == cards
