"""Global preferences: value read from the settings, toggleable for the session.

Automatic sending to Anki and verbose mode start from the settings file
(`KOTOGEN_AUTO_SEND=1`, `KOTOGEN_VERBOSE=1`); a key of the interactive menu
changes them for the session without rewriting the file.
"""

from __future__ import annotations

from kotogen import settings

# None: nothing chosen this session, the settings file decides.
_auto_send: bool | None = None
_verbose: bool | None = None


def auto_send() -> bool:
    """True if cards should go to Anki without asking."""
    if _auto_send is not None:
        return _auto_send
    return settings.flag("KOTOGEN_AUTO_SEND")


def set_auto_send(value: bool) -> None:
    """Force automatic sending (or its absence) for the current session."""
    global _auto_send
    _auto_send = value


def verbose() -> bool:
    """True if the assistant should echo the equivalent command when it is done.

    False by default: the line teaches the CLI at first, then only repeats itself.
    """
    if _verbose is not None:
        return _verbose
    return settings.flag("KOTOGEN_VERBOSE")


def set_verbose(value: bool) -> None:
    """Show (or silence) the equivalent command for the current session."""
    global _verbose
    _verbose = value
