"""AI provider abstraction.

OpenRouter: stdlib only (urllib) - no pip install required.
Anthropic:  needs `pip install anthropic`
OpenAI:     needs `pip install openai`
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from kotogen import console, currency, settings, system
from kotogen.i18n import _, convention, listed, quoted, sentence

MAX_RETRIES = 3
RETRY_DELAYS = [5, 15, 30]  # seconds between attempts


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

# The environment variable carrying the key, per provider.
KEY_VARS = {
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}

# HTTP codes no retry settles: the account or the key needs correcting. Each
# carries the whole line, what blocks and where to correct it.
FATAL_AUTH_CODES = {
    401: "{var} API key refused - correct it under Settings > API key",
    402: "not enough {provider} credit - top the account up",
    403: "{var} API key has no right to this model - see Settings > AI model",
}


def _network_reason(exc: BaseException | None) -> str:
    """What can be said of a network failure without copying the system message.

    The network, the wait or the service; urllib's own detail stays on the
    exception, shown with KOTOGEN_DEBUG=1."""
    if isinstance(exc, urllib.error.HTTPError):
        return _("the service answered HTTP {code}").format(code=exc.code)
    if isinstance(exc, TimeoutError) or (
            isinstance(exc, urllib.error.URLError)
            and isinstance(exc.reason, TimeoutError)):
        return _("timed out")
    return _("network unreachable")


# -- Consumption --------------------------------------------------------------
# What each run cost, counted here where every call goes through, and shown at
# the end of the command.


@dataclass
class Usage:
    """The total of the AI calls: number, tokens, cost when the service prices
    it, and elapsed time."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # The share of the tokens sent that the provider's cache served, billed at a
    # fraction of the price. Counted but not shown: the price reflects it.
    cached_tokens: int = 0
    cost: float = 0.0
    # True once a call returned its cost, which the native SDKs never do: the
    # tokens are then shown rather than a "$0.00". `cost` is in dollars, the
    # display currency being `currency`'s business.
    priced: bool = False
    # The command's stopwatch, not the sum of the calls: the wait endured, the
    # send to Anki included. Filled in by `finish_run`.
    seconds: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, prompt: int, completion: int, cost: float | None,
            cached: int = 0) -> None:
        self.calls += 1
        self.prompt_tokens += max(0, prompt)
        self.completion_tokens += max(0, completion)
        self.cached_tokens += max(0, cached)
        if cost is not None:
            self.cost += cost
            self.priced = True

    def summary(self) -> str:
        """What the AI has cost, in one line. "" before the first call.

        The calls, then the price (the tokens where the provider prices nothing)
        and the duration once `finish_run` has filled it. The same line on every
        screen that shows it.
        """
        if not self.calls:
            return ""
        parts = [currency.format_cost(self.cost) if self.priced
                 else _("{count} tokens").format(
                     count=_thousands(self.total_tokens))]
        if self.seconds:
            parts.append(format_duration(self.seconds))
        return (_("{count} AI {calls}").format(
            count=self.calls, calls=console.plural(self.calls, "call"))
            + " (" + listed(parts) + ")")


def _thousands(n: int) -> str:
    """12345 -> "12,345" in English, "12 345" in French."""
    return f"{n:,}".replace(",", convention("thousands_separator", ","))


def format_duration(seconds: float) -> str:
    """A readable duration: "4.2 s", "47 s", "2 min 05 s", "1 h 12 min".

    A decimal only under ten seconds, where it still tells two runs apart."""
    if seconds < 10:
        return _("{seconds} s").format(
            seconds=f"{seconds:.1f}".replace(".", convention("decimal_point", ".")))
    minutes, secs = divmod(round(seconds), 60)
    if not minutes:
        return _("{seconds} s").format(seconds=secs)
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return _("{minutes} min {seconds} s").format(minutes=minutes, seconds=f"{secs:02d}")
    return _("{hours} h {minutes} min").format(hours=hours, minutes=f"{minutes:02d}")


_run_usage = Usage()      # reset on every command
_session_usage = Usage()  # the session total (the interactive loop)
_run_started: float | None = None  # the stopwatch of the command in progress
# The models the command in progress has set to work, in the order it did: what
# a file of cards says wrote them (see `exporter`).
_run_models: list[str] = []


def record_usage(prompt: int, completion: int, cost: float | None = None,
                 cached: int = 0) -> None:
    """Account for one AI call (called by all three providers)."""
    _run_usage.add(prompt, completion, cost, cached)
    _session_usage.add(prompt, completion, cost, cached)


def run_usage() -> Usage:
    """The consumption of the command in progress."""
    return _run_usage


def session_usage() -> Usage:
    """The consumption totalled since the program started."""
    return _session_usage


def run_models() -> list[str]:
    """The models the command in progress has set to work, each once."""
    return list(_run_models)


def reset_run_usage() -> None:
    """Start again from zero for a new command (the interactive loop chains them).

    Also starts the stopwatch, called after the dialogue: only the wait is timed."""
    global _run_usage, _run_started
    _run_usage = Usage()
    _run_started = time.monotonic()
    _run_models.clear()


def finish_run() -> Usage:
    """Stop the stopwatch and return the summary of the command.

    The stopwatch is cleared once read: a second call adds no duration, and a
    command that never started gets none."""
    global _run_started
    if _run_started is not None:
        elapsed = time.monotonic() - _run_started
        _run_usage.seconds += elapsed
        _session_usage.seconds += elapsed
        _run_started = None
    return _run_usage


def _int(value: Any) -> int:
    """The integer of a usage field that may be absent or null."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _record_api_usage(usage: Any) -> None:
    """Record the `usage` block of an OpenRouter HTTP response (OpenAI format).

    Missing or incomplete is tolerated: a counter never fails a generation.
    """
    if not isinstance(usage, dict):
        return
    # `cached_tokens` is a SHARE of prompt_tokens, not an addition to it.
    details = usage.get("prompt_tokens_details")
    cached = _int(details.get("cached_tokens")) if isinstance(details, dict) else 0
    record_usage(
        _int(usage.get("prompt_tokens")),
        _int(usage.get("completion_tokens")),
        _float_or_none(usage.get("cost")),
        cached,
    )


def _sdk_stop_reason(resp: Any) -> str:
    """The stop reason of an SDK response: `stop_reason` (anthropic) or
    `choices[0].finish_reason` (openai). "" if the response carries none."""
    reason = getattr(resp, "stop_reason", None)
    if reason is None:
        choices = getattr(resp, "choices", None) or []
        reason = getattr(choices[0], "finish_reason", None) if choices else None
    return str(reason or "")


def _record_sdk_usage(resp: Any) -> None:
    """Record the usage of an SDK response (anthropic: input/output, openai:
    prompt/completion).

    Neither of them prices the call: only the tokens are known.
    """
    usage = getattr(resp, "usage", None)
    if usage is None:
        return
    prompt = _int(getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None))
    completion = _int(
        getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", None))
    # Anthropic counts cache reads and cache writes apart from input_tokens:
    # folded back in, as OpenRouter counts them, so that totals compare across
    # providers. Only the reads are served from the cache.
    cached = _int(getattr(usage, "cache_read_input_tokens", None))
    written = _int(getattr(usage, "cache_creation_input_tokens", None))
    record_usage(prompt + cached + written, completion, None, cached)


class AIAuthError(RuntimeError):
    """A final AI failure: key, quota or rights. No point retrying.

    The loops over batches and articles, which go on past an incident, stop on
    this one."""


class AITruncatedError(RuntimeError):
    """A response cut off by the token limit: what comes back is incomplete.

    Told apart from invalid JSON, since the fix is to ask for fewer items, and
    never retried: the same call would be cut, and paid for, again."""


# Fragments of the stop reasons that mean a cut: "length" (OpenAI, OpenRouter),
# "max_tokens" (Anthropic), MAX_TOKENS in native_finish_reason (Google).
_TRUNCATION_MARKERS = ("length", "max_token")


def _is_truncated(*reasons: object) -> bool:
    """True if one of the stop reasons given signals a cut-off response."""
    flat = " ".join(str(r or "").lower() for r in reasons)
    return any(marker in flat for marker in _TRUNCATION_MARKERS)


class _CacheRejected(RuntimeError):
    """The provider refused the request carrying the caching instruction.

    Internal: the call is replayed without the cache before anything fails.
    """


# -- Caching the system prompt ------------------------------------------------
# A generator's system prompt runs to thousands of characters and goes out
# unchanged with every batch; Anthropic and Google models bill its re-reads at a
# fraction of the price. Asked only of the models known to take it, and dropped
# for the rest of the command once a call is refused, which is replayed without.

# The models where caching is asked for explicitly. OpenAI does it by itself and
# exposes nothing: the gpt-* models are deliberately not here.
_CACHEABLE_PREFIXES = ("anthropic/", "google/", "claude-")

# Anthropic caches nothing under 1,024 tokens. The vocabulary system prompt
# measures ~2.4 characters per token (Latin and Japanese mixed), so 3,000
# characters clear that minimum with room to spare.
_MIN_CACHE_CHARS = 3000


def _truncated_error(limit: int) -> AITruncatedError:
    return AITruncatedError(
        _("answer cut off at the {limit} token limit - ask for fewer items at a "
          "time (--batch-size, --count).").format(limit=limit)
    )


def key_var(provider: str) -> str:
    """The name of the environment variable carrying this provider's key."""
    return KEY_VARS[provider]


def has_key(provider: str) -> bool:
    """True if a key is available (the settings file, or typed this session)."""
    return bool(settings.raw(KEY_VARS[provider]))


def store_key(provider: str, key: str) -> None:
    """Hold the key for the session: no more typing it on every command."""
    os.environ[KEY_VARS[provider]] = key.strip()


def _extract_json(text: str) -> Any:
    """Extract the first JSON object or array from a text response.

    Every "[" or "{" is tried in turn with `raw_decode`: furigana (`涼[すず]しい`)
    put brackets before the "{" of a card returned without a ```json fence.
    """
    # A markdown ```json ... ``` block
    fence = re.search(r"```(?:json)?\s*(\[[\s\S]*?\]|\{[\s\S]*?\})\s*```", text)
    if fence:
        return json.loads(fence.group(1))

    decoder = json.JSONDecoder()
    starts = sorted(i for i, ch in enumerate(text) if ch in "[{")
    for start in starts:
        try:
            value, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        return value
    raise ValueError(f"No JSON found in the response:\n{text}")


# -- Conversation with tools --------------------------------------------------
# What an agent loop takes: a turn that can, instead of answering, ask for one
# or more tools to be run.

# The providers whose tool calls are driven; `conversation()` says why only one.
TOOL_PROVIDERS = ("openrouter",)


@dataclass(frozen=True)
class ToolCall:
    """A tool the model asks to have run.

    `arguments` stays the JSON string the API returned: the tool registry
    decodes it, and tells the model when it is invalid.
    """

    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class Reply:
    """One turn of answer: text, tool calls, or both."""

    text: str
    calls: tuple[ToolCall, ...]
    message: dict  # to be put back as it is into the history of the next turn

    def __bool__(self) -> bool:
        return bool(self.text or self.calls)


def _text_of_message(message: dict) -> str:
    """The text of a message, whether the content is a string or blocks.

    A tool call often has `content: null`, and some models return text blocks
    `[{"type": "text", ...}]` where others return a string.
    """
    content = message.get("content")
    if isinstance(content, list):
        return "".join(block.get("text", "") for block in content
                       if isinstance(block, dict))
    return content or ""


def no_model(provider: str) -> str:
    """What a command that needs a model says when none is chosen for `provider`."""
    return _("No model chosen for {provider}: pick one in the kotogen menu, {settings} "
             "then {model}, or give it with --model.").format(
        provider=provider, settings=f"{quoted(_('Settings'))} (s)",
        model=f"{quoted(_('AI model'))} (m)")


class AIClient:
    """A unified wrapper around the AI APIs."""

    def __init__(self, provider: str, model: str) -> None:
        if not model:
            # None is built in (see `cli.chosen_model`), and it is said before
            # the key is asked for: without a model there is nothing to call.
            raise SystemExit(no_model(provider))
        self.provider = provider
        self.model = model
        if model and model not in _run_models:
            _run_models.append(model)
        # Goes to False on the first refusal: caching is a billing comfort, not
        # a condition of working.
        self._cache_ok = True

        if provider == "openrouter":
            self._api_key = settings.raw("OPENROUTER_API_KEY") or _prompt_key("OPENROUTER_API_KEY")

        elif provider == "anthropic":
            try:
                import anthropic  # type: ignore
            except ImportError:
                raise SystemExit(_("Missing package. Run: pip install anthropic")) from None
            api_key = settings.raw("ANTHROPIC_API_KEY") or _prompt_key("ANTHROPIC_API_KEY")
            self._client = anthropic.Anthropic(api_key=api_key)

        elif provider == "openai":
            try:
                import openai  # type: ignore
            except ImportError:
                raise SystemExit(_("Missing package. Run: pip install openai")) from None
            api_key = settings.raw("OPENAI_API_KEY") or _prompt_key("OPENAI_API_KEY")
            self._client = openai.OpenAI(api_key=api_key)

        else:
            raise ValueError(f"unknown provider: {provider!r}")

    # -- Caching the system prompt --------------------------------------------

    def _may_cache(self, system: str) -> bool:
        """Should caching of the system prompt be asked for on this call?"""
        return (self._cache_ok
                and len(system) >= _MIN_CACHE_CHARS
                and self.model.startswith(_CACHEABLE_PREFIXES))

    def _drop_cache(self, detail: str = "") -> None:
        """Switch caching off for the rest of the command, and say so.

        Called once a call replayed without the cache has gone through: a request
        refused with and without it was not refused over the cache.
        """
        self._cache_ok = False
        console.item(_("This model would not keep the instructions between calls "
                       "for a lower price: they are sent in full, for this call "
                       "and the rest of the command."))
        if detail:
            console.item(console.INDENT + _short_detail(detail, 160))

    def _system_blocks(self, system: str, cached: bool) -> Any:
        """The system prompt, bare or in a block marked for caching."""
        if not cached:
            return system
        return [{"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}}]

    # ── chat ──────────────────────────────────────────────────────────────────

    def chat(self, system: str, user: str) -> str:
        """Send system + user; return the raw text of the response."""
        if self.provider == "openrouter":
            return self._openrouter_chat(system, user)
        elif self.provider == "anthropic":
            resp = self._sdk_chat(system, 4096, lambda sys_arg: self._client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=sys_arg,
                messages=[{"role": "user", "content": user}],
            ))
            return resp.content[0].text
        else:  # openai
            ceiling = _openai_ceiling(self.model, 4096)
            resp = self._call_sdk(lambda: self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                # The reasoning models refuse `max_tokens`; every chat model
                # of Chat Completions takes this one.
                max_completion_tokens=ceiling,
            ), max_tokens=ceiling)
            return resp.choices[0].message.content

    def chat_json(self, system: str, user: str) -> Any:
        """Like chat() but parses and returns the JSON."""
        raw = self.chat(system, user)
        try:
            return _extract_json(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(
                _("The AI's answer was not in the form asked for.") + "\n\n"
                + _("Raw answer:") + f"\n{raw}"
            ) from exc

    # -- chat with a PDF document attached -------------------------------------
    # The PDF goes out in base64 for the model to read the pages itself, which
    # covers scans and broken CMaps; it takes a multimodal model, as the defaults
    # are. A larger max_tokens: a document of several pages gives long answers.

    _PDF_MAX_TOKENS = 8192

    # -- Conversation with tools ----------------------------------------------

    def conversation(self, system: str, messages: list[dict], tools: list[dict],
                     max_tokens: int = 4096, timeout: int = 180) -> Reply:
        """One turn of conversation where the model may call tools.

        `messages` is the whole history, system prompt aside, sent in full every
        turn; the message returned joins it as it is, then one `tool` message per
        call run. OpenRouter only (TOOL_PROVIDERS): Anthropic's SDK declares and
        returns tool calls in another format, which would go untested.
        """
        if self.provider not in TOOL_PROVIDERS:
            raise ValueError(f"the {self.provider} provider does not drive tools")

        def body(cached: bool) -> dict:
            return {
                "model": self.model,
                "messages": [{"role": "system",
                              "content": self._system_blocks(system, cached)},
                             *messages],
                "tools": tools,
                "tool_choice": "auto",
                "max_tokens": max_tokens,
                "usage": {"include": True},
            }

        message = self._openrouter_post(body, cached=self._may_cache(system),
                                        max_tokens=max_tokens, timeout=timeout)
        calls = tuple(
            ToolCall(str(call.get("id") or ""),
                     call.get("function", {}).get("name", ""),
                     call.get("function", {}).get("arguments", "") or "{}")
            for call in (message.get("tool_calls") or []))
        return Reply(_text_of_message(message), calls, message)

    def chat_pdf(self, system: str, user: str, pdf_bytes: bytes,
                 filename: str = "document.pdf") -> str:
        """Like chat(), with a PDF document attached to the user message."""
        b64 = base64.b64encode(pdf_bytes).decode("ascii")

        if self.provider == "openrouter":
            content = [
                {"type": "text", "text": user},
                {"type": "file", "file": {
                    "filename": filename,
                    "file_data": f"data:application/pdf;base64,{b64}",
                }},
            ]
            # engine "native": the file goes to the model itself, not to a text
            # extractor, which scans and broken CMaps defeat.
            plugins = [{"id": "file-parser", "pdf": {"engine": "native"}}]
            return self._openrouter_chat(system, content, plugins=plugins,
                                         max_tokens=self._PDF_MAX_TOKENS,
                                         timeout=300)

        elif self.provider == "anthropic":
            resp = self._sdk_chat(
                system, self._PDF_MAX_TOKENS,
                lambda sys_arg: self._client.messages.create(
                    model=self.model,
                    max_tokens=self._PDF_MAX_TOKENS,
                    system=sys_arg,
                    messages=[{"role": "user", "content": [
                        {"type": "document", "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": b64,
                        }},
                        {"type": "text", "text": user},
                    ]}],
                ))
            return resp.content[0].text

        else:  # openai
            ceiling = _openai_ceiling(self.model, self._PDF_MAX_TOKENS, pages=True)
            resp = self._call_sdk(lambda: self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": [
                        {"type": "file", "file": {
                            "filename": filename,
                            "file_data": f"data:application/pdf;base64,{b64}",
                        }},
                        {"type": "text", "text": user},
                    ]},
                ],
                max_completion_tokens=ceiling,
            ), max_tokens=ceiling)
            return resp.choices[0].message.content

    def chat_json_pdf(self, system: str, user: str, pdf_bytes: bytes,
                      filename: str = "document.pdf") -> Any:
        """Like chat_pdf() but parses and returns the JSON."""
        raw = self.chat_pdf(system, user, pdf_bytes, filename)
        try:
            return _extract_json(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(
                _("The AI's answer was not in the form asked for.") + "\n\n"
                + _("Raw answer:") + f"\n{raw}"
            ) from exc

    # -- OpenRouter (stdlib urllib, no pip install) ----------------------------

    def _openrouter_chat(self, system: str, user, plugins: list | None = None,
                         max_tokens: int = 4096, timeout: int = 120) -> str:
        """`user`: plain text, or a list of content blocks (text + file)."""
        def body(cached: bool) -> dict:
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self._system_blocks(system, cached)},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
                # The `usage` block then carries the real cost of the model
                # served, with no price table to keep.
                "usage": {"include": True},
            }
            if plugins:
                payload["plugins"] = plugins
            return payload

        message = self._openrouter_post(body, cached=self._may_cache(system),
                                        max_tokens=max_tokens, timeout=timeout)
        return message["content"]

    def _openrouter_post(self, body, *, cached: bool, max_tokens: int,
                         timeout: int) -> dict:
        """Send the body built by `body(cached)`; return the message received.

        A function, since a call refused over caching is replayed with the body
        rebuilt (`_system_blocks` changes shape). The whole message comes back:
        a tool call carries `tool_calls` rather than `content`.
        """
        data = json.dumps(body(cached)).encode("utf-8")

        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            req = urllib.request.Request(
                OPENROUTER_BASE_URL,
                data=data,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
            def call(req=req):
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))

            try:
                # A call can stay silent for two minutes: the action line turns.
                result = console.while_working(call)

                if "error" in result:
                    raise RuntimeError(
                        _("OpenRouter error: {error}").format(error=result["error"]))

                # Recorded before any check: a cut-off response is billed too.
                _record_api_usage(result.get("usage"))
                choice = (result.get("choices") or [{}])[0]
                if _is_truncated(choice.get("finish_reason"),
                                 choice.get("native_finish_reason")):
                    raise _truncated_error(max_tokens)
                return choice["message"]

            # HTTPError first: a subclass of URLError, it would otherwise pass
            # for a network failure and retry a refused key.
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace").strip()
                if exc.code in FATAL_AUTH_CODES:
                    raise self._auth_error(exc.code, detail) from exc
                # 429 (the per-minute quota) and 5xx are passing -> we retry;
                # the other 4xx (an invalid request or model) are not.
                if exc.code != 429 and exc.code < 500:
                    # Unless caching was asked for, the first suspect: the call
                    # is replayed once without it (`cached` False, so no loop),
                    # and the replay's own error is the one raised.
                    if cached:
                        message = self._openrouter_post(
                            body, cached=False, max_tokens=max_tokens,
                            timeout=timeout)
                        self._drop_cache(detail)
                        return message
                    raise RuntimeError(
                        _("OpenRouter HTTP {code} error: {detail}").format(
                            code=exc.code, detail=detail)) from exc
                last_exc = exc
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    console.item(_("HTTP {code}, trying again in {delay}s...")
                                 .format(code=exc.code, delay=delay))
                    time.sleep(delay)

            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                last_exc = exc
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    console.item(_("{reason}, trying again in {delay}s...")
                                 .format(reason=_network_reason(exc), delay=delay))
                    time.sleep(delay)

        raise RuntimeError(
            _("Failed after {count} attempts: {reason}.").format(
                count=MAX_RETRIES, reason=_network_reason(last_exc))
        )

    # -- Errors ----------------------------------------------------------------

    def _auth_error(self, code: int, detail: str) -> AIAuthError:
        """A fatal failure brought back to one line: what blocks, where to fix it.

        The provider's body says nothing the code does not; KOTOGEN_DEBUG=1 adds it."""
        reason = FATAL_AUTH_CODES.get(code)
        reason = _(reason) if reason else _("call refused (HTTP {code})").format(code=code)
        message = sentence(reason.format(var=KEY_VARS[self.provider],
                                         provider=self.provider))
        if detail and settings.flag("KOTOGEN_DEBUG"):
            message += "\n   " + _("Answer from the service: {detail}").format(
                detail=_short_detail(detail))
        return AIAuthError(message)

    def _sdk_chat(self, system: str, max_tokens: int, build):
        """An SDK call with a fallback if caching the system prompt is refused.

        `build(system_arg)` builds the call from the system prompt, bare or in a
        cached block. A refusal is replayed once without the cache, and switches
        it off only if the replay goes through; otherwise the replay's error is raised.
        """
        cached = self._may_cache(system)
        try:
            return self._call_sdk(lambda: build(self._system_blocks(system, cached)),
                                  max_tokens=max_tokens, cached=cached)
        except _CacheRejected as exc:
            resp = self._call_sdk(lambda: build(system), max_tokens=max_tokens)
            self._drop_cache(str(exc))
            return resp

    def _call_sdk(self, call, max_tokens: int = 4096, cached: bool = False):
        """Run an SDK call (anthropic/openai), translating key and quota errors.

        Both SDKs carry the HTTP code on `status_code`, whatever their exception
        classes."""
        try:
            # The spinner, as for OpenRouter.
            resp = console.while_working(call)
        except Exception as exc:
            code = getattr(exc, "status_code", None)
            if code in FATAL_AUTH_CODES:
                raise self._auth_error(code, str(exc)) from exc
            # Refused while caching was asked for: the caller replays it without.
            if cached and code in (400, 422):
                raise _CacheRejected(str(exc)) from exc
            raise
        _record_sdk_usage(resp)
        if _is_truncated(_sdk_stop_reason(resp)):
            raise _truncated_error(max_tokens)
        return resp


# -- Helpers ------------------------------------------------------------------

# OpenAI's reasoning models (the o-series, gpt-5) count their reasoning in
# `max_completion_tokens`: a ceiling sized for the answer alone comes back cut,
# its content empty. The oldest families refuse a ceiling above their maximum.
_OPENAI_LEGACY = re.compile(r"(^|:)gpt-(3\.5|4)(-|:|$)")
_OPENAI_REASONING = re.compile(r"(^|:)(o\d|gpt-5)")
_OPENAI_ROOM = 16000          # under the 16384 of gpt-4o, the smallest left
_OPENAI_PDF_ROOM = 32000      # a reasoning model reading pages thinks at length


def _openai_ceiling(model: str, answer: int, *, pages: bool = False) -> int:
    """The `max_completion_tokens` that leaves an OpenAI model room for `answer`
    tokens of answer; `pages` for a PDF attached."""
    if _OPENAI_LEGACY.search(model):
        return answer
    if pages and _OPENAI_REASONING.search(model):
        return _OPENAI_PDF_ROOM
    return _OPENAI_ROOM


def _short_detail(detail: str, limit: int = 300) -> str:
    """An error response brought back to one readable line (JSON bodies are long)."""
    flat = " ".join(console.clean(detail).split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def _prompt_key(var: str) -> str:
    """Ask the user for the API key if it is set nowhere.

    Held in the environment, then saved for later runs; a failed save does not
    fail the command. Typed in stars, as in the menu, so a paste is seen to arrive.
    Without a terminal it stops: on Windows `getpass` reads the console whatever
    the input, and a script would wait for ever."""
    if not system.can_ask():
        raise SystemExit(_("{var} is not set, and there is no terminal to type it in: "
                           "set it in the environment or in {path}.").format(
            var=var, path=settings.path_for(var)))
    console.space()
    print(_("{var} is not set.").format(var=var))
    key = console.read_secret("   " + _("Enter the key: ")).strip()
    if not key:
        raise SystemExit(_("No key given for {var}.").format(var=var))
    os.environ[var] = key
    try:
        settings.write(var, key)
    except OSError as exc:
        # Only a failed save is said.
        console.item(_("Cannot write ({error}): the key is kept for this run.")
                     .format(error=console.reason(exc)))
    return key
