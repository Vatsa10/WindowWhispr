"""Central logging configuration for WinWhispr.

Configures a rotating file handler under ``core.paths.log_path()`` (inside the
same ``~/.cache/winwhispr`` folder used for models/config/db) and tees stdout /
stderr into it.

This matters for the packaged (PyInstaller ``--noconsole``) build: Windows
gives a windowed app no console, so ``sys.stdout`` / ``sys.stderr`` are
``None``. Any bare ``print()`` call (the codebase uses many for diagnostics)
then raises ``AttributeError: 'NoneType' object has no attribute 'write'``,
which can abort whatever try/except block it happens inside -- turning a
successful model load into a reported "Engine error" with no useful detail.
Teeing through this module keeps prints working (writing only to the log file
when there is no real console) and gives us a persistent, inspectable log.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys

from core import paths

_configured = False


class _Tee:
    """File-like object that forwards writes to a real stream (if any) and a logger."""

    def __init__(self, original, logger: logging.Logger, level: int):
        self._original = original
        self._logger = logger
        self._level = level
        self._buffer = ""

    def write(self, message: str) -> None:
        if self._original is not None:
            try:
                self._original.write(message)
            except Exception:
                pass
        self._buffer += message
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line:
                self._logger.log(self._level, line)

    def flush(self) -> None:
        if self._original is not None:
            try:
                self._original.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        return bool(self._original and getattr(self._original, "isatty", lambda: False)())


def setup_logging() -> str:
    """Configure file logging + stdout/stderr teeing. Idempotent.

    Returns the log file path (as a string) for display/diagnostics.
    """
    global _configured
    log_file = paths.log_path()
    if _configured:
        return str(log_file)
    _configured = True

    handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    sys.stdout = _Tee(sys.stdout, logging.getLogger("stdout"), logging.INFO)
    sys.stderr = _Tee(sys.stderr, logging.getLogger("stderr"), logging.ERROR)

    def _excepthook(exc_type, exc_value, exc_tb) -> None:
        logging.getLogger("uncaught").critical(
            "Unhandled exception", exc_info=(exc_type, exc_value, exc_tb)
        )

    sys.excepthook = _excepthook

    logging.getLogger("winwhispr").info(
        "Logging initialized (frozen=%s) -> %s", paths.is_frozen(), log_file
    )
    return str(log_file)
