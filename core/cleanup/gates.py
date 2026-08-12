"""Deterministic cleanup gates — the always-on guard against over-editing.

These run on every cleanup output before it is pasted. On any failure the caller
falls back to the raw transcript: cleanup is an enhancement, never a gate on the
user's words.

Ported from WhimprFlow's ``whimpr-core/src/cleanup/gates.rs``.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from enum import Enum

from core.cleanup.levels import CleanupLevel

# Phrases cleanup should never *introduce* — the model answering or chatting
# instead of transcribing. Matched case-insensitively at the start of the output.
BANNED_PREFIXES = (
    "sure,",
    "sure!",
    "here is",
    "here's",
    "i'm sorry",
    "i am sorry",
    "as an ai",
    "certainly",
    "of course",
    "i cannot",
    "i can't help",
)

# Gross length-change limits. Generous on purpose: self-corrections shorten text
# and structural formatting (numbered lists, paragraph breaks) lengthens it —
# both legitimate — so only extremes are flagged.
MAX_SHRINK = 0.55
MAX_GROWTH = 1.6

_PUNCT = string.punctuation
_PUNCT_KEEP_AT_HASH = _PUNCT.replace("@", "").replace("#", "")


class GateReason(str, Enum):
    EDIT_RATIO_TOO_HIGH = "edit_ratio_too_high"
    LOST_ENTITY = "lost_entity"
    OVER_DELETION = "over_deletion"
    HALLUCINATION = "hallucination"
    BANNED_PATTERN = "banned_pattern"


@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    reason: GateReason | None = None
    detail: str = ""

    def __bool__(self) -> bool:
        return self.passed


PASS = GateVerdict(passed=True)


def evaluate(raw: str, cleaned: str, level: CleanupLevel) -> GateVerdict:
    """Check a cleanup output against the raw transcript for the given level."""
    # None never invokes the model, so there is nothing to gate.
    if level.bypasses_llm():
        return PASS

    # 1) Introduced assistant-style / greeting prefixes.
    cleaned_lc = cleaned.lstrip().lower()
    raw_lc = raw.lower()
    for prefix in BANNED_PREFIXES:
        if cleaned_lc.startswith(prefix) and prefix not in raw_lc:
            return GateVerdict(False, GateReason.BANNED_PATTERN, prefix)

    # 2) Must-preserve entities present in raw must survive in cleaned.
    for entity in must_preserve_entities(raw):
        if entity not in cleaned:
            return GateVerdict(False, GateReason.LOST_ENTITY, entity)

    # 3) Gross length changes.
    raw_len = max(len(raw), 1)
    clean_len = len(cleaned)
    shrink = (raw_len - clean_len) / raw_len
    if shrink > MAX_SHRINK:
        return GateVerdict(False, GateReason.OVER_DELETION, f"{shrink:.2f}")
    if clean_len > raw_len * MAX_GROWTH:
        return GateVerdict(False, GateReason.HALLUCINATION, f"{clean_len / raw_len:.2f}")

    # 4) Novelty: how many output words were never spoken.
    ratio = novelty_ratio(raw, cleaned)
    ceiling = level.max_novelty_ratio()
    if ratio > ceiling:
        return GateVerdict(
            False,
            GateReason.EDIT_RATIO_TOO_HIGH,
            f"{ratio:.2f} > {ceiling:.2f}",
        )

    return PASS


def must_preserve_entities(text: str) -> list[str]:
    """Tokens that must survive cleanup verbatim.

    URLs, emails, and *substantial* digit strings (phone numbers, order ids,
    years, versions — 4+ digits). Short numbers (1-3 digits) are deliberately
    NOT protected: they are routinely and correctly dropped by self-corrections
    ("meet at 2, actually 3") and by number normalization, and protecting them
    made the gate reject legitimate cleanups and fall back to raw.
    """
    out: list[str] = []
    for token in text.split():
        trimmed = token.strip(_PUNCT_KEEP_AT_HASH)
        if not trimmed:
            continue
        is_url = "://" in trimmed or ".com" in trimmed or "@" in trimmed
        digits = sum(1 for c in trimmed if c.isdigit())
        if is_url or digits >= 4:
            out.append(trimmed)
    return out


def _normalize_tok(token: str) -> str:
    """Lowercase and strip surrounding punctuation, so "3." == "3"."""
    return token.strip(_PUNCT).lower()


def novelty_ratio(raw: str, cleaned: str) -> float:
    """Fraction of output words that were never spoken.

    Filler deletion and casing/punctuation contribute nothing; a genuine rewrite
    or a hallucination (new content words) drives this up. A couple of
    legitimate normalizations ("seven" -> "7") add a little, which the per-level
    ceiling leaves room for.
    """
    raw_set = {t for t in (_normalize_tok(w) for w in raw.split()) if t}
    clean_toks = [t for t in (_normalize_tok(w) for w in cleaned.split()) if t]
    if not clean_toks:
        return 0.0
    novel = sum(1 for t in clean_toks if t not in raw_set)
    return novel / len(clean_toks)
