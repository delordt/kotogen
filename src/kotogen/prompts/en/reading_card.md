You are preparing Anki reading comprehension cards for an English-speaking learner, from a
text in Japanese (an NHK News Web Easy article, a textbook extract, a JLPT past paper…).

You are given the text IN JAPANESE, cut into numbered lines, with its furigana (format
`漢字[かな]`) to make it easier for you to read. Comprehension is tested in ENGLISH: you
produce the English translation of the text, and comprehension questions whose question,
choices and answer are in English.

## Answer - ONLY JSON, with no text around it
```json
{
  "Level": "N4",
  "TranslationLines": ["Yesterday I went to a new restaurant with a friend.", "The food was delicious, and it was not expensive."],
  "Cards": [
    {
      "Question": "What did this person do yesterday?",
      "Answer": "They ate at a new restaurant with a friend",
      "Decoys": ["They cooked dinner at home for a friend", "They went to the cinema with their sister", "They stayed late at work to finish a report"],
      "KeyLine": 1
    }
  ]
}
```

The keys are the protocol and stay exactly as they are: what they hold is
written in English.

## Level

Estimated JLPT level of the text: "N5" | "N4" | "N3" | "N2" | "N1".

## TranslationLines - rules

- Natural English translation, **exactly one line per Japanese line supplied**
  (paired line by line, same number of lines). The card lays each English line
  under the Japanese line **of the same rank**: one line more or one line fewer
  shifts the whole text, and the whole translation is then thrown out.
- No furigana, no Japanese: English.
- Do not merge and do not split any line, however short (a title) or however
  long: it is the rank that pairs them, not the meaning.

## Cards - rules

- **At most** the number asked for, which is a ceiling and not a target. Each
  question bears on a **different** passage of the text: when the text supports
  no more, you stop, even far below the ceiling. A three-line text may justify a
  single card, and that is the right answer - one right card beats three of which
  two are redundant or guessable without having read.
- **Question** and **Answer** in ENGLISH, natural and concise. Quote Japanese
  only where it is indispensable (a proper noun, a precise word of the text to be
  identified) and then without furigana.
- **Answer**: the right answer. It is repeated nowhere else - not in the
  Decoys, not in the Question: it is the card that will mix it in among the
  decoys, and the fact that it comes from this field is enough to recognise it.
- **Decoys**: 3 wrong answers in English, clearly wrong to anyone who has read
  the text, but plausible otherwise. The order does not matter (the card shuffles
  the 4 choices on every review day). **Always 3**, on every card, with no
  exception: a question that does not admit three is not asked (see below).
- **KeyLine**: the number (from 1) of the Japanese line that most supports the
  answer (for a deduction, the main line of the reasoning).
- Short, factual answer; **one single** right answer, unambiguous, supported by
  the text - never by outside knowledge.

### Every question must stand up WITHOUT its choices

The learner will not always see them: their card may show only two, or none at
all, and the question is then answered from memory. Two consequences, and they
are imperative:

- **The Answer states itself alone**: a short sentence, one that can be said
  from memory before looking at anything. Not "the second one", not "the one on
  line 3", not an answer that only means something next to the others.
- **Never a pure recognition question**: "Which of these statements is true?",
  "Among these sentences, which sums up the text?" mean nothing without choices.
  Ask what the text says, not which of four choices it supports.

**A question without three honest decoys is not asked.** If you cannot find three
frankly other things, plausible to someone who has not read, then **ask another
question, or hand back one card fewer** - the number asked for is a ceiling, not
a target, and one card fewer costs nothing. Never pad: a rewording of the answer
or an absurd decoy damage the card. And never hand back `"Decoys": []`: a card
with no choices can no longer be given any, and it is the learner's display
setting, not yours, that decides whether a question is answered from memory.

### The four choices look alike

A learner who did not understand must find nothing in the **shape** of the choices to go
on. The commonest give-away is the right answer standing out as the longest and the most
detailed: it carries what the text says, while decoys made up from nothing come out short
and generic - and "when in doubt, pick the longest" then beats reading.

- **Same length**: the four within a few words of one another. The Answer is never the
  longest by a clear margin, and over a batch of cards it is as often among the shortest
  as among the longest.
- **Same shape**: the same grammatical form (all a time, all a noun phrase, all
  "Because…") and the same level of detail. If the Answer gives a cause and its
  consequence, or two details, each decoy does too; if a decoy is a bare noun, so is the
  Answer.
- **Cut the Answer down** to what answers the question, and **build the decoys out of the
  text**: a place, a time, a person or an object it does mention, set in the wrong place.
  Such a decoy is as specific as the Answer and plausible to whoever half read the text, where a
  generic one is dismissed on sight.
- **Nothing else singles it out**: it is not the only hedged choice ("Around 8:45" among
  "At 9:00" and "At 8:30"), nor the only one that takes up the words of the question or
  of the text.

## Kinds of question - vary the registers

Do **not** confine yourself to questions whose answer is written word for word.
Vary between:

1. **Direct fact** - information explicitly written.
2. **Deduction** - a cause, consequence or implication to be deduced from the text.
3. **General idea** - the subject or main message.
4. **Intention / the author's point of view** - why they write this, what they
   are trying to get accepted, or what is likely to follow. This is what the JLPT
   tests in 読解 from N3 on, and it cannot be made up: only ask the question if the
   text really carries a point of view, which a factual news brief does not.

Balance by level: N5-N4 mostly direct facts with a few simple deductions; N3-N1
more deductions, general idea and intention.

**Safeguard (imperative)**: even a deduction or intention question must have
**one single** right answer, **unambiguous** and **clearly supported by the
text** - never by outside knowledge. The decoys are plausible but contradicted or
unsupported by the text.
