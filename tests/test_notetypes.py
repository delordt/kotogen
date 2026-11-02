"""Installing the note types from templates/ (`kotogen deck install`).

Creating what is missing destroys nothing, rewriting what exists overwrites HTML
that may have been touched up in Anki, and removing a field would empty it on
every note: the tests mostly check what the command does not do.
"""

from __future__ import annotations

import argparse

import pytest

from kotogen import choices, settings
from kotogen.anki import installed, notetypes, templates as card_templates

# -- A minimal templates/ tree, and an Anki in memory --------------------------

@pytest.fixture
def root(tmp_path):
    """templates/ tree cut down to what the specs read."""
    for spec in notetypes.SPECS:
        # all_cards and not cards: the folder carries the whole repository,
        # including what a passing .env would drop.
        for _name, sub in spec.all_cards:
            base = tmp_path / spec.directory
            folder = base / sub if sub else base
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "front.html").write_text(f"front {spec.directory}{sub}", encoding="utf-8")
            (folder / "back.html").write_text(f"back {spec.directory}{sub}", encoding="utf-8")
            (folder / "style.css").write_text(f"css {spec.directory}", encoding="utf-8")
    return tmp_path


class FakeAnki:
    """AnkiConnect in memory: remembers the write actions it received.

    Each type gets an ID by its rank, and `createModel` answers with the new
    type's ID, which the record of what kotogen wrote is filed under.
    """

    def __init__(self, models=None, templates=None, css=None, fields=None):
        self.models = list(models or [])
        self.templates = templates or {}
        self.css = css or {}
        self.fields = fields or {}
        self.writes: list[tuple[str, dict]] = []

    def __call__(self, action, **params):
        if action == "getActiveProfile":
            return "User 1"
        if action == "modelNames":
            return self.models
        if action == "modelNamesAndIds":
            return {name: 1000 + rank for rank, name in enumerate(self.models)}
        if action == "createModel":
            self.writes.append((action, params))
            return {"id": 9000 + len(self.writes), "name": params["modelName"]}
        if action == "modelTemplates":
            return self.templates.get(params["modelName"], {})
        if action == "modelStyling":
            return {"css": self.css.get(params["modelName"], "")}
        if action == "modelFieldNames":
            return self.fields.get(params["modelName"], [])
        self.writes.append((action, params))
        return None

    def did(self, action):
        return [p for a, p in self.writes if a == action]


@pytest.fixture
def anki(monkeypatch):
    fake = FakeAnki()
    monkeypatch.setattr(notetypes, "anki", fake)
    return fake


SPEC = {spec.command: spec for spec in notetypes.SPECS}
VOCAB = SPEC["vocab"]


def test_the_env_of_the_machine_does_not_choose_the_cards():
    """What is checked is the repository, not the developer's deck: an `.env` with
    `KOTOGEN_VOCAB_CARDS=Recognition`, loaded into `os.environ` by another test,
    would fail half this file. The guard is in `conftest.py`.
    """
    assert [name for name, _sub in VOCAB.cards] == ["Recognition", "Production"]


# -- Reading the templates -----------------------------------------------------

def test_missing_templates_say_where_they_were_looked_for(monkeypatch, tmp_path):
    """The folder is read in the sources, whatever the current directory: the
    message names that place, and how kotogen is meant to be installed."""
    monkeypatch.setattr(settings, "ROOT", tmp_path)
    with pytest.raises(FileNotFoundError) as raised:
        notetypes.export_templates(tmp_path / "out")
    assert str(tmp_path) in str(raised.value)
    assert "pip install -e ." in str(raised.value)


def test_vocab_has_two_cards_and_one_stylesheet(root):
    templates, css = notetypes.read_templates(VOCAB, root)
    assert list(templates) == ["Recognition", "Production"]
    assert templates["Recognition"]["Front"] == "front vocabrecognition"
    assert css == "css vocab"  # Anki has only one CSS per note type


def test_a_missing_template_file_is_not_silently_skipped(root):
    (root / "grammar" / "back.html").unlink()
    with pytest.raises(FileNotFoundError):
        notetypes.read_templates(SPEC["grammar"], root)


def test_fields_come_from_the_generator(root):
    """The fields are the ones the exporter writes, not those guessed from HTML."""
    from kotogen.generators.vocab import FIELDS

    assert VOCAB.fields == FIELDS


# -- Writing on disk (the path without Anki) -----------------------------------

def test_the_export_lays_out_what_anki_shows(root, monkeypatch, tmp_path):
    """The names Anki shows, since one comes here with Anki open; a lone card
    takes no subfolder, which would add a click to every trip to the editor."""
    monkeypatch.setattr(notetypes, "templates_root", lambda *a, **k: root)
    monkeypatch.setenv("KOTOGEN_VOCAB_CARDS", "Recognition,Production")
    dest = tmp_path / "output"
    written = notetypes.export_templates(dest, only={"vocab", "grammar"})

    laid = {path.relative_to(dest).as_posix() for path in written}
    assert laid == {
        "README.txt",
        "Vocabulary/fields.txt", "Vocabulary/style.css",
        "Vocabulary/Recognition/front.html", "Vocabulary/Recognition/back.html",
        "Vocabulary/Production/front.html", "Vocabulary/Production/back.html",
        "Grammar/fields.txt", "Grammar/style.css",
        "Grammar/front.html", "Grammar/back.html",
    }
    fields = (dest / "Vocabulary" / "fields.txt").read_text(encoding="utf-8")
    assert fields.splitlines() == VOCAB.fields


def test_the_export_writes_the_rendering_not_the_repository(root, monkeypatch, tmp_path):
    """The file minus what this profile takes out of it, or the blocks would have
    to be trimmed by hand before pasting."""
    from kotogen.anki import templates as card_templates

    (root / "grammar" / "front.html").write_text(
        "kept\n<!-- kotogen:register -->cut<!-- /kotogen:register -->\n",
        encoding="utf-8")
    monkeypatch.setattr(notetypes, "templates_root", lambda *a, **k: root)
    monkeypatch.setattr(choices, "file", lambda: tmp_path / choices.FILE)
    card_templates.set_one("grammar.register", "no")

    dest = tmp_path / "output"
    notetypes.export_templates(dest, only={"grammar"})
    front = (dest / "Grammar" / "front.html").read_text(encoding="utf-8")
    assert "kept" in front and "cut" not in front


def test_the_export_says_the_three_things_a_paste_cannot_carry(root, monkeypatch, tmp_path):
    """The name of the type, its kind, and where each file goes in Anki."""
    monkeypatch.setattr(notetypes, "templates_root", lambda *a, **k: root)
    dest = tmp_path / "output"
    notetypes.export_templates(dest, only={"grammar", "reading"})

    said = (dest / "README.txt").read_text(encoding="utf-8")
    assert "Grammar  (Cloze, " in said
    assert "Reading  (Basic, " in said
    assert "front.html  -> Front Template" in said


def test_a_missing_template_leaves_nothing_behind(root, monkeypatch, tmp_path):
    """Nothing written rather than a half-filled folder, in which the real back
    could not be told apart."""
    (root / "reading" / "back.html").unlink()
    monkeypatch.setattr(notetypes, "templates_root", lambda *a, **k: root)
    dest = tmp_path / "output"
    with pytest.raises(FileNotFoundError):
        notetypes.export_templates(dest)
    assert not dest.exists()


def test_a_skipped_notetype_is_not_exported(root, monkeypatch, tmp_path):
    """What KOTOGEN_SKIP drops is installed nowhere, disk included."""
    monkeypatch.setattr(notetypes, "templates_root", lambda *a, **k: root)
    monkeypatch.setenv("KOTOGEN_SKIP", "grammar")
    dest = tmp_path / "output"
    notetypes.export_templates(dest)
    assert not (dest / "Grammar").exists()
    assert (dest / "Reading").exists()


# -- Creation ------------------------------------------------------------------

def test_absent_notetype_is_created_with_its_fields(root, anki):
    plan = notetypes.plan_for(VOCAB, root)
    assert not plan.exists and plan.differs
    notetypes.create(plan)

    (params,) = anki.did("createModel")
    assert params["modelName"] == "Vocabulary"
    assert params["inOrderFields"][0] == "Expression"
    assert [c["Name"] for c in params["cardTemplates"]] == ["Recognition", "Production"]
    assert params["isCloze"] is False


def test_grammar_is_created_as_a_cloze_notetype(root, anki):
    """The {{c1::...}} gap of the `Sentence` is what makes the card: without
    isCloze, the note type created would be unusable."""
    plan = notetypes.plan_for(SPEC["grammar"], root)
    notetypes.create(plan)
    assert anki.did("createModel")[0]["isCloze"] is True


# -- Update --------------------------------------------------------------------

def _existing(**kwargs):
    """An Anki where "Vocabulary" already exists, matching the repository."""
    return FakeAnki(
        models=["Vocabulary"],
        templates={"Vocabulary": {
            "Recognition": {"Front": "front vocabrecognition", "Back": "back vocabrecognition"},
            "Production": {"Front": "front vocabproduction", "Back": "back vocabproduction"},
        }},
        css={"Vocabulary": "css vocab"},
        fields={"Vocabulary": list(VOCAB.fields)},
        **kwargs,
    )


def test_identical_notetype_needs_no_write(root, monkeypatch):
    fake = _existing()
    monkeypatch.setattr(notetypes, "anki", fake)
    plan = notetypes.plan_for(VOCAB, root)
    assert plan.exists and not plan.differs  # nothing to ask, nothing to write


def _outdated(plan) -> list[str]:
    """The cards of which at least one face differs, each once."""
    return list(dict.fromkeys(change.card for change in plan.changes if change.card))


def test_anki_side_is_read_under_front_and_back(root, monkeypatch):
    """`modelTemplates` answers with "Front"/"Back": read under other keys, the
    cards would come out empty and always differ from the repository."""
    fake = _existing()
    fake.templates["Vocabulary"]["Recognition"] = {
        "qfmt": "front vocabrecognition",   # keys of Anki's internal schema,
        "afmt": "back vocabrecognition",    # which this action does NOT give back
    }
    monkeypatch.setattr(notetypes, "anki", fake)
    assert _outdated(notetypes.plan_for(VOCAB, root)) == ["Recognition"]


def test_crlf_alone_is_not_a_difference(root, monkeypatch):
    """A template saved under Windows does not have to rewrite the whole type."""
    fake = _existing()
    card = fake.templates["Vocabulary"]["Recognition"]
    card["Front"] = "front vocabrecognition\r\n"
    fake.css["Vocabulary"] = "css vocab\r\n"
    monkeypatch.setattr(notetypes, "anki", fake)

    plan = notetypes.plan_for(VOCAB, root)
    assert not plan.changes


def test_each_face_is_its_own_difference(root, monkeypatch):
    """Front, back and CSS are repaired separately: they have to be told apart."""
    fake = _existing()
    fake.templates["Vocabulary"]["Recognition"]["Back"] = "old back"
    fake.css["Vocabulary"] = "old css"
    monkeypatch.setattr(notetypes, "anki", fake)

    plan = notetypes.plan_for(VOCAB, root)
    assert [(c.card, c.face) for c in plan.changes] == [
        ("Recognition", notetypes.BACK), ("", notetypes.CSS)]


def test_a_refused_face_keeps_what_anki_holds(root, monkeypatch):
    """`updateModelTemplates` writes the whole card: accepting the back must not
    take away the front just refused."""
    fake = _existing()
    card = fake.templates["Vocabulary"]["Recognition"]
    card["Front"] = "my front touched up in Anki"
    card["Back"] = "old back"
    monkeypatch.setattr(notetypes, "anki", fake)

    plan = notetypes.plan_for(VOCAB, root)
    backs = [c for c in plan.changes if c.face == notetypes.BACK]
    notetypes.update(plan, changes=backs)

    (params,) = fake.did("updateModelTemplates")
    written = params["model"]["templates"]["Recognition"]
    assert written["Back"] == "back vocabrecognition"           # the repository won
    assert written["Front"] == "my front touched up in Anki"  # the refusal holds


def test_a_one_line_change_is_counted_as_one_line(root, monkeypatch):
    fake = _existing()
    fake.templates["Vocabulary"]["Recognition"]["Front"] = "front touched up"
    monkeypatch.setattr(notetypes, "anki", fake)

    plan = notetypes.plan_for(VOCAB, root)
    assert notetypes.summary(plan.changes) == "1 line on the front"


def test_each_piece_says_its_own_size(root, monkeypatch):
    """One line for the whole type, but a count per piece: one total would not
    tell a line of CSS from the whole back. Only the first term has the unit."""
    fake = _existing()
    fake.templates["Vocabulary"]["Recognition"]["Back"] = "old back\non two lines"
    fake.css["Vocabulary"] = "old css"
    monkeypatch.setattr(notetypes, "anki", fake)

    plan = notetypes.plan_for(VOCAB, root)
    assert notetypes.summary(plan.changes) == "2 lines on the back, 1 in the CSS"


def test_the_card_is_named_only_when_several_differ(root, monkeypatch):
    """"on the back" is enough while one card is touched; otherwise say which."""
    fake = _existing()
    fake.templates["Vocabulary"]["Recognition"]["Back"] = "old back"
    monkeypatch.setattr(notetypes, "anki", fake)
    assert notetypes.summary(notetypes.plan_for(VOCAB, root).changes) == "1 line on the back"

    fake.templates["Vocabulary"]["Production"]["Back"] = "old back too"
    assert notetypes.summary(notetypes.plan_for(VOCAB, root).changes) == (
        '1 line on the back of "Recognition", 1 on the back of "Production"')


def test_changed_html_is_detected_and_rewritten(root, monkeypatch):
    fake = _existing()
    fake.templates["Vocabulary"]["Recognition"]["Front"] = "old front"
    monkeypatch.setattr(notetypes, "anki", fake)

    plan = notetypes.plan_for(VOCAB, root)
    assert _outdated(plan) == ["Recognition"]
    notetypes.update(plan)
    (params,) = fake.did("updateModelTemplates")
    assert list(params["model"]["templates"]) == ["Recognition"]  # the other is untouched


def test_missing_field_is_added_and_extra_field_is_kept(root, monkeypatch):
    fake = _existing()
    fake.fields["Vocabulary"] = ["Expression", "Translation", "MyOwnField"]
    monkeypatch.setattr(notetypes, "anki", fake)

    plan = notetypes.plan_for(VOCAB, root)
    # What the generator writes and the type lacks, in the order of FIELDS: read
    # from the code, so that a field added to the generator does not fail this.
    assert plan.missing_fields == [f for f in VOCAB.fields
                                   if f not in ("Expression", "Translation")]
    assert plan.extra_fields == ["MyOwnField"]

    expected = list(plan.missing_fields)   # added, they are no longer "missing"
    notetypes.update(plan)
    assert [p["fieldName"] for p in fake.did("modelFieldAdd")] == expected
    # A field removed would take its content away on every note.
    assert not fake.did("modelFieldRemove")


def test_an_added_field_is_put_back_at_its_rank(root, monkeypatch):
    """Anki adds a field at the end; it is moved to its rank in FIELDS. Otherwise
    field order would depend on the profile's age, and a TSV import, which pairs
    columns by rank, would put values into the neighbouring field."""
    fake = _existing()
    fake.fields["Vocabulary"] = [f for f in VOCAB.fields if f != "Context"]
    monkeypatch.setattr(notetypes, "anki", fake)

    plan = notetypes.plan_for(VOCAB, root)
    assert plan.missing_fields == ["Context"]

    notetypes.update(plan)
    (params,) = fake.did("modelFieldReposition")
    assert (params["fieldName"], params["index"]) == ("Context",
                                                      VOCAB.fields.index("Context"))


def test_cards_named_otherwise_are_matched_by_position(root, monkeypatch):
    """A type created by hand has cards "Card 1"/"Card 2": we write into them
    rather than add two beside."""
    fake = _existing()
    fake.templates["Vocabulary"] = {
        "Card 1": {"Front": "old", "Back": "old"},
        "Card 2": {"Front": "old", "Back": "old"},
    }
    monkeypatch.setattr(notetypes, "anki", fake)

    plan = notetypes.plan_for(VOCAB, root)
    assert plan.target_names == {"Recognition": "Card 1", "Production": "Card 2"}
    notetypes.update(plan)
    written = fake.did("updateModelTemplates")[0]["model"]["templates"]
    assert set(written) == {"Card 1", "Card 2"}


def test_a_card_missing_from_anki_is_not_added_silently(root, monkeypatch):
    """The collection lacks Production: adding it would create a card to review
    per existing note, so that is asked first."""
    fake = _existing()
    fake.templates["Vocabulary"] = {"JPtoEN": {"Front": "old", "Back": "old"}}
    monkeypatch.setattr(notetypes, "anki", fake)

    plan = notetypes.plan_for(VOCAB, root)
    assert plan.target_names == {"Recognition": "JPtoEN"}   # paired in order
    assert plan.new_cards == ["Production"]
    assert not plan.unmatched

    notetypes.update(plan)                              # add_cards=False by default
    assert not fake.did("modelTemplateAdd")
    assert list(fake.did("updateModelTemplates")[0]["model"]["templates"]) == ["JPtoEN"]


def test_the_missing_card_is_added_on_explicit_request(root, monkeypatch):
    fake = _existing()
    fake.templates["Vocabulary"] = {"JPtoEN": {"Front": "old", "Back": "old"}}
    monkeypatch.setattr(notetypes, "anki", fake)

    notetypes.update(notetypes.plan_for(VOCAB, root), add_cards=True)
    (params,) = fake.did("modelTemplateAdd")
    assert params["template"]["Name"] == "Production"


def test_unmatchable_cards_are_reported_not_guessed(root, monkeypatch):
    """Anki has more than the repository: writing the front into the wrong card
    would be worse than doing nothing."""
    fake = _existing()
    fake.templates["Vocabulary"] = {
        "One": {"Front": "x", "Back": "y"},
        "Two": {"Front": "x", "Back": "y"},
        "Three": {"Front": "x", "Back": "y"},
    }
    monkeypatch.setattr(notetypes, "anki", fake)

    plan = notetypes.plan_for(VOCAB, root)
    assert plan.unmatched
    assert _outdated(plan) == []
    notetypes.update(plan)
    assert not fake.did("updateModelTemplates")


# -- What this particular profile does not install (.env) ----------------------
# The repository carries every model; the .env says which ones this profile
# installs, and what it drops is neither created, compared nor reported.

def test_a_card_left_out_of_the_env_is_not_even_read(root, monkeypatch):
    monkeypatch.setenv("KOTOGEN_VOCAB_CARDS", "Recognition")
    templates, _css = notetypes.read_templates(VOCAB, root)
    assert list(templates) == ["Recognition"]


def test_a_card_left_out_of_the_env_is_not_signalled(root, monkeypatch):
    """The repository's "Production", never installed in Anki, is not reported."""
    monkeypatch.setenv("KOTOGEN_VOCAB_CARDS", "Recognition")
    fake = _existing()
    fake.templates["Vocabulary"] = {
        "JPtoEN": {"Front": "front vocabrecognition",
                   "Back": "back vocabrecognition"},
    }
    monkeypatch.setattr(notetypes, "anki", fake)

    plan = notetypes.plan_for(VOCAB, root)
    assert plan.new_cards == [] and not plan.differs


def test_a_skipped_command_is_left_alone_by_default(monkeypatch, connected, anki):
    monkeypatch.setenv("KOTOGEN_SKIP", "grammar")
    notetypes.run_deck(_args())
    created = [p["modelName"] for p in anki.did("createModel")]
    assert "Grammar" not in created and "Vocabulary" in created


def test_everything_skipped_says_so_instead_of_crashing(monkeypatch, connected, anki, capsys):
    monkeypatch.setenv("KOTOGEN_SKIP", ",".join(notetypes.COMMANDS))
    notetypes.run_deck(_args())
    assert anki.writes == [] and "Nothing to do" in capsys.readouterr().out


def test_an_explicit_only_beats_the_skip_list(monkeypatch, connected, anki):
    """What is typed by hand wins over what the .env prefers."""
    monkeypatch.setenv("KOTOGEN_SKIP", "grammar")
    notetypes.run_deck(_args(only=["grammar"]))
    assert [p["modelName"] for p in anki.did("createModel")] == ["Grammar"]


@pytest.mark.parametrize("variable, value", [
    ("KOTOGEN_SKIP", "grammer"),          # the target misspelt
    ("KOTOGEN_VOCAB_CARDS", "Reverse"),  # a card that does not exist
])
def test_a_typo_in_the_env_says_so_instead_of_doing_nothing(
        monkeypatch, connected, anki, variable, value):
    monkeypatch.setenv(variable, value)
    with pytest.raises(SystemExit) as excinfo:
        notetypes.run_deck(_args())
    assert variable in str(excinfo.value) and not anki.writes


# -- The command ---------------------------------------------------------------

def _args(**kwargs):
    return argparse.Namespace(
        **{"action": "install", "only": None, "check": False, "yes": False,
           "add_cards": False, "diff": False, "overwrite_edits": False, **kwargs})


@pytest.fixture
def connected(monkeypatch, root):
    monkeypatch.setattr(notetypes, "templates_root", lambda *a, **k: root)
    monkeypatch.setattr("kotogen.anki.connect.status",
                        lambda **k: type("S", (), {"connected": True})())


def test_check_mode_writes_nothing(monkeypatch, connected, anki, capsys):
    notetypes.run_deck(_args(check=True))
    assert anki.writes == []
    assert "to create" in capsys.readouterr().out


def test_every_notetype_says_its_state_in_the_same_column(monkeypatch, root, capsys):
    """The name on the left, the state in one column on the right ("up to date",
    "to create"), so that the types read at a glance."""
    monkeypatch.setattr(notetypes, "anki", _existing())  # only Vocabulary exists
    monkeypatch.setattr(notetypes, "templates_root", lambda *a, **k: root)
    monkeypatch.setattr("kotogen.anki.connect.status",
                        lambda **k: type("S", (), {"connected": True})())

    notetypes.run_deck(_args(check=True))
    out = capsys.readouterr().out.splitlines()
    names = [spec.notetype for spec in notetypes.SPECS]
    heads = [line for line in out if line[:1].strip() and line.split()[0] in
             {name.split()[0] for name in names}]

    assert len(heads) == len(names)
    width = max(len(name) for name in names) + 3
    for line in heads:
        assert line[:width].rstrip() in names   # the name fits in the column
        assert line[width] != " "               # the state starts right after


def test_what_a_type_drifted_by_holds_on_one_line(monkeypatch, connected, capsys,
                                                  tmp_path):
    """The diff, the customisations and the fields close the type's own line: the
    summary is read down the column of names, and customisations said above it
    would not name their type."""
    monkeypatch.setattr(choices, "file", lambda: tmp_path / choices.FILE)
    card_templates.set_one("vocab.tts", "yes")
    fake = _existing()
    fake.templates["Vocabulary"]["Recognition"]["Front"] = "my front touched up"
    fake.fields["Vocabulary"] = [f for f in VOCAB.fields if f != "Context"]
    monkeypatch.setattr(notetypes, "anki", fake)

    notetypes.run_deck(_args(check=True))
    out = capsys.readouterr().out
    (line,) = [one for one in out.splitlines() if one.startswith("Vocabulary")]
    assert line.endswith("1 customisation, 1 field to add")
    assert "Customised" not in out


def test_existing_notetype_is_not_overwritten_without_a_yes(monkeypatch, root, capsys):
    fake = _existing()
    fake.templates["Vocabulary"]["Recognition"]["Front"] = "my front touched up"
    monkeypatch.setattr(notetypes, "anki", fake)
    monkeypatch.setattr(notetypes, "templates_root", lambda *a, **k: root)
    monkeypatch.setattr("kotogen.anki.connect.status",
                        lambda **k: type("S", (), {"connected": True})())
    monkeypatch.setattr("kotogen.exporter.ask_choice", lambda *a, **k: "n")

    notetypes.run_deck(_args(only=["vocab"]))
    out = capsys.readouterr().out
    assert not fake.did("updateModelTemplates")
    # No "left as it is" line per declined type: the refusal was just typed.
    assert "1 line on the front" in out and "updated" not in out


def _two_outdated_types():
    """An Anki where `Vocabulary` and `Listening` both drift from the repository."""
    return FakeAnki(
        models=["Vocabulary", "Listening"],
        templates={"Vocabulary": {"Recognition": {"Front": "old", "Back": "old"},
                                   "Production": {"Front": "old", "Back": "old"}},
                   "Listening": {"Listening": {"Front": "old", "Back": "old"}}},
        css={"Vocabulary": "old", "Listening": "old"},
        fields={"Vocabulary": list(VOCAB.fields),
                "Listening": list(SPEC["audio"].fields)},
    )


def test_one_question_settles_every_notetype(monkeypatch, root, capsys):
    """A single question for everything to rewrite, "yes" by default: the usual
    answer, take everything, fits in one key."""
    fake = _two_outdated_types()
    monkeypatch.setattr(notetypes, "anki", fake)
    monkeypatch.setattr(notetypes, "templates_root", lambda *a, **k: root)
    monkeypatch.setattr("kotogen.anki.connect.status",
                        lambda **k: type("S", (), {"connected": True})())
    monkeypatch.setattr("kotogen.anki.backup.before", lambda *a, **k: print("Backup 2026"))

    asked = []

    def ask(options, question="", **kwargs):
        asked.append((question, dict(options), kwargs.get("indent"), kwargs.get("default")))
        return "y"

    monkeypatch.setattr("kotogen.exporter.choose", ask)
    notetypes.run_deck(_args(only=["vocab", "audio"]))

    (question, options, indent, default), = asked  # a single one, for both types
    assert question == "Update Vocabulary and Listening?"
    assert "c" in options                          # the per-type choice stays offered
    assert (indent, default) == ("", "y")          # general question, "yes" by default
    assert len(fake.did("updateModelTemplates")) == 2


def test_the_three_moments_do_not_mix(monkeypatch, root, capsys):
    """The state of every type, then the question, then what was written: done
    type by type, the summary would be split and the backup fall in between."""
    fake = _two_outdated_types()     # two types to rewrite, the others to create
    monkeypatch.setattr(notetypes, "anki", fake)
    monkeypatch.setattr(notetypes, "templates_root", lambda *a, **k: root)
    monkeypatch.setattr("kotogen.anki.connect.status",
                        lambda **k: type("S", (), {"connected": True})())
    monkeypatch.setattr("kotogen.anki.backup.before", lambda *a, **k: print("Backup 2026"))
    monkeypatch.setattr("kotogen.exporter.choose",
                        lambda options, question="", **k: print(question) or "y")

    notetypes.run_deck(_args())
    lines = [line for line in capsys.readouterr().out.splitlines()
             if line.strip() and not line.startswith("Models read")]
    count = len(notetypes.SPECS)
    summary = [line.split()[0] for line in lines[:count]]
    assert summary == [spec.notetype for spec in notetypes.SPECS]       # in one block
    assert lines[count].startswith("Update")                             # then the question
    assert lines[count + 1] == "Backup 2026"                             # then the writing
    written = lines[count + 2:count + 4]
    assert [line.split()[0] for line in written] == ["Vocabulary", "Listening"]
    assert all(line.endswith("updated") for line in written)


def test_choosing_asks_notetype_by_notetype(monkeypatch, root, capsys):
    """`c` switches back to one question per type, on the line of the type."""
    fake = _two_outdated_types()
    monkeypatch.setattr(notetypes, "anki", fake)
    monkeypatch.setattr(notetypes, "templates_root", lambda *a, **k: root)
    monkeypatch.setattr("kotogen.anki.connect.status",
                        lambda **k: type("S", (), {"connected": True})())
    monkeypatch.setattr("kotogen.anki.backup.before", lambda *a, **k: None)

    answers = iter(["n", "y"])
    asked = []

    def ask(prompt, choices, **kwargs):
        asked.append((prompt, kwargs.get("indent", "")))
        return next(answers)

    monkeypatch.setattr("kotogen.exporter.choose", lambda *a, **k: "c")
    monkeypatch.setattr("kotogen.exporter.ask_choice", ask)
    notetypes.run_deck(_args(only=["vocab", "audio"]))

    assert [prompt for prompt, _indent in asked] == [
        "update? [y] yes  [n] no  [d] detail"] * 2
    # Each question sits on its type's line, as in the summary.
    assert [indent.strip() for _prompt, indent in asked] == ["Vocabulary", "Listening"]
    written = [p["model"]["name"] for p in fake.did("updateModelTemplates")]
    assert written == ["Listening"]                   # the "n" of the vocabulary held


def test_the_backup_opens_its_own_block_and_the_report_follows(monkeypatch, root, capsys):
    """A blank line before the backup, none after: what has been rewritten is the
    report of the backup just taken, not one more block."""
    fake = _existing()
    fake.css["Vocabulary"] = "old css"
    monkeypatch.setattr(notetypes, "anki", fake)
    monkeypatch.setattr(notetypes, "templates_root", lambda *a, **k: root)
    monkeypatch.setattr("kotogen.anki.connect.status",
                        lambda **k: type("S", (), {"connected": True})())
    monkeypatch.setattr("kotogen.anki.backup.before", lambda *a, **k: print("Backup 2026"))
    monkeypatch.setattr("kotogen.exporter.ask_choice", lambda *a, **k: "y")

    notetypes.run_deck(_args(only=["vocab"]))
    out = capsys.readouterr().out.splitlines()
    save = out.index("Backup 2026")
    assert out[save - 1] == ""                        # the backup opens its block
    assert out[save + 1] == "Vocabulary   updated"   # the report hooks onto it


def test_the_last_word_is_the_gesture_left_to_do(monkeypatch, root, capsys):
    """No recount of what the list showed: the last line is the sync to do."""
    fake = _existing()
    fake.css["Vocabulary"] = "old css"
    monkeypatch.setattr(notetypes, "anki", fake)
    monkeypatch.setattr(notetypes, "templates_root", lambda *a, **k: root)
    monkeypatch.setattr("kotogen.anki.connect.status",
                        lambda **k: type("S", (), {"connected": True})())
    monkeypatch.setattr("kotogen.anki.backup.before", lambda *a, **k: None)
    monkeypatch.setattr("kotogen.exporter.ask_choice", lambda *a, **k: "y")

    notetypes.run_deck(_args(only=["vocab"]))
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines[-1] == ("Remember to synchronise Anki (it may ask for a full sync: "
                         "that is normal).")
    assert not any("updated." in line for line in lines)


def test_nothing_written_says_nothing_at_the_end(monkeypatch, root, capsys):
    fake = _existing()
    fake.css["Vocabulary"] = "old css"
    monkeypatch.setattr(notetypes, "anki", fake)
    monkeypatch.setattr(notetypes, "templates_root", lambda *a, **k: root)
    monkeypatch.setattr("kotogen.anki.connect.status",
                        lambda **k: type("S", (), {"connected": True})())
    monkeypatch.setattr("kotogen.exporter.ask_choice", lambda *a, **k: "n")

    notetypes.run_deck(_args(only=["vocab"]))
    assert "synchronise" not in capsys.readouterr().out


def test_missing_notetype_is_created_without_asking(monkeypatch, connected, anki):
    monkeypatch.setattr("kotogen.exporter.ask_choice",
                        lambda *a, **k: pytest.fail("nothing to overwrite, nothing to ask"))
    notetypes.run_deck(_args(only=["vocab"]))
    assert len(anki.did("createModel")) == 1


def test_anki_closed_says_so(monkeypatch, root):
    monkeypatch.setattr(notetypes, "templates_root", lambda *a, **k: root)
    monkeypatch.setattr("kotogen.anki.connect.status",
                        lambda **k: type("S", (), {"connected": False})())
    with pytest.raises(SystemExit) as excinfo:
        notetypes.run_deck(_args())
    assert "AnkiConnect" in str(excinfo.value)


def test_templates_dir_missing_says_where_to_run_from(monkeypatch):
    monkeypatch.setattr(notetypes, "templates_root", lambda *a, **k: None)
    monkeypatch.setattr("kotogen.anki.connect.status",
                        lambda **k: type("S", (), {"connected": True})())
    with pytest.raises(SystemExit) as excinfo:
        notetypes.run_deck(_args())
    assert "templates/" in str(excinfo.value)


def test_unknown_target_is_rejected(monkeypatch, connected):
    with pytest.raises(SystemExit) as excinfo:
        notetypes.run_deck(_args(only=["vocabulary"]))
    assert "vocabulary" in str(excinfo.value)


# -- Who moved: what kotogen wrote last, beside Anki and the repository --------
# The record of what kotogen laid down on each face (see `installed`) tells a
# release from a touch-up made in Anki, or both.

# `Vocabulary` is the first type the fake holds, hence its ID.
VOCAB_ID = 1000


def _recorded(front="front vocabrecognition", back="back vocabrecognition",
              css="css vocab"):
    """Files, as what kotogen last wrote into `Vocabulary`, the repository's own
    templates with the faces given in place of theirs."""
    installed.remember("User 1", VOCAB_ID, {
        "cards": {"Recognition": {"Front": front, "Back": back},
                  "Production": {"Front": "front vocabproduction",
                                 "Back": "back vocabproduction"}},
        "css": css})


def _no_question(monkeypatch):
    """Fails the test on any question asked or any backup taken."""
    for name in ("kotogen.exporter.choose", "kotogen.exporter.ask_choice"):
        monkeypatch.setattr(name, lambda *a, **k: pytest.fail("nothing to ask"))
    monkeypatch.setattr("kotogen.anki.backup.before",
                        lambda *a, **k: pytest.fail("nothing to lose"))


def test_a_created_type_records_what_it_laid_down(root, anki):
    """Filed under the ID `createModel` answers with: the name is the `.env`'s."""
    plan = notetypes.plan_for(VOCAB, root)
    notetypes.create(plan)
    assert installed.recall("User 1", plan.model_id) == {
        "cards": plan.templates, "css": plan.css}


def test_a_type_found_as_the_repository_has_it_gets_its_record(monkeypatch, connected):
    """A type with no record (installed by hand, or from another machine) found
    identical gets one, and nothing is written into Anki."""
    fake = _existing()
    monkeypatch.setattr(notetypes, "anki", fake)
    notetypes.run_deck(_args(only=["vocab"]))

    base = installed.recall("User 1", VOCAB_ID)
    assert base["cards"]["Recognition"] == {"Front": "front vocabrecognition",
                                            "Back": "back vocabrecognition"}
    assert base["css"] == "css vocab"
    assert fake.writes == []


def test_check_records_nothing_either(monkeypatch, connected):
    """`--check` changes nothing, the record included."""
    monkeypatch.setattr(notetypes, "anki", _existing())
    notetypes.run_deck(_args(only=["vocab"], check=True))
    assert not installed.path().exists()


def test_without_a_record_every_difference_is_asked_about(root, monkeypatch):
    """Nothing says who moved: every difference is asked, "yes" by default."""
    fake = _existing()
    fake.templates["Vocabulary"]["Recognition"]["Front"] = "old front"
    monkeypatch.setattr(notetypes, "anki", fake)

    plan = notetypes.plan_for(VOCAB, root)
    assert [change.origin for change in plan.changes] == [notetypes.UNKNOWN]
    assert plan.asked() == plan.changes


def test_a_face_kotogen_alone_moved_is_rewritten_without_a_question(
        monkeypatch, connected, capsys):
    """Anki still holds what kotogen wrote, so the rewrite only overwrites its
    own output: no question, no backup, and a note on the type's line."""
    _recorded(front="old front")
    fake = _existing()
    fake.templates["Vocabulary"]["Recognition"]["Front"] = "old front"
    monkeypatch.setattr(notetypes, "anki", fake)
    _no_question(monkeypatch)

    notetypes.run_deck(_args(only=["vocab"]))
    (params,) = fake.did("updateModelTemplates")
    assert params["model"]["templates"]["Recognition"]["Front"] == "front vocabrecognition"
    assert "Vocabulary   updated: 1 line on the front" in capsys.readouterr().out
    recorded = installed.recall("User 1", VOCAB_ID)["cards"]["Recognition"]
    assert recorded["Front"] == "front vocabrecognition"


def test_check_says_what_kotogen_alone_would_rewrite(monkeypatch, connected, capsys):
    _recorded(front="old front")
    fake = _existing()
    fake.templates["Vocabulary"]["Recognition"]["Front"] = "old front"
    monkeypatch.setattr(notetypes, "anki", fake)

    notetypes.run_deck(_args(only=["vocab"], check=True))
    assert "Vocabulary   to update: 1 line on the front" in capsys.readouterr().out
    assert fake.writes == []


def test_a_face_anki_alone_moved_is_kept_and_not_offered(monkeypatch, connected, capsys):
    """The repository still holds what kotogen wrote: the difference is a
    touch-up, and the repository is not offered back over it at every install."""
    _recorded()
    fake = _existing()
    fake.templates["Vocabulary"]["Recognition"]["Front"] = "my front touched up"
    monkeypatch.setattr(notetypes, "anki", fake)
    _no_question(monkeypatch)

    notetypes.run_deck(_args(only=["vocab"]))
    out = capsys.readouterr().out
    assert not fake.did("updateModelTemplates")
    assert "Vocabulary   kept as edited in Anki: 1 line on the front" in out
    assert "synchronise" not in out


def test_overwrite_edits_puts_the_question_back(monkeypatch, connected, capsys):
    _recorded()
    fake = _existing()
    fake.templates["Vocabulary"]["Recognition"]["Front"] = "my front touched up"
    monkeypatch.setattr(notetypes, "anki", fake)
    monkeypatch.setattr("kotogen.anki.backup.before", lambda *a, **k: None)
    monkeypatch.setattr("kotogen.exporter.ask_choice", lambda *a, **k: "y")

    notetypes.run_deck(_args(only=["vocab"], overwrite_edits=True))
    assert "Vocabulary   edited in Anki: 1 line on the front" in capsys.readouterr().out
    (params,) = fake.did("updateModelTemplates")
    assert params["model"]["templates"]["Recognition"]["Front"] == "front vocabrecognition"


def test_a_face_moved_on_both_sides_is_asked_with_no_by_default(
        monkeypatch, connected, capsys):
    """A known touch-up is not overwritten by a bare Enter. Declined, the record
    keeps what kotogen wrote, so the next install asks again rather than take
    the touch-up for kotogen's."""
    _recorded(front="old front")
    fake = _existing()
    fake.templates["Vocabulary"]["Recognition"]["Front"] = "old front touched up"
    monkeypatch.setattr(notetypes, "anki", fake)
    defaults = []

    def ask(options, question="", **kwargs):
        defaults.append(kwargs.get("default"))
        return "n"

    monkeypatch.setattr("kotogen.exporter.choose", ask)
    notetypes.run_deck(_args(only=["vocab"]))

    assert defaults == ["n"]
    assert not fake.did("updateModelTemplates")
    out = capsys.readouterr().out
    assert "Vocabulary   edited in Anki, changed in kotogen: 1 line on the front" in out
    recorded = installed.recall("User 1", VOCAB_ID)["cards"]["Recognition"]
    assert recorded["Front"] == "old front"


def test_both_sides_are_unfolded_each_from_what_kotogen_wrote():
    """One diff from Anki to the repository would mix touch-up and release."""
    change = notetypes.Change(notetypes.FRONT, ours="a\nB\nc", theirs="A\nb\nc",
                              card="Recognition", base="a\nb\nc")
    assert change.origin == notetypes.BOTH
    assert notetypes._unfolded([change]) == [
        "   edited in Anki:", "      -a", "      +A",
        "   changed in kotogen:", "      -b", "      +B",
    ]


def test_a_card_written_twice_keeps_the_first_rewrite(monkeypatch, connected):
    """The front only kotogen moved goes unasked, the back moved on both sides is
    asked. `updateModelTemplates` writes the whole card, so the second write must
    carry the first one's front, not the one Anki held before."""
    _recorded(front="old front", back="old back")
    fake = _existing()
    card = fake.templates["Vocabulary"]["Recognition"]
    card["Front"] = "old front"
    card["Back"] = "my back"
    monkeypatch.setattr(notetypes, "anki", fake)
    monkeypatch.setattr("kotogen.anki.backup.before", lambda *a, **k: None)
    monkeypatch.setattr("kotogen.exporter.ask_choice", lambda *a, **k: "y")

    notetypes.run_deck(_args(only=["vocab"]))
    first, second = (params["model"]["templates"]["Recognition"]
                     for params in fake.did("updateModelTemplates"))
    assert first == {"Front": "front vocabrecognition", "Back": "my back"}
    assert second == {"Front": "front vocabrecognition", "Back": "back vocabrecognition"}


def test_the_movers_of_one_type_each_take_their_line(monkeypatch, connected, capsys):
    """Each mover on its own line, or one could not tell which waits for an
    answer; the type's name opens the first line only."""
    _recorded(front="old front", css="old css")
    fake = _existing()
    fake.templates["Vocabulary"]["Recognition"]["Front"] = "old front"
    fake.css["Vocabulary"] = "my css"
    monkeypatch.setattr(notetypes, "anki", fake)

    notetypes.run_deck(_args(only=["vocab"], check=True))
    out = capsys.readouterr().out.splitlines()
    start = out.index("Vocabulary   to update: 1 line on the front")
    assert out[start + 1] == "             edited in Anki, changed in kotogen: 1 line in the CSS"


# -- The repository itself -----------------------------------------------------

def test_the_real_templates_are_all_readable():
    real = notetypes.templates_root()
    assert real is not None
    for spec in notetypes.SPECS:
        templates, css = notetypes.read_templates(spec, real)
        assert len(templates) == len(spec.cards)
        assert css
        for card in templates.values():
            assert card["Front"] and card["Back"]


def test_the_templates_of_the_current_folder_are_not_ours(tmp_path, monkeypatch):
    """Another project's `templates/` is not what `deck install` writes into
    Anki: the folder is the one beside the sources, wherever one stands."""
    (tmp_path / "templates" / "vocab").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    assert notetypes.templates_root() == settings.ROOT / "templates"


def test_every_field_used_by_a_template_exists_in_the_notetype():
    """A {{Field}} of a template absent from FIELDS would give a mute card."""
    import re

    real = notetypes.templates_root()
    builtin = {"FrontSide", "Tags", "Type", "Deck", "Subdeck", "Card", "CardFlag"}
    for spec in notetypes.SPECS:
        templates, _css = notetypes.read_templates(spec, real)
        known = set(spec.fields) | builtin
        for name, card in templates.items():
            used = set(re.findall(r"\{\{[#^/]?(?:[\w: ]*?::)?([^{}:#^/]+?)\}\}",
                                  card["Front"] + card["Back"]))
            unknown = {f.strip() for f in used if f.strip() and f.strip() not in known}
            # `cloze` and the compound filters sometimes fall out of the pattern:
            # only what really looks like a field name is kept.
            unknown = {f for f in unknown if not f.startswith(("c1", "text:"))}
            assert not unknown, f"{spec.notetype}/{name}: unknown field(s) {unknown}"
