"""The window that does the listening.

Edge's WebView2 has a real speech service behind ``SpeechRecognition``; Qt's
WebEngine only has the constructor and terminates the renderer the moment you
call ``start()``. So the recognizer lives in a WebView2 window rather than in
the Qt app, and this module is that window.

It is deliberately *visible*. Chromium freezes the renderer of a window that
is hidden or off-screen, and a frozen renderer hears nothing -- measured:
hidden and off-screen windows produced not even an ``onstart``, while a small
on-screen one kept transcribing with the focus elsewhere. So the window is the
status pill the app wants on screen anyway: small, frameless, always on top,
sitting at the bottom of the screen.

It runs as a child process because pywebview drives its own Win32 event loop,
which cannot share a process with Qt's.
"""

from __future__ import annotations

import sys

#: Small enough to ignore, large enough to read a few words of transcript in.
PILL_WIDTH = 300
PILL_HEIGHT = 62

#: Clear of the taskbar, which the screen geometry pywebview reports includes.
BOTTOM_MARGIN = 68


def place(screen_width: int, screen_height: int) -> tuple[int, int]:
    """Bottom-centre of the screen, clamped so it is never off it."""
    x = max(0, (screen_width - PILL_WIDTH) // 2)
    y = max(0, screen_height - PILL_HEIGHT - BOTTOM_MARGIN)
    return x, y


def run(url: str) -> None:
    """Open the pill on `url` and stay there until the process is killed."""
    import webview

    screen = webview.screens[0] if webview.screens else None
    width = getattr(screen, "width", 1920)
    height = getattr(screen, "height", 1080)
    x, y = place(width, height)

    webview.create_window(
        "WinWhispr",
        url,
        width=PILL_WIDTH,
        height=PILL_HEIGHT,
        x=x,
        y=y,
        frameless=True,
        easy_drag=True,      # no title bar, so the pill itself is the handle
        on_top=True,
        transparent=True,
        background_color="#0A0C12",
    )
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
