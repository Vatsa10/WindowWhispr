"""Best-effort detection of the current foreground application (Windows).

Used to tell the reformatter LLM which app the text will be pasted into, which
helps it align tone/format (e.g. an email client vs. a code editor).
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _window_title(user32, hwnd) -> str:
    try:
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value.strip()
    except Exception:
        return ""


def active_app_name() -> str:
    """Return the foreground app's executable name (e.g. "OUTLOOK", "chrome").

    Falls back to the window title, then an empty string. Never raises.
    """
    if sys.platform != "win32":
        return ""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return _window_title(user32, hwnd)

        handle = kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value
        )
        if not handle:
            return _window_title(user32, hwnd)
        try:
            size = wintypes.DWORD(260)
            buf = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                exe = os.path.basename(buf.value)
                return os.path.splitext(exe)[0]
        finally:
            kernel32.CloseHandle(handle)
        return _window_title(user32, hwnd)
    except Exception:  # pragma: no cover - platform/runtime dependent
        return ""
