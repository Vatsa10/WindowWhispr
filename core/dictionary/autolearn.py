"""Learn a name from the correction the user makes right after pasting.

If dictation writes "Monvi" and a moment later the field says "Manvi", that is
the user teaching WinWhispr a spelling. The detection is deliberately narrow: one
word swapped for one word, both long enough to be names, the replacement
capitalized, and the two close enough to be the same word misheard. Anything
less strict poisons the dictionary with ordinary edits.

Pure logic — the Windows watcher that supplies "before" and "after" lives in
``observer_win.py``. Ported from WhimprFlow's ``src-tauri/src/autolearn.rs``.
"""

from __future__ import annotations

import string
from dataclasses import dataclass

from core.dictionary.similarity import normalized_distance

#: Shortest word that can be a name worth learning.
MIN_WORD_LEN = 3

#: Beyond this normalized edit distance the two words are different words, not
#: the same word misheard.
MAX_DISTANCE = 0.6

#: Ordinary words whose swap is a normal edit, not a spelling lesson. Keeps
#: their/there and then/than out of the dictionary.
STOPLIST = frozenset(
    """
    the and for are but not you your youre with this that have from they theyre their there would
    could should about then than them these those here were well will what when where which while
    into just like make made want some time know take come back good much also been over only more
    most very even such many does done same sure okay yeah hey hello please thanks thank message
    email text call need send give find look tell talk work week today tomorrow yesterday
    """.split()
)

_TRIM = string.punctuation


@dataclass(frozen=True)
class Correction:
    """A mishear and the spelling the user replaced it with."""

    mishear: str
    correct: str


def word_tokens(text: str) -> list[str]:
    """Whitespace split with surrounding punctuation trimmed; case preserved."""
    return [w for w in (t.strip(_TRIM) for t in (text or "").split()) if w]


def detect_correction(inserted: str, after: str) -> Correction | None:
    """Find the single-word fix the user made to text WinWhispr just pasted."""
    ins = word_tokens(inserted)
    aft = word_tokens(after)
    if not ins or not aft:
        return None

    ins_lc = {w.lower() for w in ins}
    aft_lc = {w.lower() for w in aft}
    # Set difference, so reordering words is not mistaken for a correction.
    removed = [w for w in ins if w.lower() not in aft_lc]
    added = [w for w in aft if w.lower() not in ins_lc]
    if len(removed) != 1 or len(added) != 1:
        return None

    mishear, correct = removed[0], added[0]
    if len(mishear) < MIN_WORD_LEN or len(correct) < MIN_WORD_LEN:
        return None
    if not mishear.isalpha() or not correct.isalpha():
        return None
    if mishear.lower() == correct.lower():
        return None  # a case-only edit teaches nothing about spelling
    if correct.lower() in STOPLIST or mishear.lower() in STOPLIST:
        return None
    if not correct[0].isupper():
        return None  # names are capitalized; ordinary words are not worth learning

    distance = normalized_distance(mishear.lower(), correct.lower())
    if 0.0 < distance <= MAX_DISTANCE:
        return Correction(mishear=mishear, correct=correct)
    return None
