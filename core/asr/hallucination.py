"""Phrases Whisper says when nobody said anything.

Whisper was trained on captioned video, and a stretch of silence or noise
reliably makes it emit the caption boilerplate that ended those videos:
"thank you for watching", "subtitles by ...", a music glyph. The words are not
in the audio. They come from the training data.

The obvious fix -- delete these strings wherever they appear -- is wrong. A
person can genuinely say "thanks for watching", and an app that quietly eats
that sentence is worse than one that occasionally invents it. So the phrase
alone is never enough:

  - With a local model there is a confidence signal. A phrase invented over
    silence carries a high ``no_speech_prob``; a phrase somebody said carries
    a low one. Only the former is dropped.
  - The browser gives no such signal, so there the phrase is dropped only when
    it is the *entire* transcript -- the one case where nothing can be lost,
    because the alternative is typing boilerplate into a document.
"""

from __future__ import annotations

import re

#: Above this, the decoder is saying it does not think this was speech. Set
#: well below the decoder's own ``no_speech_threshold`` so that a phrase which
#: survived decoding can still be caught here on the strength of the match.
NO_SPEECH_FLOOR = 0.4

#: Known training-data residue. Lowercase, punctuation-free: compared against
#: `normalize()` output, never against raw text.
BLOCKLIST: frozenset[str] = frozenset({
    "thank you",
    "thank you very much",
    "thank you for watching",
    "thanks for watching",
    "thank you for watching this video",
    "thanks for watching this video",
    "please subscribe",
    "please subscribe to my channel",
    "like and subscribe",
    "don't forget to subscribe",
    "see you next time",
    "see you in the next video",
    "subtitles by",
    "subtitles by the amaraorg community",
    "subtitles by the amara org community",
    "amaraorg",
    "transcription by castingwords",
    "the end",
    "bye",
    "you",
    "music",
    "applause",
    "laughter",
    "foreign",
})

_PUNCTUATION = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercase, strip punctuation and collapse spaces, for comparison only."""
    cleaned = _PUNCTUATION.sub(" ", (text or "").lower())
    return _SPACES.sub(" ", cleaned).strip()


def is_hallucinated(segment) -> bool:
    """Whether one decoded segment is training residue rather than speech.

    Needs both halves: a blocklisted phrase AND the decoder doubting there was
    speech there. Either alone would throw away something real.
    """
    if normalize(getattr(segment, "text", "")) not in BLOCKLIST:
        return False
    return float(getattr(segment, "no_speech_prob", 0.0) or 0.0) > NO_SPEECH_FLOOR


def drop_hallucinations(segments):
    """The segments worth keeping, in order."""
    return [segment for segment in segments if not is_hallucinated(segment)]


def is_whole_transcript_hallucination(text: str) -> bool:
    """The browser's weaker test: the entire transcript is a known phrase.

    No confidence signal exists there, so this is deliberately the narrowest
    possible rule. A blocklisted phrase with anything else around it is kept,
    because the user probably said it.
    """
    return normalize(text) in BLOCKLIST
