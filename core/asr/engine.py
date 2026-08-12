"""The speech-to-text seam.

Every engine — local CTranslate2, local OpenVINO, hosted Groq — is used
through this one shape, so the pipeline never branches on which one is in use.

Engines are constructed cheaply and load lazily: the app must start instantly
even when the model behind it is a gigabyte that has not been downloaded yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class EngineCaps:
    """What the pipeline is allowed to assume about an engine."""

    #: Cheap enough to call on every closed speech segment while the user is
    #: still talking. False for anything billed or rate limited per request.
    supports_pipelining: bool
    #: Human-readable, for logs and the timing line.
    label: str
    #: True when a transcription leaves this machine.
    is_remote: bool = False


@runtime_checkable
class AsrEngine(Protocol):
    caps: EngineCaps

    def warmup(self) -> None:
        """Load weights and run a throwaway inference. Safe to call twice."""

    def transcribe(self, audio) -> str:
        """Return text for float32 mono 16 kHz samples. "" when nothing heard."""
