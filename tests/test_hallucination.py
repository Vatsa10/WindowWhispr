"""Transcripts nobody said.

Two rules, and the second is what keeps the first honest: a blocklisted phrase
is only dropped when the decoder also doubts there was speech. Without that, an
app that hears "thanks for watching" and types nothing is worse than one that
occasionally invents it.
"""

import numpy as np

from core.asr.engine import Segment, join_segments
from core.asr.hallucination import (
    BLOCKLIST,
    NO_SPEECH_FLOOR,
    drop_hallucinations,
    is_hallucinated,
    is_whole_transcript_hallucination,
    normalize,
)


def test_a_phrase_invented_over_silence_is_dropped():
    assert is_hallucinated(Segment("Thank you for watching.", no_speech_prob=0.9))


def test_the_same_phrase_actually_spoken_is_kept():
    """The whole reason this is not a string filter."""
    assert not is_hallucinated(Segment("Thank you for watching.", no_speech_prob=0.02))


def test_the_floor_is_the_deciding_line():
    just_over = Segment("music", no_speech_prob=NO_SPEECH_FLOOR + 0.01)
    just_under = Segment("music", no_speech_prob=NO_SPEECH_FLOOR - 0.01)
    assert is_hallucinated(just_over)
    assert not is_hallucinated(just_under)


def test_ordinary_speech_is_never_touched():
    assert not is_hallucinated(Segment("ship the release on Friday", no_speech_prob=0.99))


def test_punctuation_and_case_do_not_hide_a_match():
    assert is_hallucinated(Segment("  THANKS FOR WATCHING!!  ", no_speech_prob=0.8))


def test_dropping_keeps_the_real_segments_in_order():
    kept = drop_hallucinations([
        Segment("first thing", no_speech_prob=0.1),
        Segment("Thank you.", no_speech_prob=0.95),
        Segment("second thing", no_speech_prob=0.1),
    ])
    assert [s.text for s in kept] == ["first thing", "second thing"]


def test_a_segment_with_no_scores_survives():
    """Engines without confidence must behave exactly as they did before."""
    assert not is_hallucinated(Segment("Thank you"))
    assert join_segments(drop_hallucinations([Segment("Thank you")])) == "Thank you"


# --- the browser's narrower rule ------------------------------------------


def test_the_browser_drops_a_phrase_that_is_the_whole_transcript():
    assert is_whole_transcript_hallucination("Thanks for watching!")


def test_the_browser_keeps_a_blocklisted_phrase_inside_a_sentence():
    # No confidence signal exists there, so anything wider would eat real text.
    assert not is_whole_transcript_hallucination("thanks for watching the demo, it went well")


def test_normalize_is_what_both_rules_compare_against():
    assert normalize("  Thank You, For Watching!  ") == "thank you for watching"
    assert normalize("") == ""


def test_the_blocklist_holds_the_known_residue():
    for phrase in ("thank you for watching", "please subscribe", "music"):
        assert phrase in BLOCKLIST


# --- the gain ceiling ------------------------------------------------------


def test_room_tone_is_not_amplified_into_speech():
    """A 0.02 peak was being scaled about 47x, which is where Whisper invents."""
    from core.asr.faster_whisper_engine import MAX_GAIN, _normalize_peak

    noise = (np.random.default_rng(7).standard_normal(16000) * 0.02).astype(np.float32)
    before = float(np.abs(noise).max())
    after = float(np.abs(_normalize_peak(noise)).max())
    assert after <= before * MAX_GAIN + 1e-6


def test_quiet_speech_still_gets_a_real_lift():
    from core.asr.faster_whisper_engine import _normalize_peak

    quiet = (np.ones(1600, dtype=np.float32) * 0.05)
    assert float(np.abs(_normalize_peak(quiet)).max()) > 0.35


def test_loud_audio_is_still_normalised_down_toward_the_target():
    from core.asr.faster_whisper_engine import TARGET_PEAK, _normalize_peak

    loud = (np.ones(1600, dtype=np.float32) * 0.99)
    assert float(np.abs(_normalize_peak(loud)).max()) <= TARGET_PEAK + 1e-6


def test_silence_is_returned_untouched():
    from core.asr.faster_whisper_engine import _normalize_peak

    silence = np.zeros(1600, dtype=np.float32)
    assert float(np.abs(_normalize_peak(silence)).max()) == 0.0
