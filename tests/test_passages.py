"""Where the cut falls when a text is too long for one card.

Three promises: a text that fits in a card does not move (built decks would
re-import twice over), nothing read is lost, and no cut falls inside a sentence.
"""

from kotogen.generators import passages

# An NHK Easy article weighs 180 to 240 Japanese characters: that is the format
# the reading card was tuned on, so the case that must change nothing.
ARTICLE = [
    "東京[とうきょう]で 雨[あめ]が 降[ふ]りました。",
    "みんな 傘[かさ]を 使[つか]いました。",
]

SENTENCE = "今日[きょう]は とても いい 天気[てんき]でした。"


def _without_spaces(lines: list[str]) -> str:
    return "".join("".join(line.split()) for line in lines)


def _flat(blocks: list[list[str]]) -> list[str]:
    return [line for block in blocks for line in block]


# ── The common case: nothing moves ───────────────────────────────────────────

def test_a_text_that_fits_in_one_card_stays_in_one_piece():
    """The cards' fingerprint is taken on the stored text: for the decks already
    built, that text must not change."""
    assert passages.split(ARTICLE) == [ARTICLE]


def test_a_text_slightly_longer_than_an_article_is_not_cut_in_two():
    """The splitting threshold sits above the target size, on purpose: set on
    it, a 260-character text would make two anaemic halves."""
    text = [SENTENCE] * 20  # 260 characters, above the target size
    assert passages.TARGET_SIZE < passages.weight(text) <= passages.MAX_SIZE
    assert passages.split(text) == [text]


# ── The slab, cut up ─────────────────────────────────────────────────────────

def test_a_long_text_gives_passages_the_size_of_a_card():
    blocks = passages.split([SENTENCE] * 60)
    assert len(blocks) > 1
    assert all(passages.weight(block) <= passages.MAX_SIZE for block in blocks)


def test_nothing_is_lost_in_the_splitting():
    """The passages glued back together give the starting text, in order."""
    text = [f"{i}日[にち]目[め]。{SENTENCE}" for i in range(60)]
    assert _flat(passages.split(text)) == text


def test_the_cut_falls_between_the_lines():
    """A line is a unit of meaning (a paragraph, a line of dialogue): it must
    not be re-cut as long as it fits in a passage."""
    text = [SENTENCE] * 60
    assert all(line == SENTENCE for line in _flat(passages.split(text)))


def test_a_thin_tail_joins_the_previous_passage():
    """Without that gluing, the last slice would be a scrap of text with no
    question to ask about it - and the floor would grant it four."""
    blocks = passages.split([SENTENCE] * 41)  # 533 characters: 2 passages + a scrap
    assert len(blocks) == 2
    assert passages.weight(blocks[-1]) >= passages.MIN_TAIL


# ── The line that fits in no passage ─────────────────────────────────────────

def test_a_line_too_heavy_is_re_cut_into_sentences():
    """A whole text file on a single line does exist; without that fallback it
    would make one passage as unreadable as the starting text."""
    blocks = passages.split([SENTENCE * 60])
    assert len(blocks) > 1
    assert all(passages.weight(block) <= passages.MAX_SIZE for block in blocks)


def test_the_cut_never_falls_in_the_middle_of_a_sentence():
    for line in _flat(passages.split([SENTENCE * 60])):
        assert line.endswith("。")


def test_the_text_survives_being_re_cut_into_sentences():
    """The sentence splitter gives the punctuation and the words back intact:
    only the spaces of the furigana convention drop at the head of a sentence."""
    blocks = passages.split([SENTENCE * 60])
    assert _without_spaces(_flat(blocks)) == _without_spaces([SENTENCE * 60])


# ── What a text weighs ───────────────────────────────────────────────────────

def test_furigana_do_not_count_towards_the_weight():
    """Otherwise a richly annotated text would get cut for its readings, which
    add nothing to what there is to understand."""
    bare = ["東京 で 雨 が 降 りました。"]
    annotated = ["東京[とうきょう] で 雨[あめ] が 降[ふ]りました。"]
    assert passages.weight(bare) == passages.weight(annotated)


def test_punctuation_and_digits_do_not_count():
    assert passages.weight(["1、2、3。"]) == 0


# ── Two passes, the same cut ─────────────────────────────────────────────────

def test_the_splitting_is_stable():
    """The card identifiers are drawn from the text of their passage: a cut that
    moved from one pass to the next would re-import them all twice over."""
    text = [f"{i}日[にち]目[め]。{SENTENCE}" for i in range(60)]
    assert passages.split(text) == passages.split(text)
