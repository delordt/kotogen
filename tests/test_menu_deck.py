"""The screens that work on the deck itself: maintenance, questions to the deck,
backups, note types and the appearance of the cards."""

import json
import os
import re

from kotogen import console, i18n, interactive
from kotogen.anki import templates as card_templates
from kotogen.anki.maintain import marks
from kotogen.interactive import interactive_argv
from menus import *  # the fixtures every menu test starts from, and its helpers

# ── maintain ──────────────────────────────────────────────────────────────────

def test_maintain_scan_is_default(monkeypatch):
    feed(monkeypatch, ["6", ""])
    assert interactive_argv() == ["maintain", "--scan"]


def test_maintain_process_with_targets(monkeypatch):
    feed(monkeypatch, ["6", "2", "red leech", ""])
    assert interactive_argv() == ["maintain", "--only", "red", "leech"]


def test_without_a_model_the_corrections_still_look_at_the_deck(monkeypatch, capsys):
    """Looking and the marks call no model: only what does is dimmed, inside."""
    monkeypatch.delenv("KOTOGEN_MODEL")
    feed(monkeypatch, ["6", "1"])
    assert interactive_argv() == ["maintain", "--scan"]
    assert "Corrections needs" not in capsys.readouterr().out


def test_without_a_model_handling_the_marks_says_what_it_lacks(monkeypatch, capsys):
    monkeypatch.delenv("KOTOGEN_MODEL")
    feed(monkeypatch, ["6", "2", "b", "q"])
    assert interactive_argv() is None
    assert "Handle needs a model." in capsys.readouterr().out


def test_maintain_process_validates_by_hand_by_default(monkeypatch):
    """Enter to both questions: every target, none without validation."""
    feed(monkeypatch, ["6", "2", "", ""])
    assert interactive_argv() == ["maintain"]


def test_maintain_unknown_target_is_asked_again(monkeypatch):
    feed(monkeypatch, ["6", "2", "crimson", "red", ""])
    assert interactive_argv() == ["maintain", "--only", "red"]


def test_maintain_auto_on_every_target(monkeypatch):
    feed(monkeypatch, ["6", "2", "all", "all"])
    assert interactive_argv() == ["maintain", "--yes"]


def test_maintain_auto_on_a_subset(monkeypatch):
    """Targets handled and automatic targets are two distinct questions."""
    feed(monkeypatch, ["6", "2", "red leech", "red"])
    assert interactive_argv() == ["maintain", "--only", "red", "leech", "--yes", "red"]


def test_maintain_auto_is_limited_to_processed_targets(monkeypatch):
    """A target not handled, given as automatic, asks the question again."""
    feed(monkeypatch, ["6", "2", "red", "leech", "red"])
    assert interactive_argv() == ["maintain", "--only", "red", "--yes", "red"]


def test_maintain_targets_offered_are_those_accepted():
    """The list shown cannot drift away from the one the question accepts.

    The definitions come from the flags of `marks`, the validation from
    `maintain_targets()`: a flag added to one only would be offered then refused."""
    offered = {re.search(r"[a-z]+", line).group()
               for line in interactive.maintain._maintain_target_lines()}
    assert offered <= interactive.maintain.maintain_targets()
    assert offered == {"red", "orange", "green", "blue", "pink", "turquoise", "purple",
                       "leech"}


def test_maintain_targets_say_what_each_flag_aims_at(monkeypatch, capsys):
    """Every target shows its name to type and its definition, `leech` included."""
    feed(monkeypatch, ["6", "2", "red", ""])
    interactive_argv()
    out = capsys.readouterr().out
    assert "🔴 red         possible mistake" in out
    assert "   leech       failed over and over" in out


def test_maintain_targets_carry_what_awaits_them(monkeypatch, capsys):
    """The count of each target is read in the list where one chooses it."""
    monkeypatch.setattr(interactive.maintain, "_maintain_counts",
                        lambda: {"red": 3, "green": 10, "leech": 5})
    feed(monkeypatch, ["6", "2", "red", ""])
    interactive_argv()
    out = capsys.readouterr().out
    assert "🔴 red         possible mistake       3" in out
    assert "🟢 green       to enrich             10" in out
    assert "   leech       failed over and over   5" in out


def test_maintain_does_not_count_the_empty_targets(monkeypatch, capsys):
    """A target with no card shows no "0" and no trailing spaces: the line stops
    at its definition."""
    monkeypatch.setattr(interactive.maintain, "_maintain_counts",
                        lambda: {"red": 3, "orange": 0, "leech": 0})
    feed(monkeypatch, ["6", "2", "red", ""])
    interactive_argv()
    out = capsys.readouterr().out
    assert "🟠 orange      to simplify\n" in out
    assert "   leech       failed over and over\n" in out


def test_maintain_with_nothing_to_handle_comes_back_to_the_menu(monkeypatch, capsys):
    """A clean deck asks for no targets: the dialogue goes back to the maintenance
    menu, where "Look" ("1") still has something to say."""
    monkeypatch.setattr(interactive.maintain, "_maintain_counts",
                        lambda: {colour: 0 for colour in
                                 (*marks.FLAG_BY_NAME, "leech")})
    feed(monkeypatch, ["6", "2", "1"])
    assert interactive_argv() == ["maintain", "--scan"]
    assert "Nothing to handle" in capsys.readouterr().out


def test_maintain_a_silent_deck_still_lets_one_choose(monkeypatch):
    """Anki closed between the probe and the dialogue: the list loses its figures,
    not its targets."""
    feed(monkeypatch, ["6", "2", "red", ""])
    assert interactive_argv() == ["maintain", "--only", "red"]


def test_maintain_counts_keep_quiet_when_the_deck_does_not_answer(monkeypatch):
    """A count Anki cannot answer does not break off the dialogue.

    The real function is called, not the stand-in of `silent_deck`: its own catch
    is what is tested."""
    def closed(notetype, flag):
        raise ConnectionError("Anki closed")

    monkeypatch.setattr("kotogen.anki.maintain.marks.find_flagged", closed)
    assert _MAINTAIN_COUNTS() is None


def test_maintain_asks_its_two_questions_in_a_row(monkeypatch, capsys):
    """Nothing comes between the two choices: one list serves both. Input is faked
    (`console.read_line`), so the two prompts share a line in the capture."""
    feed(monkeypatch, ["6", "2", "red", ""])
    interactive_argv()
    out = capsys.readouterr().out
    assert "Without validation" not in out
    assert re.search(r"Targets to handle[^\n]*: ?Targets to apply without validation",
                     out)


# ── ask ───────────────────────────────────────────────────────────────────────

def test_ask_builds_its_own_command(monkeypatch):
    """The entry sits in the maintenance menu but launches `ask`, with the sentence
    typed as its only target."""
    feed(monkeypatch, ["6", "3", "take the N4 tag off the mature cards"])
    assert interactive_argv() == ["ask", "take the N4 tag off the mature cards"]


def test_ask_carries_nothing_of_maintenance(monkeypatch, capsys):
    """No target, no automatic: the question is the only step, and the flags of
    `maintain` mean nothing here."""
    feed(monkeypatch, ["6", "3", "shorten my cooking examples"])
    argv = interactive_argv()
    assert argv[0] == "ask" and "--only" not in argv and "--yes" not in argv
    out = capsys.readouterr().out
    assert "Targets to handle" not in out
    assert "backed up first" in out


def test_ask_is_dimmed_for_a_provider_that_drives_no_tools(monkeypatch, capsys):
    """Chosen all the same, it says why, then the corrections menu comes back:
    no request is typed for a command that would refuse it."""
    monkeypatch.setenv("KOTOGEN_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    feed(monkeypatch, ["6", "3", "", "1"])
    assert interactive_argv() == ["maintain", "--scan"]
    out = capsys.readouterr().out
    assert "Ask needs a provider that drives tools." in out
    assert "The provider anthropic drives no tools" in out
    assert "Your request" not in out


# ── Backup ────────────────────────────────────────────────────────────────────

def test_backup_takes_a_snapshot(monkeypatch):
    feed(monkeypatch, ["8", "1"])
    assert interactive_argv() == ["backup"]


def test_backup_lists_what_exists(monkeypatch):
    feed(monkeypatch, ["8", "3"])
    assert interactive_argv() == ["backup", "--list"]


def test_backup_without_a_single_snapshot_says_so_instead_of_offering_none(
        monkeypatch, tmp_path, capsys):
    """With no snapshot, "compare" says so and goes back to the backup menu
    rather than show an empty list."""
    monkeypatch.setenv("KOTOGEN_BACKUP_DIR", str(tmp_path / "empty"))
    feed(monkeypatch, ["8", "4", "", "1"])
    assert interactive_argv() == ["backup"]
    assert "No backup to compare" in capsys.readouterr().out


def test_restoring_picks_among_the_snapshots_on_disk(monkeypatch, tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir()
    for stamp in ("2026-08-16_120000", "2026-08-17_143012"):
        (directory / f"{stamp}-maintain.json").write_text(
            '{"version": 1, "notetypes": {}}', encoding="utf-8")
    monkeypatch.setenv("KOTOGEN_BACKUP_DIR", str(directory))
    # The most recent is at the head of the list, hence the choice "1".
    feed(monkeypatch, ["8", "5", "1"])
    assert interactive_argv() == ["backup", "--restore", "2026-08-17_143012"]


def test_each_snapshot_offered_counts_its_notes_in_agreement(monkeypatch, tmp_path,
                                                             capsys):
    """One note is "1 note", never "1 notes"."""
    directory = tmp_path / "backups"
    directory.mkdir()
    for stamp, notes in (("2026-08-16_120000", 2), ("2026-08-17_143012", 1)):
        (directory / f"{stamp}-maintain.json").write_text(json.dumps(
            {"version": 1, "notetypes": {"Vocabulary": {"notes": [{}] * notes}}}),
            encoding="utf-8")
    monkeypatch.setenv("KOTOGEN_BACKUP_DIR", str(directory))
    feed(monkeypatch, ["8", "5", "1"])
    interactive_argv()
    out = capsys.readouterr().out
    assert re.search(r"2026-08-17_143012 +maintain +1 note$", out, re.MULTILINE)
    assert re.search(r"2026-08-16_120000 +maintain +2 notes$", out, re.MULTILINE)


def test_a_single_snapshot_is_taken_without_a_menu(monkeypatch, tmp_path):
    """One backup leaves nothing to choose: no menu of one entry to confirm."""
    directory = tmp_path / "backups"
    directory.mkdir()
    (directory / "2026-08-17_143012-maintain.json").write_text(
        '{"version": 1, "notetypes": {}}', encoding="utf-8")
    monkeypatch.setenv("KOTOGEN_BACKUP_DIR", str(directory))
    feed(monkeypatch, ["8", "5"])
    assert interactive_argv() == ["backup", "--restore", "2026-08-17_143012"]


# ── Decks and note types ──────────────────────────────────────────────────────
# The screen only shows and writes these settings: it must write what the line
# shows, and refuse the one state a setting cannot say. A note type is chosen
# first, then its setting.

def test_the_decks_screen_lists_every_notetype(monkeypatch, capsys):
    """The list of the types already says where each of them goes in Anki."""
    feed(monkeypatch, ["7", "5", "b", "3"])
    assert interactive_argv() == ["deck", "install"]
    out = capsys.readouterr().out
    for name in ("Vocabulary", "Grammar", "Listening", "Reading", "Kanji"):
        assert name in out
    assert "Japanese::Vocabulary" in out


def test_a_notetype_screen_holds_its_own_settings(monkeypatch, capsys):
    """The four settings sit behind the type: all on one screen, at thirty lines,
    they would not fit in the window."""
    feed(monkeypatch, ["7", "5", "2", "b", "b", "3"])
    assert interactive_argv() == ["deck", "install"]
    # Those two lines exist only behind a type; the list holds names and decks.
    out = capsys.readouterr().out
    assert "Cards installed" in out and "Note type" in out


def test_uninstalling_a_notetype_hides_its_command(monkeypatch, capsys):
    """The same setting as "hide" in the welcome menu: the command leaves the list
    of cards to make too."""
    # 3 = Grammar, 1 = Installed, then back up to the welcome menu, whose redraw
    # shows the command hidden.
    feed(monkeypatch, ["7", "5", "3", "1", "b", "b", "b", "q"])
    assert interactive_argv() is None
    assert os.environ["KOTOGEN_SKIP"] == "grammar"
    out = capsys.readouterr().out
    assert interactive.deck._row("Installed", "no") in out
    assert "Hidden commands: grammar" in out


def test_a_card_left_out_is_written_as_a_white_list(monkeypatch):
    feed(monkeypatch, ["7", "5", "2", "2", "2", "b", "b", "b", "3"])
    interactive_argv()
    assert os.environ["KOTOGEN_VOCAB_CARDS"] == "Recognition"


def test_installing_them_all_is_written_by_writing_nothing(monkeypatch):
    """Taking every card writes nothing, so a card the repository adds later is
    installed without touching the setting."""
    monkeypatch.setenv("KOTOGEN_VOCAB_CARDS", "Recognition")
    feed(monkeypatch, ["7", "5", "2", "2", "2", "b", "b", "b", "3"])
    interactive_argv()
    assert os.environ["KOTOGEN_VOCAB_CARDS"] == ""


def test_a_notetype_cannot_be_left_without_a_card(monkeypatch, capsys):
    """An empty list means "all", so unticking the last card is refused, with a
    word on where to go."""
    monkeypatch.setenv("KOTOGEN_VOCAB_CARDS", "Recognition")
    feed(monkeypatch, ["7", "5", "2", "2", "1", "b", "b", "b", "3"])
    interactive_argv()
    assert os.environ["KOTOGEN_VOCAB_CARDS"] == "Recognition"
    assert "with no card would install nothing" in capsys.readouterr().out


def test_renaming_the_deck_keeps_it_for_the_next_runs(monkeypatch):
    feed(monkeypatch, ["7", "5", "2", "3", "日本語::Vocabulary", "b", "b", "3"])
    interactive_argv()
    assert os.environ["KOTOGEN_VOCAB_DECK"] == "日本語::Vocabulary"


def test_the_notetype_name_says_it_renames_nothing(monkeypatch, capsys):
    """A deck is created at the send, but a renamed note type aims at another and
    leaves the old one with its notes: the screen says so first."""
    feed(monkeypatch, ["7", "5", "2", "4", "Vocabulary (v2)", "b", "b", "3"])
    interactive_argv()
    assert os.environ["KOTOGEN_VOCAB_NOTETYPE"] == "Vocabulary (v2)"
    assert "renames nothing in Anki" in capsys.readouterr().out


def test_a_name_left_as_it_was_writes_nothing(monkeypatch):
    feed(monkeypatch, ["7", "5", "2", "3", "", "b", "b", "3"])
    interactive_argv()
    assert "KOTOGEN_VOCAB_DECK" not in os.environ


# ── Appearance of the cards ───────────────────────────────────────────────────
# The second entry of the Templates menu opens a screen, not a command, and the
# menu reopens behind it. Its settings go to a file of their own, hence the
# throwaway `templates_profile`: the user's own would sway the tests, and be changed.

def test_the_appearance_screen_opens_and_gives_the_menu_back(
        monkeypatch, templates_profile, capsys):
    feed(monkeypatch, ["7", "2", "2", "b", "b", "3"])
    assert interactive_argv() == ["deck", "install"]
    out = capsys.readouterr().out
    assert "Speech synthesis (TTS)" in out and "Vocabulary" in out


def test_a_setting_label_leaves_room_for_its_value():
    """A label as wide as its column glues the value to it.

    `_row` lays the value at `_VALUES` whatever the length of the label, so every
    language shipped is measured."""
    for lang in i18n.available():
        table = i18n._load(lang)
        too_wide = [setting.label for setting in card_templates.SETTINGS
                    if console.width(table.get(setting.label, setting.label))
                    >= interactive.deck._VALUES]
        assert too_wide == [], lang


def test_the_appearance_screen_picks_a_notetype_first(
        monkeypatch, templates_profile, capsys):
    """Every setting at once would be taller than the window, so the card is
    chosen first. The list shows what changed beside each card, and nothing beside
    the others."""
    card_templates.set_one("vocab.tts", "yes")
    card_templates.set_one("reading.order", "fixed")
    card_templates.set_one("reading.furigana", "back")
    feed(monkeypatch, ["7", "2", "b", "3"])
    interactive_argv()
    listing = capsys.readouterr().out
    assert interactive.deck._row("Vocabulary", "TTS added") in listing
    assert interactive.deck._row("Reading", "2 changes") in listing
    # Nothing changed is not said: the line stops on the name of the card.
    assert "\n    3. Grammar\n" in listing
    # The settings themselves are behind: the list does not carry them.
    assert "Audio playback (TTS)" not in listing
    # Except those that hold for every card, which toggle on the list itself.
    assert interactive.deck._row("Palette", "dark") in listing


def test_the_appearance_screen_writes_the_templates_to_disk(
        monkeypatch, templates_profile, tmp_path, capsys):
    """The way out when Anki does not answer or there is no browser. What is
    written is the rendering, ready to paste into Anki."""
    monkeypatch.setenv("KOTOGEN_OUTPUT_DIR", str(tmp_path))
    card_templates.set_one("vocab.notes", "no")
    feed(monkeypatch, ["7", "2", "w", "b", "3"])
    assert interactive_argv() == ["deck", "install"]

    folder = tmp_path / "templates"
    assert (folder / "README.txt").exists()
    # Each installed card gets a subfolder named as in Anki (`recognition` in the
    # repository).
    back = (folder / "Vocabulary" / "Recognition" / "back.html").read_text(
        encoding="utf-8")
    assert "{{furigana::Notes}}" not in back    # the setting was applied before writing
    assert str(folder) in capsys.readouterr().out


def test_a_browserless_machine_is_told_where_else_to_look(
        monkeypatch, templates_profile, capsys):
    """A preview that cannot open points to the other way: the templates written
    to disk."""
    from kotogen.anki import preview

    monkeypatch.setattr(preview, "serve", lambda **k: (_ for _ in ()).throw(
        preview.Unavailable("no browser")))
    feed(monkeypatch, ["7", "1", "3"])
    assert interactive_argv() == ["deck", "install"]

    out = capsys.readouterr().out
    assert "Preview unavailable: no browser" in out
    assert 'entry "w" of the Appearance screen' in out


def test_a_global_setting_toggles_on_the_list_itself(monkeypatch, templates_profile):
    """The palette dresses every card, so it is set on the list rather than inside
    one card. After the five note types, 6 = Palette."""
    feed(monkeypatch, ["7", "2", "6", "b", "3"])
    interactive_argv()
    assert card_templates.value("all.palette") == "light"


def test_the_palette_steps_on_to_follow_anki(monkeypatch, templates_profile, capsys):
    """Three positions, one key: dark, light, then the one that follows Anki's
    night mode - said in words on the line, not as the `auto` of the file."""
    feed(monkeypatch, ["7", "2", "6", "6", "b", "3"])
    interactive_argv()
    assert card_templates.value("all.palette") == "auto"
    assert "follows Anki" in capsys.readouterr().out


def test_the_language_of_the_cards_is_not_an_appearance(
        monkeypatch, templates_profile, capsys):
    """It picks the instructions the cards are generated from and changes no
    template: it is set in the settings ("g"), not here."""
    feed(monkeypatch, ["7", "2", "b", "3"])
    interactive_argv()
    assert "Language of the cards" not in capsys.readouterr().out
    assert card_templates.value("all.lang") == "en"


def test_resetting_the_appearance_keeps_the_language_of_the_cards(
        monkeypatch, templates_profile, capsys):
    """"Put everything back to default" undoes what the screen shows, and the
    language of generation is not on it: a French collection stays French."""
    card_templates.set_one("all.lang", "fr")
    card_templates.set_one("vocab.tts", "yes")
    feed(monkeypatch, ["7", "2", "z", "y", "b", "3"])
    interactive_argv()
    assert card_templates.value("vocab.tts") == "no"
    assert card_templates.value("all.lang") == "fr"


def test_the_language_alone_offers_no_reset(monkeypatch, templates_profile, capsys):
    """With nothing but the language set, the templates are those of the
    repository: there is nothing for the screen to put back."""
    card_templates.set_one("all.lang", "fr")
    feed(monkeypatch, ["7", "2", "b", "3"])
    interactive_argv()
    assert "Put everything back to default" not in capsys.readouterr().out


def test_leaving_a_screen_redraws_the_menu_on_a_clean_page(
        monkeypatch, templates_profile, capsys):
    """`_dialog` clears the page before the first showing of the menu; the loop
    clears it on the way back from a screen, or the menu is drawn under it."""
    monkeypatch.setattr(interactive.screen, "_clear", lambda: print("<<fresh page>>"))
    feed(monkeypatch, ["7", "2", "b", "3"])
    assert interactive_argv() == ["deck", "install"]
    last = capsys.readouterr().out.rsplit("<<fresh page>>", 1)[-1]
    assert "Templates - what to do?" in last
    assert "these settings say what you keep of them" not in last


def test_a_setting_toggles_in_place_and_outlives_the_session(
        monkeypatch, templates_profile):
    feed(monkeypatch, ["7", "2", "2", "10", "b", "b", "3"])
    assert interactive_argv() == ["deck", "install"]
    assert card_templates.value("vocab.tts") == "yes"
    assert "vocab.tts=yes" in templates_profile.read_text(encoding="utf-8")


def test_pressing_twice_comes_back_to_the_repo(monkeypatch, templates_profile):
    """Two positions: the second press undoes the first, with no question."""
    feed(monkeypatch, ["7", "2", "2", "10", "10", "b", "b", "3"])
    interactive_argv()
    assert card_templates.is_default() and not templates_profile.exists()


def test_nothing_to_reset_means_no_reset_entry(monkeypatch, templates_profile, capsys):
    feed(monkeypatch, ["7", "2", "b", "3"])
    interactive_argv()
    assert "Put everything back to default" not in capsys.readouterr().out


def test_resetting_says_what_it_undoes_and_asks_first(
        monkeypatch, templates_profile, capsys):
    """The one question of the screen: the reset also undoes older settings."""
    card_templates.set_one("vocab.tts", "yes")
    feed(monkeypatch, ["7", "2", "z", "y", "b", "3"])
    interactive_argv()
    assert card_templates.is_default()
    assert "TTS added" in capsys.readouterr().out


def test_a_refused_reset_keeps_everything(monkeypatch, templates_profile):
    card_templates.set_one("vocab.tts", "yes")
    feed(monkeypatch, ["7", "2", "z", "n", "b", "3"])
    interactive_argv()
    assert card_templates.value("vocab.tts") == "yes"


class _FakePreview:
    """A preview that opens nothing: the tests have no browser, and a real server
    would make the screen depend on a free port."""

    def __init__(self):
        self.anchors = []
        self.closed = False

    def serve(self, chosen=(), *, anchor="", open_browser=True):
        self.anchors.append(anchor)
        return self

    url = "http://127.0.0.1:0/"
    notes = ["a note of the bench"]

    def stop(self):
        self.closed = True


def test_the_appearance_screens_leave_the_preview_to_the_menu(
        monkeypatch, templates_profile, capsys):
    """The preview heads the Templates menu, one step up: one way in for one page.
    4 = Listening."""
    feed(monkeypatch, ["7", "2", "4", "b", "b", "3"])
    interactive_argv()
    assert "Preview of the cards" not in capsys.readouterr().out


def test_the_templates_menu_puts_the_cards_before_anki(monkeypatch, capsys):
    """Two groups: what the cards look like, then what Anki holds of them; the
    preview opens the first."""
    feed(monkeypatch, ["7", "b", "q"])
    interactive_argv()
    screen = capsys.readouterr().out.split("Templates - what to do?", 1)[1]
    order = [screen.index(text) for text in
             ("Your cards", "1. Preview", "2. Appearance",
              "In Anki", "3. Install", "4. Compare", "5. Decks and types")]
    assert order == sorted(order)


def test_the_templates_menu_opens_on_the_preview(
        monkeypatch, templates_profile, capsys):
    """Enter alone opens it on the first card, and the menu comes back behind it
    with the same entry selected."""
    from kotogen.anki import preview

    fake = _FakePreview()
    monkeypatch.setattr(preview, "serve", fake.serve)
    feed(monkeypatch, ["7", "", "3"])
    assert interactive_argv() == ["deck", "install"]
    assert fake.anchors == [""] and fake.closed
    out = capsys.readouterr().out
    assert "http://127.0.0.1:0/" in out and "a note of the bench" in out
    assert out.count("Templates - what to do?") == 2
    assert out.count("> [1]") == 2


def test_the_preview_says_how_to_close_it_on_a_page_of_its_own(
        monkeypatch, templates_profile, capsys):
    """Written after a menu, the line saying how to close the preview would fall
    below the window, and the terminal would look stuck."""
    from kotogen.anki import preview

    monkeypatch.setattr(preview, "serve", _FakePreview().serve)
    monkeypatch.setattr(interactive.screen, "_clear", lambda: print("<<fresh page>>"))
    # The pause needs a terminal; the line is written without one too.
    feed(monkeypatch, ["7", "1", "3"])
    interactive_argv()
    screens = capsys.readouterr().out.split("<<fresh page>>")
    assert any("Preview opened" in screen for screen in screens)
    opened = next(screen for screen in screens if "Preview opened" in screen)
    assert "Audio playback (TTS)" not in opened


def test_the_preview_is_closed_when_the_screen_is_left(
        monkeypatch, templates_profile):
    """A tab left behind must no longer be able to write into the settings."""
    from kotogen.anki import preview

    fake = _FakePreview()
    monkeypatch.setattr(preview, "serve", fake.serve)
    feed(monkeypatch, ["7", "1", "3"])
    interactive_argv()
    assert fake.closed


def test_an_unavailable_preview_says_so_and_comes_back(
        monkeypatch, templates_profile, capsys):
    """With no templates to hand, the screen says so and stays open."""
    from kotogen.anki import preview

    def refuse(*_a, **_kw):
        raise preview.Unavailable("templates/ folder not found")

    monkeypatch.setattr(preview, "serve", refuse)
    feed(monkeypatch, ["7", "1", "3"])
    assert interactive_argv() == ["deck", "install"]
    assert "Preview unavailable" in capsys.readouterr().out


# ── The marks of maintain ─────────────────────────────────────────────────────

def _written(monkeypatch) -> list:
    written: list = []
    monkeypatch.setattr("kotogen.settings.write",
                        lambda name, value: written.append((name, value)) or "/tmp/settings.env")
    return written


def test_a_flag_is_given_another_action(monkeypatch, capsys):
    """Corrections > Marks > Pink > "to renew": held for this session and the next."""
    written = _written(monkeypatch)
    # corrections; marks; pink; renew (8th action); back; back; quit
    feed(monkeypatch, ["6", "4", "5", "8", "b", "b", "q"])
    assert interactive_argv() is None
    assert written == [("KOTOGEN_FLAGS", "pink=renew")]
    assert os.environ["KOTOGEN_FLAGS"] == "pink=renew"
    out = capsys.readouterr().out
    assert "Pink - which action?" in out
    assert "to renew" in out


def test_the_star_takes_the_action_of_another_flag(monkeypatch):
    """The flag that held it takes what the star had: nothing."""
    written = _written(monkeypatch)
    # corrections; marks; star (8th mark); derive (5th action); back; back; quit
    feed(monkeypatch, ["6", "4", "8", "5", "b", "b", "q"])
    interactive_argv()
    assert written == [("KOTOGEN_FLAGS", "pink=none,star=derive")]


def test_the_leeches_can_be_left_alone(monkeypatch, capsys):
    written = _written(monkeypatch)
    # corrections; marks; leech (9th line); no action; back; back; quit
    feed(monkeypatch, ["6", "4", "9", "2", "b", "b", "q"])
    interactive_argv()
    assert written == [("KOTOGEN_FLAGS", "leech=none")]
    assert "Leech - which action?" in capsys.readouterr().out


def test_a_flag_changed_keeps_the_leeches_left_alone(monkeypatch):
    written = _written(monkeypatch)
    monkeypatch.setenv("KOTOGEN_FLAGS", "leech=none")
    # corrections; marks; pink; renew (8th action); back; back; quit
    feed(monkeypatch, ["6", "4", "5", "8", "b", "b", "q"])
    interactive_argv()
    assert written == [("KOTOGEN_FLAGS", "pink=renew,leech=none")]


def test_the_leeches_left_alone_leave_the_targets(monkeypatch, capsys):
    monkeypatch.setenv("KOTOGEN_FLAGS", "leech=none")
    feed(monkeypatch, ["6", "2", "", ""])
    assert interactive_argv() == ["maintain"]
    assert "failed over and over" not in capsys.readouterr().out


def test_the_defaults_come_back_in_one_gesture(monkeypatch):
    written = _written(monkeypatch)
    monkeypatch.setenv("KOTOGEN_FLAGS", "pink=renew")
    feed(monkeypatch, ["6", "4", "z", "b", "b", "q"])
    interactive_argv()
    assert written == [("KOTOGEN_FLAGS", "")]


def test_the_targets_follow_the_flags(monkeypatch, capsys):
    """A flag given no action leaves the list; the action is accepted by name."""
    monkeypatch.setenv("KOTOGEN_FLAGS", "purple=none,star=renew")
    feed(monkeypatch, ["6", "2", "renew", ""])
    assert interactive_argv() == ["maintain", "--only", "renew"]
    out = capsys.readouterr().out
    assert "purple" not in out
    assert "⭐ star        to renew" in out
