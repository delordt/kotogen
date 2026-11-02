"""Proofreading the readings against the MeCab dictionary.

These tests need unidic-lite, a dependency of the project. Without it the check
falls silent rather than report falsely, as the last section verifies.
"""

import pytest

from kotogen import dictionary
from kotogen.dictionary import READING_TAG, check, tag_card

mecab = pytest.mark.skipif(
    dictionary.get_tagger() is None, reason="MeCab (fugashi + unidic-lite) unavailable")


# ── Wrong readings: reported ──────────────────────────────────────────────────

@mecab
@pytest.mark.parametrize("expression", [
    "橋[みず]",
    "涼[あつ]しい",
    "図書館[としょしつ]",
    "東京[おおさか]",
    "新聞[しんもん]",
])
def test_an_invented_reading_is_reported(expression):
    found = check(expression)
    assert found is not None, f"{expression} should have been reported"
    assert found[0] == READING_TAG


@mecab
def test_the_message_gives_the_expected_reading():
    """The report says what the dictionary itself reads."""
    _, message = check("橋[みず]")
    assert "はし" in message


def test_the_message_is_one_sentence_whether_the_dictionary_reads_or_not(monkeypatch):
    """Two whole sentences, never a fragment glued on: a translation may need to
    place the reading anywhere in its own."""
    monkeypatch.setattr(dictionary, "_is_unknown", lambda surface: False)
    monkeypatch.setattr(dictionary, "possible_readings", lambda surface: {"はし"})
    monkeypatch.setattr(dictionary, "best_reading", lambda surface: "はし")
    assert check("橋[みず]") == (READING_TAG,
                                 'unexpected reading (the dictionary reads "はし")')
    monkeypatch.setattr(dictionary, "best_reading", lambda surface: "")
    assert check("橋[みず]") == (READING_TAG, "unexpected reading")


# ── Correct readings: silence ─────────────────────────────────────────────────

@mecab
@pytest.mark.parametrize("expression", [
    "涼[すず]しい",
    "食[た]べる",
    "橋[はし]",
    "箸[はし]",
    "図書館[としょかん]",
    "東京[とうきょう]",
    "新聞[しんぶん]",
    "勉強[べんきょう]",
    "お 茶[ちゃ]",
    "ご 飯[はん]",
])
def test_a_correct_reading_is_not_reported(expression):
    assert check(expression) is None


@mecab
@pytest.mark.parametrize("expression", [
    "今日[きょう]",      # ... but also こんにち
    "明日[あした]",      # ... but also あす, みょうにち
    "一日[ついたち]",    # ... but also いちにち
    "大人[おとな]",
])
def test_every_one_of_several_readings_is_accepted(expression):
    """The check queries the n-best analyses, not only the likeliest one."""
    assert check(expression) is None


# ── Cases where the check cannot conclude ─────────────────────────────────────

@mecab
@pytest.mark.parametrize("expression", [
    "ズボン",        # no kanji at all
    "たべる",
    "涼しい",        # furigana absent: fill_missing is what completes those
    "",
])
def test_nothing_to_check(expression):
    assert check(expression) is None


# ── Setting the tag ───────────────────────────────────────────────────────────

@mecab
def test_the_tag_is_added_without_wiping_the_others():
    card = {"Expression": "橋[みず]", "Tags": "Noun::Objects"}
    message = tag_card(card)
    assert message
    assert card["Tags"].split() == ["Noun::Objects", READING_TAG]


@mecab
def test_the_tag_is_set_only_once():
    card = {"Expression": "橋[みず]", "Tags": READING_TAG}
    tag_card(card)
    assert card["Tags"].split().count(READING_TAG) == 1


@mecab
def test_a_correct_card_is_not_tagged():
    card = {"Expression": "涼[すず]しい", "Tags": "Adjective::い"}
    assert tag_card(card) == ""
    assert card["Tags"] == "Adjective::い"


# ── Degrading without MeCab ───────────────────────────────────────────────────

def test_without_mecab_the_check_falls_silent(monkeypatch):
    """No dictionary, no verdict: above all no false report."""
    monkeypatch.setattr(dictionary, "get_tagger", lambda: None)
    assert check("橋[みず]") is None
    card = {"Expression": "橋[みず]", "Tags": ""}
    assert tag_card(card) == ""
    assert card["Tags"] == ""


def test_without_nbest_the_check_stays_active(monkeypatch):
    """A version of fugashi with no nbest must degrade, not crash."""
    real = dictionary.get_tagger()
    if real is None:
        pytest.skip("MeCab unavailable")

    class NoNbest:
        def __call__(self, text):
            return real(text)

        def nbestToNodeList(self, text, n):
            raise AttributeError("nbest unavailable")

    monkeypatch.setattr(dictionary, "get_tagger", NoNbest)
    assert dictionary.possible_readings("涼しい") == {"すずしい"}
