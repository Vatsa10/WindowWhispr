"""State machine assertions, ported from WhimprFlow's machine.rs tests.

Everything is driven with synthetic timestamps — no clock, no sleeps.
"""

from core.state import (
    AWAITING_LOCK,
    FINALIZING,
    IDLE,
    RECORDING,
    BarState,
    Binding,
    Cancel,
    Committed,
    DictationMachine,
    DiscardCapture,
    Down,
    Failed,
    RecordMode,
    RunPipeline,
    ShowBar,
    StartCapture,
    StopCaptureAndFinalize,
    Tick,
    Up,
    WarnSessionCap,
)
from core.state.timing import DOUBLE_TAP_MS, HOLD_MIN_MS, SESSION_CAP_MS, WARN_AT_MS

PTT = Binding.PUSH_TO_TALK
HANDS_FREE = Binding.HANDS_FREE


def kinds(actions):
    return [type(a) for a in actions]


def bars(actions):
    return [a.state for a in actions if isinstance(a, ShowBar)]


def test_hold_records_then_finalizes_on_release():
    m = DictationMachine()
    actions = m.step(Down(PTT, 0))
    assert isinstance(actions[0], StartCapture)
    assert actions[0].mode is RecordMode.PUSH_TO_TALK
    assert m.phase == RECORDING

    actions = m.step(Up(PTT, 1000))
    assert StopCaptureAndFinalize in kinds(actions)
    assert RunPipeline in kinds(actions)
    assert bars(actions) == [BarState.TRANSCRIBING]
    assert m.phase == FINALIZING


def test_short_tap_discards_and_returns_to_idle_by_default():
    # Lock-on-double-tap is opt-in, so a stray tap just goes away.
    m = DictationMachine()
    m.step(Down(PTT, 0))
    actions = m.step(Up(PTT, HOLD_MIN_MS - 1))
    assert isinstance(actions[0], DiscardCapture)
    assert m.phase == IDLE


def test_second_tap_does_not_lock_unless_enabled():
    m = DictationMachine()
    m.step(Down(PTT, 0))
    m.step(Up(PTT, 50))
    # The cooldown swallows the immediate re-press; either way, no lock.
    m.step(Down(PTT, 60))
    assert m.state.mode is not RecordMode.LOCKED


def test_short_tap_awaits_a_lock_when_enabled():
    m = DictationMachine(allow_lock=True)
    m.step(Down(PTT, 0))
    actions = m.step(Up(PTT, HOLD_MIN_MS - 1))
    assert isinstance(actions[0], DiscardCapture)
    assert m.phase == AWAITING_LOCK


def test_double_tap_locks_hands_free():
    m = DictationMachine(allow_lock=True)
    m.step(Down(PTT, 0))
    m.step(Up(PTT, 50))
    actions = m.step(Down(PTT, 50 + DOUBLE_TAP_MS))
    assert actions[0].mode is RecordMode.LOCKED
    assert bars(actions) == [BarState.LOCKED]
    assert m.phase == RECORDING


def test_late_second_tap_does_not_lock():
    m = DictationMachine(allow_lock=True)
    m.step(Down(PTT, 0))
    m.step(Up(PTT, 50))
    m.step(Tick(50 + DOUBLE_TAP_MS + 1))  # window expires
    assert m.phase == IDLE


def test_repress_ends_a_locked_session():
    m = DictationMachine(allow_lock=True)
    m.step(Down(PTT, 0))
    m.step(Up(PTT, 50))
    m.step(Down(PTT, 100))  # locked
    actions = m.step(Down(PTT, 5000))
    assert StopCaptureAndFinalize in kinds(actions)


def test_hands_free_binding_starts_locked_immediately():
    m = DictationMachine()
    actions = m.step(Down(HANDS_FREE, 0))
    assert actions[0].mode is RecordMode.LOCKED
    actions = m.step(Down(HANDS_FREE, 3000))
    assert StopCaptureAndFinalize in kinds(actions)


def test_escape_cancels_from_recording():
    m = DictationMachine()
    m.step(Down(PTT, 0))
    actions = m.step(Cancel(1000))
    assert isinstance(actions[0], DiscardCapture)
    assert bars(actions) == [BarState.CANCELLED, BarState.IDLE]
    assert m.phase == IDLE


def test_escape_cancels_from_finalizing():
    m = DictationMachine()
    m.step(Down(PTT, 0))
    m.step(Up(PTT, 1000))
    actions = m.step(Cancel(1100))
    assert isinstance(actions[0], DiscardCapture)
    assert m.phase == IDLE


def test_escape_when_idle_is_a_no_op():
    assert DictationMachine().step(Cancel(0)) == []


def test_cooldown_suppresses_an_immediate_restart():
    m = DictationMachine()
    m.step(Down(PTT, 0))
    m.step(Cancel(1000))  # sets the cooldown clock
    assert m.step(Down(PTT, 1100)) == []
    assert m.step(Down(PTT, 1600)) != []


def test_session_cap_warns_once_then_finalizes():
    m = DictationMachine()
    m.step(Down(PTT, 0))
    actions = m.step(Tick(WARN_AT_MS))
    assert WarnSessionCap in kinds(actions)
    assert m.step(Tick(WARN_AT_MS + 1000)) == []  # warns only once
    actions = m.step(Tick(SESSION_CAP_MS))
    assert StopCaptureAndFinalize in kinds(actions)


def test_pipeline_result_returns_to_idle():
    m = DictationMachine()
    m.step(Down(PTT, 0))
    m.step(Up(PTT, 1000))
    session = m.state.session
    assert bars(m.step(Committed(session))) == [BarState.DONE]
    assert m.phase == IDLE

    m.step(Down(PTT, 5000))
    m.step(Up(PTT, 6000))
    assert bars(m.step(Failed(m.state.session))) == [BarState.IDLE]
    assert m.phase == IDLE


def test_stale_pipeline_events_are_ignored():
    m = DictationMachine()
    m.step(Down(PTT, 0))
    m.step(Up(PTT, 1000))
    assert m.step(Committed(999)) == []
    assert m.phase == FINALIZING


def test_stray_ups_are_no_ops():
    m = DictationMachine()
    assert m.step(Up(PTT, 0)) == []
    assert m.phase == IDLE


def test_key_autorepeat_does_not_restart_a_session():
    # The hook filters repeats, but a leaked repeat must not reset started_ms.
    m = DictationMachine()
    m.step(Down(PTT, 0))
    session = m.state.session
    m.step(Down(PTT, 30))
    assert m.state.session == session
    assert m.state.started_ms == 0
