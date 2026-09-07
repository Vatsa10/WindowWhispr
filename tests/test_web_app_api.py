"""The settings screen's data surface.

The window is a web page talking to a local HTTP server, so this list is the
whole of what a page on this machine can do. It is pinned deliberately: a
settings route that quietly grows powers is how a local server becomes a
liability.
"""

from core.web.app_api import RESTARTS_ENGINE, WRITABLE, needs_restart, writable_changes
from core.web.server import APP_OPS, WebServer


def test_only_known_settings_can_be_written():
    changes = writable_changes({"speech_language": "hi-IN", "config_version": 99,
                                "__proto__": "x", "groq_api_key": "leak"})
    assert changes == {"speech_language": "hi-IN"}


def test_a_secret_is_not_writable_through_the_settings_page():
    """API keys live in Windows Credential Manager, never in this route."""
    for key in ("groq_api_key", "api_key", "token"):
        assert key not in WRITABLE


def test_an_empty_request_saves_nothing():
    assert writable_changes({}) == {}
    assert writable_changes(None) == {}


def test_changing_the_engine_restarts_it():
    assert needs_restart({"speech_engine": "local"}) is True
    assert needs_restart({"asr_model": "Whisper Base (local, fast)"}) is True


def test_cosmetic_settings_do_not_restart_the_engine():
    # Rebuilding the engine takes seconds and drops the hotkey; a language or
    # a checkbox must not cost that.
    assert needs_restart({"speech_language": "hi-IN"}) is False
    assert needs_restart({"startup_mode": "listen"}) is False
    assert needs_restart({"pill_enabled": False}) is False


def test_everything_that_restarts_is_also_writable():
    assert RESTARTS_ENGINE <= WRITABLE


def test_every_request_the_page_makes_has_a_handler():
    from core.web.app_api import AppApi

    for op, (method, _takes_payload) in APP_OPS.items():
        assert hasattr(AppApi, method), f"{op} points at a missing method"


def test_an_unknown_request_is_refused_by_name():
    server = WebServer()
    server.app_api = object()
    assert "drop_tables" in server.app({"op": "drop_tables"})["error"]


def test_requests_are_refused_when_there_is_no_app_window():
    # "listen" mode serves the pill and nothing else.
    assert "not available" in WebServer().app({"op": "config"})["error"]


def test_a_failing_handler_does_not_take_the_app_down():
    """A settings screen that can crash the dictation engine is a bad trade."""
    class Broken:
        def config(self):
            raise RuntimeError("disk on fire")

    server = WebServer()
    server.app_api = Broken()
    assert server.app({"op": "config"})["error"] == "disk on fire"
