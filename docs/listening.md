# Listening (`kotogen audio`)

Listening comprehension cards: questions in the language of your cards, and the transcript
with furigana on the back. The audio can come from:

- a local **audio or video** file, transcribed by Whisper or taken from a subtitle file
  beside it;
- an [NHK News Web Easy](https://news.web.nhk/news/easy/) article, whose audio and text are
  captured automatically;
- an episode of a **Japanese podcast** (the latest, or an older one by its number);
- a **YouTube video**;
- a lesson of the free **いろどり** textbook;
- a 聴解 section of the **official JLPT past papers**;
- a reading from the **青空朗読** collection.

```bash
# As many questions as the audio supports, from an MP3 or a whole folder
kotogen audio K23_01.mp3
kotogen audio ./my_audio

# With an explicit cap: at most 4 questions, fewer if the audio is short
kotogen audio K23_01.mp3 --count 4

# NHK News Web Easy article: audio + transcript captured automatically
kotogen audio https://news.web.nhk/news/easy/ne2024XXXX/ne2024XXXX.html --send

# Latest NHK Easy articles without giving a URL - the articles already handled are
# skipped (history in ~/.kotogen/seen.json), so it can be run again every day
kotogen audio nhk                  # the 4 most recent not handled yet
kotogen audio nhk --latest 6       # the 6 most recent
# (to handle an article already generated again: pass its URL directly)

# Set aside the audio files over a given length (in seconds, optional)
kotogen audio nhk --max-duration 180
kotogen audio nhk --latest 6 --max-duration 150s

# Podcast: latest episode not handled yet, cut into its self-contained passages
kotogen audio teppei
kotogen audio teppei --max-duration 90 --send
kotogen audio sakura-tips --latest 2
kotogen audio teppei-original --episode 42   # a given episode, to work through an archive
kotogen audio https://a-podcast.example/rss   # any feed, no alias needed
kotogen audio nhk-radio            # the NHKラジオニュース bulletins, at broadcast speed

# The free いろどり textbook: the next lesson, its dialogues one by one
kotogen audio irodori-shokyu1
kotogen audio irodori-shochukyu --episode 7

# The official JLPT past papers: the 聴解 sections of a level
kotogen audio jlpt-n3 --send

# 青空朗読: literature read aloud, from the shortest to the longest
kotogen audio roudoku --max-duration 600

# A collection (JLPT past papers, shadowing book): cut into one card per
# conversation, without having to open it in an audio editor
kotogen audio jlpt_n3_choukai.mp3
kotogen audio K23_01.mp3 --no-split    # or not: the file goes in one piece

# A video file: the sound track is extracted, the card stays an audio card
kotogen audio episode.mkv
kotogen audio ./season1        # a whole folder, videos and audio files mixed
kotogen audio lesson.mkv --video   # or the picture kept: the card plays a clip

# A shelf of series: the sub-folders are walked too, and what has already
# been handled is not handled again on the next pass
kotogen audio ./animes
kotogen audio ./animes --latest 3   # three episodes, the next pass takes the next three

# A lighter Whisper model (faster, less faithful)
kotogen audio K23_01.mp3 --whisper-model small
```

## Options

| Option | Effect |
|---|---|
| `--count N`, `-n` | **Maximum** number of cards per audio or per article, or `auto` (default) |
| `--latest N` | Number of items handled: NHK articles (default: 4), podcast episodes, YouTube videos, いろどり lessons or 青空朗読 readings (default: 1), past-paper sections and local files (default: all) |
| `--episode N` | Podcast episode to start from instead of the latest, or いろどり lesson number. Refused for YouTube, the past papers and 青空朗読 (see each section) |
| `--level N4`, `-l` | JLPT level (default: `auto`, detected) |
| `--max-duration SEC` | Set aside audio longer than this (`180` or `180s`): an NHK article, a 青空朗読 reading (before the download), and each passage cut from any source but NHK. On a stream or a fiction the splitter aims below it, so a shorter limit gives shorter passages, not fewer |
| `--max-video SEC` | YouTube only: set aside a video longer than this, measured **before** downloading it |
| `--no-split` | Do not split: each file goes in one piece, announced number included (default: splitting on) |
| `--whisper-model MODEL` | Whisper model for transcription: tiny, base, small, medium, large (default: `medium`) |
| `--audio-quality LEVEL` | Compression of the audio downloaded or cut: `none` (default, no compression), `light`, `medium`, `strong` |
| `--video` / `--no-video` | Video sources: keep the picture, or the sound track only (default: `KOTOGEN_VIDEO`, which asks) |

The options shared by every command (`--send`, `--output`, `--model`...) are in
[Global options](global-options.md).

## Podcasts

A podcast is an RSS feed, read with no key, token or session. Kotogen reads RSS 2.0,
RSS 1.0/RDF and Atom, with the same reader as the press catalogue of
[reading](reading.md#a-press-article). It takes the latest episode **not handled yet**,
downloads it, transcribes it, and passes it to the splitter, which keeps only the passages
that stand on their own.

```bash
kotogen audio teppei                    # latest episode not handled yet
kotogen audio teppei --latest 3         # the 3 latest
kotogen audio sakura-tips --max-duration 90 --send
kotogen audio haru                      # an N2-N1 show, see the table below
```

### Working through an archive from the start (`--episode`)

Following new episodes suits a running show, not an archive of seven hundred episodes you
want to do in order. `--episode N` sets the starting point, and `--latest` how many episodes
to take in a row:

```bash
kotogen audio teppei-original --episode 1              # the very first episode
kotogen audio teppei-original --episode 42 --latest 3  # episodes 42, 43 and 44
```

**No. 1 is the first episode published**, and the numbers go towards the most recent. When
exactly one episode announces the number in its title (`#512`, `318.`, `Ep87`, `No 141`,
`episode96`), that episode is taken; otherwise the number is the rank from the oldest. The
two counts differ by a few on a show with specials or skipped numbers, so the title of each
episode is shown before the download.

An episode asked for by number **ignores the history**: it is handled even if it already was.

### Known aliases, by level

| Level | Alias | Podcast | |
|---|---|---|---|
| N5 | `slow-japanese` | Slow Japanese (Akari) | the only one that truly slows down, down to the syllable: the entry point with no background |
| N5-N4 | `ako` | 日本語 with あこ - Nihongo Picnic | 100% Japanese from the first episode, short format |
| N5-N4 | `sakura-tips` | SAKURA TIPS｜Listen to Japanese | 650 episodes of 5 min, well articulated, transcribed on the site (archive) |
| N5-N4 | `shun` | Japanese with Shun | Genki 1-2 grammar, level announced in the title, 350 episodes |
| N5-N4 | `teppei-beginner` | Japanese podcast for beginners (Nihongo con Teppei) | 1,500 short episodes, the beginner's classic |
| N5-N1 | `tomo` | Let's Talk in Japanese! | one teacher, one topic, and the JLPT level in the title of each episode |
| N4-N3 | `sayuri` | Everyday Japanese Podcast (Sayuri) | everyday life in Japan, one notch above the textbook |
| N4-N3 | `teppei-original` | Nihongo con Teppei Original | the first 700 episodes of the intermediate series, before Z (archive) |
| N4-N3 | `teppei-z` | Nihongo con Teppei Z | 800 episodes, the direct sequel of the original series (archive) |
| N3-N2 | `bitesize` | The Bite Size Japanese Podcast (Layla) | natural Japanese about language, culture, methods |
| N3-N2 | `noriko` | Learn Japanese with Noriko | 3 seasons faster and faster, 750 episodes |
| N3-N2 | `teppei` | Nihongo con Teppei 波! | Teppei's **running** series, a monologue at natural speed |
| N3-N2 | `thinking` | Thinking in Japanese Podcast | a calm pace but never artificial, in-depth topics |
| N3-N2 | `yuyu` | YUYUの日本語Podcast | long episodes (40 min), social topics |
| N2 | `miku` | The Miku Real Japanese Podcast | Japanese as it is really spoken |
| N2 | `toranomaki` | Nihongo Toranomaki | real conversations, kept as they are |
| N2-N1 | `haru` | N2~N1日本語！Haru no Nihongo | culture, current affairs, life in Japan |
| N2-N1 | `teppei-noriko` | Japanese with Teppei and Noriko | a conversation for two, without slowing down |
| N1 | `4989` | 4989 American Life | a podcast by natives, speed and vocabulary with no concession |
| N1 | `nhk-radio` | NHKラジオニュース | the bulletins of the public radio, several a day, 5 to 15 min |
| N1 | `coten` | コテンラジオ (COTEN RADIO) | history told to natives: no adjustment, dense vocabulary |

The level only helps you choose a show: it goes neither to the splitter nor to the AI, and
`--level auto` still estimates each passage. It is an estimate, from what the show says of
itself when it says anything; the speed varies from one episode to the next.

`nhk-radio` is NHK's radio news at broadcast speed, with no adjustment for learners. Its feed
keeps only the latest bulletins, so there is no archive and `--episode` is of no use there.

Teppei opens a new feed for each new main series (Original, then Z, then 波): `teppei` is
always the **current** series, and the earlier ones keep their own alias and episodes. A
podcast that has stopped publishing is still a valid source.

### Any other podcast

An alias is only a shortcut: **any RSS feed URL works**, with no sign-up.

```bash
kotogen audio https://a-podcast.example/rss
```

To give a feed a short name, create a `podcasts.json` file in the data folder
(`%LOCALAPPDATA%\kotogen\` on Windows, `~/Library/Application Support/kotogen/` on macOS,
`~/.local/share/kotogen/` on Linux):

```json
{
  "my-teacher": {
    "name": "My teacher's podcast",
    "feed": "https://example.test/teacher/rss",
    "levels": "N4-N3"
  }
}
```

`feed` is required; `name` defaults to the alias. `levels` is optional and can be written
`"N4-N3"`, `"N4, N3"` or `["N4", "N3"]`. A show with no level comes last in the list, with an
empty level column. An entry that reuses a built-in alias replaces it, so a feed that has
moved can be fixed without waiting for a release.

### What to expect

**One to four passages per episode** is the normal result. A monologue like Teppei's
digresses and is full of `これ`, `さっきの話` and pronouns with no referent, and the splitter
sets aside every passage that depends on what came before (see [A continuous stream is not a
collection](#a-continuous-stream-podcast-interview-is-not-a-collection)). An episode that
gives no card is marked as handled all the same, and the run says it gave none: offered
again, it would cost its splitting at every run. An episode whose run failed (a network
error, an interrupted call) is not marked, and the next run offers it again.

The show's **packaging** is always set aside: opening theme, greeting, introduction, sponsor
message, call to subscribe. It makes sense out of context, but it is the same every week and
would give the same card each time.

### What stays on the disk

The episode and its transcript stay in the cache (`podcasts/<alias>/`), **the last three per
podcast**. Running the same episode again with another maximum duration or level costs
neither the download nor the transcription. A transcript serves only the Whisper model that
made it: `--whisper-model large` transcribes again an episode `small` has done, including
when `small` stood in for a `medium` that would not load. The cache is disposable: if it is
deleted, everything is downloaded and transcribed again.

Handled episodes are recorded in `~/.kotogen/seen.json`, per podcast and per mode, so
`--latest N` means **the N most recent episodes not handled yet**, as with the `nhk` keyword:
each run of `kotogen audio teppei` takes the next episode, and a catalogue of 250 episodes
can be worked through one a day without keeping a list. To redo an episode, name it by its
number (`--episode 12`). To start a podcast from scratch, forget it in the source history of
the settings screen (see [The settings](interactive.md#the-settings)).

The deck is a second memory: an episode whose cards are already in it is skipped even if this
machine's history does not know it, so a second computer needs nothing copied over (see
[The deck, a second memory](interactive.md#the-deck-a-second-memory)).

## YouTube videos

YouTube works like the podcasts: a catalogue of channels by level, a history and a cache.
Each video is downloaded, then handled like a local file.

```bash
# Latest video of a channel from the catalogue, sound track only
kotogen audio onomappu

# The same, but the card keeps the picture
kotogen audio nij --video

# The 3 latest videos (Shorts do not count: they are set aside)
kotogen audio tekuteku --latest 3

# A given video, a channel or a playlist, no alias needed
kotogen audio https://www.youtube.com/watch?v=XXXXXXXXXXX
kotogen audio https://www.youtube.com/@a-channel
kotogen audio https://www.youtube.com/playlist?list=PLXXXXXXXX

# Videos under 15 min, and passages under 90 s inside them
kotogen audio speak-naturally --max-video 900 --max-duration 90
```

**Prerequisites**: `pip install -e ".[youtube]"` (yt-dlp), plus FFmpeg. The catalogue and the
menu work without them: listing a channel's videos only reads its Atom feed.

### Japanese subtitles replace Whisper

This is the main point of this source, and what the catalogue was chosen on: many immersion
channels publish Japanese subtitles **written by hand**. Such a track is downloaded with the
video and placed beside it, the listening chain finds it (see [The subtitle laid beside it
replaces Whisper](#the-subtitle-laid-beside-it-replaces-whisper)), and **Whisper is not
called**. The transcript is then more faithful, free, and timed by hand.

Before the download, each video is announced with its length and whether it has subtitles:

```
Onomappu
   Probing the videos… (1 kept)
   Sample video title (10 min 54 s, Japanese subtitles provided)
```

YouTube's **automatic** subtitles are refused: they have no punctuation, which the splitting
and the transcript on the back depend on. A video without a hand-written track is transcribed
by Whisper, and its line says so (`transcription to be done`).

A video whose sound YouTube declares in a language other than Japanese is set aside, even
with a hand-written Japanese track: that track is a translation, and the card would have its
sound and its transcript in two languages. A video with no declared language goes through, as
many channels leave that field empty.

### Known channels, by level

| Level | Alias | Channel |
|---|---|---|
| N5-N4 | `japarrot` | Japarrot! - Let's Learn Japanese |
| N5-N4 | `kensan` | けんさんおかえり Japanese |
| N5-N3 | `nihongo-learning` | Nihongo-Learning |
| N5-N3 | `nihongo-no-jikan` | にほんごのじかん (Japanese Comprehensible Input) |
| N5-N2 | `nij` | Natural Japanese (NIJ) |
| N4-N3 | `akane` | あかね的日本語教室 |
| N4-N3 | `naoko` | Daily Japanese with Naoko |
| N4-N3 | `tekuteku` | てくてく日本語 (Japanese Podcast) |
| N3-N2 | `onomappu` | Onomappu |
| N3-N2 | `speak-naturally` | Speak Japanese Naturally |
| N3-N1 | `listening-lab` | Easy Japanese Listening Lab |
| N2-N1 | `jiro` | Jiro, just Japanese |

Each channel was checked before it entered the catalogue: its latest videos carry a
hand-written Japanese subtitle track over Japanese sound. The level is an estimate, taken
from what the channel says of itself or from its reputation; speed and vocabulary vary from
one video to the next.

Two channels no longer publish: `onomappu` since August 2025, `japarrot` since March 2024.
They stay in the catalogue, but a channel's Atom feed holds only its fifteen latest videos,
with no archive: once the history has seen those fifteen, nothing is left.

The shows of the podcast catalogue are not repeated here: Teppei, Shun and Miku also have
channels, and listing them twice would offer the same content twice.

### Any other channel

As for podcasts, an alias is only a shortcut. To give a channel a short name, create a
`channels.json` file in the data folder (`%LOCALAPPDATA%\kotogen\` on Windows,
`~/Library/Application Support/kotogen/` on macOS, `~/.local/share/kotogen/` on Linux):

```json
{
  "my-channel": {
    "name": "My teacher's channel",
    "feed": "UCXXXXXXXXXXXXXXXXXXXXXX",
    "levels": "N4-N3"
  }
}
```

`feed` takes the identifier shown on the page (`UC...` for a channel, `PL...` for a
playlist), or the URL of a channel (`.../channel/UC...` or `.../@name`), a playlist or a
feed. A handle (`.../@name`) is read off the channel's page each time the alias is used, as on
the command line: if the page cannot be read, the run says why and skips the channel.

### What does not exist here: the episode number

`--episode` does not apply to YouTube, and is refused with an explanation. A channel's feed
holds only its **fifteen latest videos**, with no archive, so a number counted from the
oldest would point to a different video after each upload. For a given video, pass its URL;
for the N most recent, use `--latest N`.

### Shorts are set aside

A channel's feed mixes videos and Shorts without telling them apart, and many channels
publish more Shorts than videos. Every video **shorter than two minutes** is therefore set
aside, and the run says so:

```
あかね的日本語教室
   Probing the videos… (1 kept, 3 already handled, 1 dropped)
   サンプル動画 (13 min 05 s, Japanese subtitles provided)
   ! サンプルのショート動画: 46 s, too short for a card
```

`--latest` counts the videos **kept**: asking for the latest video of a channel that has just
published a Short gives its latest real video. The two-minute floor also applies to a Short
pasted as a URL.

### Picture or sound track: the choice is made before the download

For a local file, the video is already on disk, and the choice only decides what is kept. For
YouTube it decides what is **downloaded**: a few megabytes of sound, or a few hundred of
video. The question is therefore asked **before** any download, once per command and never
per video: `--latest 3` asks it once. See [Keeping the picture](#keeping-the-picture---video)
for the three settings.

### What stays on the disk

The media, its subtitle and its transcript stay in the cache (`youtube/<alias>/`), **the last
three per channel**. Handled videos are recorded in `~/.kotogen/seen.json`, per channel and
per mode, so `--latest N` means **the N most recent videos not handled yet**, as for podcasts
and NHK articles. A video that gave no card is recorded all the same, as a podcast episode
is; one whose run failed is not, and will be offered again.

The deck is a second memory here too, through the short video address the card keeps: a video
already in Anki is skipped even on a machine whose history is empty (see
[The deck, a second memory](interactive.md#the-deck-a-second-memory)).

A catalogue channel pasted as a URL keeps its alias, and therefore its history and its
cache. A channel can be forgotten in the source history of the settings screen (see
[The settings](interactive.md#the-settings)); its most recent videos are then offered again.

## いろどり, the Japan Foundation's free textbook

[いろどり 生活の日本語](https://www.irodori.jpf.go.jp/) publishes its four volumes (入門,
初級1, 初級2, 初中級) as PDF and MP3, free and without an account. Its dialogues are short,
self-contained everyday exchanges (at a counter, with a colleague, with a neighbour), and each
volume states its level.

```bash
kotogen audio irodori-shokyu1              # the first lesson not done yet
kotogen audio irodori-shokyu1 --latest 3   # the next three lessons
kotogen audio irodori-shochukyu --episode 7   # lesson 7, whatever the history says
kotogen audio irodori-nyumon --send
```

| Alias | Volume | Level |
|---|---|---|
| `irodori-nyumon` | いろどり 入門 (A1) | before N5 |
| `irodori-shokyu1` | いろどり 初級1 (A2) | N5 |
| `irodori-shokyu2` | いろどり 初級2 (A2) | N5-N4 |
| `irodori-shochukyu` | いろどり 初中級 (A2/B1) | N4-N3 |

The JLPT level is an estimate: the Japan Foundation grades its volumes on the JF Standard
scale (A1/A2/B1), not in JLPT levels.

### The lesson is the unit, as the episode is for a podcast

A volume has eighteen lessons, and the history records **lessons**. A textbook is worked
through in order: without a number, `kotogen audio irodori-shokyu1` takes the first lesson
not handled yet, so each run moves on by one lesson. `--episode N` takes lesson N and ignores
the history, as for a podcast.

The deck is a second memory here too, through the volume and lesson number the card keeps: a
lesson done on another computer is skipped (see
[The deck, a second memory](interactive.md#the-deck-a-second-memory)).

A lesson gives eight to ten cards, already a full session: hence `--latest 1` by default.

### What is kept of the lesson, and what is set aside

A lesson page has fourteen to thirty-five tracks. Only the **聞く** (`kiku`) and **会話**
(`kaiwa`) tracks are downloaded: they are the dialogues. The others are drills that would
make poor cards: `kotoba` is a list of words read one after the other, `katachi` a
conjugation table, `hanasu` a single model sentence, `strategy` advice on method.

The list of tracks is read from the lesson page when the lesson is handled, as their
numbering varies from one lesson to the next. So are the topic and the **title** of the
lesson, which are then kept in the cache: kotogen ships nothing of the textbook. Without the
site and before the first reading, a lesson goes by its number (第3課).

In [interactive mode](interactive.md), いろどり is under **A book**, with 青空朗読. The
textbook is also a reading source (see [Reading](reading.md#いろどり-the-lesson-as-a-pdf)).

## Official JLPT past papers

[jlpt.jp](https://www.jlpt.jp/samples/sampleindex.html) publishes three free sample
collections, without an account: the 問題例集 of 2009 and the two 公式問題集 (2012 and
2018). Each gives, for the five levels, the booklets as PDF and the audio of the 聴解 part.

```bash
kotogen audio jlpt-n3              # the 聴解 sections of the 2018 collection, level N3
kotogen audio jlpt-n5 --send
kotogen audio jlpt2012-n2          # the 2012 collection
kotogen audio jlpt2009-n4          # the oldest, in one piece
```

**The level is part of the alias**: `jlpt-n3`, not `jlpt --level N3`. `--level` sets the
level of the cards, whereas the alias names a collection. `jlpt` alone lists the aliases you
can type.

The cards take the level of the paper: `Level::N3` for every card of `jlpt-n3`. Nothing is
estimated (an estimate would rate the easy example that opens each section one level too
low), and `--level` does not change it; it still applies to the other sources of the same
command.

| Alias | Collection |
|---|---|
| `jlpt-nX` | JLPT 公式問題集 第二集 (2018) |
| `jlpt2012-nX` | JLPT 公式問題集 (2012) |
| `jlpt2009-nX` | JLPT 問題例集 (2009) |

### A section is not an item

`N3Q1.mp3` holds the whole 問題1, its six or seven items one after the other. The splitter
makes separate cards of them, as for any collection. A level weighs about fifty megabytes.

Each section is recorded in the history separately: running the command again takes the
sections left, and a finished collection says so instead of downloading again only to give
duplicates that Anki would refuse. `--latest N` takes fewer sections at a time. There is no
`--episode` here: a collection is closed.

The deck is checked too, through the collection name and section number the card keeps: a
level done on another computer is recognised (see
[The deck, a second memory](interactive.md#the-deck-a-second-memory)).

### The figure of the exercise, found through the sound

These cards carry the figure of their exercise when it has one (see
[The figures of the JLPT past papers](#the-figures-of-the-jlpt-past-papers-the-image-field)):
the listening booklet of the collection is downloaded automatically.

The official file only identifies the **section** (`N5Q1.mp3` holds the whole 問題1). The item
number comes from **the audio itself**, which announces 「3番」 before each exercise: the
splitter already finds that number to cut it out of the sound, and its value picks the
figure. The rank of the passage in the file is never used, since the opening example and the
passages set aside shift it. Two cases give no picture:

- **a number that was not heard**: the passage is made without a figure;
- **a number announced twice**: the transcript sometimes repeats an announcement on the bell
  that ends the time for reading the choices, just before **another** item's conversation.
  Nothing says which one is right, so neither is used.

The 2009 collection has no figures at all. Its single audio holds **the whole exam**: the
track number is 1 everywhere, and since the 「◯ばん」 start again at 1 in each section, item 3
of 問題3 cannot be told apart from item 3 of 問題1.

The 読解 booklets of the same collections are a reading source (see
[Reading](reading.md#official-jlpt-past-papers)).

### The exercises with a choice of replies (発話表現, 即時応答)

Two sections of the exam are not conversations. The audio gives a **prompt** (a sentence
addressed to someone, or a situation followed by 「何と言いますか」), then **three replies
numbered 1, 2 and 3**, of which only one fits:

```
1番  これから図書館に行くんですが、何か返しておきましょうか
1    いいですよ
2    そうですか、残念ですね
3    あっ、じゃあこの本をお願いします
```

Treated as a conversation, the three replies would read as three sentences from the same
speaker. These items are therefore recognised **before** generating, in this order:

| What one wants to know | Where it comes from | Cost |
|---|---|---|
| The type of the exercise | The make-up of the exam, fixed since 2010: 問題3 of the N4 is a 発話表現, its 問題4 a 即時応答 | free |
| Failing that, the shape of the passage | Three lines opened by 1, 2 then 3 in the transcript | free |

The table assumes that a file is **one section**, as in the 2012 and 2018 collections. The
2009 collection holds the whole exam in one file, so only the shape of the passage answers. A
fourth numbered line makes it answer no: the passage is then a 概要理解, whose audio reads its
choices after the question, and those choices are set aside.

Such an item gives **a single** card, with **no written choice**. The front plays the audio,
shows the figure if there is one, and asks the same question on every item, "Which of the
three replies fits?": the exam prints no question, and one that described the situation would
give away what the audio is there to tell. You choose 1, 2 or 3 in your head. The back gives
the reply that fits, **in Japanese** with its number, marked as the key line of the
transcript. The translation stays behind the 訳 button, off by default.

The replies are not written as choices because **they are the exercise**. Translated, they
would leave only a four-second prompt to listen to, and the right one could be picked on
common sense alone:

> I am going to buy some juice, shall I get you something? -> *"Ah, a coffee please"* /
> *"It's fine"* / *"Oh yes, that looks good"*

A fourth choice would have to be invented, and would stand out without listening. The
generator empties the decoys itself, whatever the model returned.

The 発話表現 has a figure in the booklet; the 即時応答 never has one (the audio says so:
「絵などがありません」).

## 青空朗読, literature read aloud

[青空朗読](https://aozoraroudoku.jp/) has works of the 青空文庫 read by professional
announcers and trained amateurs: fifteen hundred readings, free to listen to, without an
account.

```bash
kotogen audio roudoku                        # the shortest not handled yet
kotogen audio roudoku --latest 3
kotogen audio roudoku --max-duration 600     # nothing over ten minutes
kotogen audio https://aozoraroudoku.jp/voice/rdp/rd020.html   # a given reading
```

**The collection is worked through from the shortest reading to the longest**, from under a
minute to two and a half hours: sorted by length, it tells you what you can listen to in full
today. There are no new releases to follow, so `--episode` is of no use here.

`--max-duration` is applied **before** the download, since the catalogue gives the length of
each reading: a reading that is too long is never downloaded.

The deck is a second memory here too, through the title and author the card keeps (see
[The deck, a second memory](interactive.md#the-deck-a-second-memory)).

The level is N2-N1: literature with no adjustment for learners. The same works can be read as
text (see [Reading](reading.md#青空文庫-the-public-domain-as-a-catalogue)), but the card is
made from the Whisper transcript, as the published text is not aligned with the sound.

The site forbids redistribution, not listening: the cards stay in your collection.

## A video file, and its subtitle if there is one

A drama, a filmed lesson, an interview or a recorded talk is a listening source like any
other, passed as it is.

```bash
kotogen audio episode.mkv
kotogen audio ./season1        # a whole folder, videos and audio files mixed
```

The **sound track is extracted first**, and only the sound goes through the chain: the card
stays an audio card, unless you ask for the picture (see
[Keeping the picture](#keeping-the-picture---video)). At the default notch
(`--audio-quality none`), the track is **copied without re-encoding** when its codec allows it
(AAC, ALAC, MP3, Opus, Vorbis, FLAC), so the card plays the original sound; any other codec
is re-encoded to MP3. This also keeps hundreds of megabytes of video out of
`collection.media` for thirty seconds of conversation.

Extensions read: `.mp4`, `.mkv`, `.webm`, `.mov`, `.m4v`, `.avi`, `.ts`. The original file is
never modified, and the card's `Source` field keeps its name, not that of the temporary
track.

### A shelf of series (a folder of folders)

A folder is walked **including its sub-folders**. A shelf with one folder per series, and one
per season below that, gives every episode it holds, series by series, in the order of their
names.

```bash
kotogen audio ./animes              # everything not handled yet
kotogen audio ./animes --latest 3   # three episodes at a time
```

In [interactive mode](interactive.md), **A local file** asks two more questions when the
folder holds a **series**: how many episodes to handle (one by default, out of the number
left) and how long a passage may last. A series is at least two video files in the same
folder numbered as episodes: `S01E03`, `第3話`, `ep03`, `Series - 03`, `03.mkv`, with the
tags between brackets ignored. A folder of unrelated videos gets neither question, and all
its files are handled.

```
Number of episodes to handle (12 left) [1] (b = back):
Max duration of the video, in seconds [no limit] (b = back): 30
```

**A file already handled is not handled again**, whether it gave cards or none; only one
whose run failed is taken again. A file walked from a folder is recorded in the history
(`~/.kotogen/seen.json`) like a podcast episode, and the next pass over the same folder
continues after it. The run says how many files it left out, and the history can be cleared,
whole or source by source, from the settings screen of the assistant.

A file **named on its own** ignores that history: `kotogen audio "./animes/My Series/ep03.mkv"`
makes its cards again, as an NHK article is redone by passing its URL.

A file is identified by its **name, its size and the name of the folder that holds it**, not
by its full path or its content: moving the series folder or remounting a disk changes
nothing, but renaming the folder that holds a file, re-encoding the file or downloading it
again from another source makes it new.

The sub-folder **names the cards**: an episode taken from `animes/My Series/S01` carries
`My Series/S01 - ep03.mkv` in its `Source` field, where `ep03.mkv` alone would mean nothing
six months later. A file directly in the folder named on the command line keeps its own name.

### Several sound tracks: the Japanese one is taken

An episode, a drama or a film often has two sound tracks: the original and a dub. Left to
itself, ffmpeg takes **the track with the most channels**, not the first one nor the one
marked as default: a 5.1 English dub rather than a Japanese voice in stereo, which would only
be noticed while reviewing. Kotogen therefore picks the track **declared Japanese**, and the
extraction line says so:

```
[1/1] episode.mkv
   Extracting the sound track… (Japanese track out of 2, the picture is left aside)
```

The language tags of the file decide (`jpn`, `ja`, `ja-JP`); when no track has a language
tag, the track titles are read instead (`Japanese`, `日本語`). When no track is Japanese,
nothing is guessed: ffmpeg's usual track is taken, and the run says so.

```
   ! 2 sound tracks, none declared Japanese: the main track is taken
```

A file with only one track raises no question. When the picture is kept, the video clip
carries the same track as the transcript.

### The subtitle laid beside it replaces Whisper

A subtitle file with the same name as the media is used **as it is** for the transcript:

```
episode.mkv
episode.ja.srt      <- taken, Whisper is not called
```

`.srt`, `.vtt` and `.ass` (`.ssa` too) are read, under the exact name (`episode.srt`) or the
name followed by a mark (`episode.ja.srt`, `episode.forced.srt`). When several match, a
Japanese mark is tried first, and under the same mark the `.srt` before the `.ass`. That
order only decides what is read first: each file is judged on its text, whatever its mark.

The transcript is then **more faithful** than Whisper's, written by hand while listening, and
**free**: the Whisper model is neither downloaded nor loaded.

**A track that is not in Japanese is ignored, and the run says so.** A video file usually
comes with its translation rather than its transcript (for anime, the Japanese track is the
one usually missing), which would fill the transcript on the back with English. Japanese is
recognised by its **kana**: at least half of the lines must contain some. Chinese shares the
kanji but has no kana, so the Chinese track an anime often comes with is rejected too.

```
   ! subtitle episode.en.srt ignored: not in Japanese
   Transcribing… (312 utterances)
```

### An `.ass` gives its dialogue, and nothing else

`.ass` is the usual format of anime subtitles, and it holds more than what is said: a fansub
draws signs and title cards as lines of their own, and times the karaoke of the opening and
ending syllable by syllable. Kotogen keeps what is heard:

- a line whose **style** is named for written text is left out: `Sign`, `Title`, `OP`, `ED`,
  `Karaoke`, `Romaji`, `Note`, `Credits`, `Rubi` (the readings of a TV caption), or their
  Japanese names (`看板`, `歌詞`, `ルビ`...);
- so is a line with a **karaoke** timing or a **drawing**, or whose `Effect` field is filled
  in (generated karaoke, scrolling credits);
- a **bilingual** release, with each language in a style of its own, gives its Japanese style
  only.

A line is not taken for a sign because it is positioned on the screen: a Japanese TV caption
converted to ASS positions every line, the dialogue included. The lines are put back in the
order they are shown, whatever order the file lists them in.

A subtitle has no timestamp per *word*, which the splitter uses to leave out the announced
number of a collection when the transcript joins it to the first line; it falls back on the
bounds of the line.

Those bounds are not speech bounds either: a line appears before the sentence is said and
stays on screen after its last syllable. The splitter **moves them onto the measured
silences**: a bound that falls inside a silence moves to its edge. Where there is no silence,
under an opening or closing theme, it uses a fixed margin, wider than for a Whisper timestamp
(0.30 s against 0.12 s), so the cuts of a video are less clean at its two ends than in the
middle.

### Keeping the picture (`--video`)

Sound only is the default: a listening card trains the ear, and the picture adds gestures, a
setting, sometimes the answer. But for a filmed lesson that shows what it talks about, or a
scene whose meaning depends on the place, the picture is the context.

```bash
kotogen audio lesson.mkv --video     # the card plays a clip, not an MP3
kotogen audio ./season1 --video      # every passage of every episode
```

Each passage is then **cut again from the original video** and placed in the media library
instead of the MP3: the card plays one media, and its tag goes into the `Video` field instead
of `Audio`. Nothing else changes: same splitting, same transcript (made from the sound track,
or from the subtitle beside the file), same timestamps, and **clicking a sentence of the
transcript jumps in the video** as it does in the sound.

The clip is **always re-encoded**: VP9 at 480p in a WebM, with mono Opus sound. `.mkv` and
`.avi` play in no WebView, and a file left as it is would give a black screen. A source
smaller than 480p is never enlarged.

**VP9 rather than H.264**, although H.264 is more widespread: Anki shows its cards in Qt
WebEngine, which is built **without the proprietary codecs**. Measured on Anki desktop
(Windows) on 26 August 2026, with the check card of `tests/codec_bench.py`:

```
MP4 / H.264 + AAC    REFUSED - the file could not be opened   (canPlayType: no)
WebM / VP9 + Opus    READ - frame decoded in 320x180          (canPlayType: probably)
```

VP9 and Opus are free codecs, present in every Chromium build, Anki's included, and in
Android's WebView. To measure again on another machine or Anki build, `tests/codec_bench.py`
puts its check card into Anki.

**A passage longer than 90 seconds falls back to sound only**, without a message: it is a
limit, not an error. The limit is on length rather than bitrate, since length is what fills
the media library: without it, a file handled **whole** (twenty minutes of drama) would go
into `collection.media` as video.

**Whether to keep the picture is asked, and a setting decides whether to ask.** The `i` key of
the [settings](interactive.md#the-settings) cycles through its three values and saves the one
chosen (`KOTOGEN_VIDEO`):

| Setting | What happens |
|---|---|
| `ask` (default) | the question is asked, once per command |
| `always` | the picture is kept, without asking anything |
| `never` | the sound track is extracted, without asking anything |

The question follows three rules: **once per command, never per file**
(`kotogen audio ./season1` and `--latest 3` ask once); **only when there is a picture** (an
NHK article, a podcast or a folder of MP3 files never asks); and **before any download**,
since for YouTube the answer decides what is downloaded.

In interactive mode, it is asked with the other questions, before the maximum duration (the
answer decides whether that duration applies to the video or to the audio):

```
Keep the picture (otherwise the sound track alone) (y/n) [n]:
```

On the command line, it is asked just before the download:

```
Keep the picture of the video: [p] yes  [s] sound only
```

With no one at the terminal to answer (a script, redirected input, continuous integration),
the answer is sound only, and so it is under [`--yes`](global-options.md#asking-nothing).
`--video` and `--no-video` give the answer in advance: they override the setting and ask
nothing. On a folder with no video, `--video` changes nothing.

On the card, the video player takes at most **45% of the screen height**, and shrinks to a
strip when it **sticks to the top** as you scroll: the sound goes on, the picture stays in
view, and the transcript has room again.

### Anime, the most asked-for source and the least convenient

The splitter treats an episode as a
[fiction](#a-fiction-is-neither-a-collection-nor-a-stream): its scenes are its passages, up
to eight per episode, and the opening, the recap and the next-episode preview are set aside.

The hard part is the transcription. A Japanese subtitle track is rare (you nearly always get
the English one), and without it Whisper works in the worst conditions: constant music and
sound effects, stylised voices, shouting, overlapping lines. The yield is lower than on a
podcast, and `--whisper-model large` is worth its wait. Dramas, vlogs, interviews and filmed
lessons are easier.

A **Japanese subtitle** beside the episode changes everything, whether an `.srt` or the
`.ass` fansubs come in (see
[An `.ass` gives its dialogue](#an-ass-gives-its-dialogue-and-nothing-else)): the transcript
is then written by hand, and Whisper is not called.

**Where to find episodes legally**: nearly all the official channels that post whole episodes
on YouTube block them outside Japan. Checked from outside Japan in September 2026, the few
reachable ones offered older series without a Japanese subtitle track; such a URL goes under
**A YouTube video**. Streaming services (Crunchyroll, ADN, Netflix) protect their episodes
with DRM and cannot be used.

## The figures of the JLPT past papers (the `Image` field)

A 課題理解 item asks its question in pictures: the booklet draws four choices, and the audio
does not say them. The card's `Image` field carries that figure.

The figure goes on **one card** of the passage: the one that asks the exam's own question
(「男の人はどれを買いますか」), whose options are the drawings. That card has no written
choices: you choose on the figure, as in the exam, and the back names the right option by
what it shows. The generator is told the passage has a figure, and marks that card; the other
cards ask about the conversation and carry no picture, since a figure beside a question it
does not illustrate would only mislead. When no card asks the exam's question, no card gets
the figure, and the run says so. An item with a choice of replies (発話表現) has a single card,
which takes the figure.

For a downloaded section (`jlpt-nX`), there is nothing to do: the listening booklet of the
collection is downloaded automatically, and the item number comes from the sound (see
[The figure of the exercise, found through the sound](#the-figure-of-the-exercise-found-through-the-sound)).

For your own files, **place the PDF booklet beside your audio files**. Nothing else is
needed, as for subtitles:

```
N5L.pdf
audio/N5_sample2018-2_3.mp3     <- gets the figure of section 2, item 3
audio/N5_sample2018-2_5.mp3     <- nothing: this item states its choices in words
```

The booklet is looked for beside the file, then in the folder above, and matched on the
**level** (`N5`), the only part of the name that the audio and the booklet write the same
way. Two booklets of the same level (`N4L.pdf` for listening, `N4V.pdf` for vocabulary) are
told apart by their content, not their name: the listening booklet has pages with drawings,
the other has none.

### How the exercise is found

There are two paths. A file that **is** one exercise is identified by its name; a whole
**section**, which holds six or seven exercises, by its sound.

| What is handled | Section | Rank of the item | Booklet |
|---|---|---|---|
| A folder of items cut one by one | the file name | the file name | laid beside |
| A past-paper section (`jlpt-nX`) | the track (`N5Q1.mp3`) | the 「3番」 announced in the sound | fetched |

**By the name.** Both spellings of the official samples are read (`N5_sample2018-2_3`,
`N5L_sample2018_m1b2`), and the three ways of writing the example are ignored (`_rey`, `m1r1`,
the rank `_0`): 「れい」 opens a section to show how it works, it is not an item.

A name that cannot be read gives no picture, and a file that is not a past paper is not
considered at all: `Genki_K01-03.mp3` or `3_0.mp3` is never read as an exam exercise.

**By the sound.** Only the 「ばん」 suffix makes an announced number the rank of an item. It
separates the three forms the same transcript contains: 「1番」 is item 1, 「問題1」 is the
whole section, and a bare 「2」 is the bell, which the transcript writes as a digit. A bare
number is therefore never read as a rank: no figure is better than a figure chosen on a
chime. The cases that give no figure are listed under
[The figure of the exercise, found through the sound](#the-figure-of-the-exercise-found-through-the-sound).

On the booklet side, three measurements are combined:

| What has to be known | Where it comes from | Cost |
|---|---|---|
| Where each section starts (もんだい1 to 4) | The text layer, where they extract without fault | free |
| Which pages carry drawings, and where | The objects of the PDF - the vector frames give the exact boundary | free |
| How many items each page carries | A reading through vision | **one call per booklet** |

The third cannot be avoided: the item numbers of the booklet are **drawn**, not written (the
text layer gives 「ばん」 without its digit), and the drawings cannot be grouped into items
without knowing how many items there are. The vision call is paid **once per booklet**: a
folder of twenty extracts from the same exam does not pay it twenty times, and the map is
kept in the cache (`booklets/`), found again by the booklet's content, so a later run on the
same exam does not pay it either.

### Scanned booklets (2012 collection)

The five listening booklets of the 2012 collection are **scanned**: each page is a single
picture covering 94 to 99% of it, and the text layer holds only the page number and the
header. The two free measurements of the table above find nothing there.

Kotogen reads the ink instead. The figures sit in **printed frames**, found by counting the
dark pixels row by row and column by column: a real frame line covers 0.64 to 0.70 of the
page, the lines inside the drawings (the roof of a bus, the side of a train) under 0.20. A
rectangle is kept only if its **four** edges are inked over at least 90% of their length,
which rules out the gutters between two frames.

The ink also shows where one item ends and the next begins, which the frames alone cannot
tell: the 「2ばん」 that opens an item is **printed in the margin**, level with the top of its
figures, while the strip between the two rows of one 2x2 grid is blank. On N4L 2012, 8.4% of
that strip is inked between two items, 0.0% between the rows of a grid. The number only has
to be seen, not read.

Compared with a typeset booklet:

| | Typeset booklet (2018) | Scanned booklet (2012) |
|---|---|---|
| Pages sent through vision | the pages with drawings only | **the whole booklet** |
| Sections | the text layer, for free | the same reading through vision |
| How many items a page illustrates | the same reading through vision | the printed labels, for free |

A scan costs more. In exchange, the printed labels give a cross-check: the vision reading is
trusted only for the **item numbers**, and when its count does not match the labels, no
figure is set on that page. A page that shows the drawing of the 「れい」 example beside an
item gets no figure either, since nothing says which of the two blocks is the example.

The route is chosen by **measurement**, never by the year or the file name: a booklet in which
no page has its drawings as separate PDF objects is a scan.

The method has a limit: **what is not framed is not seen**. Every item figure of the booklets
measured is framed, but a diagram drawn straight on the page would be missed, and its card
would have no picture. The N2 and N1 of the 2012 collection give no figures because their
listening sections have none.

### What the figure contains, and does not contain

The crop follows the **frames** of the choices (objects of the PDF, or ink on a scan): the
four squares whole, without the exercise number printed above them (a landmark of the
booklet, not part of the question) and without the white margins of the page.

Two kinds of figure occur:

| Kind | Where | What the figure carries |
|---|---|---|
| **Drawn** choices | 課題理解 of the N5 | The four options, numbered 1 to 4 in the picture |
| Labelled **context** | the whole N4 | Objects marked ア/イ/ウ, the options being elsewhere |

The decoys, not the picture, decide whether the card shows written choices: a card with a
picture and decoys shows both. The generator writes no decoys on the card that carries the
figure, so that card shows the picture alone and is answered on the drawings.

Nothing is guessed at any step. An unreadable booklet, an item that cannot be found, a count
that does not match: the card is made **without a picture**, and the run says so. A card
whose figure shows another exercise would be worse: it would be reviewed without ever being
answered right, and nothing on it would say why.

## How many choices the card shows

Every card is generated with four choices, except the card that carries a figure and an item
with a choice of replies (see above). How many you see is set in the "Templates" menu
(`audio.choices`), and changing it needs no new generation: `four` by default, `two` (the
right one and a decoy drawn with the seed of the day), `none` (answered from memory), or
`alternate` (every other card, by its rank in the passage). The setting is a maximum: a card
with an empty `Decoy1` field is answered from memory in every position. Outside the two cases
above, a card without a decoy is a defect: the run says so, and the instruction to the model
is to ask another question instead. The details are in [Card templates](card-templates.md).

## Automatic splitting (`--no-split` to turn it off)

Many listening sources are **collections**: a JLPT listening sample chains six conversations
separated by a bell, an announced number, a scene-setting and a question; a shadowing book
lines up ten numbered exchanges. Kotogen cuts such a file into its passages and keeps **only
the conversation**: the announced number, the bell, the title, the instructions, the question
asked by the audio and its answer options are left out. The scene-setting before a past-paper
conversation (「男の人と女の人が話しています」) is kept: without it, the conversation has no
context. The exam question is left out even when it looks useful: the card asks its own, and
the audio's would tell you what to listen for.

Every file goes through the splitter, local or downloaded (a podcast episode, a video, a
いろどり dialogue, a past-paper section, a 青空朗読 reading); an NHK Easy article never does.
`--no-split` turns it off: each file then goes in one piece.

On a 課題理解 item, not even a pause separates the scene-setting, the question and the
conversation. The exam question is recognised because the exam says it **twice**, before
the conversation and after it: a line at the edge of the passage that ends as a question (in
「か」) and is said again on the other side is removed, and the remaining sound is joined. A
line that opens with the item's number (「4番 眠いのでちょっと休んでもいいですか」) is never
removed, since it opens the passage: this keeps the prompts of the 即時応答 and the
「何と言いますか」 of the 発話表現, which are said only once.

Whisper often writes the item's number and its first line as one line
(「1番 大学で男の人と女の人が話しています」, or 「例 駅で…」 for the example), and the model,
told to leave the number out, may leave out the whole line. The splitter puts such a line back
at the head of its passage, without the number, and does the same for a scene-setting whose
number was said alone on the line before (「6番」, then 「ラジオで女の人が…」). The exam question
between them stays out. The AI that writes the card gets the line as heard, without the
number: given 「1番 大学で…」, it would take the whole line for an announcement and drop it.

A past paper gives the candidate about twenty seconds to read the options, and Whisper rarely
leaves that silence empty: it repeats what it last heard, or writes anything (「はい」 six
times, a line of Korean). A line whose every word falls inside a silence of three seconds or
more is treated as unsaid and removed, along with the same line repeated next to it and the
bell that ends the silence. On a collection, a silence that long between two consecutive lines
is cut out the same way. Three seconds is well above the pauses of a conversation, or of the
replies of a 発話表現.

That bell takes three forms in the transcript: a line of its own, written as the number
Whisper last heard (「4番」), removed with the silence it touches; a line written in the short
gap between the bell and the voice, removed as unsaid; or the first word of the conversation
stretched over the bell (「佐藤さん」), in which case the passage starts where the silence after
the bell ends.

### How any file is split cleanly

What is not speech (bell, chime, jingle, music, pause) **does not appear in the transcript**,
and the audio produced contains only stretches that were transcribed and kept. Everything else
is excluded with no rule written for it, so a source that separates its conversations
differently (letters, a plain pause, a gong) works the same way.

Three sources of information are used, in this order:

1. Whisper's **word timestamps**. Segment bounds would not be enough: Whisper often puts the
   number and the first line in the same segment (`4 あっそれ`), and only the timestamp of the
   word lets the number be left out;
2. the **real silences** of the signal (`ffmpeg silencedetect`), which say where to cut,
   **and a floor** that keeps the cut from going back over what was left out. Both are
   needed: when the pause after a number is too short to be measured (0.2 s), the nearest
   silence is the one **before** the number. The floor is the end of the previous line, or of
   the last word that ends before the speech starts. Without `ffmpeg`, a fixed margin is used
   instead: less clean, but it works;
3. **one AI call per file**, the only way to read `に` and `さん` as the numbers 2 and 3, to
   recognise 「では、始めます」 as an instruction, or to judge that a passage stands on its own.
   An answer that cannot be read is asked for again, up to three attempts in all.

A short file (under 45 s or under four lines) cannot be a collection, so the call is not made,
but **the announced number is still removed**: finding it costs nothing. This is the case of
いろどり, which publishes one dialogue per track, twenty to forty seconds long, with its number
announced at the start. The run then shows "whole file, minus its announcement". With
`--no-split`, the file goes as it is, number included.

When all three attempts of the splitting call fail, the file is dropped, and the run says so.
It is not handled in one piece: a whole collection would give one card for ten
conversations. An NHK Easy article is never split: it is one continuous reading.

### A continuous stream (podcast, interview) is not a collection

A collection has boundaries, which the splitter finds. A continuous stream has none, only
changes of topic, and an extract from the middle keeps referring to what came before (a
`これ`, a `さっきの話`, a pronoun with no referent). The criterion is therefore much stricter:
only **self-contained** passages are kept, and it is normal to keep only a handful out of
forty minutes, or none.

On a stream, a kept passage is **a window, not a chapter**. A podcast topic lasts two or three
minutes, far more than a card can hold; instead of dropping it, the splitter looks for a
window inside it, which opens on a sentence that sets its own topic and closes at the end of
an idea. The rest of the topic is set aside on either side. On a collection, cutting inside a
conversation is not allowed: its boundaries are those of the exercise.

Three limits apply to a stream, all to control cost:

- the **passage cap** is 4, against 12 for a collection: a stream has only changes of topic,
  nothing limits what a generous model might propose, and each kept passage costs a
  generation call. The cap is **told to the model**, since cutting the excess would keep the
  first four passages in audio order, and the start of a podcast is often its weakest part;
- the **target length** (20 to 90 s) is given before the split. Without it, the model proposes
  passages sized for a collection, three minutes long, which are set aside after the splitting
  call is paid for. A collection has no target: a conversation lasts what it lasts;
- `--max-duration` **lowers the top of that window** rather than being added to it:
  `--max-duration 60` aims at 20 to 60 s. A passage that is still too long is set aside **when
  the answer is read, before the cap**, so that it does not take the place of a shorter one
  further into the episode. Below 50 s, the bottom of the window comes down too, to 40% of the
  limit (`--max-duration 20` aims at 8 to 20 s): a short limit must give short passages, not
  fewer.

### A fiction is neither a collection nor a stream

An episode of a series has boundaries (its scenes), like a collection, and a plot running
through them, like a stream. It gets a criterion and a cap of its own.

The splitter keeps what can be **understood**, not only what stands entirely alone: a
listening card asks what was SAID, not what the story is about, and two characters arguing
over the last cake make a good passage even if you do not know who they are. Far less is set
aside than on a stream: a line that answers something said three scenes earlier, news whose
weight depends on an episode you have not seen.

The **cap is 8**, between the 4 of a stream and the 12 of a collection: the scenes bound the
passages, but a dozen generation calls for one episode would be too many.

The **trappings of a series** are always set aside, and named as such on screen: the opening
and closing theme songs, the recap of the previous episode (前回のあらすじ), the preview of the
next one (次回予告), the eyecatch.

**Length** is handled as on a stream: a scene runs longer than the target length, so a window
is taken inside it.

### What is displayed

The run shows durations and reasons, **never a line of Japanese**: the card is there to make
you discover the content by listening.

```
[3/5] nihongo-learning_Sample_video_title_XXXXXXXXXXX.mp4
   Extracting the sound track… (the picture is kept)
   Reading the subtitle… (55 utterances)
   Splitting… (3 passages, 6 refusals: 2 off topic, 2 not standalone, 1 too long, 1 transition)
   Generating the cards (passage 1/3, 01:19 → 01:57)… (2 cards)
```

One action per line, with its result in brackets at the end, as everywhere in the program (see
[The screen while working](interactive.md#the-screen-while-working)). The extraction line
says what was kept of the file: **`the picture is kept`** when the cards will carry it,
**`the picture is left aside`** when it is dropped (see
[Keeping the picture](#keeping-the-picture---video)). An audio file has no such line.

The split is summed up in one line, since a list per passage would fill the screen on a
shadowing book where everything is refused; the bounds of each kept passage are shown when
its cards are generated.

Each kept passage gives an MP3 beside the TSV (`jlpt_n3_choukai_02_3f9ac1d2.mp3`), which then
goes with the cards like any audio. A passage that gives no card has its extract deleted; the
original file is never modified.

### Refusing a passage with no material

An exchange of two short lines holds no comprehension question. A passage with fewer than 16
Japanese characters is set aside **without an AI call**: it costs nothing, and on a shadowing
book of ten exchanges (about 11 characters each) it saves ten calls that would give no card.
Above that threshold, the model can still return no card.

### What the questions cannot say

The front of a listening card shows only the question and the audio: the transcript, with its
`A：` / `B：` labels, is on the **back**. A question like "What does A do on coming home from
work?" asks you to identify someone whose name you have never heard.

The speakers are therefore named only by what the ear can recognise: a first name actually
spoken, a role clear from the content (the shop assistant, the customer), or an action already
mentioned in the question. When nothing tells them apart, the question is about the content of
the exchange, not about who said what. A card that names a speaker by its label is dropped
before it reaches the deck, and the run gives the reason.

### The transcript on the back, turn by turn

The back shows the transcript line by line, with the translation under each line (hidden until
the 訳 button is on). The grouping depends on the audio:

- **Dialogue**: one turn, one translation. Several sentences in a row from one speaker are
  shown one under the other under a single label, followed by the translation of the whole
  turn. A translation after every sentence would break up the exchange.
- **NHK article, monologue, narration, announcement**: sentence by sentence, each with its
  translation.

The translation is paired with the transcript line by line, by rank. One whose line count
does not match the transcript is dropped, as on the reading card: shifted by one line, every
sentence would show the translation of another. The run says so, and the cards are marked
for proofreading (`Check::Translation`, see
[Cards to proofread](global-options.md#cards-to-proofread)).

A turn is grouped up to about **100 characters**; past that, its next sentences start a new
group, with a translation of its own. A 概要理解 item has eight to fifteen sentences from a
single speaker, and grouping them all would give a block of Japanese followed by a block of
translation, where the eye cannot find the sentence it has just read.

In a dialogue, the speaker labels sit in a column on the left (the first speaker's label
stands out), every sentence starts at the same left edge, and a thin line separates two turns.

The grouping is done by the card template at display time; the transcript the AI writes stays
one sentence per line. The key line (the one the question is about, marked by a green bar on
its left) therefore marks a single sentence, even inside a grouped turn.

### Clicking a sentence to hear it there

**Clicking a sentence plays the audio from that sentence.** The bar of the card's player has a
tick where each sentence starts, the key line's in green, and clicking a tick does what
clicking its sentence does. The sentence being heard is highlighted in the transcript,
whatever started the playback. A click that ends a text selection does nothing, since you
often select a sentence to read it again.

Playback **stops at the end of the clicked sentence**, so a hard sentence can be heard again on
its own. To let playback go on, set `audio.click=continue` (the "Templates" menu, see
[Card templates](card-templates.md)); the player's own button plays the whole recording either
way. The end of a sentence is **the start of the next one**, as the transcript records only
starts, so the setting needs no regeneration and applies to the cards already in the deck.
Playback stops within a frame of the next start. A sentence that generation could not place
has no bound of its own: it is heard as part of the sentence before it.

The click targets **the sentence**, never the whole turn: every sentence keeps its own start,
inside a grouped turn too, and hovering highlights only the sentence under the pointer.

The start of each line is stored in a `Timecodes` field, matched to the line by **rank**, as
the translation is. It is never shown.

Where the starts come from:

| Source | Precision |
|---|---|
| Local file, podcast episode | To the word: Whisper timestamps every **word** |
| File with a subtitle | To the line: it is the bound of the subtitle, set by hand |
| NHK Easy article | To the sentence: the sound is transcribed separately, to place the text of the site |

The model rewrites the transcript: it joins a sentence cut in two, splits two run together,
corrects a misheard word, adds the labels and the furigana. Its lines therefore do not match
the original ones by rank, and each line is found again **by its text**, the search moving
forward through the lines: 「はい」 can come back ten times in a dialogue, and each must get its
own start.

Each line is placed in up to three steps, of decreasing precision. A line the first step
misses still gets a start: it was heard and timestamped, only the matching failed.

| Step | Comparison | Precision |
|---|---|---|
| 1 | the spelling, as it is | to the word |
| 2 | the reading, in kana | to the line |
| 3 | pro rata, between the lines placed | bounded by the interval |

Step 2 catches what the model rewrote: it writes 「豚カツ」 where the sound has 「とんかつ」,
and neither spelling contains the other, but their readings are the same. Step 3 spreads the
remaining lines over the time available, in proportion to the length of their text: read
Japanese has a roughly constant pace, so a line between two neighbours three seconds apart
lands less than three seconds from its start.

Both recovery steps are **bounded**: a recovered start must fall strictly between its
neighbours already placed, or it is discarded. This stops step 2, which is coarser, from giving
the same start to four lines in a row.

An **opening line** that is not recognised takes the start of the first word of the passage,
not its zero, so that a passage opening on two seconds of theme music does not replay the
music before the sentence.

When **no** line is recognised, the field stays empty: there is nothing to spread between. The
run says how many lines were spread pro rata, which the field cannot show.

A `-` in place of a start, if a card has one, leaves its line displayed like the others, but
not clickable.

On an NHK article, the matching cannot use the spelling: the site writes 「このあとも」 where
Whisper hears 「この後も」, and neither contains the other. It therefore uses the **reading** in
kana: the text of the site comes with its furigana, and the analyser gives the reading of what
Whisper wrote.

### The audio must say what the text says (NHK articles)

The text of an NHK card is **copied from the site**, with its furigana, which is always better
than what Whisper would hear. But it is not always what the voice file reads:

- the **sound stops before the end of the article**: the voice file is made at publication,
  and the article is corrected afterwards;
- the page has paragraphs that **are never read**, such as the label of a cross-reference
  banner (「地震で気をつけること」) picked up with the sentences of the article.

A card could then ask about a sentence nobody hears. The audio is therefore **transcribed**
before the AI call, and each sentence of the text is looked for in it. What the sound does not
say at the end of the text does not go to the AI, and the run says so:

```
   ! 1 line at the end of the article removed: the audio stops before.
```

This transcription goes into no card: it only places a text already known. It therefore
always uses the `small` model, whatever `--whisper-model` says: it takes seconds, where
`medium` would add a 1.4 GB download and take several times longer.

Two safeguards apply, because a sentence the matching misses may still be in the sound:

- **nothing is removed from the middle of the text.** A single sentence that is not found is
  nearly always a misheard word (「頭」 heard as 「穴」): it stays, with a start spread pro rata;
- **nothing is removed while the sound still has speech left.** If the unmatched end of the
  sound is at least half as long as the sentences about to be removed, the matching failed
  rather than the sound: the analyser reads a word differently from the site (「明日」 read
  あす on one side, written あした on the other). The text then stays whole.

When **no** sentence of the text is found in the sound, the audio does not belong to this
text. The article is set aside with no card and no AI call, and it is not recorded as handled:
another run will try it again.

Whisper is not installed by `kotogen[nhk]`. Without it, this check does not happen and the run
says so; the article is made from the whole text, and its lines are not clickable.

### Where the audio comes from (the `Source` field)

Every card records where it comes from, in small print at the bottom of the **back**:

| Source | What the card keeps |
|---|---|
| NHK Easy article | Its address, whole - the card makes a link of it |
| Podcast episode | The feed and the title of the episode (`Nihongo con Teppei - #123 ...`) |
| YouTube video | The channel and the title, **followed by the address of the passage**: `Onomappu - Sample video title (03:12 → 04:50) https://youtu.be/XXXXXXXXXXX?t=192` |
| Local file | Its name (`jlpt_n3_choukai.mp3`) |
| Extract of a split collection | The name **and the bounds**: `jlpt_n3_choukai.mp3 (03:12 → 04:50)` |

The bounds tell apart the extracts of one collection, which would otherwise all show the same
name. A podcast episode is named by its feed and title, not by its file, which has a cache name
and will be deleted.

When the field ends with an address, the card shows the label as a link. A YouTube address
points to the extract: its `?t=` opens the video at the second where the extract starts. A
いろどり card links to the page of its lesson, and a 青空朗読 card to the page of its reading.
An NHK article has only its address, shown shortened as the link. A podcast episode or a
past-paper section has no link: its address would only download the sound the card already
plays.

The source is on the back only: on the front, the title of an article would give away part of
what you are asked to hear.

## How many questions? (`--count`)

`--count` is a **cap**, never a quota: the AI stops when the audio no longer supports a
question on a different point. A thirty-second extract may give only one card, which is the
expected result: a quota would force it to invent more, paraphrases or guesses.

Without `--count` (the default, `auto`), the cap is computed from the length of the
transcript: one question per 30 Japanese characters or so, never fewer than 4 nor more than 24.
An NHK Easy article (180 to 240 characters) gets 6 to 8, a JLPT listening extract 4 to 12
depending on its length.

These caps are deliberately **above** what a source usually supports, or they would act as a
quota: they only catch a runaway answer, and the model, which has the content, decides the
rest. The computation is local and free, and it bounds the cost: without a cap, a long
bulletin could return thirty cards.

```bash
kotogen audio K23_01.mp3              # auto: the content decides
kotogen audio K23_01.mp3 --count 2    # at most 2, fewer if the audio is thin
```

## Maximum duration (`--max-duration`)

In seconds (`180` or `180s`). Without it, nothing is filtered: it is a choice, not a rule.

For an NHK article, the length is measured (`ffprobe`) **before** the AI call, and before the
download when the site serves a stream, so an article that is too long costs no tokens. It is
not recorded as handled either: a later run without a limit, or with a wider one, will take
it. The limit sets articles aside without taking others in their place:
`--latest 4 --max-duration 180` may give cards for only 2 articles, and the run says so. If
`ffprobe` is missing, the length is not checked, and the run says so.

For a 青空朗読 reading, the limit first applies to the whole reading, before the download, as
the catalogue gives its length. On every source but NHK, it applies to **each passage** the
splitter returns, not to the whole file: it is the length of what the card will play. A file
passed with `--no-split` has one passage, the file itself.

The limit is also **given to the splitter**, which then aims below it instead of proposing
passages that would be thrown away after the splitting call is paid for. Nothing is ever
truncated: a card cut in the middle of a sentence would be a wrong card.

## Pipeline

**Whisper** transcribes the audio once for the whole file, with the timestamp of every word.
A subtitle beside the file, if there is one, is used instead; an NHK article is captured with
its official audio, which is then transcribed to check that the sound says the text of the
site; a podcast episode is first downloaded from its RSS feed. The file is then **split** into
passages. Then the **AI** generates, for each passage: the questions **in the language of the
cards** with their four choices (shuffled on display; how many of them the card shows is the
`audio.choices` setting, see above), the Japanese transcript with furigana (the key line of
each card being given by its `KeyLine` field), and its translation.

## Whisper model (`--whisper-model`)

`medium` by default, not `small`. Whisper's mistakes end up in the cards: `small` often writes
`自信` for 地震, `結構` for 欠航, `集活` for 就活, and such cards are only noticed while
reviewing. Transcription happens **once per file** and costs computing time but **no
tokens**: it is the best quality lever available, and a free one.

The model is downloaded once, on first use (about 1.4 GB for `medium`). The download shows **at
the end of the waiting line**, where the progress of the transcription then appears:

```
   Transcribing… ⠹ model to download once only, 667.6 MB of 1.4 GB
```

This setting applies only to what becomes card text. The transcription of an NHK article,
which only places a text already written, always uses `small` (see
[The audio must say what the text says](#the-audio-must-say-what-the-text-says-nhk-articles)).

Later runs find the model on disk and download nothing. If the machine cannot load the model,
the program falls back on `small` **and says so**, since the transcript is less faithful. On a
slow machine, or for a first rough pass, `--whisper-model small` remains available.

### The wait, and the loops Whisper locks itself into

`medium` on a CPU transcribes at about real time: a nine-minute past-paper section takes nine
minutes. The waiting line therefore shows **how far the transcription has got** in the audio:

```
   Transcribing… ⠹ 03:30 of 09:12
```

That counter is also a safeguard. When a thirty-second window does not end on a complete line,
Whisper moves its cursor back to the last timestamp it emitted, which is sometimes `0.00`: the
cursor stops moving, and the transcription loops forever on the same thirty seconds. It is a
known Whisper defect, not a problem with the file.

After three windows decoded without progress, the transcription starts again **without the
context** Whisper carries from one window to the next, which is what causes the loop. The retry
is announced, since it costs the same time again:

```
   ! Whisper is going round in circles: retrying without context
```

If it loops again, the file is set aside and the following files are handled.

## Audio compression (`--audio-quality`)

**Nothing is compressed by default.** The audio of an NHK Easy article is copied as it is,
without re-encoding, into the container that takes its stream: an `.m4a` for AAC, an `.mp3`
for MP3.

The site already serves a compressed stream (AAC, around 64k): re-encoding it at a lower rate
adds a second loss to the first, on the very thing the card trains, to save a little on an
article of a few hundred kilobytes. The three other notches are there if you want smaller
files:

| Notch | What is written |
|---|---|
| `none` (default) | the original stream, copied without re-encoding |
| `light` | mono 96k MP3 |
| `medium` | mono 64k MP3 |
| `strong` | mono 48k MP3 |

These codes are the values of `--audio-quality` and `KOTOGEN_AUDIO_QUALITY`. A notch targets a
**bitrate** and knows nothing of the source: asking 96k of a 64k stream restores nothing and
makes a bigger file. The bitrate of the source is therefore the useful ceiling, and below it
the right notch is `none`.

```bash
kotogen audio nhk                          # no re-encoding
kotogen audio nhk --audio-quality strong   # the lightest files
```

In interactive mode, each press on the `q` key of the settings moves to the next notch, back to
the first after the last. The notch is saved for later runs (`KOTOGEN_AUDIO_QUALITY` in the
[settings](global-options.md#where-the-settings-live)); `--audio-quality` overrides it for one
run.

One exception: **cutting a passage requires re-encoding**. A stream copy can only cut at frame
boundaries, which moves the cut by tens of milliseconds, enough to clip a mora or let a bell in
(see [Automatic splitting](#automatic-splitting---no-split-to-turn-it-off)). For an extracted
passage, `none` therefore means a 192k MP3, whose loss cannot be heard, not "no encoding at
all". An audio file handled **whole** is never re-encoded, whatever the notch: it is copied
under a new name.

## Audio files

The `Audio` field of the card holds the full tag that plays the file:
`<audio controls src="K23_01_3f9ac1d2.mp3"></audio>`. The name is **Kotogen's**, never that of
the original file: a readable part followed by an eight-character fingerprint of the content.

The tag is in the field, not in the template, because Anki finds the media a note uses only in
its **fields**, and there only as `[sound:...]` or as an `img`, `audio` or `video` tag. A file
that no field names is reported as unused by *Tools > Check Media*, which offers to delete it,
and is left out when the deck is exported as `.apkg`. The template handles everything else:
the frame, the classes, the CSS, and whether the sound or the video plays.

The `Video` and `Image` fields follow the same rule, as does the `Images` field of the
mini-book of the [Reading](reading.md) card.

The fingerprint is needed because Anki keeps the media of every deck in a single
`collection.media` folder, with no namespace: a past paper's `01.mp3` would replace the
`01.mp3` of a textbook added months earlier, and the older cards would play the wrong sound.
The fingerprint comes from the content, not from chance: regenerating the same extract gives
the same name, so the media library does not gain a copy at every run. A file handled whole is
copied beside the TSV under that name (the sound is not re-encoded); the original keeps its
name and its place.

The audio files follow the cards, with no option to pass:

- **with `--send`** (or auto-send), the cards go into Anki, and the files into its media
  library, or those cards would be silent. With Anki open, the files go through AnkiConnect
  (`storeMediaFile`), the only safe route: writing into `collection.media` while Anki runs
  desynchronises its media database. With Anki closed, they are copied straight into the media
  folder (`KOTOGEN_MEDIA_DIR` if set, otherwise the profile whose collection was modified
  last, under `%APPDATA%\Anki2\` on Windows, `~/Library/Application Support/Anki2/` on
  macOS or `~/.local/share/Anki2/` on Linux, where the `net.ankiweb.Anki` Flatpak is looked
  for too), and Anki picks them up at its next start;
- **without sending**, the cards stay in the TSV and the audio files beside it (NHK audio files
  are downloaded into the folder of the TSV); the program lists them, to be copied into
  `collection.media` when you import. Nothing goes into Anki unless you ask.

If the media folder cannot be found, the program lists the files left to copy by hand, and
`KOTOGEN_MEDIA_DIR` sets the path in the [settings](global-options.md#where-the-settings-live).

---

[Documentation index](../README.md#documentation)
