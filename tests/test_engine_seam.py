"""The seam every engine is used through.

`transcribe()` and `transcribe_rich()` must not drift: every hallucination
threshold is tuned against the scores, and a join that disagrees with them
would silently apply those numbers to different text.
"""

from core.asr.engine import Segment, join_segments
from core.asr.hallucination import is_hallucinated


def test_joining_is_what_transcribe_returns():
    segments = [Segment(" first "), Segment("second")]
    assert join_segments(segments) == "first second"


def test_empty_segments_do_not_leave_double_spaces():
    assert join_segments([Segment("a"), Segment("   "), Segment("b")]) == "a b"


def test_no_segments_is_an_empty_string():
    assert join_segments([]) == ""


def test_a_default_segment_passes_every_threshold():
    """An engine that reports no confidence must behave exactly as before."""
    plain = Segment("some words")
    assert plain.avg_logprob == 0.0
    assert plain.no_speech_prob == 0.0
    assert not is_hallucinated(plain)


def test_every_engine_offers_the_rich_call():
    """A missing implementation would only surface at runtime, per engine."""
    import inspect

    from core.asr.faster_whisper_engine import FasterWhisperEngine
    from core.asr.openvino_engine import OpenVinoEngine
    from core.asr.remote_engine import GroqEngine

    for engine in (FasterWhisperEngine, OpenVinoEngine, GroqEngine):
        assert hasattr(engine, "transcribe_rich"), engine.__name__
        assert callable(inspect.getattr_static(engine, "transcribe_rich"))


def test_the_engine_protocol_names_both_calls():
    from core.asr.engine import AsrEngine

    assert hasattr(AsrEngine, "transcribe")
    assert hasattr(AsrEngine, "transcribe_rich")
