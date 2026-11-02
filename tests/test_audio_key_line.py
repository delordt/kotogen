"""The key line of a listening card: a rank in its own field.

A "→" inside Transcript would mix Japanese and annotation: the furigana pass and
the template would have to skip it, and the cards of one passage would each
carry a different transcript. So the rank goes in KeyLine, as on the reading
card, and the transcript stays untouched. On a choice item the rank is read off
the answer, which says which line it was copied from, not taken from the model.
"""

from __future__ import annotations

import pytest

from kotogen.generators import audio

LINES = ["A： ねえ、見て。", "B： わー、大きい荷物だ。", "A： 明日[あした] 山[やま]に 登[のぼ]るんだ。"]
TRANSLATED = ["A : Regarde.", "B : Ouah, quel gros sac.", "A : Demain, je pars en montagne."]


def _card(key_line=None, **extra):
    """A valid card as the model hands it back, key line of your choosing."""
    card = {"Question": "Pourquoi a-t-il un gros sac ?", "Answer": "Il part en montagne",
            "Decoys": ["Il déménage", "Il fait les courses", "Il part travailler"], **extra}
    if key_line is not None:
        card["KeyLine"] = key_line
    return card


def _cards(*cards):
    answer = {"Level": "N4", "TranscriptLines": list(LINES),
              "TranslationLines": list(TRANSLATED), "Cards": list(cards)}
    return audio._post_process(answer, "x.mp3", "x", "N4")


# ── The rank goes into its field ──────────────────────────────────────────────

def test_the_key_line_is_a_rank_in_its_own_field():
    card = _cards(_card(3))[0]
    assert card["KeyLine"] == "3"


def test_the_transcript_carries_no_mark():
    card = _cards(_card(3))[0]
    assert card["Transcript"] == "\n".join(LINES)
    assert "→" not in card["Transcript"]


def test_a_rank_as_a_string_is_accepted():
    """The model hands back 3 or "3" alike."""
    assert _cards(_card("3"))[0]["KeyLine"] == "3"


# ── What points at no line at all ─────────────────────────────────────────────

def test_a_rank_out_of_bounds_or_missing_leaves_the_field_empty():
    """Better to mark nothing than to mark the wrong sentence."""
    for value in (0, -1, 4, True, None, "", "two", 2.0):
        cards = _cards(_card(value))
        assert cards[0]["KeyLine"] == "", value
        assert cards[0]["Transcript"] == "\n".join(LINES), value


# ── One transcript, several cards ─────────────────────────────────────────────

def test_the_cards_of_a_passage_share_the_same_transcript():
    """A mark in the text would make every copy differ by one character."""
    cards = _cards(_card(1), _card(3))

    assert len(cards) == 2
    assert cards[0]["Transcript"] == cards[1]["Transcript"]
    assert [c["KeyLine"] for c in cards] == ["1", "3"]


# ── The choice item reads its rank off its answer ─────────────────────────────

# A 発話表現 as the model hands it back: one line per sentence of the prompt,
# then the three replies. The right one is numbered 2 and sits on line 4.
CHOICE = [
    "週末[しゅうまつ]、 友達[ともだち]と 海[うみ]に 行[い]きたいです。",
    "何[なん]と 言[い]いますか。",
    "1 週末[しゅうまつ] 海[うみ]に 行[い]ってもいいですか",
    "2 週末[しゅうまつ] 海[うみ]に 行[い]きませんか",
    "3 週末[しゅうまつ] 海[うみ]に 行[い]くそうですよ",
]
CHOICE_TRANSLATED = [
    "Vous voulez aller à la mer avec un ami ce week-end.",
    "Que dites-vous ?",
    "1 Je peux aller à la mer ce week-end ?",
    "2 Tu ne veux pas aller à la mer ce week-end ?",
    "3 Il paraît qu'il va à la mer ce week-end",
]


def _choice_card(key_line, answer=CHOICE[3]):
    """The one card of a choice item, key line of the model's choosing."""
    result = {"Level": "N4", "TranscriptLines": list(CHOICE),
              "TranslationLines": list(CHOICE_TRANSLATED),
              "Cards": [{"Question": "Vous voulez inviter un ami à la mer ce "
                                     "week-end. Que lui dites-vous ?",
                         "Answer": answer, "Decoys": [], "KeyLine": key_line}]}
    return audio._post_process(result, "x.mp3", "x", "N4", choice=True)[0]


def test_the_answer_beats_the_rank_the_model_counted():
    """The model counts on the transcript it was given, where the prompt was one
    segment, and comes back a line short: the answer is the reply of line 4."""
    assert _choice_card(3)["KeyLine"] == "4"


@pytest.mark.parametrize("key_line", [None, 0, 9, "", "two"])
def test_the_line_is_marked_even_when_no_rank_comes_back(key_line):
    """Nothing to check the model against here: the answer alone places it."""
    assert _choice_card(key_line)["KeyLine"] == "4"


def test_a_rank_the_answer_confirms_is_kept():
    assert _choice_card(4)["KeyLine"] == "4"


def test_an_answer_placing_no_line_leaves_the_model_its_rank():
    """The answer is read with certainty or not at all: with neither the text of
    a line nor an option number in it, the model's rank stands."""
    assert _choice_card(2, answer="Il faut l'inviter")["KeyLine"] == "2"


def test_an_ordinary_card_is_not_read_off_its_answer():
    """Outside a choice item the answer is in the language of the cards, nowhere in the
    transcript: the rank stands as it comes."""
    assert _cards(_card(3))[0]["KeyLine"] == "3"
