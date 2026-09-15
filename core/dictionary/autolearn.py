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

#: Everyday English. Dropping the "must be capitalised" rule let lowercase
#: technical terms through, which is the point -- but it also let ordinary
#: words through, and learning "recieve -> receive" as a dictionary entry would
#: be noise. This is the replacement guard: a correction between two words that
#: are both plain English teaches nothing about a name.
COMMON_WORDS = frozenset(
    """
    receive received believe achieve because before between business calendar definitely
    different document during example except exercise experience february finally
    following friend government happened height however immediately important interest
    knowledge language library maybe minute necessary neither occasion occurred often
    people perhaps possible probably question really receipt remember restaurant
    schedule science second separate similar special started straight strength
    surprise though thought through together tomorrow tonight truly until usually
    weather whether writing written yesterday
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
    """Find the fix the user made to text WinWhispr just pasted.

    One word for one, or one word for two either way -- a name split into two
    words is the same correction as a name misspelled, and only the second
    shape used to be visible here.
    """
    ins = word_tokens(inserted)
    aft = word_tokens(after)
    if not ins or not aft:
        return None

    ins_lc = {w.lower() for w in ins}
    aft_lc = {w.lower() for w in aft}
    # Set difference, so reordering words is not mistaken for a correction.
    removed = [w for w in ins if w.lower() not in aft_lc]
    added = [w for w in aft if w.lower() not in ins_lc]
    # One word becoming two, or two becoming one, as well as a straight swap.
    # "charge bee" -> "ChargeBee" is the case this module's own docstring is
    # written around, and strict 1-for-1 could never see it.
    if not (1 <= len(removed) <= 2 and 1 <= len(added) <= 2):
        return None
    if len(removed) == 2 and len(added) == 2:
        return None  # two independent edits, not one correction

    mishear = " ".join(removed)
    correct = " ".join(added)
    if len(mishear) < MIN_WORD_LEN or len(correct) < MIN_WORD_LEN:
        return None
    if not mishear.replace(" ", "").isalpha() or not correct.replace(" ", "").isalpha():
        return None
    if mishear.lower() == correct.lower():
        return None  # a case-only edit teaches nothing about spelling
    if any(word.lower() in STOPLIST for word in removed + added):
        return None
    # Capitalisation used to be required, which blocked every lowercase
    # technical term outright -- "kubectl", "npm", "jsonl" could never be
    # learned. The stoplist is the real guard against learning ordinary
    # English; a capital letter never was.
    if correct.lower() in COMMON_WORDS or mishear.lower() in COMMON_WORDS:
        return None

    distance = normalized_distance(mishear.lower(), correct.lower())
    if 0.0 < distance <= MAX_DISTANCE:
        return Correction(mishear=mishear, correct=correct)
    return None
