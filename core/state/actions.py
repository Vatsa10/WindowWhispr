"""Side effects the state machine asks the shell to perform.

The machine itself touches no microphone, clipboard or UI — it only says what
should happen. Ported from WhimprFlow's ``whimpr-core/src/state/actions.rs``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RecordMode(str, Enum):
    #: Recording only while the key is held.
    PUSH_TO_TALK = "push_to_talk"
    #: Recording until the key is pressed again.
    LOCKED = "locked"


class BarState(str, Enum):
    """What the overlay pill shows."""

    IDLE = "idle"
    RECORDING = "recording"
    LOCKED = "locked"
    TRANSCRIBING = "transcribing"
    DONE = "done"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass(frozen=True)
class StartCapture:
    session: int
    mode: RecordMode


@dataclass(frozen=True)
class StopCaptureAndFinalize:
    session: int


@dataclass(frozen=True)
class DiscardCapture:
    """Stop recording and throw the audio away — nothing gets pasted."""

    session: int


@dataclass(frozen=True)
class RunPipeline:
    session: int


@dataclass(frozen=True)
class ShowBar:
    state: BarState


@dataclass(frozen=True)
class PlayPing:
    pass


@dataclass(frozen=True)
class WarnSessionCap:
    pass
