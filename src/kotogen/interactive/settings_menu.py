"""The settings screen, and the settings it opens on the spot.

The folder of the cards, the display currency and the two languages are set
here. The key and the model of the AI (`models`) and the history of the sources
(`history`) have modules of their own, opened from this one.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from kotogen import (
    audio_quality,
    console,
    currency,
    i18n,
    menu,
    prefs,
    proofreading,
    seen,
    video_clip,
)
from kotogen.ai_client import has_key, key_var
from kotogen.anki import templates as card_templates
from kotogen.cli import default_provider
from kotogen.i18n import _
from kotogen.interactive.deck import _apply_template
from kotogen.interactive.history import _history
from kotogen.interactive.lists import _laid_out, _matches, _searchable
from kotogen.interactive.models import _ask_api_key, _choose_model, model_label
from kotogen.interactive.screen import (
    _ask,
    _ask_yes_no,
    _Back,
    _header,
    _menu,
    _pause,
    _remember,
    _remember_toggle,
)
from kotogen.interactive.status import _anki_state, _refresh_anki


def _settings_entries() -> list[tuple[str | None, str]]:
    """The thirteen settings, each followed by what it is worth: (key, label).

    Labels are nouns: the value column says what changes. A blank line separates
    what the keys do: seven open a choice ("h" included), five toggle on the spot
    ("q", "i" and "p" cycle through more than two positions), and the AnkiConnect
    probe acts. "g", the language of the cards, sits under "l" so that the two
    read as a pair; it is the one setting kept in `templates.env` rather than in
    the environment.

    Each letter comes from the word naming the setting; "g" (Generated) and "i"
    (Image) are forced, `c`, `l` and `v` being taken. "q" quits nothing here.
    """
    from kotogen.exporter import output_dir

    provider = default_provider()
    state = _anki_state()[0]
    values = (
        ("k", _("API key"),
         f"{key_var(provider)} " + (_("set") if has_key(provider)
                                    else _("missing"))),
        ("m", _("AI model"), model_label(provider)),
        ("o", _("TSV folder"), str(output_dir())),
        ("c", _("Display currency"), currency.describe()),
        ("h", _("Source history"), seen.describe()),
        ("l", _("Interface language"), i18n.describe()),
        ("g", _("Language of the cards"), card_templates.describe_language()),
        (None, "", ""),   # blank line: see the docstring
        ("s", _("Auto-send to Anki"),
         _("on") if prefs.auto_send() else _("off")),
        ("v", _("Equivalent command"),
         _("shown") if prefs.verbose() else _("hidden")),
        ("q", _("Audio compression"), audio_quality.describe()),
        ("i", _("Video picture"), video_clip.describe()),
        ("p", _("Doubtful cards"), proofreading.describe()),
        (None, "", ""),   # blank line: see the docstring
        ("a", _("Connection to Anki"),
         _("connected to {profile}").format(
             profile=state.profile or _("unknown profile")) if state.connected
         else _("key refused") if state.key_refused else _("not connected")),
    )
    # At least 24, two past the longest label of the French and Japanese
    # screens (22 columns). Labels are measured as translated, in screen
    # columns, and a longer one pushes the column further.
    column = max([24] + [console.width(label) + 2 for key, label, _value in values if key])
    return [(key, console.pad(label, column) + value if key else label)
            for key, label, value in values]


# ── Folder of the cards ───────────────────────────────────────────────────────
# With Anki closed, the cards go to a TSV to import by hand, in the folder
# `KOTOGEN_OUTPUT_DIR` names.

def _apply_output_dir(path: Path) -> None:
    """Holds the folder and records it."""
    print(_("The cards to import will go into {path}.").format(path=path))
    _remember("KOTOGEN_OUTPUT_DIR", str(path))
    _pause(_("Enter to come back to the menu..."))


def _ask_output_dir() -> Path:
    """Free entry of a folder, created on agreement if it does not exist yet.

    Created now rather than when the TSV is written, so that a typo shows here."""
    _header()
    console.space()
    print(_("Path of the folder to lay the TSV files in (and the MP3 files of the"
            " listening cards)."))
    path = Path(_ask(_("Folder"), back=True)).expanduser()
    if path.is_dir():
        return path
    if not _ask_yes_no(_("{path} does not exist, create it").format(path=path),
                       True):
        raise _Back
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print("   " + _("Creation impossible: {reason}").format(reason=exc))
        _pause(_("Enter to come back..."))
        raise _Back from None
    return path


def _choose_output_dir() -> None:
    """Changes the folder the TSV files to import by hand land in."""
    from kotogen.exporter import output_choices, output_dir

    while True:
        _header()
        # No line for the current folder: "(current)" marks it in the list.
        current = output_dir()
        console.space()
        print(_("Folder of the TSV files to import by hand.") + "\n")
        choices = output_choices()
        try:
            choice = _menu(
                "",
                [(str(i), f"{console.pad(name, 16)}{path}")
                 for i, (name, path) in enumerate(choices)],
                extras=[("a", _("Another folder (free entry)"))],
                marks={str(i): _("  (current)")
                       for i, (_name, path) in enumerate(choices)
                       if path == current},
                allow_back=True,
            )
        except _Back:
            return  # a way back here: we go up to the settings, nothing has changed
        try:
            _apply_output_dir(_ask_output_dir() if choice == "a"
                              else choices[int(choice)][1])
        except _Back:
            continue  # a way back from the free entry: we come back to this list
        return


# ── Display currency ──────────────────────────────────────────────────────────
# OpenRouter prices in dollars; costs show in the currency chosen here, at the
# rate of the day (see `currency`).

def _apply_currency(cur: str) -> None:
    """Holds the currency and records it."""
    currency.set_code(cur)
    if cur == currency.DEFAULT_CODE:
        detail = ""  # billing currency: no rate to announce
    elif line := currency.rate_line(cur):
        detail = f" ({line})"
    else:
        # No rate for this code: said now rather than found out as dollars later.
        detail = " " + _("(no rate known: they will stay in dollars)")
    # No leading newline: the menu already left a blank line.
    print(_("The amounts will show in {currency}.").format(
        currency=currency.label(cur)) + detail)
    _remember("KOTOGEN_CURRENCY", cur)
    _pause(_("Enter to come back to the menu..."))


def _ask_currency() -> str:
    """Free entry of a currency, checked against those that have a rate.

    A typo then shows here, not as amounts left in dollars."""
    _header()
    console.space()
    print(_("Currency to show: EUR, JPY, GBP, CHF, SEK..."))
    cur = _ask(_("Currency"), back=True).strip().upper()
    known = currency.known_codes()
    if known and cur not in known:
        console.space()
        print(_("{code} has no known exchange rate.").format(code=cur))
        print("   " + _("Currencies quoted: {codes}").format(
            codes=" ".join(known)))
        # The next screen's `_header()` wipes everything: pause on the refusal.
        _pause(_("Enter to come back..."))
        raise _Back
    return cur


def _choose_currency() -> None:
    """Changes the currency the costs show in."""
    while True:
        _header()
        console.space()
        print(_("Display currency of the costs."))
        print(_("The bill stays in dollars."))
        current = currency.code()
        if current != currency.DEFAULT_CODE and not currency.rate_line(current):
            # A code set in the .env with no known rate: the settings list shows
            # only the code, so this screen says why the amounts stay in dollars.
            console.space()
            print(_("{code} has no known rate: the amounts stay in dollars.")
                  .format(code=current))
        console.space()
        try:
            choice = _menu(
                "",
                [(cur, currency.label(cur)) for cur in currency.MENU_CODES],
                extras=[("a", _("Another currency"))],
                marks={current: _("  (current)")},
                allow_back=True,
            )
        except _Back:
            return  # a way back here: we go up to the settings, nothing has changed
        try:
            _apply_currency(_ask_currency() if choice == "a" else choice)
        except _Back:
            continue  # a way back from the free entry: we come back to this list
        return


# ── The two languages ─────────────────────────────────────────
# A list rather than a cycle like the compression notches: what is on offer shows
# before anything moves, and a press too many cannot leave the screen in a
# language one does not read. Both screens show the code then the name, like the
# two lines that open them (see `_settings_entries`). As in the grammar table,
# letters write a search, digits still aim, and Escape wipes the search first.

def _pick_language(codes: list[str], name: Callable[[str], str],
                   current: str, default: str | None = None) -> str:
    """One language among `codes`, searched by what is typed; hands back its code.

    The list opens on `default` when it is one of `codes`, else on `current`. A
    language is found by its code, by `name` or by its name in the screen's
    language, accents ignored (`_searchable`): `fr`, `french` and `francais`
    all find French. Without key-by-key reading, it is the plain numbered menu.
    """
    rows = [(code, code, name(code)) for code in codes]
    marks = {current: _("  (current)")}
    default = default if default in codes else current
    haystacks = {code: _searchable(" ".join(
        (code, name(code), card_templates.language_label(code))))
        for code in codes}

    def build(search: str, _jump: int) -> menu.View:
        kept = [row for row in rows
                if not search or _matches(search, haystacks[row[0]])]
        hint = (_("Search: {search}_").format(search=search) if search
                else _("type to search"))
        return menu.compose("", _laid_out(kept), marks=marks,
                        default=None if search else default,
                        allow_back=True, extra_hints=(hint,))

    view = build("", 0)
    if not view.raw:
        return _menu("", _laid_out(rows), marks=marks, default=default,
                     allow_back=True)
    return menu.by_key(view, allow_back=True, recompose=build)


def _choose_interface_language() -> bool:
    """Changes the language the screens are written in; False if left without.

    Each language is named in itself (`fr - Français`), the form its reader
    looks for. `i18n.use` switches the table at once, so the redrawn settings
    screen is the only answer printed.
    """
    _header()
    console.space()
    print(_("Language of the screens, the menus and the messages."))
    print(_("The language of the cards is the setting just under it."))
    console.space()
    try:
        choice = _pick_language(i18n.available(), i18n.language_name,
                                i18n.language())
    except _Back:
        return False  # a way back here: we go up, nothing has changed
    _remember_toggle("KOTOGEN_LANG", i18n.use(choice))
    return True


def _choose_card_language(suggested: str | None = None) -> None:
    """Changes the language the cards are generated in.

    `suggested` is the line the list opens on, when it is not the current one.
    Kept in `templates.env` and set only here, since it changes no template.
    Languages are named in the screen's language (`en - anglais` on a French
    screen): a property of the deck, not the reader's language (see
    `card_templates.describe_language`).
    """
    _header()
    console.space()
    print(_("Language the cards are written in: labels, translations,"
            " questions, explanations."))
    print(_("The fields, the decks and the tags keep their English names in every"
            " language, so that your searches and your cards stay the same."))
    console.space()
    setting = card_templates.LANGUAGE
    current = card_templates.value(setting.key)
    try:
        choice = _pick_language(list(setting.positions),
                                card_templates.language_label, current,
                                suggested)
    except _Back:
        return  # a way back here: we go up to the settings, nothing has changed
    _apply_template(setting, choice)


# ── Settings ──────────────────────────────────────────────────────────────────

def _settings() -> None:
    """The settings screen: one enters it once, one sets as many as one likes.

    Letters and order are those of `_settings_entries`, which says why."""
    # Reopens on the setting just touched, which is often the one wanted next.
    choice = None
    while True:
        _header()
        try:
            choice = _menu(_("Settings"), [], extras=_settings_entries(),
                           allow_back=True, default=choice)
        except _Back:
            return
        if choice == "k":
            _ask_api_key()
        elif choice == "m":
            _choose_model()
        elif choice == "o":
            _choose_output_dir()
        elif choice == "c":
            _choose_currency()
        elif choice == "h":
            _history()
        elif choice == "l":
            _choose_interface_language()
        elif choice == "g":
            _choose_card_language()
        elif choice == "s":
            prefs.set_auto_send(not prefs.auto_send())
            _remember_toggle("KOTOGEN_AUTO_SEND", "1" if prefs.auto_send() else "0")
        elif choice == "v":
            prefs.set_verbose(not prefs.verbose())
            _remember_toggle("KOTOGEN_VERBOSE", "1" if prefs.verbose() else "0")
        elif choice == "q":
            # Four positions, cycled in place: the value opposite changes.
            _remember_toggle("KOTOGEN_AUDIO_QUALITY", audio_quality.cycle().code)
        elif choice == "i":
            # Three positions, cycled like "q".
            _remember_toggle("KOTOGEN_VIDEO", video_clip.cycle())
        elif choice == "p":
            _remember_toggle("KOTOGEN_PROOFREAD", proofreading.cycle())
        elif choice == "a":
            # On demand: an Anki opened meanwhile shows without a command.
            _refresh_anki()
