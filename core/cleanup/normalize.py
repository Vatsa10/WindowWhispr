"""Deterministic text massaging around the model call.

The LLM does the smart, context-aware work; this module guarantees the
mechanical parts. It deliberately never touches punctuation-name words or
self-correction cues ("actually", "scratch that") — those are context-sensitive
and stay the model's job (a bare regex would misfire on "I actually liked it").

Ported from WhimprFlow's ``whimpr-core/src/cleanup/mod.rs``.
"""

from __future__ import annotations

# Placeholder tokens for user-requested line breaks. Explicit spoken cues are
# converted to these BEFORE the model, because a small model reliably passes an
# opaque marker through unchanged but often "helpfully" rewrites a real newline
# into a period or a space. post_process() turns them back into real breaks.
NL_SENTINEL = "[[NL]]"
NP_SENTINEL = "[[NP]]"

# Longest phrases first so "new paragraph" wins over "new". Matched as whole
# words, case-insensitively. Padded with spaces so the marker never fuses to a
# neighbouring word.
_LAYOUT_CUES_PRE: list[tuple[str, str]] = [
    ("start a new paragraph", f" {NP_SENTINEL} "),
    ("new paragraph", f" {NP_SENTINEL} "),
    ("line break", f" {NL_SENTINEL} "),
    ("next line", f" {NL_SENTINEL} "),
    ("new line", f" {NL_SENTINEL} "),
]

# Belt-and-suspenders pass for any literal cue word the pre-pass or the model
# left behind.
_LAYOUT_CUES_POST: list[tuple[str, str]] = [
    ("start a new paragraph", "\n\n"),
    ("new paragraph", "\n\n"),
    ("line break", "\n"),
    ("next line", "\n"),
    ("new line", "\n"),
]


def pre_normalize_layout(raw: str) -> str:
    """Turn explicit spoken layout cues into break sentinels, before the model.

    Correction cues are intentionally excluded — they stay the model's job.
    """
    return _replace_cues(raw, _LAYOUT_CUES_PRE)


def post_process(text: str) -> str:
    """Strip a stray code fence, restore break sentinels, tidy whitespace."""
    stripped = _strip_code_fence(text)
    restored = stripped.replace(NP_SENTINEL, "\n\n").replace(NL_SENTINEL, "\n")
    return _cap_and_trim_lines(_replace_cues(restored, _LAYOUT_CUES_POST))


def _strip_code_fence(s: str) -> str:
    """Drop a wrapping ``` code fence if the model added one."""
    t = s.strip()
    if not t.startswith("```"):
        return t
    nl = t.find("\n")
    if nl == -1:
        return t
    after = t[nl + 1:]
    end = after.rfind("```")
    body = after[:end] if end != -1 else after
    return body.strip()


def _replace_cues(text: str, cues: list[tuple[str, str]]) -> str:
    """Replace whole-word layout cues, swallowing one space after each.

    Hand-rolled rather than regex because the boundary rule is "not
    alphanumeric" on both sides and the table is ordered longest-first — a
    scanner expresses that directly and stays easy to reason about.
    """
    n = len(text)
    out: list[str] = []
    i = 0
    while i < n:
        if i == 0 or not text[i - 1].isalnum():
            for phrase, replacement in cues:
                end = i + len(phrase)
                if (
                    end <= n
                    and text[i:end].lower() == phrase
                    and (end == n or not text[end].isalnum())
                ):
                    out.append(replacement)
                    i = end
                    if i < n and text[i] == " ":
                        i += 1  # swallow the space after the cue
                    break
            else:
                out.append(text[i])
                i += 1
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _cap_and_trim_lines(s: str) -> str:
    """Trim each line, allow at most one blank line in a row, strip the ends.

    This both tidies the spaces the sentinels leave behind (" [[NL]] " -> "\\n")
    and caps runaway paragraph breaks.
    """
    lines: list[str] = []
    blanks = 0
    for line in s.split("\n"):
        stripped = line.strip()
        if stripped:
            blanks = 0
            lines.append(stripped)
        else:
            blanks += 1
            if blanks <= 1:
                lines.append("")
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)
