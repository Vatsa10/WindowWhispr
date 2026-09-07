"""The channel between a global hotkey and a browser tab doing the listening.

The desktop app records audio and runs Whisper. This does neither: Chrome and
Edge already ship a speech recognizer, so a tab parked in the background can
be the microphone and the transcriber, and this process keeps only the two
parts a web page cannot have -- a global hotkey and the ability to type into
whatever window has focus.

    Right Ctrl down  ->  Bridge.set_listening(True)  ->  SSE  ->  tab starts
    Right Ctrl up    ->  Bridge.set_listening(False) ->  SSE  ->  tab stops,
                                                          posts the transcript

Server-sent events rather than polling, because Chrome throttles timers in a
background tab to once a minute -- a polled tab would answer the hotkey a
minute late. An open response stream is not throttled, and once recognition
is running the tab is capturing audio and exempt anyway.
"""

from __future__ import annotations

import json
import queue
import threading

#: Sent when nothing has happened for this long, so a dropped connection is
#: noticed and the browser reconnects rather than sitting on a dead socket.
KEEPALIVE_SECONDS = 15.0


class Bridge:
    """Listening state, and the subscribers watching it change.

    Every method is safe to call from the keyboard hook thread, which is the
    whole point: the hook does one non-blocking put and returns.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: set[queue.Queue] = set()
        self._listening = False

    @property
    def listening(self) -> bool:
        with self._lock:
            return self._listening

    @property
    def tabs(self) -> int:
        """How many browser tabs are currently listening for the hotkey."""
        with self._lock:
            return len(self._subscribers)

    def subscribe(self) -> queue.Queue:
        """A queue of events for one browser tab, starting with the state."""
        events: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.add(events)
            events.put({"listening": self._listening})
        return events

    def unsubscribe(self, events: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(events)

    def set_listening(self, listening: bool) -> bool:
        """Tell every tab to start or stop. Returns True if this changed it.

        Windows repeats WM_KEYDOWN while a key is held, so a hook calls this
        many times per press; only a real edge is published.
        """
        listening = bool(listening)
        with self._lock:
            if listening == self._listening:
                return False
            self._listening = listening
            targets = list(self._subscribers)
        for events in targets:
            events.put({"listening": listening})
        return True


def format_event(payload: dict) -> bytes:
    """One server-sent event. Blank line terminated, as the protocol requires."""
    return f"data: {json.dumps(payload)}\n\n".encode("utf-8")
