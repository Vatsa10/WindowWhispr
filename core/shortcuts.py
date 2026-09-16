"""Putting WinWhispr in the Start Menu.

The installer creates this entry. The portable build cannot, because there is
no installer to do it, and an app that does not appear when you type its name
is an app most people cannot launch at all. So it offers to add the entry
itself.

Written through PowerShell's WScript.Shell rather than a COM binding: creating
a shortcut is the only reason this app would need one, and a subprocess that
runs for a tenth of a second at the moment somebody ticks a box is a better
trade than a dependency in every build.

Per-user, so nothing here needs administrator rights.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

_log = logging.getLogger("winwhispr.shortcuts")

NAME = "WinWhispr"
DESCRIPTION = "Hold a key and speak"

#: Creating a shortcut is near-instant; anything longer than this means
#: PowerShell is wedged and waiting cannot help.
TIMEOUT_SECONDS = 20


def start_menu_dir() -> Path:
    """The current user's Start Menu programs folder."""
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def shortcut_path() -> Path:
    return start_menu_dir() / f"{NAME}.lnk"


def target() -> Path | None:
    """The executable a shortcut should point at, or None when there is none.

    Running from source there is no single executable to launch: the entry
    point is an interpreter plus a script, and a Start Menu item that runs a
    development checkout is not something to create behind someone's back.
    """
    from core import paths

    if paths.is_frozen():
        return Path(sys.executable)
    return None


def exists() -> bool:
    return shortcut_path().is_file()


def _run(script: str) -> bool:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _log.warning("could not run PowerShell: %s", exc)
        return False
    if result.returncode != 0:
        _log.warning("shortcut command failed: %s", (result.stderr or "").strip()[:200])
        return False
    return True


def create() -> bool:
    """Add the Start Menu entry. Returns True when it is there afterwards."""
    exe = target()
    if exe is None:
        _log.info("no packaged executable to point a shortcut at")
        return False

    link = shortcut_path()
    try:
        link.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _log.warning("could not reach the Start Menu folder: %s", exc)
        return False

    # Single-quoted PowerShell strings, with any embedded quote doubled, so a
    # path containing an apostrophe cannot end the string early.
    def quoted(value: str) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    ok = _run(
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(%s); "
        "$s.TargetPath = %s; "
        "$s.WorkingDirectory = %s; "
        "$s.Description = %s; "
        "$s.Save()" % (quoted(link), quoted(exe), quoted(exe.parent), quoted(DESCRIPTION))
    )
    return ok and exists()


def remove() -> bool:
    """Take the Start Menu entry away. True when it is gone afterwards."""
    link = shortcut_path()
    try:
        link.unlink(missing_ok=True)
    except OSError as exc:
        _log.warning("could not remove the Start Menu entry: %s", exc)
        return False
    return not exists()


def set_enabled(enabled: bool) -> bool:
    """Make the entry match what was asked for."""
    return create() if enabled else remove()
