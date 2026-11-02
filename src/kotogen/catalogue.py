"""The models the providers really serve: the OpenRouter catalogue with the
day's prices, and the lists Anthropic and OpenAI give a key.

The catalogue is read from a public endpoint (no key, no tokens spent): ids,
per-token prices, context length and input modalities, so the menu sorts by
price without a hand-kept table. Cached on disk for a week; a stale cache beats
nothing. The two lists are read afresh: they are short, and a key may be served
models another is not.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, NamedTuple

from kotogen.exporter import cache_dir
from kotogen.i18n import _

MODELS_URL = "https://openrouter.ai/api/v1/models"

# Where Anthropic and OpenAI list the models a key may call: no tokens spent.
SERVED_URLS = {
    "anthropic": "https://api.anthropic.com/v1/models?limit=1000",
    "openai": "https://api.openai.com/v1/models",
}

# The catalogue moves by a few models a week: beyond that, we ask again.
MAX_AGE_SECONDS = 7 * 24 * 3600

# Prices are shown per typical command, the unit of the end-of-command summary,
# rather than per token. Volumes measured on a vocabulary generation from a PDF
# (7 calls, cached system prompt included).
REFERENCE_PROMPT_TOKENS = 40_000
REFERENCE_COMPLETION_TOKENS = 6_000


class Catalogue(NamedTuple):
    """Usable models, sorted from the cheapest to the dearest.

    `fetched` is None if nothing could ever be read. `error` holds the last
    failure even when models are returned: they then come from a stale cache,
    and the screen must say so."""

    models: list[dict]
    fetched: float | None = None
    error: str = ""


def command_cost(model: dict) -> float:
    """The estimated price of a typical generation, in dollars."""
    return (REFERENCE_PROMPT_TOKENS * model["prompt"]
            + REFERENCE_COMPLETION_TOKENS * model["completion"])


def _typable(model_id: object) -> bool:
    """True if this id can be typed and filed: chosen, it goes into the settings
    file, where a line break would write a second setting."""
    return (isinstance(model_id, str) and bool(model_id)
            and all(char.isprintable() and not char.isspace() for char in model_id))


def _usable(raw: dict) -> bool:
    """Can this model serve *every* command of the project?

    It must take a file as input, since PDFs are sent as they are
    (`pdf_source`), and be billed: the free variants allow a few requests a
    minute, and a generation chains dozens.
    """
    architecture = raw.get("architecture") or {}
    pricing = raw.get("pricing") or {}
    try:
        prompt = float(pricing.get("prompt") or 0)
        completion = float(pricing.get("completion") or 0)
    except (TypeError, ValueError):
        return False
    return (_typable(raw.get("id"))
            and "text" in (architecture.get("output_modalities") or [])
            and "file" in (architecture.get("input_modalities") or [])
            and prompt > 0 and completion > 0)


def _trim(payload: Any) -> list[dict]:
    """Cut the response down to the usable models and the fields that serve.

    Prices stay per token, so the yardstick can change without downloading again.
    500 KB of response fit in about fifteen."""
    raw_models = payload["data"] if isinstance(payload, dict) else payload
    models = [
        {
            "id": raw["id"],
            "name": raw.get("name") or raw["id"],
            "prompt": float(raw["pricing"]["prompt"]),
            "completion": float(raw["pricing"]["completion"]),
            # Caching the system prompt cuts the bill of the following batches:
            # worth a column (see ai_client).
            "cache": bool(raw["pricing"].get("input_cache_read")),
            "context": int(raw.get("context_length") or 0),
        }
        for raw in raw_models if _usable(raw)
    ]
    return sorted(models, key=command_cost)


def _fetch(timeout: int) -> list[dict]:
    req = urllib.request.Request(MODELS_URL, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return _trim(json.loads(resp.read().decode("utf-8")))


def cache_file() -> Path:
    return cache_dir() / "openrouter-models.json"


def _read_cache() -> Catalogue | None:
    path = cache_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Catalogue([model for model in data["models"] if _typable(model.get("id"))],
                         float(data["fetched"]))
    except (OSError, ValueError, KeyError, TypeError):
        # Missing, truncated or of another format: treated as absent, rewritten.
        return None


def _write_cache(models: list[dict], fetched: float) -> None:
    path = cache_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"fetched": fetched, "models": models}),
                        encoding="utf-8")
    except OSError:
        pass  # full disk, read-only folder: we do without


def _reason(exc: Exception, provider: str = "OpenRouter") -> str:
    """A line fit for the screen, made out of the network exception.

    Not the system message ("[WinError 10061] ..."), which needs translating;
    an HTTP code is kept, since it tells a service outage from a severed network."""
    if isinstance(exc, urllib.error.HTTPError):
        return _("{provider} answered {code}").format(provider=provider, code=exc.code)
    if isinstance(exc, urllib.error.URLError):
        return _("no answer")
    return _("unreadable answer")


def load(*, refresh: bool = False, timeout: int = 10) -> Catalogue:
    """The catalogue, from the cache if it is fresh, from the network if not.

    Never raises: an unreachable catalogue only leaves the screen fewer models."""
    cached = _read_cache()
    if (not refresh and cached
            and time.time() - cached.fetched < MAX_AGE_SECONDS):
        return cached
    try:
        models = _fetch(timeout)
    except (urllib.error.URLError, OSError, TimeoutError,
            ValueError, KeyError, TypeError) as exc:
        # Offline: a stale cache still ranks the models by price.
        reason = _reason(exc)
        return cached._replace(error=reason) if cached else Catalogue([], None, reason)
    fetched = time.time()
    _write_cache(models, fetched)
    return Catalogue(models, fetched)


def _listed(payload: Any) -> list[dict]:
    """The models of a `/v1/models` answer, the newest first.

    Anthropic answers newest first and names its models; OpenAI answers in no
    order, each model with its date of creation."""
    rows = [raw for raw in payload["data"] if _typable(raw.get("id"))]
    if all(isinstance(raw.get("created"), int) for raw in rows):
        rows.sort(key=lambda raw: raw["created"], reverse=True)
    return [{"id": raw["id"], "name": raw.get("display_name") or ""} for raw in rows]


# OpenAI's `/v1/models` lists every model of the account, those the Chat
# Completions API that `ai_client` calls does not serve included: the ones that
# never chat, the older completions, and the families served only through the
# Responses API. Anthropic's lists chat models only. Fragments of family names,
# not models: no model name is built in (docs/global-options.md, `--model`).
_NOT_CHAT = ("embedding", "tts", "whisper", "dall-e", "moderation", "image", "audio",
             "realtime", "transcribe", "search", "sora", "instruct", "davinci",
             "babbage", "computer-use", "codex", "deep-research", "-pro")


def _chats(models: list[dict]) -> list[dict]:
    """The models of the list that can chat, by what their ids say they are."""
    return [model for model in models
            if not any(family in model["id"].lower() for family in _NOT_CHAT)]


def served(provider: str, key: str, *, timeout: int = 10) -> Catalogue:
    """The models Anthropic or OpenAI serve to this key, the newest first.

    Never raises: what stood in the way is in `error`, a refused key said as such."""
    headers = {"Accept": "application/json"}
    if provider == "anthropic":
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    else:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(SERVED_URLS[provider], headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            models = _listed(json.loads(resp.read().decode("utf-8")))
    except urllib.error.HTTPError as exc:
        reason = (_("{provider} refuses the key").format(provider=provider)
                  if exc.code in (401, 403) else _reason(exc, provider))
        return Catalogue([], None, reason)
    except (urllib.error.URLError, OSError, TimeoutError,
            ValueError, KeyError, TypeError) as exc:
        return Catalogue([], None, _reason(exc, provider))
    if provider == "openai":
        models = _chats(models)
    return Catalogue(models, time.time())
