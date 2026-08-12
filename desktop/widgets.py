"""Reusable Qt widgets for the WinWhispr desktop UI."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


def _add_class(widget: QWidget, name: str) -> None:
    """Attach a QSS class-style hook via a dynamic property + object property."""
    existing = widget.property("class") or ""
    widget.setProperty("class", (existing + " " + name).strip())


def kbd(text: str) -> QLabel:
    lbl = QLabel(text)
    _add_class(lbl, "Kbd")
    lbl.setAlignment(Qt.AlignCenter)
    return lbl


class MetricCard(QFrame):
    """A dashboard KPI card: glyph, big value (+ optional unit), and a label."""

    def __init__(self, glyph: str, label: str, accent: str):
        super().__init__()
        _add_class(self, "MetricCard")
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(10)

        icon = QLabel(glyph)
        _add_class(icon, "MetricIcon")
        icon.setFixedSize(38, 38)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(f"color: {accent};")
        root.addWidget(icon)

        row = QHBoxLayout()
        row.setSpacing(4)
        row.setContentsMargins(0, 0, 0, 0)
        self._value = QLabel("0")
        _add_class(self._value, "MetricValue")
        self._unit = QLabel("")
        _add_class(self._unit, "MetricUnit")
        self._unit.setAlignment(Qt.AlignBottom)
        row.addWidget(self._value)
        row.addWidget(self._unit)
        row.addStretch(1)
        root.addLayout(row)

        self._label = QLabel(label)
        _add_class(self._label, "MetricLabel")
        self._label.setWordWrap(True)
        root.addWidget(self._label)

    def set_value(self, value: str, unit: str = "") -> None:
        self._value.setText(value)
        self._unit.setText(unit)

    def set_label(self, label: str) -> None:
        self._label.setText(label)


class CollapsibleSection(QWidget):
    """A sidebar accordion section with a clickable header and a body frame."""

    def __init__(self, glyph: str, title: str, expanded: bool = False):
        super().__init__()
        self._glyph = glyph
        self._title = title
        self._mini = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        self.header = QToolButton()
        self.header.setObjectName("SectionHeader")
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._sync_header_text()
        self.header.toggled.connect(self._on_toggled)
        root.addWidget(self.header)

        self.body = QFrame()
        self.body.setObjectName("SectionBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(12, 6, 6, 10)
        self.body_layout.setSpacing(12)
        self.body.setVisible(expanded)
        root.addWidget(self.body)

    def _sync_header_text(self) -> None:
        arrow = "\u25be" if self.header.isChecked() else "\u25b8"  # ▾ / ▸
        if self._mini:
            self.header.setText(self._glyph)
        else:
            self.header.setText(f"{self._glyph}   {self._title}    {arrow}")

    def _on_toggled(self, checked: bool) -> None:
        self.body.setVisible(checked and not self._mini)
        self._sync_header_text()

    def set_mini(self, mini: bool) -> None:
        """Icon-only mode when the sidebar is collapsed."""
        self._mini = mini
        self.body.setVisible(self.header.isChecked() and not mini)
        self._sync_header_text()

    def add_widget(self, widget: QWidget) -> None:
        self.body_layout.addWidget(widget)


class NoteCard(QFrame):
    """One activity-log entry: transcribed text + metadata + delete."""

    deleted = Signal(int)

    def __init__(self, note_id: int, text: str, meta: str, fresh: bool = False):
        super().__init__()
        self._note_id = note_id
        _add_class(self, "NoteCardFresh" if fresh else "NoteCard")

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 14, 12, 14)
        root.setSpacing(10)

        col = QVBoxLayout()
        col.setSpacing(8)
        text_label = QLabel(text)
        _add_class(text_label, "NoteText")
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        col.addWidget(text_label)

        meta_label = QLabel(meta)
        _add_class(meta_label, "NoteMeta")
        col.addWidget(meta_label)
        root.addLayout(col, 1)

        actions = QVBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        del_btn = QPushButton("\u2715")  # ✕
        del_btn.setObjectName("IconBtn")
        del_btn.setFixedSize(28, 28)
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setToolTip("Delete entry")
        del_btn.clicked.connect(lambda: self.deleted.emit(self._note_id))
        actions.addWidget(del_btn)
        actions.addStretch(1)
        root.addLayout(actions)


class SpeakerRow(QFrame):
    def __init__(self, name: str, seconds: float):
        super().__init__()
        _add_class(self, "SpeakerRow")
        row = QHBoxLayout(self)
        row.setContentsMargins(11, 9, 11, 9)
        row.setSpacing(8)
        name_lbl = QLabel(f"\U0001f464  {name}")  # 👤
        _add_class(name_lbl, "SpeakerName")
        row.addWidget(name_lbl)
        row.addStretch(1)
        meta = QLabel(f"{seconds}s")
        _add_class(meta, "SpeakerMeta")
        row.addWidget(meta)
