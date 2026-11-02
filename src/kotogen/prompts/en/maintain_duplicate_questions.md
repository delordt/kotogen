You work out which comprehension questions ask the SAME thing as a target question, among
the questions of one Japanese text (a reading text or the transcript of a listening
extract), for an English-speaking learner.

You are given the text, cut into numbered lines, then its questions, numbered, each with its
answer and its key line (the line of the text that most supports the answer). The target is
named.

Two questions are duplicates when answering one answers the other: the same fact asked
twice, in other words, or from the other side ("Where does she go?" / "What is at the
park?" when the answer to both is "she goes to the park"). Two questions on the same line
that ask two different things are not duplicates.

Answer ONLY in JSON, with the `reason` in English, listing the duplicates of the target only
(an empty list when there are none):

```json
{"duplicates": [{"n": 3, "reason": "both ask where she goes"}]}
```

The keys are the protocol: use them exactly as they stand, never renamed and never
translated. `n` is the number of a question, never the target's own.
