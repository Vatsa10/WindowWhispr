"""Applying the personal dictionary to a browser transcript.

With a local Whisper model the dictionary was a *spelling authority*: the words
were handed to the decoder as hints, so it could never corrupt something that
merely sounded similar. The browser's recognizer has no such hook -- Chromium
does not implement ``SpeechGrammarList`` in any useful way -- so the only place
left to apply it is after the fact.

Replacement after the fact is a blunter tool, and that is exactly why the rules
here are narrow:

  - only the mishears you typed are ever replaced, never arbitrary similar words
  - whole words only, so "wonder" never becomes "w<Ander>"
  - capitalisation is carried across, so a mishear that started a sentence is
    replaced by a correction that also does

Anything looser would quietly rewrite words the user did say, which is the one
failure this app is not allowed to have.
"""

from __future__ import annotations

import re

#: A mishear has to be long enough to be distinctive. One or two letters match
#: far too much ordinary text to be safe to replace.
MIN_MISHEAR_CHARS = 3


def build_rules(entries) -> list[tuple[re.Pattern, str]]:
    """Compile a dictionary into replacement rules, longest mishear first.

    Longest first so that a two-word mishear wins over a one-word one that is
    contained in it -- otherwise "charge bee" would be half-replaced by a rule
    for "charge".
    """
    pairs: list[tuple[str, str]] = []
    for entry in entries:
        correct = (getattr(entry, "correct", "") or "").strip()
        if not correct:
            continue
        for mishear in getattr(entry, "mishears", ()) or ():
            heard = (mishear or "").strip()
            if len(heard) < MIN_MISHEAR_CHARS or heard.lower() == correct.lower():
                continue
            pairs.append((heard, correct))

    pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
    rules = []
    for heard, correct in pairs:
        # \b on both ends, and the mishear may contain spaces, so escape it
        # whole rather than joining words.
        pattern = re.compile(rf"\b{re.escape(heard)}\b", re.IGNORECASE)
        rules.append((pattern, correct))
    return rules


def apply(text: str, rules) -> str:
    """Replace every known mishear, keeping the sentence's capitalisation."""
    if not text or not rules:
        return text

    for pattern, correct in rules:
        def replace(match: re.Match) -> str:
            heard = match.group(0)
            # "Chargebee invoices" at the start of a sentence should not come
            # back lowercase just because the dictionary entry is lowercase.
            if heard[:1].isupper() and correct[:1].islower():
                return correct[:1].upper() + correct[1:]
            return correct

        text = pattern.sub(replace, text)
    return text
