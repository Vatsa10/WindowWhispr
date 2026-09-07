"""The window that does the listening.

Edge's WebView2 has a real speech service behind ``SpeechRecognition``; Qt's
WebEngine only has the constructor and terminates the renderer the moment you
call ``start()``. So the recognizer lives in a WebView2 window rather than in
the Qt app, and this module is that window.

It is deliberately *visible*. Chromium freezes the renderer of a window that
is hidden or off-screen, and a frozen renderer hears nothing -- measured:
hidden and off-screen windows produced not even an ``onstart``, while a small
on-screen one kept transcribing with the focus elsewhere.

So the window has to stay, and the design job is to make it small enough not
to matter: a lozenge the size of a word when idle, growing only while you are
actually speaking. It runs as a child process because pywebview drives its own
Win32 event loop, which cannot share a process with Qt's.
"""

from __future__ import annotations

import sys

#: (width, height) per state. Idle is the size it spends all day at.
SIZES = {
    "idle": (128, 30),
    "live": (340, 62),
    "arm": (260, 44),
    "menu": (200, 84),
}

#: Clear of the taskbar, which the screen geometry pywebview reports includes.
BOTTOM_MARGIN = 64


def place(screen_width: int, screen_height: int, size: str = "idle") -> tuple[int, int]:
    """Bottom-centre for a given state, clamped so it is never off screen.

    Centred on width rather than pinned to a corner, so growing and shrinking
    looks like the pill breathing in place instead of sliding around.
    """
    width, height = SIZES.get(size, SIZES["idle"])
    x = max(0, (screen_width - width) // 2)
    y = max(0, screen_height - height - BOTTOM_MARGIN)
    return x, y


class Api:
    """What the page is allowed to ask of its own window.

    Deliberately two verbs. The page is served over HTTP and this is a native
    bridge into the host process, so the surface stays small enough to read.
    """

    def __init__(self) -> None:
        # Underscored on purpose: pywebview exposes the public surface of this
        # object to JavaScript and walks what it finds, and walking a Window
        # recurses through its native widget tree until the stack gives out.
        self._window = None
        self._screen = (1920, 1080)
        self._size = ""

    def bind(self, window, screen: tuple[int, int]) -> None:
        self._window = window
        self._screen = screen

    def set_size(self, size: str) -> None:
        """Grow or shrink to the size for a state."""
        if self._window is None or size == self._size or size not in SIZES:
            return
        self._size = size
        width, height = SIZES[size]
        x, y = place(*self._screen, size=size)
        self._window.resize(width, height)
        self._window.move(x, y)

    def quit(self) -> None:
        if self._window is not None:
            self._window.destroy()


def run(url: str) -> None:
    """Open the pill on `url` and stay there until it is closed."""
    import webview

    screen = webview.screens[0] if webview.screens else None
    width = getattr(screen, "width", 1920)
    height = getattr(screen, "height", 1080)

    api = Api()
    x, y = place(width, height, "arm")
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
        # asking for one leaves white triangles behind the rounded corners.
        # An opaque window the same colour as the pill has neither problem.
        background_color="#12151F",
    )
    api.bind(window, (width, height))
    # private_mode off: the microphone grant has to survive a restart, or the
    # user re-approves the mic every time the app starts.
    webview.start(private_mode=False, storage_path=_storage_path())


def _storage_path() -> str:
    from core import paths

    directory = paths.data_dir() / "webview"
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory)


if __name__ == "__main__":
    run(sys.argv[1])
