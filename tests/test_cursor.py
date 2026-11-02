"""Pick a long reading up where it was left off.

Two levels of proof: the cursor itself (what it retains, and why the
fingerprint rather than the rank), then its effect in `reading._kept` - the
announced window, the ceiling, and the fact that a short text changes nothing.
"""

from __future__ import annotations

import argparse

import pytest

from kotogen import seen
from kotogen.generators import cursor, reading, sources


def blocks(how_many: int) -> list[list[str]]:
    """Distinct passages, in order."""
    return [[f"これは{n}番目の文章です。"] for n in range(1, how_many + 1)]


def args(**fields) -> argparse.Namespace:
    values = {"passages": None, "from_passage": None}
    values.update(fields)
    return argparse.Namespace(**values)


# -- The tracking key ---------------------------------------------------------

def test_a_url_is_followed_under_a_readable_name():
    key = cursor.key_for("https://www.aozora.gr.jp/cards/000121/files/628_14895.html")
    assert key.startswith("www-aozora-gr-jp-")


def test_two_texts_from_one_site_do_not_share_their_cursor():
    """The host alone would confuse them: a site serves thousands of texts."""
    assert (cursor.key_for("https://example.test/a.html")
            != cursor.key_for("https://example.test/b.html"))


def test_a_file_is_followed_under_its_name():
    assert cursor.key_for("/tmp/folder/chapter.txt") == "chapter.txt"


def test_without_an_origin_there_is_nothing_to_follow():
    assert cursor.key_for("") == ""


# -- What the cursor retains --------------------------------------------------

def test_without_a_key_every_passage_is_returned():
    left, done = cursor.remaining("", blocks(4))
    assert [rank for rank, _ in left] == [1, 2, 3, 4]
    assert done == 0


def test_a_handled_passage_does_not_come_back():
    every = blocks(4)
    cursor.mark("work", every[0], 1, 4)
    cursor.mark("work", every[1], 2, 4)
    left, done = cursor.remaining("work", every)
    assert [rank for rank, _ in left] == [3, 4]
    assert done == 2


def test_the_rank_returned_is_the_one_of_the_whole_text():
    """"passage 7/42" means nothing if it counts within the window of the day."""
    every = blocks(10)
    for rank in range(1, 7):
        cursor.mark("work", every[rank - 1], rank, 10)
    left, _ = cursor.remaining("work", every)
    assert left[0][0] == 7


def test_it_is_the_matter_that_is_retained_and_not_the_rank():
    """A page that gains a paragraph would skip a passage if the cursor counted
    ranks: here the unchanged passage stays handled, wherever it sits."""
    every = blocks(4)
    cursor.mark("work", every[2], 3, 4)
    shifted = [["new paragraph。"]] + every
    left, done = cursor.remaining("work", shifted)
    assert done == 1
    # The handled passage is the one that moved, not the one at its rank.
    assert all(block != every[2] for _, block in left)


def test_a_rewritten_text_is_read_again_in_full():
    every = blocks(3)
    for rank, block in enumerate(every, 1):
        cursor.mark("work", block, rank, 3)
    other = [["まったく違う文章です。"] for _ in range(3)]
    left, done = cursor.remaining("work", other)
    assert len(left) == 3 and done == 0


def test_a_rank_typed_by_hand_ignores_the_history():
    every = blocks(5)
    for rank, block in enumerate(every, 1):
        cursor.mark("work", block, rank, 5)
    assert [rank for rank, _ in cursor.from_rank(every, 3)] == [3, 4, 5]


@pytest.mark.parametrize("rank", [0, -1, 6])
def test_a_rank_outside_the_text_is_refused(rank):
    with pytest.raises(ValueError):
        cursor.from_rank(blocks(5), rank)


def test_without_a_key_nothing_is_written():
    cursor.mark("", blocks(1)[0], 1, 1)
    assert seen.inventory() == []


# -- The announced window -----------------------------------------------------

def test_a_short_text_changes_nothing(capsys):
    """A single passage gets no cursor and no line, which leaves the NHK Easy
    articles already in the deck as they are."""
    kept = reading._kept(blocks(1), args(), "work")
    assert kept == [(1, blocks(1)[0])]
    assert capsys.readouterr().out == ""


def test_the_first_pass_takes_the_first_six(capsys):
    kept = reading._kept(blocks(19), args(), "work")
    assert [rank for rank, _ in kept] == [1, 2, 3, 4, 5, 6]
    output = capsys.readouterr()
    assert "passages 1 to 6 of 19" in output.out + output.err


def test_the_next_pass_takes_what_follows(capsys):
    every = blocks(19)
    for rank, block in reading._kept(every, args(), "work"):
        cursor.mark("work", block, rank, 19)
    capsys.readouterr()

    kept = reading._kept(every, args(), "work")
    assert [rank for rank, _ in kept] == [7, 8, 9, 10, 11, 12]
    output = capsys.readouterr()
    assert "passages 7 to 12 of 19" in output.out + output.err
    assert "6 already handled" in output.out + output.err


def test_an_exhausted_text_says_so_instead_of_redoing_it_all(capsys):
    every = blocks(3)
    for rank, block in enumerate(every, 1):
        cursor.mark("work", block, rank, 3)
    assert reading._kept(every, args(), "work") == []
    assert "all already handled" in capsys.readouterr().out


def test_the_ceiling_can_be_raised():
    kept = reading._kept(blocks(19), args(passages=12), "work")
    assert len(kept) == 12


def test_from_passage_restarts_at_the_asked_rank(capsys):
    every = blocks(19)
    for rank, block in enumerate(every, 1):
        cursor.mark("work", block, rank, 19)
    kept = reading._kept(every, args(from_passage=10), "work")
    assert [rank for rank, _ in kept] == [10, 11, 12, 13, 14, 15]


def test_without_a_key_the_window_stays_the_one_of_the_beginning():
    """A source that is not followed (a text pulled out of a PDF) starts from
    the first passages, on every pass."""
    kept = reading._kept(blocks(19), args(), "")
    assert [rank for rank, _ in kept] == [1, 2, 3, 4, 5, 6]


# -- What triggers the tracking -----------------------------------------------

def test_only_reading_follows_its_progress():
    """`whole` is only set by reading, which pays per passage kept. Vocabulary
    and grammar read the text in one block and move nowhere."""
    assert sources.GenericText("chapter.txt", whole=True).tracking_key
    assert not sources.GenericText("chapter.txt").tracking_key


def test_an_nhk_article_is_not_followed():
    # It fits in a single passage: there is nothing to follow.
    article = sources.NhkArticle("https://news.web.nhk/news/easy/ne1/ne1.html",
                                 "reading")
    assert article.tracking_key == ""
