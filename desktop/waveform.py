"""The dot-bar waveform drawn inside the recording pill.

Deliberately simple: one persistent timer repaints a fixed set of bars from the
latest levels. There is no per-frame widget churn, and no layout work — at 30fps
next to a live recording, that matters more than any visual sophistication.
"""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

#: Bars drawn. The engine reports fewer levels than this; they are stretched.
BAR_COUNT = 16
BAR_WIDTH = 2.4
MIN_HEIGHT = 3.0
MAX_EXTRA_HEIGHT = 20.0
FRAME_MS = 33


class Waveform(QWidget):
    """Live level display; idles with a gentle shimmer rather than a flat line."""

    def __init__(self, color: str = "#ffffff", parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._levels: list[float] = []
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.setInterval(FRAME_MS)

    def set_levels(self, levels) -> None:
        """Store the newest levels. Cheap: the timer does the drawing."""
        self._levels = list(levels or [])

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._levels = []

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)

        width = self.width()
        height = self.height()
        gap = (width - BAR_COUNT * BAR_WIDTH) / max(BAR_COUNT - 1, 1)
        now_ms = time.monotonic() * 1000.0
        levels = self._levels

        for i in range(BAR_COUNT):
            level = 0.0
            if levels:
                # Stretch the engine's few levels across all the bars.
                level = levels[int(i * len(levels) / BAR_COUNT)]
            # Silence still has to read as "listening", so never fully flatten.
            shimmer = 0.12 + 0.06 * abs(math.sin(now_ms / 260.0 + i * 0.7))
            amp = max(shimmer, level)
            bar_height = MIN_HEIGHT + amp * MAX_EXTRA_HEIGHT
            x = i * (BAR_WIDTH + gap)
            y = (height - bar_height) / 2
            painter.drawRoundedRect(
                QRectF(x, y, BAR_WIDTH, bar_height), BAR_WIDTH / 2, BAR_WIDTH / 2
            )
