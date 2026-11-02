"""Installing the Anki note types from the templates of the repository.

What is missing is created without asking. What exists is rewritten without
asking only where Anki still holds what kotogen last wrote there (see
`installed`); a face edited in Anki is kept, and one changed on both sides, or
with no record, is asked about. Nothing is ever deleted: an extra field or card
is reported, since removing a field empties it on every note.

Templates are compared as rendered for this profile (`kotogen.anki.templates`);
the fields come from the generators' `FIELDS`, so a type created here accepts
the cards the program writes.
"""

from __future__ import annotations

import copy
import difflib
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path

from kotogen import console, settings
from kotogen.anki import installed, templates as card_templates
from kotogen.anki.connect import request as anki
from kotogen.cli import cards_var, deck_config, enabled_cards
from kotogen.i18n import _, convention, counted, listed, quoted as _quoted

# `templates/<command>/` has no language level: a card prints no prose of its own,
# only the note's words and signs (本文, 訳, chevrons, an arrow). `all.lang`
# settles what the MODEL writes (see `prompts.language`), not what is installed.


# -- Description of the note types --------------------------------------------

@dataclass(frozen=True)
class NoteTypeSpec:
    """A note type: where its fields, its cards and its CSS come from."""

    command: str                            # vocab, grammar, audio, reading
    directory: str                          # subfolder of templates/
    all_cards: tuple[tuple[str, str], ...]  # (card name, subfolder or "")
    is_cloze: bool = False

    @property
    def notetype(self) -> str:
        """Name of the note type, .env override included."""
        return deck_config(self.command)[1]

    @property
    def cards(self) -> tuple[tuple[str, str], ...]:
        """Cards this profile installs: the repository, less what the `.env` drops.

        A dropped card is neither created, nor compared, nor reported.
        """
        return enabled_cards(self.command, self.all_cards)

    @property
    def fields(self) -> list[str]:
        """Fields written by the generator of this command."""
        module = import_module(f"kotogen.generators.{_MODULES[self.command]}")
        return list(module.FIELDS)


# Name of the generator module when it differs from the command.
_MODULES = {"kanji": "kanji", "vocab": "vocab", "grammar": "grammar", "audio": "audio",
            "reading": "reading"}

SPECS = (
    # One card, in a folder of its own all the same: `Production` (the kanji
    # among four) is to sit beside it.
    NoteTypeSpec("kanji", "kanji", (("Recognition", "recognition"),)),
    NoteTypeSpec("vocab", "vocab",
                 (("Recognition", "recognition"), ("Production", "production"))),
    # Cloze notetype: the {{c1::...}} gap of the `Sentence` is what makes the card.
    NoteTypeSpec("grammar", "grammar", (("Grammar", ""),), is_cloze=True),
    NoteTypeSpec("audio", "audio", (("Listening", ""),)),
    NoteTypeSpec("reading", "reading", (("Reading", ""),)),
)

COMMANDS = tuple(spec.command for spec in SPECS)

# The sheet every note type shares, at the root of `templates/`: the palette,
# the page and the furigana.
COMMON_CSS = "common.css"


# -- Reading the templates -----------------------------------------------------

def templates_root() -> Path | None:
    """The `templates/` folder of the sources the program runs from, or None.

    That folder and no other, as for the `.env` (`settings.ROOT`): never one
    found from the current directory.
    """
    candidate = settings.ROOT / "templates"
    return candidate if candidate.is_dir() else None


def _normalise(text: str) -> str:
    """Line endings and edge whitespace brought back to what Anki stores.

    Both sides of every comparison go through it: a CRLF alone is no difference.
    """
    return text.replace("\r\n", "\n").strip("\n")


def _read(path: Path, command: str, raw: bool = False) -> str:
    """Template of the repository, as this profile wants it and as Anki stores it.

    The only place customisation comes in. `raw` gives the file with its markers,
    for the preview, which removes the blocks itself; what goes into Anki is
    always rendered.
    """
    text = path.read_text(encoding="utf-8")
    return _normalise(text if raw else card_templates.render(text, command))


def _face(card: dict[str, str] | None, key: str) -> str:
    """Front or Back of a card read in Anki, normalised."""
    return _normalise((card or {}).get(key, ""))


def read_templates(spec: NoteTypeSpec, root: Path,
                   raw: bool = False) -> tuple[dict[str, dict[str, str]], str]:
    """Cards and CSS of a note type: ({name: {Front, Back}}, css).

    Raises FileNotFoundError if a template is missing, rather than install a card
    with an empty back. `raw` keeps the customisation markers (see `_read`).
    """
    base = root / spec.directory
    templates: dict[str, dict[str, str]] = {}
    css = ""
    for name, sub in spec.cards:
        folder = base / sub if sub else base
        templates[name] = {
            "Front": _read(folder / "front.html", spec.command, raw),
            "Back": _read(folder / "back.html", spec.command, raw),
        }
        # Anki has one CSS per note type: the first card's is the one (the two
        # sheets of the vocabulary are identical).
        css = css or _read(folder / "style.css", spec.command, raw)
    # The shared sheet goes first, so that the type's own rules win. The
    # program's `templates/` always has one; a root built by a test may not.
    common = root / COMMON_CSS
    if common.exists():
        css = _read(common, spec.command, raw) + "\n" + css
    return templates, css


# -- Writing the templates on disk ---------------------------------------------
# The offline counterpart of `deck install`, for when AnkiConnect does not answer
# and no browser opens the preview: the RENDERED templates, customisation
# included, laid down in a folder to be pasted into Anki's card editor.

# What Windows refuses in a file name, plus the separator of the other two: a
# note type renamed by hand in Anki may carry a colon.
_FORBIDDEN = str.maketrans({c: "-" for c in R'<>:"/\|?*'})


def _folder_name(name: str) -> str:
    """A card or note type name, such as a folder can carry it."""
    return name.translate(_FORBIDDEN).strip(" .") or "card"


def export_templates(dest: Path, only: set[str] | None = None) -> list[Path]:
    """Writes the rendered templates under `dest`; gives back the files written.

    The tree carries the names Anki shows, not the repository's; `README.txt`
    says what goes where, the fields in order and which type is a Cloze. Raises
    FileNotFoundError, before writing anything, if a template is missing.
    """
    from kotogen.cli import skipped_commands

    root = templates_root()
    if root is None:
        raise FileNotFoundError(_(
            "`templates/` folder not found in {path}: kotogen runs from a clone of "
            "its repository, installed with `pip install -e .`.")
            .format(path=_quoted(str(settings.ROOT))))

    dropped = skipped_commands()
    specs = [spec for spec in SPECS
             if spec.command not in dropped
             and (only is None or spec.command in only)]

    # Everything is read first, so that a missing template fails before any write.
    read = [(spec, *read_templates(spec, root)) for spec in specs]

    written: list[Path] = []

    def put(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # LF endings and the final newline `_normalise` took away.
        path.write_text(f"{text}\n", encoding="utf-8", newline="\n")
        written.append(path)

    for spec, cards_read, css in read:
        folder = dest / _folder_name(spec.notetype)
        put(folder / "fields.txt", "\n".join(spec.fields))
        put(folder / "style.css", css)
        # No subfolder for a single card: it would tell nothing apart.
        for name, content in cards_read.items():
            face = folder / _folder_name(name) if len(cards_read) > 1 else folder
            put(face / "front.html", content["Front"])
            put(face / "back.html", content["Back"])

    put(dest / "README.txt", _readme(read))
    return written


def _readme(read: list) -> str:
    """The instructions of the folder written: where to paste what, what to create."""
    # The menus named are quoted the way the language quotes.
    lines = [
        _("The kotogen templates, as your profile wants them."),
        "",
        _("This folder is what {menu} would have laid down in Anki").format(
            menu=_quoted(f"{_('Templates')} > {_('Install')}")),
        _("if AnkiConnect had answered. The blocks your appearance settings"),
        _("remove are already removed from it: there is nothing to trim before"),
        _("pasting."),
        "",
        _("In Anki: Tools > Manage Note Types."),
        _("  - {button} creates the type (Basic, or Cloze where it is said so);").format(
            button=_quoted(_("Add", "Anki button"))),
        _("  - {button} creates them one by one, IN THE ORDER of fields.txt;").format(
            button=_quoted(_("Fields...", "Anki button"))),
        _("  - {button} opens the three boxes the rest goes into:").format(
            button=_quoted(_("Cards...", "Anki button"))),
        _("        front.html  -> Front Template"),
        _("        back.html   -> Back Template"),
        _("        style.css   -> Styling (a single sheet for the whole type)."),
        "",
    ]
    for spec, cards_read, _css in read:
        kind = _("Cloze") if spec.is_cloze else _("Basic")
        lines.append(_("{notetype}  ({kind}, {count} fields)").format(
            notetype=spec.notetype, kind=kind, count=len(spec.fields)))
        for name in cards_read:
            where = (f"{_folder_name(name)}/" if len(cards_read) > 1 else "")
            lines.append(_("   card {name}: {where}front.html, {where}back.html")
                         .format(name=_quoted(name), where=where))
        lines.append("")
    return "\n".join(lines).rstrip("\n")


# -- Comparison with what is already in Anki -----------------------------------

# The three pieces repaired separately: a CSS put back must not take away a
# front edited in Anki.
FRONT, BACK, CSS = "front", "back", "CSS"
_FACE_KEY = {FRONT: "Front", BACK: "Back"}

# Beyond this many diff lines only the count shows; `--diff` unfolds it anyway.
_INLINE_DIFF_MAX = 3

# Who moved a face since kotogen last wrote it (see `installed`), which settles
# whether it is rewritten without a question, kept, or asked about.
UPSTREAM = "upstream"   # the repository alone: Anki holds what kotogen wrote
EDITED = "edited"       # Anki alone: the repository still holds what it wrote
BOTH = "both"           # each side, each its own way
UNKNOWN = "unknown"     # nothing recorded of what kotogen wrote


def _diff(before: str, after: str, context: int = 0) -> list[str]:
    """Unified diff from one text to the other, without the file headers."""
    lines = difflib.unified_diff(before.split("\n"), after.split("\n"),
                                 lineterm="", n=context)
    return [line for line in lines if not line.startswith(("---", "+++"))]


@dataclass(frozen=True)
class Change:
    """A drift between the repository and Anki, repairable on its own."""

    face: str          # FRONT, BACK or CSS
    ours: str          # what the repository carries
    theirs: str        # what Anki carries today
    card: str = ""     # name of the card in the repository ("" for the CSS)
    target: str = ""   # its name in Anki, when it carries another one
    base: str | None = None  # what kotogen last wrote there, None if unknown

    @property
    def origin(self) -> str:
        """Who moved since kotogen last wrote this face.

        Anki and the repository cannot both still hold what kotogen wrote: a
        change exists because they differ.
        """
        if self.base is None:
            return UNKNOWN
        if self.theirs == self.base:
            return UPSTREAM
        if self.ours == self.base:
            return EDITED
        return BOTH

    @property
    def label(self) -> str:
        """What is being talked about: "CSS", or the card and the face it names.

        The name in Anki is added when it differs from the repository's (a type
        set up by hand, whose card is "JPtoEN"). The install question uses it too.
        """
        if self.face == CSS:
            return "CSS"
        renamed = (_(" (named {name} in Anki)").format(name=_quoted(self.target))
                   if self.target and self.target != self.card else "")
        return _("card {card}{renamed}, {face}").format(
            card=_quoted(self.card), renamed=renamed, face=_(self.face))

    def diff(self, context: int = 0) -> list[str]:
        """Unified diff from Anki to the repository, without the file headers."""
        return _diff(self.theirs, self.ours, context)

    @property
    def stat(self) -> tuple[int, int, int]:
        """(hunks, lines of the repository added, lines of Anki removed)."""
        lines = self.diff()
        return (sum(line.startswith("@@") for line in lines),
                sum(line.startswith("+") for line in lines),
                sum(line.startswith("-") for line in lines))


@dataclass
class Plan:
    """What there would be to do on a note type, before doing it."""

    spec: NoteTypeSpec
    exists: bool
    templates: dict[str, dict[str, str]]     # templates of the repository
    css: str
    target_names: dict[str, str]             # repository name -> name in Anki
    changes: list[Change] = field(default_factory=list)
    current: dict[str, dict[str, str]] = field(default_factory=dict)  # Anki side
    missing_fields: list[str] | None = None  # fields to add
    extra_fields: list[str] | None = None    # fields too many (never removed)
    new_cards: list[str] | None = None       # repository cards absent from Anki
    unmatched: bool = False                  # cards that cannot be paired
    profile: str = ""                        # the Anki profile open
    model_id: int | None = None              # None for a type still to create
    base: dict = field(default_factory=dict)  # what kotogen wrote, see `installed`

    @property
    def notetype(self) -> str:
        return self.spec.notetype

    def by_origin(self, *origins: str) -> list[Change]:
        """The differences that moved the way one of `origins` says."""
        return [change for change in self.changes if change.origin in origins]

    def asked(self, overwrite_edits: bool = False) -> list[Change]:
        """The differences the question is about: those nothing settles alone.

        A face kotogen alone moved is rewritten without asking; one Anki alone
        moved is kept, unless `overwrite_edits` puts it to the question too.
        """
        return self.by_origin(UNKNOWN, BOTH, *((EDITED,) if overwrite_edits else ()))

    @property
    def differs(self) -> bool:
        """True if anything at all separates the repository from what Anki holds."""
        return (not self.exists or bool(self.changes)
                or bool(self.missing_fields) or bool(self.new_cards)
                or self.unmatched)


def _match_names(ours: list[str], theirs: list[str]) -> tuple[dict[str, str], list[str], bool]:
    """Pairs our card names with those of the existing note type.

    Gives back (pairing, repository cards absent from Anki, ambiguous pairing).
    By name when all match, else by position, the repository's surplus becoming
    cards to add. When Anki has more, nothing is guessed: a face written into the
    wrong card is worse than nothing.
    """
    if all(name in theirs for name in ours):
        return {name: name for name in ours}, [], False
    if len(ours) >= len(theirs):
        return dict(zip(ours, theirs)), ours[len(theirs):], False
    return {}, [], True


def _profile() -> str:
    """The Anki profile open, or "" from an add-on too old to say.

    What kotogen wrote is filed under it (see `installed`): one profile copied
    from another carries its note types under the same IDs.
    """
    try:
        return anki("getActiveProfile") or ""
    except RuntimeError:
        return ""


def plan_for(spec: NoteTypeSpec, root: Path) -> Plan:
    """Compares the repository and Anki for a note type. Writes nothing.

    Each change also carries what kotogen last wrote there, which says who moved.
    """
    templates, css = read_templates(spec, root)
    name = spec.notetype
    profile = _profile()

    existing = anki("modelNamesAndIds") or {}
    if name not in existing:
        return Plan(spec, exists=False, templates=templates, css=css,
                    target_names={n: n for n in templates}, profile=profile)
    model_id = existing[name]
    base = installed.recall(profile, model_id)
    written = base.get("cards") or {}

    # `modelTemplates` answers under "Front"/"Back", as `updateModelTemplates`
    # takes them, not under the "qfmt"/"afmt" of Anki's internal schema.
    raw = anki("modelTemplates", modelName=name) or {}
    target_names, new_cards, unmatched = _match_names(list(templates), list(raw))
    current = {ours: {key: _face(raw.get(theirs), key) for key in ("Front", "Back")}
               for ours, theirs in target_names.items()}

    changes = [
        Change(face, templates[ours][key], current[ours][key], ours, theirs,
               base=(written.get(ours) or {}).get(key))
        for ours, theirs in target_names.items()
        for face, key in _FACE_KEY.items()
        if current[ours][key] != templates[ours][key]
    ]

    current_css = _normalise((anki("modelStyling", modelName=name) or {}).get("css") or "")
    if current_css != css:
        changes.append(Change(CSS, css, current_css, base=base.get("css")))
    fields = anki("modelFieldNames", modelName=name) or []

    return Plan(
        spec, exists=True, templates=templates, css=css,
        target_names=target_names, changes=changes, current=current,
        missing_fields=[f for f in spec.fields if f not in fields],
        extra_fields=[f for f in fields if f not in spec.fields],
        new_cards=new_cards,
        unmatched=unmatched,
        profile=profile, model_id=model_id, base=base,
    )


# -- Writing into Anki ---------------------------------------------------------

def _record(plan: Plan) -> None:
    """Files `plan.base` as what kotogen has written into the type (see `installed`)."""
    if plan.model_id is not None:
        installed.remember(plan.profile, plan.model_id, plan.base)


def create(plan: Plan) -> None:
    """Creates the note type from scratch, and records what it laid down.

    The record is filed under the ID `createModel` answers with; an add-on that
    answers nothing leaves none, and the next install asks about the type.
    """
    model = anki(
        "createModel",
        modelName=plan.notetype,
        inOrderFields=plan.spec.fields,
        css=plan.css,
        isCloze=plan.spec.is_cloze,
        cardTemplates=[{"Name": name, **tpl} for name, tpl in plan.templates.items()],
    )
    plan.model_id = model.get("id") if isinstance(model, dict) else None
    plan.base = {"cards": copy.deepcopy(plan.templates), "css": plan.css}
    _record(plan)


def resync(plan: Plan) -> None:
    """Records the faces Anki already holds as the repository has them.

    Writes nothing into Anki. Gives a record to a type set up by hand or on
    another machine; the file is written only if that changes it.
    """
    if not plan.exists or plan.model_id is None:
        return
    before = copy.deepcopy(plan.base)
    differing = {(change.card, change.face) for change in plan.changes}
    cards = plan.base.setdefault("cards", {})
    for ours in plan.target_names:
        for face, key in _FACE_KEY.items():
            if (ours, face) not in differing:
                cards.setdefault(ours, {})[key] = plan.templates[ours][key]
    if ("", CSS) not in differing:
        plan.base["css"] = plan.css
    if plan.base != before:
        _record(plan)


def add_fields(plan: Plan) -> None:
    """Adds the fields the generator writes and the note type does not have.

    Neither asked nor backed up first: an added field arrives empty on existing
    notes and overwrites nothing.
    """
    for name in plan.missing_fields or []:
        anki("modelFieldAdd", modelName=plan.notetype, fieldName=name)
        # `modelFieldAdd` appends; the field goes back to its rank in `FIELDS`,
        # as in a type created from scratch, since a TSV import pairs its columns
        # with the RANK of the fields. Anki moves the content with the field.
        index = plan.spec.fields.index(name)
        anki("modelFieldReposition", modelName=plan.notetype, fieldName=name, index=index)
    # Added: the rewrite that follows must not add them again.
    plan.missing_fields = []


def update(plan: Plan, add_cards: bool = False,
           changes: list[Change] | None = None) -> None:
    """Updates an existing note type.

    Never takes anything away: adds the missing fields, rewrites the drifts of
    `changes` (all by default). `add_cards` is never implicit: each existing note
    gets a card to review. `updateModelTemplates` writes whole cards, so a face
    left out is laid down again as Anki holds it, and keeps its record.
    """
    changes = plan.changes if changes is None else list(changes)
    add_fields(plan)

    if add_cards:
        for name in plan.new_cards or []:
            anki("modelTemplateAdd", modelName=plan.notetype,
                 template={"Name": name, **plan.templates[name]})

    templates: dict[str, dict[str, str]] = {}
    for change in (c for c in changes if c.face != CSS):
        card = templates.setdefault(
            change.card, dict(plan.current.get(change.card) or plan.templates[change.card]))
        card[_FACE_KEY[change.face]] = change.ours

    if templates:
        anki("updateModelTemplates", model={
            "name": plan.notetype,
            "templates": {plan.target_names[name]: tpl for name, tpl in templates.items()},
        })

    if any(c.face == CSS for c in changes):
        anki("updateModelStyling", model={"name": plan.notetype, "css": plan.css})

    # What was written is now both Anki's state and kotogen's record: a second
    # call on this plan (after the question) starts from it, not from Anki's
    # faces before the first.
    cards = plan.base.setdefault("cards", {})
    for name in (plan.new_cards or []) if add_cards else []:
        cards[name] = dict(plan.templates[name])
    for change in changes:
        if change.face == CSS:
            plan.base["css"] = change.ours
            continue
        key = _FACE_KEY[change.face]
        cards.setdefault(change.card, {})[key] = change.ours
        plan.current.setdefault(change.card, {})[key] = change.ours
    plan.changes = [change for change in plan.changes if change not in changes]
    _record(plan)


# -- The `kotogen deck install` command ----------------------------------------

# Where a drift sits, said the way one would read it: "12 lines on the front".
_PLACE = {FRONT: "on the front", BACK: "on the back", CSS: "in the CSS"}


def summary(changes: list[Change]) -> str:
    """What differs, piece by piece: "12 lines on the front, 108 on the back".

    One line per note type with a count per piece, the card named only when
    several cards of the type are touched. The exact diff stays under `[d]`.
    """
    cards = {change.card for change in changes if change.card}
    parts: list[str] = []
    for change in changes:
        # A rewritten line is a "+1, -1": counted once.
        count = max(change.stat[1], change.stat[2])
        place = _(_PLACE[change.face])
        if change.card and len(cards) > 1:
            place += _(" of {card}").format(card=_quoted(change.card))
        # The unit goes on the first term only.
        head = (counted(count, "{count} line", "{count} lines")
                .format(count=count) if not parts else str(count))
        parts.append(f"{head} {place}")
    return listed(parts)


def _unfolded(changes: list[Change], context: int = 0) -> list[str]:
    """The diffs unfolded, each under its label when there are several."""
    colon = convention("colon", ": ").rstrip()
    lines: list[str] = []
    for change in changes:
        if len(changes) > 1:
            lines.append(f"{change.label}{colon}")
        for side, diff in _sides(change, context):
            indent = "   "
            if side:
                lines.append(f"   {side}{colon}")
                indent = "      "
            lines += [f"{indent}{line}" for line in diff
                      if context or not line.startswith("@@")]
    return lines


def _sides(change: Change, context: int) -> list[tuple[str, list[str]]]:
    """The diffs a change reads through: one, or one per side when both moved.

    When both moved, one diff from Anki would mix the edit with the release, so
    each side is shown from what kotogen last wrote.
    """
    if change.origin != BOTH:
        return [("", change.diff(context=context))]
    return [(_("edited in Anki"), _diff(change.base, change.theirs, context)),
            (_("changed in kotogen"), _diff(change.base, change.ours, context))]


def _inline_diff(changes: list[Change], full_diff: bool = False) -> list[str]:
    """The diff unfolded outright under the count, as long as it fits three lines."""
    added = sum(change.stat[1] for change in changes)
    removed = sum(change.stat[2] for change in changes)
    if not full_diff and added + removed > _INLINE_DIFF_MAX:
        return []
    return _unfolded(changes)


def _drifts(plan: Plan, check: bool, overwrite_edits: bool = False) -> list[str]:
    """What separates an existing type from the repository, one line per mover.

    First what kotogen alone moved, said as done (as to do under `--check`), then
    what the question is about, last what is kept: one line each, so that what
    waits for an answer is plain.
    """
    colon = convention("colon", ": ")
    lines: list[str] = []
    if upstream := plan.by_origin(UPSTREAM):
        head = _("to update") if check else _("updated")
        lines.append(head + colon + summary(upstream))
    if unknown := plan.by_origin(UNKNOWN):
        lines.append(summary(unknown))
    if both := plan.by_origin(BOTH):
        lines.append(_("edited in Anki, changed in kotogen") + colon + summary(both))
    if edited := plan.by_origin(EDITED):
        head = _("edited in Anki") if overwrite_edits else _("kept as edited in Anki")
        lines.append(head + colon + summary(edited))
    return lines


def _created(plan: Plan) -> str:
    """What the creation of a note type laid down, or what it would lay down."""
    cards = listed(plan.templates)
    fields = counted(len(plan.spec.fields), "{count} field", "{count} fields").format(
        count=len(plan.spec.fields))
    return counted(len(plan.templates),
                   "{fields}, card {cards}",
                   "{fields}, cards {cards}").format(fields=fields, cards=cards)


def _fields(count: int, done: bool) -> str:
    """What is said of the missing fields: added, or still to add.

    The count, not the names, which the changelog gives: it closes the line.
    """
    if done:
        line = counted(count, "{count} field added", "{count} fields added")
    else:
        line = counted(count, "{count} field to add", "{count} fields to add")
    return line.format(count=count)


def _reported(plan: Plan, new_cards: bool = True) -> list[str]:
    """What is reported without being touched, nor offered for repair.

    `new_cards` is false when the question about them follows.
    """
    lines = []
    # One sentence per entry, its lines cut by the translator: the column
    # shows them one under the other.
    if plan.unmatched:
        lines += _("Anki has more cards than kotogen: their HTML is neither\n"
                   "compared nor written. Rename them in Anki to line them up.").splitlines()
    for name in (plan.new_cards or []) if new_cards else []:
        lines.append(_("card {name} of kotogen, absent from this note type")
                     .format(name=_quoted(name)))
    for name in plan.extra_fields or []:
        lines += _("extra field {name}: kept, removing it\n"
                   "would erase its content on every note").format(
                       name=_quoted(name)).splitlines()
    return lines


# -- Display in columns --------------------------------------------------------

class _Column:
    """The name of the type on the left, what becomes of it on the right.

    The name opens the first line only, whatever it says; the others line up
    under it.
    """

    def __init__(self, name: str, width: int) -> None:
        self.head = name.ljust(width)
        self.indent = " " * width

    def take(self) -> str:
        """The indent of the next line: the name the first time, blank after."""
        head, self.head = self.head, self.indent
        return head

    def show(self, line: str) -> None:
        print(f"{self.take()}{line}".rstrip())


# -- Repository cards absent from the note type --------------------------------

def _note_count(notetype: str) -> int | None:
    """How many notes this type carries, or None if the question failed.

    It puts a figure on what adding a card costs.
    """
    try:
        return len(anki("findNotes", query=f'note:"{notetype}"') or [])
    except (ConnectionError, RuntimeError):
        return None


def _ask_new_cards(plan: Plan, column: _Column) -> list[str]:
    """Asks what to do with the absent repository cards; gives back those to add.

    Add, no (written to the `.env` whitelist, so it is not asked again), or
    later. Asked after the general question, apart from it.
    """
    from kotogen.exporter import choose

    add: list[str] = []
    if plan.new_cards:
        console.space()
    for name in plan.new_cards or []:
        count = _note_count(plan.notetype)
        if count is None:
            cost = _("creates one card to review per existing note")
        else:
            cost = counted(
                count,
                "creates {count} card to review, one per existing note",
                "creates {count} cards to review, one per existing note"
            ).format(count=count)
        column.show(_("card {name} of kotogen, absent from this note type")
                    .format(name=_quoted(name)))
        indent = column.indent
        answer = choose([
            ("a", _("add it ({cost})").format(cost=cost)),
            ("n", _("no, and stop reporting it (writes {var})")
             .format(var=cards_var(plan.spec.command))),
            ("l", _("later")),
        ], default="l", indent=f"{indent} ")
        if answer == "a":
            add.append(name)
        elif answer == "n":
            _keep_only(plan, name, indent)
    return add


def _keep_only(plan: Plan, dropped: str, indent: str = "   ") -> None:
    """Takes a card out of the whitelist of the settings, for good."""
    import os

    kept = [name for name, _sub in plan.spec.cards if name != dropped]
    variable = cards_var(plan.spec.command)
    try:
        settings.write(variable, ", ".join(kept))
    except OSError as exc:
        print(f"{indent}   " + _("Write failed: {error}").format(error=console.reason(exc)))
        return
    # For the rest of THIS run too: the following types are planned on it.
    os.environ[variable] = ", ".join(kept)
    print(f"{indent}   " + _("→ {name} removed (setting {var})")
          .format(name=dropped, var=variable))


def _and_list(names: list[str]) -> str:
    """Joins names: `Listening` and `Reading`, or `A`, `B` and `C`."""
    if len(names) < 2:
        return "".join(names)
    return _("{first} and {last}").format(first=listed(names[:-1]), last=names[-1])


def _ask_all(plans: list[Plan], width: int, force: bool,
             overwrite_edits: bool = False) -> dict[str, list[Change]]:
    """A single question for everything to rewrite; gives back what is kept.

    Only what nothing settles alone is asked about (`Plan.asked`). "yes" is the
    default, the backup making it reversible, but "no" where a face moved on both
    sides: Enter must not put the repository over an edit. `d` unfolds the
    diffs, `c` asks type by type.
    """
    from kotogen.exporter import choose

    outdated = [plan for plan in plans if plan.exists and plan.asked(overwrite_edits)]
    if not outdated or force:
        return {plan.notetype: plan.asked(overwrite_edits) for plan in outdated}

    question = _("Update {names}?").format(
        names=_and_list([plan.notetype for plan in outdated]))
    options = [("y", _("yes")), ("n", _("no")), ("d", _("detail"))]
    if len(outdated) > 1:
        options.append(("c", _("choose type by type")))
    default = "n" if any(plan.by_origin(BOTH) for plan in outdated) else "y"
    while True:
        console.space()
        answer = choose(options, question, default=default, indent="")
        if answer == "y":
            return {plan.notetype: plan.asked(overwrite_edits) for plan in outdated}
        if answer == "n":
            return {}
        if answer == "c":
            return {plan.notetype: _ask_one(plan, width, overwrite_edits)
                    for plan in outdated}
        for plan in outdated:
            column = _Column(plan.notetype, width)
            for line in _unfolded(plan.asked(overwrite_edits), context=2):
                column.show(line)


def _ask_one(plan: Plan, width: int, overwrite_edits: bool = False) -> list[Change]:
    """The same question, asked type by type after `[c]`, on the line of the type."""
    from kotogen.exporter import ask_choice

    asked = plan.asked(overwrite_edits)
    column = _Column(plan.notetype, width)
    while True:
        answer = ask_choice(_("update? [y] yes  [n] no  [d] detail"), "ynd",
                            default="n" if plan.by_origin(BOTH) else "y",
                            indent=column.take())
        if answer != "d":
            return list(asked) if answer == "y" else []
        for line in _unfolded(asked, context=2):
            print(f"{column.indent}{line}")


def _targets(args) -> set[str]:
    """Note types to handle, and validation of what the `.env` declares.

    `--only` wins over KOTOGEN_SKIP. Both are checked, so that a misspelt name
    is not silently ignored.
    """
    import sys

    from kotogen.cli import skipped_commands, wanted_cards

    only = set(args.only or ())
    if unknown := only - set(COMMANDS):
        sys.exit(counted(len(unknown),
                         "Unknown target: {names} (expected: {expected})",
                         "Unknown targets: {names} (expected: {expected})").format(
                      names=" ".join(sorted(unknown)), expected=" ".join(COMMANDS)))

    skipped = skipped_commands()
    if unknown := skipped - set(COMMANDS):
        sys.exit(counted(len(unknown),
                         "KOTOGEN_SKIP: unknown target: {names} (expected: {expected})",
                         "KOTOGEN_SKIP: unknown targets: {names} (expected: {expected})")
                 .format(names=" ".join(sorted(unknown)), expected=" ".join(COMMANDS)))

    for spec in SPECS:
        available = [name for name, _sub in spec.all_cards]
        if unknown := [n for n in wanted_cards(spec.command) if n not in available]:
            sys.exit(counted(len(unknown),
                             "{var}: unknown card: {names} (expected: {expected})",
                             "{var}: unknown cards: {names} (expected: {expected})").format(
                          var=cards_var(spec.command), names=listed(unknown),
                          expected=listed(available)))

    if only:
        return only
    if ignored := skipped & set(COMMANDS):
        print(_("Dropped by KOTOGEN_SKIP: {names}").format(
            names=" ".join(sorted(ignored))) + "\n")
    return set(COMMANDS) - skipped


def _review(args, root: Path, only: set[str], width: int) -> tuple[list[Plan], bool]:
    """The summary: one line per note type, before any question.

    What needs no question is done here, on the line announcing it: creating a
    type, adding a field, rewriting a face kotogen alone moved. Gives back the
    plans read, and whether something has been written.
    """
    import sys

    plans: list[Plan] = []
    for spec in SPECS:
        if spec.command not in only:
            continue
        try:
            plans.append(plan_for(spec, root))
        except FileNotFoundError as exc:
            print(spec.notetype.ljust(width)
                  + _("template missing ({error}) - skipped").format(
                      error=console.reason(exc)),
                  file=sys.stderr)
        except (ConnectionError, RuntimeError) as exc:
            # The message already names AnkiConnect.
            sys.exit(console.reason(exc, console.ALONE))

    # Everything is compared first: a short diff is unfolded only if it is alone.
    overwrite = args.overwrite_edits
    alone = sum(1 for plan in plans if plan.exists and plan.asked(overwrite)) == 1
    touched = False
    for plan in plans:
        column = _Column(plan.notetype, width)
        # See `resync`; `--check` writes nothing anywhere.
        if not args.check:
            resync(plan)
        if not plan.differs:
            column.show(_("up to date"))
            continue
        # Taken before the faces rewritten here leave the plan: `--diff` shows
        # them too, the short diff only what the question is about.
        shown = plan.changes if args.diff else plan.asked(overwrite)

        # One line per mover (see `_drifts`), the first followed by the
        # customisations, then the fields just written.
        groups: list[str] = []
        try:
            if not plan.exists:
                if not args.check:
                    create(plan)
                    touched = True
                head = _("to create") if args.check else _("created")
                # The colon is spaced by the language (see `i18n.convention`).
                groups.append(head + convention("colon", ": ") + _created(plan))
            else:
                groups += _drifts(plan, args.check, overwrite)
            parts = groups[:1]
            # The customisations close only a line reporting a difference, which
            # they may explain.
            if parts:
                parts += _customised(plan.spec.command)
            if plan.exists and plan.missing_fields:
                parts.append(_fields(len(plan.missing_fields), done=not args.check))
                if not args.check:
                    add_fields(plan)
                    touched = True
            if plan.exists and not args.check and (upstream := plan.by_origin(UPSTREAM)):
                update(plan, changes=upstream)
                touched = True
        except (ConnectionError, RuntimeError) as exc:
            print(column.take() + _("Failed: {error}").format(error=console.reason(exc)),
                  file=sys.stderr)
            continue

        lines = ([listed(parts)] if parts else []) + groups[1:]
        for line in lines + _reported(plan, new_cards=args.check or args.add_cards):
            column.show(line)
        # A short diff saves a `[d]`, but only for a lone type: with several it
        # would break up the summary.
        if alone or args.diff:
            for line in _inline_diff(shown, full_diff=args.diff):
                column.show(line)
    return plans, touched


def _customised(command: str) -> list[str]:
    """How many of this profile's customisations this note type carries.

    The count, never the list, which the customisation screen shows. Empty for a
    type left as the repository ships it.
    """
    count = len(card_templates.differences(command))
    if not count:
        return []
    return [counted(count,
                    "{count} customisation",
                    "{count} customisations").format(count=count)]


def run_deck(args) -> None:
    """Installs/updates the note types from `templates/`.

    Three blocks, never mixed: the state of every type, the question, then what
    was written, the type's name opening each line.
    """
    import sys

    from kotogen.anki.connect import UNREACHABLE, status

    if not status(refresh=True).connected:
        sys.exit(_(UNREACHABLE))

    root = templates_root()
    if root is None:
        sys.exit(_("`templates/` folder not found in {path}: kotogen runs from a "
                   "clone of its repository, installed with `pip install -e .`.")
                 .format(path=_quoted(str(settings.ROOT))))
    # Said only when read outside the current folder, where the path explains a
    # comparison that would look wrong. No blank line after it: the backup opens
    # its own.
    if not root.is_relative_to(Path.cwd()):
        print(_("Models read in {path}").format(path=root))

    only = _targets(args)
    if not only:
        print(_("Nothing to do: KOTOGEN_SKIP drops every note type."))
        return

    width = max(len(spec.notetype) for spec in SPECS if spec.command in only) + 3
    plans, touched = _review(args, root, only, width)
    if args.check:
        return

    # -- What is asked for: rewriting what already exists ---------------------
    accepted = _ask_all(plans, width, args.yes, args.overwrite_edits)
    added: dict[str, list[str]] = {}
    for plan in plans:
        if plan.exists and plan.new_cards:
            added[plan.notetype] = (list(plan.new_cards) if args.add_cards
                                    else _ask_new_cards(plan, _Column(plan.notetype, width)))

    saved = False

    def save_once() -> None:
        """Snapshot of the templates, just before the first rewrite.

        An edit made in Anki exists ONLY there, so the snapshot is its one copy.
        Taken once, and only when an accepted change is about to be written.
        """
        nonlocal saved
        if saved:
            return
        saved = True
        from kotogen.anki import backup
        console.space()
        backup.before("deck", only=sorted(only))

    # -- What has been written: one line per type touched ---------------------
    #
    # Nothing for the types left as they are: the summary and the answer said it.
    for plan in plans:
        changes = accepted.get(plan.notetype) or []
        cards = added.get(plan.notetype) or []
        if not plan.exists or (not changes and not cards):
            continue
        column = _Column(plan.notetype, width)
        # From here on, `new_cards` holds the cards decided, not those absent.
        plan.new_cards = cards
        try:
            save_once()
            update(plan, add_cards=bool(cards), changes=changes)
        except (ConnectionError, RuntimeError) as exc:
            print(column.take() + _("Failed: {error}").format(error=console.reason(exc)),
                  file=sys.stderr)
            continue
        touched = True
        done = [_("updated")] if changes else []
        done += [_("card {name} added").format(name=_quoted(name)) for name in cards]
        column.show(listed(done))

    # Only after a write, and only what the lines above do not say: the sync.
    if touched:
        console.space()
        print(_("Remember to synchronise Anki (it may ask for a full sync: "
                "that is normal)."))
