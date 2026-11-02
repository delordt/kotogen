"""Cards to proofread: what came out damaged, and what becomes of it.

A card the model returned keepable but faulty (a translation short of lines, a
missing transcript, the answer among the decoys) is paid for: it is neither
dropped out of hand nor exported unsaid. **A card kept under a "!!"
(`console.failed`) is a card to proofread**; a "!" (`console.aside`) means what
remains is good.

The `KOTOGEN_PROOFREAD` mode decides: `keep` exports them as they are, `tag`
marks them with a `Check::` tag, `drop` holds them back, `ask` (the default)
asks once just before sending. Tagging is a choice and not part of `keep`: it
records a generation accident, which would sit unasked in Anki's tag tree for
months. A tag rather than note ids, which a TSV lacks and `addNotes` returns as
None for a duplicate. It is set at sorting time only: the TSV is written as it
goes, and an interrupted pass would leave tagged cards nobody asked for.
"""

from __future__ import annotations

from kotogen import console, settings
from kotogen.i18n import _, agreed, counted, listed, quoted as _quoted

ENV_VAR = "KOTOGEN_PROOFREAD"

# The dictionary's family of tags (`Check::Reading`, `Check::Word`, see
# `dictionary.READING_TAG`), so that one search finds them all. Filed in the
# collection, so English whatever the language of the cards or the interface.
TAG_PREFIX = "Check::"

# The faults recorded, from the widest to the narrowest. Each names what the
# CARD lacks rather than what failed in the answer: the name is what is searched
# in Anki weeks later.
TRANSLATION_TAG = f"{TAG_PREFIX}Translation"
TRANSCRIPT_TAG = f"{TAG_PREFIX}Transcript"
CHOICES_TAG = f"{TAG_PREFIX}Choices"

# The reasons the comprehension cards are marked for, shared by listening and
# reading. Held in English, translated where displayed (`reasons`): a
# module-level `_()` would resolve the language before `cli.main()` loads it.
UNALIGNED_TRANSLATION = "translation not lined up"
DUPLICATED_ANSWER = "right answer duplicated among the decoys"

# In the order the "p" key of the settings cycles through them: the default
# first, then from the most discreet to the most expeditious.
MODES = ("ask", "keep", "tag", "drop")

DEFAULT_MODE = MODES[0]

# The yes/no spellings one types from memory, which the default would silently
# swallow. "yes" means `keep` rather than `tag`: it puts nothing in Anki unasked.
_SYNONYMS = {"1": "keep", "true": "keep", "yes": "keep", "on": "keep",
             "always": "keep",
             "0": "drop", "false": "drop", "no": "drop", "off": "drop",
             "never": "drop"}

# What a card remembers of its fault: the tag to set if one is asked for, and
# the reason as the console said it, for the summary line. Underscored keys do
# not go out on export (see `exporter._tsv_row`).
KEY_TAGS = "_proofread_tags"
KEY_REASON = "_proofread"

# None: nothing chosen this session, the setting decides.
_mode: str | None = None


# -- The mode in force --------------------------------------------------------

def by_mode(value: str) -> str:
    """The mode of that name, or the default if the name matches none.

    Never an error, as in `video_clip.by_mode`: a stale setting must not stop the
    command.
    """
    wanted = (value or "").strip().lower()
    if wanted in MODES:
        return wanted
    return _SYNONYMS.get(wanted, DEFAULT_MODE)


def modes() -> tuple[str, ...]:
    """The accepted names, in display order."""
    return MODES


def mode() -> str:
    """The mode in force: the session's, failing that the settings'."""
    if _mode is not None:
        return _mode
    return by_mode(settings.raw(ENV_VAR))


def set_mode(value: str) -> None:
    """Fix the mode for the current session, without rewriting the settings."""
    global _mode
    _mode = by_mode(value)


def cycle() -> str:
    """Move to the next mode, wrapping to the first after the last."""
    following = MODES[(MODES.index(mode()) + 1) % len(MODES)]
    set_mode(following)
    return following


def describe() -> str:
    """What the settings screen shows facing the setting."""
    return _(mode())


# -- Mark, then sort ----------------------------------------------------------

def mark(cards, tag: str, reason: str) -> None:
    """Record the fault on these cards: its tag, and the reason that says why.

    Writes nothing into "Tags", unlike `dictionary.tag_card`: `sort_out` decides
    later. A fault already recorded on a card is not recorded twice.
    """
    for card in cards:
        for key, value in ((KEY_TAGS, tag), (KEY_REASON, reason)):
            kept = card.setdefault(key, [])
            if value not in kept:
                kept.append(value)


def marked(cards) -> list[dict]:
    """Those carrying a fault, in the order they were produced in."""
    return [card for card in cards if card.get(KEY_REASON)]


def tags(cards) -> list[str]:
    """The tags these cards would receive, without duplicates and in order.

    In order of appearance, like `reasons`: both are read on one summary line.
    """
    seen: list[str] = []
    for card in cards:
        for tag in card.get(KEY_TAGS, []):
            if tag not in seen:
                seen.append(tag)
    return seen


def apply_tags(cards) -> None:
    """Put the recorded tags into the "Tags" field, next to those already there.

    A tag already present is not doubled. Called by `sort_out` only, the one
    place that knows the tag was asked for.
    """
    for card in cards:
        present = str(card.get("Tags", "")).split()
        for tag in card.get(KEY_TAGS, []):
            if tag not in present:
                present.append(tag)
        if present:
            card["Tags"] = " ".join(present)


def _applied(cards) -> list[str]:
    """The tags these cards actually carry: none until `apply_tags` has run."""
    return [tag for tag in tags(cards)
            if any(tag in str(card.get("Tags", "")).split() for card in cards)]


def reasons(cards) -> str:
    """The reasons of these cards, gathered into a fragment of a sentence.

    Without duplicates and in order of appearance. A reason is recorded in
    English (`UNALIGNED_TRANSLATION`) and translated here.
    """
    seen: list[str] = []
    for card in cards:
        for reason in card.get(KEY_REASON, []):
            if reason not in seen:
                seen.append(reason)
    return listed(_(reason) for reason in seen)


def resolve(args) -> str:
    """The mode that applies to this pass: the option, failing that the setting.

    Only the commands that produce cards carry `--proofread`, which holds for one
    pass and is never written to the settings.
    """
    return by_mode(asked) if (asked := getattr(args, "proofread", None)) else mode()


def sort_out(cards: list[dict], args=None) -> tuple[list[dict], list[dict]]:
    """Apply the mode to the marked cards. Returns (kept, dropped).

    Asks nothing when no card is marked. The tags are set here only: the TSV
    lines went out without them, and `exporter.finish` rewrites them right after.
    """
    to_proofread = marked(cards)
    if not to_proofread:
        return cards, []
    if (chosen := resolve(args)) == "ask":
        chosen = _ask(to_proofread)
    if chosen == "drop":
        return [card for card in cards if not card.get(KEY_REASON)], to_proofread
    if chosen == "tag":
        apply_tags(to_proofread)
    return cards, []


def _ask(to_proofread: list[dict]) -> str:
    """Put the question, once, and return the mode chosen.

    Asked just before the closing block, once all the command produced is known.
    Tagging comes LAST: it is what `choose` returns when nobody can answer, and it
    neither drops paid-for cards nor keeps them without a trace.
    """
    from kotogen.exporter import choose

    console.space()
    what = reasons(to_proofread)
    count = len(to_proofread)
    question = counted(count, "{count} card to proofread ({reasons})",
                       "{count} cards to proofread ({reasons})")
    answer = choose([("d", counted(count, "drop it", "drop them")),
                     ("k", counted(count, "keep it", "keep them")),
                     ("t", counted(count, "tag it", "tag them"))],
                    question.format(count=count, reasons=what))
    return {"d": "drop", "k": "keep", "t": "tag"}[answer]


def summary(kept: list[dict], dropped: list[dict]) -> list[str]:
    """The line of the closing block, if there is anything to say about it.

    One line, shaped like the other `extras`: the tag to search in Anki, and the
    reasons. Kept without a tag, it says so: it is then the only trace left.
    """
    if dropped:
        count = len(dropped)
        line = counted(count,
                       "{count} card to proofread dropped ({reasons})",
                       "{count} cards to proofread dropped ({reasons})")
        return [f"   {line.format(count=count, reasons=reasons(dropped))}"]
    if to_proofread := marked(kept):
        count = len(to_proofread)
        applied = _applied(to_proofread)
        # Fragments of the sentence below, agreed with its count.
        if applied:
            mark = agreed(count, "tagged {tags}").format(tags=_quoted(" ".join(applied)))
        else:
            mark = agreed(count, "kept without a tag")
        line = counted(count,
                       "{count} card to proofread, {mark} ({reasons})",
                       "{count} cards to proofread, {mark} ({reasons})")
        return [f"   {line.format(count=count, mark=mark, reasons=reasons(to_proofread))}"]
    return []
