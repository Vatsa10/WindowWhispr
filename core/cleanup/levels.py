"""Auto Cleanup levels — how aggressively the LLM may edit a transcript.

``NONE`` bypasses the model entirely (raw ASR is pasted). The others append a
modifier to the shared system prompt. Light is the default deliberately: an
aggressive default is the top source of "it changed what I said" complaints.

Ported from WhimprFlow's ``whimpr-core/src/cleanup/levels.rs``.
"""

from __future__ import annotations

from enum import Enum

_MODIFIERS = {
    "none": "",
    "light": (
        "Be conservative: apply the allowed edits minimally. When unsure "
        "whether to edit, leave the text as spoken."
    ),
    "medium": (
        "You may also tighten wording for clarity and conciseness, but never "
        "change the meaning."
    ),
    "high": (
        "You may rewrite phrasing for brevity and polish while strictly "
        "preserving every fact, name, number, and the speaker's intent."
    ),
}

# Ceiling on the *novelty ratio* (fraction of output words that were never
# spoken) that the deterministic gate tolerates. Filler deletion and punctuation
# contribute nothing; number/spoken-punctuation normalization adds a little, so
# Light leaves headroom for that while still catching a full rewrite.
_NOVELTY = {"none": 0.0, "light": 0.34, "medium": 0.55, "high": 0.85}


class CleanupLevel(str, Enum):
    NONE = "none"
    LIGHT = "light"
    MEDIUM = "medium"
    HIGH = "high"

    def bypasses_llm(self) -> bool:
        """True when no model runs and the raw transcript is used verbatim."""
        return self is CleanupLevel.NONE

    def modifier(self) -> str:
        """Text appended to the shared system prompt for this level."""
        return _MODIFIERS[self.value]

    def max_novelty_ratio(self) -> float:
        return _NOVELTY[self.value]

    @classmethod
    def parse(cls, value, default: "CleanupLevel" = None) -> "CleanupLevel":
        """Lenient lookup for config values; unknown strings fall back."""
        default = default or cls.LIGHT
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return default


DEFAULT_LEVEL = CleanupLevel.LIGHT
