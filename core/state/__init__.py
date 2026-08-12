"""Dictation state: a pure reducer plus the events and actions around it."""

from core.state.actions import (
    BarState,
    DiscardCapture,
    PlayPing,
    RecordMode,
    RunPipeline,
    ShowBar,
    StartCapture,
    StopCaptureAndFinalize,
    WarnSessionCap,
)
from core.state.events import Binding, Cancel, Committed, Down, Failed, Tick, Up
from core.state.machine import (
    AWAITING_LOCK,
    FINALIZING,
    IDLE,
    RECORDING,
    DictationMachine,
)

__all__ = [
    "AWAITING_LOCK",
    "BarState",
    "Binding",
    "Cancel",
    "Committed",
    "DictationMachine",
    "DiscardCapture",
    "Down",
    "FINALIZING",
    "Failed",
    "IDLE",
    "PlayPing",
    "RECORDING",
    "RecordMode",
    "RunPipeline",
    "ShowBar",
    "StartCapture",
    "StopCaptureAndFinalize",
    "Tick",
    "Up",
    "WarnSessionCap",
]
