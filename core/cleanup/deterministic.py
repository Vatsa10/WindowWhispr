"""Cleanup without a model.

Most of what dictation needs is not intelligence, it is bookkeeping: drop the
"um", collapse the stutter, turn "period" into ".", capitalize the sentence.
Rules do that in microseconds, offline, identically every time — where the
smallest local model measured three seconds and still got it wrong.

What rules cannot do is decide *meaning*: whether "actually" corrects the
previous clause or merely intensifies it needs context. Those cases are left
alone here and are the only reason to turn an LLM on at all.

Everything in this module is pure text in, text out.
"""

from __future__ import annotations

import re

#: Fillers safe to delete wherever they appear as standalone words. Words whose
#: removal can change meaning ("like" as a verb, "right" as agreement) are not
#: here — a wrong deletion is worse than a surviving "um".
HARD_FILLERS = ("um", "uh", "erm", "uhh", "umm", "hmm", "mm")

#: Fillers only removed at the start of a sentence, where they are reliably
#: throat-clearing rather than content ("So, I think…" vs "…so I left").
LEADING_FILLERS = ("so", "well", "okay", "ok", "right", "now")

#: Spoken punctuation. Order matters: longer phrases must be tried first, or
#: "exclamation" would match inside "exclamation point".
SPOKEN_PUNCTUATION = [
    ("exclamation point", "!"),
    ("exclamation mark", "!"),
    ("question mark", "?"),
    ("full stop", "."),
    ("open parenthesis", "("),
    ("close parenthesis", ")"),
    ("semicolon", ";"),
    ("colon", ":"),
    ("comma", ","),
    ("period", "."),
    ("dash", "—"),
    ("hyphen", "-"),
]

_WORD = r"(?<![\w'])%s(?![\w'])"


def clean(text: str) -> str:
    """Apply every deterministic rule, in the order they must run."""
    if not text or not text.strip():
        return ""
    out = text
    out = remove_fillers(out)
    out = collapse_stutters(out)
    out = apply_spoken_punctuation(out)
    out = fix_spacing(out)
    out = capitalize_sentences(out)
    return out.strip()


def remove_fillers(text: str) -> str:
    """Delete hesitation sounds, and throat-clearing at a sentence start."""
    out = text
    for filler in HARD_FILLERS:
        out = re.sub(_WORD % re.escape(filler), "", out, flags=re.IGNORECASE)
    for filler in LEADING_FILLERS:
        # Only at the very start, or right after sentence-ending punctuation.
        # The leading \s* matters: removing "um" from "um so I think" leaves a
        # space in front of "so", which would otherwise no longer look like the
        # start of the text.
        out = re.sub(
            rf"(^\s*|(?<=[.!?])\s+){re.escape(filler)}\b[,]?\s*",
            r"\1",
            out,
            flags=re.IGNORECASE,
        )
    # Close the gaps the deletions just opened, rather than leaving doubled
    # spaces for a later pass to notice.
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def collapse_stutters(text: str) -> str:
    """"the the team" -> "the team". Deliberate reduplication is preserved."""
    keep = {"had", "that", "no", "bye", "very", "really"}

    def replace(match: re.Match) -> str:
        word = match.group(1)
        return match.group(0) if word.lower() in keep else word

    return re.sub(r"\b(\w+)(\s+\1\b)+", replace, text, flags=re.IGNORECASE)


def apply_spoken_punctuation(text: str) -> str:
    """Turn spoken punctuation names into marks.

    Only when the word is used *as* punctuation: "period" after a word becomes
    ".", but "the period drama" keeps its noun. The heuristic is that a
    punctuation name used as punctuation is followed by a word boundary and not
    preceded by an article or adjective marker.
    """
    out = text
    for phrase, mark in SPOKEN_PUNCTUATION:
        pattern = rf"(?<![\w'])(?<!the )(?<!a )(?<!an )(?<!this ){re.escape(phrase)}(?![\w'])"
        replacement = mark + " " if mark not in "([" else " " + mark
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
    # The spoken word had a space in front of it that the mark should not keep:
    # "that works period" must become "that works.", not "that works .".
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    return out.strip()


def fix_spacing(text: str) -> str:
    """Tidy the whitespace the deletions above leave behind."""
    out = re.sub(r"[ \t]+", " ", text)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)       # no space before a mark
    out = re.sub(r"([,;:])(?=\S)", r"\1 ", out)      # one space after a mark
    out = re.sub(r"([.!?])(?=[A-Za-z])", r"\1 ", out)
    out = re.sub(r"\(\s+", "(", out)
    out = re.sub(r"\s+\)", ")", out)
    out = re.sub(r" *\n *", "\n", out)
    return out.strip()


def capitalize_sentences(text: str) -> str:
    """Capitalize the first letter of the text and of each new sentence.

    Also fixes the standalone "i", which recognition lowercases often enough to
    be noticeable.
    """
    out = re.sub(r"\bi\b", "I", text)

    def upper(match: re.Match) -> str:
        return match.group(0).upper()

    out = re.sub(r"(^|[.!?]\s+|\n)([a-z])",
                 lambda m: m.group(1) + m.group(2).upper(), out)
    return out
