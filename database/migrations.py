"""Schema migrations for the WinWhispr SQLite database.

Versioned with SQLite's built-in ``PRAGMA user_version`` — no extra table, no
extra dependency. Each migration is a list of statements applied in order; the
runner is idempotent and safe to call on every startup.

Adding a migration: append a new entry to ``_MIGRATIONS`` keyed by the version
it upgrades *to*. Prefer ``ALTER TABLE ... ADD COLUMN`` (SQLite applies it in
place, no table rebuild).
"""

from __future__ import annotations

import sqlite3

# version -> statements taking the schema from (version - 1) to version.
_MIGRATIONS: dict[int, list[str]] = {
    1: [
        # Per-session context and the raw/cleaned pair, so the cleanup pass can
        # be audited (and undone) after the fact.
        "ALTER TABLE notes ADD COLUMN app TEXT",
        "ALTER TABLE notes ADD COLUMN raw_text TEXT",
        "ALTER TABLE notes ADD COLUMN cleaned INTEGER DEFAULT 0",
        "ALTER TABLE notes ADD COLUMN chars INTEGER",
        "ALTER TABLE notes ADD COLUMN duration_ms INTEGER",
    ],
}

LATEST_VERSION = max(_MIGRATIONS) if _MIGRATIONS else 0


def current_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations. Returns the resulting schema version."""
    version = current_version(conn)
    for target in sorted(_MIGRATIONS):
        if target <= version:
            continue
        for statement in _MIGRATIONS[target]:
            try:
                conn.execute(statement)
            except sqlite3.OperationalError as exc:
                # A column can already exist when a partially-applied migration
                # is re-run (or a dev added it by hand). Anything else is real.
                if "duplicate column name" not in str(exc).lower():
                    raise
        # PRAGMA does not accept parameter binding.
        conn.execute(f"PRAGMA user_version = {int(target)}")
        version = target
    conn.commit()
    return version
