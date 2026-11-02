"""Writing the cards as JSON Lines: the file for tools other than Anki.

It has to say what the TSV says, card for card, and the command line has to
keep it away from Anki: a JSON file is not something to send.
"""

import argparse
import json
from datetime import datetime

import pytest

import kotogen
from kotogen import cli, exporter, prefs, prompts
from kotogen.ai_client import AIClient
from kotogen.anki import connect, media
from kotogen.exporter import (
    NotCards,
    _tsv_row,
    append_cards,
    finish,
    read_cards,
    resolve_output_path,
)
from kotogen.generators import audio, vocab

FIELDS = ["Expression", "Translation", "Notes"]


def read(path):
    """The header line of a JSON Lines file, then its cards."""
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return lines[0], lines[1:]


def args_for(send=False):
    return argparse.Namespace(send=send, deck="Japanese::Vocabulary", notetype="Vocabulary")


# ── The file ──────────────────────────────────────────────────────────────────

def test_a_header_line_then_one_line_per_card(tmp_path):
    path = tmp_path / "out.jsonl"
    append_cards(path, [{"Expression": "水[みず]"}], FIELDS, "Japanese::Vocabulary", "Vocabulary")
    append_cards(path, [{"Expression": "火[ひ]"}], FIELDS, "Japanese::Vocabulary", "Vocabulary")

    header, cards = read(path)
    assert {key: header[key] for key in ("format", "version", "deck", "notetype")} == {
        "format": "kotogen", "version": exporter.JSON_VERSION,
        "deck": "Japanese::Vocabulary", "notetype": "Vocabulary"}
    assert [c["fields"]["Expression"] for c in cards] == ["水[みず]", "火[ひ]"]


def test_the_first_line_says_the_fields_and_what_wrote_them(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    AIClient(provider="openrouter", model="model/test")
    path = tmp_path / "out.jsonl"
    append_cards(path, [{"Expression": "水[みず]"}], FIELDS, "d", "n")

    header = read(path)[0]
    assert header["fields"] == FIELDS
    assert header["lang"] == prompts.language()
    assert header["kotogen"] == kotogen.__version__
    assert header["model"] == "model/test"
    assert datetime.fromisoformat(header["generated_at"]).utcoffset() is not None


def test_each_card_says_its_kind_and_the_files_it_plays(tmp_path):
    listening = {"Audio": exporter.audio_ref("A_01.mp3"),
                 "Image": exporter.image_ref("A_01_fig.png"),
                 "Transcript": 'src="not_a_file.mp3"'}
    path = tmp_path / "audio.jsonl"
    append_cards(path, [listening], audio.FIELDS, "d", "Listening")
    [line] = read(path)[1]
    assert line["kind"] == "audio"
    assert line["media"] == ["A_01.mp3", "A_01_fig.png"]

    path = tmp_path / "vocab.jsonl"
    append_cards(path, [{"Expression": "水[みず]"}], vocab.FIELDS, "d", "Vocabulary")
    [line] = read(path)[1]
    assert (line["kind"], line["media"]) == ("vocab", [])


def test_a_file_already_begun_keeps_its_first_line(tmp_path):
    """The first line is written by the run that opens the file: one of version 1
    stays one, its new cards saying more than it promises."""
    path = tmp_path / "out.jsonl"
    first = json.dumps({"format": "kotogen", "version": 1, "deck": "d", "notetype": "n"})
    path.write_text(first + "\n", encoding="utf-8")
    append_cards(path, [{"Expression": "水[みず]"}], vocab.FIELDS, "d", "n")
    assert path.read_text(encoding="utf-8").splitlines()[0] == first
    assert read(path)[1][0]["kind"] == "vocab"


def test_the_fields_come_in_the_order_of_the_note_type(tmp_path):
    path = tmp_path / "out.jsonl"
    append_cards(path, [{"Notes": "n", "Expression": "水[みず]"}], FIELDS, "d", "n")
    assert list(read(path)[1][0]["fields"]) == FIELDS


def test_the_values_are_those_of_the_tsv(tmp_path):
    """Same cleaning and furigana as the TSV; only the escaping differs."""
    card = {"Expression": "彼[かれ]は今日[きょう]", "Translation": "<b>un</b>\ndeux",
            "Tags": "  Noun::Nature   Level::N5 "}
    path = tmp_path / "out.jsonl"
    append_cards(path, [card], FIELDS, "d", "n")

    written = read(path)[1][0]
    columns = _tsv_row(card, FIELDS).rstrip("\n").split("\t")
    assert list(written["fields"].values()) == columns[:-1]
    assert written["fields"]["Translation"] == "un<br>deux"
    assert written["tags"] == ["Noun::Nature", "Level::N5"]


def test_a_media_field_keeps_its_tag(tmp_path):
    audio = exporter.audio_ref("A_01.mp3")
    path = tmp_path / "out.jsonl"
    append_cards(path, [{"Audio": audio}], ["Audio"], "d", "n")
    assert read(path)[1][0]["fields"]["Audio"] == audio


def test_japanese_is_written_as_it_reads(tmp_path):
    """Not as \\u escapes: the file is also opened by people."""
    path = tmp_path / "out.jsonl"
    append_cards(path, [{"Expression": "水"}], FIELDS, "Japanese::語彙", "n")
    content = path.read_text(encoding="utf-8")
    assert "水" in content and "語彙" in content


def test_the_name_says_the_format():
    assert exporter.is_json("cards.jsonl")
    assert exporter.is_json("CARDS.JSONL")
    assert not exporter.is_json("cards.tsv")
    assert not exporter.is_json("cards.json")


def test_a_json_run_gets_a_jsonl_name(tmp_path, monkeypatch):
    monkeypatch.setenv("KOTOGEN_OUTPUT_DIR", str(tmp_path))
    args = argparse.Namespace(output=None, send=False, format="json")
    path = resolve_output_path(args, "vocab")
    assert path.parent == tmp_path
    assert path.name.startswith("vocab_") and path.suffix == ".jsonl"


# ── Reading it back ───────────────────────────────────────────────────────────

def test_a_file_written_is_read_back_card_for_card(tmp_path):
    path = tmp_path / "out.jsonl"
    append_cards(path, [{"Expression": "水[みず]", "Tags": "Level::N5"}], vocab.FIELDS,
                 "d", "Vocabulary")
    read_back = read_cards(path)
    assert read_back.header["version"] == exporter.JSON_VERSION
    [card] = read_back.cards
    assert card["id"] == "vocab:水:みず" and card["kind"] == "vocab"
    assert card["fields"]["Expression"] == "水[みず]" and card["tags"] == ["Level::N5"]


def test_a_key_the_reader_does_not_know_is_passed_over(tmp_path):
    path = tmp_path / "later.jsonl"
    path.write_text("\n".join([
        json.dumps({"format": "kotogen", "version": 2, "notetype": "n", "colour": "red"}),
        json.dumps({"id": "x", "kind": "vocab", "fields": {"Expression": "水"},
                    "tags": [], "media": [], "weight": 3}),
    ]) + "\n", encoding="utf-8")
    [card] = read_cards(path).cards
    assert card == {"id": "x", "kind": "vocab", "fields": {"Expression": "水"}, "tags": []}


def test_a_version_the_reader_does_not_know_is_refused(tmp_path):
    path = tmp_path / "later.jsonl"
    path.write_text(json.dumps({"format": "kotogen", "version": 3}) + "\n",
                    encoding="utf-8")
    with pytest.raises(NotCards, match="version 3"):
        read_cards(path)


# ── The closing block ─────────────────────────────────────────────────────────

def test_a_json_file_is_not_offered_to_anki(monkeypatch, capsys, tmp_path):
    """Neither the import nor the media library has anything to do with it,
    and its media are already beside it."""
    def boom(*a, **k):
        pytest.fail("AnkiConnect should not have been called")

    monkeypatch.setattr(connect, "status", boom)
    monkeypatch.setattr(media, "media_dir_hint", boom)
    out = tmp_path / "out.jsonl"
    finish([{"Expression": "水[みず]"}], FIELDS, args_for(), out,
           preview=[], media=[tmp_path / "a.mp3"], media_label="audio")
    printed = capsys.readouterr().out
    assert f"1 card -> {out}" in printed
    assert "Anki import" not in printed
    assert "a.mp3" not in printed


# ── The command line ──────────────────────────────────────────────────────────

@pytest.fixture
def run(monkeypatch):
    """Runs `vocab` through the command line, and hands back the arguments the
    generator received."""
    from kotogen.generators import vocab

    got = {}
    monkeypatch.setattr(prefs, "_auto_send", False)
    monkeypatch.setattr(vocab, "run_vocab", lambda a: got.update(vars(a)))
    # A command that needs the model stops without one, before any work.
    monkeypatch.setenv("KOTOGEN_MODEL", "publisher/model-a")

    def go(*argv):
        got.clear()
        cli._run(["vocab", "食べる", *argv])
        return got
    return go


def test_tsv_is_the_default(run, monkeypatch):
    monkeypatch.delenv("KOTOGEN_FORMAT", raising=False)
    assert run()["format"] == "tsv"


def test_the_setting_chooses_json(run, monkeypatch):
    monkeypatch.setenv("KOTOGEN_FORMAT", "json")
    assert run()["format"] == "json"
    assert run("--format", "tsv")["format"] == "tsv"


def test_an_unknown_setting_falls_back_on_tsv(run, monkeypatch):
    monkeypatch.setenv("KOTOGEN_FORMAT", "xml")
    assert run()["format"] == "tsv"


def test_json_sends_nothing_even_with_auto_send(run, monkeypatch):
    monkeypatch.setattr(prefs, "_auto_send", True)
    got = run("--format", "json")
    assert got["send"] is False


def test_json_and_send_are_refused_together(run):
    with pytest.raises(SystemExit) as exc:
        run("--format", "json", "--send")
    assert "--send" in str(exc.value.code)


def test_the_name_given_decides(run, monkeypatch, tmp_path):
    monkeypatch.setenv("KOTOGEN_FORMAT", "json")
    assert run("--output", str(tmp_path / "a.jsonl"))["format"] == "json"
    assert run("--output", str(tmp_path / "a.tsv"))["format"] == "tsv"


def test_a_format_that_contradicts_the_name_is_refused(run, tmp_path):
    with pytest.raises(SystemExit) as exc:
        run("--format", "tsv", "--output", str(tmp_path / "a.jsonl"))
    assert "a.jsonl" in str(exc.value.code)


def test_a_file_of_a_later_layout_is_not_added_to(run, tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_text(json.dumps({"format": "kotogen", "version": 3}) + "\n",
                    encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        run("--output", str(path))
    assert "version 3" in str(exc.value.code)


def test_a_file_of_another_tool_is_not_added_to(run, tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_text('{"name": "something else"}\n', encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        run("--output", str(path))
    assert "not a file of kotogen cards" in str(exc.value.code)


def test_a_file_of_the_first_layout_is_added_to(run, tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_text(json.dumps({"format": "kotogen", "version": 1, "deck": "d",
                                "notetype": "Vocabulary"}) + "\n", encoding="utf-8")
    assert run("--output", str(path))["format"] == "json"


def test_the_file_named_is_the_memory_of_a_json_run(run, tmp_path):
    from kotogen import memory
    from kotogen.anki import deck as anki_deck

    run("--output", str(tmp_path / "a.jsonl"))
    assert memory.known().name("Japanese") == "a.jsonl"
    run("--output", str(tmp_path / "a.tsv"))
    assert memory.known() is anki_deck.DECK
