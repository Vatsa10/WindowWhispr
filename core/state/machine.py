"""The dictation state machine.

A pure ``step(input) -> list[Action]`` reducer: no clock, no mic, no keyboard
hook. Time arrives as ``Tick`` and key events as ``Down``/``Up``/``Cancel``, so
the whole hold / double-tap-lock / cancel / cooldown / session-cap behavior is
deterministic and unit-testable.

Ported from WhimprFlow's ``whimpr-core/src/state/machine.rs``.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.state.actions import (
    BarState,
    DiscardCapture,
    PlayPing,
    RecordMode,
    RunPipeline,
    ShowBar,
    StartCapture,
    StopCaptureAndFinalize,
    WarnSessionCap,
)
from core.state.events import Binding, Cancel, Committed, Down, Failed, Tick, Up
from core.state.timing import (
    COOLDOWN_MS,
    DOUBLE_TAP_MS,
    HOLD_MIN_MS,
    SESSION_CAP_MS,
    WARN_AT_MS,
)


class Phase(str):
    pass


IDLE = "idle"
RECORDING = "recording"
AWAITING_LOCK = "awaiting_lock"
FINALIZING = "finalizing"


@dataclass
class State:
    """Current phase plus whatever that phase needs to remember."""

    phase: str = IDLE
    session: int | None = None
    mode: RecordMode | None = None
    started_ms: int = 0
    #: True once the approaching-cap warning fired for this session.
    warned: bool = False
    #: When the tap that opened AWAITING_LOCK ended.
    tap_up_ms: int = 0


class DictationMachine:
    """Owns the state and the bookkeeping the reducer needs."""

    def __init__(self, allow_lock: bool = False):
        self.state = State()
        self._next_session = 1
        #: When the last session ended, for cooldown debouncing.
        self._last_end_ms: int | None = None
        # Double-tap-to-lock is off by default. It is a genuinely useful mode,
        # but as a default it turns a mistyped key into a recording that does
        # not stop when you let go — surprising in exactly the wrong direction.
        self._allow_lock = bool(allow_lock)

    # --- public ------------------------------------------------------------

    @property
    def phase(self) -> str:
        return self.state.phase

    def is_recording(self) -> bool:
        return self.state.phase == RECORDING

    def step(self, event) -> list:
        """Advance by one input, returning the side effects to perform."""
        if isinstance(event, (Down, Up, Cancel)):
            return self._on_trigger(event)
        if isinstance(event, (Committed, Failed)):
            return self._on_pipeline(event)
        if isinstance(event, Tick):
            return self._on_tick(event.now_ms)
        return []

    # --- trigger handling --------------------------------------------------

    def _on_trigger(self, event) -> list:
        state = self.state

        if isinstance(event, Cancel):
            if state.phase in (RECORDING, FINALIZING):
                return self._cancel(state.session, event.at_ms)
            if state.phase == AWAITING_LOCK:
                return self._cancel(None, event.at_ms)
            return []

        if isinstance(event, Down):
            if state.phase == IDLE:
                if self._in_cooldown(event.at_ms):
                    return []
                mode = (
                    RecordMode.PUSH_TO_TALK
                    if event.binding is Binding.PUSH_TO_TALK
                    else RecordMode.LOCKED
                )
                return self._begin(mode, event.at_ms)

            # A second tap inside the window locks hands-free recording.
            if state.phase == AWAITING_LOCK and event.binding is Binding.PUSH_TO_TALK:
                if event.at_ms - state.tap_up_ms <= DOUBLE_TAP_MS:
                    return self._begin(RecordMode.LOCKED, event.at_ms)
                return []

            # Pressing again ends a locked session, whichever key does it.
            if state.phase == RECORDING and state.mode is RecordMode.LOCKED:
                return self._finalize(state.session)
            return []

        if isinstance(event, Up):
            if (
                state.phase == RECORDING
                and state.mode is RecordMode.PUSH_TO_TALK
                and event.binding is Binding.PUSH_TO_TALK
            ):
                held = event.at_ms - state.started_ms
                if held >= HOLD_MIN_MS:
                    return self._finalize(state.session)
                # Too short to be speech: throw it away.
                session = state.session
                if self._allow_lock:
                    # Watch for the second tap that locks hands-free recording.
                    self.state = State(phase=AWAITING_LOCK, tap_up_ms=event.at_ms)
                else:
                    self.state = State()
                    self._last_end_ms = event.at_ms
                return [DiscardCapture(session), ShowBar(BarState.IDLE)]
            return []

        return []

    # --- pipeline / time ---------------------------------------------------

    def _on_pipeline(self, event) -> list:
        state = self.state
        if state.phase != FINALIZING or event.session != state.session:
            return []
        self.state = State()
        # The session is over internally; the shell decides how long "done"
        # lingers before the pill returns to idle.
        return [ShowBar(BarState.DONE if isinstance(event, Committed) else BarState.IDLE)]

    def _on_tick(self, now_ms: int) -> list:
        state = self.state
        if state.phase == AWAITING_LOCK:
            if now_ms - state.tap_up_ms > DOUBLE_TAP_MS:
                # A single tap that never became a double-tap.
                self.state = State()
                self._last_end_ms = now_ms
                return [ShowBar(BarState.IDLE)]
            return []

        if state.phase == RECORDING:
            elapsed = now_ms - state.started_ms
            if elapsed >= SESSION_CAP_MS:
                return self._finalize(state.session)
            if elapsed >= WARN_AT_MS and not state.warned:
                state.warned = True
                return [WarnSessionCap()]
        return []

    # --- transitions -------------------------------------------------------

    def _in_cooldown(self, now_ms: int) -> bool:
        return self._last_end_ms is not None and now_ms - self._last_end_ms < COOLDOWN_MS

    def _begin(self, mode: RecordMode, at_ms: int) -> list:
        session = self._next_session
        self._next_session += 1
        self.state = State(phase=RECORDING, session=session, mode=mode, started_ms=at_ms)
        bar = BarState.RECORDING if mode is RecordMode.PUSH_TO_TALK else BarState.LOCKED
        return [StartCapture(session, mode), PlayPing(), ShowBar(bar)]

    def _finalize(self, session: int) -> list:
        self.state = State(phase=FINALIZING, session=session)
        return [
            StopCaptureAndFinalize(session),
            ShowBar(BarState.TRANSCRIBING),
            RunPipeline(session),
        ]

    def _cancel(self, session: int | None, at_ms: int) -> list:
        self.state = State()
        self._last_end_ms = at_ms
        actions = []
        if session is not None:
            actions.append(DiscardCapture(session))
        actions.append(ShowBar(BarState.CANCELLED))
        actions.append(ShowBar(BarState.IDLE))
        return actions
