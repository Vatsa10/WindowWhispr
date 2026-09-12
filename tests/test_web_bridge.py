"""The hotkey-to-browser channel.

The browser is the recognizer in this mode, so the only thing this process
gets right or wrong is *when* it tells the tab to listen. These pin that.
"""

import json
import queue

from core.web.bridge import Bridge, format_event
from core.web.server import WebServer


def test_a_new_tab_is_told_the_current_state_immediately():
    # A tab that connects mid-press must start listening, not wait for the
    # next edge -- otherwise reloading during a hold loses the utterance.
    bridge = Bridge()
    bridge.set_listening(True)
    assert bridge.subscribe().get_nowait() == {"listening": True}


def test_every_open_tab_hears_the_key():
    bridge = Bridge()
    tabs = [bridge.subscribe() for _ in range(3)]
    for tab in tabs:
        tab.get_nowait()  # the initial state
    bridge.set_listening(True)
    assert [tab.get_nowait() for tab in tabs] == [{"listening": True}] * 3


def test_key_repeat_does_not_publish_again():
    """Windows repeats WM_KEYDOWN while a key is held.

    A publish per repeat would restart the recognizer tens of times a second
    and the tab would hear nothing at all.
    """
    bridge = Bridge()
    tab = bridge.subscribe()
    tab.get_nowait()
    assert bridge.set_listening(True) is True
    for _ in range(20):
        assert bridge.set_listening(True) is False
    assert tab.get_nowait() == {"listening": True}
    assert tab.empty()


def test_a_closed_tab_stops_receiving():
    bridge = Bridge()
    tab = bridge.subscribe()
    bridge.unsubscribe(tab)
    assert bridge.tabs == 0
    bridge.set_listening(True)
    tab.get_nowait()  # only the state it was handed at subscribe time
    assert tab.empty()


def test_unsubscribe_is_safe_to_repeat():
    bridge = Bridge()
    tab: queue.Queue = bridge.subscribe()
    bridge.unsubscribe(tab)
    bridge.unsubscribe(tab)


def test_an_event_is_terminated_by_a_blank_line():
    # Server-sent events are framed by the blank line; without it the browser
    # buffers the event forever and the hotkey appears dead.
    raw = format_event({"listening": False})
    assert raw.endswith(b"\n\n")
    assert json.loads(raw.decode().removeprefix("data: ").strip()) == {"listening": False}


# --- what happens to a transcript once the tab sends it back --------------


def _server(**kwargs):
    return WebServer(tidy=lambda text: text.upper(), bridge=Bridge(), **kwargs)


def _recorder(sink):
    """Stand-in for the real paste path, which reports whether it worked."""
    def paste(text):
        sink.append(text)
        return True
    return paste


def test_a_transcript_is_cleaned_before_it_is_typed():
    typed = []
    web = _server(paste=_recorder(typed), allow_paste=True)
    assert web.final({"text": "hello there"}) == {"text": "HELLO THERE", "pasted": True}
    assert typed == ["HELLO THERE"]


def test_silence_types_nothing():
    typed = []
    web = _server(paste=_recorder(typed), allow_paste=True)
    assert web.final({"text": "   "}) == {"text": "", "pasted": False}
    assert typed == []


def test_the_text_comes_back_even_when_typing_is_off():
    """The page shows what was heard, so a disabled paste is not a dead end."""
    web = _server()
    assert web.final({"text": "hello"}) == {"text": "HELLO", "pasted": False}


def test_health_says_whether_this_is_hotkey_mode():
    assert WebServer().health()["hotkey"] is False
    assert _server().health()["hotkey"] is True


# --- the hook that turns a key press into a listening state ---------------


class _FakeEvent:
    def __init__(self, name, event_type):
        self.name = name
        self.event_type = event_type


def _hooked(monkeypatch):
    """Install the real hook against a stand-in ``keyboard`` module."""
    import sys
    import types

    from core.web import server

    module = types.ModuleType("keyboard")
    captured = {}
    module.hook = lambda fn, suppress=False: captured.setdefault("fn", fn)
    monkeypatch.setitem(sys.modules, "keyboard", module)
    bridge = Bridge()
    server._hook_hotkey(bridge, "right ctrl")
    return bridge, captured["fn"]


def test_left_ctrl_does_not_start_dictation(monkeypatch):
    """Scan codes for "right ctrl" include 29, which is LEFT ctrl.

    Hooking by scan code made either Ctrl start dictation; matching the
    event's own name is what keeps them apart.
    """
    bridge, on_event = _hooked(monkeypatch)
    on_event(_FakeEvent("ctrl", "down"))
    assert bridge.listening is False


def test_alt_gr_does_not_start_dictation(monkeypatch):
    # Windows sends a synthetic Ctrl with AltGr; the resolved name is not it.
    bridge, on_event = _hooked(monkeypatch)
    on_event(_FakeEvent("alt gr", "down"))
    assert bridge.listening is False


def test_holding_the_key_listens_and_releasing_stops(monkeypatch):
    bridge, on_event = _hooked(monkeypatch)
    on_event(_FakeEvent("right ctrl", "down"))
    assert bridge.listening is True
    on_event(_FakeEvent("right ctrl", "up"))
    assert bridge.listening is False


def test_a_release_we_never_saw_pressed_is_ignored(monkeypatch):
    # The key can already be down when the hook is installed.
    bridge, on_event = _hooked(monkeypatch)
    on_event(_FakeEvent("right ctrl", "up"))
    assert bridge.listening is False


# --- the language, chosen once ------------------------------------------


def test_a_language_change_reaches_a_page_that_is_already_open():
    """The app is meant to run for weeks; settings must not need a restart."""
    chosen = {"tag": "en-US"}
    web = WebServer(bridge=Bridge(), language=lambda: chosen["tag"])
    assert web.health()["language"] == "en-US"
    chosen["tag"] = "hi-IN"
    assert web.health()["language"] == "hi-IN"


def test_a_plain_string_language_still_works():
    assert WebServer(language="fr-FR").health()["language"] == "fr-FR"


# --- the pill as the way back to the app ---------------------------------


def test_double_click_raises_the_app():
    """Once the window is closed to the tray the pill is the only handle."""
    raised = []
    web = _server()
    web.on_show_app = lambda: raised.append(True)
    assert web.show_app() == {"shown": True}
    assert raised == [True]


def test_asking_for_the_app_when_there_is_none_is_not_an_error():
    # "listen" mode has no desktop window; the pill must not break there.
    assert _server().show_app() == {"shown": False}


# --- the whole path a transcript takes before it is typed ----------------


def test_cleanup_can_be_turned_off(tmp_path, monkeypatch):
    """Off means the words are typed exactly as they were heard."""
    from core.web.server import build_hotkey_services

    monkeypatch.setattr("core.config_store.load_config",
                        lambda: {"cleanup_level": "none", "speech_language": "auto"})
    web = build_hotkey_services(allow_paste=False)
    spoken = "um so we should uh ship it"
    assert web.tidy({"text": spoken})["text"] == spoken


def test_cleanup_on_removes_the_fillers(monkeypatch):
    from core.web.server import build_hotkey_services

    monkeypatch.setattr("core.config_store.load_config",
                        lambda: {"cleanup_level": "light", "speech_language": "auto"})
    web = build_hotkey_services(allow_paste=False)
    tidied = web.tidy({"text": "um so we should uh ship it period"})["text"]
    assert "um" not in tidied.lower().split()
    assert tidied.endswith(".")
