"""Timing constants for the dictation state machine.

All in milliseconds. Ported from WhimprFlow's ``whimpr-core/src/state/timing.rs``.
"""

#: A key-up sooner than this is a tap, not a hold — the capture is discarded.
HOLD_MIN_MS = 200

#: How long after a tap a second press still counts as a double-tap (which locks
#: hands-free recording).
DOUBLE_TAP_MS = 350

#: After a session ends, ignore new starts for this long. Debounces the release
#: of a chord and stray repeat presses.
COOLDOWN_MS = 500

#: Hard ceiling on one recording, so a key stuck down cannot record forever.
SESSION_CAP_MS = 20 * 60 * 1000

#: Warn the user once when a session approaches the cap.
WARN_AT_MS = 19 * 60 * 1000

#: How often the driver loop feeds a Tick in. The cap/double-tap timeouts are
#: only as precise as this.
TICK_MS = 50
