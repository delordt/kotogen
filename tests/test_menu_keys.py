"""Driving the menus by keys: arrows, digits, searches, tick boxes, and what
was typed before the screen was drawn."""

import os
import re
import sys

from kotogen import audio_quality, console, i18n, interactive, keyboard, prefs, system
from kotogen.interactive import interactive_argv
from kotogen.interactive.screen import BANNER
from menus import *  # the fixtures every menu test starts from, and its helpers

# ── Driving by keys ───────────────────────────────────────────────────────────
# On a terminal the menus take arrows too. The tests play the source of keys,
# and `raw_mode` has nothing to set.

THREE = [("first", "first option"), ("second", "second option"), ("third", "third option")]


def test_arrows_move_the_selection_and_enter_validates(keys, capsys):
    keys([keyboard.DOWN, keyboard.DOWN, keyboard.ENTER])
    assert interactive.screen._menu("", THREE) == "third"
    assert "third option" in _highlighted(capsys.readouterr().out)


def test_a_digit_aims_at_its_option_and_enter_opens_it(keys, capsys):
    """A number moves to its line without opening it: Enter decides, so what is
    about to open is always in view."""
    keys(["3", keyboard.ENTER])
    assert interactive.screen._menu("", THREE) == "third"
    assert "third option" in _highlighted(capsys.readouterr().out)


def test_a_provider_then_its_model_are_chosen_by_keys(keys, monkeypatch, capsys):
    """The arrows reach the provider, then its list filters as one types."""
    from kotogen import catalogue

    monkeypatch.setenv("OPENAI_API_KEY", "sk-oa-test")
    monkeypatch.setattr(catalogue, "served", lambda provider, key, *, timeout=10:
                        catalogue.Catalogue([{"id": "gpt-new", "name": ""},
                                             {"id": "o-new", "name": ""}], 1.0))
    keys([keyboard.DOWN, keyboard.DOWN, keyboard.ENTER, "o", keyboard.ENTER])
    interactive.models._choose_model()
    assert os.environ["KOTOGEN_PROVIDER"] == "openai"
    assert os.environ["KOTOGEN_MODEL"] == "o-new"
    assert "Models openai serves to your key: 2." in capsys.readouterr().out


# ── Searchable lists ──────────────────────────────────────────────────────────
# Typing narrows a long list, in Japanese, in rōmaji or in the language of the gloss.

# The glosses as the JLPT grammar table gives them on an English screen.
RULES = [
    ("でも", "N4  でも      Or something, any (with a question word)"),
    ("やすい", "N4  やすい     Easy to, prone to"),
    ("にくい", "N4  にくい     Hard to, difficult to"),
]


def test_typing_filters_the_list(keys, capsys):
    """"diffi" leaves nothing but にくい, and Enter ticks it."""
    keys(list("diffi") + [keyboard.ENTER])
    assert interactive.lists._tickable_pages("N4", RULES) == ["にくい"]
    screen = _plain(capsys.readouterr().out)
    assert "Search: diffi" in screen
    assert "1 of 3" in screen


def test_romaji_finds_the_japanese(keys, capsys):
    """"niku" is enough without a Japanese keyboard."""
    keys(list("niku") + [keyboard.ENTER])
    assert interactive.lists._tickable_pages("N4", RULES) == ["にくい"]


def test_the_japanese_can_be_typed_as_it_is_too(keys):
    keys(["に", "く", keyboard.ENTER])
    assert interactive.lists._tickable_pages("N4", RULES) == ["にくい"]


def test_wiping_the_search_gives_the_whole_list_back(keys, capsys):
    """Backspace undoes the typing, Escape empties it at once; only then does
    Escape leave."""
    keys(list("niku") + [keyboard.BACKSPACE] * 4 + [" ", keyboard.ENTER])
    assert interactive.lists._tickable_pages("N4", RULES) == ["でも"]


def test_escape_wipes_the_search_before_coming_back_out(keys):
    keys(list("niku") + [keyboard.ESC, " ", keyboard.ENTER])
    # The search emptied, the aim starts again at the head of the whole list.
    assert interactive.lists._tickable_pages("N4", RULES) == ["でも"]


def test_a_search_with_no_result_leaves_the_screen_as_it_is(keys):
    """Nothing disappears on a typo: the previous list holds."""
    keys(list("zzz") + [" ", keyboard.ENTER])
    assert interactive.lists._tickable_pages("N4", RULES) == ["でも"]


def test_the_boxes_survive_the_filter(keys):
    """Tick, filter, tick elsewhere: both leave together."""
    keys([" "] + list("niku") + [" ", keyboard.ENTER])
    assert interactive.lists._tickable_pages("N4", RULES) == ["でも", "にくい"]


def test_the_digits_still_aim_in_a_searchable_list(keys):
    """A search is typed in letters, so digits still aim."""
    keys(["2", " ", keyboard.ENTER])
    assert interactive.lists._tickable_pages("N4", RULES) == ["やすい"]


def test_a_language_is_found_by_its_name(keys, capsys):
    """The two language lists are searched like the rules: "fran" is French."""
    keys(list("fran") + [keyboard.ENTER])
    assert interactive.settings_menu._pick_language(["en", "fr"], i18n.language_name,
                                      "en") == "fr"
    assert "Search: fran" in _plain(capsys.readouterr().out)


def test_a_language_is_found_under_either_of_its_names(keys):
    """French is listed as `Français`; "french" and "francais" find it too."""
    for typed in ("french", "francais", "fr"):
        keys(list(typed) + [keyboard.ENTER])
        assert interactive.settings_menu._pick_language(["en", "fr"], i18n.language_name,
                                          "en") == "fr"


def test_escape_wipes_the_language_search_and_aims_at_the_current_one(keys):
    """Wiping the search is not choosing: the aim goes back where it opened."""
    keys(list("eng") + [keyboard.ESC, keyboard.ENTER])
    assert interactive.settings_menu._pick_language(["en", "fr"], i18n.language_name,
                                      "fr") == "fr"


# ── Two-digit numbers ─────────────────────────────────────────────────────────
# Past nine options, a "1" may start "14": the pause between the keys tells them
# apart. A number only aims, so a misread one breaks nothing.

def _long_list() -> list[tuple[str, str]]:
    """Twenty options, like the menu of the podcasts."""
    return [(f"o{n}", f"option {n}") for n in range(1, 21)]


def _long_menu(keys, pressed: list[str]) -> str:
    keys([*pressed, keyboard.ENTER])
    return interactive.screen._menu("A long list", _long_list())


def test_two_digits_reach_an_option_past_the_ninth(keys):
    """"20" aims at the twentieth option: the second digit extends the first
    instead of replacing it."""
    assert _long_menu(keys, ["2", "0"]) == "o20"


def test_a_second_digit_that_leads_nowhere_starts_over(keys):
    """"25" does not exist in a list of twenty: the "5" starts over and aims at
    the fifth."""
    assert _long_menu(keys, ["2", "5"]) == "o5"


def test_a_number_is_dropped_by_any_other_key(keys):
    """The arrow ends the number in hand: the "4" after it does not make "14"."""
    assert _long_menu(keys, ["1", keyboard.DOWN, "4"]) == "o4"


def test_a_pause_between_two_digits_starts_a_new_number(keys, monkeypatch):
    """The pause tells a number typed in one go from two aims: without it, "1"
    then "2" would always make "12"."""
    keys(["1", "2", keyboard.ENTER])
    # The typing stops after the "1": the delay goes by with nothing coming.
    monkeypatch.setattr(keyboard, "pending", lambda timeout=0.0: False)
    assert interactive.screen._menu("A long list", _long_list()) == "o2"


def test_nothing_opens_on_a_digit_alone(keys):
    """Nothing starts from an aiming key: a number typed awry launches nothing."""
    keys(["7", "3", keyboard.ENTER])
    assert interactive.screen._menu("A long list", _long_list()) == "o3"


# ── The tick-box menus ────────────────────────────────────────────────────────
# The lists of works (the books of a level, the articles of a feed) hand back a
# list of keys: Space ticks, Enter validates. With no box ticked they behave like
# any other menu.

def _works() -> list[tuple[str, str]]:
    return [("a", "first"), ("b", "second"), ("c", "third")]


def _to_tick(keys, pressed: list[str], **kwargs):
    keys([*pressed, keyboard.ENTER])
    return interactive.screen._menu("Three works", _works(), multi=True, **kwargs)


def test_space_ticks_and_enter_validates_the_boxes(keys):
    assert _to_tick(keys, [" ", keyboard.DOWN, " "]) == ["a", "b"]


def test_a_tick_menu_with_no_box_takes_the_line_aimed_at(keys):
    """Without Space, one work is chosen as in any other menu."""
    assert _to_tick(keys, [keyboard.DOWN]) == ["b"]


def test_a_box_laid_down_awry_is_taken_up_in_the_same_place(keys):
    """Space toggles without moving the cursor, so a box is unticked where it was
    ticked."""
    assert _to_tick(keys, [" ", " ", keyboard.DOWN, " "]) == ["b"]


def test_the_boxes_show_in_the_list(keys, capsys):
    """Every label has its box ahead of it, ticked or not, so the column holds."""
    assert _to_tick(keys, [" ", keyboard.DOWN]) == ["a"]
    lines = [line.strip() for line in _plain(capsys.readouterr().out).splitlines()]
    assert "1. [x] first" in lines
    assert "3. [ ] third" in lines


def test_an_action_leaves_with_the_boxes(keys):
    """"See the next ones" comes back after the boxes, so a paged list turns
    without losing them."""
    assert _to_tick(keys, [" ", keyboard.END],
                    extras=[("n", "See the next ones")]) == ["a", "n"]


def test_the_boxes_of_another_page_are_part_of_the_choice(keys):
    """They are not on the screen, and yet they are works that have been kept."""
    assert _to_tick(keys, [keyboard.DOWN, " "], checked={"z"}) == ["b", "z"]


def test_the_menu_footer_counts_the_boxes(keys, capsys):
    """The count covers every box, not only the screen's: on a second page it
    alone says that those of the first still hold."""
    _to_tick(keys, [" ", keyboard.DOWN, " "], allow_back=True)
    out = capsys.readouterr().out
    assert "Space to tick, Escape to go back - 2 ticked" in out
    # With nothing ticked the footer gives only the gesture.
    assert "0 ticked" not in out


def test_several_numbers_typed_stand_for_several_boxes(monkeypatch, capsys):
    """Without a terminal there is no Space key: numbers separated by spaces tick
    several, and the list says so."""
    feed(monkeypatch, ["1 3"])
    assert interactive.screen._menu("Three works", _works(), multi=True) == ["a", "c"]
    assert "Several at once" in capsys.readouterr().out


def test_a_number_typed_with_a_letter_ticks_then_acts(monkeypatch):
    """"1 n": without Space, the only way to carry boxes to the next screen."""
    feed(monkeypatch, ["1 n"])
    assert interactive.screen._menu("Three works", _works(), multi=True,
                             extras=[("n", "See the next ones")]) == ["a", "n"]


def test_a_dialog_closed_on_a_menu_leaves_a_single_blank_line(keys, monkeypatch, capsys):
    """A menu already leaves a blank line behind it; the end of the dialogue adds
    no second one."""
    console.watch()   # like `cli.main()`: it is what reads the output
    keys(["6", keyboard.ENTER, "1", keyboard.ENTER])
    assert interactive_argv() == ["maintain", "--scan"]
    out = _plain(capsys.readouterr().out)
    assert out.endswith("\n\n") and not out.endswith("\n\n\n")


# ── What was typed in advance ─────────────────────────────────────────────────
# An Enter typed ahead waits in the queue of the terminal and reaches the next
# screen unseen: it validates nothing there, and crosses no pause.

def test_an_enter_typed_in_advance_validates_nothing(keys, monkeypatch):
    """An Enter already queued when the menu opens is ignored; the arrow and the
    Enter typed afterwards decide as usual."""
    keys([keyboard.ENTER, keyboard.DOWN, keyboard.ENTER])
    queued = iter([True, False])
    monkeypatch.setattr(keyboard, "pending", lambda timeout=0.0: next(queued, False))
    assert interactive.screen._menu("", THREE) == "second"


def test_the_pause_only_opens_on_a_key_typed_after_it(monkeypatch):
    """The queue is drained first, or an Enter typed ahead would cross the pause
    and scroll the output away unread."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    drained = []
    monkeypatch.setattr(keyboard, "drain", lambda: drained.append(True))
    feed(monkeypatch, [""])
    interactive.screen._pause("Enter to come back to the menu...")
    assert drained


def test_the_pause_copies_the_command_and_stays_open(monkeypatch, capsys):
    """"c" copies and the pause reopens: copying comes before going back to the
    menu."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(keyboard, "drain", lambda: None)
    copies = []
    monkeypatch.setattr(system, "copy",
                        lambda text: copies.append(text) or "xclip")
    feed(monkeypatch, ["c", ""])
    interactive.screen._pause("Enter to come back...", to_copy="kotogen vocab 食べる")

    assert copies == ["kotogen vocab 食べる"]
    out = capsys.readouterr().out
    assert "Command copied (xclip)." in out
    assert out.count("Enter to come back...") == 2   # reopened after the copy


def test_the_pause_without_anything_to_copy_ignores_the_key(monkeypatch):
    """With no `to_copy`, "c" is an answer like any other, and the pause closes."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(keyboard, "drain", lambda: None)
    feed(monkeypatch, ["c"])   # one answer only: a second read would raise
    interactive.screen._pause("Enter to come back...")


def test_a_copy_says_only_what_it_knows():
    """Three facts, three sentences: a utility answered, the terminal was sent a
    sequence, or nothing was there."""
    assert "(xclip)" in interactive.screen._copy_report("xclip")
    assert "OSC 52" in interactive.screen._copy_report(system.OSC52)
    assert "check before pasting" in interactive.screen._copy_report(
        system.OSC52)
    assert "unavailable" in interactive.screen._copy_report("")


def _painted(out: str) -> list[tuple[int, int]]:
    """For every redraw: (lines announced, lines actually written).

    A block climbs back up the lines it announced (`\\033[nA`) to redraw itself."""
    blocks = out.split("\033[J")[:-1]
    counted = []
    for block in blocks:
        up = re.search(r"\033\[(\d+)A", block)
        counted.append((int(up.group(1)) if up else 0, block.count("\n")))
    # The first block climbs back up nothing, so there is nothing to check.
    return [(up, written) for up, written in counted if up]


def _assert_never_overflows(out: str) -> None:
    """No redraw writes more lines than it climbed back up.

    One line more pushes the block down a line at every key until the screen
    scrolls. Fewer is fine: `\\033[J` wipes the freed line (the last pass drops the
    "Escape to go back" hint), and `menu.repaint` announces what it just wrote.
    """
    painted = _painted(out)
    assert painted, "no redraw observed: the test checks nothing"
    assert all(written <= up for up, written in painted)


def test_a_redrawn_menu_never_writes_past_what_it_climbs_back(keys, capsys):
    """A title of several lines is counted whole, and each entry fits on one line
    whatever it is passed, or the menu creeps down at every arrow."""
    keys([keyboard.DOWN, keyboard.DOWN, keyboard.ENTER])
    interactive.screen._menu("\nA title\non three\nlines",
                      [("a", "first"), ("b", "second")])
    _assert_never_overflows(capsys.readouterr().out)


def test_a_japanese_label_is_measured_in_screen_columns(keys, monkeypatch,
                                                        capsys):
    """A line is truncated in screen columns, not in characters.

    "〜てください" is six characters for twelve columns: counted in characters,
    the line would wrap and its highlight bar take two lines."""
    keys([keyboard.DOWN, keyboard.ENTER])
    monkeypatch.setenv("COLUMNS", "40")
    interactive.screen._menu("Grammar cards", [
        ("a", "One precise rule  e.g. 〜てください, のに"),
        ("b", "NHK Easy articles"),
    ])
    out = capsys.readouterr().out
    _assert_never_overflows(out)
    assert all(console.width(line) < 40
               for line in _plain(out).split("\n"))


def test_a_menu_taller_than_the_window_falls_back_to_typing(
        keys, monkeypatch, capsys):
    """The redraw cannot climb back higher than the screen.

    A menu taller than the window would creep down at every key, so it falls back
    on the numbered entry, which has nothing to climb back up."""
    keys([keyboard.ENTER])           # no key will be read
    monkeypatch.setenv("LINES", "24")
    feed(monkeypatch, ["3"])
    assert interactive.screen._menu("", [(f"o{n}", f"option {n}")
                                  for n in range(30)]) == "o2"
    out = capsys.readouterr().out
    assert not _painted(out) and "\033[7m" not in out


def test_the_escape_hint_does_not_survive_the_choice(keys, capsys):
    """After a choice, "b" goes back, not Escape, so the hint goes; its blank line
    stays, to set the next question apart from the list."""
    keys([keyboard.ENTER])
    interactive.screen._menu("A title", [("a", "first"), ("b", "second")],
                      allow_back=True)

    screens = capsys.readouterr().out.split("\033[J")[:-1]
    assert any("Escape to go back" in screen for screen in screens[:-1])
    assert "Escape to go back" not in screens[-1]
    assert screens[-1].endswith("\r\033[K\n")  # the blank line it carried


def test_the_free_model_entry_asks_its_provider_by_key(keys, monkeypatch, capsys):
    """Free entry by keys: the provider is chosen with the arrows, then the name
    of the model is typed."""
    keys(["a", keyboard.ENTER, keyboard.DOWN, keyboard.DOWN, keyboard.ENTER])
    feed(monkeypatch, ["studio/model-b"])
    interactive.models._choose_model()
    assert os.environ["KOTOGEN_PROVIDER"] == "openrouter"
    assert os.environ["KOTOGEN_MODEL"] == "studio/model-b"
    out = capsys.readouterr().out
    assert "At which provider?" in out
    # The menu of the providers starts from a clean screen, like the others.
    assert out.count(BANNER) == 2
    _assert_never_overflows(out)


def test_a_digit_is_a_move_like_any_other(keys, monkeypatch, capsys):
    """The number aims, the arrow corrects, Enter opens."""
    keys(["1", keyboard.DOWN, keyboard.ENTER])
    chosen = interactive.screen._menu("", [(str(n), f"option {n}") for n in range(12)])
    assert chosen == "1"
    out = capsys.readouterr().out
    # A redraw proves the keys were in use.
    assert _painted(out)
    # No key hint: arrows and Enter are common to every screen, and this menu has
    # no way back.
    assert "to validate" not in out
    assert "Escape" not in out


def test_a_letter_shortcut_also_waits_for_enter(keys, monkeypatch, capsys):
    """A letter typed awry only moves the selection: it sets off nothing."""
    keys(["a", keyboard.ESC])
    interactive.models._choose_model()
    assert os.environ["KOTOGEN_MODEL"] == MODEL
    assert "free entry" in _highlighted(capsys.readouterr().out)


def test_escape_goes_back(keys):
    keys([keyboard.ESC])
    interactive.models._choose_model()
    assert os.environ["KOTOGEN_MODEL"] == MODEL


def test_escape_on_the_settings_screen_returns_to_the_menu(keys, capsys):
    """By keys, "s" then Enter opens the settings, and Escape goes back to the
    menu."""
    keys(["s", keyboard.ENTER, keyboard.ESC, "q", keyboard.ENTER])
    assert interactive_argv() is None
    out = capsys.readouterr().out
    assert "Settings" in out and "API key" in out
    _assert_never_overflows(out)


def test_the_settings_screen_stays_open_between_two_changes(monkeypatch):
    """The screen does not close after one change, so two changes take one trip."""
    feed(monkeypatch, ["s", "s", "v", "b", "q"])
    assert interactive_argv() is None
    assert prefs.auto_send() is True
    assert prefs.verbose() is True


def test_the_settings_screen_reopens_on_the_setting_just_changed(keys, capsys):
    """The screen reopens on the setting just changed, not at the top: the second
    press, an Enter alone, proves the selection stayed."""
    keys(["q", keyboard.ENTER, keyboard.ENTER, keyboard.ESC])
    interactive.settings_menu._settings()
    assert audio_quality.code() == "medium"
    assert "Audio compression" in _highlighted(capsys.readouterr().out)


def test_the_menu_reopens_on_the_line_it_was_left(keys, capsys):
    """The same at the main menu: coming back from the settings reopens the list
    on "Settings"."""
    keys(["s", keyboard.ENTER, keyboard.ESC, keyboard.ENTER, keyboard.ESC,
          "q", keyboard.ENTER])
    assert interactive_argv() is None
    out = capsys.readouterr().out
    # Back on "Settings", the next Enter reopens the screen without aiming again;
    # a selection back at the top would have opened the first command.
    assert "API key" in out
    assert "Vocabulary cards" not in out
    _assert_never_overflows(out)
