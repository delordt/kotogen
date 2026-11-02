"""Exporting the cards: everything the program produces goes through here.

Anki's importer forgives neither a misplaced column nor a missing directive, and
`_clean_field` is the last place a card can be damaged before it is written.
"""

import argparse
import contextlib
import re
from pathlib import Path

import pytest

from conftest import Held
from kotogen import console, exporter, keyboard, memory, menu
from kotogen.exporter import (
    Outlet,
    Taken,
    _clean_field,
    _tsv_header,
    _tsv_row,
    append_cards,
    ask_choice,
    choose,
    finish,
    print_preview,
    resolve_output_path,
    short,
)

FIELDS = ["Expression", "Translation", "Notes"]


def run_args(output=None, send=False, **extra):
    """The arguments of a generator run, as far as the file of the run cares."""
    return argparse.Namespace(output=output, send=send, **extra)


# ── Cleaning the fields ───────────────────────────────────────────────────────

def test_html_tags_are_taken_out():
    assert _clean_field("<b>Cool</b>") == "Cool"


def test_tabs_are_neutralised():
    """A tab inside a field would shift every column after it."""
    assert "\t" not in _clean_field("before\tafter")


def test_line_breaks_become_br():
    assert _clean_field("one\ntwo") == "one<br>two"


def test_the_furigana_are_normalised_at_writing_time():
    """The spacing of the groups is enforced here, at the last moment."""
    assert _clean_field("今日[きょう]は 涼[すず]しい") == "今日[きょう]は 涼[すず]しい"
    assert _clean_field("彼[かれ]は今日[きょう]") == "彼[かれ]は 今日[きょう]"


def test_the_images_field_goes_through_the_export_intact():
    """The reading card's mini-book needs its <img> tags, which other fields lose."""
    images = '<img src="reading_tadoku_ab12cd34_p001.jpg">'
    row = _tsv_row({"Images": images}, ["Images"])
    assert row.strip("\n").split("\t")[0] == images


def test_the_images_field_does_not_break_the_columns():
    """A tab or a line break there would still split a column or a card."""
    row = _tsv_row({"Images": '<img src="a.jpg">\t<img\nsrc="b.jpg">'}, ["Images"])
    assert row.count("\t") == 1  # the one tags column that follows
    assert row.count("\n") == 1


def test_the_source_field_gets_no_furigana():
    """The provenance is a trace, not a sentence: MeCab's readings and spaces
    would rewrite the episode's title."""
    title = "Nihongo con Teppei - #123 ゲスト回"
    row = _tsv_row({"Source": title}, ["Source"])
    assert row.split("\t")[0] == title


def test_the_id_gets_no_furigana():
    """An identifier comes from the media name, in kanji for a past-paper
    section: `問題` must not become ` 問題[もんだい]`."""
    row = _tsv_row({"ID": "N3_問題1_01_8b2cc9de_002"}, ["ID"])
    assert row.split("\t")[0] == "N3_問題1_01_8b2cc9de_002"


def test_the_source_field_is_still_cleaned_like_the_others():
    """Spared the furigana, not the cleaning: a tag or a tab does the same damage."""
    row = _tsv_row({"Source": "<b>papers.pdf</b>\tp. 3"}, ["Source"])
    column = row.split("\t")[0]
    assert column == "papers.pdf p. 3"


def test_the_vocabulary_context_gets_no_furigana():
    """The template shows `{{Context}}` as it stands, on the `Production` front:
    a reading added there would be printed in its brackets."""
    from kotogen.generators import vocab
    card = {"Expression": "航空機", "Context": "plus soutenu que 飛行機"}
    row = _tsv_row(card, vocab.FIELDS).split("	")
    assert row[vocab.FIELDS.index("Context")] == "plus soutenu que 飛行機"
    assert "[" in row[vocab.FIELDS.index("Expression")]


def test_the_kanji_notes_keep_the_readings_of_the_appendix():
    """The notes of a kanji card name words read as a whole, with the reading
    of the Joyo appendix: the counter rule would read 一日 as a count of days."""
    from kotogen.generators import kanji
    card = {"Kanji": "一", "Notes": " 一日[ついたち]、 一人[ひとり]"}
    row = _tsv_row(card, kanji.FIELDS).split("\t")
    assert row[kanji.FIELDS.index("Notes")] == " 一日[ついたち]、 一人[ひとり]"


@pytest.mark.parametrize("command", ["reading", "audio"])
def test_the_answer_gets_the_readings_its_decoys_get(command):
    """The card shuffles the answer in among the decoys: the one choice without
    readings would give itself away."""
    from importlib import import_module
    fields = import_module(f"kotogen.generators.{command}").FIELDS
    card = {"Answer": "駅で待ちます", "Decoy1": "駅で待ちます"}
    values = exporter.outgoing(card, fields)["fields"]
    assert values["Answer"] == values["Decoy1"]
    assert "駅[えき]" in values["Answer"]


def test_the_grammar_answer_stays_as_it_is_typed():
    """`{{type:Answer}}` compares what was typed character by character."""
    from kotogen.generators import grammar
    values = exporter.outgoing({"Answer": "降れば"}, grammar.FIELDS)["fields"]
    assert values["Answer"] == "降れば"


def test_an_absent_value_becomes_an_empty_string():
    assert _clean_field("") == ""


def test_a_tag_left_open_comes_out_as_text():
    """The tag pattern needs a closing `>`: a tag left open would be closed by
    the template's own markup, and `<img src=x onerror=...` would run."""
    out = _clean_field("a cat <img src=x onerror=alert(1) ", furigana=False)
    assert out == "a cat &lt;img src=x onerror=alert(1) "


def test_escaping_twice_changes_nothing():
    """A card read back from its file must go out again unchanged."""
    once = _clean_field('Tom & Jerry say "no" <3', furigana=False)
    assert once == "Tom &amp; Jerry say &quot;no&quot; &lt;3"
    assert _clean_field(once, furigana=False) == once


def test_a_control_character_never_lands_in_a_field():
    """An ESC from a model or a page, written as one or as an entity, would drive
    the terminal of whoever reads the TSV or the note."""
    from kotogen.exporter import safe_text

    assert safe_text("a cat\u001b[2J here\u009b") == "a cat[2J here"
    assert safe_text("a cat&#27;[2J here") == "a cat[2J here"
    assert safe_text("one\ntwo") == "one<br>two"


def test_a_line_for_the_console_drops_its_control_characters():
    assert short("a reason\u001b]0;title\u0007 given") == "a reason]0;title given"


def test_the_apostrophe_is_left_as_it_is_typed():
    """`aujourd'hui` has to stay searchable in Anki the way one types it."""
    assert _clean_field("Il fait frais aujourd'hui.") == "Il fait frais aujourd'hui."


# ── The TSV header ────────────────────────────────────────────────────────────

def test_the_import_directives():
    header = _tsv_header(FIELDS, "Japanese::Vocabulary", "Vocabulary")
    assert "#separator:tab" in header
    assert "#html:true" in header
    assert "#deck:Japanese::Vocabulary" in header
    assert "#notetype:Vocabulary" in header


def test_the_tags_column_comes_after_the_fields():
    """Anki numbers from 1: 3 fields -> the tags are in column 4."""
    assert "#tags column:4" in _tsv_header(FIELDS, "d", "n")


# ── TSV rows ──────────────────────────────────────────────────────────────────

def test_the_order_of_the_columns_with_the_tags_last():
    row = _tsv_row(
        {"Expression": "水[みず]", "Translation": "Eau", "Notes": "", "Tags": "Noun::Nature"},
        FIELDS)
    assert row.rstrip("\n").split("\t") == ["水[みず]", "Eau", "", "Noun::Nature"]


def test_a_missing_field_gives_an_empty_column():
    row = _tsv_row({"Expression": "水[みず]"}, FIELDS)
    assert row.rstrip("\n").split("\t") == ["水[みず]", "", "", ""]


def test_several_tags_are_separated_by_a_single_space():
    row = _tsv_row({"Tags": "  Noun::Nature   Level::N5  "}, FIELDS)
    assert row.rstrip("\n").split("\t")[-1] == "Noun::Nature Level::N5"


def test_a_tag_cannot_end_the_string_the_templates_read_it_in():
    """The templates read `{{Tags}}` between backquotes: a backquote, a `${`, a
    backslash or a `</script>` in a tag would be code there. The file and the
    deck carry the same tags."""
    card = {"Tags": "Level::N4 `${alert(1)}` \\u0041 </script> ``"}
    expected = ["Level::N4", "{alert(1)}", "u0041", "/script"]
    assert _tsv_row(card, FIELDS).rstrip("\n").split("\t")[-1] == " ".join(expected)
    assert exporter.outgoing(card, FIELDS)["tags"] == expected


# ── Writing as it goes ────────────────────────────────────────────────────────

def test_the_header_is_written_only_once(tmp_path):
    """The batches append as they go: a second header would break the import."""
    path = tmp_path / "out.tsv"
    append_cards(path, [{"Expression": "水[みず]"}], FIELDS, "d", "n")
    append_cards(path, [{"Expression": "火[ひ]"}], FIELDS, "d", "n")

    lines = path.read_text(encoding="utf-8").splitlines()
    assert sum(1 for line in lines if line.startswith("#separator")) == 1
    assert lines[-2].startswith("水[みず]")
    assert lines[-1].startswith("火[ひ]")


def test_an_empty_file_gets_its_header(tmp_path):
    path = tmp_path / "out.tsv"
    path.touch()
    append_cards(path, [{"Expression": "水[みず]"}], FIELDS, "d", "n")
    assert path.read_text(encoding="utf-8").startswith("#separator:tab")


def test_a_file_appended_to_then_rewritten_ends_its_lines_one_way(tmp_path):
    """Appended and rewritten alike, on every system: a line feed alone."""
    path = tmp_path / "out.tsv"
    water, fire = {"Expression": "水[みず]"}, {"Expression": "火[ひ]"}
    append_cards(path, [water, fire], FIELDS, "d", "n")
    assert b"\r\n" not in path.read_bytes()
    tagged = dict(water, Tags="Check::Reading")
    exporter.replace_rows(path, [(_tsv_row(water, FIELDS), _tsv_row(tagged, FIELDS))])
    exporter.remove_cards(path, [fire], FIELDS)
    written = path.read_bytes()
    assert b"\r\n" not in written
    assert written.decode("utf-8").splitlines()[-1].endswith("Check::Reading")


def test_a_rewrite_cut_short_leaves_the_file_as_it_was(tmp_path, monkeypatch):
    """`--output` may name a file holding an earlier run's cards: never half of it."""
    import os

    path = tmp_path / "out.tsv"
    water = {"Expression": "水[みず]"}
    append_cards(path, [water], FIELDS, "d", "n")
    before = path.read_bytes()

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", interrupted)
    with pytest.raises(KeyboardInterrupt):
        exporter.remove_cards(path, [water], FIELDS)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def _held_by_another_program(monkeypatch):
    """What Windows answers a replace while OneDrive or an indexer holds the file."""
    def busy(path, text, **kwargs):
        raise PermissionError(13, "Access is denied", str(path))

    monkeypatch.setattr(exporter.system, "write_whole", busy)


def test_a_file_held_by_another_program_is_rewritten_in_place(tmp_path, monkeypatch):
    """The close of a paid run must not die on its bookkeeping."""
    path = tmp_path / "out.tsv"
    water, fire = {"Expression": "水[みず]"}, {"Expression": "火[ひ]"}
    append_cards(path, [water, fire], FIELDS, "d", "n")
    _held_by_another_program(monkeypatch)
    exporter.remove_cards(path, [fire], FIELDS)
    written = path.read_bytes()
    assert "火".encode() not in written and "水".encode() in written
    assert b"\r\n" not in written


def test_a_file_that_cannot_be_rewritten_at_all_is_said_and_left(tmp_path, monkeypatch,
                                                                 capsys):
    path = tmp_path / "out.tsv"
    water = {"Expression": "水[みず]"}
    append_cards(path, [water], FIELDS, "d", "n")
    before = path.read_bytes()
    _held_by_another_program(monkeypatch)

    def refused(*args, **kwargs):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(exporter, "open", refused, raising=False)
    exporter.replace_rows(path, [(_tsv_row(water, FIELDS),
                                  _tsv_row(dict(water, Tags="Check::Reading"), FIELDS))])
    assert path.read_bytes() == before
    assert "out.tsv" in capsys.readouterr().err


def test_a_line_separator_in_a_field_is_a_line_break_and_not_a_new_line(tmp_path):
    """U+2028 cuts a line for `splitlines`: in a field it would split the card's
    line in two, and neither half would be found again."""
    assert exporter.safe_text("dog walk home") == "dog<br>walk<br>home"
    plain = {"Expression": "猫", "Translation": "cat"}
    odd = {"Expression": "犬", "Translation": "dog walk"}
    tsv = tmp_path / "cards.tsv"
    append_cards(tsv, [plain, odd], FIELDS, "d", "n")
    exporter.remove_cards(tsv, [odd], FIELDS)
    assert "dog" not in tsv.read_text(encoding="utf-8")
    jsonl = tmp_path / "cards.jsonl"
    append_cards(jsonl, [plain, odd], FIELDS, "d", "n")
    read = exporter.read_cards(jsonl)
    assert (len(read.cards), read.unreadable) == (2, 0)


def test_a_card_file_written_by_hand_reads_a_separator_inside_a_value(tmp_path):
    """JSON leaves U+2028 unescaped: the line is cut on line feeds alone."""
    path = tmp_path / "cards.jsonl"
    path.write_text('{"format": "kotogen", "version": 2}\n'
                    '{"fields": {"Expression": "犬", "Translation": "dog walk"}}\n',
                    encoding="utf-8")
    read = exporter.read_cards(path)
    assert (len(read.cards), read.unreadable) == (1, 0)
    assert read.cards[0]["fields"]["Translation"] == "dog walk"


def test_a_short_text_is_cut_to_screen_columns():
    """A kanji takes two columns: cut by characters, a Japanese field runs over."""
    cut = short("猫" * 50, 20)
    assert console.width(cut) <= 20 and cut.endswith("…")


# ── Choosing the output path ──────────────────────────────────────────────────

def test_the_output_option_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("KOTOGEN_OUTPUT_DIR", str(tmp_path / "ignored"))
    chosen = tmp_path / "my-own.tsv"
    assert resolve_output_path(run_args(str(chosen)), "vocab") == chosen


def test_the_configured_output_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("KOTOGEN_OUTPUT_DIR", str(tmp_path))
    path = resolve_output_path(run_args(), "vocab")
    assert path.parent == tmp_path
    assert path.name.startswith("vocab_") and path.suffix == ".tsv"


def test_the_cache_wins_over_the_configured_folder(tmp_path, monkeypatch):
    """On a direct send the TSV is only a backup: the setting, meant for files to
    import, does not pour the media onto the Desktop.
    """
    monkeypatch.setenv("KOTOGEN_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(exporter, "_cache_output_dir", lambda: tmp_path / "cache")
    assert resolve_output_path(run_args(send=True), "vocab").parent == tmp_path / "cache"


def test_the_backup_is_filed_in_the_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("KOTOGEN_OUTPUT_DIR", raising=False)
    monkeypatch.setattr(exporter, "_cache_output_dir", lambda: tmp_path / "cache")
    monkeypatch.chdir(tmp_path)
    assert resolve_output_path(run_args(send=True), "vocab").parent == tmp_path / "cache"
    assert resolve_output_path(run_args(), "vocab").parent == Path.cwd()


# ── Tidying up the runs ───────────────────────────────────────────────────────

def _run(folder: Path, name: str, when: float, media: int = 2) -> list[Path]:
    """Writes one run into the cache: its media, then its TSV, as a generation
    does. The pruning's cut-off relies on that order."""
    import os

    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for i in range(media):
        path = folder / f"{name}_{i}.mp3"
        path.write_bytes(b"x")
        os.utime(path, (when, when))
        written.append(path)
    tsv = folder / f"{name}.tsv"
    tsv.write_text("#separator:tab\n", encoding="utf-8")
    os.utime(tsv, (when + 0.5, when + 0.5))
    return written + [tsv]


def test_the_tidying_keeps_the_last_runs(tmp_path, monkeypatch):
    """The last three runs stay whole, media included."""
    cache = tmp_path / "runs"
    monkeypatch.setattr(exporter, "_cache_output_dir", lambda: cache)
    runs = [_run(cache, f"audio_{n}", 1_000 + n * 10) for n in range(5)]

    exporter._prune_runs()

    assert all(not f.exists() for run in runs[:2] for f in run)
    assert all(f.exists() for run in runs[2:] for f in run)


def test_the_tidying_spares_a_run_under_way(tmp_path, monkeypatch):
    """The media already written by the opening run are the most recent."""
    import os

    cache = tmp_path / "runs"
    monkeypatch.setattr(exporter, "_cache_output_dir", lambda: cache)
    for n in range(4):
        _run(cache, f"audio_{n}", 1_000 + n * 10)
    under_way = cache / "audio_4_0.mp3"
    under_way.write_bytes(b"x")
    os.utime(under_way, (2_000, 2_000))

    exporter._prune_runs()

    assert under_way.exists()


def test_the_tidying_touches_nothing_below_the_threshold(tmp_path, monkeypatch):
    """Three runs or fewer: the safety net is still useful in full."""
    cache = tmp_path / "runs"
    monkeypatch.setattr(exporter, "_cache_output_dir", lambda: cache)
    runs = [_run(cache, f"audio_{n}", 1_000 + n * 10) for n in range(3)]

    exporter._prune_runs()

    assert all(f.exists() for run in runs for f in run)


def test_the_tidying_with_no_cache_folder(tmp_path, monkeypatch):
    """The very first run: nothing to do, nothing to say."""
    monkeypatch.setattr(exporter, "_cache_output_dir", lambda: tmp_path / "never")
    exporter._prune_runs()


def test_the_run_that_opens_does_the_tidying(tmp_path, monkeypatch):
    """The tidying hangs off `resolve_output_path`, not off the end of a command
    that may crash before getting there."""
    cache = tmp_path / "runs"
    monkeypatch.delenv("KOTOGEN_OUTPUT_DIR", raising=False)
    monkeypatch.setattr(exporter, "_cache_output_dir", lambda: cache)
    oldest = _run(cache, "audio_0", 1_000)
    for n in range(1, 4):
        _run(cache, f"audio_{n}", 1_000 + n * 10)

    resolve_output_path(run_args(send=True), "audio")

    assert all(not f.exists() for f in oldest)


def test_the_tidying_spares_the_working_folder(tmp_path, monkeypatch):
    """With no send, the TSV goes to the user: nothing is erased there."""
    monkeypatch.delenv("KOTOGEN_OUTPUT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    runs = [_run(tmp_path, f"audio_{n}", 1_000 + n * 10) for n in range(5)]
    monkeypatch.setattr(exporter, "_cache_output_dir", lambda: tmp_path)

    resolve_output_path(run_args(), "audio")

    assert all(f.exists() for run in runs for f in run)


# ── The destinations offered ──────────────────────────────────────────────────

def test_output_dir_defaults_to_the_current_folder(monkeypatch, tmp_path):
    monkeypatch.delenv("KOTOGEN_OUTPUT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert exporter.output_dir() == Path.cwd()


def test_output_dir_follows_the_setting(monkeypatch, tmp_path):
    monkeypatch.setenv("KOTOGEN_OUTPUT_DIR", str(tmp_path / "my-own"))
    assert exporter.output_dir() == tmp_path / "my-own"


def test_output_choices_open_on_the_usual_folders(monkeypatch, tmp_path):
    """The four destinations of the setting, the current folder (the default) at
    the head and computed at call time, not frozen at import."""
    monkeypatch.setattr(exporter, "_known_folder", lambda name: tmp_path / name)
    monkeypatch.chdir(tmp_path)
    choices = exporter.output_choices()
    assert [name for name, _ in choices] == [
        "Current folder", "Desktop", "Downloads", "Documents"]
    assert choices[0][1] == Path.cwd()
    assert choices[1][1] == tmp_path / "desktop"


def test_the_desktop_is_the_one_this_system_declares(monkeypatch, tmp_path):
    """Under Linux the desktop is named in the session language (`~/Bureau` in
    French): a ~/Desktop would be a second folder beside it.
    """
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("XDG_DESKTOP_DIR", str(tmp_path / "Desktop"))
    assert exporter._known_folder("desktop") == tmp_path / "Desktop"


def test_the_english_name_is_the_last_resort(monkeypatch, tmp_path):
    """Nothing declared (a minimal Linux, macOS): the English name under ~
    exists everywhere."""
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-file"))
    monkeypatch.delenv("XDG_DESKTOP_DIR", raising=False)
    assert exporter._known_folder("desktop") == tmp_path / "Desktop"


# ── The closing block ─────────────────────────────────────────────────────────
# What the run made, said once. The cards go to the run's memory if it is an `Outlet`.

class Taking(Held, Outlet):
    """A deck that takes cards, and answers what the test tells it to."""

    def __init__(self, taken: Taken | None = None, renamed: dict | None = None):
        super().__init__()
        self.taken = taken or Taken((1, 0))
        self.renamed = renamed or {}
        self.handed: list[tuple] = []

    def take(self, cards, fields, deck, notetype, media):
        self.handed.append((list(cards), deck, notetype, list(media)))
        for card in cards:
            for name, value in card.items():
                for old, new in self.renamed.items():
                    if isinstance(value, str):
                        card[name] = value = value.replace(old, new)
        return self.taken

    def by_hand(self) -> str:
        return "the-media-folder"


def args_for(send, deck="Japanese::Vocabulary", notetype="Vocabulary"):
    return argparse.Namespace(send=send, deck=deck, notetype=notetype)


def deck_taking(monkeypatch, **kwargs) -> Taking:
    deck = Taking(**kwargs)
    monkeypatch.setattr(memory, "_known", deck)
    return deck


def test_nothing_is_handed_over_unless_asked(monkeypatch):
    deck = deck_taking(monkeypatch)
    finish([{"Expression": "水[みず]"}], FIELDS, args_for(send=False),
           Path("out.tsv"), preview=[])
    assert deck.handed == []


def test_the_cards_go_to_the_deck_of_the_run(monkeypatch, tmp_path):
    deck = deck_taking(monkeypatch)
    media = [tmp_path / "a.mp3"]
    finish([{"Expression": "水[みず]"}], FIELDS, args_for(send=True),
           Path("out.tsv"), preview=[], media=media)
    [(cards, name, notetype, handed)] = deck.handed
    assert cards == [{"Expression": "水[みず]"}]
    assert (name, notetype, handed) == ("Japanese::Vocabulary", "Vocabulary", media)


def test_duplicates_are_counted_in_the_summary(monkeypatch, capsys):
    """A refused note is a duplicate, not a failure."""
    deck_taking(monkeypatch, taken=Taken((1, 1)))
    finish([{"Expression": "水[みず]"}, {"Expression": "水[みず]"}],
           FIELDS, args_for(send=True), Path("out.tsv"), preview=[])
    out = capsys.readouterr().out
    assert '1 card in "Japanese::Vocabulary"' in out
    assert "1 duplicate ignored" in out


def test_a_successful_send_holds_on_one_line(monkeypatch, capsys):
    """The cards are in Anki: they are seen there, not in the console."""
    deck_taking(monkeypatch, taken=Taken((2, 0)))
    finish([{"Expression": "水[みず]"}, {"Expression": "火[ひ]"}], FIELDS,
           args_for(send=True), Path("out.tsv"), preview=["  1. 水", "  2. 火"])
    out = capsys.readouterr().out
    assert '2 cards in "Japanese::Vocabulary"' in out
    assert "Preview" not in out          # nothing to list
    assert "out.tsv" not in out         # the TSV is no more than a backup
    assert "Anki import" not in out


def test_a_failed_send_says_why_and_where(monkeypatch, capsys):
    """Anki's absence is only mentioned where it changes something."""
    deck_taking(monkeypatch, taken=Taken(None, "Anki was not connected"))
    finish([{"Expression": "水[みず]"}], FIELDS, args_for(send=True),
           Path("out.tsv"), preview=["  1. 水"])
    out = capsys.readouterr().out
    # The obstacle and the path on one line.
    assert "Anki was not connected: the card is in out.tsv" in out
    assert "Anki import" in out
    assert "Preview" in out


def test_a_run_with_no_deck_to_take_them_keeps_them_in_its_file(monkeypatch, capsys):
    """A program that only wants cards hands them to nothing."""
    monkeypatch.setattr(memory, "_known", Held())
    finish([{"Expression": "水[みず]"}], FIELDS, args_for(send=True),
           Path("out.tsv"), preview=[])
    assert "no deck to send them to: the card is in out.tsv" in capsys.readouterr().out


def test_with_no_send_the_block_does_not_mention_anki(monkeypatch, capsys):
    deck_taking(monkeypatch)
    finish([{"Expression": "水[みず]"}], FIELDS, args_for(send=False),
           Path("out.tsv"), preview=["  1. 水"], extras=["   3 entry(ies) ignored"])
    out = capsys.readouterr().out
    assert "connected" not in out
    assert "1 card -> out.tsv" in out
    assert "3 entry(ies) ignored" in out


def test_the_block_does_not_stack_empty_lines(monkeypatch, capsys):
    deck_taking(monkeypatch)
    finish([{"Expression": "水[みず]"}], FIELDS, args_for(send=True),
           Path("out.tsv"), preview=[])
    lines = capsys.readouterr().out.split("\n")
    assert not any(a.strip() == "" and b.strip() == ""
                   for a, b in zip(lines, lines[1:]))


def test_media_are_counted_by_folder_on_request(monkeypatch, capsys, tmp_path):
    """A mini-book runs to thirty pages: the folder is named, not thirty paths."""
    deck_taking(monkeypatch)
    pages = [tmp_path / f"p{i}.png" for i in range(9)]
    finish([{"Expression": "水[みず]"}], FIELDS, args_for(send=False), Path("out.tsv"),
           preview=[], media=pages, media_label="image", media_grouped=True)
    out = capsys.readouterr().out
    assert f"9 images in {tmp_path}" in out
    assert "p3.png" not in out


def test_media_to_copy_say_where_the_deck_keeps_them(monkeypatch, capsys, tmp_path):
    deck_taking(monkeypatch)
    finish([{"Expression": "水[みず]"}], FIELDS, args_for(send=False), Path("out.tsv"),
           preview=[], media=[tmp_path / "a.mp3"], media_label="audio")
    out = capsys.readouterr().out
    assert "to copy into the-media-folder:" in out
    assert "a.mp3" in out


def test_the_media_to_copy_are_headed_by_a_name_and_not_by_a_count(monkeypatch, capsys,
                                                                   tmp_path):
    """A Japanese noun counted carries its counter (`個のファイル`): with no
    number in front, the heading has a name of its own."""
    from kotogen import i18n

    monkeypatch.setattr(i18n, "_language", "ja")
    monkeypatch.setattr(i18n, "_catalogue", {
        "audio": "個の音声", "audios": "個の音声", "media|Audio files": "音声ファイル",
        "{label} to copy with the cards:": "カードといっしょにコピーする {label}："})
    monkeypatch.setattr(memory, "_known", Held())
    finish([{"Expression": "水[みず]"}], FIELDS, args_for(send=False), Path("out.tsv"),
           preview=[], media=[tmp_path / "a.mp3"], media_label="audio")
    out = capsys.readouterr().out
    assert "カードといっしょにコピーする 音声ファイル：" in out
    assert "個の音声" not in out


def test_media_left_out_by_the_deck_are_named(monkeypatch, capsys, tmp_path):
    left = tmp_path / "b.mp3"
    deck_taking(monkeypatch, taken=Taken((1, 0), left_out=[left]))
    finish([{"Expression": "水[みず]"}], FIELDS, args_for(send=True), Path("out.tsv"),
           preview=[], media=[tmp_path / "a.mp3", left], media_label="audio")
    out = capsys.readouterr().out
    assert "b.mp3" in out and "a.mp3" not in out


def test_the_file_already_written_follows_a_name_the_deck_kept(monkeypatch, tmp_path):
    """The row written before the send carries the old media name: it is rewritten."""
    tsv = tmp_path / "out.tsv"
    fields = ["Expression", "Audio", "Notes"]   # "Audio" carries HTML, hence the tag
    card = {"Expression": "水", "Audio": '<audio controls src="A_01.mp3"></audio>',
            "Notes": ""}
    append_cards(tsv, [card], fields, "Japanese::Vocabulary", "Vocabulary")
    deck_taking(monkeypatch, renamed={"A_01.mp3": "a_01.mp3"})
    finish([card], fields, args_for(send=True), tsv,
           preview=[], media=[tmp_path / "A_01.mp3"])
    assert 'src="a_01.mp3"' in tsv.read_text(encoding="utf-8")
    assert 'src="A_01.mp3"' not in tsv.read_text(encoding="utf-8")


# ── Dialogue and display ──────────────────────────────────────────────────────

def test_a_choice_is_read_regardless_of_case(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "  R  ")
    assert ask_choice("?", "rc") == "r"


def test_a_question_that_quotes_the_model_cannot_drive_the_terminal(monkeypatch, capsys):
    """`derive` asks "Create {word}?" with the word the model proposed."""
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert ask_choice("Create 猫\x1b[2J? [y] yes  [n] no", "yn") == "y"
    with exporter.unattended(True):
        ask_choice("Create 犬\x1b]0;owned\x07?", "yn")
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\x07" not in out and "猫[2J" in out


def test_a_choice_outside_a_dialogue_takes_the_default(monkeypatch):
    def eof(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert ask_choice("?", "rc", default="r") == "r"


def test_a_choice_with_no_default_takes_the_last_one(monkeypatch):
    """The menus put the most cautious option last."""
    def eof(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert ask_choice("?", "sg") == "g"


def test_an_invalid_answer_asks_again(monkeypatch, capsys):
    answers = iter(["x", "c"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert ask_choice("?", "rc") == "c"
    assert "expected answer" in capsys.readouterr().out


def test_the_question_is_printed_instead_of_handed_to_input(monkeypatch, capsys):
    """`input(prompt)` writes on the C stdout, cp1252 on a Windows console, which
    crashes on the Japanese a maintenance question quotes."""
    received = []
    monkeypatch.setattr("builtins.input", lambda *args: received.append(args) or "y")
    assert ask_choice("Delete 「食べる」? [y] yes  [n] no", "yn") == "y"
    assert received == [()]                   # nothing was handed to input()
    assert "食べる" in capsys.readouterr().out


def test_the_typed_return_does_not_leave_two_empty_lines(monkeypatch, capsys):
    """The terminal, not the program, writes the Return that ends the question:
    it must be counted, or the next block adds a second empty line."""
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    console.watch()
    assert ask_choice("[y] yes  [n] no", "yn") == "y"
    console.space()
    print("the next block")
    # The capture lacks the Return the terminal echoes: on screen, one empty line.
    assert capsys.readouterr().out == "   [y] yes  [n] no \nthe next block\n"


# ── A choice among several, in the middle of a command ────────────────────────

FATES = [("1", "keep card 1"), ("2", "keep card 2"), ("3", "tell apart"),
         ("4", "do nothing")]


def _pressing(monkeypatch, *pressed):
    """A terminal that reads keys, typing `pressed` one by one."""
    source = iter(pressed)
    monkeypatch.setenv("COLUMNS", "120")
    monkeypatch.setattr(menu, "raw_ready", lambda: True)
    monkeypatch.setattr(keyboard, "raw_mode", contextlib.nullcontext)
    monkeypatch.setattr(keyboard, "read_key", lambda: next(source))
    monkeypatch.setattr(keyboard, "pending", lambda timeout=0.0: timeout > 0)


def test_a_choice_is_driven_like_the_menus(monkeypatch, capsys):
    _pressing(monkeypatch, keyboard.UP, keyboard.UP, keyboard.ENTER)
    assert choose(FATES) == "2"
    chosen = re.findall(r"\033\[7m(.*?)\033\[0m", capsys.readouterr().out)[-1]
    assert chosen.startswith("›") and chosen.strip().endswith("2. keep card 2")


def test_a_key_struck_only_aims(monkeypatch):
    """A letter quits nothing: Enter alone decides, on the line in view."""
    _pressing(monkeypatch, "q", keyboard.UP, keyboard.ENTER)
    assert choose([("a", "accept"), ("s", "skip"), ("q", "quit")], start="s") == "s"


def test_a_reflex_enter_takes_the_prudent_line(monkeypatch):
    """The last option, failing a line named to open on."""
    _pressing(monkeypatch, keyboard.ENTER)
    assert choose(FATES) == "4"
    _pressing(monkeypatch, keyboard.ENTER)
    assert choose([("a", "accept"), ("s", "skip"), ("q", "quit")], start="s") == "s"


def test_outside_a_terminal_the_options_are_listed_then_typed(monkeypatch, capsys):
    monkeypatch.setattr(menu, "raw_ready", lambda: False)
    monkeypatch.setattr("builtins.input", lambda *a: "3")
    assert choose(FATES, "What to do?") == "3"
    out = capsys.readouterr().out
    assert out.startswith("   What to do?\n     1. keep card 1\n")
    assert "     4. do nothing\n   Choice? " in out


def test_outside_a_dialogue_a_choice_stops_where_ask_choice_does(monkeypatch):
    """The EOF of a script takes `default`, else the last option - not `start`,
    which only concerns a hand on Enter."""
    def eof(*a):
        raise EOFError

    monkeypatch.setattr(menu, "raw_ready", lambda: False)
    monkeypatch.setattr("builtins.input", eof)
    assert choose([("a", "accept"), ("s", "skip"), ("q", "quit")], start="s") == "q"


# ── Asking nothing: `--yes` of the commands that produce cards ────────────────
# It answers each question as a script's EOF does, and ends with its command;
# the `--yes` of maintain is another, which still asks before deleting.

def _no_hand(monkeypatch):
    """A terminal where waiting for an answer fails the test."""
    def waited(*a):
        raise AssertionError("an answer was waited for")

    monkeypatch.setattr("builtins.input", waited)
    monkeypatch.setattr(keyboard, "read_key", waited)


def test_under_yes_a_question_takes_the_answer_of_a_script(monkeypatch, capsys):
    _no_hand(monkeypatch)
    with exporter.unattended(True):
        assert ask_choice("[r] remove  [c] create anyway", "rc", default="r") == "r"
        assert ask_choice("[p] picture  [s] sound only", "ps") == "s"
    # The answer is written after the question, as if typed.
    assert capsys.readouterr().out == ("   [r] remove  [c] create anyway r\n"
                                       "   [p] picture  [s] sound only s\n")


def test_under_yes_a_choice_is_listed_never_driven(monkeypatch, capsys):
    """A terminal that reads keys gets the printed list, not the highlight."""
    _pressing(monkeypatch)
    _no_hand(monkeypatch)
    with exporter.unattended(True):
        assert choose(FATES, "What to do?") == "4"
    out = capsys.readouterr().out
    assert "\033[7m" not in out
    assert out.endswith("     4. do nothing\n   Choice? 4\n")


def test_the_yes_ends_with_its_block(monkeypatch):
    """Even left by an error: the next command of the assistant asks again."""
    with contextlib.suppress(RuntimeError), exporter.unattended(True):
        raise RuntimeError
    monkeypatch.setattr("builtins.input", lambda *a: "c")
    assert ask_choice("?", "rc", default="r") == "c"


def test_the_y_of_the_command_line_reaches_the_questions(monkeypatch):
    from kotogen import cli
    from kotogen.generators import vocab

    seen = []
    monkeypatch.setattr(vocab, "run_vocab", lambda a: seen.append(exporter._unattended))
    monkeypatch.setenv("KOTOGEN_MODEL", "publisher/model-a")
    cli._run(["vocab", "食べる", "-y"])
    cli._run(["vocab", "食べる", "--yes"])
    cli._run(["vocab", "食べる"])
    assert seen == [True, True, False]
    assert exporter._unattended is False


@pytest.mark.parametrize("argv", [["maintain", "-y"], ["ask", "anything", "-y"],
                                  ["deck", "install", "-y"], ["backup", "--restore", "-y"]])
def test_the_other_yes_keeps_its_own_meaning(argv):
    """There `--yes` confirms, and a deletion is still asked for: a script's
    answer would turn every deletion down unseen."""
    from kotogen.cli import build_parser

    args = build_parser().parse_args(argv)
    assert args.yes is not None and args.yes is not False
    assert not hasattr(args, "unattended")


def test_truncating_a_line():
    assert short("a" * 100, 10) == "a" * 9 + "…"
    assert short("short", 10) == "short"
    assert "\n" not in short("two\nlines")


def test_the_preview_is_capped_and_announces_the_rest(capsys):
    print_preview([f"line {i}" for i in range(30)], limit=5)
    out = capsys.readouterr().out
    assert "line 4" in out
    assert "line 5" not in out
    assert "and 25 more" in out
