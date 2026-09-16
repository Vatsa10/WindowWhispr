"""The window that does the listening.

It is a real Edge window. Qt's WebEngine has only the ``SpeechRecognition``
constructor and kills the renderer on ``start()``; WebView2 has the
constructor and the microphone but not the service behind them, failing with
``network`` after ``onaudiostart`` on a machine where Edge transcribes the
same page in the same second. Edge itself is the one host that works, so the
pill is an Edge window in app mode with its frame taken off.

It cannot be hidden. Chromium freezes the renderer of a window that is hidden
or off-screen, and a frozen renderer hears nothing -- measured: neither
produced so much as an ``onstart``. What it CAN be is tiny and faint: a 16px
window at 35% opacity still reported ``onstart``, ``onaudiostart``,
``onspeechstart`` and a transcript. So idle is a dot in a corner you choose,
and the window only grows when there is something to say.

It runs as a child process: it owns a browser process and a small HTTP
control server, which is the page's only way to ask its own window for
anything.
"""

from __future__ import annotations

import logging
import sys
import threading
import time

from core.web import edge

_log = logging.getLogger("winwhispr.pill")

#: (width, height) per state. ``dot`` is what it spends all day at.
SIZES = {
    "dot": (18, 18),
    "live": (340, 66),
    "arm": (280, 52),
    "menu": (208, 100),
}

#: The corner the dot lives in, and the margins that keep it clear of the
#: taskbar and of window edges people drag things to.
CORNERS = ("bottom-right", "bottom-left", "top-right", "top-left")
DEFAULT_CORNER = "bottom-right"
MARGIN_X = 20
MARGIN_BOTTOM = 56   # clear of the taskbar, which the reported height includes
MARGIN_TOP = 20

#: The settings window. A minimum rather than a fixed size: the layout is a
#: grid that reflows, and this is only the point below which text would clip.
APP_WIDTH = 1040
APP_HEIGHT = 700
APP_MIN_SIZE = (420, 380)


def place(screen_width: int, screen_height: int, size: str = "dot",
          corner: str = DEFAULT_CORNER, scale: float = 1.0) -> tuple[int, int]:
    """Where a window of this size sits, in the chosen corner.

    Anchored by the corner rather than by the top-left, so growing from the dot
    into the pill expands inward instead of pushing the window off the screen.

    Everything here is physical pixels, which is what the screen and the window
    are measured in; `scale` converts the CSS sizes the page is drawn in.
    """
    width, height = scaled(size, scale)
    if corner not in CORNERS:
        corner = DEFAULT_CORNER
    right = corner.endswith("right")
    bottom = corner.startswith("bottom")

    margin_x = round(MARGIN_X * scale)
    x = screen_width - width - margin_x if right else margin_x
    y = (screen_height - height - round(MARGIN_BOTTOM * scale) if bottom
         else round(MARGIN_TOP * scale))
    return max(0, x), max(0, y)


def scaled(size: str, scale: float = 1.0) -> tuple[int, int]:
    """The window size in physical pixels for a state drawn at `scale`."""
    width, height = SIZES.get(size, SIZES["dot"])
    return round(width * scale), round(height * scale)


class Api:
    """What the page is allowed to ask of its own window.

    Deliberately small. The page is served over HTTP and reaches this over
    HTTP too, so the surface stays short enough to read in one go.
    """

    def __init__(self) -> None:
        self._hwnd = None
        self._browser = None
        self._app = None
        self._app_window = None
        self._screen = (1920, 1080)
        self._size = ""
        self._corner = DEFAULT_CORNER
        self._scale = 1.0
        self.stopped = False

    def bind(self, hwnd, browser, screen: tuple[int, int],
             corner: str = DEFAULT_CORNER) -> None:
        self._hwnd = hwnd
        self._browser = browser
        self._screen = screen
        self._corner = corner if corner in CORNERS else DEFAULT_CORNER
        self._scale = edge.dpi_scale(hwnd)

    def set_size(self, size: str) -> None:
        """Grow or shrink to the size for a state."""
        if self._hwnd is None or size == self._size or size not in SIZES:
            return
        self._size = size
        self._reposition()

    def set_corner(self, corner: str) -> None:
        """Move to a different corner, chosen in settings."""
        if self._hwnd is None or corner not in CORNERS or corner == self._corner:
            return
        self._corner = corner
        self._reposition()

    def _reposition(self) -> None:
        size = self._size or "dot"
        width, height = scaled(size, self._scale)
        x, y = place(*self._screen, size=size, corner=self._corner,
                     scale=self._scale)
        print(f"[pill] {size} -> {width}x{height} at {x},{y} "
              f"(scale {self._scale})", flush=True)
        edge.place(self._hwnd, x, y, width, height, self._scale)

    def drag(self) -> None:
        if self._hwnd is not None:
            edge.drag(self._hwnd)

    def open_app(self, url: str) -> None:
        """Open the settings window, or raise the one already open."""
        if self._app_window is not None and edge.is_window(self._app_window):
            edge.raise_window(self._app_window)
            return
        before = edge.browser_windows()
        self._app = edge.launch(url, _profile(), APP_WIDTH, APP_HEIGHT)
        for _ in range(80):
            time.sleep(0.25)
            fresh = edge.browser_windows() - before
            if fresh:
                self._app_window = next(iter(fresh))
                break

    def quit(self) -> None:
        self.stopped = True


def _profile() -> str:
    """Edge's profile directory: ours, never the user's own."""
    from core import paths

    directory = paths.data_dir() / "edge"
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory)


def _control_server(api: "Api"):
    """The page's only way to talk to its window.

    A separate origin from the page, so every response says so; the calls are
    all side effects and nothing reads a reply.
    """
    import http.server
    import urllib.parse

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            value = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
            route = parsed.path
            try:
                if route == "/size":
                    api.set_size(value)
                elif route == "/corner":
                    api.set_corner(value)
                elif route == "/drag":
                    api.drag()
                elif route == "/open-app":
                    api.open_app(value)
                elif route == "/quit":
                    api.quit()
            except Exception:
                _log.exception("pill control %s failed", route)
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run(url: str, corner: str = DEFAULT_CORNER) -> None:
    """Open the pill on `url` and stay there until it is closed."""
    width, height = edge.screen_size()
    api = Api()
    server = _control_server(api)
    port = server.server_address[1]

    joiner = "&" if "?" in url else "?"
    start_w, start_h = SIZES["arm"]
    # Which window is ours is decided by what is new, not by which process
    # owns it: Edge hands the window to a browser process that already has the
    # profile open and the process we started then exits straight away.
    before = edge.browser_windows()
    browser = edge.launch(f"{url}{joiner}ctl={port}", _profile(), start_w, start_h)

    hwnd = None
    deadline = time.time() + 30
    while hwnd is None and time.time() < deadline:
        time.sleep(0.25)
        fresh = edge.browser_windows() - before
        hwnd = next(iter(fresh), None)
    if hwnd is None:
        _log.error("the pill window never appeared")
        browser.terminate()
        return

    print(f"[pill] screen {width}x{height}, corner {corner}, control port {port}",
          flush=True)
    api.bind(hwnd, browser, (width, height), corner)
    edge.strip_frame(hwnd)
    api.set_size("arm")

    try:
        # The window, not the process we launched, is the life of the pill:
        # that process is often a launcher that exits the moment Edge takes
        # over. When the window goes, so does this.
        while not api.stopped and edge.is_window(hwnd):
            time.sleep(0.3)
    finally:
        edge.close(hwnd)
        if api._app_window is not None:
            edge.close(api._app_window)
        server.shutdown()


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else DEFAULT_CORNER)
