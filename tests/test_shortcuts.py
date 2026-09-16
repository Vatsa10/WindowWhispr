"""The Start Menu entry.

An app that does not appear when you type its name is an app most people
cannot launch. The installer makes this entry; the portable build has to offer
to make it itself.
"""

from pathlib import Path

from core import shortcuts


def test_the_entry_goes_in_the_users_own_start_menu(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    expected = tmp_path / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    assert shortcuts.start_menu_dir() == expected
    assert shortcuts.shortcut_path() == expected / "WinWhispr.lnk"


def test_no_shortcut_is_offered_when_running_from_source(monkeypatch):
    """A Start Menu item that launches a development checkout is not something
    to create behind somebody's back."""
    monkeypatch.setattr("core.paths.is_frozen", lambda: False)
    assert shortcuts.target() is None
    assert shortcuts.create() is False


def test_a_packaged_build_points_at_its_own_executable(monkeypatch):
    monkeypatch.setattr("core.paths.is_frozen", lambda: True)
    monkeypatch.setattr("sys.executable", r"C:\Apps\WinWhispr\WinWhispr.exe")
    assert shortcuts.target() == Path(r"C:\Apps\WinWhispr\WinWhispr.exe")


def test_removing_what_is_not_there_is_success(monkeypatch, tmp_path):
    # Untoggling a setting that was never on must not report a failure.
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert shortcuts.remove() is True


def test_removing_deletes_the_entry(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    link = shortcuts.shortcut_path()
    link.parent.mkdir(parents=True, exist_ok=True)
    link.write_bytes(b"not really a shortcut")
    assert shortcuts.exists() is True
    assert shortcuts.remove() is True
    assert shortcuts.exists() is False


def test_a_path_with_an_apostrophe_cannot_break_the_command(monkeypatch, tmp_path):
    """The script is built as PowerShell source, so a quote in a path would
    otherwise end the string early and run whatever followed."""
    sent = {}
    monkeypatch.setattr("core.paths.is_frozen", lambda: True)
    monkeypatch.setattr("sys.executable", str(tmp_path / "Bob's Apps" / "WinWhispr.exe"))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(shortcuts, "_run", lambda script: sent.setdefault("script", script) or True)
    monkeypatch.setattr(shortcuts, "exists", lambda: True)

    assert shortcuts.create() is True
    # Every apostrophe from the path appears doubled inside the quoted string.
    assert "Bob''s Apps" in sent["script"]


def test_a_powershell_failure_is_reported_not_raised(monkeypatch, tmp_path):
    monkeypatch.setattr("core.paths.is_frozen", lambda: True)
    monkeypatch.setattr("sys.executable", str(tmp_path / "WinWhispr.exe"))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(shortcuts, "_run", lambda script: False)
    assert shortcuts.create() is False


def test_set_enabled_goes_both_ways(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    calls = []
    monkeypatch.setattr(shortcuts, "create", lambda: calls.append("create") or True)
    monkeypatch.setattr(shortcuts, "remove", lambda: calls.append("remove") or True)
    shortcuts.set_enabled(True)
    shortcuts.set_enabled(False)
    assert calls == ["create", "remove"]
