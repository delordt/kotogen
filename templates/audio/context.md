# Context

The Anki listening card plays an audio file and asks a question about it, with written
choices or a picture (often the figure from the JLPT booklet).

The card content follows the language of the cards (`all.lang`), English by default. The
field and tag names below do not: they are the names of the note type in Anki. The audio and
its transcript are in Japanese.

The card has no colour of its own: it uses the colour of its text, like the reading card,
and green marks only the answer (the right choice, the key line and its tick on the bar).
The question is the title of the card, under a badge with the level the note is filed under
(`Level::N4`, read from the tags; `audio.badge=no` removes it).

The card draws its own player: a round play button, a progress bar, the time, and a speed
button that goes 1× → ¾× → ½× and back, for that card. It drives the media element of the
`Audio` (or `Video`) field and removes its controls; if the script does not run, the
system's player stays and still plays, and `audio.player=native` always keeps it. On the
back, the bar has a tick where each sentence of `Timecodes` starts (the key line's in
green), and touching a tick acts like clicking its sentence.

The player is sticky: when you scroll, it stays at the top of the screen with a light
shadow, so you can pause it while reading the transcript further down, on a phone too
(AnkiDroid).

The choices are **shuffled on display**, not at generation. Both faces compute the same
order from the `ID` and `Question` fields and the review day (which starts at 4 a.m., Anki's
default). The order changes every day, so you remember the answer, not its letter. The CSS
hides the choices until the script has run, so a failed script shows no choices rather than
the fields in their stored order, answer last.

On the back, the right answer is **highlighted in place** among the choices; when the front
showed none, the back writes it out in full. Then comes the Japanese transcript, in a block
folded by default (`audio.transcript=unfolded` opens it): one line per sentence with
furigana, the speakers of a dialogue in a column, and the key line marked by a green rule on
the left. A "訳" button at the end of its title shows the translation in small print under
each line (under each turn, in a dialogue). It is off when each card opens, so that you read
the Japanese first (`audio.translation=at-once` starts it on, `never` removes it).

**Clicking a sentence of the transcript plays that sentence alone**, using `Timecodes`:
playback stops where the next sentence starts (`audio.click=continue` lets it play on). Each
sentence keeps its own start time inside a turn that groups several, and the sentence being
heard is highlighted. A click that ends a text selection does nothing, and a line without a
start time shows no pointer and no hover effect.

## Fields

- `ID`: a unique ID: the name of the media file the card plays, without its extension, then
  the rank of the card (`K23_01_3f9ac1d2_001`)
- `Audio`: the tag that plays the audio file, written in full
  (`<audio controls src="K23_01_3f9ac1d2.mp3"></audio>`), since Anki only finds the media a
  note uses in its fields. **Empty** when the card carries a video
- `Video`: the tag of the video clip (`<video ... src="ep03_01_a1b2c3d4.webm">`), when the
  source was a video and its picture was kept (`kotogen audio episode.mkv --video`).
  **Exclusive of `Audio`**: the filled field says which media plays, since Anki's template
  language can only test whether a field is empty. The video takes at most 45% of the screen
  height, 22% when it sticks to the top
- `Question`: the question about the audio (no TTS: only the audio is spoken). It may quote a
  Japanese term heard in the audio when the question is about that term, and is shown with
  its furigana. On an item with a choice of replies (発話表現, 即時応答), the program writes
  the question itself, the same for every such item: "Which of the three replies fits?"
- `Decoy1`, `Decoy2`, `Decoy3`: three wrong answers (fewer when the model returned fewer).
  The note carries them all; how many the card shows is the "Number of choices" setting of
  the "Templates" menu (`audio.choices`: four, two, none, or alternate, which shows them on
  odd-ranked cards only, the rank being read from the `ID`), so changing it does not call the
  AI again. `Decoy1` is empty on the card that carries the figure, on an item with a choice
  of replies, and when the model returned no decoy: these cards show no written choices,
  whatever the setting
- `Image`: the figure of the exercise, from the JLPT booklet: four choices **drawn** and
  numbered (課題理解 of the N5), or only a **context** labelled ア/イ/ウ whose choices are
  given elsewhere (the N4). The card shows the picture whenever the field is filled, and the
  written choices whenever `Decoy1` is. Filled in automatically for a past-paper item: a
  section downloaded from the JLPT samples, whose booklet comes with it, or your own file
  named after its position, with the PDF booklet of its level beside it (see
  [Listening](../../docs/listening.md)). Only one card of the passage gets it: the one that
  asks the question of the exam. That card has no decoys, as you choose on the figure, and
  its back writes the `Answer` out in full
- `Answer`: the right answer, a short sentence that stands on its own, since the back writes
  it out in full when the card shows no choices. **Except** on an item with a choice of
  replies, where it is the Japanese reply that fits, number included
  (`3 あっ、お 茶[ちゃ]をお 願[ねが]いします`): translated, the three replies would leave only
  the prompt to listen to. The card shuffles the answer in among the decoys; it is never
  copied into a decoy field
- `Transcript`: the Japanese transcript of the audio, as plain text (the export removes any
  HTML tag), one line per sentence (line break = Shift+Enter in Anki's editor), furigana in
  the `漢字[かんじ]` format. In a conversation, each line starts with its speaker (`A：`,
  `B：`, or a name or role the audio states); a news bulletin, a monologue or an unclear case
  has no labels
- `Translation`: the translation of the transcript, as plain text, line by line with
  `Transcript`
- `Timecodes`: the second each line of `Transcript` starts at, separated by spaces
  (`0.50 3.00 4.20 7.10`), matched to the lines by rank like `Translation`. A line is found in
  the sound by its spelling, failing that by its reading in kana; failing both, its start is
  spread between its neighbours in proportion to the length of the texts. A `-` leaves the
  line shown but not clickable. Empty when no line was found in the sound. Never shown
- `KeyLine`: the rank (from 1) of the line of `Transcript` that best supports the answer,
  which the back marks with a green rule; empty, no line is marked. A field rather than a
  marker in the transcript, as on the reading card: the transcript stays the same on every
  card of the passage, and a correction in Anki is a number to type
- `Source`: where the audio comes from: the address of an NHK Easy article (kept whole; the
  card makes a link of it), the feed and the episode of a podcast, the channel and the title
  of a YouTube video followed by the address of the passage (`... https://youtu.be/...?t=192`:
  the card shows the label as a link that opens the video at the extract), or the name of
  the original file. An extract cut from a longer file adds its bounds, so that each extract
  points to its own part (`collection.mp3 (03:12 → 04:50)`). Shown in small print at the
  bottom of the back only (`audio.source=no` removes it): on the front, the title of an
  article could give away part of the answer

## Tags

- `Level::N5`, `Level::N4`, `Level::N3`, `Level::N2`, `Level::N1`

## Automatic generation

The generator makes the cards from an audio file:

```bash
kotogen audio K23_01.mp3 --count 3 --send
```

Whisper transcribes the audio, or a Japanese subtitle file beside it is used instead,
without calling Whisper. The AI then writes the questions, the transcript with furigana and
the translation. A video file is used for its sound track unless you keep its picture
(`--video`, or yes when the run asks): each passage is then cut as a VP9/WebM clip of at
most 480p, which the card plays, and a passage longer than 90 seconds falls back to sound
only. See [Listening](../../docs/listening.md).
