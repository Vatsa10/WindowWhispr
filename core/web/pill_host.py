"""The window that does the listening.

Edge's WebView2 has a real speech service behind ``SpeechRecognition``; Qt's
WebEngine only has the constructor and terminates the renderer the moment you
call ``start()``. So the recognizer lives in a WebView2 window rather than in
the Qt app, and this module is that window.

It cannot be hidden. Chromium freezes the renderer of a window that is hidden
or off-screen, and a frozen renderer hears nothing -- measured: neither
produced so much as an ``onstart``. What it CAN be is tiny and faint: a 16px
window at 35% opacity still reported ``onstart``, ``onaudiostart``,
``onspeechstart`` and a transcript. So idle is a dot in a corner you choose,
and the window only grows when there is something to say.

It runs as a child process because pywebview drives its own Win32 event loop,
which cannot share a process with Qt's.
"""

from __future__ import annotations

import sys

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
          corner: str = DEFAULT_CORNER) -> tuple[int, int]:
    """Where a window of this size sits, in the chosen corner.

    Anchored by the corner rather than by the top-left, so growing from the dot
    into the pill expands inward instead of pushing the window off the screen.
    """
    width, height = SIZES.get(size, SIZES["dot"])
    if corner not in CORNERS:
        corner = DEFAULT_CORNER
    right = corner.endswith("right")
    bottom = corner.startswith("bottom")

    x = screen_width - width - MARGIN_X if right else MARGIN_X
    y = screen_height - height - MARGIN_BOTTOM if bottom else MARGIN_TOP
    return max(0, x), max(0, y)


class Api:
    """What the page is allowed to ask of its own window.

    Deliberately small. The page is served over HTTP and this is a native
    bridge into the host process, so the surface stays short enough to read.
    """

    def __init__(self) -> None:
        # Underscored on purpose: pywebview exposes the public surface of this
        # object to JavaScript and walks what it finds, and walking a Window
        # recurses through its native widget tree until the stack gives out.
        self._window = None
        self._app = None
        self._screen = (1920, 1080)
        self._size = ""
        self._corner = DEFAULT_CORNER

    def bind(self, window, screen: tuple[int, int], corner: str = DEFAULT_CORNER) -> None:
        self._window = window
        self._screen = screen
        self._corner = corner if corner in CORNERS else DEFAULT_CORNER

    def set_size(self, size: str) -> None:
        """Grow or shrink to the size for a state."""
        if self._window is None or size == self._size or size not in SIZES:
            return
        self._size = size
        width, height = SIZES[size]
        x, y = place(*self._screen, size=size, corner=self._corner)
        self._window.resize(width, height)
        self._window.move(x, y)

    def set_corner(self, corner: str) -> None:
        """Move to a different corner, chosen in settings."""
        if self._window is None or corner not in CORNERS or corner == self._corner:
            return
        self._corner = corner
        x, y = place(*self._screen, size=self._size or "dot", corner=corner)
        self._window.move(x, y)

    def open_app(self, url: str) -> None:
        """Open the settings window, or raise the one already open.

        Both windows live here because pywebview drives one event loop per
        process; a second process would be a second loop and a second WebView2
        runtime for no gain.
        """
        import webview

        if self._app is not None:
            try:
                self._app.restore()
                return
            except Exception:
                self._app = None  # it was closed; fall through and rebuild

        window = webview.create_window(
            "WinWhispr",
            url,
            width=APP_WIDTH,
            height=APP_HEIGHT,
            min_size=APP_MIN_SIZE,
            background_color="#0F172A",
        )
        self._app = window

        def forget():
            self._app = None

        window.events.closed += forget

    def quit(self) -> None:
        if self._window is not None:
            self._window.destroy()


def run(url: str, corner: str = DEFAULT_CORNER) -> None:
    """Open the pill on `url` and stay there until it is closed."""
    import webview

    screen = webview.screens[0] if webview.screens else None
    width = getattr(screen, "width", 1920)
    height = getattr(screen, "height", 1080)

    api = Api()
    x, y = place(width, height, "arm", corner)
    start_w, start_h = SIZES["arm"]

    window = webview.create_window(
        "WinWhispr",
        url,
        js_api=api,
        width=start_w,
        height=start_h,
        x=x,
        y=y,
        frameless=True,
        easy_drag=True,      # no title bar, so the pill itself is the handle
        on_top=True,
        # Not transparent: WebView2 has no transparent backdrop on Windows and
        # asking for one leaves white corners behind a rounded pill.
        background_color="#0F172A",
    )
    api.bind(window, (width, height), corner)
    # private_mode off: the microphone grant has to survive a restart, or the
    # user re-approves the mic every time the app starts.
    webview.start(private_mode=False, storage_path=_storage_path())


def _storage_path() -> str:
    from core import paths

    directory = paths.data_dir() / "webview"
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory)


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else DEFAULT_CORNER)
