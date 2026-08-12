"""Watch the focused field for the correction that follows a paste.

Windows exposes the text of most edit controls through UI Automation, so a
single delayed read tells us whether the user fixed a word. This is
opportunistic by design: Chromium and Electron apps expose nothing unless
accessibility is enabled, and there the watcher simply finds nothing.

Privacy: this reads the contents of whatever field has focus, which is why the
feature is off by default and must be turned on explicitly. The observed text
is never logged or stored — only the learned ``mishear -> correct`` pair is.
"""

from __future__ import annotations

import logging
import threading

from core.dictionary import SOURCE_AUTO
from core.dictionary.autolearn import detect_correction, word_tokens

_log = logging.getLogger("winwhispr.autolearn")

#: How long to wait before reading the field back. Long enough for the user to
#: notice a wrong name and fix it, short enough that they are still on the same
#: text. One read, not a poll — this is a courtesy feature, not a keylogger.
OBSERVE_DELAY_SECONDS = 7.0

#: A one-word paste gives the diff nothing to anchor on.
MIN_WORDS_TO_WATCH = 2

# UI Automation pattern ids (UIA_*PatternId).
_UIA_TEXT_PATTERN = 10014
_UIA_VALUE_PATTERN = 10002
_UIA_LEGACY_PATTERN = 10018


def watch_for_correction(inserted: str, dictionary, delay: float = OBSERVE_DELAY_SECONDS):
    """Schedule a single read of the focused field, on a daemon thread.

    Returns the thread (or None when there is nothing worth watching) so tests
    and callers can join it.
    """
    if not inserted or len(word_tokens(inserted)) < MIN_WORDS_TO_WATCH:
        return None
    thread = threading.Thread(
        target=_observe,
        args=(inserted, dictionary, delay),
        daemon=True,
        name="winwhispr-autolearn",
    )
    thread.start()
    return thread


def _observe(inserted: str, dictionary, delay: float) -> None:
    import time

    focus = focused_identity()
    if focus is None:
        return
    time.sleep(delay)
    # Re-acquire rather than holding the element across the wait: the COM object
    # belongs to the apartment that created it, and the user may have moved on.
    after_focus = focused_identity()
    if after_focus is None or after_focus[0] != focus[0]:
        return  # focus moved elsewhere; whatever is there now is not our text
    after = read_focused_text()
    if not after:
        return
    found = detect_correction(inserted, after)
    if found is None:
        return
    if dictionary.add(found.correct, [found.mishear], source=SOURCE_AUTO):
        # Log the lesson, never the text it came from.
        _log.info("auto-learned: %r -> %r", found.mishear, found.correct)


def focused_identity():
    """(process id, runtime id) of the focused element, or None."""
    element = _focused_element()
    if element is None:
        return None
    try:
        return (int(element.CurrentProcessId), tuple(element.GetRuntimeId()))
    except Exception:
        return None


def read_focused_text() -> str:
    """Best-effort text of the focused element."""
    element = _focused_element()
    if element is None:
        return ""
    for reader in (_read_text_pattern, _read_value_pattern, _read_legacy_pattern):
        try:
            text = reader(element)
        except Exception:
            continue
        if text:
            return text
    return ""


def _automation():
    """A UI Automation client for the calling thread.

    COM objects are apartment-bound, so this is created per call rather than
    cached — the cost is trivial against a 7 second wait.
    """
    import comtypes.client

    # Generated wrappers must land somewhere writable; inside a frozen bundle
    # (Program Files) they cannot be written at all.
    try:
        from core import paths

        gen_dir = paths.data_dir() / "comtypes_gen"
        gen_dir.mkdir(parents=True, exist_ok=True)
        comtypes.client.gen_dir = str(gen_dir)
    except Exception:  # pragma: no cover - fall back to the default location
        pass

    comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
    module = comtypes.client.GetModule("UIAutomationCore.dll")
    return comtypes.client.CreateObject(
        "{ff48dba4-60ef-4201-aa87-54103eef594e}",
        interface=module.IUIAutomation,
    )


def _focused_element():
    try:
        return _automation().GetFocusedElement()
    except Exception as exc:  # pragma: no cover - COM/platform dependent
        _log.debug("Could not read the focused element: %s", exc)
        return None


def _read_text_pattern(element) -> str:
    pattern = element.GetCurrentPattern(_UIA_TEXT_PATTERN)
    if not pattern:
        return ""
    from comtypes.gen import UIAutomationClient as uia

    text = pattern.QueryInterface(uia.IUIAutomationTextPattern)
    return str(text.DocumentRange.GetText(-1) or "")


def _read_value_pattern(element) -> str:
    pattern = element.GetCurrentPattern(_UIA_VALUE_PATTERN)
    if not pattern:
        return ""
    from comtypes.gen import UIAutomationClient as uia

    return str(pattern.QueryInterface(uia.IUIAutomationValuePattern).CurrentValue or "")


def _read_legacy_pattern(element) -> str:
    pattern = element.GetCurrentPattern(_UIA_LEGACY_PATTERN)
    if not pattern:
        return ""
    from comtypes.gen import UIAutomationClient as uia

    legacy = pattern.QueryInterface(uia.IUIAutomationLegacyIAccessiblePattern)
    return str(legacy.CurrentValue or "")
