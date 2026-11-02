"""Writing the cards (incremental TSV or JSON Lines) and showing the summaries.

Cards are written batch by batch and summed up once, at the close (`finish`).
Sending them is left to the collection the run is aimed at (`Outlet`); the Anki
one is the adapter's (`kotogen.anki.send`), handed over by the command line.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from kotogen import (
    __version__,
    ai_client,
    console,
    identity,
    memory,
    menu,
    prompts,
    proofreading,
    settings,
    system,
)
from kotogen.furigana import process_furigana
from kotogen.i18n import _, counted, listed, quoted as _quoted

# -- Helpers ------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")

# A line break in a field: the tag Anki's editor writes, the newline a model
# hands back, or a Unicode line or paragraph separator, which would cut the line
# of the file in two for whoever reads it with `splitlines`.
_LINE_BREAK_RE = re.compile("<br\\s*/?>|\n| | ", re.IGNORECASE)

# What a tag may not carry: the templates read `{{Tags}}` in a JavaScript
# template string (the level badge), where a backquote ends it, `${` opens an
# expression, a backslash escapes and `<` can end the script. No real tag has any.
_UNSAFE_TAG_RE = re.compile(r"[`$\\<>]")

# Fields whose content is HTML (the mini-book's `<img>` tags, the listening
# card's players: see the next block), exported as they are, not stripped.
RAW_HTML_FIELDS = frozenset({"Images", "Audio", "Video", "Image"})

# Fields exported without furigana. `ID` (built from a media name), `Source` (an
# address, a file name) and the numbers of `Timecodes`, `KeyLine` and `KeyPage`
# are not text to read: MeCab would only add readings and spaces.
PLAIN_FIELDS = frozenset({"ID", "Source", "Timecodes", "KeyLine", "KeyPage"})

# Fields plain on one kind only: the kanji card's come checked (MeCab reads 一日
# as days), a vocabulary `Context` prints raw on `Production`, and a grammar card
# matches `Target` and `Answer` character for character, which readings would part.
PLAIN_BY_KIND = {"kanji": frozenset({"Kanji", "Onyomi", "Kunyomi", "Words", "Strokes",
                                     "OtherReadings", "Composition", "LookAlikes",
                                     "Notes", "Decoy1", "Decoy2", "Decoy3"}),
                 "vocab": frozenset({"Context"}),
                 "grammar": frozenset({"Translation", "Target", "Nuance", "Answer"})}


def plain_field(name: str, kind: str | None) -> bool:
    """True if this field of a card of that kind is written without furigana.

    The rule of the export, which `ask` follows too when it writes into a note.
    """
    return name in PLAIN_FIELDS or name in PLAIN_BY_KIND.get(kind or "", ())


# -- How a field designates a medium ------------------------------------------
# Anki only counts a media file as used when a FIELD carries its tag: a bare
# name leaves it out of the media check and of an .apkg. The template places the
# tag. Not `[sound:...]`, which cannot start at a given instant, as the listening
# card's clickable transcript needs.

def audio_ref(filename: str) -> str:
    """The tag of the Audio field: the sound player of the listening card.

    No `type` attribute: the `none` compression keeps the original container
    (`.m4a`, `.opus`), and the browser goes by the file's extension.
    """
    return f'<audio controls src="{filename}"></audio>'


def video_ref(filename: str) -> str:
    """The tag of the Video field: the same player, picture included."""
    return f'<video controls playsinline preload="metadata" src="{filename}"></video>'


def image_ref(filename: str) -> str:
    """The tag of the Image field: the figure that comes with a past-paper exercise."""
    return f'<img src="{filename}">'


# The file a media tag names, read back by `media_named` and by `anki.send`,
# which points a card at the name Anki kept for it.
MEDIA_SRC_RE = re.compile(r'src="([^"]*)"')


def media_named(values: dict[str, str]) -> list[str]:
    """The files a card plays or shows, each once, in the order its fields name them.

    Only the HTML fields can name one: the others lose their tags (`_field_value`).
    """
    names: list[str] = []
    for name, value in values.items():
        if name in RAW_HTML_FIELDS:
            names += [file for file in MEDIA_SRC_RE.findall(value)
                      if file and file not in names]
    return names


def safe_text(value, line: Callable[[str], str] = str) -> str:
    """A field as text the card can only display, its line breaks kept as `<br>`.

    `line` (the furigana pass) gets each line as plain text; the result is
    escaped, entities read back first and control characters dropped, as
    `_TAG_RE` misses an unclosed `<img onerror=`. The apostrophe stays, so that
    `aujourd'hui` is still found by a search in Anki.
    """
    return "<br>".join(
        html.escape(line(console.clean(html.unescape(_TAG_RE.sub("", part)))), quote=False)
        .replace('"', "&quot;")
        for part in _LINE_BREAK_RE.split(str(value)))


def safe_tag(tag) -> str:
    """A tag the templates can read: what would end its string taken out."""
    return _UNSAFE_TAG_RE.sub("", str(tag))


def _clean_field(value, furigana: bool = True) -> str:
    """A field in plain text: tags stripped, furigana completed, newlines as `<br>`.

    `<br>` is what Shift+Enter writes in Anki's editor. One the model wrote goes
    with the other tags: only its newlines break its lines.
    """
    text = _TAG_RE.sub("", str(value)).replace("\t", " ")
    return safe_text(text, process_furigana if furigana else str)


def _field_value(name: str, value, kind: str | None = None) -> str:
    """The value of a field on export, cleaned unless the field carries HTML.

    A raw field only loses its tabs and newlines, the TSV's separators. A plain
    field (`plain_field`) skips the furigana.
    """
    if name in RAW_HTML_FIELDS:
        return " ".join(str(value).split())
    return _clean_field(value, furigana=not plain_field(name, kind))


# User folders offered as a destination: their Windows GUID (OneDrive often
# redirects them), their XDG variable (`~/Bureau` in a French Linux session),
# and as a last resort the English name under ~, which is right on macOS.
_KNOWN_FOLDERS = {
    "desktop": ("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}", "XDG_DESKTOP_DIR", "Desktop"),
    "downloads": ("{374DE290-123F-4565-9164-39C4925E467B}", "XDG_DOWNLOAD_DIR", "Downloads"),
    "documents": ("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}", "XDG_DOCUMENTS_DIR", "Documents"),
}


def _shell_folder(guid: str) -> Path | None:
    """The path of a folder Windows knows, or None if the system call fails."""
    import ctypes
    from ctypes import wintypes

    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    try:
        ole32, shell32 = ctypes.windll.ole32, ctypes.windll.shell32
        rfid, out = _GUID(), ctypes.c_wchar_p()
        if ole32.IIDFromString(guid, ctypes.byref(rfid)):
            return None
        if shell32.SHGetKnownFolderPath(ctypes.byref(rfid), 0, None, ctypes.byref(out)):
            return None
        try:
            return Path(out.value)
        finally:
            ole32.CoTaskMemFree(out)
    except (AttributeError, OSError):
        return None


def _known_folder(name: str) -> Path:
    """A usual user folder: desktop, downloads or documents."""
    guid, xdg_var, fallback = _KNOWN_FOLDERS[name]
    if system.windows():
        if (path := _shell_folder(guid)) is not None:
            return path
    elif (path := system.xdg_user_dir(xdg_var)) is not None:
        return path
    return Path.home() / fallback


def output_choices() -> list[tuple[str, Path]]:
    """The destinations offered by the "o" setting, the default first.

    Computed at call time: the current folder and the user folders can change.
    """
    return [
        (_("Current folder"), Path.cwd()),
        (_("Desktop"), _known_folder("desktop")),
        (_("Downloads"), _known_folder("downloads")),
        (_("Documents"), _known_folder("documents")),
    ]


def _default_output_dir(cache: bool = False) -> Path:
    """The output folder: the cache for a mere backup, failing that
    KOTOGEN_OUTPUT_DIR if it is set, failing that the current folder.

    The cache comes first: "o" picks where files to be imported land, and cards
    sent to Anki leave nothing to import. `--output` beats all of them (see
    `resolve_output_path`). The current folder rather than the Desktop: it is
    where the command was typed.
    """
    if cache:
        return _cache_output_dir()
    return settings.folder("KOTOGEN_OUTPUT_DIR") or Path.cwd()


def output_dir() -> Path:
    """The folder a TSV to be imported by hand will land in.

    Shown only where it serves: the "o" setting and the closing block.
    """
    return _default_output_dir()


def cache_dir() -> Path:
    """The program cache folder (see `system.cache_dir`).

    Re-exported because much of the program asks the exporter for it."""
    return system.cache_dir()


def _cache_output_dir() -> Path:
    """The folder of backup TSVs, when the cards go straight into Anki.

    The TSV is still written batch by batch, as a net against a crash, but out
    of the working folder since nobody imports it.
    """
    return cache_dir() / "runs"


# Enough to find a failed run's TSV after one or two more runs, without keeping
# copies of what Anki already has for ever.
RUNS_KEPT = 3


def _prune_runs(keep: int = RUNS_KEPT) -> None:
    """Keep only the `keep` most recent backups of sent runs.

    The cut-off is the mtime of the (keep+1)-th newest TSV, the media being named
    after their source, not their TSV. A TSV is completed after its media, so
    anything older belongs to an older run; the run in progress is safe.
    """
    folder = _cache_output_dir()
    if not folder.is_dir():
        return
    tsvs = sorted((f for f in folder.iterdir()
                   if f.is_file() and f.suffix.lower() == ".tsv"),
                  key=lambda f: f.stat().st_mtime, reverse=True)
    if len(tsvs) <= keep:
        return
    cutoff = tsvs[keep].stat().st_mtime
    for path in folder.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime <= cutoff:
                path.unlink()
        except OSError:
            continue  # file open elsewhere, permissions: the next run will retry


def short(text: str, n: int = 70) -> str:
    """A text on one line of at most `n` screen columns, its control characters out."""
    return console.truncate(console.clean(text).replace("\n", " "), n)


# -- The file of the run -------------------------------------------------------
#
# A `.jsonl` is JSON Lines, anything else the TSV Anki imports. The suffix
# decides rather than a flag: `--output` may name a file an earlier run wrote,
# and what is appended must match it. JSON Lines rather than a JSON array, which
# only closes at the end: an interrupted run keeps the lines it wrote.

JSON_SUFFIX = ".jsonl"

# The version of the JSON Lines layout, in its first line. It changes when a
# reader of one layout would misread the other (a key renamed, moved, or one to
# count on), never for a field added to a note type.
JSON_VERSION = 2


def is_json(path: str | Path) -> bool:
    """True if the cards of this file are written as JSON Lines."""
    return Path(path).suffix.lower() == JSON_SUFFIX


def resolve_output_path(args: argparse.Namespace, prefix: str) -> Path:
    """Settle the path of the file once and for all (before the batch loop).

    Priority: `--output`, the cache for a `--send` run (a mere backup), then
    `$KOTOGEN_OUTPUT_DIR`, then the current folder; the media go beside it.
    `--format` picks the suffix of a made-up name, TSV by default. Picking the
    cache prunes its older runs.
    """
    if args.output:
        return Path(args.output)
    cache = bool(args.send)
    out_dir = _default_output_dir(cache)
    out_dir.mkdir(parents=True, exist_ok=True)
    if cache:
        _prune_runs()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = JSON_SUFFIX if getattr(args, "format", None) == "json" else ".tsv"
    return out_dir / f"{prefix}_{timestamp}{suffix}"


def _tsv_header(fields: list[str], deck: str, notetype: str) -> str:
    """Return the #directive header lines of the TSV."""
    return "\n".join([
        "#separator:tab",
        "#html:true",
        f"#deck:{deck}",
        f"#notetype:{notetype}",
        "#tags column:" + str(len(fields) + 1),
    ]) + "\n"


def _tsv_row(card: dict, fields: list[str]) -> str:
    """Turn a card into one TSV line."""
    kind = identity.kind_of(fields)
    row = [_field_value(f, card.get(f, ""), kind) for f in fields]
    row.append(" ".join(_tags(card)))
    return "\t".join(row) + "\n"


def provenance() -> dict:
    """What a file written for another program says of its cards, besides them.

    Their language (`all.lang`), the kotogen release, the models the run used by
    the time the file opened (`ai_client.run_models`), and the time to the second
    with its offset.
    """
    return {"lang": prompts.language(), "kotogen": __version__,
            "model": ", ".join(ai_client.run_models()),
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds")}


def _json_header(fields: list[str], deck: str, notetype: str) -> str:
    """The first line of a JSON Lines file: what it is, where its cards go, and
    what wrote them.

    The TSV's `#deck` and `#notetype`, plus the note type's fields in order and
    the `provenance`. Only the run that opens the file writes it."""
    return json.dumps({"format": "kotogen", "version": JSON_VERSION,
                       "deck": deck, "notetype": notetype, "fields": list(fields)}
                      | provenance(), ensure_ascii=False) + "\n"


def outgoing(card: dict, fields: list[str]) -> dict:
    """A card as it goes out: its identity and its kind, its fields in the order
    of the note type, its tags, then the files it plays or shows.

    The values are the TSV's (`_field_value`), for a JSON line and a note sent
    alike; the identity is drawn from them as written, so a reader can derive it
    again (`identity`). A field list no generator writes gets neither `id` nor
    `kind`. `media` names the files as the fields do (`media_named`)."""
    kind = identity.kind_of(fields)
    values = {f: _field_value(f, card.get(f, ""), kind) for f in fields}
    out = {"id": identity.of(kind, values), "kind": kind} if kind else {}
    return out | {"fields": values, "tags": _tags(card), "media": media_named(values)}


def _tags(card: dict) -> list[str]:
    """The tags of a card as they go out, each one readable by the templates."""
    return [tag for tag in map(safe_tag, str(card.get("Tags", "")).split()) if tag]


def _json_row(card: dict, fields: list[str]) -> str:
    """Turn a card into one JSON line (see `outgoing`)."""
    return json.dumps(outgoing(card, fields), ensure_ascii=False) + "\n"


def _row(card: dict, fields: list[str], path: Path) -> str:
    """The line this card takes in that file, in the format of the file."""
    return _json_row(card, fields) if is_json(path) else _tsv_row(card, fields)


# -- Reading a JSON Lines file back --------------------------------------------
# For the memory of a JSON run (`known.JsonlFile`) and for `kotogen rework`.

# The layouts read back. A card of version 1 carries no `kind`: it is read off
# its fields.
JSON_VERSIONS = (1, 2)


class NotCards(ValueError):
    """A file that is not kotogen's JSON Lines, or of a layout this release does
    not read."""


@dataclass
class CardFile:
    """A JSON Lines file of cards, read back."""

    header: dict
    cards: list[dict]
    # Lines that did not read: one card fewer each, never a reason to stop.
    unreadable: int = 0


def read_cards(path: Path) -> CardFile:
    """The header and the cards of a JSON Lines file written by kotogen.

    Each card comes back as `{"id", "kind", "fields", "tags"}`, its kind read off
    its fields when the line lacks it. Unknown keys are passed over; an unknown
    version raises `NotCards`, its keys being open to misreading. Raises OSError
    when the file cannot be read.
    """
    lines = Path(path).read_text(encoding="utf-8").split("\n")
    try:
        header = json.loads(lines[0]) if lines[0].strip() else None
    except ValueError:
        header = None
    if not isinstance(header, dict) or header.get("format") != "kotogen":
        raise NotCards(_("{path} is not a file of kotogen cards (JSON Lines)").format(
            path=_quoted(Path(path).name)))
    version = header.get("version")
    if version not in JSON_VERSIONS:
        raise NotCards(_("{path} is written in version {version} of the JSON Lines of "
                         "kotogen, which this release does not read (it reads "
                         "{known})").format(
            path=_quoted(Path(path).name), version=version,
            known=", ".join(str(v) for v in JSON_VERSIONS)))
    cards: list[dict] = []
    unreadable = 0
    for line in lines[1:]:
        if not line.strip():
            continue
        try:
            card = json.loads(line)
        except ValueError:
            card = None
        fields = card.get("fields") if isinstance(card, dict) else None
        if not isinstance(fields, dict):
            unreadable += 1
            continue
        fields = {name: str(value) for name, value in fields.items()}
        cards.append({"id": card.get("id"),
                      "kind": card.get("kind") or identity.kind_of(list(fields)),
                      "fields": fields,
                      "tags": [str(tag) for tag in card.get("tags") or []]})
    return CardFile(header, cards, unreadable)


def append_cards(
    path: Path,
    cards: list[dict],
    fields: list[str],
    deck: str,
    notetype: str,
) -> None:
    """Write the headers if the file does not exist, then append the cards.

    The run's memory is told of a TSV's cards (`known.Known.written`), so that a
    second run with Anki closed, before the import, does not make them again.
    Lines end on a bare line feed, as `system.write_whole` writes them when the
    file is rewritten.
    """
    write_header = not path.exists() or path.stat().st_size == 0
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        if write_header:
            f.write(_json_header(fields, deck, notetype) if is_json(path)
                    else _tsv_header(fields, deck, notetype))
        for card in cards:
            f.write(_row(card, fields, path))
    if not is_json(path):
        memory.known().written(notetype, cards)


def remove_cards(path: Path, cards: list[dict], fields: list[str]) -> None:
    """Remove these cards from the file already written, and nothing else.

    Written batch by batch, the file holds every card generated, including those
    `proofreading` then drops. Their lines go one by one rather than the file
    being rewritten: `--output` may name a file holding an earlier run's cards.
    A line or a file not found is passed over.
    """
    if not cards:
        return
    to_remove: dict[str, int] = {}
    for card in cards:
        line = _row(card, fields, path)
        to_remove[line] = to_remove.get(line, 0) + 1
    try:
        lines = _lines_of(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return
    kept = []
    for line in lines:
        if to_remove.get(line):
            to_remove[line] -= 1
            continue
        kept.append(line)
    _rewrite(path, "".join(kept))


def replace_rows(path: Path, replacements: list[tuple[str, str]]) -> None:
    """Rewrite these lines of the file already written, one for one, and nothing else.

    Carries into the file what changed on a card once written: the tag a card
    to proofread gets at sorting time (see `proofreading`), or the media name
    the collection kept (`Outlet.take`). As in `remove_cards`, an earlier run's
    lines are left alone and a line not found is passed over.
    """
    if not replacements:
        return
    expected: dict[str, list[str]] = {}
    for old, new in replacements:
        expected.setdefault(old, []).append(new)
    try:
        lines = _lines_of(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return
    out = []
    for line in lines:
        if expected.get(line):
            line = expected[line].pop(0)
        out.append(line)
    _rewrite(path, "".join(out))


def _lines_of(text: str) -> list[str]:
    """The lines of a file of the run, each with its line feed.

    Cut on the line feed alone: `splitlines` also cuts on U+2028, which a line
    written by hand or by another program may carry inside a field.
    """
    lines = text.split("\n")
    return [line + "\n" for line in lines[:-1]] + ([lines[-1]] if lines[-1] else [])


def _rewrite(path: Path, text: str) -> None:
    """Rewrite the file of the run, which never stops the close of a paid run.

    Whole if it can be; in place when Windows will not replace it (OneDrive or
    an indexer holding it); failing both, left as it was, said on one line.
    """
    try:
        system.write_whole(path, text)
        return
    except OSError:
        pass
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except OSError as exc:
        console.failed(_("{path} could not be brought up to date ({error}): it keeps "
                         "its lines as they were.").format(
            path=_quoted(path.name), error=console.reason(exc)))


# -- Where the cards go besides their file -------------------------------------
# At the close (`finish`), a run hands its media then its notes to the
# collection it is aimed at; Anki's is in the adapter (`kotogen.anki.send`).
# Without one, the cards stay in their file.


@dataclass(frozen=True)
class Taken:
    """What a collection made of the cards it was handed."""

    # (added, duplicates refused), or None when it did not take them.
    sent: tuple[int, int] | None
    # Why it did not, as a fragment of a sentence the closing block completes
    # with the path of the file ("Anki was not connected").
    blocked: str = ""
    # The media it could not put down, to be copied by hand.
    left_out: list[Path] = field(default_factory=list)
    # The fields it had to add to the note type to hold the cards.
    fields_added: list[str] = field(default_factory=list)


class Outlet:
    """A collection that takes the cards of a run, besides the file they are in.

    The run's memory is one when it can (`memory.known`): the deck the cards
    are compared with is the deck they go into.
    """

    def take(self, cards: list[dict], fields: list[str], deck: str, notetype: str,
             media: list[Path]) -> Taken:
        """Put the media and the cards in.

        May point a media field of the cards at the name the collection kept
        for its file: the closing block carries that into the file written.
        """
        raise NotImplementedError

    def by_hand(self) -> str:
        """Where a media file goes when it is copied by hand, said for this system."""
        raise NotImplementedError


def _outlet() -> Outlet | None:
    """The collection this run's cards go into, when it takes them."""
    held = memory.known()
    return held if isinstance(held, Outlet) else None


def _media_heading(label: str) -> str:
    """The media of a run named as a heading, with no count in front.

    Not the counted noun: in Japanese it carries its counter (`個のファイル`).
    `label` is the English singular `finish` receives.
    """
    return {"image": _("Images", "media"), "audio": _("Audio files", "media"),
            "media": _("Media files", "media")}.get(label) or _("Files", "media")


def finish(cards: list[dict], fields: list[str], args: argparse.Namespace,
           out_path: Path, *,
           preview: list[str] | Callable[[list[dict]], list[str]],
           extras: list[str] | None = None,
           media: list[Path] | None = None, media_label: str = "file",
           media_grouped: bool = False) -> tuple[int, int] | None:
    """The closing block of a command: media, sending, then ONE summary.

    Returns the send's `(added, duplicates)`, or None when the cards did not go
    into Anki, the one place a missing connection is reported. `preview` may be
    a function of the cards going out, so that a dropped card is not shown;
    `media_label` is the media's English singular, and `media_grouped` counts
    them by folder (a mini-book's pages) rather than naming them.
    """
    media = list(media or [])
    sending = bool(getattr(args, "send", False))

    # Sorting comes first: what it drops leaves the send, the file, the count and
    # the preview alike. The marked cards' lines are kept from before, to find
    # them in the file once `sort_out` has tagged them.
    before = [(card, _row(card, fields, out_path)) for card in proofreading.marked(cards)]
    cards, dropped = proofreading.sort_out(cards, args)
    if dropped:
        remove_cards(out_path, dropped, fields)
    replace_rows(out_path, [(line, after) for card, line in before
                                    if (after := _row(card, fields, out_path)) != line])
    extras = list(extras or []) + proofreading.summary(cards, dropped)
    if callable(preview):
        preview = preview(cards)
    left_out: list[Path] = []
    fields_added: list[str] = []
    sent: tuple[int, int] | None = None
    blocked = ""
    outlet = _outlet()
    if sending and outlet is None:
        blocked = _("no deck to send them to")
    elif sending:
        # The media go with the cards sent; with no send they stay beside the
        # TSV. The collection may rename a file and point the fields at its name
        # (`Outlet.take`): the file written follows, like the proofreading tags.
        before_media = [(card, _row(card, fields, out_path)) for card in cards]
        taken = outlet.take(cards, fields, args.deck, args.notetype, media)
        replace_rows(out_path, [(line, after) for card, line in before_media
                                if (after := _row(card, fields, out_path)) != line])
        sent, blocked, left_out = taken.sent, taken.blocked, taken.left_out
        fields_added = taken.fields_added

    lines: list[str] = []
    if sent is not None:
        added, dupes = sent
        line = _("{count} {cards} in {deck}").format(
            count=added, cards=console.plural(added, "card"),
            deck=_quoted(args.deck))
        if dupes:
            line += counted(dupes,
                            ", {count} duplicate ignored",
                            ", {count} duplicates ignored").format(count=dupes)
        if media and not left_out:
            line += _(", {count} {label} in the media library").format(
                count=len(media), label=console.plural(len(media), media_label))
        lines.append(line)
    elif blocked:
        # The obstacle and where the cards are instead, in one sentence.
        line = counted(len(cards),
                       "{obstacle}: the card is in {path}",
                       "{obstacle}: the {count} cards are in {path}")
        lines.append(line.format(obstacle=blocked, count=len(cards), path=out_path))
    else:
        lines.append(_("{count} {cards} -> {path}").format(
            count=len(cards), cards=console.plural(len(cards), "card"),
            path=out_path))
    # An added field is in the notes, but the card templates show it only once
    # installed.
    if fields_added:
        line = counted(len(fields_added),
                       "→ field {names} added to {notetype}: `kotogen deck install` "
                       "brings its card templates up to date",
                       "→ fields {names} added to {notetype}: `kotogen deck install` "
                       "brings its card templates up to date")
        lines.append("   " + line.format(names=listed(fields_added),
                                         notetype=_quoted(args.notetype)))
    lines += extras
    # A JSON Lines file is not for Anki: no import hint, and its media are
    # already beside it.
    for_anki = not is_json(out_path)
    if sent is None and for_anki:
        lines.append("   " + _("→ Anki import: File > Import > select the file"))

    # Listed rather than counted: each of these files is to be copied by hand.
    if for_anki and (pending := (left_out if sending else media)):
        label = _media_heading(media_label)
        lines.append("   " + (_("{label} to copy into {folder}:").format(
            label=label, folder=outlet.by_hand()) if outlet is not None
            else _("{label} to copy with the cards:").format(label=label)))
        if media_grouped:
            for folder in sorted({p.parent for p in pending}):
                count = sum(1 for p in pending if p.parent == folder)
                lines.append("   - " + _("{count} {label} in {folder}").format(
                    count=count, label=console.plural(count, media_label),
                    folder=folder))
        else:
            lines += [f"   - {path}" for path in pending]

    # A single print, so that no line of the block opens a blank line of its own.
    console.space()
    print("\n".join(lines))

    if sent is None:
        print_preview(preview)
    return sent


# -- Display ------------------------------------------------------------------

# Raised by `--yes` for the length of one command, see `unattended`.
_unattended = False


@contextmanager
def unattended(on: bool):
    """Within the block, every question answers itself as a script's would.

    For `--yes`: each question takes its EOF answer, `default` or else the last,
    prudent choice. A block rather than a setting, since the assistant runs
    several commands in one process.
    """
    global _unattended
    before, _unattended = _unattended, on
    try:
        yield
    finally:
        _unattended = before


def ask_choice(prompt: str, choices: str, *, default: str | None = None,
               indent: str = "   ") -> str:
    """Read a single-character choice among `choices` (case insensitive).

    On EOF, returns `default`, or else the LAST choice: menus put the most
    prudent option last. Under `unattended`, the same answer at once, printed
    after the question as if typed. `indent` lines the question up with a column.
    The prompt is cleaned (`console.clean`): it may quote a model's words.
    """
    prompt = console.clean(prompt)
    if _unattended:
        answer = (default or choices[-1]).lower()
        print(f"{indent}{prompt} {answer}")
        return answer
    valid = set(choices.lower())
    while True:
        # Printed rather than handed to `input()`, which writes to the C stdout
        # (cp1252 on Windows consoles) and crashes on Japanese. `read_line()`
        # counts the typed newline, so the next block adds no second blank line.
        print(f"{indent}{prompt} ", end="", flush=True)
        try:
            ans = console.read_line().strip().lower()
        except EOFError:
            return (default or choices[-1]).lower()
        if ans and ans[0] in valid:
            return ans[0]
        print(f"{indent}" + _("→ expected answer: {choices}").format(
            choices="/".join(choices)))


def choose(options: list[tuple[str, str]], question: str = "", *,
           default: str | None = None, start: str | None = None,
           indent: str = "   ") -> str:
    """Offer `options` (key, label) one per line; hand back the key chosen.

    The assistant's menu where the terminal allows it (`menu.by_key`), else the
    lines and `ask_choice`. The highlight opens on `start`, else `default`, else
    the last, prudent option: a list ending on "quit" passes `start`, since EOF
    must stop there and Enter must not.
    """
    keys = [key for key, _label in options]
    if question:
        print(f"{indent}{console.clean(question)}")
    view = menu.View(
        lines=[f"{indent}  {key}. {console.clean(label)}" for key, label in options],
        targets=keys, tokens=keys, line_of={i: i for i in range(len(keys))},
        shortcuts={key.lower(): i for i, key in enumerate(keys)}, boxes={},
        dimmed=set(), numbered=0,
        start=keys.index(start or default or keys[-1]),
        raw=(not _unattended and menu.raw_ready()
             and menu.fits_on_screen(len(options))), footer=0)
    if view.raw:
        return menu.by_key(view, allow_back=False)
    print("\n".join(view.lines))
    return ask_choice(_("Choice?"), "".join(keys), default=default, indent=indent)


def print_preview(lines: list[str], limit: int | None = 20) -> None:
    """Show the "Preview" box common to the generators (one card per line)."""
    console.space()
    print("── " + _("Preview") + " " + "─" * 60)
    shown = lines if limit is None else lines[:limit]
    for line in shown:
        print(line)
    if limit is not None and len(lines) > limit:
        print("  " + _("... and {count} more").format(count=len(lines) - limit))
    print("─" * 65)
