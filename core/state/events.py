"""Inputs to the dictation state machine.

Ported from WhimprFlow's ``whimpr-core/src/state/events.rs``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Binding(str, Enum):
    """Which shortcut produced a key event."""

    #: Hold to talk (Right Ctrl by default); tap twice to lock hands-free.
    PUSH_TO_TALK = "push_to_talk"
    #: The legacy press-to-start / press-to-stop chord.
    HANDS_FREE = "hands_free"


@dataclass(frozen=True)
class Down:
    binding: Binding
    at_ms: int


@dataclass(frozen=True)
class Up:
    binding: Binding
    at_ms: int


@dataclass(frozen=True)
class Cancel:
    """Esc: stop and throw the session away."""

    at_ms: int


@dataclass(frozen=True)
class Committed:
    """The pipeline pasted the text for this session."""

    session: int


@dataclass(frozen=True)
class Failed:
    """The pipeline gave up on this session."""

    session: int


@dataclass(frozen=True)
class Tick:
    """Time passing. The machine holds no clock of its own."""

    now_ms: int
