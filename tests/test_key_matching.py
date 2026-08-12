"""The talk key must be exactly the key the user chose.

`keyboard.key_to_scan_codes("right ctrl")` returns (57629, 29, 57373), and 29
is LEFT ctrl — so hooking by key name made either Ctrl start dictation. These
tests pin the event-name matching that replaced it.
"""

import queue
import types

import pytest

from core.state import Binding, Cancel, Down, Up


class FakeListener:
    """The key-handling half of HotkeyListener, without the engine."""

    def __init__(self, ptt="right ctrl", cancel="esc"):
        self._ptt_key = ptt
        self._cancel_key = cancel
        self._ptt_down = False
        self._events = queue.Queue()
        self._now = 0

    _now_ms = staticmethod(lambda: 0)

    def _post(self, event):
        self._events.put(event)

    def drain(self):
        out = []
        while not self._events.empty():
            out.append(self._events.get())
        return out


@pytest.fixture()
def listener():
    from core.hotkey_listener import HotkeyListener

    fake = FakeListener()
    # Bind the real handler to the stand-in: the method under test only touches
    # the attributes FakeListener provides.
    fake._on_key_event = types.MethodType(HotkeyListener._on_key_event, fake)
    return fake


def key(name, event_type="down"):
    return types.SimpleNamespace(name=name, event_type=event_type)


def test_right_ctrl_starts_and_stops(listener):
    listener._on_key_event(key("right ctrl", "down"))
    listener._on_key_event(key("right ctrl", "up"))
    events = listener.drain()
    assert isinstance(events[0], Down)
    assert events[0].binding is Binding.PUSH_TO_TALK
    assert isinstance(events[1], Up)


def test_left_ctrl_is_ignored(listener):
    for name in ("ctrl", "left ctrl"):
        listener._on_key_event(key(name, "down"))
        listener._on_key_event(key(name, "up"))
    assert listener.drain() == []


def test_altgr_is_ignored(listener):
    # Windows sends a synthetic left-ctrl with AltGr; the library names the
    # event "alt gr", which must not be mistaken for the talk key.
    listener._on_key_event(key("alt gr", "down"))
    assert listener.drain() == []


def test_autorepeat_collapses_to_one_press(listener):
    for _ in range(5):
        listener._on_key_event(key("right ctrl", "down"))
    assert len(listener.drain()) == 1


def test_release_without_press_is_ignored(listener):
    listener._on_key_event(key("right ctrl", "up"))
    assert listener.drain() == []


def test_escape_cancels_on_press_only(listener):
    listener._on_key_event(key("esc", "down"))
    listener._on_key_event(key("esc", "up"))
    events = listener.drain()
    assert len(events) == 1
    assert isinstance(events[0], Cancel)


def test_key_name_matching_is_case_insensitive(listener):
    listener._on_key_event(key("Right Ctrl", "down"))
    assert len(listener.drain()) == 1


def test_other_keys_are_ignored(listener):
    for name in ("a", "shift", "space", "f13", None):
        listener._on_key_event(key(name, "down"))
    assert listener.drain() == []
