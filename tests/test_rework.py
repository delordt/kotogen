"""`kotogen rework`: the maintenance of a file, written down and nothing else.

The model is faked. Pinned: what the command reads, asks for and writes (one line
per card, under its id), and what it leaves alone: its input file and any deck.
"""

from __future__ import annotations

import json

import pytest

from kotogen import cli, prompts, rework
from kotogen.anki import connect, deck as anki_deck
from kotogen.exporter import append_cards
from kotogen.generators import kanji, vocab


class FakeClient:
    """Answers by the card the message names; keeps the messages and instructions."""

    def __init__(self, answers: dict[str, dict]):
        self.answers = answers
        self.asked: list[tuple[str, str]] = []

    def chat_json(self, system, user):
        self.asked.append((system, user))
        for word, answer in self.answers.items():
            if word in user:
                if isinstance(answer, Exception):
                    raise answer
                return answer
        return {"changed": False, "reason": "rien"}


def _card(expression, translation, **extra):
    return {"Expression": expression, "Translation": translation, "Context": "",
            "Notes": "", "Example": "", "ExampleTranslation": "", "Tags": "", **extra}


@pytest.fixture
def cards(tmp_path):
    """A file of three vocabulary cards, as `vocab --format json` writes it."""
    path = tmp_path / "cards.jsonl"
    append_cards(path, [_card("涼[すず]しい", "Frais, agréable (temps)"),
                        _card("学生[がくせい]", "Étudiant"),
                        _card("閉[し]める", "Fermer")],
                 vocab.FIELDS, "Japanese::Vocabulary", "Vocabulary")
    return path


@pytest.fixture
def anki_untouchable(monkeypatch):
    """A rework asks Anki nothing: it works on a file."""
    def refuse(*args, **kwargs):
        pytest.fail("Anki was asked during a rework")

    monkeypatch.setattr(anki_deck, "anki", refuse)
    monkeypatch.setattr(connect, "status", refuse)


def run(monkeypatch, client, *argv):
    monkeypatch.setattr(rework, "AIClient", lambda **kwargs: client)
    cli._run(["rework", *map(str, argv), "--model", "publisher/model-a"])


def proposals(path):
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return lines[0], lines[1:]


# ── What is written ───────────────────────────────────────────────────────────

def test_each_card_gets_a_line_under_its_own_id(monkeypatch, cards, tmp_path,
                                                anki_untouchable):
    client = FakeClient({"涼[すず]しい": {
        "changed": True, "reason": "un seul sens", "fields": {"Translation": "Frais"}}})
    out = tmp_path / "proposals.jsonl"
    run(monkeypatch, client, cards, "--task", "simplify", "--output", out)
    header, lines = proposals(out)
    assert header["format"] == rework.FORMAT and header["task"] == "simplify"
    assert header["cards"] == "cards.jsonl" and header["lang"] == "fr"
    assert [line["id"] for line in lines] == [
        "vocab:涼しい:すずしい", "vocab:学生:がくせい", "vocab:閉める:しめる"]
    assert lines[0]["fields"] == {"Translation": "Frais"}
    assert lines[0]["reason"] == "un seul sens"
    assert lines[1]["fields"] == {} and lines[1]["kind"] == "vocab"


def test_the_proposals_end_their_lines_on_a_line_feed(monkeypatch, cards, tmp_path):
    """As every file of cards, whatever the system: Windows would add a carriage
    return to each line written in text mode."""
    out = tmp_path / "proposals.jsonl"
    run(monkeypatch, FakeClient({}), cards, "--task", "simplify", "--output", out)
    written = out.read_bytes()
    assert b"\n" in written and b"\r\n" not in written


def test_the_file_read_is_left_as_it_was(monkeypatch, cards, tmp_path, anki_untouchable):
    before = cards.read_bytes()
    client = FakeClient({"涼[すず]しい": {"fields": {"Translation": "Frais"}}})
    run(monkeypatch, client, cards, "--task", "simplify", "--output", tmp_path / "p.jsonl")
    assert cards.read_bytes() == before


def test_an_output_that_is_the_file_read_is_refused(monkeypatch, cards):
    before = cards.read_bytes()
    monkeypatch.setattr(rework, "AIClient",
                        lambda **kwargs: pytest.fail("a model was called"))
    with pytest.raises(SystemExit) as refused:
        cli._run(["rework", str(cards), "--task", "simplify", "--output", str(cards),
                  "--model", "publisher/model-a"])
    assert "--output" in str(refused.value)
    assert cards.read_bytes() == before


def test_proposals_already_written_are_never_overwritten(monkeypatch, cards, tmp_path):
    """They were paid for: a second run names another file rather than lose them."""
    earlier = tmp_path / "cards.simplify.jsonl"
    earlier.write_text('{"format": "kotogen-proposals"}\n', encoding="utf-8")
    monkeypatch.setattr(rework, "AIClient",
                        lambda **kwargs: pytest.fail("a model was called"))
    with pytest.raises(SystemExit) as refused:
        cli._run(["rework", str(cards), "--task", "simplify", "--model", "publisher/model-a"])
    assert "already exists" in str(refused.value)
    assert earlier.read_text(encoding="utf-8") == '{"format": "kotogen-proposals"}\n'


def test_the_proposals_go_beside_the_cards_by_default(monkeypatch, cards):
    run(monkeypatch, FakeClient({}), cards, "--task", "reading")
    assert (cards.parent / "cards.reading.jsonl").exists()


def test_reading_asks_for_the_writing_of_the_japanese(monkeypatch, cards, tmp_path):
    client = FakeClient({})
    run(monkeypatch, client, cards, "--task", "reading", "--output", tmp_path / "p.jsonl")
    assert all(user.splitlines()[0].endswith("text") for _system, user in client.asked)
    assert all("### text" in system for system, _user in client.asked)


# ── Which cards ───────────────────────────────────────────────────────────────

def test_ids_name_the_cards_worked_on(monkeypatch, cards, tmp_path, capsys):
    ids = tmp_path / "ids.txt"
    ids.write_text("# the hard ones\nvocab:閉める:しめる\n\nvocab:absent\n", encoding="utf-8")
    client = FakeClient({})
    out = tmp_path / "p.jsonl"
    run(monkeypatch, client, cards, "--task", "simplify", "--ids", ids, "--output", out)
    assert [line["id"] for line in proposals(out)[1]] == ["vocab:閉める:しめる"]
    assert len(client.asked) == 1
    assert "1 id is not in cards.jsonl: vocab:absent" in capsys.readouterr().out


def test_a_card_of_a_kind_no_task_reworks_is_left_out(monkeypatch, tmp_path, capsys):
    path = tmp_path / "kanji.jsonl"
    append_cards(path, [{"Kanji": "学", "Meaning": "étude"}], kanji.FIELDS,
                 "Japanese::Kanji", "Kanji")
    with pytest.raises(SystemExit) as exc:
        run(monkeypatch, FakeClient({}), path, "--task", "simplify")
    assert "No card of" in str(exc.value.code)
    assert "1 card of a kind no task reworks, left out" in capsys.readouterr().out


def test_a_file_of_an_unknown_version_is_refused(monkeypatch, tmp_path):
    path = tmp_path / "later.jsonl"
    path.write_text(json.dumps({"format": "kotogen", "version": 99}) + "\n",
                    encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        run(monkeypatch, FakeClient({}), path, "--task", "simplify")
    assert "version 99" in str(exc.value.code)


def test_a_file_that_holds_no_cards_of_kotogen_is_refused(monkeypatch, tmp_path):
    path = tmp_path / "other.jsonl"
    path.write_text('{"name": "something else"}\n', encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        run(monkeypatch, FakeClient({}), path, "--task", "simplify")
    assert "not a file of kotogen cards" in str(exc.value.code)


# ── The tasks that are passes of their own ────────────────────────────────────

def test_a_leech_of_several_kanji_gets_their_meaning(monkeypatch, cards, tmp_path):
    client = FakeClient({"学生[がくせい]": {
        "fields": {"Translation": "Élève", "Notes": ""},
        "kanji_help": "学 étude → apprendre<br>生 vie"}})
    out = tmp_path / "p.jsonl"
    run(monkeypatch, client, cards, "--task", "leech", "--output", out)
    line = proposals(out)[1][1]
    assert line["fields"] == {"Translation": "Élève"}    # never emptied
    assert line["kanji_help"] == "学 étude<br>生 vie"
    assert client.asked[1][0] == prompts.load("leech_simplify")


def test_derive_lists_what_a_card_calls_for_and_what_is_already_there(
        monkeypatch, cards, tmp_path):
    client = FakeClient({
        "閉[し]める": {"words": [{"word": "閉まる", "relation": "pair", "gloss": "se fermer"},
                                {"word": "涼しい", "relation": "family", "gloss": "frais"}]},
        "涼[すず]しい": {"words": [{"word": "閉まる", "relation": "family", "gloss": ""}]},
    })
    out = tmp_path / "p.jsonl"
    run(monkeypatch, client, cards, "--task", "derive", "--output", out)
    lines = {line["id"]: line for line in proposals(out)[1]}
    first, last = lines["vocab:涼しい:すずしい"], lines["vocab:閉める:しめる"]
    # 涼しい comes first in the file: 閉まる is new there, and only there.
    assert first["derive"] == [{"word": "閉まる", "relation": "family", "gloss": "",
                                "kind": "vocab"}]
    assert last["derive"] == []
    assert last["already"] == ["閉まる", "涼しい"]


# ── When the model fails ──────────────────────────────────────────────────────

def test_a_card_that_failed_says_so_on_its_line(monkeypatch, cards, tmp_path, capsys):
    client = FakeClient({"学生[がくせい]": RuntimeError("unreadable answer")})
    out = tmp_path / "p.jsonl"
    run(monkeypatch, client, cards, "--task", "simplify", "--output", out)
    lines = proposals(out)[1]
    assert lines[1] == {"id": "vocab:学生:がくせい", "kind": "vocab",
                        "error": "unreadable answer"}
    assert len(lines) == 3
    assert "1 card failed: its line says why" in capsys.readouterr().out


def test_an_ids_file_that_does_not_read_says_so_in_a_sentence(monkeypatch, cards, tmp_path):
    missing = tmp_path / "nowhere" / "ids.txt"
    with pytest.raises(SystemExit) as stop:
        run(monkeypatch, FakeClient({}), cards, "--task", "simplify", "--ids", missing)
    assert str(stop.value.code).startswith("Cannot read ")
    assert "ids.txt" in str(stop.value.code)


def test_an_output_in_a_folder_that_does_not_exist_is_refused_first(monkeypatch, cards,
                                                                    tmp_path):
    """Said before any model is called, as the file of proposals is what is paid for."""
    out = tmp_path / "missing" / "proposals.jsonl"
    monkeypatch.setattr(rework, "AIClient",
                        lambda **kwargs: pytest.fail("a model was called"))
    with pytest.raises(SystemExit) as stop:
        cli._run(["rework", str(cards), "--task", "simplify", "--output", str(out),
                  "--model", "publisher/model-a"])
    assert "does not exist" in str(stop.value.code)
