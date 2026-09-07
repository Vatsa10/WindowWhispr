"""A small HTTP server that turns a browser into a WinWhispr microphone.

Why this exists: the desktop app can only be driven from the machine it runs
on. A browser page can be opened from a phone, a tablet, or a second laptop,
and Chrome and Edge ship a speech engine that costs nothing and returns a
transcript the moment the speaker pauses.

Three things the page can ask for:

    POST /api/stt     audio in, transcript out, for browsers with no speech
                      engine of their own. Uses this machine local Whisper,
                      so nothing leaves the network.
    POST /api/tidy    the cleanup rules and snippets this app already applies
                      to desktop dictation.
    POST /api/paste   type the text into whatever window has focus here.
    GET  /api/events  a stream telling the tab when the hotkey is held, so a
                      browser can be the recognizer for the whole desktop.
    POST /api/final   a transcript from that tab: cleaned, then typed.

Standard library only: this is a single-user server on a private network, and
a web framework would be a dependency to freeze, audit and ship for no gain.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import mimetypes
import queue
import secrets as _secrets
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core.web.bridge import KEEPALIVE_SECONDS, Bridge, format_event

_log = logging.getLogger("winwhispr.web")

DEFAULT_PORT = 8788
STATIC_DIR = Path(__file__).parent / "static"

#: Refuse audio larger than this. The page sends one utterance at a time; a
#: bigger body is a mistake or an attack, and decoding it would cost real
#: memory on the dictating machine.
MAX_BODY_BYTES = 25 * 1024 * 1024


def decode_wav(data: bytes):
    """16-bit PCM WAV bytes into float32 mono samples in [-1, 1]."""
    import numpy as np

    with wave.open(io.BytesIO(data)) as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        frames = handle.readframes(handle.getnframes())
    if width != 2:
        raise ValueError(f"expected 16-bit audio, got {width * 8}-bit")
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples


class WebServer:
    """Owns the HTTP server and the handful of things the page can do.

    The engine, cleanup and paste callables are injected rather than imported,
    so the whole surface can be exercised without a microphone, a model, or a
    keyboard hook.
    """

    def __init__(self, transcribe=None, tidy=None, paste=None, token: str = "",
                 allow_paste: bool = False, bridge=None, language: str = "auto"):
        self._transcribe = transcribe
        self._tidy = tidy
        self._paste = paste
        self.token = token
        self.allow_paste = bool(allow_paste)
        #: Present only in hotkey mode, where a browser tab is the recognizer.
        self.bridge = bridge
        #: BCP-47 tag for the recognizer, or "auto" to follow the system.
        #: A callable is re-read on every request, so changing the language in
        #: settings reaches a page that has been open for days.
        self._language = language
        self._httpd = None
        self._thread = None

    @property
    def language(self) -> str:
        value = self._language
        return value() if callable(value) else value

    def health(self) -> dict:
        return {
            "ok": True,
            "app": "WinWhispr",
            "server_stt": self._transcribe is not None,
            "paste": self.allow_paste and self._paste is not None,
            "hotkey": self.bridge is not None,
            "language": self.language,
        }

    def stt(self, payload: dict) -> dict:
        if self._transcribe is None:
            return {"error": "speech recognition is not available on the server"}
        audio_b64 = payload.get("audio") or ""
        if not audio_b64:
            return {"text": ""}
        try:
            samples = decode_wav(base64.b64decode(audio_b64))
        except Exception as exc:
            _log.warning("bad audio from the browser: %s", exc)
            return {"error": f"could not decode audio: {exc}"}
        if len(samples) < 1600:  # under 0.1s is a mis-click, not speech
            return {"text": ""}
        return {"text": (self._transcribe(samples) or "").strip()}

    def tidy(self, payload: dict) -> dict:
        text = (payload.get("text") or "").strip()
        if not text:
            return {"text": ""}
        if self._tidy is None:
            return {"text": text}
        try:
            return {"text": self._tidy(text)}
        except Exception as exc:  # cleanup is never allowed to lose words
            _log.warning("tidy failed (%s); returning the text unchanged", exc)
            return {"text": text}

    def paste(self, payload: dict) -> dict:
        if not self.allow_paste or self._paste is None:
            return {"error": "pasting is disabled on this server"}
        text = (payload.get("text") or "").strip()
        if not text:
            return {"pasted": False}
        self._paste(text)
        return {"pasted": True}

    def final(self, payload: dict) -> dict:
        """A finished utterance from the recognizer tab: clean it, type it.

        Cleanup runs first so the words that land in the document are the ones
        the desktop app would have produced -- fillers gone, spoken
        punctuation applied, snippets expanded.
        """
        text = (payload.get("text") or "").strip()
        if not text:
            return {"text": "", "pasted": False}
        text = self.tidy({"text": text})["text"]
        pasted = False
        if self.allow_paste and self._paste is not None:
            pasted = bool(self._paste(text))
        return {"text": text, "pasted": pasted}

    def build(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT):
        handler = _make_handler(self)
        self._httpd = ThreadingHTTPServer((host, port), handler)
        self._httpd.daemon_threads = True
        return self._httpd

    def start(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> int:
        """Serve on a background thread. Returns the bound port."""
        httpd = self.build(host, port)
        self._thread = threading.Thread(target=httpd.serve_forever, daemon=True,
                                        name="winwhispr-web")
        self._thread.start()
        return httpd.server_address[1]

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


def _make_handler(server: WebServer):
    class Handler(BaseHTTPRequestHandler):
        server_version = "WinWhispr"

        def log_message(self, fmt, *args):  # quieter than the default
            _log.debug("%s - %s", self.address_string(), fmt % args)

        def _send_json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            """A token is required only when one was set (i.e. off localhost)."""
            if not server.token:
                return True
            supplied = self.headers.get("X-WinWhispr-Token", "")
            if not supplied and "?" in self.path:
                # EventSource cannot set a header, so the stream carries its
                # token in the query string instead.
                from urllib.parse import parse_qs

                query = parse_qs(self.path.split("?", 1)[1])
                supplied = (query.get("token") or [""])[0]
            # Constant-time: this guards a route that types into the user
            # machine, so a timing oracle on the token is worth avoiding.
            return _secrets.compare_digest(supplied, server.token)

        def _discard_body(self, limit: int = 1024 * 1024) -> None:
            """Read and throw away a bounded amount of the request body."""
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            remaining = min(max(length, 0), limit)
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)
            # Anything larger than the cap is not worth reading to be polite
            # about; close instead of streaming it.
            self.close_connection = length > limit

        def _read_json(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return None
            if length <= 0 or length > MAX_BODY_BYTES:
                return None
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return None

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/api/health":
                return self._send_json(server.health())
            if path == "/api/events":
                return self._send_events()
            if path in ("/", "/index.html"):
                return self._send_static("index.html")
            if path in ("/listen", "/listen.html"):
                return self._send_static("listen.html")
            if path.startswith("/static/"):
                return self._send_static(path[len("/static/"):])
            self._send_json({"error": "not found"}, 404)

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            if not self._authorized():
                # Drain first: replying while the client is still uploading
                # makes Windows reset the connection, so the caller sees a
                # socket error instead of the 401 explaining what went wrong.
                self._discard_body()
                return self._send_json({"error": "unauthorized"}, 401)
            payload = self._read_json()
            if payload is None:
                self.close_connection = True
                return self._send_json({"error": "bad request"}, 400)

            if path == "/api/stt":
                return self._send_json(server.stt(payload))
            if path == "/api/tidy":
                return self._send_json(server.tidy(payload))
            if path == "/api/final":
                return self._send_json(server.final(payload))
            if path == "/api/paste":
                result = server.paste(payload)
                return self._send_json(result, 403 if result.get("error") else 200)
            self._send_json({"error": "not found"}, 404)

        def _send_events(self) -> None:
            """Hold the connection open and push listening state as it changes."""
            if server.bridge is None:
                return self._send_json({"error": "not found"}, 404)
            if not self._authorized():
                return self._send_json({"error": "unauthorized"}, 401)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            events = server.bridge.subscribe()
            try:
                while True:
                    try:
                        payload = events.get(timeout=KEEPALIVE_SECONDS)
                    except queue.Empty:
                        # A comment line: keeps proxies and the browser from
                        # deciding an idle stream has died.
                        self.wfile.write(b": keepalive\n\n")
                    else:
                        self.wfile.write(format_event(payload))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass  # the tab closed or the network went away
            finally:
                server.bridge.unsubscribe(events)
                self.close_connection = True

        def _send_static(self, name: str) -> None:
            # Resolve inside the static directory only: this server can be
            # exposed to a network, and path traversal here would hand out
            # arbitrary files from the dictating machine.
            target = (STATIC_DIR / name).resolve()
            if STATIC_DIR.resolve() not in target.parents or not target.is_file():
                return self._send_json({"error": "not found"}, 404)
            body = target.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                mimetypes.guess_type(target.name)[0] or "application/octet-stream",
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def build_services(allow_paste: bool = False):
    """Wire the real engine, cleanup and paste path. Returns (server, engine)."""
    from core import paths, snippets
    from core.asr import build_engine
    from core.cleanup import deterministic
    from core.config_store import load_config
    from core.dictionary import DictionaryStore

    config = load_config()
    engine = build_engine(config.get("asr_model", "auto"),
                          device=config.get("asr_device", "auto"))
    dictionary = DictionaryStore(paths.dictionary_path()).load()
    engine.set_vocabulary([entry.correct for entry in dictionary.entries()])
    snippet_table = snippets.load(paths.snippets_path())

    def tidy(text: str) -> str:
        return snippets.expand(deterministic.clean(text), snippet_table)

    paste = None
    if allow_paste:
        from core.web.paste import paste_text

        paste = paste_text

    server = WebServer(transcribe=engine.transcribe, tidy=tidy, paste=paste,
                       allow_paste=allow_paste)
    return server, engine


def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT,
          allow_paste: bool = False, token: str = "") -> None:
    """Run the browser front end until interrupted (blocking)."""
    web, engine = build_services(allow_paste=allow_paste)
    web.token = token

    print(f"[WinWhispr][web] warming {engine.caps.label}...")
    engine.warmup()

    httpd = web.build(host, port)
    bound = httpd.server_address[1]
    shown = _lan_address() if host == "0.0.0.0" else host
    print(f"[WinWhispr][web] open http://{shown}:{bound}")
    if token:
        print(f"[WinWhispr][web] access token: {token}")
    if allow_paste:
        print("[WinWhispr][web] typing into the focused window is ENABLED")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[WinWhispr][web] stopped")
    finally:
        httpd.server_close()


def build_hotkey_services(allow_paste: bool = True):
    """Wire hotkey mode: cleanup and typing, but no local speech model.

    The whole point of this mode is that the browser already has a recognizer,
    so nothing here loads Whisper, opens a microphone, or downloads a model.
    """
    from core import paths, snippets
    from core.cleanup import deterministic
    from core.config_store import load_config
    from core.web.languages import normalize

    snippet_table = snippets.load(paths.snippets_path())

    def language() -> str:
        # Re-read rather than captured: the app is meant to stay running, and
        # a language chosen in settings should not need a restart.
        return normalize(load_config().get("speech_language", "auto"))

    def tidy(text: str) -> str:
        return snippets.expand(deterministic.clean(text), snippet_table)

    paste = None
    if allow_paste:
        from core.web.paste import paste_text

        paste = paste_text

    return WebServer(tidy=tidy, paste=paste, allow_paste=allow_paste,
                     bridge=Bridge(), language=language)


def _hook_hotkey(bridge, key: str = "right ctrl"):
    """Publish key-down and key-up for one key. Returns the hook handle.

    Matching is on the event's own name rather than scan codes: the codes for
    "right ctrl" include 29, which is LEFT ctrl, so a scan-code hook makes
    either Ctrl start dictation. The name also identifies AltGr correctly.

    The handler runs on the library's hook thread, where anything slow stalls
    keyboard input system-wide, so it does one non-blocking publish.
    """
    import keyboard

    key = key.lower()
    held = {"down": False}

    def on_event(event):
        if (getattr(event, "name", "") or "").lower() != key:
            return
        pressed = getattr(event, "event_type", None) == "down"
        if pressed == held["down"]:
            return  # auto-repeat while held, or a release we never saw pressed
        held["down"] = pressed
        bridge.set_listening(pressed)

    return keyboard.hook(on_event, suppress=False)


def spawn_pill(url: str):
    """Start the recognizer window as a child process. Returns the process.

    A child rather than a thread: pywebview drives its own Win32 event loop
    and cannot share a process with Qt's.
    """
    import subprocess
    import sys

    if getattr(sys, "frozen", False):
        argv = [sys.executable, "pill", url]
    else:
        argv = [sys.executable, "-m", "core.web.pill_host", url]
    return subprocess.Popen(argv)


def serve_hotkey(host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                 token: str = "", key: str = "right ctrl",
                 window: bool = True) -> None:
    """Hold a key anywhere; the recognizer window listens and types the result.

    Blocking, and meant to stay running: there is no model to load, so it is
    ready the moment it starts and costs nothing while it waits.
    """
    web = build_hotkey_services(allow_paste=True)
    web.token = token

    httpd = web.build(host, port)
    bound = httpd.server_address[1]
    shown = _lan_address() if host == "0.0.0.0" else host
    url = f"http://{shown}:{bound}/listen" + (f"?token={token}" if token else "")

    try:
        _hook_hotkey(web.bridge, key)
    except Exception as exc:  # pragma: no cover - needs a real keyboard hook
        print(f"[WinWhispr][web] could not install the {key} hook: {exc}")
        print("[WinWhispr][web] try running this terminal as Administrator.")
        httpd.server_close()
        return

    print(f"[WinWhispr][web] language: {web.language}", flush=True)
    print(f"[WinWhispr][web] hold {key} in any app and speak.", flush=True)
    child = None
    if window:
        child = spawn_pill(url)
    else:
        print(f"[WinWhispr][web] open {url}", flush=True)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[WinWhispr][web] stopped")
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
        httpd.server_close()


def _lan_address() -> str:
    """This machine address on the local network, for the printed URL."""
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))  # no packets are actually sent
            return probe.getsockname()[0]
    except OSError:  # pragma: no cover - network dependent
        return socket.gethostname()
