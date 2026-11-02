"""The settings reached from the main menu: the AI model and its catalogue, the
history of sources, the folder of the cards, the currency and the switches."""

import os
from pathlib import Path

import pytest

from kotogen import audio_quality, i18n, interactive, keyboard, prefs, seen
from kotogen.anki import templates as card_templates
from kotogen.anki.connect import AnkiStatus
from kotogen.cli import build_parser, chosen_model, default_provider
from kotogen.interactive import interactive_argv
from menus import *  # the fixtures every menu test starts from, and its helpers

# ── AI model ──────────────────────────────────────────────────────────────────
# None is built in: the screen offers the providers, and each lists its models.

def _fake_catalogue(monkeypatch, models: list[dict], *, error: str = "",
                    fetched: float | None = 1_770_000_000.0) -> list[bool]:
    """Serves a catalogue with no network; hands back the list of the refreshes
    asked for (True = "u", an explicit update)."""
    from kotogen import catalogue

    refreshes: list[bool] = []

    def load(*, refresh=False, timeout=10):
        refreshes.append(refresh)
        return catalogue.Catalogue(models, fetched, error)

    monkeypatch.setattr(catalogue, "load", load)
    return refreshes


def _fake_served(monkeypatch, models: list[dict], *, error: str = "") -> list[tuple]:
    """Serves the list of a provider with no network; hands back the (provider,
    key) of each reading."""
    from kotogen import catalogue

    asked: list[tuple] = []

    def served(provider, key, *, timeout=10):
        asked.append((provider, key))
        return catalogue.Catalogue(models, 1_770_000_000.0 if models else None, error)

    monkeypatch.setattr(catalogue, "served", served)
    return asked


def _entry(model_id: str, prompt: float, *, cache: bool = True) -> dict:
    return {"id": model_id, "name": model_id, "prompt": prompt,
            "completion": prompt * 5, "cache": cache, "context": 200_000}


def _written(monkeypatch) -> list:
    written: list = []
    monkeypatch.setattr("kotogen.settings.write",
                        lambda name, value: written.append((name, value)) or "/tmp/settings.env")
    return written


def test_the_model_screen_offers_the_providers_and_no_model(monkeypatch, capsys):
    """No model is put forward: the screen names the providers, and each lists
    its own."""
    feed(monkeypatch, ["s", "m", "b", "b", "q"])
    assert interactive_argv() is None
    assert os.environ["KOTOGEN_MODEL"] == MODEL
    out = capsys.readouterr().out
    screen = out[out.rindex("serves today."):].split("\nSettings\n")[0]
    for provider in ("openrouter", "anthropic", "openai"):
        assert provider in screen
    assert "free entry" in screen
    assert "/" not in screen   # no model's name, which an OpenRouter id writes with one


def test_a_model_of_the_catalogue_is_applied_and_saved(monkeypatch, capsys):
    """The provider and the model are saved together, and both redrawn screens
    show them: the status line and the settings' "m" line."""
    written = _written(monkeypatch)
    _fake_catalogue(monkeypatch, [_entry("cheap/model", 1e-7), _entry("dear/model", 3e-6)])
    # settings; "m"; OpenRouter; its first model; back; quit
    feed(monkeypatch, ["s", "m", "1", "1", "b", "q"])
    assert interactive_argv() is None
    assert os.environ["KOTOGEN_MODEL"] == "cheap/model"
    assert written == [("KOTOGEN_PROVIDER", "openrouter"), ("KOTOGEN_MODEL", "cheap/model")]
    out = capsys.readouterr().out
    assert "Record it" not in out
    assert _status_bar(out).startswith("AI [cheap/model via openrouter]")
    settings_line = [l for l in out.splitlines() if l.strip().startswith("m.")][-1]
    assert settings_line.endswith("cheap/model via openrouter")


def test_catalogue_lists_models_with_the_price_of_a_generation(monkeypatch, capsys):
    _fake_catalogue(monkeypatch, [_entry("cheap/model", 1e-7),
                                  _entry("dear/model", 3e-6)])
    feed(monkeypatch, ["s", "m", "1", "1", "b", "q"])
    interactive_argv()
    out = capsys.readouterr().out
    assert "OpenRouter catalogue of" in out
    assert "0.0070 $" in out          # 40 000 x 1e-7 + 6 000 x 5e-7
    assert "$/generation" in out


def test_catalogue_can_be_filtered_by_name(monkeypatch, capsys):
    """98 models do not make a menu: "f" cuts the list down to a piece of a name."""
    _fake_catalogue(monkeypatch, [_entry("publisher/model-a", 1e-7),
                                  _entry("studio/model-b", 3e-7)])
    # catalogue; filter; "studio"; the only one left; quit
    feed(monkeypatch, ["s", "m", "1", "f", "studio", "1", "b", "q"])
    interactive_argv()
    assert os.environ["KOTOGEN_MODEL"] == "studio/model-b"
    assert 'Filter "studio": 1 model.' in capsys.readouterr().out


def test_catalogue_can_be_refreshed_on_demand(monkeypatch):
    """"u" asks for the catalogue again without waiting for the cache to lapse."""
    refreshes = _fake_catalogue(monkeypatch, [_entry("cheap/model", 1e-7)])
    feed(monkeypatch, ["s", "m", "1", "u", "1", "b", "q"])
    interactive_argv()
    assert refreshes == [False, True]


def test_a_stale_catalogue_says_so(monkeypatch, capsys):
    """Served from a stale cache: the screen says its prices are dated."""
    _fake_catalogue(monkeypatch, [_entry("cheap/model", 1e-7)],
                    error="no answer")
    feed(monkeypatch, ["s", "m", "1", "b", "b", "b", "q"])
    interactive_argv()
    out = capsys.readouterr().out
    assert "refresh impossible: no answer" in out


def test_an_unreachable_catalogue_returns_to_the_providers(monkeypatch, capsys):
    """No network and no cache: back to the providers, the model unchanged."""
    _fake_catalogue(monkeypatch, [], error="no answer", fetched=None)
    # catalogue (fails, comes back); back; back; quit
    feed(monkeypatch, ["s", "m", "1", "b", "b", "q"])
    assert interactive_argv() is None
    assert os.environ["KOTOGEN_MODEL"] == MODEL
    out = capsys.readouterr().out
    assert "Catalogue unavailable: no answer" in out
    assert out.count("every publisher behind one key") >= 2


def test_a_provider_lists_its_models_to_the_key(monkeypatch, capsys):
    """Anthropic and OpenAI give their list to a key: the one held is sent."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    asked = _fake_served(monkeypatch, [{"id": "claude-new", "name": "Claude New"},
                                       {"id": "claude-old", "name": "Claude Old"}])
    # settings; "m"; Anthropic; its second model; back; quit
    feed(monkeypatch, ["s", "m", "2", "2", "b", "q"])
    interactive_argv()
    assert asked == [("anthropic", "sk-ant-test")]
    assert os.environ["KOTOGEN_PROVIDER"] == "anthropic"
    assert os.environ["KOTOGEN_MODEL"] == "claude-old"
    out = capsys.readouterr().out
    assert "Models anthropic serves to your key: 2." in out
    assert "Claude New" in out


def test_a_provider_without_a_key_asks_for_it_before_listing(monkeypatch):
    written_key = _written(monkeypatch)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "sk-oa-typed")
    asked = _fake_served(monkeypatch, [{"id": "gpt-new", "name": ""}])
    feed(monkeypatch, ["s", "m", "3", "1", "b", "q"])
    interactive_argv()
    assert asked == [("openai", "sk-oa-typed")]
    assert ("OPENAI_API_KEY", "sk-oa-typed") in written_key
    assert os.environ["KOTOGEN_MODEL"] == "gpt-new"


def test_no_key_typed_lists_nothing(monkeypatch):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "")
    from kotogen import catalogue

    monkeypatch.setattr(catalogue, "served",
                        lambda *a, **k: pytest.fail("listed without a key"))
    feed(monkeypatch, ["s", "m", "3", "b", "b", "q"])
    interactive_argv()
    assert os.environ["KOTOGEN_MODEL"] == MODEL


def test_a_list_refused_returns_to_the_providers(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-old")
    _fake_served(monkeypatch, [], error="anthropic refuses the key")
    feed(monkeypatch, ["s", "m", "2", "b", "b", "q"])
    interactive_argv()
    assert os.environ["KOTOGEN_MODEL"] == MODEL
    assert "Catalogue unavailable: anthropic refuses the key" in capsys.readouterr().out


def test_custom_model_asks_its_provider_first_then_its_key(monkeypatch, capsys):
    """Free entry: the provider first, and its missing key is asked for at once
    rather than in the middle of a generation."""
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "")
    # settings; "m"; free entry; anthropic provider; model; back; quit
    feed(monkeypatch, ["s", "m", "a", "1", "claude-typed", "b", "q"])
    assert interactive_argv() is None
    assert os.environ["KOTOGEN_PROVIDER"] == "anthropic"
    out = capsys.readouterr().out
    assert "claude-typed via anthropic" in out
    assert "ANTHROPIC_API_KEY key (anthropic)." in out
    # No key typed: the status line says why the model cannot be called.
    assert _status_bar(out).startswith("AI [key to be set]")


def test_back_from_the_model_menu_changes_nothing(monkeypatch):
    feed(monkeypatch, ["s", "m", "b", "b", "q"])
    assert interactive_argv() is None
    assert os.environ["KOTOGEN_MODEL"] == MODEL


def test_the_model_stays_out_of_the_equivalent_command(monkeypatch):
    """A setting like the others: the command typed again reads it where the
    menu wrote it."""
    _fake_catalogue(monkeypatch, [_entry("cheap/model", 1e-7)])
    # settings; "m"; OpenRouter; its model; back; make; vocab; a word; the word;
    # no send
    feed(monkeypatch, ["s", "m", "1", "1", "b", "2", "1", "食べる", ""])
    argv = interactive_argv()
    assert argv == ["vocab", "食べる"]
    assert build_parser().parse_args(argv).model is None


def test_without_a_model_the_commands_that_call_it_are_dimmed(monkeypatch, capsys):
    """Chosen all the same, an entry says what it lacks and where to get it."""
    monkeypatch.delenv("KOTOGEN_MODEL")
    feed(monkeypatch, ["2", "q"])
    interactive_argv()
    out = capsys.readouterr().out
    assert _status_bar(out).startswith("AI [model to be chosen]")
    assert "Vocabulary needs a model." in out
    assert 'No model chosen  -> the settings, key "m"' in out


# ── Source history ────────────────────────────────────────────────────────────

def test_the_history_screen_names_its_sources_and_forgets_one(monkeypatch, capsys):
    """The file's keys ("nhk", "onomappu") are folder names: the screen shows the
    names they were chosen under, and forgetting one source leaves the others."""
    seen.mark("audio", "nhk", "ne1", "Article")
    seen.mark("audio", "onomappu", "vid-1", "Video")
    feed(monkeypatch, ["s", "h", "2", "y", "b", "b", "q"])
    interactive_argv()
    out = capsys.readouterr().out
    assert "NHK Easy" in out and "Onomappu (YouTube)" in out
    assert seen.load("audio", "onomappu") == {}
    assert seen.load("audio", "nhk") == {"ne1": "Article"}


def test_forgetting_everything_empties_the_history(monkeypatch):
    seen.mark("audio", "nhk", "ne1", "Article")
    seen.mark("reading", "nhk", "ne2", "Other")
    seen.mark("audio", "teppei", "guid-1", "Episode")
    # The screen reopens after the forgetting, empty: one more "b" to leave it.
    feed(monkeypatch, ["s", "h", "a", "y", "b", "b", "q"])
    interactive_argv()
    assert seen.inventory() == []


def test_taking_back_from_the_deck_fills_an_empty_history(monkeypatch, capsys):
    """The case of the second machine: nothing in the file, everything in the deck."""
    from kotogen.anki import deck as anki_deck

    article = "https://news.web.nhk/news/easy/ne2026071201/ne2026071201.html"
    monkeypatch.setattr(anki_deck, "anki", lambda action, **params: (
        [1] if action == "findNotes" and '"note:Listening"' in params.get("query", "")
        else [{"fields": {"Source": {"value": article}}}] if action == "notesInfo"
        else []))
    feed(monkeypatch, ["s", "h", "d", "b", "b", "q"])
    interactive_argv()
    assert seen.load("audio", "nhk") == {"ne2026071201": ""}
    assert "1 entry taken back from the deck: NHK Easy 1" in capsys.readouterr().out


def test_taking_back_names_the_sources_the_deck_no_longer_holds(monkeypatch, capsys):
    """A source whose cards were deleted stays in the history: the screen says so,
    but forgetting it stays manual, since a deleted card was often a bad one."""
    from kotogen.anki import deck as anki_deck

    seen.mark("audio", "onomappu", "vid-1", "Video deleted since")
    article = "https://news.web.nhk/news/easy/ne2026071201/ne2026071201.html"
    monkeypatch.setattr(anki_deck, "anki", lambda action, **params: (
        [1] if action == "findNotes" and '"note:Listening"' in params.get("query", "")
        else [{"fields": {"Source": {"value": article}}}] if action == "notesInfo"
        else []))
    feed(monkeypatch, ["s", "h", "d", "b", "b", "q"])
    interactive_argv()
    out = capsys.readouterr().out
    assert "1 source no longer has a card in the deck: Onomappu (YouTube)." in out
    assert seen.load("audio", "onomappu") == {"vid-1": "Video deleted since"}


def _deck_that_carries(*traces: str):
    """AnkiConnect that hands back nothing but those provenances, all in listening."""
    return lambda action, **params: (
        list(range(len(traces)))
        if action == "findNotes" and '"note:Listening"' in params.get("query", "")
        else [{"fields": {"Source": {"value": trace}}} for trace in traces]
        if action == "notesInfo" else [])


def test_forgetting_those_no_longer_in_the_deck(monkeypatch, capsys):
    """The sources with no card left in the deck are forgotten in one go; the rest
    stays."""
    from kotogen.anki import deck as anki_deck

    article = "https://news.web.nhk/news/easy/ne2026071201/ne2026071201.html"
    seen.mark("audio", "nhk", "ne2026071201", "Article")
    seen.mark("audio", "onomappu", "vid-1", "Video deleted since")
    monkeypatch.setattr(anki_deck, "anki", _deck_that_carries(article))
    feed(monkeypatch, ["s", "h", "f", "y", "b", "b", "q"])
    interactive_argv()
    out = capsys.readouterr().out
    assert "No card left in the deck: Onomappu (YouTube)." in out
    assert seen.load("audio", "onomappu") == {}
    assert seen.load("audio", "nhk") == {"ne2026071201": "Article"}


def test_forgetting_the_absent_touches_nothing_when_the_deck_carries_all(
        monkeypatch, capsys):
    """It only says so: nothing is wiped without an answer."""
    from kotogen.anki import deck as anki_deck

    article = "https://news.web.nhk/news/easy/ne2026071201/ne2026071201.html"
    seen.mark("audio", "nhk", "ne2026071201", "Article")
    monkeypatch.setattr(anki_deck, "anki", _deck_that_carries(article))
    feed(monkeypatch, ["s", "h", "f", "b", "b", "q"])
    interactive_argv()
    assert "Nothing to forget" in capsys.readouterr().out
    assert seen.load("audio", "nhk") == {"ne2026071201": "Article"}


def test_a_refused_forget_of_the_absent_leaves_the_whole_history(monkeypatch, capsys):
    """The question is asked with "no": what is forgotten here is paid for again."""
    from kotogen.anki import deck as anki_deck

    seen.mark("audio", "onomappu", "vid-1", "Video deleted since")
    monkeypatch.setattr(anki_deck, "anki", _deck_that_carries(
        "https://news.web.nhk/news/easy/ne2026071201/ne2026071201.html"))
    feed(monkeypatch, ["s", "h", "f", "", "b", "b", "q"])
    interactive_argv()
    assert seen.load("audio", "onomappu") == {"vid-1": "Video deleted since"}


def test_taking_back_without_anki_does_not_say_the_deck_is_empty(monkeypatch, capsys):
    """Anki closed is not "nothing to take back": nothing could be read."""
    monkeypatch.setattr("kotogen.interactive.status.anki_status",
                        _fake_status(AnkiStatus(connected=False)))
    monkeypatch.setattr(seen, "recover",
                        lambda deck: pytest.fail("the deck should not be read"))
    feed(monkeypatch, ["s", "h", "d", "b", "b", "q"])
    interactive_argv()
    assert "Anki is not connected" in capsys.readouterr().out


def test_a_refused_forget_leaves_the_history_alone(monkeypatch):
    """The question defaults to "no", and a refusal reopens the list."""
    seen.mark("audio", "nhk", "ne1", "Article")
    feed(monkeypatch, ["s", "h", "1", "", "b", "b", "q"])
    interactive_argv()
    assert seen.load("audio", "nhk") == {"ne1": "Article"}


def test_an_empty_history_says_so_instead_of_an_empty_list(monkeypatch, capsys):
    """Empty, the screen still opens: on a new machine, taking back from the deck
    is what it is for."""
    feed(monkeypatch, ["s", "h", "b", "b", "q"])
    interactive_argv()
    out = capsys.readouterr().out
    assert "the history is empty" in out
    assert "Take back from the deck" in out
    # And the settings line already says it, before one opens the screen.
    assert "Source history" in out


def test_the_way_back_is_a_key_not_a_line(keys, capsys):
    """Driven by keys, a menu has no "Back" entry to cross with the arrow: its
    footer names Escape instead."""
    keys([keyboard.ESC])
    with pytest.raises(interactive.screen._Back):
        interactive.screen._menu("", [("a", "first")], allow_back=True)
    out = capsys.readouterr().out
    assert "Back" not in out
    assert "Escape to go back" in out


def test_b_goes_back_although_unlisted(keys):
    """"b" is the way back of the questions typed as a line: in a menu driven by
    keys it comes back out like Escape, although no line announces it."""
    keys(["b"])
    with pytest.raises(interactive.screen._Back):
        interactive.screen._menu("", [("a", "first")], allow_back=True)


def test_escape_goes_back_from_a_question(monkeypatch):
    """Escape goes back from a typed question too: it does not end the line, but
    arrives in it as a character, with the Enter typed after it."""
    feed(monkeypatch, ["\x1b"])
    with pytest.raises(interactive.screen._Back):
        interactive.screen._ask("Word or expression", back=True)


def test_escape_is_not_announced(monkeypatch, capsys):
    """"b" is the way back the prompt teaches: it also works where keys are not
    read one by one."""
    feed(monkeypatch, ["\x1b"])
    with pytest.raises(interactive.screen._Back):
        interactive.screen._ask("Word or expression", back=True)
    assert "(b = back)" in capsys.readouterr().out


def test_escape_pressed_goes_back_where_the_keys_are_read(keys, monkeypatch):
    """On a terminal the answer is read key by key: a Windows console would take
    Escape to erase the line, and the question never see it."""
    keys([keyboard.ESC])
    monkeypatch.setattr(keyboard, "available", lambda: True)
    with pytest.raises(interactive.screen._Back):
        interactive.screen._ask("Number of texts to write", "1", back=True)


def test_a_question_with_no_way_back_does_not_read_keys(keys, monkeypatch):
    """Only the questions one can leave: the others keep the line of the
    terminal, its editing and its input method."""
    keys([keyboard.ESC])
    monkeypatch.setattr(keyboard, "available", lambda: True)
    feed(monkeypatch, ["猫"])
    assert interactive.screen._ask("Word or expression") == "猫"


def test_escape_before_an_answer_is_not_a_way_back(monkeypatch):
    """Only a bare Escape goes back: before an answer it is a stray character,
    and cancelling on it would lose what was typed."""
    feed(monkeypatch, ["\x1bとり"])
    assert interactive.screen._ask("Word or expression", back=True) == "\x1bとり"


def test_the_selection_wraps_around(keys):
    """Up on the first line reaches the last, rather than eight presses down."""
    keys([keyboard.UP, keyboard.ENTER])
    assert interactive.screen._menu("", [("a", "first"), ("b", "second")]) == "b"


def test_catalogue_filters_as_you_type(keys, monkeypatch):
    _fake_catalogue(monkeypatch, [_entry("publisher/model-a", 1e-7),
                                  _entry("studio/model-b", 3e-7),
                                  _entry("studio/model-c", 9e-7)])
    # "stu" drops the publisher, the arrow goes down onto the second of the two left
    keys(["s", "t", "u", keyboard.DOWN, keyboard.ENTER])
    feed(monkeypatch, ["n"])
    interactive.models._browse_catalogue()
    assert os.environ["KOTOGEN_MODEL"] == "studio/model-c"


def test_backspace_widens_the_filter_again(keys, monkeypatch, capsys):
    _fake_catalogue(monkeypatch, [_entry("studio/model-b", 3e-7)])
    keys(["s", "t", "u", "x", keyboard.BACKSPACE, keyboard.ENTER])
    feed(monkeypatch, ["n"])
    interactive.models._browse_catalogue()
    out = capsys.readouterr().out
    assert 'No model whose name holds "stux".' in out
    assert os.environ["KOTOGEN_MODEL"] == "studio/model-b"


def test_escape_clears_the_filter_then_returns(keys, monkeypatch):
    _fake_catalogue(monkeypatch, [_entry("studio/model-b", 3e-7)])
    keys(["g", keyboard.ESC, keyboard.ESC])
    with pytest.raises(interactive.screen._Back):
        interactive.models._browse_catalogue()
    assert os.environ["KOTOGEN_MODEL"] == MODEL


def test_f5_refreshes_the_catalogue(keys, monkeypatch):
    refreshes = _fake_catalogue(monkeypatch, [_entry("studio/model-c", 9e-7)])
    keys([keyboard.F5, keyboard.ENTER])
    feed(monkeypatch, ["n"])
    interactive.models._browse_catalogue()
    assert refreshes == [False, True]


def test_a_failed_refresh_keeps_the_models_on_screen(keys, monkeypatch, capsys):
    """F5 offline must not empty the screen: the prices known stay, with the
    reason for their age."""
    from kotogen import catalogue

    served = [catalogue.Catalogue([_entry("studio/model-c", 9e-7)], 1_770_000_000.0),
              catalogue.Catalogue([], None, "no answer")]
    monkeypatch.setattr(catalogue, "load",
                        lambda *, refresh=False, timeout=10: served[bool(refresh)])
    keys([keyboard.F5, keyboard.ENTER])
    feed(monkeypatch, ["n"])
    interactive.models._browse_catalogue()
    out = capsys.readouterr().out
    assert "refresh impossible" in out
    assert os.environ["KOTOGEN_MODEL"] == "studio/model-c"


def test_env_model_belongs_to_its_provider(monkeypatch):
    """KOTOGEN_MODEL does not follow an explicit, different --provider: a model
    name only means something to its own provider, and no other is built in."""
    monkeypatch.setenv("KOTOGEN_PROVIDER", "openrouter")
    monkeypatch.setenv("KOTOGEN_MODEL", "studio/model-b")
    assert chosen_model() == "studio/model-b"
    assert chosen_model("anthropic") == ""


def test_unknown_provider_in_env_is_ignored(monkeypatch):
    """A mistyped .env must not stop one from generating cards."""
    monkeypatch.setenv("KOTOGEN_PROVIDER", "opnai")
    assert default_provider() == "openrouter"


# ── Folder of the cards ───────────────────────────────────────────────────────

@pytest.fixture
def output_folders(monkeypatch, tmp_path):
    """The destinations offered, inside a tmp_path: the real ones depend on the
    machine (and OneDrive moves the Desktop). Hands back the simulated Desktop."""
    monkeypatch.delenv("KOTOGEN_OUTPUT_DIR", raising=False)
    monkeypatch.setattr("kotogen.exporter._known_folder", lambda name: tmp_path / name)
    return tmp_path / "desktop"


def test_closed_anki_says_so_without_naming_the_folder(monkeypatch, capsys, tmp_path):
    """Anki closed, the bracket says "not connected" and nothing more: the folder
    is named at the end of a generation, with the path of the file written."""
    monkeypatch.delenv("KOTOGEN_OUTPUT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    anki_down(monkeypatch)
    feed(monkeypatch, ["q"])
    interactive_argv()
    out = capsys.readouterr().out
    assert _status_bar(out).endswith("Anki [not connected]")
    assert str(Path.cwd()) not in out


def test_refused_key_is_left_to_the_warning_line(monkeypatch, capsys):
    """A refused key reads "not connected", like a closed Anki: the case is rare
    (`apiKey` set by hand), and the warning below names the add-on and setting."""
    monkeypatch.setattr("kotogen.interactive.status.anki_status",
                        _fake_status(AnkiStatus(connected=False, key_refused=True)))
    feed(monkeypatch, ["q"])
    interactive_argv()
    out = capsys.readouterr().out
    assert _status_bar(out).endswith("Anki [not connected]")
    assert "AnkiConnect refuses the key" in out


def test_output_dir_setting_applies_and_is_saved(monkeypatch, capsys, output_folders):
    written: list = []
    monkeypatch.setattr("kotogen.settings.write",
                        lambda name, value: written.append((name, value)) or "/tmp/settings.env")
    # settings; "o"; 4th destination (Documents); back; quit
    feed(monkeypatch, ["s", "o", "4", "b", "q"])
    assert interactive_argv() is None
    assert os.environ["KOTOGEN_OUTPUT_DIR"] == str(output_folders.parent / "documents")
    assert written == [("KOTOGEN_OUTPUT_DIR", str(output_folders.parent / "documents"))]
    # The "o" line of the settings, redrawn, carries the new folder.
    out = capsys.readouterr().out
    settings_line = [l for l in out.splitlines() if l.strip().startswith("o.")][-1]
    assert settings_line.endswith(str(output_folders.parent / "documents"))


def test_the_current_folder_is_marked_in_the_list(monkeypatch, capsys, output_folders):
    """The folder in place is spotted without reading the "Current" line above
    again."""
    monkeypatch.setenv("KOTOGEN_OUTPUT_DIR", str(output_folders))
    feed(monkeypatch, ["s", "o", "b", "b", "q"])
    interactive_argv()
    entry = next(line for line in capsys.readouterr().out.splitlines()
                 if "Desktop" in line)
    assert entry.endswith("(current)")


def test_a_typed_folder_is_created_on_agreement(monkeypatch, output_folders):
    """A missing folder is created when typed, not at the end of a generation."""
    target = output_folders.parent / "mine" / "cards"
    monkeypatch.setattr("kotogen.settings.write", lambda name, value: None)
    # settings; "o"; free entry; path; creation accepted; back; quit
    feed(monkeypatch, ["s", "o", "a", str(target), "y", "b", "q"])
    interactive_argv()
    assert target.is_dir()
    assert os.environ["KOTOGEN_OUTPUT_DIR"] == str(target)


def test_a_refused_creation_returns_to_the_list(monkeypatch, output_folders):
    """Refusing the creation holds nothing and comes back to the list."""
    target = output_folders.parent / "typo"
    # settings; "o"; free entry; path; creation refused; back; back; quit
    feed(monkeypatch, ["s", "o", "a", str(target), "n", "b", "b", "q"])
    assert interactive_argv() is None
    assert not target.exists()
    assert "KOTOGEN_OUTPUT_DIR" not in os.environ


def test_back_from_the_output_dir_menu_changes_nothing(monkeypatch, output_folders):
    feed(monkeypatch, ["s", "o", "b", "b", "q"])
    assert interactive_argv() is None
    assert "KOTOGEN_OUTPUT_DIR" not in os.environ


# ── Display currency ──────────────────────────────────────────────────────────

@pytest.fixture
def rates_known(monkeypatch):
    """Rates known in advance: the screen must never touch the network here."""
    from kotogen import currency
    monkeypatch.setattr(currency, "_table",
                        {"fetched": 0.0, "day": "2026-08-17",
                         "rates": {"EUR": 0.86259, "JPY": 159.23}})
    monkeypatch.setattr(currency, "_looked_up", True)
    monkeypatch.delenv("KOTOGEN_CURRENCY", raising=False)


def test_currency_setting_applies_and_is_saved(monkeypatch, capsys, rates_known):
    written: list = []
    monkeypatch.setattr("kotogen.settings.write",
                        lambda name, value: written.append((name, value)) or "/tmp/settings.env")
    # settings; "c"; 2nd currency (the euro); back; quit
    feed(monkeypatch, ["s", "c", "2", "b", "q"])
    assert interactive_argv() is None
    assert os.environ["KOTOGEN_CURRENCY"] == "EUR"
    assert written == [("KOTOGEN_CURRENCY", "EUR")]
    out = capsys.readouterr().out
    assert "Record it" not in out
    # The "c" line of the settings, redrawn, carries the currency and nothing else.
    settings_line = [l for l in out.splitlines() if l.strip().startswith("c.")][-1]
    assert settings_line.endswith("EUR €")
    # The rate is said when choosing, on the currency's line.
    assert "The amounts will show in EUR €. ($1 = €0.8626)" in out


def test_the_current_currency_is_marked_in_the_list(monkeypatch, capsys, rates_known):
    monkeypatch.setenv("KOTOGEN_CURRENCY", "JPY")
    feed(monkeypatch, ["s", "c", "b", "b", "q"])
    interactive_argv()
    entry = next(line for line in capsys.readouterr().out.splitlines()
                 if line.strip().endswith("(current)"))
    assert "JPY" in entry


def test_a_currency_without_a_quote_is_refused_on_the_spot(monkeypatch, capsys,
                                                           rates_known):
    """The typo shows here, not as amounts left in dollars."""
    # settings; "c"; free entry; a code that does not exist; back; back; quit
    feed(monkeypatch, ["s", "c", "a", "EURO", "b", "b", "q"])
    assert interactive_argv() is None
    assert "KOTOGEN_CURRENCY" not in os.environ
    out = capsys.readouterr().out
    assert "EURO has no known exchange rate." in out
    assert "Currencies quoted: EUR JPY USD" in out


def test_back_from_the_currency_menu_changes_nothing(monkeypatch, rates_known):
    feed(monkeypatch, ["s", "c", "b", "b", "q"])
    assert interactive_argv() is None
    assert "KOTOGEN_CURRENCY" not in os.environ


def test_the_catalogue_prices_follow_the_currency(monkeypatch, rates_known):
    from kotogen import interactive as ui
    monkeypatch.setenv("KOTOGEN_CURRENCY", "EUR")
    model = {"id": "a/model", "prompt": 0.000003, "completion": 0.000015,
             "cache": True, "context": 200_000}
    # $0.21 for a typical generation (40 000 tokens sent, 6 000 received).
    assert "0.1811 €" in ui.models._catalogue_line(model)


def test_what_a_provider_names_its_models_is_cleaned_on_screen():
    """The names come from the provider's answer: an escape would drive the
    terminal, a line break would split the list."""
    from kotogen import interactive as ui

    line = ui.models._served_line({"id": "model-a", "name": "Model\x1b[2J A\nnew"})
    assert line == "model-a" + " " * 37 + "Model[2J A new"


def test_missing_notetype_is_explained_and_flagged(monkeypatch, capsys):
    """A note type that is absent is detailed at the top and marked on its entry."""
    monkeypatch.setattr("kotogen.interactive.status.anki_status", _fake_status(
        AnkiStatus(connected=True, profile="Test",
                   notetypes=frozenset({"Kanji", "Vocabulary", "Listening", "Reading"}))))
    feed(monkeypatch, ["q"])
    interactive_argv()
    out = capsys.readouterr().out
    # The status line is unchanged: what is missing is reported on the menu entry.
    assert _status_bar(out).endswith("Anki [Test]")
    assert "!!" not in _status_bar(out)
    # The problem and its way out on one line: this block heads every screen.
    warning = next(l for l in out.splitlines() if '"Grammar"' in l)
    assert warning == ('!! Grammar: note type "Grammar" missing'
                       '  -> the "Templates" menu')
    grammar_entry = next(l for l in out.splitlines() if l.strip().startswith("3."))
    assert grammar_entry.endswith("(!)")


def test_section_headers_take_no_number(monkeypatch, capsys):
    """The subheadings take no number: maintain stays the 6th choice, and the
    settings entry takes none either."""
    feed(monkeypatch, ["9", "6", ""])
    assert interactive_argv() == ["maintain", "--scan"]
    assert "a number from 1 to 8" in capsys.readouterr().out


# ── Auto-send ─────────────────────────────────────────────────────────────────

def test_auto_send_skips_the_question(monkeypatch):
    # auto-send on: --send is added without anything being asked
    monkeypatch.setattr(prefs, "_auto_send", True)
    feed(monkeypatch, ["2", "1", "食べる"])
    assert interactive_argv() == ["vocab", "食べる", "--send"]


def test_auto_send_still_sends_when_anki_down(monkeypatch):
    # Anki may be opened during the generation: the send is attempted at the end
    monkeypatch.setattr(prefs, "_auto_send", True)
    anki_down(monkeypatch)
    feed(monkeypatch, ["2", "1", "食べる"])
    assert interactive_argv() == ["vocab", "食べる", "--send"]


def test_a_json_run_is_not_offered_the_send(monkeypatch):
    # JSON Lines is for other tools: neither auto-send nor the question applies
    monkeypatch.setattr(prefs, "_auto_send", True)
    monkeypatch.setenv("KOTOGEN_FORMAT", "json")
    feed(monkeypatch, ["2", "1", "食べる"])
    assert interactive_argv() == ["vocab", "食べる"]


def test_menu_key_toggles_auto_send(monkeypatch):
    # settings; "s" toggles the preference without leaving the screen; back; vocab
    feed(monkeypatch, ["s", "s", "b", "2", "1", "食べる"])
    assert interactive_argv() == ["vocab", "食べる", "--send"]
    assert prefs.auto_send() is True


# ── Audio compression ─────────────────────────────────────────────────────────

def test_menu_key_cycles_the_audio_compression(monkeypatch, capsys):
    """Each "q" moves one notch, on the spot: two lead from "none" to "medium",
    the word the file and `--audio-quality` use too."""
    feed(monkeypatch, ["s", "q", "q", "b", "q"])  # settings; q; q; back; quit
    interactive_argv()
    assert audio_quality.code() == "medium"
    out = capsys.readouterr().out
    screen = out[out.rindex("\nSettings\n"):]
    assert "Audio compression       medium" in screen


def test_the_equivalent_command_carries_the_compression(monkeypatch):
    """The dialogue never asks for the compression, but the command carries it
    once off its default, so that it replays the same elsewhere."""
    monkeypatch.setattr(audio_quality, "_code", "strong")
    feed(monkeypatch, ["4", "", "", "", "", "", ""])
    assert interactive_argv() == ["audio", "nhk", "--audio-quality", "strong"]


def test_the_default_compression_stays_out_of_the_command(monkeypatch):
    feed(monkeypatch, ["4", "", "", "", "", "", ""])
    assert interactive_argv() == ["audio", "nhk"]


def test_send_flag_is_resolved_from_preference(monkeypatch):
    # with neither --send nor --no-send, it is the preference that decides CLI-side
    from kotogen import cli
    from kotogen.generators import vocab

    monkeypatch.setattr(prefs, "_auto_send", True)
    assert build_parser().parse_args(["vocab", "食べる"]).send is None  # unresolved at parsing
    got = {}
    monkeypatch.setattr(vocab, "run_vocab", lambda a: got.update(send=a.send))
    cli._run(["vocab", "食べる"])
    assert got == {"send": True}


def test_no_send_beats_the_preference(monkeypatch):
    monkeypatch.setattr(prefs, "_auto_send", True)
    args = build_parser().parse_args(["vocab", "食べる", "--no-send"])
    assert args.send is False


# ── The toggles are held too ──────────────────────────────────────────────────
# What is checked: the value a toggle sets survives the next launch.

@pytest.mark.parametrize("key, name, expected", [
    ("s", "KOTOGEN_AUTO_SEND", "1"),
    ("v", "KOTOGEN_VERBOSE", "1"),
    ("i", "KOTOGEN_VIDEO", "always"),
    ("q", "KOTOGEN_AUDIO_QUALITY", "light"),
    ("p", "KOTOGEN_PROOFREAD", "keep"),
])
def test_a_toggle_is_saved_like_the_rest(monkeypatch, capsys, key, name, expected):
    written: list = []
    monkeypatch.setattr("kotogen.settings.write",
                        lambda n, value: written.append((n, value)) or "/tmp/settings.env")
    feed(monkeypatch, ["s", key, "b", "q"])
    assert interactive_argv() is None
    assert written == [(name, expected)]
    # A toggle says nothing: the value redrawn beside its key is the answer.
    assert "Recorded in" not in capsys.readouterr().out


def test_the_language_of_the_cards_is_chosen_from_the_settings_too(
        monkeypatch, capsys, templates_profile):
    """"g", under "l", is the one place the language of the cards is set. It is
    kept in `templates.env` with the other card choices, never in the `.env`."""
    written: list = []
    monkeypatch.setattr("kotogen.settings.write",
                        lambda name, value: written.append((name, value)))
    # French by its rank in the list, which is not always the second: the
    # languages are the folders of `prompts/`, in the order of their codes.
    french = str(card_templates.LANGUAGE.positions.index("fr") + 1)
    feed(monkeypatch, ["s", "g", french, "b", "q"])
    assert interactive_argv() is None
    assert card_templates.value("all.lang") == "fr"
    assert written == []
    # Code and name, the name in the language of the screen: English here, while
    # the cards have gone French.
    screen = capsys.readouterr().out
    screen = screen[screen.rindex("\nSettings\n"):]
    assert "Language of the cards" in screen
    assert "fr - French" in screen


def test_the_languages_are_chosen_from_a_list_of_what_exists(
        monkeypatch, capsys, templates_profile):
    """Both languages are picked from a list, not stepped through: one press too
    many could leave the screen in a language one cannot read. Each list shows
    the code and the name, in the language itself for the screens and in the
    screen's for the cards. Going back from either changes nothing."""
    monkeypatch.setattr("kotogen.settings.write", lambda name, value: None)
    feed(monkeypatch, ["s", "l", "b", "g", "b", "b", "q"])
    assert interactive_argv() is None
    screens = capsys.readouterr().out.split("\nSettings\n")
    # Each cut opens on the settings and closes on the screen its key opened.
    interface, cards = screens[1], screens[2]
    assert "en  English" in interface and "fr  Français" in interface
    assert "en  English" in cards and "fr  French" in cards
    assert i18n.language() == "en"
    assert card_templates.value("all.lang") == "en"


def test_the_language_chosen_is_held_and_the_screen_comes_back_translated(
        monkeypatch, capsys):
    """Unlike the other values, the language reloads the table: the labels come
    back translated, which is the whole answer. It is saved like the rest."""
    written: list = []
    monkeypatch.setattr("kotogen.settings.write",
                        lambda name, value: written.append((name, value)))
    # French by its rank among the tables of `locales/`: not always the second.
    french = str(i18n.available().index("fr") + 1)
    feed(monkeypatch, ["s", "l", french, "b", "q"])
    assert interactive_argv() is None
    assert written == [("KOTOGEN_LANG", "fr")]
    out = capsys.readouterr().out
    settings_screen = out[out.rindex("\nRéglages\n"):]
    assert "Langue de l'interface" in settings_screen
    assert "fr - Français" in settings_screen
    # The main menu speaks it too: the language is the session's.
    assert "Réglages" in out[out.rindex("AI ["):]


def test_the_folders_line_up_whatever_the_language(monkeypatch, capsys, output_folders):
    """A Japanese folder name takes two columns a character: padded by `len`, its
    path would start further right than the others."""
    from kotogen import console

    root = str(output_folders.parent)
    monkeypatch.chdir(root)
    monkeypatch.setattr(i18n, "_language", "ja")
    monkeypatch.setattr(i18n, "_catalogue", {"Current folder": "現在のフォルダ",
                                             "Desktop": "デスクトップ"})
    feed(monkeypatch, ["s", "o", "b", "b", "q"])
    interactive_argv()
    lines = [line for line in capsys.readouterr().out.splitlines()
             if ("現在のフォルダ" in line or "デスクトップ" in line) and root in line]
    assert len(lines) == 2
    assert len({console.width(line[:line.index(root)]) for line in lines}) == 1
