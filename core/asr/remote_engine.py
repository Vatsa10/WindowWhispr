"""Hosted speech-to-text (Groq Whisper).

Kept behind the same interface as the local engines, and marked as neither
pipelinable nor local: it is billed and rate limited per request, so the
session sends it one request with the whole utterance instead of one per
speech segment.
"""

from __future__ import annotations

from core.asr.engine import EngineCaps
from core.groq_client import DEFAULT_ASR_MODEL


class GroqEngine:
    def __init__(self, model: str = DEFAULT_ASR_MODEL, sample_rate: int = 16000):
        self._model = model
        self._sample_rate = sample_rate
        self.caps = EngineCaps(
            supports_pipelining=False,
            label=f"Groq {model}",
            is_remote=True,
        )

    def warmup(self) -> None:
        """Nothing to load. The first request pays for DNS and TLS."""

    def transcribe(self, audio) -> str:
        from core import secrets
        from core.groq_client import transcribe

        return transcribe(
            audio,
            api_key=secrets.get_key("groq_api_key"),
            model=self._model,
            sample_rate=self._sample_rate,
        )
