"""The text of an NHK article has to be the one its audio says.

The text is copied from the site, but the audio may stop before its end or skip
a paragraph (a cross-reference banner), and a question on a sentence never heard
cannot be answered. Listening places each sentence of the text in the sound,
matched on readings (the site writes 「きょう」 where Whisper hears 「今日」): a
tail not found goes, the rest gets its timecode.
"""

from __future__ import annotations

import argparse
import re

import pytest

from kotogen.generators import nhk, whisper
from kotogen.generators.audio_split import Segment

URL = "https://news.web.nhk/news/easy/ne1/ne1.html"
M3U8 = "https://media.vd.st.nhk/news/easy/easy_audio/ne1/index.m3u8?hdnts=token"

# The text of the site: kana wherever NHK Easy puts some.
LINES = [
    "きょうは 雨[あめ]が たくさん 降[ふ]りました。",
    "電車[でんしゃ]が 止[と]まって、 大[おお]きい 駅[えき]は 人[ひと]でいっぱいでした。",
    "あしたは 晴[は]れるでしょう。",
]

# What Whisper hears of the same sound: the same sentences, in kanji.
HEARD = [
    "今日は雨がたくさん降りました。",
    "電車が止まって、大きい駅は人でいっぱいでした。",
    "あしたは晴れるでしょう。",
]


def args_nhk(count=3):
    return argparse.Namespace(max_duration=None, audio_quality=None,
                              count=count, level="auto")


def listening(*texts) -> list[Segment]:
    """One listening: one sentence per segment, ten seconds each."""
    return [Segment(text, i * 10.0, i * 10.0 + 9.0, ())
            for i, text in enumerate(texts)]


class _AI:
    """A model that returns a card and remembers what it was given."""

    def __init__(self) -> None:
        self.seen = ""

    def chat_json(self, system, user):
        self.seen = user
        lines = [l for l in user.splitlines() if re.match(r"^\d+\. ", l)]
        return {
            "TranslationLines": [f"Ligne {i}." for i in range(1, len(lines) + 1)],
            "Cards": [{"Question": "Que s'est-il passé ?", "Answer": "Il a plu",
                       "Decoys": ["Il a neigé", "Il a gelé", "Il a venté"],
                       "KeyLine": 1}],
        }


class _NoAI:
    def chat_json(self, *a, **k):
        pytest.fail("no AI call should be paid for a dropped article")


def _pipeline(monkeypatch, tmp_path, segments, lines=None, client=None):
    """Sets up the pipeline of an article, the listening being the given one."""
    monkeypatch.setattr(nhk, "fetch_article",
                        lambda *a, **k: ("Title", list(lines or LINES), None, "", M3U8))
    monkeypatch.setattr(nhk, "probe_duration", lambda src: 30.0)

    def _write(url, out_dir, stem, level):
        path = out_dir / f"{stem}.mp3"
        path.write_bytes(b"\0" * 2048)
        return path

    monkeypatch.setattr(nhk, "transcode_url", _write)
    monkeypatch.setattr(nhk, "_listen", lambda *a, **k: segments)
    remembered: list[str] = []
    monkeypatch.setattr(nhk, "mark_seen",
                        lambda url, title="", **k: remembered.append(url))
    return client or _AI(), remembered


# -- The tail the audio does not say ------------------------------------------

def test_the_audio_stops_before_the_end_of_the_text(monkeypatch, tmp_path):
    """The voice file only reads the first two sentences: the third enters
    neither the AI call nor the transcript of the card."""
    client, _ = _pipeline(monkeypatch, tmp_path, listening(*HEARD[:2]))

    cards, _ = nhk.generate_for_url(URL, args_nhk(), client, tmp_path)

    assert "あしたは" not in client.seen          # never paid for
    assert "(2 lignes)" in client.seen
    assert cards
    assert "あしたは" not in cards[0]["Transcript"]
    assert cards[0]["Transcript"].count("\n") == 1


def test_the_spoken_lines_keep_their_timecode(monkeypatch, tmp_path):
    client, _ = _pipeline(monkeypatch, tmp_path, listening(*HEARD[:2]))

    cards, _ = nhk.generate_for_url(URL, args_nhk(), client, tmp_path)

    assert cards[0]["Timecodes"] == "0.00 10.00"


def test_a_gap_in_the_middle_removes_nothing(monkeypatch, tmp_path):
    """A lone sentence not found is a misheard word, not an audio that stops: the
    text stays whole, and the line gets an instant between its neighbours."""
    heard = [HEARD[0], "まったく違う文です。", HEARD[2]]
    client, _ = _pipeline(monkeypatch, tmp_path, listening(*heard))

    cards, _ = nhk.generate_for_url(URL, args_nhk(), client, tmp_path)

    assert "あしたは" in client.seen
    assert cards[0]["Transcript"].count("\n") == 2
    instants = [float(m) for m in cards[0]["Timecodes"].split()]
    assert instants[0] == 0.0 and instants[2] == 20.0
    assert instants[0] < instants[1] < instants[2]


def test_a_reading_cut_another_way_cuts_nothing(monkeypatch, tmp_path):
    """The last line is missed because the analyser reads 「明日」 あす where the
    site writes あした. The sound still speaks, so nothing is removed: the line
    takes its place after the previous one, in the time left."""
    heard = [*HEARD[:2], "明日は晴れるでしょう。"]
    client, _ = _pipeline(monkeypatch, tmp_path, listening(*heard))

    cards, _ = nhk.generate_for_url(URL, args_nhk(), client, tmp_path)

    assert "あしたは" in client.seen
    assert cards[0]["Transcript"].count("\n") == 2
    instants = [float(m) for m in cards[0]["Timecodes"].split()]
    assert instants[:2] == [0.0, 10.0]
    assert instants[2] > 10.0


# -- The audio that does not go with the text ---------------------------------

def test_an_audio_foreign_to_the_text_gives_neither_card_nor_ai(monkeypatch, tmp_path):
    """Not one sentence found means another audio, not a short one: no card, no
    AI call, no MP3 left behind, and the article is not remembered as done."""
    client, remembered = _pipeline(monkeypatch, tmp_path,
                                   listening("これは全然別のニュースです。"),
                                   client=_NoAI())

    with pytest.raises(RuntimeError, match="do not go together"):
        nhk.generate_for_url(URL, args_nhk(), client, tmp_path)

    assert list(tmp_path.iterdir()) == []
    assert remembered == []


class _FailingAI:
    def chat_json(self, *a, **k):
        raise ValueError("The AI did not return valid JSON.")


class _EmptyAI:
    def chat_json(self, *a, **k):
        return {"TranslationLines": [], "Cards": []}


@pytest.mark.parametrize("client", [_FailingAI(), _EmptyAI()])
def test_an_article_with_no_card_leaves_no_audio_behind(monkeypatch, tmp_path, client):
    """A failed call or an answer with no card: nothing points at the MP3, which
    would otherwise sit unused in the output folder, then in Anki's media."""
    _ai, remembered = _pipeline(monkeypatch, tmp_path, listening(*HEARD), client=client)

    try:
        cards, _ = nhk.generate_for_url(URL, args_nhk(), client, tmp_path)
    except ValueError:
        cards = []

    assert cards == []
    assert list(tmp_path.glob("*.mp3")) == []
    assert remembered == []


# -- With no listening --------------------------------------------------------

def test_with_no_listening_the_whole_text_goes_through(monkeypatch, tmp_path):
    """Whisper missing (the NHK mode does not install it): the article keeps all
    its text, and only its lines are not clickable."""
    client, _ = _pipeline(monkeypatch, tmp_path, [])

    cards, _ = nhk.generate_for_url(URL, args_nhk(), client, tmp_path)

    assert "あしたは" in client.seen
    assert cards[0]["Timecodes"] == ""
    assert cards[0]["Transcript"].count("\n") == 2


def test_whisper_missing_does_not_fail_the_article(monkeypatch, tmp_path):
    """Without the package `_listen` says so and returns an empty list, where the
    audio mode, which requires Whisper, raises."""
    monkeypatch.setattr(nhk.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(whisper, "_transcribe",
                        lambda *a, **k: pytest.fail("Whisper called without Whisper"))

    assert nhk._listen(tmp_path / "audio.mp3") == []


def test_an_impossible_listening_lets_the_article_through(monkeypatch, tmp_path):
    """A failed transcription costs only the cross-check, and is said."""
    monkeypatch.setattr(nhk.importlib.util, "find_spec", lambda name: object())

    def _breaks(*a, **k):
        raise RuntimeError("unreadable model")

    monkeypatch.setattr(whisper, "_transcribe", _breaks)

    assert nhk._listen(tmp_path / "audio.mp3") == []
