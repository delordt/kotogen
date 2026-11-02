"""What a listening card may ask, and what it may not.

The front shows only the question and the audio; the transcript, with its
`A：` / `B：` labels, is on the back. A question naming a speaker by label has
no possible answer: the prompt forbids it, and should the model write one
anyway, the card must not enter the deck.
"""

from __future__ import annotations

from kotogen.generators import audio


def answer(question: str, solution: str = "Un gros sac",
           decoys: tuple[str, ...] = ("Une photo", "Un livre", "Une clé")) -> dict:
    return {
        "Level": "N4",
        "TranscriptLines": ["A：ねえ、見て。", "B：わー、大きい荷物だ。"],
        "TranslationLines": ["A : Regarde.", "B : Ouah, quel gros sac."],
        "Cards": [{"Question": question, "Answer": solution,
                   "Decoys": list(decoys), "KeyLine": 2}],
    }


def built(question: str, **kwargs) -> list[dict]:
    return audio._post_process(answer(question, **kwargs), "x.mp3", "x", "N4")


# ── The four wordings found in a real batch ───────────────────────────────────

def test_a_question_naming_a_speaker_is_refused(capsys):
    for question in (
        "Que fait A en rentrant du travail ?",
        "Pourquoi B mentionne-t-il les desserts ?",
        "Qu'est-ce qui a surpris la personne B ?",
        "Que suggère le locuteur A à la fin de la conversation ?",
    ):
        assert built(question) == [], question
    # A refused card is sorting, not a failure: said on stdout, marked "!".
    assert "label" in capsys.readouterr().out


def test_the_label_is_hunted_down_in_the_answers_too():
    """A solution `C'est B qui paie` is just as undecipherable."""
    assert built("Qui règle l'addition ?", solution="C'est B qui paie") == []
    assert built("Qui règle l'addition ?",
                 decoys=("Le client", "Personne", "A")) == []


# ── What has to get through ───────────────────────────────────────────────────

def test_a_question_pointing_by_role_or_action_gets_through():
    for question in (
        "Que conseille le vendeur au client ?",
        "Que fait la personne qui rentre du travail ?",
        "Pourquoi les légumes sont-ils chers cette année ?",
        "Où a-t-il trouvé le manga ?",
    ):
        assert len(built(question)) == 1, question


def test_a_hyphenated_verb_is_not_a_label():
    """`A-t-il compris ?` is ordinary French, not a label."""
    assert len(built("A-t-il compris la consigne ?")) == 1


# ── What gets through damaged ─────────────────────────────────────────────────
# A card kept under a "!!" has an empty field or a duplicated option. The flaw is
# recorded, not put in "Tags": the proofreading setting decides at export time
# whether it goes out as it stands, tagged, or not at all.

def test_an_unaligned_translation_marks_the_cards_of_the_passage(capsys):
    from kotogen import proofreading

    given = answer("Que voit-on ?")
    given["TranslationLines"] = ["A : Regarde."]
    cards = audio._post_process(given, "x.mp3", "x", "N4")
    assert "translation not lined up" in capsys.readouterr().err
    assert proofreading.tags(cards[:1]) == [proofreading.TRANSLATION_TAG]


def test_an_unaligned_translation_is_not_laid_under_the_wrong_lines(capsys):
    """The back pairs a translation line with a transcript line by rank: one
    short, every line would show the translation of another."""
    given = answer("Que voit-on ?")
    given["TranslationLines"] = ["A : Regarde.", "B : Ouah.", "A : Oui."]
    cards = audio._post_process(given, "x.mp3", "x", "N4")
    assert cards[0]["Translation"] == ""
    assert cards[0]["Transcript"]
    assert "Translation field left empty" in capsys.readouterr().err


def test_a_card_that_is_not_an_object_is_skipped_not_fatal(capsys):
    """One stray string among the cards must not stop the run, nor take the
    other cards of the passage with it."""
    given = answer("Que voit-on ?")
    given["Cards"].insert(0, "Que voit-on ?")
    cards = audio._post_process(given, "x.mp3", "x", "N4")
    assert [card["Question"] for card in cards] == ["Que voit-on ?"]
    assert "card 1 skipped" in capsys.readouterr().out


def test_a_missing_transcript_marks_the_cards_of_the_passage(capsys):
    from kotogen import proofreading

    given = answer("Que voit-on ?")
    given["TranscriptLines"] = []
    given["TranslationLines"] = []
    cards = audio._post_process(given, "x.mp3", "x", "N4")
    assert "transcript missing" in capsys.readouterr().err
    assert proofreading.tags(cards[:1]) == [proofreading.TRANSCRIPT_TAG]


def test_a_duplicated_solution_marks_only_its_own_card():
    from kotogen import proofreading

    given = answer("Que voit-on ?")
    given["Cards"].append({"Question": "Où sont-ils ?", "Answer": "Dehors",
                           "Decoys": ["Chez eux", "Au bureau", "En classe"],
                           "KeyLine": 1})
    given["Cards"][0]["Decoys"] = ["Un gros sac", "Un livre", "Une clé"]
    cards = audio._post_process(given, "x.mp3", "x", "N4")
    assert proofreading.tags(cards[:1]) == [proofreading.CHOICES_TAG]
    assert proofreading.tags(cards[1:2]) == []
