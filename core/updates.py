"""Knowing when a newer WinWhispr exists.

Deliberately the smallest thing that works: ask GitHub what the latest release
is, compare it to what is running, and if it is newer, say so once. No
downloading, no unpacking, no replacing a running executable. An updater that
can rewrite the app is a large amount of trust and a large amount of code, and
for a tool this size "there is a new version, here is the link" is the whole
of the value.

Everything here fails quietly. A machine with no network, a rate limit, a
GitHub outage: none of them are the user's problem, and none of them may stop
an app whose actual job is typing what you say.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

_log = logging.getLogger("winwhispr.updates")

REPO = "Vatsa10/WindowWhispr"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"

#: GitHub blocks requests with no User-Agent outright.
USER_AGENT = "WinWhispr-update-check"

#: Checked at most this often. The answer changes on the order of weeks, and
#: an unauthenticated caller gets sixty API requests an hour to share with
#: everything else on the machine.
CHECK_EVERY = timedelta(days=1)

TIMEOUT_SECONDS = 6

_VERSION = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def parse(version: str) -> tuple[int, int, int]:
    """A version string as numbers, ignoring any `v` prefix or suffix.

    Unparseable input becomes (0, 0, 0), which compares as older than
    everything -- so a malformed local version offers an update rather than
    hiding one, and a malformed remote version is never newer than what is
    installed.
    """
    match = _VERSION.search(str(version or ""))
    if not match:
        return (0, 0, 0)
    return tuple(int(part) if part else 0 for part in match.groups())  # type: ignore[return-value]


def is_newer(latest: str, current: str) -> bool:
    """Whether `latest` is a version worth telling the user about."""
    return parse(latest) > parse(current)


def current_version() -> str:
    """The running version, from the VERSION file beside the app."""
    from core import paths

    try:
        return (paths.resource_dir() / "VERSION").read_text(encoding="utf-8").strip()
    except Exception:
        return "0.0.0"


def _stamp_path() -> Path:
    from core import paths

    return paths.data_dir() / "update-check.json"


def _read_stamp() -> dict:
    try:
        return json.loads(_stamp_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_stamp(payload: dict) -> None:
    try:
        path = _stamp_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as exc:
        _log.debug("could not record the update check: %s", exc)


def due(now=None) -> bool:
    """Whether enough time has passed to ask again."""
    last = _read_stamp().get("checked_at")
    if not last:
        return True
    try:
        checked = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
    except ValueError:
        return True
    if not checked.tzinfo:
        checked = checked.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - checked >= CHECK_EVERY


def fetch_latest(url: str = LATEST_URL) -> str:
    """The latest published version, or "" if it cannot be determined."""
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        _log.debug("update check failed: %s", exc)
        return ""
    return str(payload.get("tag_name") or payload.get("name") or "").strip()


def check(force: bool = False, now=None) -> dict:
    """Look for a newer release, at most once a day unless forced.

    Returns what the caller needs to say something useful, and never raises.
    """
    current = current_version()
    if not force and not due(now):
        return {"checked": False, "update": False, "current": current}

    latest = fetch_latest()
    _write_stamp({"checked_at": (now or datetime.now(timezone.utc)).isoformat(),
                  "latest": latest})
    if not latest:
        return {"checked": True, "update": False, "current": current}
    return {
        "checked": True,
        "update": is_newer(latest, current),
        "current": current,
        "latest": latest.lstrip("vV"),
        "url": RELEASES_PAGE,
    }
