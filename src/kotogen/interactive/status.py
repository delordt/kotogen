"""What the main menu knows before anything is chosen.

Whether Anki answers and which note types it lacks (offered to be installed or
hidden), what each command still needs and the screen that says so, and the
status line: what will be called, and where the cards will land.
"""

from __future__ import annotations

import threading
from collections.abc import Collection

from kotogen import console, system
from kotogen.ai_client import TOOL_PROVIDERS, has_key, key_var
from kotogen.anki.connect import AnkiStatus, status as anki_status
from kotogen.cli import chosen_model, deck_config, default_provider, skipped_commands
from kotogen.i18n import _, quoted
from kotogen.interactive.models import model_label
from kotogen.interactive.screen import _PROBE_NOTICE_DELAY, _pause, _remember, _spin_while_alive

# Commands that produce cards, with the short label of the indicator. English,
# translated at display: `_()` at import would run before `cli.main()` loads the
# language.
CARD_COMMANDS = (
    ("kanji", "Kanji"),
    ("vocab", "Vocabulary"),
    ("grammar", "Grammar"),
    ("audio", "Listening"),
    ("reading", "Reading"),
)

# Main menu, in display order: (command, name, description). A None command is a
# subheading over the entries that follow it (an empty label: a blank line).
MAIN_MENU = (
    (None, "Make cards", ""),
    ("kanji", "Kanji", "the kanji of your words, a JLPT level or a text"),
    ("vocab", "Vocabulary", "words, a web page, a text file or a PDF"),
    ("grammar", "Grammar", "one rule, a JLPT level or a grammar page"),
    ("audio", "Listening", "multiple-choice comprehension on an audio"),
    ("reading", "Reading", "comprehension questions on a text"),
    (None, "Look after a deck", ""),
    ("maintain", "Corrections", "marked cards: flags, leeches"),
    ("deck", "Templates", "see your cards, set them, install them"),
    ("backup", "Backup", "snapshot of the deck, comparison, restore"),
)


def _probe_anki() -> AnkiStatus:
    """Questions AnkiConnect, saying so when the wait shows.

    Usually immediate, but a busy Anki (a sync) or a firewall that swallows the
    packets can make it last seconds.
    """
    result: list[AnkiStatus] = []
    probe = threading.Thread(target=lambda: result.append(anki_status(refresh=True)))
    probe.start()
    probe.join(_PROBE_NOTICE_DELAY)
    if probe.is_alive():
        _spin_while_alive(probe, _("Anki..."))
    return result[0] if result else AnkiStatus(connected=False)


def _missing_notetypes(state: AnkiStatus) -> dict[str, str]:
    """Commands whose note type is missing from Anki (command -> name expected).

    A missing deck is created at the send; a missing note type makes AnkiConnect
    refuse the notes, after the AI has been paid. Commands in `KOTOGEN_SKIP` are
    left out."""
    if not state.connected:
        return {}
    skipped = skipped_commands()
    return {command: notetype
            for command, _label in CARD_COMMANDS
            if command not in skipped
            and (notetype := deck_config(command)[1]) not in state.notetypes}


# Commands already offered for hiding in this session: the question is asked once,
# not at every return to the menu.
_skip_offered: set[str] = set()


def _offer_skip(missing: dict[str, str]) -> None:
    """Offers to install, or to hide, a command whose note type is missing.

    Installing runs `deck install` restricted to that type, so that no other type
    of the profile is asked about. Silent outside a terminal.
    """
    from kotogen.exporter import choose

    if not system.can_ask():
        return
    for command, notetype in list(missing.items()):
        if command in _skip_offered:
            continue
        _skip_offered.add(command)
        label = _(dict(CARD_COMMANDS)[command])
        console.space()
        print(_("{label}: the {notetype} note type does not exist in this profile.")
              .format(label=label, notetype=quoted(notetype)))
        choice = choose([("i", _("install it now")), ("h", _("hide the command")),
                         ("l", _("later"))], default="l", indent=" ")
        if choice == "i":
            if _install_notetypes({command: notetype}):
                missing.pop(command)
        elif choice == "h":
            _remember("KOTOGEN_SKIP", ",".join(sorted(skipped_commands() | {command})))
            missing.pop(command)


def _install_notetypes(missing: dict[str, str]) -> bool:
    """Creates the missing note types (command -> name), and says whether they
    all exist now.

    Shows what `deck install` prints, then pauses before the menu wipes it. A
    refusal (Anki gone, templates not found) is said and leaves the command
    marked. One install for all of them: a new profile lacks the five."""
    from kotogen.anki import notetypes
    from kotogen.cli import build_parser

    console.space()
    try:
        notetypes.run_deck(build_parser().parse_args(
            ["deck", "install", "--only", *missing]))
    except SystemExit as exc:
        if isinstance(exc.code, str):
            console.failed(exc.code)
    except (ConnectionError, RuntimeError) as exc:
        console.failed(console.reason(exc, console.ALONE))
    installed = set(missing.values()) <= anki_status(refresh=True).notetypes
    _pause(_("Enter to come back to the menu") + "...")
    return installed


# State of Anki for the session: probed once at start-up, then kept, since a probe
# can take seconds and the menu reopens after every command. The "a" setting
# probes again, and so does the send, just before it writes.
_anki: tuple[AnkiStatus, dict[str, str]] | None = None


def _refresh_anki(*, offer_skip: bool = True) -> tuple[AnkiStatus, dict[str, str]]:
    """Probes AnkiConnect and holds the state (and its missing types) for the menu.

    `offer_skip=False` before a send: no question may slip in between the
    dialogue and the generation.
    """
    global _anki
    state = _probe_anki()
    missing = _missing_notetypes(state)
    if offer_skip:
        _offer_skip(missing)
    _anki = (state, missing)
    return _anki


def _anki_state() -> tuple[AnkiStatus, dict[str, str]]:
    """State of Anki to show: the one already known, probed on the first pass."""
    return _anki if _anki is not None else _refresh_anki()


# What an entry can lack: Anki, the AI key, the model, and for `ask` a provider
# that drives tools. A dimmed entry carries no mark: the status line says which.
_ANKI, _KEY, _MODEL, _TOOLS = "anki", "key", "model", "tools"

# The screen of a dimmed entry chosen all the same, problem then way out. Anki
# has just been probed again (`_still_missing`): its way out names what keeps it
# silent. English, translated at the display site.
_WAYS_OUT = {_ANKI: ("Anki does not answer",
                     "is Anki open, with the AnkiConnect add-on installed?"),
             _KEY: ("{var} missing", "the settings, key {key}"),
             _MODEL: ("No model chosen", "the settings, key {key}"),
             _TOOLS: ("The provider {provider} drives no tools",
                      "the settings, key {key}")}
# Anki answers but refuses the key: asking whether it is open would mislead.
_KEY_REFUSED = ("AnkiConnect refuses the key", "setting KOTOGEN_ANKICONNECT_KEY")
_WAY_OUT_KEYS = {_KEY: "k", _MODEL: "m", _TOOLS: "m"}
_NEEDS = {_ANKI: "Anki", _KEY: "an API key", _MODEL: "a model",
          _TOOLS: "a provider that drives tools"}


def _missing_for(*, anki: Collection[str] = (), ai: Collection[str] = (),
                 tools: Collection[str] = ()) -> dict[str, tuple[str, ...]]:
    """What is missing from each entry named; nothing for those that are ready.

    `anki` lists the entries that need AnkiConnect, `ai` those that call the
    model, `tools` those that need a provider of `ai_client.TOOL_PROVIDERS`. The
    result serves both as `disabled=` and for `_why_not`, so that no entry is
    dimmed without saying why. Reads the session's state (`_anki_state`) rather
    than probing again.
    """
    missing: dict[str, list[str]] = {}
    if not _anki_state()[0].connected:
        for key in anki:
            missing.setdefault(key, []).append(_ANKI)
    if not has_key(default_provider()):
        for key in ai:
            missing.setdefault(key, []).append(_KEY)
    if not chosen_model():
        for key in ai:
            missing.setdefault(key, []).append(_MODEL)
    if default_provider() not in TOOL_PROVIDERS:
        for key in tools:
            missing.setdefault(key, []).append(_TOOLS)
    return {key: tuple(what) for key, what in missing.items()}


def _still_missing(missing: tuple[str, ...]) -> tuple[str, ...]:
    """What a dimmed entry one has chosen all the same still lacks.

    Anki is probed again, the session's state being possibly old; the key and
    the model need no probe, being read from the settings."""
    if _ANKI in missing and _refresh_anki()[0].connected:
        return tuple(m for m in missing if m != _ANKI)
    return missing


def _why_not(missing: tuple[str, ...], what: str = "") -> None:
    """The screen of a dimmed entry one has chosen all the same.

    One warning: the sentence, then its ways out with no blank line or indent
    between them.
    """
    what = what or _("This command")
    var = key_var(default_provider())
    refused = _anki_state()[0].key_refused
    lines = []
    for m in missing:
        problem, way_out = (_KEY_REFUSED if m == _ANKI and refused
                            else _WAYS_OUT[m])
        lines.append((_(problem).format(var=var, provider=default_provider()),
                      _(way_out).format(key=quoted(_WAY_OUT_KEYS.get(m, "")))))
    # The arrows line up, so that two missing things read as one table.
    column = max(console.width(problem) for problem, _way in lines)
    console.space()
    print(_("{what} needs {needs}.").format(
        what=what, needs=_(" and ").join(_(_NEEDS[m], "needs") for m in missing)))
    for problem, way_out in lines:
        print(f"{console.pad(problem, column)}  -> {way_out}")
    _pause(_("Enter to come back to the menu..."))


# Commands with nothing to do without AnkiConnect: they read or write the deck.
# The generating ones stay open offline, writing a TSV to import later.
ANKI_ONLY = ("maintain",)

# The generating commands, which call the model: dimmed without a key or a model
# rather than stopped at the end of their dialogue. The Corrections entry stays
# open, its looking and its marks needing no model: its own menu dims the rest.
IA_COMMANDS = ("kanji", "vocab", "grammar", "audio", "reading")

# The shown name of a command, for `_why_not`: "Corrections", not "maintain".
_NAMES = {key: name for key, name, _desc in MAIN_MENU if key}


def _visible_menu() -> list[tuple[str | None, str, str]]:
    """MAIN_MENU without the hidden commands, and without the subheadings gone empty."""
    skipped = skipped_commands()
    kept = [entry for entry in MAIN_MENU if entry[0] not in skipped]
    return [entry for i, entry in enumerate(kept)
            if entry[0] is not None
            or any(e[0] is not None for e in kept[i + 1:i + 2])]


def _print_status(state: AnkiStatus, missing: dict[str, str]) -> None:
    """A single status line: what will be called, where the cards will land.

    Each bracket names its destination (the model, the profile) or what stops it
    ("key to be set", "model to be chosen", "not connected"); a key AnkiConnect
    refuses gets a warning line of its own. The running cost of the chained
    commands follows, as `Usage.summary` writes it."""
    from kotogen.ai_client import session_usage

    provider = default_provider()
    ai = (_("key to be set") if not has_key(provider)
          else _("model to be chosen") if not chosen_model(provider)
          else model_label(provider))
    anki = ((state.profile or _("unknown profile")) if state.connected
            else _("not connected"))
    console.space()
    print(_("AI [{ai}]   Anki [{anki}]").format(ai=ai, anki=anki))
    if spent := session_usage().summary():
        print(spent)

    # One line per warning, problem and way out. A missing key or model gets
    # none, the bracket says it; a refused key does, or "not connected" alone
    # would send one to reopen an Anki already open.
    warnings = ["!! " + _("AnkiConnect refuses the key")
                + "  -> " + _("setting KOTOGEN_ANKICONNECT_KEY")
                ] if state.key_refused else []
    warnings += [
        "!! " + _("{label}: note type {notetype} missing").format(
            label=_(dict(CARD_COMMANDS)[command]), notetype=quoted(notetype))
        + "  -> " + _("the {menu} menu").format(menu=quoted(_("Templates")))
        for command, notetype in missing.items()
    ]
    # No blank line between the warnings, nor before them: they belong to the
    # status line, and spaced out, five of them would push the menu off the screen.
    if warnings:
        print("\n".join(warnings))
    if hidden := sorted(skipped_commands()):
        console.space()
        print(_("Hidden commands: {names}").format(names=" ".join(hidden)))
