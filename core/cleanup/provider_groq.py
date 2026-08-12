"""Cleanup via a Groq chat model.

Sends the exact same message list as the local provider — same system prompt,
same few-shot turns — so the deterministic gates judge both by one standard.
A hosted 70B model is markedly better at spoken self-corrections than anything
that runs on a laptop, and it removes the local model from the latency budget.

The transcript leaves the machine when this is selected. That is the trade the
user makes by choosing it, and the UI says so.
"""

from __future__ import annotations

from core.groq_client import DEFAULT_CHAT_MODEL, chat


class GroqCleanupProvider:
    id = "groq"

    #: A hosted model this size follows the system prompt without the full
    #: demonstration set. Measured: identical output, ~220 fewer tokens per
    #: request — which matters, because the free tier's real ceiling is tokens
    #: per minute (8000), not requests per minute.
    few_shot = 4

    def __init__(self, model: str = DEFAULT_CHAT_MODEL, max_tokens: int = 1024):
        self._model = model
        self._max_tokens = int(max_tokens)

    def ready(self) -> bool:
        from core import secrets

        return secrets.has_key("groq_api_key")

    def cleanup(self, messages) -> str:
        from core import secrets

        return chat(
            messages,
            api_key=secrets.get_key("groq_api_key"),
            model=self._model,
            max_tokens=self._max_tokens,
        )
