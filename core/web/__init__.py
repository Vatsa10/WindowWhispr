"""Browser front end for WinWhispr.

Dictation from any browser on the network, using the browser's own speech
engine where it has one and this machine's local Whisper where it does not.
"""

from core.web.server import DEFAULT_PORT, WebServer, serve

__all__ = ["DEFAULT_PORT", "WebServer", "serve"]
