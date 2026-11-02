"""The deck as a second memory of the sources already handled.

The local history knows only this machine; the synchronised deck spares a fresh
one paying again for what another did. The recovery reads the cards' provenances
(`known.Known`), from a deck held in memory here.
"""

from __future__ import annotations

import pytest

from conftest import Held, held_card
from kotogen import seen

ARTICLE = "https://news.web.nhk/news/easy/ne2026071201/ne2026071201.html"
BOOK = "https://tadoku.org/japanese/book/6346/"
EPISODE = "Nihongo con Teppei 波! - Ep 700"
VIDEO = "Onomappu - なんとか (00:12 → 00:45) https://youtu.be/AbCd1234xyz"
SECTION = "JLPT 公式問題集 (2012) - N3 - 問題2 (00:12 → 00:45)"
LESSON = "いろどり 初級1 (A2) - 第1課 駅の近くに住んでいます (00:12 → 00:45)"


def deck(**by_notetype: list[str]) -> Held:
    """A deck whose cards carry these provenances, note type by note type."""
    return Held({notetype: [held_card(i, Source=trace) for i, trace in enumerate(traces)]
                 for notetype, traces in by_notetype.items()})


# ── Recovering the history ────────────────────────────────────────────────────

@pytest.mark.parametrize("trace, expected", [
    (ARTICLE, ("nhk", "ne2026071201")),
    (f"{BOOK} (p. 3-)", ("tadoku", "6346")),
    (VIDEO, ("onomappu", "AbCd1234xyz")),
    # Sources that read back their own composed label. The two 青空 shelves do
    # too, through their catalogue: see `test_aozora`.
    (SECTION, ("jlpt2012-n3", "問題2")),
    (LESSON, ("irodori-shokyu1", "1")),
    # Recognised, but an episode's card does not carry its guid.
    (f"{EPISODE} (00:12 → 00:45)", ("teppei", "")),
    ("my_course.mp3 (00:12 → 00:45)", None),
])
def test_what_a_provenance_makes_it_possible_to_name(trace, expected):
    assert seen._recognise(trace) == expected


def test_recovering_writes_the_history_of_the_deck():
    recovery = seen.recover(deck(
        Listening=[ARTICLE, VIDEO, SECTION, LESSON, f"{EPISODE} (00:12 → 00:45)"],
        Reading=[f"{BOOK} (p. 3-)", "course.pdf (p. 2)"]))
    assert seen.load("audio", "nhk") == {"ne2026071201": ""}
    assert seen.load("audio", "onomappu") == {"AbCd1234xyz": ""}
    assert seen.load("audio", "jlpt2012-n3") == {"問題2": ""}
    assert seen.load("audio", "irodori-shokyu1") == {"1": ""}
    assert seen.load("reading", "tadoku") == {"6346": ""}
    assert recovery.added == {"nhk": 1, "onomappu": 1, "tadoku": 1,
                               "jlpt2012-n3": 1, "irodori-shokyu1": 1}
    assert recovery.without_id == 1   # the podcast episode
    assert recovery.foreign == 1          # a PDF of one's own, that nothing names


def test_recovering_twice_adds_nothing_more():
    seen.recover(deck(Listening=[ARTICLE]))
    recovery = seen.recover(deck(Listening=[ARTICLE]))
    assert recovery.added == {} and recovery.known == 1


def test_the_recovery_reads_the_deck_afresh():
    """It reads the deck again rather than what a command kept of it."""
    held = deck(Listening=[VIDEO])
    held.sources()
    held.by_notetype["Listening"].append(held_card(9, Source=ARTICLE))
    assert seen.recover(held).added == {"onomappu": 1, "nhk": 1}


# ── What the deck no longer carries ───────────────────────────────────────────

def test_a_source_whose_cards_have_gone_is_said_so():
    """Deleted cards leave the source in the history, so it is not offered
    again: the recovery says so and erases nothing."""
    seen.mark("audio", "nhk", "ne-deleted", "Article deleted since")
    recovery = seen.recover(deck(Listening=[VIDEO]))
    assert recovery.missing == ("nhk",)
    assert seen.load("audio", "nhk") == {"ne-deleted": "Article deleted since"}
    assert seen.missing(deck(Listening=[VIDEO])) == ("nhk",)


def test_a_silent_deck_makes_nobody_disappear():
    """An empty answer (Anki closed, wrong note type, sync behind) would make
    the whole history look gone."""
    seen.mark("audio", "nhk", "ne1", "Article")
    assert seen.recover(deck()).missing == ()


def test_a_mode_the_deck_said_nothing_about_concludes_nothing():
    """Cards for listening only: a book read is not declared gone on the silence
    of its mode."""
    seen.mark("reading", "tadoku", "6346", "A book")
    assert seen.recover(deck(Listening=[VIDEO])).missing == ()


def test_the_vocabulary_is_not_judged_by_the_deck():
    """Its cards have no Source field, so the deck knows nothing of them."""
    seen.mark("vocab", "nhk", "ne1", "Article")
    assert seen.recover(deck(Listening=[VIDEO])).missing == ()


def test_what_a_card_cannot_name_is_never_said_to_have_gone():
    """A long reading's cursor is filed under a fingerprint of its address,
    which no provenance gives back: its absence proves nothing."""
    seen.mark("reading", "www-aozora-gr-jp-1a2b3c4d", "abcdef", "passage 1/9")
    seen.mark("reading", "tadoku", "6346", "A book")
    assert seen.recover(deck(Reading=["course.pdf (p. 2)"])).missing == ("tadoku",)


def test_recovering_only_ever_adds_and_never_erases():
    """The local history may hold more than the deck (cards deleted since): the
    recovery adds, it does not level."""
    seen.mark("audio", "nhk", "ne-old", "Article")
    seen.recover(deck(Listening=[ARTICLE]))
    assert seen.load("audio", "nhk") == {"ne-old": "Article",
                                            "ne2026071201": ""}
