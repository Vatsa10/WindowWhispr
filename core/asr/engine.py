"""The speech-to-text seam.

Every engine — local CTranslate2, local OpenVINO, hosted Groq — is used
through this one shape, so the pipeline never branches on which one is in use.

Engines are constructed cheaply and load lazily: the app must start instantly
even when the model behind it is a gigabyte that has not been downloaded yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


def join_segments(segments) -> str:
    """The text of a rich transcription, as ``transcribe`` returns it.

    One definition, used by every engine, so the two entry points cannot drift
    apart -- which would make every threshold tuned against one of them wrong
    for the other.
    """
    return " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()


@dataclass(frozen=True)
class Segment:
    """One decoded stretch of speech, with what the decoder thought of it.

    The scores are what separate a transcript from a hallucination, and a
    bare string throws them away. Engines that cannot supply them return the
    defaults below, which are deliberately neutral: they pass every threshold,
    so an engine without confidence behaves exactly as it did before.
    """

    text: str
    #: Mean log probability of the tokens. Nearer zero is more confident.
    avg_logprob: float = 0.0
    #: How sure the decoder is that this stretch was not speech at all.
    no_speech_prob: float = 0.0
    #: The language actually decoded, when the engine reports one.
    language: str = ""


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
        """Return text for float32 mono 16 kHz samples. "" when nothing heard.

        Always equal to the joined text of ``transcribe_rich``.
        """

    def transcribe_rich(self, audio):
        """The same transcription, with per-segment decoder scores."""
