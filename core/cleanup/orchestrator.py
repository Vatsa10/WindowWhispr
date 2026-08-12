"""Run a transcript through cleanup, with the raw text as the safety net.

The contract this module exists to enforce: **cleanup is an enhancement, never
a gate**. A provider error, a timeout, an empty result, or any gate rejection
all end the same way — the user's raw words get pasted. The only thing cleanup
can do is make the text better; it can never make it disappear.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass

from core.cleanup import CleanupContext, build_messages, evaluate_gates
from core.cleanup.gates import GateReason
from core.cleanup.normalize import post_process, pre_normalize_layout

_log = logging.getLogger("winwhispr.cleanup")

#: Wall-clock ceiling for a single cleanup call. Past this the raw transcript is
#: pasted; a dictation app cannot make the user wait on a slow model.
DEFAULT_TIMEOUT_MS = 4000


@dataclass(frozen=True)
class CleanupResult:
    """What to paste, and how it was arrived at."""

    text: str
    used_raw: bool
    reason: str = ""
    latency_ms: int = 0


def run_cleanup(raw: str, ctx: CleanupContext, provider, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> CleanupResult:
    """Clean ``raw`` under ``ctx``, falling back to the raw transcript."""
    started = time.monotonic()

    def elapsed_ms() -> int:
        return int((time.monotonic() - started) * 1000)

    raw = raw or ""
    if not raw.strip():
        return CleanupResult(text=raw, used_raw=True, reason="empty")

    # Spoken layout cues become opaque sentinels before the model sees them, and
    # real breaks after. raw_out is the fallback text with the sentinels already
    # resolved, so a fallback never pastes a literal "[[NL]]".
    raw_norm = pre_normalize_layout(raw)
    raw_out = post_process(raw_norm)

    if ctx.level.bypasses_llm():
        return CleanupResult(text=raw_out, used_raw=True, reason="level_none",
                             latency_ms=elapsed_ms())
    if provider is None:
        return CleanupResult(text=raw_out, used_raw=True, reason="no_provider",
                             latency_ms=elapsed_ms())

    try:
        messages = build_messages(raw_norm, ctx)
        model_out = _call_with_timeout(provider, messages, timeout_ms)
    except FutureTimeout:
        # The orphaned call keeps running (a local OpenVINO generate cannot be
        # cancelled); it just no longer blocks the paste.
        _log.warning("cleanup timed out after %dms — pasting raw", timeout_ms)
        return CleanupResult(text=raw_out, used_raw=True, reason="timeout",
                             latency_ms=elapsed_ms())
    except Exception as exc:  # pragma: no cover - provider/runtime dependent
        _log.warning("cleanup provider failed (%s) — pasting raw", exc)
        return CleanupResult(text=raw_out, used_raw=True, reason="provider_error",
                             latency_ms=elapsed_ms())

    if not (model_out or "").strip():
        return CleanupResult(text=raw_out, used_raw=True, reason="empty_output",
                             latency_ms=elapsed_ms())

    cleaned = post_process(model_out)
    verdict = evaluate_gates(raw_out, cleaned, ctx.level)
    latency = elapsed_ms()
    if not verdict.passed:
        reason: GateReason = verdict.reason
        # Logged at INFO, not DEBUG: the rejection rate on real dictation is how
        # the per-level novelty ceilings get tuned.
        _log.info(
            "cleanup gate rejected the edit (%s: %s) — pasting raw",
            reason.value if reason else "?",
            verdict.detail,
        )
        return CleanupResult(text=raw_out, used_raw=True,
                             reason=f"gate:{reason.value if reason else '?'}",
                             latency_ms=latency)

    _log.debug("cleanup ok in %dms", latency)
    return CleanupResult(text=cleaned, used_raw=False, latency_ms=latency)


def _call_with_timeout(provider, messages, timeout_ms: int) -> str:
    """Run ``provider.cleanup`` with a wall-clock ceiling.

    A plain daemon thread rather than a ThreadPoolExecutor: the executor joins
    its workers at interpreter exit, so an orphaned model call would hold up
    quitting the app. A daemon thread just dies with the process.
    """
    if not timeout_ms or timeout_ms <= 0:
        return provider.cleanup(messages)

    box: dict = {}

    def _run():
        try:
            box["ok"] = provider.cleanup(messages)
        except BaseException as exc:  # surfaced on the calling thread below
            box["err"] = exc

    worker = threading.Thread(target=_run, daemon=True, name="winwhispr-cleanup")
    worker.start()
    worker.join(timeout_ms / 1000.0)
    if worker.is_alive():
        raise FutureTimeout()
    if "err" in box:
        raise box["err"]
    return box.get("ok", "")
