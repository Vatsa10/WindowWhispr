"""Spoken commands that act on the target app instead of becoming text.

Only *trailing* commands are recognized, and only as an exact final phrase.
"Then press enter on the form" is a sentence about pressing enter; "send it to
the team, press enter" is an instruction. Requiring the phrase at the very end
is what keeps the two apart without any understanding of the sentence.

Applied after cleanup, so the model cannot quietly rewrite the cue away.
"""

from __future__ import annotations

import string
from dataclasses import dataclass

#: Trailing phrase -> key to send. Longest phrases are matched first.
COMMANDS: dict[str, str] = {
    "press enter": "enter",
    "hit enter": "enter",
    "press return": "enter",
    "new tab": "tab",
    "press tab": "tab",
}

_TRAILING = string.punctuation + string.whitespace


@dataclass(frozen=True)
class ParsedCommand:
    """The text to paste, plus any key to press afterwards."""

    text: str
    key: str | None = None


def parse(text: str) -> ParsedCommand:
    """Split a trailing spoken command off the end of ``text``."""
    body = (text or "").rstrip(_TRAILING)
    lowered = body.lower()
    for phrase in sorted(COMMANDS, key=len, reverse=True):
        if lowered.endswith(phrase):
            head = body[: len(body) - len(phrase)]
            # The cue must be its own phrase, not the tail of a longer word.
            if head and head[-1].isalnum():
                continue
            stripped = head.rstrip(_TRAILING)
            if not stripped:
                # The whole utterance was the command; there is nothing to
                # paste, but the keypress still stands.
                return ParsedCommand("", COMMANDS[phrase])
            return ParsedCommand(stripped, COMMANDS[phrase])
    return ParsedCommand(text or "", None)
