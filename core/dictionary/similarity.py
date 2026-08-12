"""Token similarity for dictionary matching.

Hand-rolled Levenshtein rather than a C-extension dependency: the inputs are
single words (rarely past 20 characters) matched a few dozen times per
utterance, so the O(n*m) loop is far below the noise floor of a model call.
"""

from __future__ import annotations

#: Normalized edit distance below which two tokens count as the same word.
#: Chosen to catch a mis-heard name ("monvi" vs "manvi") without dragging in
#: unrelated short words.
CLOSE_THRESHOLD = 0.34


def levenshtein(a: str, b: str) -> int:
    """Edit distance between two strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,          # deletion
                    current[j - 1] + 1,       # insertion
                    previous[j - 1] + (ca != cb),  # substitution
                )
            )
        previous = current
    return previous[-1]


def normalized_distance(a: str, b: str) -> float:
    """Edit distance scaled by the longer string, in [0, 1]."""
    if a == b:
        return 0.0
    longest = max(len(a), len(b))
    if longest == 0:
        return 0.0
    return levenshtein(a, b) / longest


def close(a: str, b: str, threshold: float = CLOSE_THRESHOLD) -> bool:
    """True when two tokens are the same word or a near miss."""
    return normalized_distance(a, b) <= threshold
