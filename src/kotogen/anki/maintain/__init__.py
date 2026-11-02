"""Maintaining a deck in Anki: the notes read, shown, confirmed and written.

What to propose for a card is the library's (`kotogen.maintenance`); the flags,
the notes read and written through AnkiConnect, the question and the snapshot
taken first (`backup`) are here. `review` holds the command (`run_maintain`),
`flag_pass` the flag pass, `marks` the flags and what every pass shares, and
`lone_kanji` the cards with no place in the vocabulary; `leech`, `derive`,
`duplicates` and `listening` hold their own passes. Cards are read by
`anki.deck.card` and written back by their note id.
"""
