"""On-device cleanup provider, backed by the OpenVINO GenAI LLM.

WinWhispr already keeps a warm ``Reformatter`` pipeline for the clipboard reformat
hotkey; this reuses it rather than loading a second copy of the same model into
memory. Keeping one pipeline also means its lock serializes the two features, so
they can never generate concurrently.

The chat turns are rendered as ChatML here rather than handed to the pipeline's
chat template, because the request is multi-turn (few-shot demonstrations) and
``LLMPipeline.generate`` takes a single string.
"""

from __future__ import annotations

#: Trailing tokens a model may emit that are envelope, not content.
_STOP_MARKERS = ("<|im_end|>", "<|endoftext|>", "</s>")


def render_chatml(messages) -> str:
    """Render cleanup messages as ChatML, primed for the assistant's reply."""
    parts = [f"<|im_start|>{m.role}\n{m.content}<|im_end|>\n" for m in messages]
    parts.append("<|im_start|>assistant\n")
    return "".join(parts)


def strip_envelope(text: str) -> str:
    """Drop chat-template scaffolding and transcript tags the model echoed."""
    out = text or ""
    for marker in _STOP_MARKERS:
        idx = out.find(marker)
        if idx != -1:
            out = out[:idx]
    out = out.strip()
    # Some small models mirror the <USER_MESSAGE> wrapper back at us.
    if out.startswith("<USER_MESSAGE>"):
        out = out[len("<USER_MESSAGE>"):]
    if out.endswith("</USER_MESSAGE>"):
        out = out[: -len("</USER_MESSAGE>")]
    return out.strip()


class LocalCleanupProvider:
    """Cleanup via the local OpenVINO model. Never raises for "not ready"."""

    id = "local"

    def __init__(self, reformatter, max_new_tokens: int = 400):
        self._reformatter = reformatter
        self._max_new_tokens = int(max_new_tokens)

    def ready(self) -> bool:
        return getattr(self._reformatter, "status", "") == "ready"

    def cleanup(self, messages) -> str:
        """Return cleaned text for the given message list."""
        raw = self._reformatter.generate(
            render_chatml(messages),
            max_new_tokens=self._max_new_tokens,
            apply_chat_template=False,
        )
        return strip_envelope(raw)
