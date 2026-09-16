"""Noticing that a newer version exists.

The rules that matter: never raise, never nag, and never claim an update on
input it could not parse.
"""

from datetime import datetime, timedelta, timezone

from core.updates import CHECK_EVERY, check, due, is_newer, parse


def test_versions_compare_by_number_not_string():
    # "0.10.0" sorts before "0.9.0" as text, which is the classic way this
    # goes wrong.
    assert is_newer("0.10.0", "0.9.0")
    assert not is_newer("0.9.0", "0.10.0")


def test_a_v_prefix_is_ignored():
    assert parse("v1.2.3") == (1, 2, 3)
    assert not is_newer("v1.0.0", "1.0.0")


def test_a_partial_version_is_padded():
    assert parse("2") == (2, 0, 0)
    assert parse("2.1") == (2, 1, 0)
    assert is_newer("2.1", "2.0.9")


def test_the_same_version_is_not_an_update():
    assert not is_newer("1.4.2", "1.4.2")


def test_unparseable_input_never_claims_an_update():
    """A bad response from the network must not pop a notice."""
    assert not is_newer("", "1.0.0")
    assert not is_newer("not a version", "1.0.0")
    assert not is_newer(None, "1.0.0")


def test_an_unreadable_local_version_still_offers_the_update():
    # Better to point at a release that exists than to hide it.
    assert is_newer("1.0.0", "")


def test_a_check_is_due_when_nothing_was_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr("core.paths.data_dir", lambda: tmp_path)
    assert due() is True


def test_a_recent_check_is_not_due_again(tmp_path, monkeypatch):
    monkeypatch.setattr("core.paths.data_dir", lambda: tmp_path)
    now = datetime.now(timezone.utc)
    check(force=True, now=now)          # records the stamp
    assert due(now + CHECK_EVERY - timedelta(minutes=5)) is False
    assert due(now + CHECK_EVERY + timedelta(minutes=5)) is True


def test_a_corrupt_stamp_means_check_again(tmp_path, monkeypatch):
    monkeypatch.setattr("core.paths.data_dir", lambda: tmp_path)
    (tmp_path / "update-check.json").write_text("{ broken", encoding="utf-8")
    assert due() is True


def test_a_network_failure_is_not_an_update_and_not_an_error(tmp_path, monkeypatch):
    """The app's job is typing what you say, not reaching GitHub."""
    monkeypatch.setattr("core.paths.data_dir", lambda: tmp_path)
    monkeypatch.setattr("core.updates.fetch_latest", lambda *a, **k: "")
    result = check(force=True)
    assert result["update"] is False
    assert result["checked"] is True


def test_a_newer_release_reports_a_link(tmp_path, monkeypatch):
    monkeypatch.setattr("core.paths.data_dir", lambda: tmp_path)
    monkeypatch.setattr("core.updates.current_version", lambda: "0.1.0")
    monkeypatch.setattr("core.updates.fetch_latest", lambda *a, **k: "v0.2.0")
    result = check(force=True)
    assert result["update"] is True
    assert result["latest"] == "0.2.0"
    assert "releases" in result["url"]


def test_skipping_the_check_says_so_rather_than_guessing(tmp_path, monkeypatch):
    monkeypatch.setattr("core.paths.data_dir", lambda: tmp_path)
    monkeypatch.setattr("core.updates.fetch_latest", lambda *a, **k: "v9.9.9")
    now = datetime.now(timezone.utc)
    check(force=True, now=now)
    skipped = check(now=now)
    assert skipped["checked"] is False
    assert skipped["update"] is False
