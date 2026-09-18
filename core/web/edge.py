"""A real Edge window, restyled into the pill.

WebView2 ships the ``SpeechRecognition`` constructor but not the speech
service behind it: ``start()`` reaches ``onaudiostart`` and then fails with
``network``, every time, on a machine where Edge itself transcribes the same
page in the same second. So the recognizer window is Edge -- launched in app
mode, then stripped of its frame and parked in a corner by hand.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import wintypes

user32 = ctypes.windll.user32
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_uint]

GWL_STYLE = -16
WS_POPUP = -2147483648        # 0x80000000 as a signed LONG
WS_VISIBLE = 0x10000000
HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
WM_NCLBUTTONDOWN = 0x00A1
HTCAPTION = 2

CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


def executable() -> str | None:
    """Where Edge is, or None if this machine has no Edge."""
    for path in CANDIDATES:
        if os.path.exists(path):
            return path
    env = os.environ.get("PROGRAMFILES(X86)") or os.environ.get("PROGRAMFILES")
    if env:
        guess = os.path.join(env, "Microsoft", "Edge", "Application", "msedge.exe")
        if os.path.exists(guess):
            return guess
    return None


def launch(url: str, profile: str, width: int, height: int,
           app_mode: bool = True) -> subprocess.Popen:
    """Open `url` in its own Edge window, using a profile of our own.

    Our own profile so the microphone grant survives a restart and so the
    user's own Edge windows, history and session are never touched.
    """
    exe = executable()
    if exe is None:
        raise RuntimeError("Microsoft Edge was not found on this machine.")
    argv = [
        exe,
        f"--app={url}" if app_mode else url,
        f"--user-data-dir={profile}",
        f"--window-size={width},{height}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--disable-features=Translate,msEdgeSplitScreen",
    ]
    # An escape hatch for testing: it is the only way to hand Edge a recorded
    # voice instead of a microphone, and the pill runs in a child process where
    # patching this call from a test would not reach it.
    argv += os.environ.get("WINWHISPR_EDGE_FLAGS", "").split()
    return subprocess.Popen(argv)


def browser_windows() -> set[int]:
    """Every visible Chromium top-level window on the desktop.

    Not filtered by process id: Edge hands a new window to an already-running
    browser process whenever one shares the profile, so the process we start
    often owns no window at all and exits immediately.
    """
    found: set[int] = set()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            name = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, name, 64)
            if name.value == "Chrome_WidgetWin_1":
                found.add(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return found


def find_window(pid: int) -> int | None:
    """The visible top-level window belonging to `pid`, if it has one."""
    for hwnd in browser_windows():
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            return hwnd
    return None


def strip_frame(hwnd: int) -> None:
    """Remove the title bar and border, leaving only the page."""
    user32.SetWindowLongW(hwnd, GWL_STYLE, ctypes.c_long(WS_POPUP | WS_VISIBLE).value)


def _frame_slack(hwnd: int) -> tuple[int, int]:
    """How much of the window rectangle the page does not get.

    A stripped popup should be all client area, but Windows still keeps a
    little for itself; sizing the window to the pill exactly leaves the page a
    few pixels short, which is enough for it to wrap or show a scrollbar.
    """
    window = wintypes.RECT()
    client = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(window))
    user32.GetClientRect(hwnd, ctypes.byref(client))
    return ((window.right - window.left) - (client.right - client.left),
            (window.bottom - window.top) - (client.bottom - client.top))


#: Chromium draws its own title bar for an app window INSIDE the client area,
#: where taking the native frame off cannot reach it. So the window is made
#: taller by this much, moved up by the same amount, and then clipped to hide
#: it -- measured at 28 CSS pixels, and measured again by the test that pins
#: the page's viewport to the size actually asked for.
TITLE_STRIP = 28


def place(hwnd: int, x: int, y: int, width: int, height: int,
          scale: float = 1.0) -> None:
    """Move and resize, staying above other windows and never taking focus.

    `width` and `height` are the size the PAGE should end up with, in physical
    pixels. What the window is set to is larger: Chromium's own title bar and
    the frame Windows keeps both come out of the client area, and both are
    added here and then hidden again.

    Never taking focus is the point of the whole design: dictation types into
    whatever window the user was already in, so stealing focus would send the
    words to the pill instead.
    """
    strip = round(TITLE_STRIP * scale)
    flags = SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW
    slack_x, slack_y = _frame_slack(hwnd)
    outer_w = width + slack_x
    outer_h = height + strip + slack_y
    user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y - strip, outer_w, outer_h, flags)
    # Clip the title bar away. The region is in window coordinates, so cutting
    # the top off leaves exactly the page showing, at exactly `x, y`.
    region = ctypes.windll.gdi32.CreateRectRgn(0, strip, outer_w, outer_h)
    user32.SetWindowRgn(hwnd, region, True)


def rect(hwnd: int) -> tuple[int, int, int, int]:
    box = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(box))
    return box.left, box.top, box.right, box.bottom


def drag(hwnd: int) -> None:
    """Hand the drag to Windows, as if the page were a title bar."""
    user32.ReleaseCapture()
    user32.PostMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)


def screen_size() -> tuple[int, int]:
    ctypes.windll.user32.SetProcessDPIAware()
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def is_window(hwnd: int) -> bool:
    return bool(user32.IsWindow(hwnd))


def raise_window(hwnd: int) -> None:
    user32.ShowWindow(hwnd, 9)          # SW_RESTORE
    user32.SetForegroundWindow(hwnd)


def close(hwnd: int) -> None:
    """Ask the window to close, which is how Edge saves and shuts down cleanly."""
    if is_window(hwnd):
        user32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE


def dpi_scale(hwnd: int) -> float:
    """How many physical pixels the window gets per CSS pixel.

    Window rectangles are in physical pixels and the page is laid out in CSS
    pixels, which are not the same thing on a scaled display: a 340px pill on a
    150% screen needs a 510px window, and asking for 340 gets you a pill with
    scrollbars.
    """
    try:
        return user32.GetDpiForWindow(hwnd) / 96.0
    except Exception:      # pragma: no cover - very old Windows
        return 1.0


#: Chromium timestamps are microseconds since 1601, not since 1970.
_EPOCH_OFFSET_US = 11644473600 * 1_000_000


def grant_microphone(profile: str, origin: str) -> None:
    """Record the microphone as already allowed for `origin`.

    The profile belongs to us and holds one page, so there is nobody to ask:
    the user installed a dictation app, and making them click Allow in a
    frameless window the size of a pill is a worse answer than granting the
    one permission that app exists to use.

    Written before Edge starts, because Edge rewrites this file as it runs.
    Best effort: a profile that cannot be seeded just shows the prompt.
    """
    import json
    import time

    default = os.path.join(profile, "Default")
    path = os.path.join(default, "Preferences")
    try:
        os.makedirs(default, exist_ok=True)
        try:
            with open(path, encoding="utf-8") as handle:
                prefs = json.load(handle)
        except (OSError, ValueError):
            prefs = {}

        settings = (prefs.setdefault("profile", {})
                         .setdefault("content_settings", {})
                         .setdefault("exceptions", {})
                         .setdefault("media_stream_mic", {}))
        stamp = str(int(time.time() * 1_000_000) + _EPOCH_OFFSET_US)
        settings[f"{origin},*"] = {"last_modified": stamp, "setting": 1}

        temporary = path + ".new"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(prefs, handle)
        os.replace(temporary, path)
    except OSError:
        pass


HWND_NOTOPMOST = wintypes.HWND(-2)


def centre(hwnd: int, width: int, height: int,
           screen: tuple[int, int], scale: float = 1.0) -> None:
    """Put a normal window in the middle of the screen, at a usable size.

    Edge remembers where each window of a profile last sat, which is how the
    settings window came back at y=-2173 -- off the top of the screen, opened
    but invisible. Placing it explicitly makes "open the app" mean the same
    thing every time.
    """
    outer_w = round(width * scale)
    outer_h = round(height * scale)
    x = max(0, (screen[0] - outer_w) // 2)
    y = max(0, (screen[1] - outer_h) // 2)
    user32.SetWindowPos(hwnd, HWND_NOTOPMOST, x, y, outer_w, outer_h,
                        SWP_SHOWWINDOW)
