#!/usr/bin/env python3
"""Anki card generator CLI for Japanese learning."""

import argparse
import sys
from pathlib import Path

from kotogen import (
    __version__,
    audio_quality,
    console,
    jlpt,
    memory,
    proofreading,
    settings,
    system,
    video_clip,
)
from kotogen.i18n import _, quoted as _quoted

# The package alone, not its modules: `maintenance.review` pulls the AI client
# in, and the parser is built at every launch, maintenance or not.
from kotogen.maintenance import DEFAULT_TAG, IVL_MATURE, TASKS as REWORK_TASKS

# Provider and model used without --provider / --model, which the model screen of
# the interactive menu writes together (KOTOGEN_PROVIDER, KOTOGEN_MODEL); the
# command-line options take precedence. No model is built in: models come and go
# faster than releases, so the user picks one among those the provider serves.
FALLBACK_PROVIDER = str(settings.default("KOTOGEN_PROVIDER"))
PROVIDERS = ("anthropic", "openai", "openrouter")


def default_provider() -> str:
    """Provider called without --provider: KOTOGEN_PROVIDER, else OpenRouter.

    An unknown name is ignored, so a mistyped setting does not stop a run."""
    provider = settings.text("KOTOGEN_PROVIDER").lower()
    return provider if provider in PROVIDERS else FALLBACK_PROVIDER


def chosen_model(provider: str | None = None) -> str:
    """The model chosen for this provider (KOTOGEN_MODEL), "" when there is none.

    KOTOGEN_MODEL only holds for the provider chosen with it, since a model name
    belongs to its provider: another `--provider` needs its own `--model`."""
    provider = provider or default_provider()
    return settings.text("KOTOGEN_MODEL") if provider == default_provider() else ""


# What a generator writes its cards as: the TSV Anki imports (the default), or
# JSON Lines for any other tool.
FORMATS = ("tsv", "json")

# What `--level` accepts: a JLPT level, or "auto" - every level, or the one
# the AI judges, depending on the command.
LEVEL_CHOICES = ("auto", *jlpt.LEVELS)


def output_format() -> str:
    """Format written without --format: KOTOGEN_FORMAT, else the TSV.

    An unknown value gives the TSV rather than an error, like every setting here."""
    value = settings.text("KOTOGEN_FORMAT").lower()
    return value if value in FORMATS else FORMATS[0]


def seconds(value: str) -> int:
    """A duration in seconds given on the command line: "180", or "180s"."""
    try:
        parsed = int(value.strip().rstrip("sS"))
    except ValueError:
        raise argparse.ArgumentTypeError(
            _("duration in seconds expected, got {value}").format(value=_quoted(value))) from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError(
            _("the duration must be strictly positive"))
    return parsed


def card_count(value: str) -> int | None:
    """Cap on cards: "auto" (the content decides) or a positive integer.

    None = auto: the generator works the cap out from the length of what it
    sends to the model (see `generators/quota.py`). A maximum, never a target.
    """
    text = value.strip().lower()
    if text == "auto":
        return None
    try:
        parsed = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(_(
            "a number of cards or {auto} expected, got {value}")
            .format(auto=_quoted("auto"), value=_quoted(value))) from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError(_(
            "the number of cards must be strictly positive ({auto} to let the "
            "content decide)").format(auto=_quoted("auto")))
    return parsed


def build_parser() -> argparse.ArgumentParser:
    # Options shared by several subcommands, carried by "parent" parsers so that
    # they are written after the subcommand (kotogen vocab "word" --send).
    ai_opts = argparse.ArgumentParser(add_help=False)
    ai_opts.add_argument(
        "--provider",
        default=default_provider(),
        choices=list(PROVIDERS),
        help="AI provider (default: openrouter, or KOTOGEN_PROVIDER in the settings file)",
    )
    ai_opts.add_argument(
        "--model",
        default=None,
        help=(
            "Model name, as the provider names it (default: KOTOGEN_MODEL in the settings "
            "file, when the provider is the one chosen with it). No model is built in: the "
            "'m' setting of the interactive menu lists the models each provider serves today"
        ),
    )
    out_opts = argparse.ArgumentParser(add_help=False)
    # default=None: with neither --send nor --no-send, KOTOGEN_AUTO_SEND decides
    # (resolved in _run).
    send_opts = out_opts.add_mutually_exclusive_group()
    send_opts.add_argument(
        "--send",
        action="store_true",
        default=None,
        help="Also send cards to Anki via AnkiConnect (requires Anki open with AnkiConnect addon)",
    )
    send_opts.add_argument(
        "--no-send",
        action="store_false",
        dest="send",
        help="Never send to Anki, even if KOTOGEN_AUTO_SEND is set (TSV only)",
    )
    out_opts.add_argument(
        "--output",
        "-o",
        default=None,
        metavar="FILE",
        help=(
            "Output file path (default: a dated name in the cache for a run that sends "
            "to Anki, else in KOTOGEN_OUTPUT_DIR, else in the current directory). "
            "A name ending in .jsonl is written as JSON Lines, any other as TSV"
        ),
    )
    out_opts.add_argument(
        "--format",
        choices=list(FORMATS),
        default=None,
        help=(
            "What the cards are written as: 'tsv' (the default) is the file Anki "
            "imports, 'json' is JSON Lines - a header line, then one card per line "
            "with its identity, its fields and its tags - for any other tool. "
            "JSON is not for Anki, so it cannot be combined with --send. "
            "Without this option KOTOGEN_FORMAT applies"
        ),
    )
    out_opts.add_argument(
        "--proofread",
        dest="proofread",
        choices=list(proofreading.modes()),
        default=None,
        help=(
            "Cards the model returned damaged - the ones the run flags with a "
            "'!!' line (translation not aligned with the text, transcript "
            "missing, right answer repeated among the decoys). 'keep' exports "
            "them as they are, 'tag' exports them tagged "
            f"'{proofreading.TAG_PREFIX}...' so Anki can find them again, 'drop' keeps "
            "them out of the file and out of the deck, 'ask' (the default) "
            "asks once, just before sending. Overrides "
            f"{proofreading.ENV_VAR} for this run only."
        ),
    )
    # Not `yes` like the `--yes` of maintain, ask, deck and backup, which accept
    # what they would confirm: this one answers as outside a terminal (see
    # `exporter.unattended`).
    out_opts.add_argument(
        "--yes",
        "-y",
        dest="unattended",
        action="store_true",
        help=(
            "Ask nothing: every question of the run takes the answer it takes "
            "outside a terminal - the cards to proofread tagged, a video kept as "
            "its sound track, a lone kanji turned down, the words of an "
            "expression generated. --proofread and --video still settle their "
            "own question"
        ),
    )
    parser = argparse.ArgumentParser(
        prog="kotogen",
        description="Generate Anki cards for Japanese learning using AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  kotogen                      (no argument: guided interactive mode)
  kotogen kanji 学                        (one kanji card)
  kotogen kanji 学生                      (a card for each kanji of a word: 学 and 生)
  kotogen kanji deck                      (the kanji of your vocabulary that have no card yet)
  kotogen kanji jlpt --level N4 --count 30
  kotogen kanji https://ja.wikipedia.org/wiki/寿司   (the kanji of a page)
  kotogen vocab "涼しい cool temperature"
  kotogen vocab --file words.md
  kotogen vocab "食べる" --provider openrouter --model publisher/model   (another model, this run only)
  kotogen vocab --file words.md --batch-size 20   (fewer API calls: 20 words per request)
  kotogen vocab N4V.pdf --jobs 1         (one batch at a time instead of 4 in parallel)
  kotogen vocab N4V.pdf --send -y        (no question on the way: each takes its answer for a script)
  kotogen vocab jlpt --level N4          (the N4 words your deck is still missing)
  kotogen vocab jlpt --level N3 --count 50
  kotogen vocab --theme "job interview"  (the words of a theme your deck is still missing)
  kotogen vocab https://ja.wikipedia.org/wiki/寿司     (any page, not just NHK)
  kotogen vocab subtitles.srt            (any local text file)
  kotogen reading chapter.txt --count 4   (at most 4 questions; fewer if the text is short)
  kotogen vocab https://news.web.nhk/news/easy/ne2024XXXX/ne2024XXXX.html --count 8 --level N4
  kotogen vocab N4V.pdf                  (every useful word mined from a PDF document)
  kotogen vocab course.pdf --count 50 --level N4
  kotogen grammar "〜てください" --count 5
  kotogen grammar jlpt --level N4        (the N4 rules your deck is still missing)
  kotogen grammar --url https://…      (the rule this page documents)
  kotogen grammar --file rules.md        (one rule per line)
  kotogen grammar "のに" "〜たら" "〜ながら"   (several rules in one go)
  kotogen grammar jlpt --level N3 --rules 5 --count 3
  kotogen reading manual.pdf --send      (reading texts mined from a PDF document)
  kotogen grammar "〜ながら" --count 3 --send
  kotogen grammar "のに" --count 4 --url https://…
  kotogen audio K23_01.mp3               (as many questions as the audio supports)
  kotogen audio K23_01.mp3 --count 5     (at most 5, and fewer for a short clip)
  kotogen audio jlpt_n3_choukai.mp3      (a collection: one card set per conversation)
  kotogen audio K23_01.mp3 --no-split    (one file, one card set, whatever it holds)
  kotogen audio ./my_audio --level N4 --send
  kotogen audio episode.mkv               (a video: its sound track, the card stays an audio one)
  kotogen audio episode.mkv --video       (and this time the card keeps the picture)
  kotogen audio nhk
  kotogen audio nhk --latest 6 --send
  kotogen audio nhk --max-duration 180    (articles whose audio exceeds 3 min are skipped)
  kotogen audio https://news.web.nhk/news/easy/ne2024XXXX/ne2024XXXX.html --count 3
  kotogen audio https://news.web.nhk/news/easy/ne2024XXXX/ne2024XXXX.html --count 4 --send
  kotogen audio teppei                    (latest episode of a podcast, cut into its self-contained passages)
  kotogen audio teppei-original --episode 42          (episode no. 42 instead of the latest)
  kotogen audio teppei-original --episode 42 --latest 3   (episodes 42, 43 and 44)
  kotogen audio teppei --max-duration 90  (and no passage longer than 90 s)
  kotogen audio sakura-tips --latest 2 --send   (aliases are graded: sakura-tips is N5-N4, haru is N2-N1)
  kotogen audio https://a-podcast.example/rss   (any RSS feed, no alias needed)
  kotogen audio onomappu                  (latest video of a YouTube channel, sound track only)
  kotogen audio nij --video               (and this time the card keeps the picture)
  kotogen audio tekuteku --latest 3       (its 3 latest videos; Shorts are skipped, they are not listening material)
  kotogen audio speak-naturally --max-video 900   (skip videos over 15 min, before downloading them)
  kotogen audio onomappu --max-video 900 --max-duration 90   (short videos, and short passages inside them)
  kotogen audio https://www.youtube.com/watch?v=XXXXXXXXXXX      (a single video, no alias needed)
  kotogen audio https://www.youtube.com/@a-channel               (a channel, or .../channel/UC..., or a playlist URL)
  kotogen reading nhk
  kotogen reading deck                                  (a short text written on the words your deck is learning)
  kotogen reading deck --shape exam --length medium --texts 2   (two 中文 texts shaped like the JLPT)
  kotogen reading https://news.web.nhk/news/easy/ne2024XXXX/ne2024XXXX.html --count 4 --send
  kotogen reading tadoku.pdf                            (illustrated pages: read as a mini-book, no flag needed)
  kotogen reading https://tadoku.org/japanese/book/6346/ (free Tadoku book: PDF downloaded, always a mini-book)
  kotogen reading past-paper.pdf --pages 12              (a single page: one JLPT reading exercise)
  kotogen reading ./book_pages --count 8                 (a folder of page images, same mini-book)
  kotogen maintain --scan
  kotogen maintain --only red blue leech
  kotogen maintain --only leech --yes
  kotogen maintain --type grammar audio   (only those note types; default: all in use)
  kotogen maintain --yes red green        (auto on red/green, the rest validated by hand)
  kotogen ask "which cards have an example without a translation?" --scan
  kotogen rework cards.jsonl --task simplify --output proposals.jsonl
                                          (what the AI proposes for each card of a file; nothing is changed)
  kotogen ask "take the N4 tag off the cards whose interval is over 60 days"
  kotogen deck install                    (create/update the note types from templates/)
  kotogen deck install --check            (say what differs, change nothing)
  kotogen backup                          (snapshot the Japanese decks right now)
  kotogen backup --list
  kotogen backup --diff                   (what changed since the last snapshot)
  kotogen backup --restore 2026-08-17_143012
  kotogen backup --full                   (plus one .apkg per deck, media included)
  kotogen update                          (take the sources, then renew the modules)
  kotogen update --check                  (say what is waiting, change nothing)

Decks and note types are hardcoded defaults, overridable in the settings file:
  KOTOGEN_VOCAB_DECK / KOTOGEN_VOCAB_NOTETYPE       (Japanese::Vocabulary / Vocabulary)
  KOTOGEN_GRAMMAR_DECK / KOTOGEN_GRAMMAR_NOTETYPE   (Japanese::Grammar / Grammar)
  KOTOGEN_AUDIO_DECK / KOTOGEN_AUDIO_NOTETYPE       (Japanese::Listening / Listening)
  KOTOGEN_READING_DECK / KOTOGEN_READING_NOTETYPE   (Japanese::Reading / Reading)
  KOTOGEN_KANJI_DECK / KOTOGEN_KANJI_NOTETYPE       (Japanese::Kanji / Kanji)

What this profile actually installs (the repo keeps every model regardless):
  KOTOGEN_VOCAB_CARDS    the card templates of that note type you want, comma
                          separated (e.g. "Recognition"); unset means all of them
  KOTOGEN_SKIP           commands you never use (e.g. grammar,audio): hidden from
                          the menu, skipped by `deck install` without --only

Other settings (see docs/global-options.md for where they live):
  KOTOGEN_AUTO_SEND=1    send every card straight to Anki (no question, TSV kept
                          as a backup in the cache dir); --no-send overrides it
  KOTOGEN_FORMAT=json    write the cards as JSON Lines instead of a TSV, for a
                          tool other than Anki (nothing is sent); --format
                          overrides it
  KOTOGEN_MEDIA_DIR      collection.media path, only if auto-detection fails
  KOTOGEN_ANKICONNECT_URL  and  KOTOGEN_ANKICONNECT_KEY
                          where the addon listens, if its config moved it off
                          http://127.0.0.1:8765 (scheme optional), and the
                          `apiKey` that same config may require
  KOTOGEN_BACKUP=0       never snapshot automatically before maintain/ask/deck install
                          (`kotogen backup` run by hand, and the snapshot a
                          restore takes first, still happen)
  KOTOGEN_BACKUP_DIR     where snapshots live (default: the platform's data dir,
                          never the cache dir - those get wiped by cleaners)
  KOTOGEN_VERBOSE=1      interactive mode: end each command with the equivalent
                          command line (to learn the CLI); off by default
  KOTOGEN_AUDIO_QUALITY  how hard to compress downloaded/cut audio: none (the
                          default, no re-encoding), light, medium or strong;
                          --audio-quality overrides it
  KOTOGEN_VIDEO          video sources: what to do with the picture. 'ask'
                          (the default) asks once per run, and only when a video
                          is actually involved; 'always' keeps it (the card
                          plays a short clip), 'never' extracts the sound track.
                          Outside a terminal, and under --yes, the question
                          answers itself with the sound track; --video /
                          --no-video overrides it all
  KOTOGEN_PROOFREAD      cards returned damaged (the '!!' lines): 'ask'
                          (the default) asks once per run, and only if there is
                          one; 'keep' exports them as they are, 'tag' exports
                          them tagged 'Check::…', 'drop' keeps them out.
                          Outside a terminal, and under --yes, the question
                          answers itself by tagging them (they are paid for,
                          and no one read the '!!'); --proofread overrides it
  KOTOGEN_DEBUG=1        print the full traceback of an unexpected error
                          instead of a single summary line
        """,
    )

    # Answered before the missing subcommand can be complained about: a question
    # about the program, not a command, which `main` also keeps from the first-run
    # pass.
    parser.add_argument(
        "--version",
        action="version",
        version=f"kotogen {__version__}",
        help="Print the version of the program and exit",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # -- kanji ------------------------------------------------------------------
    kanji_parser = subparsers.add_parser(
        "kanji",
        parents=[ai_opts, out_opts],
        help="Generate kanji cards (meaning, readings, the words of your deck that carry them)",
    )
    kanji_input = kanji_parser.add_mutually_exclusive_group(required=True)
    kanji_input.add_argument(
        "entry",
        nargs="?",
        help=(
            "Kanji to make cards for: one or several (学, \"学 語 読\"), a word (学生 gives "
            "学 and 生), or an entry that names a kanji without writing it (gaku, study). "
            "The keyword 'deck' takes the kanji of your vocabulary that have no card yet, "
            "'jlpt' those of a JLPT level; a URL or a text file, the kanji of that text"
        ),
    )
    kanji_input.add_argument(
        "--file",
        "-f",
        type=Path,
        metavar="FILE",
        help="Text file whose kanji to make cards for (a list or a running text alike)",
    )
    kanji_parser.add_argument(
        "--count",
        "-n",
        type=int,
        default=None,
        metavar="N",
        help=(
            "deck/jlpt/text: how many kanji to make at most, the easiest first "
            "(default: 20). Replaying the command takes the next ones"
        ),
    )
    kanji_parser.add_argument(
        "--level",
        "-l",
        default="auto",
        choices=LEVEL_CHOICES,
        help=(
            "deck/jlpt/text: keep the kanji of that JLPT level only "
            "(default: auto = every level, easiest first)"
        ),
    )
    kanji_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Make cards even for the kanji that already have one. By default they are "
            "dropped before the AI is called (their card would be refused as a duplicate)"
        ),
    )
    kanji_parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        metavar="N",
        help="Kanji sent to the AI per request (default: 8)",
    )
    kanji_parser.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=4,
        metavar="N",
        help=(
            "Batches generated in parallel (default: 4, 1 = sequential). Same number "
            "of API calls, so same cost; only the waiting is shared"
        ),
    )
    # -- vocab ----------------------------------------------------------------
    vocab_parser = subparsers.add_parser(
        "vocab",
        parents=[ai_opts, out_opts],
        help="Generate vocabulary cards (recognition and production, one card per word)",
    )
    vocab_input = vocab_parser.add_mutually_exclusive_group(required=True)
    vocab_input.add_argument(
        "word",
        nargs="?",
        help=(
            "Word/expression to create a card for (raw notes, rōmaji, translation... anything), "
            "ANY web page URL (an NHK Easy article included) or local text file to mine, "
            "the keyword 'jlpt' for the words of a JLPT level your deck is still missing, "
            "or the path or URL of a PDF document (course, JLPT paper…)"
        ),
    )
    vocab_input.add_argument(
        "--file",
        "-f",
        type=Path,
        metavar="FILE",
        help="Markdown file with words - one entry per line (may include rough translation/rōmaji)",
    )
    vocab_input.add_argument(
        "--theme",
        "-t",
        metavar="THEME",
        help=(
            "The words of a theme your deck is still missing, in your own words: "
            "a field (fruits, programming), a situation (job interview), a closed set "
            "(days of the week, cities of Japan) or a class of words (i-adjectives)"
        ),
    )
    vocab_parser.add_argument(
        "--count",
        "-n",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Page/text/PDF/JLPT/theme: max words to extract per page/text/document/level/theme "
            "(default: 10 per page or text, 20 for 'jlpt' and --theme, no limit for a PDF)"
        ),
    )
    vocab_parser.add_argument(
        "--level",
        "-l",
        default="auto",
        choices=LEVEL_CHOICES,
        help=("Page/text/PDF/theme: JLPT level to target when picking words. "
              "JLPT source: which level to fill in (default: auto = easiest first, "
              "all levels)"),
    )
    vocab_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Generate even the entries already present in the deck. By default they are "
            "dropped before the AI is called (their card would be refused as a duplicate)"
        ),
    )
    vocab_parser.add_argument(
        "--decompose",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Also create a card for each vocabulary word an expression is made of "
            "(お腹が空いた → お腹, 空く), in dictionary form, particles and grammar left "
            "out. On for a word you type yourself and for --file lists, off for the bulk "
            "sources (PDF, JLPT, theme, web page, text) whose entries are already single words. "
            "The words are listed by the very call that writes the expression card, so "
            "spotting them costs nothing; only the cards you keep are paid for"
        ),
    )
    vocab_parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        metavar="N",
        help=(
            "Number of words sent to the AI per request (default: 10). "
            "Higher = fewer API calls but larger prompts; lower = safer format/quality"
        ),
    )
    vocab_parser.add_argument(
        "--no-known-words",
        action="store_false",
        dest="known_words",
        help=(
            "Do not tell the AI which words the deck already holds. By default the most "
            "fundamental known words are sent, so example sentences stay readable; they "
            "ride in the cached system prompt, so they are paid once per run"
        ),
    )
    vocab_parser.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=4,
        metavar="N",
        help=(
            "Batches generated in parallel (default: 4, 1 = sequential). Same number "
            "of API calls, so same cost; only the waiting is shared"
        ),
    )
    # -- grammar --------------------------------------------------------------
    grammar_parser = subparsers.add_parser(
        "grammar",
        parents=[ai_opts, out_opts],
        help="Generate grammar exercise cards for a given rule",
    )
    grammar_parser.add_argument(
        "rule",
        nargs="*",
        default=[],
        help=(
            "Grammar rule(s) to practise (e.g. '〜てください', 'のに', 'younitanomu' - "
            "rōmaji and rough notes are fine); or the keyword 'jlpt' for the rules of a "
            "JLPT level your deck is still missing"
        ),
    )
    grammar_parser.add_argument(
        "--file",
        "-f",
        type=Path,
        metavar="FILE",
        help="Text file with grammar rules - one per line (# comments are skipped)",
    )
    grammar_parser.add_argument(
        "--rules",
        type=int,
        default=None,
        metavar="N",
        help="JLPT source: max grammar rules to work on (default: 3)",
    )
    grammar_parser.add_argument(
        "--count",
        "-n",
        type=int,
        default=5,
        help="Number of cards to generate (default: 5)",
    )
    grammar_parser.add_argument(
        "--level",
        "-l",
        default="auto",
        choices=LEVEL_CHOICES,
        help=("JLPT source: which level to fill in "
              "(default: auto = easiest first, all levels)"),
    )
    grammar_parser.add_argument(
        "--url",
        default=None,
        metavar="URL",
        help=("Reference page for the cards, written in their URL field. Given WITHOUT a "
              "rule, the page itself says which rule to work on - any grammar site"),
    )
    # -- audio ----------------------------------------------------------------
    audio_parser = subparsers.add_parser(
        "audio",
        parents=[ai_opts, out_opts],
        help=("Generate listening cards from audio files, NHK Easy articles, podcasts, "
              "YouTube videos, Irodori lessons, JLPT past papers or Aozora Roudoku "
              "readings"),
    )
    audio_parser.add_argument(
        "inputs",
        nargs="+",
        metavar="AUDIO_URL_NHK_PODCAST_OR_YOUTUBE",
        help=(
            "Audio file(s)/folder(s) (.mp3, .wav, .m4a...), "
            "NHK Easy article URL(s) (https://news.web.nhk/news/easy/...), "
            "the keyword 'nhk' to fetch the latest articles from the site, "
            "a podcast alias (sakura-tips, teppei, noriko, haru… - a score of shows "
            "from N5 to N1, listed by level in the interactive assistant and by "
            "an unknown alias) or ANY podcast RSS feed URL, whose latest episode "
            "(or the one given by --episode) is downloaded, transcribed and cut "
            "into its self-contained passages, "
            "a YouTube channel alias (onomappu, nij, tekuteku… - immersion channels "
            "whose videos carry hand-written Japanese subtitles, so Whisper is skipped) "
            "or ANY YouTube video, channel or playlist URL, "
            "an official JLPT listening collection ('jlpt-n3', 'jlpt2012-n5'), "
            "an Irodori volume alias ('irodori-shokyu1' - free Japan Foundation "
            "textbook, one lesson at a time, --episode picks the lesson), "
            "or 'roudoku' for 青空朗読 (public-domain works read aloud, shortest "
            "first)"
        ),
    )
    audio_parser.add_argument(
        "--latest",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Number of items to process: NHK articles (default: 4); podcast "
            "episodes, YouTube videos, Irodori lessons and 'roudoku' readings "
            "(default: 1); past-paper sections and local files (default: all). "
            "The defaults differ because the costs do - an NHK article is two "
            "minutes long and comes with its own transcript, while an episode or "
            "a video weighs tens of megabytes and, unless subtitles come with it, "
            "several minutes of Whisper"
        ),
    )
    audio_parser.add_argument(
        "--episode",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Podcast episode number to start from, to work through an archive "
            "instead of following the latest (default: the latest episode). "
            "The number the show announces in its titles when it announces one, "
            "the rank from the oldest episode otherwise - either way no. 1 is the "
            "first episode ever published. --latest then takes that many episodes "
            "in a row, towards the recent ones (--episode 42 --latest 3: 42, 43, "
            "44). An explicitly numbered episode is processed even if it already "
            "was. Podcasts only: a YouTube feed holds its 15 latest videos and no "
            "archive behind them, so a number there would point at a different "
            "video after every upload - it is refused rather than left to drift"
        ),
    )
    audio_parser.add_argument(
        "--count",
        "-n",
        type=card_count,
        default=None,
        metavar="N",
        help=(
            "Max cards per audio/article, or 'auto' to let the content decide "
            "(default: auto). Never a quota: the AI stops as soon as the audio no "
            "longer supports another question, so a short clip yields fewer cards"
        ),
    )
    audio_parser.add_argument(
        "--level",
        "-l",
        default="auto",
        choices=LEVEL_CHOICES,
        help="JLPT level - 'auto' to detect automatically (default: auto)",
    )
    audio_parser.add_argument(
        "--max-duration",
        type=seconds,
        default=None,
        metavar="SEC",
        help=(
            "Skip any audio longer than this, in seconds (180, or 180s). NHK: measured "
            "before download and before the AI is called. Local files, podcast "
            "episodes and YouTube videos: applies to each passage found by the splitter, "
            "not to the whole file - and the splitter is told the limit, so it aims "
            "below it instead of proposing passages that get thrown away. To skip a "
            "whole YouTube video by its length, see --max-video. Optional: no limit "
            "by default"
        ),
    )
    audio_parser.add_argument(
        "--max-video",
        type=seconds,
        default=None,
        metavar="SEC",
        help=(
            "YouTube only: skip any video longer than this, in seconds (900, or 900s). "
            "Measured by probing the video, before anything is downloaded - that is the "
            "last moment where skipping still saves the bandwidth and the transcription. "
            "A separate flag from --max-duration on purpose: the two ask different "
            "questions, and 'no passage longer than 90 s' must not quietly mean 'no "
            "video at all'. Optional: no limit by default, and Shorts are dropped "
            "regardless (under 2 min is not listening material)"
        ),
    )
    audio_parser.add_argument(
        "--split",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Local and downloaded files alike (never an NHK article): detect a "
            "collection of separate conversations (JLPT samples, shadowing books) "
            "and cut it into one audio per conversation, keeping the "
            "conversation only - the announced number, the bell, the exam instructions "
            "and its own question are left out. Passages too thin for a question are "
            "dropped without calling the AI. A file holding a single conversation goes "
            "through whole, minus the number announcing it if there is one (textbook "
            "tracks open on theirs). Off with --no-split, which takes every file whole"
        ),
    )
    audio_parser.add_argument(
        "--whisper-model",
        default="medium",
        metavar="MODEL",
        help=(
            "Whisper model for the files to transcribe, local or downloaded: tiny, "
            "base, small, medium, large (default: medium). Transcription runs once per "
            "file and costs CPU time, not tokens - and its mistakes end up in the cards, "
            "so accuracy is worth the wait. Downloads ~1.4 GB on first use; falls back "
            "to small, loudly, if the machine cannot load it"
        ),
    )
    audio_parser.add_argument(
        "--audio-quality",
        choices=audio_quality.codes(),
        default=None,
        help=(
            "How hard to compress the audio kotogen downloads or cuts: none "
            "(the default: the stream is copied untouched, no re-encoding), "
            "light (MP3 mono 96k), medium (64k) or strong (48k). NHK Easy "
            "serves an already compressed stream, so re-encoding it lower "
            "stacks a second loss on the first - "
            "on the one thing the card trains. Without this option the "
            "interactive setting applies, then KOTOGEN_AUDIO_QUALITY"
        ),
    )
    audio_parser.add_argument(
        "--video",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Video files: keep the picture instead of extracting the sound track. "
            f"The card then plays a clip cut to the passage (VP9/WebM {video_clip.HEIGHT}p, "
            "always re-encoded - Anki's desktop WebView plays no H.264, and .mkv/.avi "
            "play in no WebView at all), and a passage "
            f"longer than {video_clip.MAX_SECONDS} s falls back to sound only, without "
            "a word: a media library that syncs has no room for a whole episode. Audio "
            "files are unaffected. Without this option KOTOGEN_VIDEO applies, "
            "which by default asks - once per run, and only if a video is really "
            "there; --no-video refuses the picture without asking, --video keeps "
            "it without asking"
        ),
    )
    # -- reading ---------------------------------------------------------------
    from kotogen.generators.deck_story import LENGTHS, SHAPES

    reading_parser = subparsers.add_parser(
        "reading",
        parents=[ai_opts, out_opts],
        help=(
            "Generate reading comprehension cards (the questions follow the "
            "language of the cards) from web pages, text files, NHK Easy articles, "
            "PDF documents, Tadoku books, Aozora Bunko works, JLPT past papers, "
            "Irodori lessons, page images, or texts written on your deck"
        ),
    )
    reading_parser.add_argument(
        "inputs",
        nargs="+",
        metavar="URL_PDF_OR_NHK",
        help=(
            "ANY web page URL or local text file, NHK Easy article URL(s), "
            "the keyword 'nhk' to fetch the latest articles from the site, "
            "the keyword 'deck' to have texts written on the words and grammar "
            "your deck is learning, "
            "PDF document path(s) or URL(s) whose reading texts will be mined, "
            "the URL of a free Tadoku book page (its PDF is downloaded, always "
            "a mini-book), an Aozora Bunko work or book-card URL, an official "
            "JLPT sample alias ('jlpt-n3', 'jlpt2012-n5'), an Irodori volume "
            "alias ('irodori-shokyu1'), and/or image file(s) or folder(s) of "
            "page images (always a mini-book)"
        ),
    )
    reading_parser.add_argument(
        "--read-as",
        default="auto",
        choices=["auto", "text", "book"],
        help=(
            "PDF only: how to read the document (default: auto, decided from "
            "the pages themselves). 'text' mines the reading texts as text, "
            "'book' renders the pages as images the card leafs through "
            "(image inputs and Tadoku books are always read as a book)"
        ),
    )
    reading_parser.add_argument(
        "--pages",
        default=None,
        metavar="RANGE",
        help=(
            "PDF or folder of page images: pages to keep, 1-based (e.g. 3-18, 12-, "
            "or 7 for a single page such as one JLPT exercise); default: all of them"
        ),
    )
    reading_parser.add_argument(
        "--latest",
        type=int,
        default=4,
        metavar="N",
        help="NHK ('nhk' keyword): number of recent articles to process (default: 4)",
    )
    reading_parser.add_argument(
        "--count",
        "-n",
        type=card_count,
        default=None,
        metavar="N",
        help=(
            "Max questions per text or per passage of a long one, or 'auto' to let the content decide "
            "(default: auto). Never a quota: the AI stops as soon as the text no "
            "longer supports another question, so a short one yields fewer cards"
        ),
    )
    reading_parser.add_argument(
        "--texts",
        type=int,
        default=None,
        metavar="N",
        help=(
            "PDF: max reading texts to extract per document (default: all). "
            "'deck': how many texts to write (default: 1)"
        ),
    )
    reading_parser.add_argument(
        "--shape",
        default="story",
        choices=list(SHAPES),
        help=(
            "'deck' only: a story or a dialogue from everyday life, or a text "
            "shaped like the JLPT reading section - a notice, an e-mail, an "
            "essay (default: story)"
        ),
    )
    reading_parser.add_argument(
        "--length",
        default="short",
        choices=list(LENGTHS),
        help=(
            "'deck' only: the JLPT lengths of the level - short (短文, 80 to 200 "
            "characters), medium (中文, 250 to 500), long (長文, 550 to 1000, "
            "from N3 up) (default: short)"
        ),
    )
    reading_parser.add_argument(
        "--from-passage",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Long text only: start at passage N instead of resuming where the "
            "last run stopped, and ignore the history (the reading counterpart "
            "of --episode). '--from-passage 1' rereads a work from its beginning"
        ),
    )
    reading_parser.add_argument(
        "--passages",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Long text only: max passages processed in ONE run, each becoming "
            "one card text with its own questions (default: 6). Running the "
            "command again picks up where it stopped, so a novel is read a few "
            "passages at a time. A text that already fits on a card is never cut"
        ),
    )
    reading_parser.add_argument(
        "--level",
        "-l",
        default="auto",
        choices=LEVEL_CHOICES,
        help="JLPT level - 'auto' to detect automatically (default: auto)",
    )
    # -- maintain ---------------------------------------------------------------
    maintain_parser = subparsers.add_parser(
        "maintain",
        parents=[ai_opts],  # neither --send nor --output: maintain writes into Anki
        help="Maintain an existing deck: review flagged cards and clean/rework leeches (AnkiConnect required)",
    )
    maintain_parser.add_argument(
        "--only",
        nargs="+",
        metavar="TARGET",
        default=None,
        help=(
            "Targets to process (default: every flag with an action, and 'leech' "
            "unless KOTOGEN_FLAGS says leech=none). Flag colours: red orange "
            "green blue pink turquoise purple (or numbers 1-7), 'star', an action "
            "(error simplify enrich text derive duplicate audio renew), and/or "
            "'leech'. Ex: --only red renew leech"
        ),
    )
    maintain_parser.add_argument(
        "--type",
        nargs="+",
        choices=("vocab", "grammar", "reading", "audio"),
        metavar="TYPE",
        default=None,
        help=(
            "Note types to go through, named by their command: vocab grammar "
            "reading audio (default: every one this profile uses, see KOTOGEN_SKIP)"
        ),
    )
    maintain_parser.add_argument(
        "--tag",
        default=DEFAULT_TAG,
        help=f"Leech tag name (default: {DEFAULT_TAG})",
    )
    maintain_parser.add_argument(
        "--mature-ivl",
        type=int,
        default=IVL_MATURE,
        metavar="DAYS",
        help=f"Interval (days) above which a leech is considered mastered (default: {IVL_MATURE})",
    )
    maintain_parser.add_argument(
        "--scan",
        action="store_true",
        help="List what needs attention (flags + leeches), then exit (no AI, no changes)",
    )
    maintain_parser.add_argument(
        "--yes",
        "-y",
        nargs="*",
        metavar="TARGET",
        default=None,
        help=(
            "Auto-accept, with no per-card validation: apply flag fixes, bulk-clean false "
            "leeches, rework+reset true ones. Never deletes a note. Bare '--yes' applies to "
            "every processed target; '--yes red leech' restricts auto mode to those targets"
        ),
    )

    # -- ask ---------------------------------------------------------------------
    # The AI options, and nothing of `maintain`: the only target is the sentence
    # typed, and the note types opened are those the backup covers.
    ask_parser = subparsers.add_parser(
        "ask",
        parents=[ai_opts],  # neither --send nor --output: it writes into Anki
        help="State a request in your own words and let the AI work on the deck (AnkiConnect required)",
    )
    ask_parser.add_argument(
        "request",
        help=(
            "What to do, in your own words. Ex: \"take the N4 tag off the cards whose "
            "interval is over 60 days\". The AI works with the project's tools, and every "
            "write is shown before it is made. Requires --provider openrouter"
        ),
    )
    ask_parser.add_argument(
        "--scan",
        action="store_true",
        help="Look only: the writing tools are not even given to the AI (questions, surveys)",
    )
    ask_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help=(
            "Apply each write without confirming it one by one. A deletion is still "
            "asked for: no note goes without you"
        ),
    )

    # -- rework ------------------------------------------------------------------
    # The AI options, and nothing of the deck: a file of cards in, a file of
    # proposals out.
    rework_parser = subparsers.add_parser(
        "rework",
        parents=[ai_opts],
        help=("Rework the cards of a JSON Lines file: write what the AI proposes for "
              "each one into another file (nothing is sent, nothing is changed)"),
    )
    rework_parser.add_argument(
        "cards",
        type=Path,
        metavar="CARDS",
        help="JSON Lines file of cards, as --format json writes it",
    )
    rework_parser.add_argument(
        "--task",
        required=True,
        choices=list(REWORK_TASKS),
        help=(
            "What to propose for each card: 'simplify' makes it lighter, 'reading' "
            "writes its Japanese right (readings first), 'leech' reworks it as "
            "maintain reworks a leech, 'derive' lists the words and rules it calls "
            "for, those the file already holds left out"
        ),
    )
    rework_parser.add_argument(
        "--ids",
        type=Path,
        default=None,
        metavar="FILE",
        help=("File of the ids of the cards to rework, one per line "
              "(default: every card the task applies to)"),
    )
    rework_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        metavar="FILE",
        help="Where to write the proposals (default: <cards>.<task>.jsonl beside the cards)",
    )

    # -- deck --------------------------------------------------------------------
    # No AI options: installing a note type calls no model.
    deck_parser = subparsers.add_parser(
        "deck",
        help="Install/update the Anki note types from templates/ (AnkiConnect required)",
    )
    deck_parser.add_argument(
        "action",
        choices=["install"],
        help="install: create the missing note types, update the existing ones",
    )
    deck_parser.add_argument(
        "--only",
        nargs="+",
        metavar="TARGET",
        default=None,
        help="Note types to handle (default: all). Ex: --only vocab grammar",
    )
    deck_parser.add_argument(
        "--check",
        action="store_true",
        help="List what would change, then exit (no modification)",
    )
    deck_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help=(
            "Overwrite existing note types without asking, faces edited both in Anki "
            "and in kotogen included. Missing ones are always created without asking; "
            "nothing is ever deleted"
        ),
    )
    deck_parser.add_argument(
        "--overwrite-edits",
        action="store_true",
        help=(
            "Also offer to put the repository back over the faces edited in Anki "
            "alone. Off by default: such an edit is kept and reported"
        ),
    )
    deck_parser.add_argument(
        "--diff",
        action="store_true",
        help=(
            "Show the full diff of every difference. Off by default: only short "
            "ones are unfolded, the others are counted"
        ),
    )
    deck_parser.add_argument(
        "--add-cards",
        action="store_true",
        help=(
            "Also add the card templates the repo has and the note type lacks. Off "
            "by default: adding one creates a card to review for EVERY existing note"
        ),
    )

    # -- backup ------------------------------------------------------------------
    # No AI options either: backing up calls no model.
    backup_parser = subparsers.add_parser(
        "backup",
        help="Snapshot/restore the Japanese decks: notes, tags, scheduling, templates (AnkiConnect required)",
    )
    backup_parser.add_argument(
        "--only",
        nargs="+",
        metavar="TARGET",
        default=None,
        help="Decks to snapshot (default: all of them). Ex: --only vocab grammar",
    )
    backup_parser.add_argument(
        "--list",
        action="store_true",
        help="List the snapshots already taken, newest first",
    )
    backup_parser.add_argument(
        "--diff",
        nargs="?",
        const="latest",
        metavar="STAMP",
        default=None,
        help=(
            "Show what changed since a snapshot (default: the latest one). "
            "STAMP is a timestamp such as 2026-08-17_143012, or just 2026-08-17"
        ),
    )
    backup_parser.add_argument(
        "--restore",
        nargs="?",
        const="latest",
        metavar="STAMP",
        default=None,
        help=(
            "Put a snapshot back: fields, tags, scheduling, recreated notes, templates. "
            "Never deletes anything - notes added since are left alone"
        ),
    )
    backup_parser.add_argument(
        "--full",
        action="store_true",
        help=(
            "Also export one .apkg per deck (media and scheduling included). Heavy, "
            "and restored by hand from Anki: the JSON snapshot is the one kotogen replays"
        ),
    )
    backup_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Restore without the confirmation prompt",
    )

    # -- update ------------------------------------------------------------------
    # Neither AI nor deck options: this one touches the program, not the
    # collection, and calls no model.
    update_parser = subparsers.add_parser(
        "update",
        help="Bring the program up to date: take the sources of its repository, then renew the modules installed",
    )
    update_parser.add_argument(
        "--check",
        action="store_true",
        help="Only say what the repository has waiting; nothing is taken and nothing is installed",
    )

    return parser


# Deck / note type per command, overridable by a setting (KOTOGEN_<COMMAND>_DECK
# / KOTOGEN_<COMMAND>_NOTETYPE), not by an option. The table belongs to the
# registry, which derives those settings from it.
_DECK_DEFAULTS = settings.DECK_DEFAULTS

# The commands that own a deck: what the backup calls "the Japanese decks", the
# rest of the collection staying out of its archives.
DECK_COMMANDS = tuple(_DECK_DEFAULTS)


def deck_config(command: str) -> tuple[str, str]:
    """Deck and note type of a command, settings included (also used by the
    interactive assistant to say which ones already exist in Anki)."""
    prefix = f"KOTOGEN_{command.upper()}"
    return settings.text(f"{prefix}_DECK"), settings.text(f"{prefix}_NOTETYPE")


def cards_var(command: str) -> str:
    """Name of the variable listing the cards wanted for this command."""
    return f"KOTOGEN_{command.upper()}_CARDS"


def wanted_cards(command: str) -> list[str]:
    """Cards of that note type this profile installs, or [] for "all of them".

    A whitelist: the repository carries every model, including those a profile
    does not review (the `Production` of the vocabulary).
    """
    return settings.items(cards_var(command))


def enabled_cards(command: str, cards: tuple) -> tuple:
    """Filters the cards of the repository by the whitelist of the settings.

    The repository's order is kept: it fixes the order of the cards at creation.
    """
    wanted = wanted_cards(command)
    return tuple(card for card in cards if card[0] in wanted) if wanted else cards


def skipped_commands() -> frozenset[str]:
    """Commands declared unused (KOTOGEN_SKIP), in lower case.

    A blacklist, unlike the cards, so that a command added later is on for all.
    """
    return frozenset(name.lower() for name in settings.items("KOTOGEN_SKIP"))


def _resolve_deck_config(args: argparse.Namespace) -> None:
    """Fills args.deck / args.notetype in from the defaults or the settings."""
    if args.command in _DECK_DEFAULTS:
        args.deck, args.notetype = deck_config(args.command)


def _resolve_format(args: argparse.Namespace) -> None:
    """Fills args.format in, and settles what it allows of the send.

    A file named by --output has its format by its suffix (`exporter.is_json`):
    a --format that disagrees is refused, as is a JSON Lines file this release
    cannot read. JSON Lines sends nothing: --send is refused, auto-send is off.
    """
    if not hasattr(args, "format"):
        return
    fmt = args.format or output_format()
    if args.output:
        from kotogen.exporter import NotCards, is_json, read_cards
        named = "json" if is_json(args.output) else "tsv"
        if args.format and args.format != named:
            sys.exit(_("--format {format} does not match {path}: a .jsonl file is "
                       "JSON Lines, any other is a TSV")
                     .format(format=args.format, path=_quoted(args.output)))
        fmt = named
        existing = Path(args.output)
        if fmt == "json" and existing.is_file() and existing.stat().st_size:
            try:
                read_cards(existing)
            except NotCards as exc:
                sys.exit(console.reason(exc, console.ALONE))
            except OSError:
                pass  # the writing will say what stands in the way
    if fmt == "json":
        if args.send:
            sys.exit(_("--send puts the cards into Anki and JSON Lines is for other "
                       "tools: use one or the other"))
        args.send = False
    args.format = fmt


def _force_utf8_output() -> None:
    """Avoids UnicodeEncodeError on Windows consoles in cp1252 (kana, accents)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    # The watcher of the output, put on before the first line (see `console`).
    console.watch()


# The commands that call the model; `maintain --scan` is the one mode of them
# that never does.
MODEL_COMMANDS = ("vocab", "grammar", "kanji", "audio", "reading", "maintain", "ask",
                  "rework")


def needs_model(args: argparse.Namespace) -> bool:
    """True if this command line calls the model, and so needs one chosen."""
    if args.command == "maintain" and getattr(args, "scan", False):
        return False
    return args.command in MODEL_COMMANDS


def _run(argv: list[str], *, recap: bool = False) -> bool:
    """Parses the argv and runs the matching subcommand.

    `recap` recalls the equivalent command at the end of the run, for the
    interactive assistant, and only in verbose mode (KOTOGEN_VERBOSE, the "v"
    setting of the menu). True when the command renewed the program itself (an
    update that took new sources), which a running session no longer matches."""
    from kotogen.anki.deck import DECK

    parser = build_parser()
    args = parser.parse_args(argv)
    _resolve_deck_config(args)
    _resolve_format(args)
    # A run aimed at the deck remembers with Anki's, which the library cannot
    # name; `rework` aims at a file and remembers with nothing.
    memory.follow(args, deck=None if args.command == "rework" else DECK)

    # Neither --send nor --no-send: the automatic-send preference decides.
    if hasattr(args, "send") and args.send is None:
        from kotogen import prefs
        args.send = prefs.auto_send()

    # The model chosen for the provider; `deck` has no --model to resolve.
    if getattr(args, "model", "") is None:
        args.model = chosen_model(args.provider)

    from kotogen import ai_client
    from kotogen.ai_client import AIAuthError
    from kotogen.exporter import unattended
    # What `ask` cannot serve whatever the model (a provider without tools) is
    # said first, or the model would be chosen for nothing.
    if args.command == "ask":
        from kotogen.anki.ask import preflight
        preflight(args)
    # Before any work: a download, a browser or a reading of the deck is paid
    # for nothing when no model can follow it.
    if needs_model(args) and not args.model:
        sys.exit(ai_client.no_model(args.provider))

    # A final AI failure (key, quota, permissions) crosses the generators on
    # purpose, so as not to be replayed at every batch, and ends here as a message.
    ai_client.reset_run_usage()
    try:
        # `--yes` of a command that produces cards: no question stops it.
        with unattended(getattr(args, "unattended", False)):
            if args.command == "vocab":
                from kotogen.generators.vocab import run_vocab
                run_vocab(args)
            elif args.command == "grammar":
                from kotogen.generators.grammar import run_grammar
                run_grammar(args)
            elif args.command == "audio":
                from kotogen.generators.audio import run_audio
                run_audio(args)
            elif args.command == "reading":
                from kotogen.generators.reading import run_reading
                run_reading(args)
            elif args.command == "kanji":
                from kotogen.generators.kanji import run_kanji
                run_kanji(args)
            elif args.command == "maintain":
                from kotogen.anki.maintain.review import run_maintain
                run_maintain(args)
            elif args.command == "ask":
                from kotogen.anki.ask import run_ask
                run_ask(args)
            elif args.command == "rework":
                from kotogen.rework import run_rework
                run_rework(args)
            elif args.command == "deck":
                from kotogen.anki.notetypes import run_deck
                run_deck(args)
            elif args.command == "backup":
                from kotogen.anki.backup import run_backup
                run_backup(args)
            elif args.command == "update":
                from kotogen.update import run_update
                return run_update(args)
    except AIAuthError as exc:
        # The message stands on its own ("API key ... refused"): no prefix.
        sys.exit(str(exc))
    finally:
        # In a `finally`: a command interrupted or crashed has paid for calls
        # too. The cost always comes out, the equivalent command only if asked.
        from kotogen import prefs
        _print_footer(argv if recap and prefs.verbose() else None)
    return False


def format_cmd(argv: list[str]) -> str:
    """Makes the argv displayable: quotes around the arguments with spaces."""
    return " ".join(f'"{a}"' if " " in a else a for a in argv)


def _print_footer(argv: list[str] | None) -> None:
    """End-of-command summary: what was launched, then what it cost.

    Written at the end, where it is read on getting control back, and stuck to
    the block it closes. The duration only appears in the cost summary, beside
    the tokens and the price: alone it would measure the wait on Anki."""
    from kotogen.ai_client import finish_run

    usage = finish_run()
    lines = []
    if argv is not None:
        lines.append(_("Equivalent command: kotogen {line}")
                     .format(line=format_cmd(argv)))
    if summary := usage.summary():
        lines.append(summary)
    if lines:
        # `close_line` and not `space`: the footer lands right under the last
        # line the command wrote.
        console.close_line()
        print("\n".join(lines))


def _getting_started() -> bool:
    """Open the getting-started guide if this first launch has anything to set
    up; say whether it opened.

    The first launch is recorded whether the guide opens or not, so it never
    turns up later, and before it runs, so Ctrl+C counts too. Imported here: it
    brings the whole assistant, which a command typed in full does not need.
    """
    from kotogen import getting_started

    if not getting_started.first_launch():
        return False
    getting_started.met()
    if not getting_started.needed():
        return False
    getting_started.run()
    return True


def _run_typed(argv: list[str]) -> None:
    """A command typed in the shell, under the net the assistant's commands get.

    SystemExit goes through as it is: it carries the command's own message and code.
    """
    try:
        _run(argv)
    except KeyboardInterrupt:
        console.space()
        print(_("Command interrupted."))
        sys.exit(130)  # what a shell expects of a program stopped by Ctrl+C
    except EOFError:
        # A question asked with no terminal to answer it: stdin piped or closed.
        console.space()
        sys.exit(_("The input ended before a question was answered: run the command "
                   "in a terminal, or with --yes where it takes one."))
    except Exception as exc:
        console.space()
        if settings.flag("KOTOGEN_DEBUG"):
            import traceback
            traceback.print_exc()
            sys.exit(unexpected(exc))
        sys.exit(unexpected(exc) + "\n" + _("To see where it happened, run the command "
                                            "again with KOTOGEN_DEBUG=1."))


def unexpected(exc: Exception) -> str:
    """What an error nothing caught says: its first line, then its kind.

    The kind names the error in a report; what is below the first line (a raw
    model answer) stays for KOTOGEN_DEBUG.
    """
    kind = type(exc).__name__
    if not console.clean(str(exc)).strip():
        return _("Stopped by an unexpected error ({kind})").format(kind=kind)
    return _("Stopped by an unexpected error: {error} ({kind})").format(
        error=console.reason(exc, console.ALONE), kind=kind)


def _assistant_can_open() -> bool:
    """True if somebody can drive the assistant: a terminal on both sides."""
    return system.can_ask()


def main() -> None:
    from kotogen.anki.deck import DECK

    _force_utf8_output()
    system.ignore_current_folder()  # before the first ffmpeg, git or clip is run
    settings.load()  # settings of the repository and of the profile, if any
    # Until a command says otherwise, the program remembers with the deck: the
    # screens of the assistant read it before any command has run.
    memory.follow(argparse.Namespace(), deck=DECK)

    argv = sys.argv[1:]
    if not argv and not _assistant_can_open():
        # Before the guide and the first-run offer, which would mark themselves
        # seen for a launch nobody was in front of.
        sys.exit(_("The assistant needs a terminal: outside one, type the command "
                   "itself (kotogen --help lists them)."))
    # What is missing installs itself here, once per environment, before the
    # first paid call (see `prerequisites`). Not for a help or a version, nor
    # when the getting-started guide has just opened: it asks that last.
    try:
        welcomed = not argv and _getting_started()
    except (KeyboardInterrupt, EOFError):
        # Ctrl+C in the guide quits, as it does at the main menu.
        console.space()
        print(_("Cancelled."))
        return
    if not {"-h", "--help", "--version"} & set(argv) and not welcomed:
        from kotogen import prerequisites
        before = console.lines_written()
        prerequisites.on_first_run()
        # The interactive assistant opens by clearing the screen: a pause, only
        # if the pass wrote something, lets it be read.
        if not argv and console.lines_written() > before:
            from kotogen.interactive.screen import _pause
            _pause(_("Enter to continue..."))
    if argv:
        _run_typed(argv)
        return

    # Without an argument: the interactive assistant in a loop, each command it
    # builds going through argparse, until "q", or Ctrl+C at the main menu or in
    # the settings. A command's errors (sys.exit) or interruption bring the menu back.
    from kotogen.interactive import interactive_argv
    banner = True
    while True:
        argv = interactive_argv(banner=banner)
        banner = False
        if argv is None:  # the user has quit or cancelled (Ctrl+C)
            return
        try:
            renewed = _run(argv, recap=True)
        except SystemExit as exc:
            if isinstance(exc.code, str):
                # Like every incident: "!!" under the block where it happened.
                console.failed(exc.code)
        except KeyboardInterrupt:
            console.space()
            print(_("Command interrupted."))
        except Exception as exc:
            # A net: the unforeseen (network, an unexpected answer) must not take
            # the session down. The full trace is printed with KOTOGEN_DEBUG=1.
            console.failed(unexpected(exc))
            if settings.flag("KOTOGEN_DEBUG"):
                import traceback
                traceback.print_exc()
        else:
            if renewed:
                # The modules imported at start-up are the old version's, the
                # data files on disk the new one's: the update said to relaunch.
                return


if __name__ == "__main__":
    main()
