"""Shared pytest fixtures.

House rule: nothing under ``tests/`` may import PySide6, keyboard, sounddevice
or openvino at module scope. Everything tested here is pure logic, so the suite
runs on any machine (including CI without a display, a mic, or a model).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Redirect every user-writable path to a temp dir for the test."""
    from core import paths

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    return tmp_path
