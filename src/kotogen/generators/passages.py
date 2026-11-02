"""Cutting a long text into passages, each the text of one reading card.

A reading card shows its whole text, which reads at the size of an NHK Easy
article and not at a chapter's. A longer text is cut between its lines, which
are already units of meaning; a line too heavy for a passage is first re-split
into sentences (`nhk.split_sentences`). How many passages are processed is the
generator's business (`reading.PASSAGES_MAX`).
"""

from __future__ import annotations

from kotogen.generators import quota

# The weight aimed at for a passage, in Japanese characters without furigana
# (`quota.japanese_chars`): the size of an NHK Easy article, the format the
# reading card was tuned on. A passage closes before the next line would pass it.
TARGET_SIZE = 240

# A text above this is split. Well above the target, so that a slightly long
# article stays one card rather than two thin halves.
MAX_SIZE = 400

# A last passage lighter than this joins the one before: too thin for a question
# worth asking (`quota.MIN_CHARS`), it would still get four from `quota.FLOOR`.
MIN_TAIL = TARGET_SIZE // 2


def weight(lines: list[str]) -> int:
    """What a text weighs, as the splitting counts it."""
    return quota.japanese_chars(lines)


def _into_sentences(lines: list[str]) -> list[str]:
    """Re-split into sentences only the lines that do not fit in a passage.

    The others keep their splitting, which carries meaning (a paragraph, a line
    of dialogue).
    """
    from kotogen.generators.nhk import split_sentences

    out: list[str] = []
    for line in lines:
        if weight([line]) > TARGET_SIZE:
            out.extend(split_sentences([line]))
        else:
            out.append(line)
    return out


def split(lines: list[str]) -> list[list[str]]:
    """The text in card-sized passages, in order.

    Exactly one passage when the text fits in a card, so that the stored text and
    the card ids drawn from it (`reading._fingerprint`) do not move. The cut
    depends only on the text: two runs over one source give the same cards.
    """
    if weight(lines) <= MAX_SIZE:
        return [list(lines)]

    blocks: list[list[str]] = []
    current: list[str] = []
    carried = 0
    for line in _into_sentences(lines):
        weighs = weight([line])
        if current and carried + weighs > TARGET_SIZE:
            blocks.append(current)
            current, carried = [], 0
        current.append(line)
        carried += weighs
    if current:
        blocks.append(current)

    # A thin tail joins the previous passage. The two stay under TARGET_SIZE +
    # MIN_TAIL (below MAX_SIZE), unless that passage is a single sentence heavier
    # than the target, which can carry them past MAX_SIZE.
    if len(blocks) > 1 and weight(blocks[-1]) < MIN_TAIL:
        blocks[-2].extend(blocks.pop())
    return blocks
