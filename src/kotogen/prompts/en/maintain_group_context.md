Several Japanese vocabulary cards share the SAME English translation. On the `EN → JP`
front, the learner sees nothing but that translation and the `Context` field: as long as
those do not tell them apart, the question has several right answers and none of them can be
found. Give each card the `Context` that points at it and at no other.

What belongs to a batch:

- **The contexts are read together**: none of them may be able to point at two cards of
  the batch. Read them against one another before answering.
- **A register badge does not tell apart.** A card followed by `Tags=` carries a register
  (`Register::改まった語`, `Speaker::男性語`...) that the card shows on its back, with the
  answer: the question does not see it. When that register is what tells the card apart,
  its `Context` says it by naming the other card (*more formal than 友達*), and a
  `Context` already saying it is kept.
- A context already in place and doing its job is not touched up, and a comparison already
  in place (*more formal than 今*) is kept as it stands. Touch up a context that holds just
  as well for another card of the batch, take it back if it teaches nothing.
- **A translation that is too broad is corrected, not told apart.** A card that is in the
  batch only because its translation is inaccurate or cut short gets its right
  `Translation`, in 1 to 3 words, with no ";", no "/" and no bracket: 要点 is not
  `Essential` but `Key point`. It then leaves the batch, and its `Context` is emptied.
  Never retranslate to tell apart two words that really translate the same: those keep
  their translation and get a `Context`. A qualifier in brackets (`Aunt (someone
  else's)`) is not a translation: it is a `Context` moved into the question.
- **`Notes` that already tell the card apart** (*of living beings*) hold its `Context` in
  disguise: make the `Context` of it and take that part out of the `Notes`, keeping the
  rest as it stands. What the `Context` says goes out of the `Notes` even worded otherwise
  (`Context` *rainfall*, `Notes` *Of rain, of snow*). The `Notes` you hand back replace the
  whole field.

And what holds for every vocabulary card:

{{include:vocab_fields}}

The field names are the note type's schema: use them exactly as they stand, never
renamed and never translated. What you write under them is English.

Stay concise. Never change the `Expression`, and the `Translation` only for the reason given above.

If two cards of the batch are in fact the SAME word (the same Japanese word under two
spellings or two cuttings of the furigana), do not invent two contexts for them: report them
in `duplicates`. One kanji read two ways (末[すえ], 末[まつ]) is two words. Two really distinct words are told apart, they are not reported; when in
doubt, tell them apart.

Answer ONLY in JSON. The keys are the protocol and stay exactly as they are:

```json
{
  "reason": "what tells the batch apart, in one sentence",
  "cards": [
    {"n": 1, "Context": "paid employment"},
    {"n": 2, "Context": "task to be done", "Notes": "…"},
    {"n": 3, "Context": ""},
    {"n": 4, "Translation": "Key point", "Context": ""}
  ],
  "duplicates": [[5, 6]]
}
```

`n` is the number of the card in the list. Include in `cards` only the cards really
changed, and leave out `duplicates` if there are none.
