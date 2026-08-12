import sqlite3

import pytest

from database import migrations


def _legacy_db(path):
    """A database at the pre-migration (v0) schema, with one row in it."""
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE notes (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp         TEXT    NOT NULL,
            text              TEXT    NOT NULL,
            word_count        INTEGER NOT NULL,
            duration_seconds  REAL    NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO notes (timestamp, text, word_count, duration_seconds)"
        " VALUES ('2026-01-01T00:00:00', 'hello there', 2, 1.5)"
    )
    conn.commit()
    return conn


@pytest.fixture()
def conn(tmp_path):
    c = _legacy_db(tmp_path / "t.db")
    yield c
    c.close()


def _columns(conn):
    return {row[1] for row in conn.execute("PRAGMA table_info(notes)")}


def test_adds_new_columns(conn):
    assert "raw_text" not in _columns(conn)
    migrations.migrate(conn)
    assert {"app", "raw_text", "cleaned", "chars", "duration_ms"} <= _columns(conn)


def test_preserves_existing_rows(conn):
    migrations.migrate(conn)
    row = conn.execute("SELECT text, word_count FROM notes").fetchone()
    assert row == ("hello there", 2)


def test_is_rerunnable(conn):
    migrations.migrate(conn)
    before = _columns(conn)
    migrations.migrate(conn)
    migrations.migrate(conn)
    assert _columns(conn) == before
    assert migrations.current_version(conn) == migrations.LATEST_VERSION


def test_partially_applied_migration_recovers(conn):
    # A crash between the ALTER and the version bump leaves the column present
    # but user_version stale; re-running must not blow up on the duplicate.
    conn.execute("ALTER TABLE notes ADD COLUMN app TEXT")
    conn.commit()
    migrations.migrate(conn)
    assert migrations.current_version(conn) == migrations.LATEST_VERSION
