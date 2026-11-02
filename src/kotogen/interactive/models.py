"""The AI: the key of the provider, and the model, which nothing picks for you.

No model is built in or put forward: models come and go faster than releases.
Each provider lists the ones it serves today, the OpenRouter catalogue with the
day's prices, Anthropic and OpenAI to the key; a model typed by hand goes too.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable

from kotogen import catalogue, console, currency, keyboard, menu, settings
from kotogen.ai_client import has_key, key_var, store_key
from kotogen.cli import PROVIDERS, chosen_model, default_provider
from kotogen.i18n import _, convention, quoted
from kotogen.interactive.screen import _ask, _Back, _header, _menu, _pause, _remember

# The providers in the order the model screen offers them, with what sets each
# apart. English, translated where they are displayed.
PROVIDER_NOTES = (
    ("openrouter", "every publisher behind one key, with today's prices"),
    ("anthropic", "direct Anthropic API (pip install anthropic)"),
    ("openai", "direct OpenAI API (pip install openai)"),
)

# Where each provider hands out its keys, shown by the screen that asks for one.
_KEY_PAGES = {
    "openrouter": "https://openrouter.ai/keys",
    "anthropic": "https://console.anthropic.com/settings/keys",
    "openai": "https://platform.openai.com/api-keys",
}

# Models displayed at once by a list: one screenful, filterable.
CATALOGUE_ROWS = 15


# ── API key ───────────────────────────────────────────────────────────────────
# Entered from the settings, or where a model is chosen: the AI client would
# only ask for it after the whole dialogue.

def _read_key(provider: str) -> bool | None:
    """Takes the key of `provider`, holds it and records it.

    True once a key is held, False if none was typed, None if cancelled. Typed
    as stars rather than silently, so a failed paste shows. The last four
    characters are echoed: the form in which the provider shows its keys."""
    var = key_var(provider)
    print(_("{var} key ({provider}).").format(var=var, provider=provider))
    if page := _KEY_PAGES.get(provider):
        print(_("To get one: {page}").format(page=page))
    print(_("It will show as stars while typing; an empty Enter cancels."))
    try:
        key = console.read_secret(
            "   " + _("{var} key: ").format(var=var)).strip()
    except (KeyboardInterrupt, EOFError):
        console.space()
        print(_("Cancelled."))
        return None
    console.space()
    if not key:
        print(_("No key entered, nothing has changed."))
        return False
    store_key(provider, key)
    if _remember(var, key):
        print(_("Key ...{last} kept and recorded in a local file, not to be"
                " shared.").format(last=key[-4:]))
    return True


def _ask_api_key() -> None:
    """The "k" setting: the key of the current provider, on a screen of its own."""
    _header()
    console.space()
    if _read_key(default_provider()) is not None:
        _pause(_("Enter to come back to the menu..."))


# ── AI model ──────────────────────────────────────────────────────────────────
# Set like the key, at once and for the next runs: the CLI reads the two
# variables again at every command.

def model_label(provider: str, model: str = "") -> str:
    """A model as the screens name it: the model, then who serves it.

    `model` defaults to the one chosen for that provider; with none, the label
    says that one is to be chosen.
    """
    model = model or chosen_model(provider)
    if not model:
        return _("to be chosen")
    return _("{model} via {provider}").format(model=model, provider=provider)


def _apply_model(provider: str, model: str) -> None:
    """Holds the choice and records it, then asks for the provider's key if it
    has none.

    Both variables together: a model name only means something at its provider.
    """
    # No blank line first: the menu already leaves one.
    print(_("Model set: {model}.").format(model=model_label(provider, model)))
    _remember("KOTOGEN_PROVIDER", provider)
    _remember("KOTOGEN_MODEL", model)
    if not has_key(provider):
        # Another provider expects another key: asked now, not at generation.
        console.space()
        _read_key(provider)
    _pause(_("Enter to come back to the menu..."))


def _ask_custom_model() -> None:
    """Free entry: any model at all, at any one of the providers.

    The provider first, as a model name only means something at its own. The
    screen is cleared first: a menu stacked under another has no room left to
    redraw under the arrows."""
    _header()
    provider = _menu(_("At which provider?"), [(name, name) for name in PROVIDERS],
                     allow_back=True)
    console.space()
    print(_("Exact name of the model, as the provider expects it"
            " (OpenRouter: {shape}).").format(shape=quoted(_("publisher/model"))))
    _apply_model(provider, _ask(_("Model"), back=True))


# ── The lists of models ───────────────────────────────────────────────────────
# One screen for every provider: the lines over the models (`intro`) and the line
# of each (`line`) are the provider's own. Only the OpenRouter catalogue is read
# again on demand: the others are read afresh whenever they open.

def _catalogue_line(model: dict) -> str:
    """One line of the catalogue screen: the id, the price of a generation, the rest."""
    cost, sign = currency.convert(catalogue.command_cost(model))
    context = (f"{model['context']:,}".replace(",", convention("thousands_separator", ","))
               if model["context"] else "?")
    cache = _("cache", "column") if model["cache"] else ""
    return (f"{console.pad(console.clean(model['id']), 44)}{currency.decimals(cost):>10} "
            f"{sign}  {console.pad(cache, _cache_column())}  {context:>9}")


def _cache_column() -> int:
    """The width of the cache column, its heading translated included."""
    return max(5, console.width(_("cache", "column")))


def _catalogue_intro(cat: catalogue.Catalogue, query: str, matching: list[dict],
                     shown: list[dict], *, indent: str, refine: str) -> list[str]:
    """What the list shows, where it comes from, and when it dates from."""
    day = (time.strftime(convention("date", "%b %d, %Y"), time.localtime(cat.fetched))
           if cat.fetched else "?")
    lines = ["", _("OpenRouter catalogue of {day}: {count} models able to read a"
                   " PDF,").format(day=day, count=len(cat.models)),
             _("as the commands of the project require.")]
    if cat.error:
        # Served from a cache not refreshed: the prices are of the day said above.
        lines.append("   " + _("(refresh impossible: {reason})").format(
            reason=cat.error))
    lines += _narrowed(query, matching, shown, _("The {count} cheapest are shown; {refine}."),
                       refine)
    # The headings take the offset of the model lines, and the price heading the
    # width of an amount and its symbol, so it lines up whatever the currency.
    context = _("context")
    lines += ["", f"{indent}{console.pad(_('model'), 44)}"
                  + _("{symbol}/generation").format(symbol=currency.symbol())
                  + f"  {console.pad(_('cache', 'column'), _cache_column())}  "
                  + console.pad_left(context, 9)]
    return lines


def _served_line(model: dict) -> str:
    """One line of a provider's own list: the id, then the name it gives, if any."""
    name = " ".join(console.clean(model["name"]).split())
    return (console.pad(console.clean(model["id"]), 44) + name).rstrip()


def _served_intro(provider: str, cat: catalogue.Catalogue, query: str,
                  matching: list[dict], shown: list[dict], *, indent: str,
                  refine: str) -> list[str]:
    """How many models the key is served, newest first."""
    lines = ["", _("Models {provider} serves to your key: {count}.").format(
        provider=provider, count=len(cat.models))]
    return lines + _narrowed(query, matching, shown,
                             _("The {count} newest are shown; {refine}."), refine) + [""]


def _narrowed(query: str, matching: list[dict], shown: list[dict], cut: str,
              refine: str) -> list[str]:
    """What the filter keeps, and how many of those the screen holds."""
    lines = []
    if query:
        lines.append(_("Filter {query}: {count} {models}.").format(
            query=quoted(query), count=len(matching),
            models=console.plural(len(matching), "model")))
    if len(shown) < len(matching):
        lines.append(cut.format(count=len(shown), refine=refine))
    return lines


# What a list puts over its models: (list, filter, models matching, models shown)
# and the indent and the way to narrow, as keywords.
_Intro = Callable[..., list[str]]


def _pick_by_key(cat: catalogue.Catalogue, intro: _Intro, line: Callable[[dict], str],
                 reload: Callable[[], catalogue.Catalogue] | None = None) -> str:
    """A list of models as one types: every letter narrows it.

    The letters feed the filter, so the other actions take Escape (clear, then
    leave) and F5 (read the list again, where `reload` allows it)."""
    query, index, offset = "", 0, 0
    _header()
    with keyboard.raw_mode():
        painted = 0
        while True:
            matching = [m for m in cat.models if query in m["id"]]
            index = max(0, min(index, len(matching) - 1))
            offset = min(offset, index)
            if index >= offset + CATALOGUE_ROWS:
                offset = index - CATALOGUE_ROWS + 1
            offset = max(0, min(offset, max(0, len(matching) - CATALOGUE_ROWS)))
            shown = matching[offset:offset + CATALOGUE_ROWS]

            lines = intro(cat, query, matching, shown,
                          indent="    ", refine=_("type to narrow"))
            highlight = None
            if shown:
                highlight = len(lines) + index - offset
                lines += [f"    {line(m)}" for m in shown]
            else:
                lines.append("    " + _("No model whose name holds {query}.")
                             .format(query=quoted(query)))
            lines += ["", "  " + _("filter: {query}").format(query=query) + "▌"]
            painted = menu.repaint(lines, painted, highlight)

            key = keyboard.read_key()
            if key == keyboard.ENTER and shown:
                return matching[index]["id"]
            if key == keyboard.ESC:
                if not query:
                    raise _Back
                query, index, offset = "", 0, 0
            elif key == keyboard.BACKSPACE:
                query, index, offset = query[:-1], 0, 0
            elif key == keyboard.F5 and reload:
                fresh = reload()
                # A failed refresh keeps the models, and only its reason.
                cat = fresh if fresh.models else cat._replace(error=fresh.error)
            elif key == keyboard.UP:
                index -= 1
            elif key == keyboard.DOWN:
                index += 1
            elif key == keyboard.PGUP:
                index -= CATALOGUE_ROWS
            elif key == keyboard.PGDN:
                index += CATALOGUE_ROWS
            elif key == keyboard.HOME:
                index = 0
            elif key == keyboard.END:
                index = len(matching) - 1
            elif len(key) == 1:
                query, index, offset = query + key.lower(), 0, 0


def _pick_numbered(cat: catalogue.Catalogue, intro: _Intro, line: Callable[[dict], str],
                   reload: Callable[[], catalogue.Catalogue] | None = None) -> str:
    """The same list where the keys are not read one by one.

    Redirected output, no ANSI, tests: the filter is a question of its own, and
    a model is chosen by its number."""
    query = ""
    while True:
        _header()
        matching = [m for m in cat.models if query in m["id"]]
        shown = matching[:CATALOGUE_ROWS]
        print("\n".join(intro(
            cat, query, matching, shown,
            indent=" " * (4 + len(str(len(shown)))),
            refine=_("{key} narrows the search").format(key=quoted("f")))))
        extras = [("f", _("Filter by part of the name")
                   + (_(" (currently: {query})").format(query=query) if query else ""))]
        if reload:
            extras.append(("u", _("Update the catalogue now")))
        choice = _menu("", [(m["id"], line(m)) for m in shown],
                       extras=extras, allow_back=True)
        if choice == "f":
            # An empty Enter clears the filter.
            query = _ask(_("Filter (Enter = none)"), "").strip().lower()
            continue
        if choice == "u":
            console.space()
            print(_("Reading the OpenRouter catalogue..."))
            cat = reload()
            continue
        return choice


def _pick(cat: catalogue.Catalogue, intro: _Intro, line: Callable[[dict], str],
          reload: Callable[[], catalogue.Catalogue] | None = None) -> str:
    pick = _pick_by_key if menu.raw_ready() else _pick_numbered
    return pick(cat, intro, line, reload)


def _unavailable(reason: str) -> None:
    """A list that could not be read: says why, then raises `_Back` to the providers."""
    console.space()
    print(_("Catalogue unavailable: {reason}").format(reason=reason))
    _pause(_("Enter to come back..."))
    raise _Back


def _browse_catalogue() -> None:
    """The OpenRouter catalogue, sorted from cheapest to dearest.

    Raises `_Back` to return to the providers, the model unchanged."""
    console.space()
    print(_("Reading the OpenRouter catalogue..."))
    cat = catalogue.load()
    if not cat.models:
        _unavailable(cat.error)
    _apply_model("openrouter", _pick(cat, _catalogue_intro, _catalogue_line,
                                     lambda: catalogue.load(refresh=True)))


def _browse_served(provider: str) -> None:
    """The models Anthropic or OpenAI serve to the key, the newest first.

    They list them to a key only: a missing one is asked for first. Raises
    `_Back` to return to the providers, the model unchanged."""
    if not has_key(provider):
        console.space()
        if not _read_key(provider):
            _pause(_("Enter to come back..."))
            raise _Back
    console.space()
    print(_("Reading the models of {provider}...").format(provider=provider))
    cat = catalogue.served(provider, settings.raw(key_var(provider)))
    if not cat.models:
        _unavailable(cat.error)
    _apply_model(provider, _pick(cat, functools.partial(_served_intro, provider),
                                 _served_line))


def _choose_model() -> None:
    """Changes the model called to generate the cards: a provider, then one of
    the models it serves, or any model typed by hand."""
    while True:
        _header()
        console.space()
        print(_("Model called to make the cards: each provider lists the ones it"
                " serves today."))
        console.space()
        current = default_provider() if chosen_model() else None
        try:
            choice = _menu(
                "",
                [(name, f"{name:<12}{_(note)}") for name, note in PROVIDER_NOTES],
                extras=[("a", _("Another model (free entry)"))],
                marks={current: _("  (current)")} if current else None,
                default=current,
                allow_back=True,
            )
        except _Back:
            return  # up to the settings, nothing changed
        try:
            if choice == "a":
                _ask_custom_model()
            elif choice == "openrouter":
                _browse_catalogue()
            else:
                _browse_served(choice)
        except _Back:
            continue  # back from a sub-screen to this list
        return
