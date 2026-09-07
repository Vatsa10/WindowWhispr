"""Type text from the browser into whatever window has focus on this machine.

This is the bridge that makes a browser page more than a scratchpad: dictate
on a phone, and the words land in the document open on the PC.

It reuses the desktop injection discipline — save the clipboard, paste, let
slow applications read it, restore — because those details were learned the
hard way and a second copy would relearn them the hard way too.
"""

from __future__ import annotations

import logging
import time

_log = logging.getLogger("winwhispr.web")

#: Let the target application actually read the clipboard before restoring it.
#: Outlook reads asynchronously and pastes stale content if this is too short.
PASTE_SETTLE_SECONDS = 0.25


def paste_text(text: str) -> bool:
    """Put text on the clipboard, send Ctrl+V, restore the clipboard."""
    if not text:
        return False
    import keyboard
    import pyperclip

    try:
        saved = pyperclip.paste()
    except Exception:  # pragma: no cover - clipboard backend dependent
        saved = ""

    try:
        pyperclip.copy(text)
        keyboard.send("ctrl+v")
        time.sleep(PASTE_SETTLE_SECONDS)
        return True
    except Exception as exc:  # pragma: no cover - runtime guard
        _log.warning("paste from the browser failed: %s", exc)
        return False
    finally:
        try:
            pyperclip.copy(saved)
        except Exception:
            pass
