"""The floating status pill.

A small always-on-top, click-through lozenge near the bottom of the screen that
says what dictation is doing right now. It exists because the main window is
almost never the focused app while you dictate — without it, "is it listening?"
and "why did nothing appear?" have no answer anywhere the user is looking.

Geometry per state is a plain table so the state -> size mapping stays testable
without a display.
"""

from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from desktop.waveform import Waveform

#: Distance from the bottom of the work area (never under the taskbar).
BOTTOM_MARGIN = 56

MORPH_MS = 420

#: state -> (width, height, label). Width grows for error text so a specific
#: headline ("Dictation key isn't wired up") is not clipped into uselessness.
GEOMETRY = {
    "idle": (76, 16, ""),
    "recording": (250, 44, ""),
    "locked": (250, 44, ""),
    "transcribing": (180, 36, "Cleaning up…"),
    "done": (180, 36, "Done"),
    "cancelled": (180, 36, "Discarded"),
    "error": (300, 36, "Something's off"),
}

#: How long "done"/"discarded" linger before the pill shrinks back to idle.
LINGER_MS = 900


def geometry_for(state: str) -> tuple[int, int, str]:
    """Size and label for a bar state; unknown states fall back to idle."""
    return GEOMETRY.get(state, GEOMETRY["idle"])


class FlowPill(QWidget):
    """Always-on-top, click-through status pill."""

    def __init__(self, colors: dict):
        super().__init__(None)
        self._colors = colors
        self._state = "idle"
        self._label = ""

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool  # keeps it out of the taskbar and Alt-Tab
            | Qt.WindowTransparentForInput  # clicks pass through to the app below
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self._waveform = Waveform(colors.get("text", "#ffffff"), self)
        self._waveform.hide()

        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setDuration(MORPH_MS)

        self._linger = QTimer(self)
        self._linger.setSingleShot(True)
        self._linger.timeout.connect(lambda: self.set_state("idle"))

        self._apply_geometry(animate=False)

    # ---- public API -------------------------------------------------------

    def set_state(self, state: str, label: str | None = None) -> None:
        """Switch what the pill shows."""
        self._state = state if state in GEOMETRY else "idle"
        _w, _h, default_label = geometry_for(self._state)
        self._label = label if label is not None else default_label

        recording = self._state in ("recording", "locked")
        if recording:
            self._waveform.start()
            self._waveform.show()
        else:
            self._waveform.hide()
            self._waveform.stop()

        self._apply_geometry(animate=True)
        self.update()

        if self._state in ("done", "cancelled"):
            self._linger.start(LINGER_MS)
        else:
            self._linger.stop()

    def set_levels(self, levels) -> None:
        self._waveform.set_levels(levels)

    # ---- geometry ---------------------------------------------------------

    def _target_rect(self) -> QRect:
        width, height, _label = geometry_for(self._state)
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        # availableGeometry, not geometry: the pill must sit above the taskbar.
        area = screen.availableGeometry()
        x = area.x() + (area.width() - width) // 2
        y = area.y() + area.height() - height - BOTTOM_MARGIN
        return QRect(x, y, width, height)

    def _apply_geometry(self, animate: bool) -> None:
        target = self._target_rect()
        if animate and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(self.geometry())
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self.setGeometry(target)
        # Waveform sits between the two glyph slots.
        self._waveform.setGeometry(34, 10, max(target.width() - 68, 10), 24)

    # ---- painting ---------------------------------------------------------

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        radius = rect.height() / 2

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, QColor(self._colors.get("panel", "#12151f")))

        if self._state in ("recording", "locked"):
            self._paint_recording_glyphs(painter, rect)
        elif self._label:
            color = (
                self._colors.get("danger", "#ff5a52")
                if self._state == "error"
                else self._colors.get("muted", "#8b90a0")
            )
            painter.setPen(QColor(color))
            painter.drawText(rect, Qt.AlignCenter, self._label)

    def _paint_recording_glyphs(self, painter: QPainter, rect) -> None:
        painter.setPen(Qt.NoPen)
        # Left: cancel hint. Right: stop. Both are indicators, not buttons —
        # the window is click-through, and the keyboard drives everything.
        painter.setBrush(QColor(self._colors.get("muted", "#8b90a0")))
        painter.drawEllipse(10, rect.height() // 2 - 8, 16, 16)
        # A locked (hands-free) session is marked by the accent colour, since
        # nothing is holding the key down to tell you it is still running.
        stop_key = "accent" if self._state == "locked" else "danger"
        painter.setBrush(QColor(self._colors.get(stop_key, "#ff5a52")))
        painter.drawEllipse(rect.width() - 26, rect.height() // 2 - 8, 16, 16)
