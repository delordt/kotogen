"""Audio comprehension card generator (mp3 → Whisper → AI → cards)."""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import shutil
import sys
import tempfile
from functools import partial
from pathlib import Path

from kotogen import audio_quality, console, prompts, proofreading, video_clip
from kotogen.ai_client import AIAuthError, AIClient, AITruncatedError
from kotogen.exporter import (
    append_cards,
    audio_ref,
    finish,
    image_ref,
    resolve_output_path,
    video_ref,
)
from kotogen.generators import (
    audio_files,
    audio_split,
    exam_items,
    key_line,
    quota,
    subtitles,
    timecodes,
    whisper,
)
from kotogen.generators.audio_split import Segment
from kotogen.i18n import _, agreed, convention, counted
from kotogen.jlpt import LEVELS as JLPT_LEVELS

# A lone speaker label inside a sentence: "What is A doing?", "person B". Not
# when a hyphen or an apostrophe touches it, as in the French `A-t-il` or `l'A`.
_SPEAKER_LABEL_RE = re.compile(r"(?<![\w'’-])[ABC](?![\w'’-])")

FIELDS = [
    "ID",
    "Audio",
    # The media when the source is a video and its picture was asked for
    # (`--video`). Never filled with `Audio`: Anki's templates can only test
    # whether a field is empty, so the filled one says which file plays.
    "Video",
    "Question",
    "Decoy1",
    "Decoy2",
    "Decoy3",
    "Image",
    "Answer",
    "Transcript",
    "Translation",
    # One instant per Transcript line, in seconds, separated by spaces
    # (`12.34 16.00 -`), paired with the lines by rank as Translation is.
    # Read by the template only, never displayed.
    "Timecodes",
    # Rank (from 1) of the Transcript line that carries the answer. A field
    # rather than a marker on the line: the transcript stays plain content, the
    # same on every card of the passage, and a fix in Anki is a number typed.
    "KeyLine",
    "Source",
]


# ── AI generation ─────────────────────────────────────────────────────────────

# Tells the generator it has a multiple-choice item, which the prompt forbids it
# to guess (`_is_choice` knows it for free). Held in English and translated by
# `prompts.say` where used: the language of the cards is unknown at import.
CHOICE_INSTRUCTION = (
    "This audio is a past-paper item with ANSWERS TO CHOOSE FROM (発話表現 or "
    "即時応答): a prompt, then three replies numbered 1, 2 and 3 of which only one "
    "fits. Apply case 3, and hand back exactly one card: \"Question\": \"\", Answer "
    "in Japanese (the reply that fits, its number included) and \"Decoys\": []."
)

# The question of every such item, written here: the exam prints none, and the
# model's would tell the situation the audio is there to tell. Card text, in the
# language of the cards.
CHOICE_QUESTION = "Which of the three replies fits?"

# Tells the generator the passage has a printed figure, attached to the call: the
# figure illustrates the audio's own question, and only the model knows which
# card asks it. That card alone carries the figure. The booklet was cut by
# machine, so the model also says whether the figure belongs to this audio.
FIGURE_INSTRUCTION = (
    "This audio is a past-paper item with a PRINTED FIGURE, attached to this "
    "message and shown on the front of the card. Apply the rule of the printed "
    "figure: describe it in \"FigureShows\", then say in \"FigureFits\" whether "
    "it illustrates this audio; if it does, "
    "the first card asks the question the audio itself asks, with \"Decoys\": [], "
    "is answered by the label the figure prints, and it alone carries "
    "\"Figure\": true."
)

# The same check on an item with replies to choose, whose one card takes the
# picture of its prompt.
CHOICE_FIGURE_INSTRUCTION = (
    "The picture of this item is attached to this message and shown on the front "
    "of the card: describe it in \"FigureShows\", then say in \"FigureFits\" "
    "whether it shows the situation the prompt describes."
)


def _generate_for_audio(
    client: AIClient,
    audio_name: str,
    transcript_lines: list[str],
    limit: int,
    level: str,
    choice: bool = False,
    figure: Path | None = None,
) -> dict:
    """The model's answer for one passage; `figure`, when given, goes with the call."""
    numbered = "\n".join(f"{i}. {line}" for i, line in enumerate(transcript_lines, 1))
    # Prompt, not screen: the whole message is in the language of the cards.
    if level == "auto":
        level_part = prompts.say("Estimate the JLPT level of the content (Level field).")
    else:
        level_part = prompts.say("The target JLPT level is {level}.").format(level=level)

    user_msg = (
        prompts.say("Raw transcript of the file \"{name}\":").format(name=audio_name)
        + f"\n\n{numbered}\n\n"
        + (prompts.say(CHOICE_INSTRUCTION) if choice else quota.instruction(limit))
        + (" " + prompts.say(CHOICE_FIGURE_INSTRUCTION if choice else FIGURE_INSTRUCTION)
           if figure is not None else "")
        + f" {level_part}"
    )

    if figure is None:
        result = client.chat_json(prompts.load("audio_card"), user_msg)
    else:
        # A one-page PDF: the one attachment every provider of the client reads.
        from kotogen.generators import pdf_pages

        result = client.chat_json_pdf(prompts.load("audio_card"), user_msg,
                                      pdf_pages.to_pdf([figure]),
                                      figure.with_suffix(".pdf").name)
    if not isinstance(result, dict):
        raise ValueError(_("unexpected JSON structure: {kind}").format(kind=type(result).__name__))
    return result


# ── Post-processing ───────────────────────────────────────────────────────────

# Why a card was tagged for proofreading, beside the reasons it shares with the
# reading cards (`proofreading.UNALIGNED_TRANSLATION`): English, translated where
# displayed, as a module-level `_()` would run before `cli.main()` loads them.
MISSING_TRANSCRIPT = "transcript missing"


def _post_process(result: dict, audio_name: str, stem: str, level_arg: str,
                  source: str = "", *, segments: list[Segment] | None = None,
                  block=None, whole: bool = False, figure: str = "",
                  is_video: bool = False, reading: bool = False,
                  choice: bool = False) -> list[dict]:
    """Builds the final cards: Anki fields, key line marked, the answer apart from
    the decoys (the template shuffles the four).

    `segments` and `block` fill Timecodes, matched on readings with `reading` (a
    transcript not heard from the audio). `choice` drops the written options,
    which would give the answer away; `figure` goes on the card marked for it.
    """
    t_lines = [str(l) for l in (result.get("TranscriptLines") or []) if str(l).strip()]
    f_lines = [str(l) for l in (result.get("TranslationLines") or []) if str(l).strip()]

    level = level_arg if level_arg != "auto" else str(result.get("Level", "")).strip()
    if level not in JLPT_LEVELS:
        level = "N5"

    # A flaw of the passage is marked on each of its cards (below), as cards are
    # found again in Anki one by one.
    flaws: list[tuple[str, str]] = []
    if not t_lines:
        console.failed(_("transcript missing from the AI answer - Transcript "
                         "field empty."))
        flaws.append((proofreading.TRANSCRIPT_TAG, MISSING_TRANSCRIPT))
    if len(f_lines) != len(t_lines):
        # The template pairs the lines by rank: off by one, every line would
        # show the translation of another, so none is kept, as on a reading card.
        console.failed(_("translation not lined up ({given} lines vs {expected}) "
                         "- Translation field left empty.").format(
                             given=len(f_lines), expected=len(t_lines)))
        flaws.append((proofreading.TRANSLATION_TAG, proofreading.UNALIGNED_TRANSLATION))
        f_lines = []

    transcript = "\n".join(t_lines)
    translation = "\n".join(f_lines)
    # The field cannot tell an instant heard from one prorated between two
    # neighbours, so the screen says how many were prorated: many means the
    # transcript drifted.
    log: list[str] = []
    stamps = (timecodes.for_lines(t_lines, segments, block, whole=whole,
                                  reading=reading, log=log)
              if segments else "")
    if (prorated := log.count(timecodes.PRORATA)):
        console.aside(counted(prorated,
                              "{count} line timestamped pro rata: its text was "
                              "recognised in the sound neither by its spelling nor by "
                              "its reading",
                              "{count} lines timestamped pro rata: their text was "
                              "recognised in the sound neither by its spelling nor by "
                              "its reading").format(count=prorated))

    # The model saw the figure: one cut out for another item goes on no card.
    if figure and result.get("FigureFits") is False:
        console.aside(_("the figure does not illustrate this passage: it is left out"))
        figure = ""
    cards: list[dict] = []
    figure_laid = False
    for i, raw in enumerate(result.get("Cards") or [], start=1):
        if not isinstance(raw, dict):
            console.aside(_("card {rank} skipped (fields incomplete)").format(rank=i))
            continue
        # A choice item asks the same question everywhere (see CHOICE_QUESTION).
        question = (prompts.say(CHOICE_QUESTION) if choice
                    else str(raw.get("Question", "")).strip())
        answer = str(raw.get("Answer", "")).strip()
        decoys = [str(r).strip() for r in (raw.get("Decoys") or []) if str(r).strip()]
        # The figure's card is answered on its drawings, as in the exam: written
        # options would be a second set matching none of them.
        illustrated = bool(figure) and not figure_laid and (
            choice or raw.get("Figure") is True)
        if illustrated and not choice:
            decoys = []
        if choice and decoys:
            # The model ignored the instruction: worth saying, though the card
            # does without them.
            console.aside(counted(len(decoys),
                                  "card {rank}: {count} written option on a "
                                  "multiple-choice item, dropped",
                                  "card {rank}: {count} written options on a "
                                  "multiple-choice item, dropped")
                          .format(rank=i, count=len(decoys)))
            decoys = []

        if not question or not answer:
            console.aside(_("card {rank} skipped (fields incomplete)").format(rank=i))
            continue
        # The A/B/C labels live in the transcript, on the back: a front asking
        # "What is A doing?" names someone the learner never heard named.
        if any(_SPEAKER_LABEL_RE.search(field)
               for field in (question, answer, *decoys)):
            console.aside(_("card {rank} skipped: it names a speaker A/B, a label "
                            "the front does not show.").format(rank=i))
            continue
        # The answer is always an option; a decoy equal to it shows it twice.
        duplicate = ""
        if answer in decoys:
            decoys = [r for r in decoys if r != answer]
            console.failed(_("card {rank}: the Answer also appears among the "
                             "decoys.").format(rank=i))
            duplicate = proofreading.DUPLICATED_ANSWER

        # The note carries three decoys; how many show is the template's
        # "Number of options". A card with fewer is kept, and said: no setting
        # will give it options back.
        if len(decoys) > 3:
            console.aside(counted(len(decoys) - 3,
                                  "card {rank}: {count} decoys for 3 fields, the "
                                  "last one is dropped",
                                  "card {rank}: {count} decoys for 3 fields, the "
                                  "last {extra} are dropped").format(
                                      rank=i, count=len(decoys), extra=len(decoys) - 3))
            decoys = decoys[:3]
        elif not decoys:
            # Not said in case 3 or on the figure: no options is the card there.
            if not choice and not illustrated:
                console.aside(_("card {rank}: no decoy handed back, kept as an "
                                "open question").format(rank=i))
        elif len(decoys) < 3:
            console.aside(_("card {rank}: {count} {decoys} instead of 3, "
                            "{options} options at most").format(
                                rank=i, count=len(decoys),
                                decoys=console.plural(len(decoys), "decoy"),
                                options=len(decoys) + 1))

        key = key_line.rank(raw.get("KeyLine"), len(t_lines))
        # On a choice item, the line the answer was copied from beats the
        # model's rank, counted on the transcript as given. Silent: both mostly
        # agree.
        if choice and (found := exam_items.answered_line(answer, t_lines)):
            key = key_line.rank(found, len(t_lines))
        figure_laid = figure_laid or illustrated

        cards.append({
            "ID": f"{stem}_{i:03d}",
            # The unused field stays empty: a tag for a file never dropped would
            # be a missing media at the first review.
            "Audio": "" if is_video else audio_ref(audio_name),
            "Video": video_ref(audio_name) if is_video else "",
            "Question": question,
            "Decoy1": decoys[0] if len(decoys) > 0 else "",
            "Decoy2": decoys[1] if len(decoys) > 1 else "",
            "Decoy3": decoys[2] if len(decoys) > 2 else "",
            "Image": image_ref(figure) if illustrated else "",
            "Answer": answer,
            "Transcript": transcript,
            "Translation": translation,
            "Timecodes": stamps,
            "KeyLine": key,
            "Source": source,
            "Tags": f"Level::{level}",
        })
        if duplicate:
            proofreading.mark(cards[-1:], proofreading.CHOICES_TAG, duplicate)

    if figure and cards and not figure_laid:
        console.aside(_("no card asks the question of the figure: it is left out"))

    for tag, reason in flaws:
        proofreading.mark(cards, tag, reason)

    return cards


# ── One passage, a series of cards ────────────────────────────────────────────

def _write_extract(source: Path, out_dir: Path, rank: int, suffix: str, write) -> Path:
    """Writes an extract beside the TSV under a name taken from its content.

    `write(path)` encodes it under a working name, renamed once the fingerprint
    of the result is known.
    """
    draft = out_dir / f".kotogen_{os.getpid()}_{rank:02d}{suffix}"
    try:
        write(draft)
        dest = out_dir / (f"{audio_files._readable(source.stem)}_{rank:02d}_"
                          f"{audio_files.fingerprint(draft)}{suffix}")
        # Not `rename`, which Windows refuses over an existing target: a second
        # pass over the same audio finds it, holding the same bytes.
        os.replace(draft, dest)
    finally:
        # ffmpeg may still hold the draft after a Ctrl+C on Windows (WinError 32):
        # its PermissionError would replace the KeyboardInterrupt.
        with contextlib.suppress(OSError):
            draft.unlink(missing_ok=True)
    return dest


def _extract_span(source: Path, block, rank: int, out_dir: Path, level) -> Path:
    """Writes the mp3 of a passage beside the TSV, and hands back its path."""
    from kotogen.generators import nhk as nhk_gen  # late import (avoids a cycle)

    return _write_extract(
        source, out_dir, rank, ".mp3",
        lambda dest: nhk_gen.transcode_spans_to_mp3(source, dest, block.spans(), level))


def _extract_clip(video: Path, block, rank: int, out_dir: Path) -> Path:
    """Writes the WebM clip of a passage beside the TSV, and hands back its path.

    Cut from the original video, at the instants of its sound track. The track
    is chosen again here, at the cost of one ffprobe, so a clip cannot carry a
    track the transcription did not hear.
    """
    from kotogen.generators import nhk as nhk_gen  # late import (avoids a cycle)

    chosen = nhk_gen.japanese_track(nhk_gen.probe_audio_tracks(video))
    return _write_extract(
        video, out_dir, rank, video_clip.SUFFIX,
        lambda dest: nhk_gen.transcode_spans_to_clip(video, dest, block.spans(),
                                                     chosen))


def _copy_whole(source: Path, out_dir: Path) -> Path:
    """Copies a file handled whole under a name taken from its content.

    The user's file keeps its name, which would collide in collection.media
    (`01.mp3`): the copy carries the fingerprint. Nothing is re-encoded.
    """
    dest = out_dir / (f"{audio_files._readable(source.stem)}_"
                      f"{audio_files.fingerprint(source)}{source.suffix.lower()}")
    if dest.resolve() != source.resolve():
        shutil.copy2(source, dest)
    return dest


def _generate_for_block(client: AIClient, args, source: Path, block, rank: int,
                        split, segments: list[Segment], out_dir: Path,
                        out_path, media_files: list[Path],
                        origin: str | Path = "", link: str = "",
                        figure: Path | None = None,
                        video: Path | None = None,
                        choice: bool = False,
                        level: str = "") -> list[dict] | None:
    """Cards drawn from one passage: media extraction, AI call, write to the TSV.

    A file not split comes as its single block, its sound copied, not
    re-encoded. `origin` names the source of the cards (the file, or a podcast
    episode's label), `source` failing it; `link` reopens this passage where the
    source allows (a YouTube video, at its second). `video` is the file the clip
    is cut from when its picture was asked for, `source` staying the sound track
    and the fallback. `choice` caps the passage at its one question; `level`,
    the source's own when it says one (`_set_level`), overrides `--level`.
    None, unlike an empty list, means the passage broke (its extraction or the
    call): a file with no card is then kept out of the history.
    """
    from kotogen.generators import (
        nhk as nhk_gen,  # late import (avoids a cycle)
        sources,
    )

    level = level or args.level
    total = len(split.blocks)
    max_duration = nhk_gen.max_duration_seconds(args)
    # --max-duration bounds each passage, not only an NHK article.
    if max_duration and round(block.duration) > round(max_duration):
        console.aside(_("passage {rank}/{total}: {duration}, beyond {limit}").format(
            rank=rank, total=total,
            duration=nhk_gen.format_duration(block.duration),
            limit=nhk_gen.format_duration(max_duration)))
        return []

    # The clip first: when it works no mp3 is made, as the card plays one media
    # and the other would sit unused in the media library.
    clip = None
    if video is not None:
        # A passage too long for a clip falls back to sound alone, silently:
        # a bound, not an incident.
        if block.duration <= video_clip.MAX_SECONDS:
            try:
                clip = _extract_clip(video, block, rank, out_dir)
            except Exception as exc:
                # Falls back on the sound, which always extracts.
                console.failed(_("passage {rank}/{total}, picture dropped: "
                                 "{reason}").format(rank=rank, total=total, reason=exc))

    try:
        media = clip or (_copy_whole(source, out_dir) if split.whole
                         else _extract_span(source, block, rank, out_dir,
                                            audio_quality.resolve(args)))
    except Exception as exc:
        console.failed(_("passage {rank}/{total}, extraction impossible: "
                         "{reason}").format(rank=rank, total=total, reason=exc))
        return None
    # A pass replayed over its own output finds the user's file already under
    # our name: the clean-up below must spare it.
    ours = media.resolve() != source.resolve()

    # --count is a cap, never a target; by default the passage's length sets it.
    lines = block.texts(segments)
    limit = 1 if choice else quota.resolve(args.count, lines)
    # The bounds show when the passage is handled, not in the split's summary.
    bounds = "" if split.one_piece else (
        f"{audio_split.timestamp(block.start)} → {audio_split.timestamp(block.end)}")
    where = _("passage {rank}/{total}, {bounds}").format(
        rank=rank, total=total, bounds=bounds) if bounds else ""
    console.action(quota.announce(), among=where)
    # The bounds go in the Source too, or a collection's extracts would all
    # point at the same file.
    provenance = sources.provenance(origin or source, bounds, link)
    result = None
    asked = limit
    retried = False
    while True:
        try:
            result = _generate_for_audio(client, media.name, lines, asked,
                                         level, choice, figure=figure)
        except AIAuthError:
            console.close_line()   # the line does not stay open behind us
            raise
        except AITruncatedError:
            # The one failure with a known fix: ask for half as many cards. One
            # retry only; more would be paid for guessing.
            if retried or asked <= 1:
                console.done(_("given up"))
                break
            retried = True
            asked = max(1, asked // 2)
            console.extend(_("retried shorter"))
        except Exception as exc:
            console.done(_("failed: {reason}").format(reason=console.reason(exc)))
            break
        else:
            break

    cards = []
    if result is not None:
        cards = quota.enforce(
            _post_process(result, media.name, media.stem, level, provenance,
                          segments=segments, block=block, whole=split.whole,
                          figure=figure.name if figure else "",
                          is_video=clip is not None, choice=choice),
            asked)

    if result is not None:
        console.done(f"{len(cards)} {console.plural(len(cards), 'card')}")

    if cards:
        append_cards(out_path, cards, FIELDS, args.deck, args.notetype)
        media_files.append(media)
        # A figure may serve every passage of a file: listed once, and only
        # when a card shows it.
        if (figure and figure not in media_files
                and any(card["Image"] for card in cards)):
            media_files.append(figure)
    elif ours:
        # Nothing points at it any more; the user's own file is spared (`ours`).
        media.unlink(missing_ok=True)
    return None if result is None else cards


# ── Public entry point ────────────────────────────────────────────────────────

# Defaults of `--latest` by source (`default=None` on the CLI side): an NHK Easy
# article lasts two minutes, a podcast episode costs minutes of Whisper.
LATEST_NHK = 4
LATEST_PODCAST = 1
# A video costs what a podcast episode does.
LATEST_YOUTUBE = 1
# A lesson already gives eight to ten dialogues, and as many cards.
LATEST_IRODORI = 1
# A reading lasts from thirty seconds to two and a half hours.
LATEST_ROUDOKU = 1


def _latest(args: argparse.Namespace, default: int) -> int:
    return default if getattr(args, "latest", None) is None else args.latest


def _podcast_episodes(entries: list[str], count: int,
                      number: int | None = None) -> list[tuple]:
    """Podcast entries → downloaded episodes: [(file, feed, episode)].

    Without a number, the last `count` episodes not yet handled; with one, the
    `count` episodes from it, history ignored. A feed unreachable or empty is
    said and skipped.
    """
    from kotogen.generators import (
        nhk as nhk_gen,  # late import (avoids a cycle)
        podcast,
    )

    downloaded: list[tuple] = []
    for entry in entries:
        try:
            feed = podcast.resolve(entry)
        except Exception as exc:
            console.title(entry)
            console.failed(str(exc))
            continue
        # Titled by the show's name (from the catalogue, or a URL's host), not by
        # what was typed.
        console.title(feed.name)
        console.action(_("Reading the feed"))
        try:
            if number is None:
                name, episodes, skipped = podcast.latest(feed, count)
            else:
                # A number typed by hand ignores the history: nothing is skipped.
                name, episodes = podcast.from_number(feed, number, count)
                skipped = 0
        except Exception as exc:
            console.failed(str(exc))
            continue
        # The feed's own name, when it differs from the catalogue's.
        found = (f"{name}, " if name and name != feed.name else "")
        found += (f"{len(episodes)} {console.plural(len(episodes), 'episode')}"
                  if episodes else _("no new episode"))
        if skipped:
            found += agreed(skipped, ", {count} already handled",
                            "episode").format(count=skipped)
        console.done(found)
        if not episodes:
            continue
        console.items([
            f"{e.title or e.guid}"
            + (f" ({nhk_gen.format_duration(e.duration)})" if e.duration else "")
            for e in episodes])

        console.action(_("Downloading the episodes"), margin=True)
        got: list = []
        for episode in episodes:
            try:
                path = podcast.fetch(feed, episode)
            except Exception as exc:
                console.failed(f"{episode.title or episode.guid}{convention('colon', ': ')}{exc}")
                continue
            got.append(path)
            downloaded.append((path, feed, episode))
        console.done(_("{count} {files}, {size}").format(
            count=len(got), files=console.plural(len(got), "file"),
            size=console.size_of(got)) if got else _("no file"))
    return downloaded


def _jlpt_sections(entries: list[str], count: int) -> list[tuple]:
    """`jlpt-nX` entries → downloaded listening sections: [(file, target, track)].

    Every section by default, as an exam is sat whole: `count` only takes fewer.
    A collection that cannot be reached is said and skipped.
    """
    from kotogen.generators import jlpt_papers

    downloaded: list[tuple] = []
    for entry in entries:
        try:
            target = jlpt_papers.resolve(entry)
        except Exception as exc:
            console.title(entry)
            console.failed(str(exc))
            continue
        console.title(target.name)
        remaining, done = jlpt_papers.tracks(target)
        if count:
            remaining = remaining[:count]
        # A line only for what the list below cannot show: nothing new, or how
        # many were already handled.
        if done or not remaining:
            found = (f"{len(remaining)} {console.plural(len(remaining), 'section')}"
                     if remaining else _("no new section"))
            if done:
                found += agreed(done, ", {count} already handled",
                                "section").format(count=done)
            console.item(found)
        if not remaining:
            continue
        console.items([track.name for track in remaining])

        console.action(_("Downloading the sections"), margin=True)
        got: list = []
        for track in remaining:
            try:
                path = jlpt_papers.fetch(target, track)
            except Exception as exc:
                console.failed(f"{track.name}{convention('colon', ': ')}{exc}")
                continue
            got.append(path)
            downloaded.append((path, target, track))
        console.done(_("{count} {files}, {size}").format(
            count=len(got), files=console.plural(len(got), "file"),
            size=console.size_of(got)) if got else _("no file"))
    return downloaded


def _irodori_lessons(entries: list[str], count: int,
                     number: int | None = None) -> list[tuple]:
    """`irodori-…` entries → downloaded dialogues: [(file, lesson, file)].

    The lesson is the unit of the history and carries the provenance, so each
    dialogue's item is its own file. Without a number, the first lessons not
    yet done: a textbook goes in order.
    """
    from kotogen.generators import irodori

    downloaded: list[tuple] = []
    for entry in entries:
        try:
            volume = irodori.resolve(entry)
        except Exception as exc:
            console.title(entry)
            console.failed(str(exc))
            continue
        console.title(volume.name)
        try:
            lessons, done = irodori.lessons(volume, count, from_lesson=number)
        except Exception as exc:
            console.failed(str(exc))
            continue
        # Said only when the list does not show it, as for the past papers.
        if done or not lessons:
            found = (f"{len(lessons)} {console.plural(len(lessons), 'lesson')}"
                     if lessons else _("no new lesson"))
            if done:
                found += agreed(done, ", {count} already handled",
                                "lesson").format(count=done)
            console.item(found)
        if not lessons:
            continue
        console.items([f"{lesson.name} ({lesson.theme})" if lesson.theme else lesson.name
                       for lesson in lessons])

        console.action(_("Downloading the dialogues"), margin=True)
        got: list = []
        for lesson in lessons:
            try:
                files = irodori.fetch(lesson)
            except Exception as exc:
                console.failed(f"{lesson.name}{convention('colon', ': ')}{exc}")
                continue
            got.extend(files)
            downloaded.extend((path, lesson, path) for path in files)
        console.done(_("{count} {dialogues}, {size}").format(
            count=len(got), dialogues=console.plural(len(got), "dialogue"),
            size=console.size_of(got)) if got else _("no dialogue"))
    return downloaded


def _roudoku_readings(entries: list[str], count: int,
                      limit: float | None = None) -> list[tuple]:
    """`roudoku` entries → downloaded readings: [(file, library, reading)].

    Shortest first: the library is a progression (see `aozora_roudoku`).
    `--max-duration` (`limit`) applies before the download, the catalogue giving
    each duration.
    """
    from kotogen.generators import aozora_roudoku as roudoku, nhk as nhk_gen

    downloaded: list[tuple] = []
    for entry in entries:
        library, wanted = roudoku.resolve(entry)
        console.title(library.name)
        if wanted is not None:
            readings, done, dropped = [wanted], 0, 0
        else:
            console.action(_("Reading the catalogue"))
            readings, done, dropped = roudoku.to_do(count, limit=limit)
            found = (f"{len(readings)} {console.plural(len(readings), 'reading')}"
                     if readings else _("no new reading"))
            if done:
                found += agreed(done, ", {count} already handled",
                                "reading").format(count=done)
            if dropped:
                found += agreed(dropped, ", {count} too long",
                                "reading").format(count=dropped)
            console.done(found)
        if not readings:
            continue
        console.items([
            f"{reading.label}"
            + (f" ({nhk_gen.format_duration(reading.duration)})"
               if reading.duration else "")
            for reading in readings])

        console.action(_("Downloading the readings"), margin=True)
        got: list = []
        for reading in readings:
            try:
                path = roudoku.fetch(library, reading)
            except Exception as exc:
                console.failed(f"{reading.title}{convention('colon', ': ')}{exc}")
                continue
            got.append(path)
            downloaded.append((path, library, reading))
        console.done(_("{count} {files}, {size}").format(
            count=len(got), files=console.plural(len(got), "file"),
            size=console.size_of(got)) if got else _("no file"))
    return downloaded


def _youtube_videos(entries: list[str], count: int, *, image: bool,
                    limit: float | None = None) -> list[tuple]:
    """YouTube entries → downloaded videos: [(file, source, info)].

    Candidates are probed until `count` are kept, not truncated beforehand: a
    fresh Short must not hide the latest video. One whose sound is not
    Japanese, too short, or longer than `--max-video` (`limit`) is dropped
    before the download, on stdout: a sort, not a breakdown. A source that
    cannot be reached is said and skipped.
    """
    from kotogen.generators import (
        nhk as nhk_gen,  # late import (avoids a cycle)
        youtube,
    )

    downloaded: list[tuple] = []
    for entry in entries:
        try:
            source = youtube.resolve(entry)
        except Exception as exc:
            console.title(entry)
            console.failed(str(exc))
            continue
        console.title(source.name)
        console.action(_("Probing the videos"))
        try:
            name, candidates, skipped = youtube.candidates(source)
        except Exception as exc:
            console.failed(str(exc))
            continue

        # The probe says what a candidate is, its language, and whether its
        # transcription is done; the batch kept is listed once final.
        kept: list[tuple] = []
        dropped: list[str] = []
        for video in candidates:
            if len(kept) >= count:
                break
            try:
                info = youtube.probe(video)
            except Exception as exc:
                console.failed(str(exc))
                continue
            title = info.title or info.id
            duration = nhk_gen.format_duration(info.duration) if info.duration else "?"
            if not youtube.japanese_sound(info):
                # A manual Japanese track over a sound that is not Japanese: the
                # card would have its audio and its back in two languages.
                dropped.append(_("{title}: sound in {language}, not in Japanese")
                               .format(title=title, language=info.language))
                continue
            if info.duration and info.duration < youtube.MIN_DURATION:
                # A Short, almost always: a channel's feed mixes them in with
                # the videos without telling them apart.
                dropped.append(_("{title}: {duration}, too short for a card")
                               .format(title=title, duration=duration))
                continue
            if limit and info.duration and info.duration > limit:
                dropped.append(_("{title}: {duration}, longer than {limit}").format(
                    title=title, duration=duration,
                    limit=nhk_gen.format_duration(limit)))
                continue
            kept.append((info, title, duration))

        found = (f"{name}, " if name and name != source.name else "")
        found += (agreed(len(kept), "{count} kept", "video").format(count=len(kept))
                  if kept else _("no new video"))
        if skipped:
            found += agreed(skipped, ", {count} already handled",
                            "video").format(count=skipped)
        if dropped:
            found += agreed(len(dropped), ", {count} dropped",
                            "video").format(count=len(dropped))
        console.done(found)
        console.items([
            # Subtitles or not, said before the download: of what the probe
            # finds, it alone changes what the pass costs.
            f"{title} ({duration}, "
            + (_("Japanese subtitles provided") if info.ja_subtitle
               else _("transcription to be done")) + ")"
            for info, title, duration in kept])
        for reason in dropped:
            console.aside(reason)
        if not kept:
            continue

        console.action(_("Downloading the videos"), margin=True)
        got: list = []
        for info, title, _duration in kept:
            try:
                path = youtube.fetch(source, info, image=image)
            except Exception as exc:
                console.failed(f"{title}{convention('colon', ': ')}{exc}")
                continue
            got.append(path)
            downloaded.append((path, source, info))
        console.done(_("{count} {files}, {size}").format(
            count=len(got), files=console.plural(len(got), "file"),
            size=console.size_of(got)) if got else _("no file"))
    return downloaded


def run_audio(args: argparse.Namespace) -> None:
    from kotogen.generators import (
        nhk as nhk_gen,  # late import (avoids a cycle)
        podcast,
        sources,
        youtube,
    )

    # A PDF is refused by name, rather than as an invalid audio file.
    if any(sources.is_pdf(i) for i in args.inputs):
        sys.exit(_(
            "A PDF document holds no audio: listening cards need an audio file "
            "or an NHK article.\n"
            "For a PDF, use: kotogen vocab / reading <file.pdf>"
        ))

    # Each predicate refuses the routes of the others by itself, or an NHK
    # article or a video URL would reach the RSS parser.
    want_latest = any(i.strip().lower() == "nhk" for i in args.inputs)
    youtube_entries = [i for i in args.inputs if sources.is_youtube(i)]
    podcast_entries = [i for i in args.inputs if sources.is_podcast(i)]
    jlpt_entries = [i for i in args.inputs if sources.is_jlpt(i)]
    irodori_entries = [i for i in args.inputs if sources.is_irodori(i)]
    roudoku_entries = [i for i in args.inputs if sources.is_roudoku(i)]
    # A local path is whatever no remote route recognises: "./season1" and
    # "K23_01.mp3" have no shape in common.
    remote_kinds = (sources.is_nhk, sources.is_podcast, sources.is_youtube,
                    sources.is_jlpt, sources.is_irodori, sources.is_roudoku)
    paths = [Path(i) for i in args.inputs
             if not any(recognises(i) for recognises in remote_kinds)]
    files = audio_files._collect_audio_files(paths) if paths else []
    # What a folder already gave cards for is left out (see `_files_to_do`).
    files, already_done = audio_files._files_to_do(files, paths,
                                                   getattr(args, "latest", None))

    urls = sources.nhk_urls(args.inputs, _latest(args, LATEST_NHK), "audio")
    remote_entries = (podcast_entries or youtube_entries or jlpt_entries
                      or irodori_entries or roudoku_entries)
    if want_latest and not urls and not files and not remote_entries:
        console.title(sources.no_news())
        return

    if already_done and not urls and not files and not remote_entries:
        # A folder worked through, told apart from one where nothing was found.
        console.title(_("Nothing new in there: every file of these folders has "
                        "already been handled (name a file to do it again)."))
        return

    if not urls and not files and not remote_entries:
        sys.exit(_("No NHK URL, YouTube channel, podcast, past paper, lesson or "
                   "audio file to handle."))

    # `--episode` counts from the first episode published, which a YouTube feed
    # does not reach; refused rather than ignored.
    if youtube_entries and getattr(args, "episode", None) is not None:
        sys.exit(_(
            "--episode does not apply to YouTube: a channel's feed carries only "
            "its last fifteen videos, with no archive, and a number there would "
            "designate another video at every publication.\n"
            "   Use --latest N for the N most recent, or paste the URL of the "
            "video you want."
        ))

    # Nor are the past papers and 青空朗読 numbered (see the message); いろどり
    # keeps `--episode`, as its lesson 7 stays lesson 7.
    if (jlpt_entries or roudoku_entries) and getattr(args, "episode", None) is not None:
        sys.exit(_(
            "--episode applies neither to the official past papers nor to 青空朗読: "
            "a collection has only its few sections, and the library of readings "
            "is filed by duration, not by rank.\n"
            "   Use --latest N, or --max-duration to bound the duration."
        ))

    client = AIClient(provider=args.provider, model=args.model)
    out_path = resolve_output_path(args, "audio")
    out_dir = out_path.parent
    whisper_models: dict = {}
    media_files: list[Path] = []
    # Working folder for the transcriptions, deleted at the end. Opened before
    # the NHK loop: an article's audio is transcribed to cross-check its text,
    # and cached there too.
    work_dir = Path(tempfile.mkdtemp(prefix="kotogen_transcriptions_"))

    # Settled before any download: it decides whether a YouTube video comes
    # whole or as its sound track, and the "ask" mode asks only when a picture
    # is in play (a YouTube entry, or a local file by its suffix).
    keep_image = video_clip.resolve(args, in_play=bool(youtube_entries) or any(
        f.suffix.lower() in audio_files.VIDEO_EXTENSIONS for f in files))

    # A downloaded file then goes the way of a local one, its source module beside
    # it: each exposes `provenance`, `link`, `cache_folder`, `mark_done` and
    # `cleanup`, so what follows knows nothing of the sources.
    remote: dict[Path, tuple] = {}
    if youtube_entries:
        for path, source, info in _youtube_videos(
                youtube_entries, _latest(args, LATEST_YOUTUBE),
                image=keep_image,
                limit=getattr(args, "max_video", None)):
            remote[path] = (youtube, source, info)
            files.append(path)
    if podcast_entries:
        for path, feed, episode in _podcast_episodes(
                podcast_entries, _latest(args, LATEST_PODCAST),
                getattr(args, "episode", None)):
            remote[path] = (podcast, feed, episode)
            files.append(path)
    if jlpt_entries:
        from kotogen.generators import jlpt_papers
        for path, target, track in _jlpt_sections(
                jlpt_entries, getattr(args, "latest", None) or 0):
            remote[path] = (jlpt_papers, target, track)
            files.append(path)
    if irodori_entries:
        from kotogen.generators import irodori
        for path, lesson, item in _irodori_lessons(
                irodori_entries, _latest(args, LATEST_IRODORI),
                getattr(args, "episode", None)):
            remote[path] = (irodori, lesson, item)
            files.append(path)
    if roudoku_entries:
        from kotogen.generators import aozora_roudoku
        for path, library, reading in _roudoku_readings(
                roudoku_entries, _latest(args, LATEST_ROUDOKU),
                nhk_gen.max_duration_seconds(args)):
            remote[path] = (aozora_roudoku, library, reading)
            files.append(path)
    if remote_entries and not urls and not files:
        # Silent on purpose: each entry has already said why it gave nothing.
        return

    all_cards: list[dict] = []
    skipped_long = 0  # articles dropped by --max-duration
    refused = 0  # local files without a single usable passage
    failures = 0  # files that hit a breakdown (track, transcription, split): not a verdict
    booklets: dict = {}   # past-paper booklets already read, by path

    # ── NHK articles (URL) ────────────────────────────────────────────────────
    for n, url in enumerate(urls, 1):
        console.rank(n, len(urls), nhk_gen.article_id(url))
        try:
            cards, audio_path = nhk_gen.generate_for_url(
                url, args, client, out_dir, work_dir, whisper_models)
        except AIAuthError:
            raise  # key/quota: the following articles would all fail the same
        except nhk_gen.AudioTooLong as exc:
            # A sort, not a breakdown: on stdout, and not marked as handled, for
            # another limit to take up.
            console.aside(str(exc))
            skipped_long += 1
            continue
        except Exception as exc:
            console.failed(str(exc))
            continue
        if cards:
            append_cards(out_path, cards, FIELDS, args.deck, args.notetype)
            if audio_path:
                media_files.append(audio_path)
        all_cards.extend(cards)
        console.done(f"{len(cards)} {console.plural(len(cards), 'card')}")

    if skipped_long:
        # Said, or `--latest 4` giving 2 articles would look like a bug.
        console.title(counted(skipped_long,
                              "{count} article dropped: audio longer than {limit}.",
                              "{count} articles dropped: audio longer than {limit}.")
                      .format(count=skipped_long,
                              limit=nhk_gen.format_duration(
                                  nhk_gen.max_duration_seconds(args))))

    # Local files are listed as a source, downloaded ones already were under
    # theirs; what the history left out is said before the exit below.
    local = [f for f in files if f not in remote]
    if local or already_done:
        console.title(_("Audio files"))
        console.items([audio_files._label(f, paths) for f in local])
    if already_done:
        console.item(counted(already_done,
                             "{count} file already handled, left out",
                             "{count} files already handled, left out")
                     .format(count=already_done))

    if not files:
        shutil.rmtree(work_dir, ignore_errors=True)
        _finish_audio(all_cards, out_path, media_files, args, refused)
        return

    try:
        for n, audio in enumerate(files, 1):
            console.rank(n, len(files), audio_files._label(audio, paths))

            # A video's sound track is what gets transcribed, split and used as
            # media; with the picture kept, each passage is cut from the video.
            track = audio
            source_video = None
            if audio.suffix.lower() in audio_files.VIDEO_EXTENSIONS:
                console.action(_("Extracting the sound track"))
                try:
                    track, chosen = audio_files._extract_track(audio, work_dir,
                                                               audio_quality.resolve(args))
                except Exception as exc:
                    console.failed(_("sound track cannot be extracted: {reason}")
                                   .format(reason=exc))
                    failures += 1
                    continue
                # Says what the cards will carry, not the temporary track's name:
                # a picture left aside (`KOTOGEN_VIDEO=never`) is said here.
                if keep_image:
                    source_video = audio
                image = (_("the picture is kept") if keep_image
                         else _("the picture is left aside"))
                console.done(f"{chosen}, {image}" if chosen else image)

            # A subtitle beside the file is a free transcription, more faithful
            # than Whisper. Looked for beside the original, not the extracted
            # track in its temporary folder.
            subtitle = subtitles.load(audio)
            for dropped, reason in subtitle.rejected:
                console.aside(_("subtitle {name} ignored: {reason}").format(
                    name=dropped.name, reason=_(reason)))

            segments = list(subtitle.segments)
            if segments:
                console.action(_("Reading the subtitle"))
                console.done(f"{len(segments)} "
                             f"{console.plural(len(segments), 'utterance')}")

            if not segments:
                # A downloaded file's transcript goes in its source's cache, filed
                # under the medium: a replay with other settings reuses minutes.
                folder = (remote[audio][0].cache_folder(remote[audio][1])
                          if audio in remote else work_dir)
                try:
                    segments = whisper._transcribe(track, args.whisper_model,
                                                   whisper_models, folder,
                                                   source=audio)
                except Exception as exc:
                    console.failed(_("transcription impossible: {reason}")
                                   .format(reason=console.reason(exc)))
                    failures += 1
                    continue
            if not segments:
                # A verdict, like a split with no passage: the empty transcript is
                # filed, and offered again the file would hold `--latest 1` on it.
                console.aside(_("transcription empty, file ignored."))
                refused += 1
                audio_files._mark_handled(audio, remote, paths)
                continue

            # A collection (past-paper conversations, textbook exchanges) is cut
            # into passages; an ordinary file stays one block, minus the number
            # a textbook track may open on.
            console.action(_("Splitting"))
            try:
                split = audio_split.split_audio(client, track, segments,
                                                active=getattr(args, "split", True),
                                                limit=nhk_gen.max_duration_seconds(args))
            except AIAuthError:
                console.close_line()
                raise
            except Exception as exc:
                # Not retried by the split: a breakdown of this file, not of the run.
                console.failed(_("cannot split, file turned down: {reason}").format(
                    reason=console.reason(exc)))
                failures += 1
                continue
            audio_split.show(split)
            if split.kind == audio_split.KIND_FAILED:
                # A breakdown, kept apart from the refusals, for which "no card"
                # is a good result. The split has said it on stderr.
                failures += 1
                continue
            if not split.blocks:
                refused += 1  # the summary of the split has already said it
                # A verdict on the file, not a breakdown: offered again, it would
                # cost its splitting at every run and hold `--latest 1` on it.
                audio_files._mark_handled(audio, remote, paths)
                continue

            # Not said: they only decide whether the file counts as handled.
            file_cards = 0
            broken = False
            # A downloaded file is named by its source's label, its own name
            # being a cache key; `link_for` reopens a passage where the source
            # can (a YouTube URL, at the second).
            link_for = None
            if audio in remote:
                module, remote_source, item = remote[audio]
                origin = module.provenance(remote_source, item)
                link_for = partial(module.link, remote_source, item)
            else:
                origin = audio_files._label(audio, paths)
            # A figure belongs to the exercise: a file that is one shares it with
            # all its passages, and a section's passages each name theirs.
            file_figure = audio_files._exam_figure(client, audio, booklets, out_dir)
            level = audio_files._set_level(audio, remote.get(audio))
            for rank, block in enumerate(split.blocks, 1):
                figure = file_figure or audio_files._passage_figure(
                    client, remote.get(audio), block, booklets, out_dir)
                choice = audio_files._is_choice(audio, remote.get(audio),
                                                block.texts(segments))
                cards = _generate_for_block(
                    client, args, track, block, rank, split, segments, out_dir,
                    out_path, media_files, origin,
                    link_for(block.start) if link_for else "",
                    figure, source_video, choice, level)
                if cards is None:
                    broken = True  # the passage's line has said why
                    continue
                all_cards.extend(cards)
                file_cards += len(cards)
            # Each passage has said its count, and the total comes at the end.
            # A file with no card is handled all the same, as above, unless a
            # passage broke: a failed call says nothing of the file.
            if file_cards or not broken:
                audio_files._mark_handled(audio, remote, paths)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        for module, remote_source, _item in remote.values():
            module.cleanup(remote_source)

    _finish_audio(all_cards, out_path, media_files, args, refused, failures)


def _finish_audio(all_cards: list[dict], out_path, media_files: list[Path], args,
                  refused: int = 0, failures: int = 0) -> None:
    """Summary, preview, media installed into Anki, and AnkiConnect send."""
    if failures:
        # Said even when other files gave cards, or a dropped file goes unseen.
        console.space()
        print(counted(failures,
                      "{count} file dropped on a breakdown (reason above).",
                      "{count} files dropped on a breakdown (reason above).")
              .format(count=failures), file=sys.stderr)
    if not all_cards:
        if refused:
            # A refusal is not a breakdown: a shadowing book has nothing to ask
            # about, so "no card" exits cleanly, on stdout.
            console.title(_("No card: these audio files carry no comprehension to "
                            "check (shadowing sentences, instructions, extracts "
                            "too short)."))
            return
        sys.exit(_("No card generated."))

    # "audio" would be wrong under a pass that dropped video clips, on the line
    # that says what to copy by hand when the cards are not sent.
    label = ("media" if any(p.suffix.lower() in audio_files.VIDEO_EXTENSIONS for p in media_files)
             else "audio")
    finish(all_cards, FIELDS, args, out_path, media=media_files,
           media_label=label, preview=quota.preview)
