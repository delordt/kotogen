"""A minimal AnkiConnect client (stdlib), shared by every module of the adapter."""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass

from kotogen import settings
from kotogen.i18n import _

# 127.0.0.1 rather than localhost: on Windows localhost resolves first to ::1,
# where AnkiConnect does not listen, and each request loses two seconds there.
ANKICONNECT_URL = "http://127.0.0.1:8765"

# Said the same way for every connection failure (Anki closed, addon missing);
# the system error stays on the exception, shown with KOTOGEN_DEBUG=1. English,
# translated where raised: `_()` at import would run before the settings load.
UNREACHABLE = "AnkiConnect unreachable. Is Anki open with the AnkiConnect addon?"

# The addon answers, but its `apiKey` setting requires a key the .env must supply.
BAD_KEY = ("AnkiConnect refuses the key: its `apiKey` setting requires one, "
           "and KOTOGEN_ANKICONNECT_KEY must carry the same value.")

# Anki writes no flag or note type while the browser or an Add or Edit window is
# open, whatever card it shows. Every later write would fail the same way, hence
# an exception of its own: a pass stops on the first one.
EDITOR_OPEN = ("Anki refuses to write while one of its editing windows is open. "
               "Close the browser, and any Add or Edit window, then run again.")


class EditorOpen(RuntimeError):
    """A write refused because an editing window is open in Anki."""


def url() -> str:
    """AnkiConnect's address: the default, or KOTOGEN_ANKICONNECT_URL if set.

    Read at call time: the settings load after this module is imported. The
    scheme may be left out (`127.0.0.1:8766`), urllib refusing a URL without one.
    """
    custom = settings.raw("KOTOGEN_ANKICONNECT_URL")
    if not custom:
        return ANKICONNECT_URL
    return custom if "://" in custom else f"http://{custom}"


def _api_key() -> str:
    """The key the addon expects when its `apiKey` setting is filled in.

    Empty by default, and the `key` field is then not sent at all.
    """
    return settings.raw("KOTOGEN_ANKICONNECT_KEY")


def request(action: str, *, timeout: float = 60, **params):
    """An AnkiConnect call; returns the `result` field of the response.

    Raises ConnectionError if Anki is unreachable, RuntimeError if the action
    fails on the Anki side (non-empty `error` field), and EditorOpen, a
    RuntimeError, when an editing window is open.
    """
    body = {"action": action, "version": 6, "params": params}
    if key := _api_key():
        body["key"] = key
    req = urllib.request.Request(url(), data=json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
    except Exception as exc:
        raise ConnectionError(_(UNREACHABLE)) from exc
    if error := result.get("error"):
        # "valid api key must be provided" and "Close the affected editor before
        # this API write" come back on any action and are not its fault.
        if "api key" in error.lower():
            raise RuntimeError(_(BAD_KEY))
        if "editor" in error.lower():
            raise EditorOpen(_(EDITOR_OPEN))
        raise RuntimeError(_("Anki refused {action}: {error}")
                           .format(action=action, error=error))
    return result.get("result")


# -- Connection status --------------------------------------------------------

@dataclass(frozen=True)
class AnkiStatus:
    """A snapshot of Anki's state: reachable, profile open, decks, note types."""

    connected: bool
    profile: str = ""
    decks: frozenset[str] = frozenset()
    notetypes: frozenset[str] = frozenset()
    # Open but refusing the key: the menu says so rather than "not connected".
    key_refused: bool = False


# The menu, the send question and the media copy ask back to back; a TTL this
# short still sees an Anki opened in the meantime.
_STATUS_TTL = 3.0
_status_cache: tuple[float, AnkiStatus] | None = None


def _try(action: str, timeout: float):
    """A call that returns None instead of raising (status, no consequence)."""
    try:
        return request(action, timeout=timeout)
    except (ConnectionError, RuntimeError):
        return None


def status(*, refresh: bool = False, timeout: float = 2) -> AnkiStatus:
    """AnkiConnect's current state, possibly served from the cache.

    `refresh=True` forces a real query, as the menu and a send do.
    """
    global _status_cache
    now = time.monotonic()
    if not refresh and _status_cache and now - _status_cache[0] < _STATUS_TTL:
        return _status_cache[1]
    try:
        request("version", timeout=timeout)
    except ConnectionError:
        state = AnkiStatus(connected=False)
    except RuntimeError as exc:
        # `version` is the one action no version of the addon refuses: an error
        # answer here is the key, not the action.
        state = AnkiStatus(connected=False, key_refused=_(BAD_KEY) in str(exc))
    else:
        state = AnkiStatus(
            connected=True,
            profile=_try("getActiveProfile", timeout) or "",
            decks=frozenset(_try("deckNames", timeout) or ()),
            notetypes=frozenset(_try("modelNames", timeout) or ()),
        )
    _status_cache = (now, state)
    return state
