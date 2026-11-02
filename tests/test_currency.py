"""The display currency: conversion, disk cache, network failures, formatting.

The frankfurter answer is faked and the cache diverted to a temporary folder.
The bill is in dollars, the display need not be, and a missing rate must never
silence a cost summary.
"""

from __future__ import annotations

import json
import time
import urllib.error

import pytest

from kotogen import currency
from kotogen.ai_client import Usage


class _FakeResponse:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def cache_in_tmp(monkeypatch, tmp_path):
    """Rates held in memory forgotten, disk cache confined to the test's folder."""
    currency.reset()
    monkeypatch.setattr(currency.system, "cache_dir", lambda: tmp_path)
    yield
    currency.reset()


def serve(monkeypatch, rates: dict | None = None, day: str = "2026-08-17") -> list[int]:
    """Makes the rates endpoint answer; returns the counter of network calls."""
    calls: list[int] = []
    payload = {"amount": 1, "base": "USD", "date": day,
               "rates": rates if rates is not None else {"EUR": 0.5, "JPY": 100.0}}

    def urlopen(req, timeout=None):
        calls.append(1)
        return _FakeResponse(payload)

    monkeypatch.setattr(currency.urllib.request, "urlopen", urlopen)
    return calls


def fail(monkeypatch, exc: Exception | None = None) -> None:
    def urlopen(req, timeout=None):
        raise exc or urllib.error.URLError("getaddrinfo failed")

    monkeypatch.setattr(currency.urllib.request, "urlopen", urlopen)


# ── The dollar costs neither a request nor a conversion ───────────────────────

def test_the_dollar_is_the_default():
    assert currency.code() == "USD"
    assert currency.format_cost(0.0182) == "$0.02"


def test_in_dollars_no_request_is_made(monkeypatch):
    """The billing currency needs no rate at all: nothing to ask for."""
    calls = serve(monkeypatch)
    currency.format_cost(0.0182)
    assert calls == []


# ── Conversion ────────────────────────────────────────────────────────────────

def test_the_amounts_follow_the_currency_chosen(monkeypatch):
    serve(monkeypatch, {"EUR": 0.5})
    currency.set_code("eur")  # typed in lower case: the code is normalised
    assert currency.code() == "EUR"
    assert currency.format_cost(0.0182) == "€0.01"


def test_a_currency_with_no_known_symbol_shows_by_its_code(monkeypatch):
    serve(monkeypatch, {"SEK": 10.0})
    currency.set_code("SEK")
    assert currency.format_cost(1.5) == "15.00 SEK"


def test_the_command_summary_follows_the_currency(monkeypatch):
    """The call summary at the end of a command is where the cost matters."""
    serve(monkeypatch, {"EUR": 0.5})
    currency.set_code("EUR")
    usage = Usage()
    usage.add(12_000, 3_400, 0.0182)
    assert usage.summary().endswith("(€0.01)")


def test_the_cost_stays_counted_in_dollars(monkeypatch):
    """Conversion is for display only: the amount held is the one billed."""
    serve(monkeypatch, {"EUR": 0.5})
    currency.set_code("EUR")
    usage = Usage()
    usage.add(12_000, 3_400, 0.0182)
    assert usage.cost == pytest.approx(0.0182)


def test_a_fixed_rate_in_the_env_wins_over_the_market(monkeypatch):
    """An expense claim wants one rate, not each call's rate of the day."""
    calls = serve(monkeypatch, {"EUR": 0.5})
    currency.set_code("EUR")
    monkeypatch.setenv("KOTOGEN_CURRENCY_RATE", "0.90")  # a decimal comma works too
    assert currency.format_cost(1.0) == "€0.90"
    assert calls == []  # rate known in advance: no request


def test_an_unreadable_fixed_rate_is_ignored(monkeypatch):
    serve(monkeypatch, {"EUR": 0.5})
    currency.set_code("EUR")
    monkeypatch.setenv("KOTOGEN_CURRENCY_RATE", "free")
    assert currency.format_cost(1.0) == "€0.50"


# ── The disk cache ────────────────────────────────────────────────────────────

def test_the_rates_are_asked_for_only_once(monkeypatch):
    """The catalogue converts a hundred amounts: one network round trip."""
    calls = serve(monkeypatch)
    currency.set_code("EUR")
    for _ in range(10):
        currency.format_cost(0.01)
    assert len(calls) == 1


def test_the_next_launch_reads_the_cache(monkeypatch):
    calls = serve(monkeypatch)
    currency.set_code("EUR")
    currency.format_cost(0.01)
    currency.reset()  # a fresh run, the same machine
    currency.format_cost(0.01)
    assert len(calls) == 1


def test_a_stale_cache_is_refreshed(monkeypatch):
    calls = serve(monkeypatch)
    currency.set_code("EUR")
    currency.format_cost(0.01)
    old = json.loads(currency.cache_file().read_text(encoding="utf-8"))
    old["fetched"] = time.time() - currency.MAX_AGE_SECONDS - 1
    currency.cache_file().write_text(json.dumps(old), encoding="utf-8")
    currency.reset()
    currency.format_cost(0.01)
    assert len(calls) == 2


def test_a_corrupt_cache_is_treated_as_absent(monkeypatch):
    calls = serve(monkeypatch)
    currency.cache_file().write_text("{trunca", encoding="utf-8")
    currency.set_code("EUR")
    assert currency.format_cost(1.0) == "€0.50"
    assert len(calls) == 1


def test_an_unwritable_cache_breaks_nothing(monkeypatch, tmp_path):
    """Disk full or folder read-only: do without the cache."""
    monkeypatch.setattr(currency.system, "cache_dir",
                        lambda: tmp_path / "file" / "subfolder")
    (tmp_path / "file").write_text("I am not a folder", encoding="utf-8")
    serve(monkeypatch)
    currency.set_code("EUR")
    assert currency.format_cost(1.0) == "€0.50"


# ── No network ────────────────────────────────────────────────────────────────

def test_offline_the_last_known_rate_serves(monkeypatch):
    """Yesterday's rate is far closer than a rate hard-coded last year."""
    serve(monkeypatch)
    currency.set_code("EUR")
    currency.format_cost(0.01)
    old = json.loads(currency.cache_file().read_text(encoding="utf-8"))
    old["fetched"] = time.time() - currency.MAX_AGE_SECONDS - 1
    currency.cache_file().write_text(json.dumps(old), encoding="utf-8")

    currency.reset()
    fail(monkeypatch)
    assert currency.format_cost(1.0) == "€0.50"


def test_offline_with_no_cache_the_fallback_rate_serves(monkeypatch):
    fail(monkeypatch)
    currency.set_code("EUR")
    applied = currency.rate()
    assert applied.value == pytest.approx(currency.FALLBACK_RATES["EUR"])
    assert applied.code == "EUR"


def test_offline_no_currency_is_declared_unknown(monkeypatch):
    """With no list at hand, a code is taken on trust rather than refused over
    an outage."""
    fail(monkeypatch)
    assert currency.known_codes() == []


def test_the_network_is_asked_only_once_even_when_it_is_down(monkeypatch):
    """A five-second timeout on every amount would stall the display."""
    calls: list[int] = []

    def urlopen(req, timeout=None):
        calls.append(1)
        raise urllib.error.URLError("getaddrinfo failed")

    monkeypatch.setattr(currency.urllib.request, "urlopen", urlopen)
    currency.set_code("EUR")
    for _ in range(5):
        currency.format_cost(0.01)
    assert len(calls) == 1


def test_an_http_error_does_not_fail_the_display(monkeypatch):
    fail(monkeypatch, urllib.error.HTTPError(
        currency.RATES_URL, 403, "Forbidden", {}, None))
    currency.set_code("EUR")
    assert currency.format_cost(1.0).startswith("€")


def test_a_currency_with_no_rate_stays_in_dollars(monkeypatch):
    """An amount in dollars beats an unconverted amount dressed up as euros."""
    serve(monkeypatch, {"EUR": 0.5})
    currency.set_code("XYZ")
    assert currency.format_cost(1.0) == "$1.00"
    assert currency.rate_line() == ""  # nothing to announce: nothing is converted


# ── Formatting ────────────────────────────────────────────────────────────────

def test_a_spend_shows_to_the_cent(monkeypatch):
    """A spend reads in cents, with no zeros to count."""
    serve(monkeypatch, {"EUR": 0.5})
    currency.set_code("EUR")
    assert currency.format_cost(0.146) == "€0.07"
    assert currency.format_cost(0.15) == "€0.08"  # exactly half a cent: rounds up
    assert currency.format_cost(2.4) == "€1.20"


def test_a_tiny_amount_is_not_rounded_to_zero(monkeypatch):
    """"€0.00" would read as "free"; the right answer is "negligible"."""
    serve(monkeypatch, {"EUR": 0.5})
    currency.set_code("EUR")
    assert currency.format_cost(0.000024) == "< €0.01"
    assert currency.format_cost(0) == "€0.00"  # no paid call at all: really zero


def test_the_rate_applied_is_said_plainly(monkeypatch):
    """The rate alone: its source and date are in the documentation."""
    serve(monkeypatch, {"EUR": 0.86259})
    currency.set_code("EUR")
    assert currency.rate_line() == "$1 = €0.8626"


def test_the_dollar_has_no_rate_to_announce():
    assert currency.rate_line() == ""


def test_the_setting_says_only_the_currency(monkeypatch):
    """The settings screen is taken in at a glance: the rate would drown it."""
    calls = serve(monkeypatch, {"EUR": 0.86259})
    currency.set_code("EUR")
    assert currency.describe() == "EUR €"
    assert calls == []  # drawing the settings asks for no rate


def test_a_currency_whose_symbol_is_its_code_does_not_repeat_itself():
    """The symbol is shown only when it differs from the code: not "CHF CHF"."""
    assert currency.label("EUR") == "EUR €"
    assert currency.label("CHF") == "CHF"


def test_the_sign_goes_where_the_language_puts_it(monkeypatch):
    """Before the amount in English, after it in French; a code always after."""
    from kotogen import i18n

    assert currency.money("0.02", "$") == "$0.02"
    assert currency.money("12.30", "SEK") == "12.30 SEK"
    monkeypatch.setattr(i18n, "_language", "fr")
    monkeypatch.setattr(i18n, "_catalogue", i18n._load("fr"))
    assert currency.money("0,02", "$") == "0,02 $"  # a non-breaking space


@pytest.mark.parametrize("code", ["CAD", "AUD", "CNY", "BRL"])
def test_a_symbol_of_several_characters_sits_where_a_symbol_does(code):
    """CA$, A$, CN¥ and R$ are symbols: before the amount in English."""
    sign = currency.SYMBOLS[code]
    assert currency.money("12.30", sign) == f"{sign}12.30"
    assert currency.money("12.30", "CHF") == "12.30 CHF"
