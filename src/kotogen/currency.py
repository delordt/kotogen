"""Display currency: the bill is in dollars, the screen is not bound to be.

The day's ECB rate (frankfurter.app, public, no key) is applied at display time
only. It is cached for a day and never fails a command: offline, the last known
rate serves, then a hard-coded one. In dollars, the default, none of it runs.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import NamedTuple

from kotogen import i18n, settings, system

RATES_URL = "https://api.frankfurter.app/latest?from=USD"

# The reference rates come out once per working day.
MAX_AGE_SECONDS = 24 * 3600

# The billing currency, hence the one that needs neither a rate nor a network.
DEFAULT_CODE = "USD"

# Symbols of the common currencies; a code absent from here is shown as it is
# ("12.30 SEK"). The ECB, not this table, says which currencies have a rate.
SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "JPY": "¥",
    "GBP": "£",
    "CHF": "CHF",
    "CAD": "CA$",
    "AUD": "A$",
    "CNY": "CN¥",
    "KRW": "₩",
    "INR": "₹",
    "BRL": "R$",
}

# Offered by the menu: the billing currency, the euro (the other one most bills
# are paid in) and the yen. Any other is typed in by its code.
MENU_CODES = ("USD", "EUR", "JPY")

# Last resort, with neither network nor cache: the rates of 2026-08-17, there
# only to give a summary the right order of magnitude.
FALLBACK_RATES = {
    "EUR": 0.86259,
    "JPY": 159.23,
    "GBP": 0.73751,
    "CHF": 0.80989,
    "CAD": 1.3859,
}


class Rate(NamedTuple):
    """How many currency units a dollar is worth, and which one we really serve.

    With no rate found, `code` is `USD` and `value` 1: dollars, rather than an
    unconverted amount under the euro sign."""

    value: float
    code: str


# -- The setting --------------------------------------------------------------
# An environment variable, like the model. The menu sets it for the session and
# writes it to `settings.env` at once, for the next ones.

def code() -> str:
    """Display currency: `KOTOGEN_CURRENCY`, failing that the billed dollar."""
    return settings.raw("KOTOGEN_CURRENCY").upper() or DEFAULT_CODE


def set_code(value: str) -> None:
    """Change the display currency for the current session."""
    os.environ["KOTOGEN_CURRENCY"] = value.strip().upper()


def symbol(cur: str | None = None) -> str:
    """The symbol of a currency, or its code when we do not know it."""
    cur = cur or code()
    return SYMBOLS.get(cur, cur)


def label(cur: str | None = None) -> str:
    """A currency as it is named on screen: "EUR €", "SEK"."""
    cur = cur or code()
    sign = symbol(cur)
    return cur if sign == cur else f"{cur} {sign}"


def _fixed_rate() -> float | None:
    """The rate pinned by the settings (`KOTOGEN_CURRENCY_RATE`), if it holds up.

    A rate stable from one command to the next, as an expense claim wants. An
    unreadable or negative value is ignored, and the day's rate applies."""
    raw = settings.raw("KOTOGEN_CURRENCY_RATE").replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


# -- The day's rates ----------------------------------------------------------

def cache_file() -> Path:
    return system.cache_dir() / "exchange-rates.json"


def _fetch(timeout: int) -> dict:
    # frankfurter refuses (403) the `User-Agent` urllib sends by default.
    req = urllib.request.Request(RATES_URL, headers={
        "Accept": "application/json", "User-Agent": "kotogen"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    rates = {str(k).upper(): float(v) for k, v in payload["rates"].items()}
    if not rates:
        raise ValueError("no rate in the response")
    return {"fetched": time.time(), "rates": rates}


def _read_cache() -> dict | None:
    try:
        data = json.loads(cache_file().read_text(encoding="utf-8"))
        return {"fetched": float(data["fetched"]),
                "rates": {str(k): float(v) for k, v in data["rates"].items()}}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        # Missing, truncated or of another format: treated as absent, rewritten.
        return None


def _write_cache(table: dict) -> None:
    try:
        system.write_whole(cache_file(), json.dumps(table))
    except OSError:
        pass  # full disk, read-only folder: we do without


# The rates kept for this run, and whether they were looked up: the catalogue
# screen converts a hundred amounts, each of which would wait on a dead network.
_table: dict | None = None
_looked_up = False


def reset() -> None:
    """Forget the rates kept (reloaded when next needed). For the tests."""
    global _table, _looked_up
    _table, _looked_up = None, False


def _rates() -> dict | None:
    """The day's rates, from the cache if it is fresh, from the network if not.

    Never raises: an unreachable rate only shows amounts in another currency."""
    global _table, _looked_up
    if _looked_up:
        return _table
    _looked_up = True
    cached = _read_cache()
    if cached and time.time() - cached["fetched"] < MAX_AGE_SECONDS:
        _table = cached
        return _table
    try:
        # Short: with the network down, this delays the end of every command.
        fresh = _fetch(timeout=5)
    except (urllib.error.URLError, OSError, TimeoutError,
            ValueError, KeyError, TypeError):
        _table = cached  # stale but far more accurate than the fallback rate
        return _table
    _write_cache(fresh)
    _table = fresh
    return _table


def rate(cur: str | None = None) -> Rate:
    """The rate to apply for this currency, and where it comes from."""
    cur = (cur or code()).upper()
    if cur == DEFAULT_CODE:
        return Rate(1.0, DEFAULT_CODE)
    if (fixed := _fixed_rate()) is not None:
        return Rate(fixed, cur)
    table = _rates()
    if table and (value := table["rates"].get(cur)):
        return Rate(value, cur)
    if value := FALLBACK_RATES.get(cur):
        return Rate(value, cur)
    # No known rate (a code that does not exist, a service mute the first time):
    # dollars, the only amount known to be true.
    return Rate(1.0, DEFAULT_CODE)


def known_codes() -> list[str]:
    """The quoted currencies, to validate an input - empty when we cannot tell.

    Empty means no list at hand (neither network nor cache), not no currency:
    the code is then better taken on trust than refused."""
    table = _rates()
    return sorted({DEFAULT_CODE, *table["rates"]}) if table else []


# -- Display ------------------------------------------------------------------

def _point(text: str) -> str:
    """The decimal separator of the language in use, applied to a formatted number."""
    return text.replace(".", i18n.convention("decimal_point", "."))


def money(number: str, sign: str) -> str:
    """An amount already written out, with its currency sign where the language
    puts it: "$0.02" in English, "0,02 $" in French.

    The position is a convention of the table, like the decimal point. A
    three-letter code always follows: "12.30 SEK", not "SEK12.30"; a symbol of
    several characters is still a symbol: "CA$12.30"."""
    if len(sign) == 3 and sign.isalpha():
        return f"{number} {sign}"
    return i18n.convention("money", "{sign}{number}").format(
        sign=sign, number=number)


def convert(amount: float) -> tuple[float, str]:
    """An amount in dollars, returned in the display currency: (amount, symbol)."""
    applied = rate()
    return amount * applied.value, symbol(applied.code)


def decimals(amount: float) -> str:
    """A number written out, never rounded to zero when it is not zero.

    For rates and catalogue prices, read digit by digit; an expense is rounded
    to the cent instead (see `format_cost`)."""
    text = f"{amount:.4f}" if amount < 1 else f"{amount:.2f}"
    if amount and float(text) == 0:
        text = f"{amount:.6f}"
    return _point(text)


def format_cost(amount: float) -> str:
    """An expense as it is shown: "€0.07", "$1.20", "< €0.01".

    To the cent; below half a cent, "0.00" would read as free, hence "< 0.01".
    Catalogue prices keep their decimals (`decimals`), or they would all be equal."""
    converted, sign = convert(amount)
    # On the written decimal value, not on its binary approximation: "0.075"
    # must give 0.08, which float rounding does not guarantee.
    rounded = Decimal(str(converted)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if converted and not rounded:
        return "< " + money(_point("0.01"), sign)
    return money(_point(f"{rounded:.2f}"), sign)


def rate_line(cur: str | None = None) -> str:
    """The rate applied, spelled out: "$1 = €0.8626", or "" with nothing to convert.

    The only sign that a converted amount is not the bill. The rate's source and
    age are left to the documentation."""
    cur = (cur or code()).upper()
    applied = rate(cur)
    if applied.code == DEFAULT_CODE:
        return ""
    return f"{money('1', '$')} = {money(decimals(applied.value), symbol(cur))}"


def describe() -> str:
    """What the setting is worth: the currency, and nothing more - "USD $".

    No rate: it would crowd the settings screen, and drawing that screen must
    not touch the network. The rate is shown when the setting is opened."""
    return label()
