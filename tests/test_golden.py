"""What the commands write, byte for byte.

Each generation runs end to end through the command line, the model answering as
in the other tests' fixtures, and its TSV and JSON Lines are compared with the
copies in `tests/golden/`: line endings as LF, and the release and the moment of
a JSON Lines header checked apart, then settled. A change meant to be seen
rewrites the copies with `UPDATE_GOLDEN=1 pytest tests/test_golden.py`.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

import kotogen
from kotogen import cli
from kotogen.generators import audio, audio_split, grammar, kanji, reading, vocab, whisper

GOLDEN = Path(__file__).resolve().parent / "golden"


class FakeClient:
    """The model, answering in turn what it is given to answer."""

    def __init__(self, *responses):
        self.responses = list(responses)

    def chat_json(self, system, user):
        return self.responses.pop(0) if self.responses else []


# ── The answers, as the fixtures of the other tests write them ────────────────

def _vocab_card(expression, translation, **extra):
    """`test_vocab.card`: every field, the ones the model left empty included."""
    return {"Expression": expression, "Translation": translation, "Context": "",
            "Notes": "", "Example": "", "ExampleTranslation": "", "Tags": "", **extra}


VOCAB = [
    _vocab_card("涼[すず]しい", "Frais",
                Notes="Pour la température, jamais pour une personne.",
                Example="今日[きょう]は 涼[すず]しいですね。",
                ExampleTranslation="Il fait frais aujourd'hui.",
                Tags="Adjective::い"),
    _vocab_card("被[かぶ]る", "Porter", Context="sur la tête",
                Example="帽子[ぼうし]を 被[かぶ]る。",
                ExampleTranslation="Porter un chapeau.",
                Tags="Verb::五段動詞"),
    _vocab_card("図書館[としょかん]", "Bibliothèque", Tags="Noun::Places"),
]

# `test_kanji.answer`.
KANJI = {"Kanji": "学", "Meaning": "étude, apprentissage",
         "Words": [{"word": "大学[だいがく]", "meaning": "université", "reading": "ガク"},
                   {"word": "学[まな]ぶ", "meaning": "apprendre", "reading": "まな.ぶ"}],
         "Composition": "⺍ + 冖 + 子 - un enfant sous un toit",
         "LookAlikes": "", "Notes": "", "Decoys": ["字", "覚", "挙"]}

# The gap sentences of `test_grammar`, as the model hands back a series of two.
GRAMMAR = [
    {"Sentence": "音楽[おんがく]を 聞[き]き{{c1::ながら}}、 勉強[べんきょう]します。",
     "Translation": "J'étudie en écoutant de la musique.", "Target": "en écoutant",
     "Hint": "聞く", "Nuance": "Deux actions en même temps.",
     "Explanation": "La forme en ます sans ます, puis ながら.", "Register": "丁寧体"},
    {"Sentence": "歩[ある]き{{c1::ながら}} 話[はな]しましょう。",
     "Translation": "Parlons en marchant.", "Target": "en marchant",
     "Hint": "歩く", "Nuance": "", "Explanation": "", "Register": "丁寧体"},
]

# `test_reading`: a question with three decoys and an open one. The file name is
# the title, counted as the first line by the translation and the key lines.
READING_TEXT = "東京で雨が降りました。\nみんな傘を使いました。\n"
READING = {"Level": "N4",
           "TranslationLines": ["La pluie", "Il a plu à Tokyo.",
                                "Tout le monde a utilisé un parapluie."],
           "Cards": [{"Question": "Où a-t-il plu ?", "Answer": "À Tokyo",
                      "Decoys": ["À Osaka", "À Kyoto", "À Hokkaido"], "KeyLine": 2},
                     {"Question": "Qu'ont-ils utilisé ?", "Answer": "Un parapluie",
                      "Decoys": [], "KeyLine": 3}]}

# `test_source_field`: a collection of three conversations, heard and split.
SEGMENTS = [
    audio_split.Segment("セクション10", 0.0, 2.0),
    audio_split.Segment("ねえ、見て。", 4.0, 9.0),
    audio_split.Segment("わー、大きい荷物だ。どこ行くの?", 9.0, 14.0),
    audio_split.Segment("明日から、友達と山に登るんだ。", 20.0, 25.0),
]
SPLIT = audio_split.Split("collection",
                          [audio_split.Block((1,), ((4.0, 9.0),)),
                           audio_split.Block((2,), ((9.0, 14.0),))], [])


def _audio_answer(*_args, **_kwargs) -> dict:
    return {"Level": "N4",
            "TranscriptLines": ["ねえ、見て。", "わー、大きい荷物だ。"],
            "TranslationLines": ["Regarde.", "Ouah, quel gros sac."],
            "Cards": [{"Question": "Qu'est-ce qui est montré ?", "Answer": "Un gros sac",
                       "Decoys": ["Une photo", "Un livre", "Une clé"], "KeyLine": 2}]}


# ── The runs ──────────────────────────────────────────────────────────────────

def _client(monkeypatch, module, *responses) -> None:
    client = FakeClient(*responses)
    monkeypatch.setattr(module, "AIClient", lambda **kwargs: client)


def _kanji(tmp_path, monkeypatch) -> list[str]:
    _client(monkeypatch, kanji, [KANJI])
    return ["kanji", "学"]


def _vocab(tmp_path, monkeypatch) -> list[str]:
    _client(monkeypatch, vocab, VOCAB)
    words = tmp_path / "words.md"
    words.write_text("# Mots\n- 涼しい\n- 被る\n- 図書館\n", encoding="utf-8")
    return ["vocab", "--file", str(words), "--jobs", "1"]


def _grammar(tmp_path, monkeypatch) -> list[str]:
    _client(monkeypatch, grammar, GRAMMAR)
    return ["grammar", "ながら", "--count", "2"]


def _reading(tmp_path, monkeypatch) -> list[str]:
    _client(monkeypatch, reading, READING)
    text = tmp_path / "pluie.txt"
    text.write_text(READING_TEXT, encoding="utf-8")
    return ["reading", str(text)]


def _audio(tmp_path, monkeypatch) -> list[str]:
    def extract(source, block, rank, out_dir, bitrate):
        path = out_dir / f"{source.stem}_{rank:02d}.mp3"
        path.write_bytes(b"")
        return path

    monkeypatch.setattr(audio, "AIClient", lambda **kwargs: object())
    monkeypatch.setattr(whisper, "_transcribe", lambda *a, **k: SEGMENTS)
    monkeypatch.setattr(audio_split, "split_audio", lambda *a, **k: SPLIT)
    monkeypatch.setattr(audio, "_extract_span", extract)
    monkeypatch.setattr(audio, "_generate_for_audio", _audio_answer)
    source = tmp_path / "collection.mp3"
    source.write_bytes(b"")
    return ["audio", str(source), "--no-video"]


RUNS = {"kanji": _kanji, "vocab": _vocab, "grammar": _grammar,
        "audio": _audio, "reading": _reading}
SUFFIXES = {"tsv": ".tsv", "json": ".jsonl"}

# The copies' JSON Lines header, in place of what changes from run to run.
SETTLED = {"kotogen": "<release>", "generated_at": "<moment>"}


def _settled(written: bytes) -> bytes:
    """A JSON Lines file with its release and its moment settled, once checked."""
    first, rest = written.split(b"\n", 1)
    header = json.loads(first)
    assert header["kotogen"] == kotogen.__version__
    assert datetime.fromisoformat(header["generated_at"]).utcoffset() is not None
    return (json.dumps(header | SETTLED, ensure_ascii=False).encode("utf-8")
            + b"\n" + rest)


@pytest.mark.parametrize("fmt", list(SUFFIXES))
@pytest.mark.parametrize("command", list(RUNS))
def test_a_run_writes_what_it_always_wrote(command, fmt, tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    argv = RUNS[command](work, monkeypatch)
    out = work / f"{command}{SUFFIXES[fmt]}"
    cli._run([*argv, "--output", str(out), "--format", fmt, "--model", "publisher/model-a"])

    written = out.read_bytes().replace(b"\r\n", b"\n")
    if fmt == "json":
        written = _settled(written)
    golden = GOLDEN / out.name
    if os.environ.get("UPDATE_GOLDEN"):
        golden.parent.mkdir(exist_ok=True)
        golden.write_bytes(written)
    assert written == golden.read_bytes().replace(b"\r\n", b"\n"), (
        f"{out.name} no longer reads as tests/golden/{out.name}")
