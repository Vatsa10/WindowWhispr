"""Corrections on their way to becoming dictionary entries.

Seeing a correction once proves nothing: people fix typos, change their minds,
and rewrite sentences. Seeing the same correction twice is a pattern, and a
pattern is worth remembering. So a detected correction lands here first, and
only a repeat is promoted into the dictionary proper.

That turns "I fix this every single time" into "I fix it twice and never
again", without ever interrupting to ask. Promoted entries are tagged as
learned in the dictionary screen and can be deleted there, which is the whole
of the user's control over it -- a prompt in the middle of dictation would cost
more than the mistake it prevents.

Pure logic over a small JSON file. No platform dependency: the before/after
signal that feeds it is Windows-only today, but nothing here knows that.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

_log = logging.getLogger("winwhispr.dictionary")

#: How many sightings before a correction is trusted enough to act on.
PROMOTE_AT = 2

#: A correction nobody has repeated in this long was a one-off. Without expiry
#: two unrelated typos months apart would eventually add up to a promotion.
EXPIRE_AFTER = timedelta(days=30)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(stamp: str):
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass
class Pending:
    """A correction seen at least once, not yet trusted."""

    mishear: str
    correct: str
    count: int = 1
    last_seen: str = field(default_factory=lambda: _now().isoformat())

    @property
    def key(self) -> tuple[str, str]:
        return (self.mishear.lower(), self.correct.lower())

    def is_expired(self, now=None) -> bool:
        seen = _parse(self.last_seen)
        if seen is None:
            return True  # unreadable timestamp: treat as stale rather than trust it
        return (now or _now()) - seen > EXPIRE_AFTER

    def to_json(self) -> dict:
        return {"mishear": self.mishear, "correct": self.correct,
                "count": self.count, "last_seen": self.last_seen}

    @classmethod
    def from_json(cls, raw: dict):
        mishear = str(raw.get("mishear") or "").strip()
        correct = str(raw.get("correct") or "").strip()
        if not mishear or not correct:
            return None
        try:
            count = int(raw.get("count") or 1)
        except (TypeError, ValueError):
            count = 1
        return cls(mishear=mishear, correct=correct, count=max(1, count),
                   last_seen=str(raw.get("last_seen") or _now().isoformat()))


class PendingStore:
    """The sidecar file, with the same durability rules as the dictionary.

    A corrupt or missing file is an empty store, never an error: learning is a
    convenience, and failing to dictate because a JSON file went bad would be
    an absurd trade.
    """

    def __init__(self, path: Path):
        self._path = Path(path)
        self._rows: list[Pending] = []
        self._lock = threading.RLock()

    def load(self):
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            rows = [Pending.from_json(row) for row in raw.get("pending", [])]
            self._rows = [row for row in rows if row is not None]
        except FileNotFoundError:
            self._rows = []
        except Exception as exc:
            _log.warning("pending corrections unreadable (%s); starting empty", exc)
            self._rows = []
        return self

    def rows(self) -> list[Pending]:
        with self._lock:
            return list(self._rows)

    def save(self) -> None:
        payload = {"pending": [row.to_json() for row in self.rows()]}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=str(self._path.parent),
                prefix=self._path.name, suffix=".tmp", delete=False)
            with handle as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(handle.name, self._path)
        except Exception as exc:
            _log.warning("could not save pending corrections: %s", exc)

    def prune(self, now=None) -> int:
        """Drop expired rows. Returns how many went."""
        with self._lock:
            before = len(self._rows)
            self._rows = [row for row in self._rows if not row.is_expired(now)]
            return before - len(self._rows)

    def record(self, mishear: str, correct: str, now=None) -> Pending | None:
        """Count one sighting. Returns the row, or None if it was not usable."""
        mishear = (mishear or "").strip()
        correct = (correct or "").strip()
        if not mishear or not correct or mishear.lower() == correct.lower():
            return None
        stamp = (now or _now()).isoformat()
        with self._lock:
            for row in self._rows:
                if row.key == (mishear.lower(), correct.lower()):
                    row.count += 1
                    row.last_seen = stamp
                    return row
            row = Pending(mishear=mishear, correct=correct, count=1, last_seen=stamp)
            self._rows.append(row)
            return row

    def forget(self, row: Pending) -> None:
        with self._lock:
            self._rows = [r for r in self._rows if r.key != row.key]


def observe(correction, pending: PendingStore, dictionary, now=None) -> bool:
    """Record a correction and promote it if it has now been seen enough.

    Returns True when something was promoted into the dictionary. Both stores
    are saved here so a caller cannot half-apply a promotion.
    """
    from core.dictionary import SOURCE_AUTO

    if correction is None:
        return False
    pending.prune(now)
    row = pending.record(correction.mishear, correction.correct, now)
    if row is None:
        pending.save()
        return False

    promoted = False
    if row.count >= PROMOTE_AT:
        dictionary.add(row.correct, [row.mishear], source=SOURCE_AUTO)
        dictionary.save()
        pending.forget(row)
        promoted = True
        _log.info("learned %r -> %r after %d sightings",
                  row.mishear, row.correct, row.count)
    pending.save()
    return promoted
