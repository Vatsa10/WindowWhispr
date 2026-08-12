"""Launch WinWhispr when Windows starts.

Uses the per-user Run key rather than a Startup-folder shortcut: it needs no
admin rights, it is one value to read, write, and delete, and "is autostart on?"
becomes a single lookup instead of a filesystem guess.
"""

from __future__ import annotations

import logging
import sys

from core import paths

_log = logging.getLogger("winwhispr.autostart")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "WinWhispr"


def _command() -> str:
    """The command Windows should run at login."""
    if paths.is_frozen():
        return f'"{sys.executable}"'
    # From source: run the same interpreter against main.py.
    root = paths.resource_dir()
    return f'"{sys.executable}" "{root / "main.py"}"'


def is_enabled() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _type = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except Exception as exc:  # pragma: no cover - registry/platform dependent
        _log.warning("Could not read autostart setting: %s", exc)
        return False


def set_enabled(enabled: bool) -> bool:
    """Turn autostart on or off. Returns True when the change stuck."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass  # already off
        return True
    except Exception as exc:  # pragma: no cover - registry/platform dependent
        _log.warning("Could not change autostart setting: %s", exc)
        return False
