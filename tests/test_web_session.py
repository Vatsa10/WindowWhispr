"""Browser dictation as the desktop app owns it.

The app starts one engine, and only one: two would both hook the key and both
try to type. These pin the start/stop discipline without a window, a hook or a
microphone.
"""

import core.web.session as session
from core.web.session import PORT_ATTEMPTS, BrowserDictation


class _FakeServer:
    def __init__(self, busy_ports=()):
        self.busy = set(busy_ports)
        self.stopped = False
        self.on_transcript = None
        self.bridge = object()
        self.language = "en-US"
        self.bound = None

    def start(self, host, port):
        if port in self.busy:
            raise OSError("address in use")
        self.bound = port
        return port

    def stop(self):
        self.stopped = True


class _FakeChild:
    def __init__(self):
        self.terminated = False
        self._alive = True

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self.terminated = True
        self._alive = False

    def wait(self, timeout=None):
        self._alive = False
        return 0


def _install(monkeypatch, server, child=None):
    monkeypatch.setattr(session, "build_hotkey_services", lambda **_: server)
    monkeypatch.setattr(session, "spawn_pill", lambda url: child or _FakeChild())
    monkeypatch.setattr("core.web.server._hook_hotkey",
                        lambda bridge, key, on_change=None: None)


def test_starting_binds_hooks_and_opens_the_window(monkeypatch):
    server = _FakeServer()
    child = _FakeChild()
    _install(monkeypatch, server, child)
    dictation = BrowserDictation(port=9100)
    dictation.start()
    assert server.bound == 9100
    assert dictation.url == "http://127.0.0.1:9100/listen"
    assert dictation.is_running()


def test_a_port_held_by_a_stale_copy_is_stepped_over(monkeypatch):
    """A previous instance can still hold the port for a moment after exit."""
    server = _FakeServer(busy_ports={9100, 9101})
    _install(monkeypatch, server)
    dictation = BrowserDictation(port=9100)
    dictation.start()
    assert server.bound == 9102


def test_giving_up_says_which_port_it_tried(monkeypatch):
    server = _FakeServer(busy_ports=range(9100, 9100 + PORT_ATTEMPTS))
    _install(monkeypatch, server)
    try:
        BrowserDictation(port=9100).start()
    except RuntimeError as exc:
        assert "9100" in str(exc)
    else:
        raise AssertionError("expected a RuntimeError")


def test_stopping_closes_the_window_and_the_socket(monkeypatch):
    server = _FakeServer()
    child = _FakeChild()
    _install(monkeypatch, server, child)
    dictation = BrowserDictation(port=9100)
    dictation.start()
    dictation.stop()
    assert child.terminated and server.stopped
    assert not dictation.is_running()


def test_stopping_twice_is_safe(monkeypatch):
    """Quitting the app after the user already closed the pill must not throw."""
    _install(monkeypatch, _FakeServer())
    dictation = BrowserDictation(port=9100)
    dictation.start()
    dictation.stop()
    dictation.stop()


def test_a_transcript_is_reported_with_its_word_count(monkeypatch):
    server = _FakeServer()
    _install(monkeypatch, server)
    seen = []
    dictation = BrowserDictation(on_transcript=lambda *args: seen.append(args),
                                 port=9100)
    dictation.start()
    server.on_transcript("we should ship it")
    assert seen[0][0] == "we should ship it"
    assert seen[0][1] == 4
    assert seen[0][2] >= 0.0


def test_a_failure_to_log_does_not_lose_the_dictation(monkeypatch):
    """The words are already typed by then; a stats write must not raise back."""
    server = _FakeServer()
    _install(monkeypatch, server)

    def explode(*_):
        raise RuntimeError("database is locked")

    dictation = BrowserDictation(on_transcript=explode, port=9100)
    dictation.start()
    server.on_transcript("hello")  # must not raise


def test_empty_transcripts_are_not_logged(monkeypatch):
    server = _FakeServer()
    _install(monkeypatch, server)
    seen = []
    dictation = BrowserDictation(on_transcript=lambda *a: seen.append(a), port=9100)
    dictation.start()
    server.on_transcript("")
    assert seen == []
