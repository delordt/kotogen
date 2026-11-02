"""The guide a new user meets: what is missing before the first card.

One page per step, in the order they are needed, under a bar showing what is
done: the language (screens, then cards), the key, the model, Anki with its
add-on and note types, then the optional modules. A done step moves on, any step
can be skipped, Escape goes back a page and "m" leaves for the menu.

It opens on the first launch in front of a terminal, if the key, the model or
Anki is missing, and that launch is written down either way
(`KOTOGEN_GETTING_STARTED`): Anki closed is the common case of a launch, not a
sign of a newcomer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from kotogen import console, i18n, menu, prerequisites, settings, system
from kotogen.ai_client import has_key, key_var
from kotogen.anki import templates as card_templates
from kotogen.anki.connect import BAD_KEY, AnkiStatus
from kotogen.cli import chosen_model, default_provider
from kotogen.i18n import _, convention, counted
from kotogen.interactive import models, screen, settings_menu, status

ENV_VAR = "KOTOGEN_GETTING_STARTED"

# The code of AnkiConnect on AnkiWeb, the one thing typed into Anki.
ANKICONNECT_CODE = "2055492159"

# Steps, in the order they are needed: (key, name in the bar, title of its page).
# English here and translated where they are displayed, like `status.CARD_COMMANDS`.
_STEPS = (
    ("lang", "Language", "Language"),
    ("key", "API key", "API key"),
    ("model", "Model", "AI model"),
    ("anki", "Anki", "Anki"),
    ("modules", "Modules", "Optional modules"),
)

# Room between two names of the bar.
_GAP = 4

# What the bar is drawn with: a step done, a step not done, the page one is on.
_FULL, _EMPTY, _HERE = "━", "─", "▲"


def first_launch() -> bool:
    """Whether this launch is the one the guide belongs to.

    Only in front of a terminal, so that a script run first does not use the
    guide up, and only until a launch has been the first (see `met`).
    """
    return system.can_ask() and settings.flag(ENV_VAR)


def needed() -> bool:
    """Whether the first launch has anything to set up: the key, the model or
    Anki missing.

    The key and the model first, which need no probe. The Anki probe is kept for
    the main menu, and asks nothing about the note types: the guide installs
    them at once.
    """
    if not has_key(default_provider()) or not chosen_model():
        return True
    return not _anki_ready()


def met() -> None:
    """Write down that the first launch has come, so that the next launches go
    to the menu whatever they find missing. A failed write only shows the guide
    once more."""
    try:
        settings.write(ENV_VAR, "0")
    except OSError:
        pass


def _anki() -> tuple[AnkiStatus, dict[str, str]]:
    """The state of Anki the session holds, probed without the per-type question."""
    held = status._anki
    return held if held is not None else status._refresh_anki(offer_skip=False)


def _anki_ready() -> bool:
    state, missing = _anki()
    return state.connected and not missing


def _colon(label: str, value: str) -> str:
    """"Label: value", spaced the way the language of the screen spaces it."""
    return f"{label}{convention('colon', ': ')}{value}"


# -- Which steps are done -----------------------------------------------------

def _modules_done() -> bool:
    return not prerequisites.missing() and not prerequisites.ffmpeg_missing()


_DONE: dict[str, Callable[[], bool]] = {
    # Done once a language is written down, English included: a reader happy with
    # the default cannot be told from one who never saw the page.
    "lang": lambda: bool(settings.raw("KOTOGEN_LANG")),
    "key": lambda: has_key(default_provider()),
    "model": lambda: bool(chosen_model()),
    "anki": _anki_ready,
    "modules": _modules_done,
}


# -- The bar ------------------------------------------------------------------

def _bar(here: int) -> list[str]:
    """The names of the steps, the bar under them, and the mark of the page.

    A done step is dimmed and its stretch drawn full. Steps are done in any order,
    so the bar shows what is done, not how far one is.
    """
    names, bar, mark = "  ", "  ", "  "
    for index, (key, name, _title) in enumerate(_STEPS):
        name = _(name, "step")
        done = _DONE[key]()
        span = console.width(name) + (_GAP if index < len(_STEPS) - 1 else 0)
        if index == here:
            mark += " " * (console.width(name) // 2) + _HERE
        elif index < here:
            mark += " " * span
        shown = menu.dim(name) if done and menu.ansi_ready() else name
        names += shown + " " * (span - console.width(name))
        bar += (_FULL if done else _EMPTY) * span
    return [names, bar, mark]


# -- The pages ----------------------------------------------------------------

@dataclass
class _Page:
    """What a page says, and what it offers: (key, label) -> what it does.

    "next" is understood by the guide itself and needs no action.
    """

    lines: list[str]
    options: list[tuple[str, str]]
    actions: dict[str, Callable[[], None]] = field(default_factory=dict)


def _next(here: int, done: bool) -> tuple[str, str]:
    """The way on: "Next step" once done, "Skip this step" before, "Finish" last."""
    if here == len(_STEPS) - 1:
        return "next", _("Finish") if done else _("Skip this step")
    return "next", _("Next step") if done else _("Skip this step")


def _language_page(here: int) -> _Page:
    lines = [_colon(_("Screens"), i18n.describe()),
             _colon(_("Cards"), card_templates.describe_language())]
    done = _DONE["lang"]()
    choose = ("set", _("Change the languages") if done else _("Choose the languages"))
    return _Page(lines, _ordered(choose, _next(here, done), done),
                 {"set": _set_language})


def _key_page(here: int) -> _Page:
    provider = default_provider()
    done = _DONE["key"]()
    lines = [_colon(key_var(provider), _("set") if done else _("missing"))]
    if not done and (page := models._KEY_PAGES.get(provider)):
        lines.append(_("To get one: {page}").format(page=page))
    enter = ("set", _("Replace the key") if done else _("Enter the key"))
    return _Page(lines, _ordered(enter, _next(here, done), done),
                 {"set": models._ask_api_key})


def _model_page(here: int) -> _Page:
    done = _DONE["model"]()
    lines = [_colon(_("Model"), models.model_label(default_provider()))]
    if not done:
        lines.append(_("None is built in: each provider lists the ones it serves today."))
    choose = ("set", _("Change the model") if done else _("Choose the model"))
    return _Page(lines, _ordered(choose, _next(here, done), done),
                 {"set": models._choose_model})


def _anki_page(here: int) -> _Page:
    state, missing = _anki()
    if state.connected and not missing:
        return _Page([_("Connected to the {profile} profile.")
                     .format(profile=_profile(state))],
                     [_next(here, True)])
    if state.connected:
        names = i18n.listed(sorted(missing.values()))
        lines = [_colon(counted(len(missing),
                                "Note type to create",
                                "Note types to create"), names)]
        return _Page(lines, [("install", counted(len(missing),
                                                 "Create it",
                                                 "Create them")), _next(here, False)],
                     {"install": lambda: _create(missing)})
    check = ("check", _("Ask Anki again"))
    if state.key_refused:
        lines = [_(BAD_KEY)]
    else:
        lines = [_("Anki does not answer. It must be open, with the AnkiConnect add-on:"),
                 "   " + _("Tools > Add-ons > Get Add-ons..., code {code}, then"
                           " restart Anki").format(code=ANKICONNECT_CODE)]
    return _Page(lines, [check, _next(here, False)], {"check": _probe})


def _modules_page(here: int) -> _Page:
    pending = prerequisites.missing()
    lines = []
    if not pending and not prerequisites.ffmpeg_missing():
        lines.append(_("Every optional module is installed, FFmpeg included."))
    column = max((console.width(prerequisites.weight(e)) for e in pending), default=0)
    lines += [f"   {console.pad(prerequisites.weight(e), column)}  {_(e.what)}"
              for e in pending]
    if prerequisites.ffmpeg_missing():
        lines += [_("FFmpeg (sound and video) installs by hand: {command}")
                  .format(command=system.ffmpeg_hint())]
    options = []
    if pending:
        total = prerequisites.weight_of(pending)
        options.append(("install", counted(len(pending),
                                           "Install it ({total})",
                                           "Install them ({total})").format(total=total)))
    options.append(_next(here, _modules_done()))
    return _Page(lines, options, {"install": _install_modules})


def _ordered(action: tuple[str, str], onward: tuple[str, str],
             done: bool) -> list[tuple[str, str]]:
    """The action first while the step is to do, the way on first once it is done:
    the line Enter takes is the likeliest one."""
    return [onward, action] if done else [action, onward]


def _profile(state: AnkiStatus) -> str:
    return i18n.quoted(state.profile) if state.profile else _("unknown profile")


_PAGES: dict[str, Callable[[int], _Page]] = {
    "lang": _language_page, "key": _key_page, "model": _model_page,
    "anki": _anki_page, "modules": _modules_page,
}


# -- What the pages do --------------------------------------------------------

def _set_language() -> None:
    """The screens, then the cards, the second opened on the first answer."""
    if settings_menu._choose_interface_language():
        settings_menu._choose_card_language(suggested=i18n.language())


def _probe() -> None:
    status._refresh_anki(offer_skip=False)


def _create(missing: dict[str, str]) -> None:
    """Every missing note type in one install, then Anki asked again: the state
    the session holds is what says whether the step is done."""
    screen._header()
    status._install_notetypes(missing)
    _probe()


def _install_modules() -> None:
    screen._header()
    console.space()
    prerequisites.install_now()
    screen._pause(_("Enter to continue..."))


# -- The guide ----------------------------------------------------------------

def run() -> None:
    """The guide, page by page, until its last page or the menu.

    Opens on the first step still to do. An action that leaves its step done
    moves on; otherwise the page is shown again.
    """
    to_do = [i for i, (key, _name, _title) in enumerate(_STEPS) if not _DONE[key]()]
    here = to_do[0] if to_do else 0
    while here < len(_STEPS):
        key, _name, title = _STEPS[here]
        page = _PAGES[key](here)
        screen._header()
        console.space()
        print("\n".join(_bar(here)))
        console.space()
        print(_(title, "step"))
        console.space()
        print("\n".join(page.lines))
        try:
            choice = screen._menu(
                "", [(None, "")] + page.options,
                extras=[(None, ""), ("m", _("Go to the menu"))],
                default=page.options[0][0], allow_back=True)
        except screen._Back:
            if here == 0:
                return
            here -= 1
            continue
        if choice == "m":
            return
        if choice == "next":
            here += 1
            continue
        page.actions[choice]()
        if _DONE[key]():
            here += 1
