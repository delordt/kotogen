"""The breathing line: one empty line separates two blocks, it never opens one.

Two blocks that know nothing of each other (two menus, a dialogue and the
command it launches) must not each lay a leading "\\n": never two empty lines
in a row. The watcher is installed in the test body, not in a fixture: pytest's
capture reinstalls `sys.stdout` between setup and call, which would remove it.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

from kotogen import console, keyboard

SRC = Path(__file__).resolve().parents[1] / "src" / "kotogen"


def screen() -> None:
    """A blank screen, watched: what follows is what the screen would get."""
    console.watch()


def shown(capsys) -> str:
    """The output as it reads: without what only drives the screen."""
    out = capsys.readouterr().out
    return re.sub(r"\033\[[0-9;?]*[ -/]*[@-~]", "", out).replace("\r", "")


def final_screen(capsys) -> list[str]:
    """What is LEFT on the screen, carriage returns applied as a terminal would.

    Each "\\r" goes back to the start of the line and what follows overwrites
    it: read flat, an animated line holds every one of its redraws.
    """
    out = re.sub(r"\033\[[0-9;?]*[ -/]*[@-~]", "", capsys.readouterr().out)
    lines = []
    for raw in out.split("\n"):
        line = ""
        for part in raw.split("\r"):
            line = part + line[len(part):]
        lines.append(line.rstrip())
    return lines


# ── The decision ──────────────────────────────────────────────────────────────

def test_the_breathing_line_is_owed_after_a_line_of_text(capsys):
    screen()
    print("a question put")
    console.space()
    print("the next block")
    assert shown(capsys) == "a question put\n\nthe next block\n"


def test_the_breathing_line_is_not_owed_after_an_empty_line(capsys):
    screen()
    print("a menu left\n")
    console.space()
    print("the next block")
    assert shown(capsys) == "a menu left\n\nthe next block\n"


def test_two_breathing_lines_in_a_row_make_only_one(capsys):
    """The dialogue closes on a breathing line and the command it launches
    opens on its own, each unaware of the other."""
    screen()
    print("last answer")
    console.space()   # end of the dialogue
    console.space()   # head of the command
    print("[1/2] first source")
    assert shown(capsys) == "last answer\n\n[1/2] first source\n"


def test_what_erases_itself_does_not_decide_the_breathing_line(capsys):
    """A spinner writes a waiting line, then erases it and moves the cursor back
    up. The spaces of the erasing must not count as text, or the next block
    would lay one more breathing line."""
    screen()
    print("a menu left\n")
    with console.leaving_no_trace():
        print()
        print("\rwaiting…", end="")
        print("\r         \r", end="")
        print("\033[A", end="")
    console.space()
    print("the next block")
    # `space()` writes nothing: the menu's empty line is still the last one.
    assert shown(capsys) == "a menu left\n\n\nwaiting…         the next block\n"


def test_leaving_no_trace_does_not_touch_the_output(capsys):
    """It restores the watcher's memory only: nothing written is swallowed."""
    screen()
    with console.leaving_no_trace():
        print("visible all the same")
    assert shown(capsys) == "visible all the same\n"


# ── The step that holds on one line ───────────────────────────────────────────

def test_the_beats_of_a_step_hold_on_one_line(capsys):
    """The name of the text, the announcement of the call, what came out of it:
    three beats learnt one after the other, a single line on the screen."""
    screen()
    console.open_line("[1/4]")
    console.extend("駅前に新しい図書館ができた - 5 line(s)", sep=" ")
    console.extend("Generating the cards…")
    console.close_line("2 card(s)")
    assert shown(capsys) == ("[1/4] 駅前に新しい図書館ができた - 5 line(s)"
                            " - Generating the cards… - 2 card(s)\n")


def test_a_line_that_was_cut_is_given_back_whole(capsys):
    """The AI client writes a retry after the open line; the outcome then goes
    on a copy of the whole line rather than after the retry."""
    screen()
    console.open_line("   [1/3] Generating the cards…")
    print("   HTTP 429, retrying in 5s…")
    console.close_line("2 card(s)")
    assert shown(capsys) == (
        "   [1/3] Generating the cards…   HTTP 429, retrying in 5s…\n"
        "   [1/3] Generating the cards… - 2 card(s)\n")


def test_a_dropped_line_leaves_the_screen_as_it_found_it(monkeypatch, capsys):
    """A wait closed on nothing only said the program was alive: it is erased,
    and what follows writes from the start of the same line."""
    screen()
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    print("a block above")
    console.action("Thinking")
    console.drop_line()
    console.item("5 notes")
    assert [line for line in final_screen(capsys) if line] == ["a block above",
                                                              "   5 notes"]


def test_a_dropped_line_hands_the_breathing_line_back_its_memory(monkeypatch, capsys):
    """The erasing writes spaces: read as text, they would make the next block
    lay a second breathing line."""
    screen()
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    print("a block that ends\n")
    console.action("Thinking")
    console.drop_line()
    console.space()
    print("the next block")
    assert final_screen(capsys) == ["a block that ends", "", "the next block", ""]


def test_a_line_nobody_can_erase_is_closed_rather_than_dropped(capsys):
    """A redirected output cannot erase what it wrote: the wait stays, a useful
    trace in a log."""
    screen()
    console.action("Thinking")
    console.drop_line()
    console.item("5 notes")
    assert shown(capsys) == "   Thinking…\n   5 notes\n"


def test_a_line_something_has_written_under_is_no_longer_ours_to_erase(monkeypatch,
                                                                       capsys):
    """Once the AI client has written a retry after the open line, erasing there
    would take the retry away."""
    screen()
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    console.action("Thinking")
    console.failed("HTTP 429")
    console.drop_line()
    assert [line for line in final_screen(capsys) if line] == ["   Thinking…"]


def test_closing_with_no_line_open_writes_nothing(capsys):
    """A caller closes before its block without checking that a line is open."""
    screen()
    console.close_line()
    console.close_line("2 card(s)")
    assert shown(capsys) == ""


def test_a_step_does_not_open_another_over_it(capsys):
    """The next passage gets its own line; the one before is finished."""
    screen()
    console.open_line("   [1/2] Generating the cards…")
    console.open_line("   [2/2] Generating the cards…")
    console.close_line()
    assert shown(capsys) == ("   [1/2] Generating the cards…\n"
                            "   [2/2] Generating the cards…\n")


def test_the_breathing_line_closes_the_step_before_separating(capsys):
    """The block before a breathing line cannot still be under way."""
    screen()
    console.open_line("[1/1] a text")
    console.space()
    print("the next block")
    assert shown(capsys) == "[1/1] a text\n\nthe next block\n"


def test_an_output_does_not_open_on_emptiness(capsys):
    # Nothing written yet counts as an empty screen: no gap at the head.
    screen()
    console.space()
    print("[1/1] source")
    assert shown(capsys) == "[1/1] source\n"


def test_a_cleared_screen_starts_again_from_nothing(capsys):
    screen()
    print("a whole menu")
    print("\033[H\033[2J\033[3J", end="")
    console.space()
    print("the banner")
    assert shown(capsys) == "a whole menu\nthe banner\n"


def test_the_typed_return_finishes_the_line(capsys, monkeypatch):
    """The terminal, not `sys.stdout`, echoes the Return key.

    Uncounted, it leaves the dialogue's last question looking unfinished, and
    the breathing lines of the dialogue and of the command would add up."""
    screen()
    monkeypatch.setattr("builtins.input", lambda: "y")
    print("Send the cards to Anki too (y/n) [n]: ", end="")
    assert console.read_line() == "y"
    console.space()   # end of the dialogue
    console.space()   # head of the command
    print("[1/1] 14.mp3")
    # The echo's line break is missing from the capture (the terminal writes
    # it): what counts is a single empty line after it, not two.
    assert shown(capsys) == "Send the cards to Anki too (y/n) [n]: \n[1/1] 14.mp3\n"


# ── The shape of the work ─────────────────────────────────────────────────────
# Three forms: a source and what it carries, an action and its result, a rank
# and what is done to it. The shape depends NEITHER on the source NOR on what
# happened inside it.

def test_a_source_lists_what_it_carries(capsys):
    screen()
    console.title("NHK ラジオニュース")
    console.action("Reading the feed")
    console.done("3 episodes, 12 already handled")
    console.items(["ep 1", "ep 2"])
    assert shown(capsys) == ("NHK ラジオニュース\n"
                             "   Reading the feed… (3 episodes, 12 already handled)\n"
                             "   ep 1\n"
                             "   ep 2\n")


def test_a_long_list_cuts_itself_short(capsys):
    """Items past the first few add nothing to read."""
    screen()
    console.items([f"ep {n}" for n in range(1, 12)], maximum=3)
    assert shown(capsys).splitlines()[-1] == "   ... and 8 more"


def test_a_single_one_left_is_not_said_in_the_plural(capsys):
    screen()
    console.items(["a", "b", "c", "d"], maximum=3)
    assert shown(capsys).splitlines()[-1] == "   ... and 1 more"


def test_an_action_with_no_result_closes_on_its_label(capsys):
    """"(ok)" would add nothing: the label alone says the action took place."""
    screen()
    console.action("Loading the article")
    console.done()
    assert shown(capsys) == "   Loading the article…\n"


def test_what_locates_the_action_holds_inside_its_label(capsys):
    """There are only two levels of indent: the place of a passage in its
    collection goes inside the label, not on a third level."""
    screen()
    console.action("Generating the cards", among="passage 3/6, 00:12 → 01:30")
    console.done("3 cards")
    assert shown(capsys) == ("   Generating the cards "
                            "(passage 3/6, 00:12 → 01:30)… (3 cards)\n")


def test_a_shared_action_stands_apart_from_the_list(capsys):
    """In the margin, and separated: stuck to the list before it, it would pass
    for its last item."""
    screen()
    console.title("Remote documents")
    console.items(["https://tadoku.org/japanese/book/41209/"])
    console.action("Downloading", margin=True)
    console.done("1 document, 2.1 MB")
    assert shown(capsys) == ("Remote documents\n"
                             "   https://tadoku.org/japanese/book/41209/\n"
                             "\n"
                             "Downloading… (1 document, 2.1 MB)\n")


def test_an_aside_does_not_close_the_action_which_completes_all_the_same(capsys):
    """An aside cuts the generation line, which is then written again whole
    rather than gluing its count to the aside."""
    screen()
    console.action("Generating the cards")
    console.aside("12 cards given back for a ceiling of 8")
    console.done("8 cards")
    assert shown(capsys) == ("   Generating the cards…\n"
                             "   ! 12 cards given back for a ceiling of 8\n"
                             "   Generating the cards… (8 cards)\n")


def test_a_failure_leaves_the_action_open_behind_it(capsys):
    """A failed action has no result to reopen its label on."""
    screen()
    console.rank(2, 3, "ne2026083012345")
    console.action("Loading the article")
    console.failed("text not found")
    console.rank(3, 3, "ne2026083012346")
    assert shown(capsys) == ("[2/3] ne2026083012345\n"
                             "   Loading the article…\n"
                             "\n"
                             "[3/3] ne2026083012346\n")


def test_the_shape_holds_with_no_watcher(capsys):
    """A redirected output (a CI log, a `> output.txt`) cannot be read back:
    what the console writes itself under an action, it KNOWS about."""
    # No `screen()`: the output is not watched.
    console._step, console._cut = None, False
    console.action("Generating the cards")
    console.aside("one entry ignored")
    console.done("2 cards")
    assert shown(capsys).splitlines() == [
        "   Generating the cards…",
        "   ! one entry ignored",
        "   Generating the cards… (2 cards)",
    ]


def test_a_weight_reads_in_its_own_unit():
    assert console.size(412 * 1024) == "412 KB"
    assert console.size(2_200_000) == "2.1 MB"
    # A Whisper model's weights: "1.4 GB", not "1457.3 MB".
    assert console.size(1_527_000_000) == "1.4 GB"
    # "0 KB" would read as "empty": a file that exists weighs at least 1 KB.
    assert console.size(300) == "1 KB"
    # An absent file counts as nothing rather than failing the measure.
    assert console.size_of([Path("nowhere.mp3")]) == "0 KB"


def test_agreement_avoids_the_forgotten_plural():
    assert console.plural(1, "passage") == "passage"
    assert console.plural(2, "passage") == "passages"
    assert console.plural(2, "person", "people") == "people"


def test_the_reason_of_a_failure_stops_at_its_first_line():
    """The message of `chat_json` carries the model's raw answer below its
    sentence: only the sentence is kept."""
    exc = ValueError(
        "The AI did not return valid JSON.\n\n"
        'Raw answer:\n```json\n{"cards": [食べ終わったら')
    assert console.reason(exc) == "The AI did not return valid JSON."


def test_a_reason_longer_than_the_line_is_truncated():
    assert console.reason("a" * 80).endswith("…")
    assert len(console.reason("a" * 80)) == 60
    assert console.reason("timed out") == "timed out"

# ── The secret in stars ───────────────────────────────────────────────────────

def typing(*keys: str):
    """Replays keys one by one, as `keyboard.read_key` returns them."""
    left = list(keys)
    return lambda: left.pop(0)


def test_one_star_per_character_and_the_input_is_given_back(capsys):
    """Unlike with `getpass`, the user sees that something was typed."""
    screen()
    assert console._stars(typing("s", "k", "-", keyboard.ENTER)) == "sk-"
    assert shown(capsys) == "***\n"


def test_a_backspace_takes_the_star_away_with_the_character(capsys):
    screen()
    assert console._stars(typing("s", "j", keyboard.BACKSPACE, "k",
                                 keyboard.ENTER)) == "sk"
    assert shown(capsys) == "**\b \b*\n"


def test_a_backspace_on_nothing_does_not_erase_the_prompt(capsys):
    """Otherwise the cursor would go back into the prompt."""
    screen()
    assert console._stars(typing(keyboard.BACKSPACE, "k", keyboard.ENTER)) == "k"
    assert shown(capsys) == "*\n"


def test_the_special_keys_do_not_fall_into_the_secret():
    """A stray arrow must not end up in the key."""
    assert console._stars(typing("s", keyboard.UP, "k", keyboard.ENTER)) == "sk"


def test_escape_cancels_the_masked_input():
    """Like a line left empty: the caller has only one case to handle."""
    assert console._stars(typing("s", "k", keyboard.ESC)) == ""


def test_after_the_stars_the_breathing_line_lays_only_one_line(capsys):
    """The echo is ours this time: the watcher sees the line finished."""
    screen()
    console._stars(typing("k", keyboard.ENTER))
    console.space()
    print("Key …sk-9 kept")
    assert shown(capsys) == "*\n\nKey …sk-9 kept\n"


# ── A line one can leave with Escape ──────────────────────────────────────────
# `input()` never hears Escape on Windows: the console keeps it to erase the
# line. A question with a way back reads its answer key by key instead.

def test_a_line_is_typed_and_echoed(capsys):
    screen()
    assert console._line(typing("2", "0", keyboard.ENTER)) == "20"
    assert shown(capsys) == "20\n"


def test_escape_on_an_empty_line_goes_back(capsys):
    screen()
    assert console._line(typing(keyboard.ESC)) is None
    assert shown(capsys) == "\n"


def test_escape_on_a_typed_line_erases_it_first():
    """As in the Windows console: a first Escape erases the line, so a slip does
    not lose a pasted URL, and a second goes back."""
    assert console._line(typing("h", "t", keyboard.ESC, "5", keyboard.ENTER)) == "5"
    assert console._line(typing("h", "t", keyboard.ESC, keyboard.ESC)) is None


def test_a_backspace_takes_back_the_two_columns_of_a_kanji(capsys):
    screen()
    assert console._line(typing("食", "べ", keyboard.BACKSPACE, keyboard.BACKSPACE,
                                "猫", keyboard.ENTER)) == "猫"
    assert shown(capsys) == "食べ\b\b  \b\b\b\b  \b\b猫\n"


def test_the_special_keys_do_not_fall_into_the_line():
    assert console._line(typing("1", keyboard.LEFT, "2", keyboard.ENTER)) == "12"


# ── What the watcher reads ────────────────────────────────────────────────────

def test_the_ansi_sequences_do_not_count_as_text(capsys):
    """A menu's last line, empty, is written "\\r\\033[K\\n": counted as text,
    it would make the next menu lay a second breathing line."""
    screen()
    print("a menu")
    sys.stdout.write("\r\033[K\n")   # the empty line a menu leaves on exit
    sys.stdout.write("\033[J")
    console.space()
    print("the next menu")
    assert shown(capsys) == "a menu\n\nthe next menu\n"


def test_the_watcher_lets_through_what_it_watches(capsys):
    # A watcher that swallowed an empty line would falsify the menu's redraw
    # count, and the menu would move down a line on every key.
    screen()
    print("a\n\n\nb", end="")
    assert capsys.readouterr().out == "a\n\n\nb"


def test_the_rest_of_the_stream_goes_through_the_wrapper():
    screen()
    # What the wrapper does not define comes from the stream it watches.
    assert sys.stdout.isatty() in (True, False)
    assert sys.stdout.write("") == 0


# ── No breathing line written by hand ─────────────────────────────────────────

# What is written by hand on purpose, and why.
TOLERATED = {
    # The margin above the banner: the screen was just cleared.
    ("screen.py", 'print(f"\\n{BANNER}")'),
}

# `print("\n".join(...))` and `print("\n" + ...)` assemble a block, they do
# not open on emptiness: the "\n" there is an internal separator.
ASSEMBLY = re.compile(r'print\(f?"\\n(?:"\.join|" \+ )')


def _hand_written_breathing_lines() -> list[str]:
    guilty = []
    for path in sorted(SRC.rglob("*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            text = line.strip()
            if not re.match(r'print\(f?"\\n', text) or ASSEMBLY.match(text):
                continue
            # stderr is not watched: its breathing line stays written by hand.
            if "sys.stderr" in text or (path.name, text) in TOLERATED:
                continue
            guilty.append(f"{path.name}:{n}  {text}")
    return guilty


def test_no_breathing_line_is_written_by_hand():
    """`print("\\n...")` decides a breathing line blind: only `console.space()`,
    which looks at the output, can decide."""
    assert _hand_written_breathing_lines() == []


# ── What escapes the watcher ──────────────────────────────────────────────────

def _direct_reads() -> list[str]:
    """The calls to `input()` anywhere but in `console.read_line()`.

    Read from the syntax tree, so prose that mentions `input()` is not reported.
    """
    guilty = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "console.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "input"):
                guilty.append(f"{path.name}:{node.lineno}")
    return guilty


def test_no_input_outside_console():
    """`input()` writes and reads behind the watcher's back.

    Its prompt goes to the C stdout (cp1252 on Windows consoles, which crashes
    on Japanese), and the terminal echoes the Return key, so the prompt line
    looks unfinished: only `console.read_line()` keeps that count.
    """
    assert _direct_reads() == []


def _secrets_read_elsewhere() -> list[str]:
    """The calls to `getpass` anywhere but in `console.read_secret()`."""
    guilty = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "console.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "getpass"):
                guilty.append(f"{path.name}:{node.lineno}")
    return guilty


def test_no_secret_typed_outside_console():
    """`getpass` shows nothing: a pasted key and a failed paste look alike.

    `console.read_secret()` shows the typing without making it readable, and
    holds the fallback on `getpass`."""
    assert _secrets_read_elsewhere() == []


# ── Display width ─────────────────────────────────────────────────────────────
# `青空朗読` takes eight columns for four characters: a column padded by `len`
# after it would shift by four against its Latin neighbours.

def test_a_japanese_character_takes_two_columns():
    assert console.width("青空朗読") == 8
    assert console.width("いろどり") == 8


def test_accented_latin_takes_one():
    # `Résumé` has to measure six: the "ambiguous" characters count for one, the
    # way terminals do outside an East Asian context.
    assert console.width("Résumé") == 6
    assert console.width("Articles NHK Easy") == 17


def test_a_mixed_label_is_measured_piece_by_piece():
    assert console.width("青空朗読 (N2-N1)") == 8 + len(" (N2-N1)")


def test_the_padding_counts_columns_and_not_characters():
    assert console.pad("青空朗読", 12) == "青空朗読    "
    assert console.pad("Résumé", 10) == "Résumé    "


def test_a_text_wider_than_the_column_overflows_without_truncating():
    assert console.pad("青空朗読", 4) == "青空朗読"


def test_a_combining_mark_takes_no_column():
    """A file name NFD wrote (macOS) spells `が` as `か` + U+3099, `é` as `e` +
    U+0301: the screen shows one character, and a column counted two would slip."""
    assert console.width("が") == console.width("が") == 2
    assert console.width("Résumé") == console.width("Résumé") == 6
    assert console.pad("Résumé", 8) == "Résumé  "


def test_an_error_that_says_nothing_is_named_by_its_kind():
    """`ConnectionError()` would otherwise leave "Interrupted: " with no reason."""
    assert console.reason(ConnectionError()) == "ConnectionError"
    assert console.reason("") == ""


# ── The wait that spins ───────────────────────────────────────────────────────
# A waiting line erases itself without a tail, and what is written while it
# spins stays free of spinner frames.

def test_cleaning_drops_what_drives_the_terminal_and_keeps_the_lines():
    """C0 but the line feed and the tab, DEL, C1: the Japanese and the accents stay."""
    text = "猫\u001b[2J\tcafé\r\u0007\u007f\u0085\u009b\nfin"
    assert console.clean(text) == "猫[2J\tcafé\nfin"


def test_the_lines_of_a_run_carry_no_terminal_control(capsys):
    """A feed's title or a page's name reaches the screen through these lines."""
    console.title("Feed\u001b]0;owned\u0007")
    console.rank(1, 2, "\u009b2J週末の予定")
    console.item("item\u001b[8m")
    console.aside("left\u001b[2K")
    console.failed("broken\u001b[1A")
    captured = capsys.readouterr()
    assert "\u001b" not in captured.out + captured.err
    assert "\u009b" not in captured.out
    assert "週末の予定" in captured.out


def test_a_duration_reads_like_a_watch():
    assert console.duration(0) == "00:00"
    assert console.duration(72) == "01:12"
    assert console.duration(3800) == "1:03:20"


def test_what_the_work_gives_back_comes_back_to_the_caller():
    assert console.while_working(lambda: 21 * 2) == 42


def test_what_the_work_raises_is_raised_in_the_same_place():
    import pytest

    def falls():
        raise ValueError("the real error, not one of translation")

    with pytest.raises(ValueError, match="the real error"):
        console.while_working(falls)


def test_a_wait_with_nothing_to_report_spins_and_writes_nothing_else(monkeypatch,
                                                                     capsys):
    """A model call cannot report progress, and the label names what is awaited:
    the frame is the label and the spinner, with no elapsed seconds."""
    import time

    screen()
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    console.action("Thinking")
    console.while_working(lambda: time.sleep(3 * console.SPINNER_PERIOD))
    console.done()

    # Carriage returns applied, the action is left closed on its label alone.
    assert [line for line in final_screen(capsys) if line.strip()] == [
        "   Thinking…"]


def test_the_wait_animates_nothing_outside_the_thread_holding_the_line(monkeypatch,
                                                                       capsys):
    """Six batches of AI calls in parallel would animate the same line six times
    a frame. Only the main thread animates it; the others work in silence."""
    import threading

    screen()
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    console.action("Generating the cards")
    inside: list = []
    thread = threading.Thread(
        target=lambda: inside.append(console.while_working(lambda: "done")))
    thread.start()
    thread.join()
    console.done("2 cards")

    assert inside == ["done"]
    assert shown(capsys).endswith("Generating the cards… (2 cards)\n")


def test_what_is_written_during_the_wait_does_not_cross_the_spinner(monkeypatch,
                                                                    capsys):
    """The animated line carries the label AND its spinner: what is written
    below must erase it first, or "Transcribing… ⠹" would head that line."""
    import time

    screen()
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    console.action("Transcribing")

    def work():
        time.sleep(3 * console.SPINNER_PERIOD)
        console.aside("one passage dropped")
        time.sleep(3 * console.SPINNER_PERIOD)

    console.while_working(work)
    console.done("14 lines")

    lines = [line for line in final_screen(capsys) if line.strip()]
    # The fact starts on a clean line, and the action closes whole below it.
    assert lines == ["   ! one passage dropped",
                     "   Transcribing… (14 lines)"]


# ── Ctrl+C during a wait ──────────────────────────────────────────────────────
# The work runs in a daemon thread that sleeps long past the interrupt: what is
# pinned is what the main thread does once Ctrl+C reaches it.

def _interrupted_wait(seconds: float = 5.0) -> float:
    """Ctrl+C a moment into a wait of `seconds`; hands back how long it took to land."""
    import _thread
    import threading
    import time

    import pytest

    threading.Timer(4 * console.SPINNER_PERIOD, _thread.interrupt_main).start()
    start = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        console.while_working(lambda: time.sleep(seconds))
    return time.monotonic() - start


def test_ctrl_c_during_the_spinner_leaves_no_frame_behind(monkeypatch, capsys):
    """A frame left on the line would make the next action's first detail erase
    that action's label along with it."""
    screen()
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    console.action("Backup")
    _interrupted_wait()
    assert console._animated_width == 0
    console.space()
    console.action("Loading the article")
    console.item("a detail")
    console.done("5 sentences")
    assert [line for line in final_screen(capsys) if line.strip()] == [
        "   Backup…", "   Loading the article…", "   a detail",
        "   Loading the article… (5 sentences)"]


def test_ctrl_c_is_heard_at_once_with_no_line_to_animate():
    """Outside a terminal the wait is not animated, and a bare `join` would hold
    the interrupt back on Windows until the paid call ends."""
    assert _interrupted_wait() < 2.5


def test_a_reason_is_cut_to_screen_columns_and_cleaned():
    cut = console.reason("猫" * 40, columns=20)
    assert console.width(cut) <= 20 and cut.endswith("…")
    assert "\x1b" not in console.reason("\x1b]0;title\x07the service is down")
