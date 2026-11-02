Two Japanese vocabulary cards risk being confused. Suggest a way of telling them apart
clearly, by adjusting the `Context` and/or the `Notes` of one and of the other.

The `Context` carries the distinction when the two cards have the SAME English
translation, and the `Notes` what sheds light after the answer. At least one of the two
cards carries a `Context` that points at it - a register badge is on the back, and the
question does not see it; the plainest may stay bare. A `Context` already in place and doing its job is not touched up.

{{include:vocab_fields}}

The field names are the note type's schema: use them exactly as they stand, never
renamed and never translated. What you write under them is English.

Stay concise. Do NOT change `Expression` or `Translation`, unless a correction is
indispensable.

Special case: when one of the two cards has NO place in the deck while the other is good (a
word that does not exist or is malformed, a wrong spelling, a wrong translation, a fragment
that is not used on its own, a card with no content to review), do not invent an artificial
distinction: ask for it to be deleted with `"delete"` (1 or 2). Only use `"delete"` if the
card kept already covers everything there is to learn; two really distinct words, two
nuances, two registers, two spellings that are both correct are told apart, they are not
deleted. When in doubt, tell them apart.

Answer ONLY in JSON, in one of the two forms:

```json
{
  "reason": "what tells them apart, in one sentence",
  "card1": {"Context": "upper body"},
  "card2": {"Context": "on the head", "Notes": "…"}
}
```

```json
{
  "reason": "why this card has no place, in one sentence",
  "delete": 2
}
```

Include only the fields really changed; leave out card1 or card2 if you do not touch it.
