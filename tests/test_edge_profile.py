"""The microphone grant WinWhispr writes into its own Edge profile.

The pill is a frameless window the size of a lozenge; a permission prompt is a
poor thing to ask of it, and the app has no purpose without the microphone. So
the grant is written into the profile before Edge starts. These pin the shape
Chromium reads it back in.
"""

import json

import pytest

from core.web.edge import grant_microphone

ORIGIN = "http://127.0.0.1:8321"


def _prefs(profile):
    return json.loads((profile / "Default" / "Preferences").read_text(encoding="utf-8"))


def _mic(profile):
    return _prefs(profile)["profile"]["content_settings"]["exceptions"]["media_stream_mic"]


def test_the_microphone_is_allowed_for_the_page(tmp_path):
    grant_microphone(str(tmp_path), ORIGIN)
    assert _mic(tmp_path)[f"{ORIGIN},*"]["setting"] == 1


def test_it_creates_a_profile_that_does_not_exist_yet(tmp_path):
    """The first run is exactly the run that must not show a prompt."""
    profile = tmp_path / "never-used"
    grant_microphone(str(profile), ORIGIN)
    assert (profile / "Default" / "Preferences").exists()


def test_it_keeps_everything_else_in_the_file(tmp_path):
    """Edge owns this file; we add one key to it and touch nothing else."""
    default = tmp_path / "Default"
    default.mkdir()
    (default / "Preferences").write_text(json.dumps(
        {"profile": {"name": "kept", "content_settings": {"exceptions": {
            "media_stream_camera": {"http://example.test,*": {"setting": 2}}}}}}),
        encoding="utf-8")

    grant_microphone(str(tmp_path), ORIGIN)

    prefs = _prefs(tmp_path)
    assert prefs["profile"]["name"] == "kept"
    exceptions = prefs["profile"]["content_settings"]["exceptions"]
    assert exceptions["media_stream_camera"] == {"http://example.test,*": {"setting": 2}}
    assert f"{ORIGIN},*" in exceptions["media_stream_mic"]


def test_a_second_port_is_added_rather_than_replacing_the_first(tmp_path):
    """The port changes between runs, and an old grant costs nothing."""
    grant_microphone(str(tmp_path), ORIGIN)
    grant_microphone(str(tmp_path), "http://127.0.0.1:9999")
    assert len(_mic(tmp_path)) == 2


def test_an_unreadable_profile_is_survivable(tmp_path):
    """Worst case is the prompt the user would have seen anyway."""
    default = tmp_path / "Default"
    default.mkdir()
    (default / "Preferences").write_text("{not json", encoding="utf-8")
    grant_microphone(str(tmp_path), ORIGIN)
    assert _mic(tmp_path)[f"{ORIGIN},*"]["setting"] == 1


@pytest.mark.parametrize("stamp_key", ["last_modified"])
def test_the_timestamp_is_in_chromiums_epoch(tmp_path, stamp_key):
    """Microseconds since 1601. A Unix timestamp here reads as the year 1970."""
    grant_microphone(str(tmp_path), ORIGIN)
    stamp = int(_mic(tmp_path)[f"{ORIGIN},*"][stamp_key])
    assert stamp > 13_000_000_000_000_000
