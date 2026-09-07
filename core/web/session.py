"""Browser dictation, owned by the desktop app.

The desktop app is the product: one thing to install, one thing in the tray,
one place to pick a language. This is the part of it that dictates using the
browser's speech engine instead of a local model -- the server, the global
hotkey, and the recognizer window, started and stopped together.

Why a child process for the window: pywebview drives its own Win32 event loop,
which cannot share a process with Qt's. Why a window at all, rather than
something invisible: Chromium freezes the renderer of a hidden or off-screen
window, and a frozen renderer hears nothing. See ``core.web.pill_host``.
"""

from __future__ import annotations

import logging
import threading
import time

from core.web.server import DEFAULT_PORT, build_hotkey_services, spawn_pill

_log = logging.getLogger("winwhispr.web")

#: Ports to try before giving up. A stale copy of the app can still hold the
#: first one for a moment, and failing to dictate over that would be absurd.
PORT_ATTEMPTS = 12


class BrowserDictation:
    """The hotkey, the server and the recognizer window as one object.

    ``on_transcript(text, words, seconds)`` and ``on_state(listening)`` are
    called from server threads, so a GUI caller must marshal them.
    """

    def __init__(self, on_transcript=None, on_state=None,
                 key: str = "right ctrl", port: int = DEFAULT_PORT):
        self._on_transcript = on_transcript
        self._on_state = on_state
        self._key = key
        self._port = port
        self._server = None
        self._child = None
        self._started_at = 0.0
        self.url = ""

    @property
    def language(self) -> str:
        return self._server.language if self._server else "auto"

    def start(self) -> None:
        """Bind, hook the key, and open the recognizer window."""
        self._server = build_hotkey_services(allow_paste=True)
        self._server.on_transcript = self._record

        bound = self._bind()
        self.url = f"http://127.0.0.1:{bound}/listen"

        from core.web.server import _hook_hotkey

        _hook_hotkey(self._server.bridge, self._key, on_change=self._on_key)
        self._child = spawn_pill(self.url)
        _log.info("browser dictation on %s, key=%s", self.url, self._key)

    def _bind(self) -> int:
        last = None
        for offset in range(PORT_ATTEMPTS):
            try:
                return self._server.start("127.0.0.1", self._port + offset)
            except OSError as exc:
                last = exc
        raise RuntimeError(f"no free port from {self._port}: {last}")

    def _on_key(self, listening: bool) -> None:
        if listening:
            self._started_at = time.monotonic()
        if self._on_state is not None:
            self._on_state(listening)

    def _record(self, text: str) -> None:
        """A finished utterance, already cleaned and typed."""
        if self._on_transcript is None or not text:
            return
        spoke = max(0.0, time.monotonic() - self._started_at) if self._started_at else 0.0
        try:
            self._on_transcript(text, len(text.split()), spoke)
        except Exception as exc:  # a logging failure must not lose dictation
            _log.warning("could not record a transcript: %s", exc)

    def stop(self) -> None:
        """Close the window and the server. Safe to call twice."""
        child, self._child = self._child, None
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=3)
            except Exception:
                child.kill()
        if self._server is not None:
            self._server.stop()
            self._server = None

    def is_running(self) -> bool:
        """False once the user has quit the pill, so the app can notice."""
        return self._child is not None and self._child.poll() is None

    def watch(self, on_closed) -> threading.Thread:
        """Call ``on_closed()`` if the recognizer window goes away."""
        def wait():
            child = self._child
            if child is None:
                return
            child.wait()
            if self._child is child:  # not a stop() we asked for
                on_closed()

        thread = threading.Thread(target=wait, daemon=True, name="winwhispr-pill-watch")
        thread.start()
        return thread
