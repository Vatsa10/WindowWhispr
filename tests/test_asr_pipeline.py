"""The pipelined session: order, timing, cancellation, failure."""

import time

import numpy as np
import pytest

from core.asr.engine import EngineCaps
from core.asr.pipeline import TranscriptionSession


class FakeEngine:
    """Records what it was asked to transcribe, and how often."""

    def __init__(self, pipelining=True, delay=0.0, fail_on=None):
        self.caps = EngineCaps(supports_pipelining=pipelining, label="fake")
        self.calls = []
        self._delay = delay
        self._fail_on = fail_on

    def warmup(self):
        pass

    def transcribe(self, audio):
        if self._delay:
            time.sleep(self._delay)
        marker = float(audio[0])
        self.calls.append(len(audio))
        if self._fail_on is not None and marker == self._fail_on:
            raise RuntimeError("engine exploded")
        return f"seg{int(marker)}"


def clip(marker, length=100):
    return np.full(length, float(marker), dtype=np.float32)


def test_segments_are_joined_in_order():
    session = TranscriptionSession(FakeEngine())
    session.start()
    for i in range(4):
        session.submit(clip(i))
    assert session.finish() == "seg0 seg1 seg2 seg3"


def test_out_of_order_completion_still_yields_spoken_order():
    # A short later segment can finish before a long earlier one.
    engine = FakeEngine(delay=0.01)
    session = TranscriptionSession(engine)
    session.start()
    session.submit(clip(0, 4000))
    session.submit(clip(1, 10))
    assert session.finish() == "seg0 seg1"


def test_the_tail_is_included():
    session = TranscriptionSession(FakeEngine())
    session.start()
    session.submit(clip(0))
    assert session.finish(clip(1)) == "seg0 seg1"


def test_work_happens_during_the_hold_not_after_release():
    # The whole point: segments submitted while speaking are already done, so
    # finishing costs only the tail.
    engine = FakeEngine(delay=0.05)
    session = TranscriptionSession(engine)
    session.start()
    for i in range(4):
        session.submit(clip(i))
    time.sleep(0.35)  # user keeps talking; the worker keeps up
    session.finish()
    assert session.tail_ms < 50, f"release cost {session.tail_ms:.0f}ms"


def test_empty_session_returns_empty():
    session = TranscriptionSession(FakeEngine())
    session.start()
    assert session.finish() == ""


def test_empty_segments_are_ignored():
    engine = FakeEngine()
    session = TranscriptionSession(engine)
    session.start()
    session.submit(np.array([], dtype=np.float32))
    session.submit(None)
    assert session.finish() == ""
    assert engine.calls == []


def test_engine_failure_surfaces_on_finish():
    session = TranscriptionSession(FakeEngine(fail_on=1.0))
    session.start()
    session.submit(clip(0))
    session.submit(clip(1))
    with pytest.raises(RuntimeError):
        session.finish()


def test_metered_engine_gets_exactly_one_call():
    engine = FakeEngine(pipelining=False)
    session = TranscriptionSession(engine)
    session.start()
    for i in range(3):
        session.submit(clip(i, 10))
    session.finish(clip(3, 10))
    assert len(engine.calls) == 1, "a metered engine must not be called per segment"
    assert engine.calls[0] == 40, "the whole utterance should be sent at once"


def test_abandoned_session_drops_its_work():
    session = TranscriptionSession(FakeEngine())
    session.start()
    session.submit(clip(0))
    session.abandon()
    assert session.finish() == ""
