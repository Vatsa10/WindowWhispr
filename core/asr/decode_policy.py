"""Which language to decode a segment as.

One sentence containing two languages is normal for most of the world, and
pinning the decoder to one forces half of it through the wrong phonetics. The
obvious fix -- let the model detect the language freely -- is worse than the
problem: it is exactly how English spoken with a Russian accent comes back as
Russian text. The accent looks like the language.

So detection is never open-ended. The user declares a pair, and only those two
are ever candidates:

  - A declared pair is the whole world. A language nobody declared is never
    selected, however confident the model is about it, which is what stops an
    accent from redirecting the transcript into another language.
  - Doubt resolves to the primary, deliberately and asymmetrically. Missing a
    switch costs a clumsy sentence; guessing the wrong language costs a
    transcript nobody can read, and the two are not worth trading evenly.
  - No secondary means a hard pin, byte-identical to a single-language decode.
    Nobody who has not opted in takes on any new risk.
"""

from __future__ import annotations

import logging

_log = logging.getLogger("winwhispr.asr")

#: Below this the segment is too short or too noisy to call, and the primary
#: wins. Detection on a second of audio is not reliable enough to gamble a
#: whole sentence on.
DETECT_FLOOR = 0.6


def clamp(probabilities, primary: str, secondary: str,
          floor: float = DETECT_FLOOR) -> str:
    """Pick between the declared pair, given per-language probabilities.

    Pure: the model call lives in `resolve`, so the judgment can be tested
    without loading a gigabyte of weights.
    """
    if not secondary or secondary == primary:
        return primary
    scores = dict(probabilities or {})
    candidates = {
        primary: float(scores.get(primary, 0.0) or 0.0),
        secondary: float(scores.get(secondary, 0.0) or 0.0),
    }
    best = max(candidates, key=lambda lang: candidates[lang])
    if candidates[best] < floor:
        return primary
    return best


def resolve(model, audio, primary: str, secondary: str,
            floor: float = DETECT_FLOOR) -> str:
    """The language to decode this segment as.

    Costs one encoder-only pass over about thirty frames, which the pipelined
    worker in core/asr/pipeline.py hides behind the speech still being spoken.
    A detection failure falls back to the primary rather than raising: a
    clumsy transcript beats no transcript.
    """
    if not secondary or secondary == primary:
        return primary
    try:
        _language, _probability, all_probabilities = model.detect_language(audio=audio)
    except Exception as exc:  # pragma: no cover - model/runtime dependent
        _log.debug("language detection failed (%s); using %s", exc, primary)
        return primary

    chosen = clamp(dict(all_probabilities or []), primary, secondary, floor)
    _log.debug("language %s chosen from pair (%s, %s)", chosen, primary, secondary)
    return chosen
