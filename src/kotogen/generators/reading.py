"""Reading comprehension card generator (Japanese text -> questions about it).

A card reads as text (the `Text` field, furigana hidden by default) or as a
mini-book (pages as images in `Images`, `Text` left empty); a past paper's
composed document (a poster, a table) is cut out as an image and keeps its
transcription for the back. The source decides which: a PDF is measured
(`pdf_pages.read_mode`), and `--read-as text|book` forces it. The AI writes the
questions in the language of the cards (`all.lang`), always with four options:
how many the card shows is a template setting.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import urllib.parse
from collections.abc import Sequence
from pathlib import Path

from kotogen import console, memory, prompts, proofreading
from kotogen.ai_client import AIAuthError, AIClient
from kotogen.exporter import append_cards, cache_dir, finish, resolve_output_path, short
from kotogen.generators import key_line, passages, pdf_source, quota
from kotogen.i18n import _, agreed, convention, counted, listed, quoted
from kotogen.jlpt import LEVELS as JLPT_LEVELS

FIELDS = [
    "ID",
    "Text",
    "Images",
    "Question",
    "Decoy1",
    "Decoy2",
    "Decoy3",
    "Answer",
    # The translation of the `Text` field, matched line by line by RANK as on the
    # listening card; the back lays it under each sentence, behind a switch.
    "Translation",
    # Rank (from 1) of the `Text` line supporting the answer, which the back
    # highlights. Not a marker inside the `Text` as on the listening card: the
    # text is on the FRONT, and the marker would show where to look.
    "KeyLine",
    # `KeyLine` for a mini-book: the page the answer is read on, where the back
    # opens the book (`key_line.page`). Empty on a card that carries its text.
    "KeyPage",
    "Source",
]

# Spending ceiling on ONE source: one AI call per passage, and a chapter of
# twenty thousand characters would make eighty. `--passages` takes more.
PASSAGES_MAX = 6


# ── Identifier of a card ──────────────────────────────────────────────────────

# The ID, first field of the note type, is what Anki compares to refuse a
# duplicate. Drawn from the MATTER READ rather than the time, so that a rerun on
# the same text gives the same IDs. The length of the media fingerprints
# (`kotogen.generators.audio_files`, `pdf_pages.digest`).
FINGERPRINT_LEN = 8


def _fingerprint(matter: str) -> str:
    """Short fingerprint of the matter read, which gives its cards their identity.

    The images when the card carries any, the text otherwise: a composed document
    has both, and its transcription varies between passes where image names do not.
    """
    return hashlib.sha256(matter.encode("utf-8")).hexdigest()[:FINGERPRINT_LEN]


# The ID also carries a readable part of its source before the fingerprint, as a
# listening card's carries its medium, to be recognised in the Anki browser.
# Capped like the media names (`audio_files.READABLE_MAX`): a label can be a sentence.
READABLE_MAX = 40

# What `sources.provenance` adds to locate the passage IN its source -
# "(passage 2/6)", "(pages 12-18)". Dropped from the name: the rank is already in
# the ID, and the page range is found again in the fingerprint.
_DETAIL_RE = re.compile(r"\s*\([^()]*\)\s*$")
_EXTENSION_RE = re.compile(r"\.[A-Za-z0-9]{1,4}$")


def _name(source: str) -> str:
    """The readable part of the ID: enough to recognise the source at a glance.

    Drawn from the `Source` field; of a URL, the host and the last part of the
    path, which name the article (`nhk_or_jp_k10014837511000`). An empty string
    when nothing names the source, and the ID then has no name part.
    """
    source = _DETAIL_RE.sub("", (source or "").strip())
    if source.lower().startswith(("http://", "https://")):
        address = urllib.parse.urlsplit(source)
        host = re.sub(r"^www\d*\.", "", address.hostname or "")
        page = _EXTENSION_RE.sub("", Path(address.path.rstrip("/")).name)
        source = f"{host} {page}"
    else:
        source = _EXTENSION_RE.sub("", source)
    # As in the media names, Japanese stays (`isalnum` accepts it): "第3回".
    clean = "".join(c if (c.isalnum() or c in "-_") else "_" for c in source)
    return re.sub(r"_+", "_", clean).strip("_")[:READABLE_MAX].strip("_")


# ── AI generation ─────────────────────────────────────────────────────────────

def _generate_for_text(
    client: AIClient, title: str, text_lines: list[str], limit: int, level: str,
    *, translate: bool = True, locate: bool = True,
) -> dict:
    """The AI call on ONE card text.

    `text_lines` is the text as the card carries it, TITLE INCLUDED, so that the
    ranks the model hands back (TranslationLines, KeyLine) match it. `translate`
    is false for a mini-book, which does not carry the text; `locate` still asks
    for the key line when its pages were told apart (`key_line.page`).
    """
    # Asked in the language of the cards: `prompts.say`, never `_()`.
    numbered = "\n".join(f"{i}. {line}" for i, line in enumerate(text_lines, 1))
    level_part = (
        prompts.say("Estimate the JLPT level of the text (Level field).")
        if level == "auto" else
        prompts.say("The target JLPT level is {level}.").format(level=level)
    )
    header = (prompts.say("Text \"{title}\" (its line 1 is the title):").format(title=title)
              if title else prompts.say("Text:"))
    if translate:
        translation_part = prompts.say(
            "Hand back TranslationLines: exactly {count} English line(s), "
            "one per Japanese line above, in the same order."
        ).format(count=len(text_lines))
    elif locate:
        translation_part = prompts.say(
            "This text is read as pictures: hand back no TranslationLines - the "
            "card does not carry the text, there would be nothing to lay them "
            "under. Hand back KeyLine all the same: the card opens the book at "
            "the page that line is printed on.")
    else:
        translation_part = prompts.say(
            "This text is read as pictures: hand back neither "
            "TranslationLines nor KeyLine - the card does not carry the "
            "text, there would be nothing to lay them under.")
    user_msg = (
        f"{header}\n\n{numbered}\n\n"
        f"{quota.instruction(limit)} {translation_part} {level_part}"
    )
    result = client.chat_json(prompts.load("reading_card"), user_msg)
    if not isinstance(result, dict):
        raise ValueError(_("unexpected JSON structure: {kind}").format(kind=type(result).__name__))
    return result


# ── Post-processing ───────────────────────────────────────────────────────────

def _translation(result: dict, text_lines: list[str]) -> tuple[str, str]:
    """The translation of the text, one line per Japanese line: (translation, flaw).

    The flaw, empty when all is well, is what the cards will miss; `_post_process`
    marks them with it. Lines match by RANK, so a count that does not tally drops
    the whole translation: off by one, it would read as though it were right.
    """
    f_lines = [str(l) for l in (result.get("TranslationLines") or []) if str(l).strip()]
    if not f_lines:
        return "", ""
    if len(f_lines) != len(text_lines):
        console.failed(_("translation not lined up ({given} lines vs {expected}) "
                         "- Translation field left empty.").format(
                             given=len(f_lines), expected=len(text_lines)))
        return "", proofreading.UNALIGNED_TRANSLATION
    return "\n".join(f_lines), ""


def _post_process(result: dict, text_lines: list[str], level_arg: str,
                  images: str = "", source: str = "",
                  text_on_back: bool = False,
                  page_of_line: Sequence[int] = ()) -> list[dict]:
    """Builds the final cards: shared text, translation, decoys, `Level` tags.

    The answer has its own field, never among the decoys: the card shuffles them
    at display time. `images` (mini-book) leaves `Text`, `Translation` and
    `KeyLine` empty, lest the back spell the reading out under the book, and
    `page_of_line` turns the key line into a page (`KeyPage`). `text_on_back`
    keeps a composed document's text and translation for the back.
    """
    level = level_arg if level_arg != "auto" else str(result.get("Level", "")).strip()
    if level not in JLPT_LEVELS:
        level = "N5"

    # The mini-book carries no text, a composed document does (on the back); the
    # translation and the key line follow the text.
    carries_text = not images or text_on_back
    text = "\n".join(text_lines) if carries_text else ""
    translation, flaw = (_translation(result, text_lines) if carries_text
                         else ("", ""))
    cards: list[dict] = []

    for i, raw in enumerate(result.get("Cards") or [], start=1):
        if not isinstance(raw, dict):
            console.aside(_("card {rank} skipped (question/answer missing)").format(rank=i))
            continue
        question = str(raw.get("Question", "")).strip()
        answer = str(raw.get("Answer", "")).strip()
        decoys = [str(l).strip() for l in (raw.get("Decoys") or []) if str(l).strip()]

        if not question or not answer:
            console.aside(_("card {rank} skipped (question/answer missing)").format(rank=i))
            continue

        # An `Answer` also among the decoys would show twice, giving itself away.
        duplicate = ""
        if answer in decoys:
            decoys = [l for l in decoys if l != answer]
            console.failed(_("card {rank}: the Answer also appears among the "
                             "decoys.").format(rank=i))
            duplicate = proofreading.DUPLICATED_ANSWER

        if len(decoys) > 3:
            # The note only has three decoy fields.
            console.aside(counted(len(decoys) - 3,
                                  "card {rank}: {count} decoys for 3 fields, the "
                                  "last one is dropped",
                                  "card {rank}: {count} decoys for 3 fields, the "
                                  "last {extra} are dropped").format(
                                      rank=i, count=len(decoys), extra=len(decoys) - 3))
            decoys = decoys[:3]
        elif not decoys:
            # A defect no setting can mend: kept, its answer being whole, but reported.
            console.aside(_("card {rank}: no decoy handed back, kept as an open "
                            "question").format(rank=i))
        elif len(decoys) < 3:
            console.aside(_("card {rank}: {count} {decoys} instead of 3, "
                            "{options} options at most").format(
                                rank=i, count=len(decoys),
                                decoys=console.plural(len(decoys), "decoy"),
                                options=len(decoys) + 1))

        cards.append({
            "Text": text,
            "Images": images,
            "Question": question,
            "Decoy1": decoys[0] if len(decoys) > 0 else "",
            "Decoy2": decoys[1] if len(decoys) > 1 else "",
            "Decoy3": decoys[2] if len(decoys) > 2 else "",
            "Answer": answer,
            "Translation": translation,
            "KeyLine": (key_line.rank(raw.get("KeyLine"), len(text_lines))
                         if carries_text else ""),
            "KeyPage": ("" if carries_text
                        else key_line.page(raw.get("KeyLine"), page_of_line)),
            "Source": source,
            "Tags": f"Level::{level}",
        })
        if duplicate:
            proofreading.mark(cards[-1:], proofreading.CHOICES_TAG, duplicate)

    # Laid on every card of the text, since Anki finds them card by card.
    if flaw:
        proofreading.mark(cards, proofreading.TRANSLATION_TAG, flaw)

    return cards


# ── Public entry point ────────────────────────────────────────────────────────

def _emit_passage(client: AIClient, title: str, lines: list[str],
                  args: argparse.Namespace, out_path,
                  all_cards: list[dict], images: str = "",
                  pages: int = 0, source: str = "", where: str = "",
                  text_on_back: bool = False, name: str = "",
                  page_of_line: Sequence[int] = ()) -> list[dict]:
    """Generates the cards of ONE card text, assigns the IDs and fills the TSV.

    `name` opens the ID in place of the one drawn from `source` (see
    `deck_story`). The ceiling follows this passage, already split by
    `_emit_cards`. Feeds all_cards in place; hands back the cards of the text.
    """
    limit = quota.resolve(args.count, lines, pages=pages)

    # The title opens the `Text` field of EVERY passage, which out of context
    # would not say what it is about, and is numbered with the lines.
    text_lines = [title] + lines if title else lines
    # In the page map, the title is read on the page of the first line.
    pages_of = list(page_of_line)
    if title and pages_of:
        pages_of.insert(0, pages_of[0])

    # Where it stands in its document (passage 2 of 6) goes in the action's label.
    console.action(quota.announce(), among=where)
    result = _generate_for_text(client, title, text_lines, limit, args.level,
                                translate=not images or text_on_back,
                                locate=not images or text_on_back or bool(pages_of))
    cards = quota.enforce(
        _post_process(result, text_lines, args.level, images, source,
                      text_on_back, pages_of), limit)
    # The rank counts WITHIN the text, so that a text keeps its IDs whatever was
    # handled before it; identical passages share theirs, and Anki refuses the
    # duplicate. The name is for the eye: the fingerprint makes the uniqueness.
    for i, card in enumerate(cards, start=1):
        card["ID"] = "_".join(filter(None, [
            "RC", name or _name(source),
            _fingerprint(card["Images"] or card["Text"]), f"{i:03d}"]))
    if cards:
        append_cards(out_path, cards, FIELDS, args.deck, args.notetype)
    all_cards.extend(cards)
    # The running total is given once, at the foot of the pass.
    console.done(f"{len(cards)} {console.plural(len(cards), 'card')}")
    return cards


def _kept(blocks: list[list[str]], args: argparse.Namespace,
          key: str = "") -> list[tuple[int, list[str]]]:
    """The passages really handled, the spending being announced before it is made.

    One AI call per passage, `PASSAGES_MAX` by default. On a tracked source
    (`key`), the REMAINING ones, so that a rerun moves forward (see `cursor`).
    Each passage keeps its rank in the WHOLE text, for its `Source` field.
    """
    from kotogen.generators import cursor

    if len(blocks) == 1:
        return [(1, blocks[0])]
    maximum = args.passages or PASSAGES_MAX
    from_rank = getattr(args, "from_passage", None)

    if from_rank is not None:
        # A rank typed by hand ignores the history, as `--episode` does.
        remaining, already = cursor.from_rank(blocks, from_rank), 0
    else:
        remaining, already = cursor.remaining(key, blocks)

    if not remaining:
        console.item(_("Long text: {count} passages, all already handled "
                       "(--from-passage 1 to start over)").format(count=len(blocks)))
        return []

    kept = remaining[:maximum]
    # One passage or a run of them: a matter of meaning, not of grammar, so not
    # the language's to decide.
    first, last = kept[0][0], kept[-1][0]
    bounds = (_("passage {rank}").format(rank=first) if first == last
              else _("passages {first} to {last}").format(first=first, last=last))
    where = _("{bounds} of {total}").format(bounds=bounds, total=len(blocks))
    if already:
        where += agreed(already, ", {count} already handled",
                        "passage").format(count=already)
    if len(remaining) <= maximum:
        console.item(_("Long text: {where}, one call per passage").format(where=where))
    elif key:
        console.aside(_("Long text: {where} (--passages to take more, replay for "
                        "the next batch)").format(where=where))
    else:
        # No history (a PDF's text, say): a rerun would start at the same passage.
        console.aside(_("Long text: {where} (--passages to take more, "
                        "--from-passage {next} for the next batch)").format(
                            where=where, next=last + 1))
    return kept


def _where(source: str, n: int, total: int) -> str:
    """The provenance of a passage: its source, and where one stands in it.

    In the language of the cards, as `Source` is card content, and appended the
    way `sources.provenance` appends a place: `_name` drops it from the ID and
    `known.carries` reads past it, whatever the language. A text in one piece
    keeps its provenance as it is.
    """
    from kotogen.generators import sources

    if not source or total <= 1:
        return source
    return sources.provenance(source, prompts.say("passage {rank}/{total}").format(
        rank=n, total=total))


def _emit_cards(client: AIClient, title: str, lines: list[str],
                args: argparse.Namespace, out_path,
                all_cards: list[dict], images: str = "",
                pages: int = 0, source: str = "", where: str = "",
                key: str = "", text_on_back: bool = False,
                page_of_line: Sequence[int] = ()) -> list[dict]:
    """The cards of a text, split into passages when it overflows the card.

    A text that fits in one card passes through unchanged: same cards, same IDs.
    A mini-book is never split (`--pages` bounds it), and a passage that fails
    does not stop the following ones.
    """
    if images:
        return _emit_passage(client, title, lines, args, out_path, all_cards,
                             images=images, pages=pages, source=source,
                             where=where, text_on_back=text_on_back,
                             page_of_line=page_of_line)

    from kotogen.generators import cursor

    all_blocks = passages.split(lines)
    kept = _kept(all_blocks, args, key)
    if len(all_blocks) == 1:
        return _emit_passage(client, title, kept[0][1], args, out_path,
                             all_cards, source=source, where=where)

    cards: list[dict] = []
    for rank, block in kept:
        try:
            made = _emit_passage(
                client, title, block, args, out_path, all_cards,
                source=_where(source, rank, len(all_blocks)),
                where=listed(filter(None, [
                    where, _("passage {rank}/{total}").format(
                        rank=rank, total=len(all_blocks))])))
        except AIAuthError:
            raise
        except Exception as exc:
            console.failed(console.reason(exc))
            continue
        cards += made
        # Marked only once it gave cards, so that a missed passage comes back.
        if made:
            cursor.mark(key, block, rank, len(all_blocks))
    return cards


# ── Provenance trace ──────────────────────────────────────────────────────────

def _pages_asked(spec: str | None) -> str:
    """The page range as it was asked for, for the provenance trace.

    The request rather than the indices: "p. 12-14" is what one would retype.
    Empty with no range, the whole document having served.
    """
    return f"p. {spec}" if spec else ""


# ── Mini-book (pages as images) ───────────────────────────────────────────────

def _book_pages(source: str, args: argparse.Namespace) -> tuple[str, list[Path], bytes]:
    """Prepares a reading in images: (fallback title, rendered pages, PDF).

    The PDF carries only the pages kept, so that the model reads what the card shows.
    """
    from kotogen.generators import pdf_pages

    out_dir = cache_dir() / "pages"
    if pdf_source.is_pdf_input(source):
        path = pdf_source.clean_path(source)
        data = pdf_source.load_pdf(path)
        indices = pdf_pages.parse_pages(args.pages, pdf_pages.page_count(data))
        console.action(_("Rendering the pages as images"))
        pages = pdf_pages.render_pdf(data, indices, out_dir, path.stem)
        return path.stem, pages, pdf_pages.subset(data, indices)

    files = pdf_pages.resolve_images(source)
    indices = pdf_pages.parse_pages(args.pages, len(files))
    stem = pdf_pages.clean_path(source).stem or "images"
    console.action(_("Preparing the images"))
    images = pdf_pages.render_images([files[i] for i in indices], out_dir, stem)
    # The model only reads PDFs: the images are assembled into one for the call.
    return stem, images, pdf_pages.to_pdf(images)


def _emit_book(client: AIClient, source: str, args: argparse.Namespace,
               out_path, all_cards: list[dict],
               media: list[Path], reading: pdf_source.Text | None = None,
               origin: str = "") -> None:
    """A reading as a mini-book: pages as images, questions about their content.

    `reading`: the transcription the arbitration call already handed back, so
    that the pages are not paid for twice. `origin`: the address the document was
    fetched from, which the cards keep rather than the download's name.
    """
    from kotogen.generators import pdf_pages, sources

    stem, images, document = _book_pages(source, args)
    media.extend(images)
    weight = sum(p.stat().st_size for p in images)
    console.done(_("{count} {pages}, {size} for the media library").format(
        count=len(images), pages=console.plural(len(images), "page"),
        size=console.size(weight)))

    if reading is None:
        console.action(_("The model reads the pages"))
        reading = pdf_source.extract_reading(client, document, f"{stem}.pdf", len(images))
        console.done(_("{title} - {count} {lines} of Japanese").format(
            title=short(reading.title, 45) or _("(no title)"), count=len(reading.lines),
            lines=console.plural(len(reading.lines), "line")))
    # Without the page map the cards are whole: only the jump to the answer's page
    # is lost, an aside rather than a failure.
    if len(images) > 1 and not reading.page_of_line:
        console.aside(_("pages not told apart - the back opens the book at its "
                        "first one"))
    _emit_cards(client, reading.title, reading.lines, args, out_path, all_cards,
                images=pdf_pages.images_field(images), pages=len(images),
                source=sources.provenance(origin or Path(source),
                                          _pages_asked(args.pages)),
                page_of_line=reading.page_of_line)


def _selected(pdf_bytes: bytes, spec: str | None) -> tuple[bytes, int]:
    """(subdocument of the pages kept, their number) - the whole document with no range.

    `--pages` bounds a text reading too. With no range the document goes as it
    is, and the "pdf" extra is not needed.
    """
    from kotogen.generators import pdf_pages

    if not spec:
        try:
            return pdf_bytes, pdf_pages.page_count(pdf_bytes)
        except RuntimeError:  # "pdf" extra absent: the count is only indicative
            return pdf_bytes, 0
    indices = pdf_pages.parse_pages(spec, pdf_pages.page_count(pdf_bytes))
    return pdf_pages.subset(pdf_bytes, indices), len(indices)


def _cut_out_documents(document: bytes, stem: str,
                       texts: list[pdf_source.Text],
                       media: list[Path]) -> dict[int, str]:
    """The `Images` field of the texts that are composed documents, by rank.

    Each is cut out of the page it is printed on (see `pdf_documents`). One not
    found is left out, and its card is made as text.
    """
    from kotogen.generators import pdf_documents, pdf_pages

    targeted = [(n, t) for n, t in enumerate(texts, 1) if t.document]
    if not targeted:
        return {}

    console.action(_("Cutting out the composed documents"),
                   among=f"{len(targeted)} "
                         f"{console.plural(len(targeted), 'document')}")
    found: dict[int, str] = {}
    cut: list[Path] = []
    missed: list[str] = []
    for rank, text in targeted:
        try:
            cut_out = pdf_documents.cut_out(document, text.lines)
        except Exception as exc:      # "pdf" extra absent, unreadable PDF
            console.done()
            console.failed(console.reason(exc))
            return {}
        if cut_out is None:
            missed.append(short(text.title, 30)
                          or _("text {rank}").format(rank=rank))
            continue
        page, image = cut_out
        path = pdf_pages.save_image(image, cache_dir() / "pages", stem, page)
        cut.append(path)
        media.append(path)
        found[rank] = pdf_pages.images_field([path])

    console.done(_("{found}/{total}, {size} for the media library").format(
        found=len(found), total=len(targeted), size=console.size_of(cut))
        if found else _("none", "figure"))
    for name in missed:
        # Typically a handwritten memo set as an image: no text layer to match.
        console.aside(_("{name}: page not found, the card will be made as text").format(
            name=name))
    return found


def _emit_texts(client: AIClient, texts: list[pdf_source.Text],
                args: argparse.Namespace, out_path,
                all_cards: list[dict], source: str = "",
                images: dict[int, str] | None = None) -> None:
    """The texts spotted in a document, each giving its set of cards.

    A text that fails does not stop the others, read in the same call. `images`
    holds, by rank, the cut-out document of those that have one.
    """
    images = images or {}
    for n, text in enumerate(texts, 1):
        # The text is named in the label of the action, not on a line of its own.
        where = (_("text {rank}/{total}, {title}").format(
            rank=n, total=len(texts),
            title=short(text.title, 30) or _("no title"))
            if len(texts) > 1 else "")
        try:
            _emit_cards(client, text.title, text.lines, args, out_path, all_cards,
                        images=images.get(n, ""), source=source, where=where,
                        text_on_back=bool(images.get(n)))
        except AIAuthError:
            raise
        except Exception as exc:
            console.failed(console.reason(exc))
            continue


def _emit_pdf(client: AIClient, path: Path, args: argparse.Namespace, out_path,
              all_cards: list[dict], media: list[Path],
              origin: str = "") -> None:
    """A PDF document, read as text or as a mini-book depending on what its pages carry.

    As text, the model spots and transcribes the reading texts, scans included.
    `origin`: the address the document was fetched from, when it comes from the web.
    """
    from kotogen.generators import pdf_pages, sources

    data = pdf_source.load_pdf(path)
    mode = args.read_as
    if mode == "auto":
        # An action like any other: its conclusion closes the same line.
        console.action(_("Measuring the pages"))
        mode, reason = pdf_pages.read_mode(data, args.pages)
        console.done(reason)

    if mode == "book":
        _emit_book(client, str(path), args, out_path, all_cards, media,
                   origin=origin)
        return

    document, pages = _selected(data, args.pages)
    if mode == "text":
        console.action(_("Spotting the reading texts"),
                       among=_("max {count}").format(count=args.texts) if args.texts else "")
        texts = pdf_source.extract_texts(client, document, path.name, args.texts)
        console.done(f"{len(texts)} {console.plural(len(texts), 'text')}")
    else:
        # Undecided: the same call says what the document is and transcribes it.
        console.action(_("The model reads the pages"))
        mode, texts = pdf_source.extract_mode_and_texts(client, document, path.name,
                                                        pages, args.texts)
        if mode == "book":
            console.done(_("the pages carry the reading -> mini-book"))
            _emit_book(client, str(path), args, out_path, all_cards, media,
                       reading=texts[0], origin=origin)
            return
        console.done(_("the text of the pages is enough -> {count} {texts}").format(
            count=len(texts), texts=console.plural(len(texts), "text")))

    if not texts:
        console.failed(_("no usable reading text in this document."))
        return
    # Cut from the SUBDOCUMENT sent to the model, whose pages it counts: the whole
    # PDF would shift them by the first rank of `--pages`.
    images = _cut_out_documents(document, path.stem, texts, media)
    _emit_texts(client, texts, args, out_path, all_cards,
                sources.provenance(origin or path, _pages_asked(args.pages)),
                images)


def _fetch_remote(source: str) -> tuple[Path, str, str]:
    """A remote entry -> (local PDF, name for the screen, provenance for the card).

    A textbook alias names a VOLUME, whose next lesson `irodori.lessons` picks
    from the history. A Tadoku book shows its title but leaves its address on the
    card, to be reopened; a collection or a lesson gives its name to both.
    """
    from kotogen.generators import irodori, jlpt_papers, pdf_web, sources

    if sources.is_jlpt(source):
        path, name = jlpt_papers.booklet(jlpt_papers.resolve(source))
        return path, name, name
    if sources.is_irodori(source):
        volume = irodori.resolve(source)
        lessons, _unused = irodori.lessons(volume, 1, mode="reading")
        if not lessons:
            raise RuntimeError(_("{volume}: the 18 lessons have already been "
                                 "handled in reading.").format(volume=volume.name))
        path, name = irodori.booklet(lessons[0])
        return path, name, name
    path, title = pdf_web.fetch(source)
    return path, title, source


def _mark_remote_done(entry: str) -> None:
    """Remembers that a collection or a lesson gave cards, when it is one.

    The counterpart of `pdf_web.mark_seen` for the two aliased sources, so that
    `kotogen reading irodori-shokyu1` moves forward in the textbook.
    """
    from kotogen.generators import irodori, jlpt_papers, sources

    if sources.is_jlpt(entry):
        jlpt_papers.mark_read(jlpt_papers.resolve(entry))
    elif sources.is_irodori(entry):
        volume = irodori.resolve(entry)
        lessons, _unused = irodori.lessons(volume, 1, mode="reading")
        if lessons:
            irodori.mark_done(lessons[0], mode="reading")


def _fetch_web_pdfs(inputs: list[str]) -> tuple[list[str], set[str], dict[str, str],
                                                dict[str, str], dict[str, str]]:
    """Fetches the remote documents; hands back (entries, books, origins, titles, aliases).

    `books` are the Tadoku entries, picture books with nothing to measure; any
    other PDF URL behaves like the file on disk. Keyed by local path: `origins`
    the address the cards keep, `titles` the book's name for the screen, and
    `aliases` the entry as typed, to remember the section or lesson it gave.
    """
    from kotogen.generators import pdf_web, sources

    def _is_remote(entry: str) -> bool:
        """True for anything that becomes a local PDF before the rest exists.

        A PDF or Tadoku URL, a collection of past papers, a textbook lesson: all
        fetched under one action.
        """
        return (pdf_web.is_source(entry) or sources.is_jlpt(entry)
                or sources.is_irodori(entry))

    resolved: list[str] = []
    books: set[str] = set()
    origins: dict[str, str] = {}
    titles: dict[str, str] = {}
    aliases: dict[str, str] = {}
    remote = [i for i in inputs if _is_remote(i)]
    if not remote:
        return list(inputs), books, origins, titles, aliases

    # The batch is listed whole, then fetched under a single action.
    console.title(_("Remote documents"))
    console.items(remote)
    console.action(_("Downloading"), margin=True)
    fetched: list = []
    for source in inputs:
        if not _is_remote(source):
            resolved.append(source)
            continue
        try:
            path, title, came_from = _fetch_remote(source)
        except Exception as exc:
            console.failed(f"{source}{convention('colon', ': ')}{exc}")
            continue
        as_str = str(path)
        fetched.append(path)
        resolved.append(as_str)
        origins[as_str] = came_from
        aliases[as_str] = source
        if title:
            titles[as_str] = title
        if pdf_web.is_book_url(source):
            books.add(as_str)
    console.done(_("{count} {documents}, {size}").format(
        count=len(fetched), documents=console.plural(len(fetched), "document"),
        size=console.size_of(fetched)) if fetched else _("no document"))
    return resolved, books, origins, titles, aliases


def run_reading(args: argparse.Namespace) -> None:
    from kotogen.generators import deck_story, pdf_pages, pdf_web, sources

    # The keyword `deck` names no text: those are written once the client exists.
    on_deck = any(i.strip().lower() == deck_story.KEYWORD for i in args.inputs)
    given = [i for i in args.inputs if i.strip().lower() != deck_story.KEYWORD]

    # The PDFs given by URL are fetched first: the rest only knows files.
    inputs, tadoku_books, origins, titles, aliases = _fetch_web_pdfs(given)

    # Images and Tadoku books can only be mini-books; a PDF is routed document by
    # document (see `_emit_pdf`).
    books = [i for i in inputs if i in tadoku_books or pdf_pages.is_image_source(i)]
    routes = sources.split(i for i in inputs if i not in books)
    pdf_paths = [pdf_source.clean_path(i) for i in routes.pdf]

    # The furigana are laid locally by MeCab rather than paid for from the model;
    # a site's own <ruby> is kept. `whole`: no bound on input, only the passages
    # kept being paid for, so that a novel can be read on (see `cursor`).
    texts = sources.text_sources(routes.nhk + routes.text, mode="reading",
                                 latest=args.latest, furigana=True, whole=True)
    if not texts and not pdf_paths and not books and not on_deck:
        if any(i.strip().lower() == "nhk" for i in args.inputs):
            console.title(sources.no_news(_("reading")))
            return
        sys.exit(_("No source to handle (give a URL, a text file, a PDF document, "
                   "the entry of a free Tadoku book, a folder of images, the "
                   "keyword {nhk} or the keyword {deck}).").format(
                       nhk=quoted("nhk"), deck=quoted(deck_story.KEYWORD)))

    client = AIClient(provider=args.provider, model=args.model)
    out_path = resolve_output_path(args, "reading")
    all_cards: list[dict] = []
    media_files: list[Path] = []

    if on_deck:
        try:
            texts += deck_story.stories(client, args.texts or 1, args.level,
                                        args.shape, args.length, memory.known())
        except RuntimeError as exc:
            if not texts and not pdf_paths and not books:
                sys.exit(str(exc))
            console.failed(str(exc))

    def read_text(src, title: str, lines: list[str]) -> list[dict]:
        if not isinstance(src, deck_story.DeckStory):
            return _emit_cards(client, title, lines, args, out_path, all_cards,
                               source=src.provenance, key=src.tracking_key)
        # A text written on the deck has the level it was asked at, and is never
        # cut into passages: its length was CHOSEN, as for an exam's 長文.
        src.report()
        cards = _emit_passage(client, title, lines,
                              argparse.Namespace(**{**vars(args), "level": src.level}),
                              out_path, all_cards, source=src.provenance,
                              name=src.name)
        src.check(cards)
        return cards

    sources.each(texts, read_text)

    # ── PDF documents ────────────────────────────────────────────────────────
    # The entry, not the cleaned path, is the key of the fetched addresses.
    for n, (entry, path) in enumerate(zip(routes.pdf, pdf_paths), 1):
        console.rank(n, len(pdf_paths), titles.get(str(path)) or path.name)
        before = len(all_cards)
        try:
            _emit_pdf(client, path, args, out_path, all_cards, media_files,
                      origins.get(entry, ""))
        except AIAuthError:
            raise
        except Exception as exc:
            console.failed(str(exc))
            continue
        # Into the history once it gave cards: the next pass takes the following
        # section or lesson.
        if len(all_cards) > before:
            _mark_remote_done(aliases.get(entry, ""))

    # ── Mini-book readings (PDF rendered as pages, or images already ready) ───
    for n, source in enumerate(books, 1):
        console.rank(n, len(books), titles.get(source) or Path(source).name)
        before = len(all_cards)
        try:
            _emit_book(client, source, args, out_path, all_cards, media_files,
                       origin=origins.get(source, ""))
        except AIAuthError:
            raise
        except Exception as exc:
            console.failed(str(exc))
            continue
        # Into the history once it gave cards, for the assistant's catalogue to
        # report it as already handled.
        if len(all_cards) > before and source in tadoku_books:
            pdf_web.mark_seen(origins.get(source, ""), titles.get(source, ""))

    if not all_cards:
        sys.exit(_("No card generated."))

    finish(all_cards, FIELDS, args, out_path, media=media_files,
           media_label="image", media_grouped=True, preview=quota.preview)
