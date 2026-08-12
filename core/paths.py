"""Centralized path resolution for WinWhispr.

Works both when running from source (``uv run winwhispr`` / ``python main.py``)
and when frozen with PyInstaller.

Layout:
- Read-only bundled resources (icons) resolve to the frozen bundle directory
  when packaged, or the project root when running from source.
- User-writable data (models, config, database, speaker samples, OpenVINO
  compile cache) lives under ``~/.cache/winwhispr`` (honoring ``XDG_CACHE_HOME``).
  This location is never inside a OneDrive-synced folder, so multi-GB assets
  are not uploaded/dehydrated.

To avoid re-downloading multi-GB assets for existing source checkouts, the
legacy in-repo locations (``.models``, ``config.json``, ``app_metrics.db``,
``.speakers``) are reused when they already exist in a source tree.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "winwhispr"


def is_frozen() -> bool:
    """True when running inside a PyInstaller (or similar) bundle."""
    return getattr(sys, "frozen", False)


def resource_dir() -> Path:
    """Directory holding read-only bundled resources (e.g. ``assets/``)."""
    if is_frozen():
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
        return Path(base)
    return Path(__file__).resolve().parent.parent


def asset_path(*parts: str) -> Path:
    """Resolve a file inside the bundled ``assets/`` directory."""
    return resource_dir().joinpath("assets", *parts)


def data_dir() -> Path:
    """User-writable base directory (``~/.cache/winwhispr``), created on demand."""
    root = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    path = Path(root) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _legacy_root() -> Path | None:
    """Project root of a source checkout, or None when frozen."""
    if is_frozen():
        return None
    return Path(__file__).resolve().parent.parent


def _prefer_legacy(name: str) -> Path | None:
    """Return the legacy in-repo path for ``name`` if it already exists."""
    root = _legacy_root()
    if root is None:
        return None
    candidate = root / name
    return candidate if candidate.exists() else None


def models_dir() -> Path:
    """Base directory for downloaded models (asr/llm/vad live beneath it)."""
    legacy = _prefer_legacy(".models")
    if legacy is not None:
        return legacy
    path = data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    """Location of ``config.json``."""
    legacy = _prefer_legacy("config.json")
    if legacy is not None:
        return legacy
    return data_dir() / "config.json"


def dictionary_path() -> Path:
    """Location of the personal dictionary (names and terms to spell right)."""
    return data_dir() / "dictionary.json"


def snippets_path() -> Path:
    """Location of the text-expansion snippet table."""
    return data_dir() / "snippets.json"


def db_path() -> Path:
    """Location of the SQLite analytics database."""
    legacy = _prefer_legacy("app_metrics.db")
    if legacy is not None:
        return legacy
    return data_dir() / "app_metrics.db"


def speakers_dir() -> Path:
    """Directory holding enrolled speaker WAV samples."""
    legacy = _prefer_legacy(".speakers")
    if legacy is not None:
        return legacy
    return data_dir() / "speakers"


def ov_cache_dir() -> Path:
    """Directory for OpenVINO compiled-model caching, created on demand."""
    path = data_dir() / "ov_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    """Directory for debug log files, created on demand."""
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_path() -> Path:
    """Location of the main rotating debug log file."""
    return logs_dir() / "winwhispr.log"
