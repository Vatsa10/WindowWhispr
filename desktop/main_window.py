"""WinWhispr native desktop window (PySide6).

A standalone Windows application (no browser / WebView) that runs the dictation
engine in-process and acts as a live activity logger. Text is injected into
whichever external app has focus; this window only shows what happened.
"""

from __future__ import annotations

import os
import sys
import threading
import logging
from datetime import datetime, timezone

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, Qt, Signal, Slot
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from core.config_store import load_config, save_config
from core.dictionary import SOURCE_AUTO, DictionaryStore
from core.hotkey_listener import HotkeyListener
from core.model_registry import (
    DEFAULT_LLM_DISPLAY,
    DEFAULT_MODEL_DISPLAY,
    list_llm_model_names,
    list_model_names,
)
from core.processor import available_devices, input_devices
from core.stats import summary
from core import autostart, secrets
from core import paths
from core import speaker
from database import db_manager
from desktop import theme
from desktop.pill import FlowPill
from desktop.widgets import (
    CollapsibleSection,
    MetricCard,
    NoteCard,
    SpeakerRow,
    kbd,
)

_ICON_PNG = str(paths.asset_path("winwhispr.png"))

_PIPELINE_KEYS = {"hotkey", "vad_threshold", "asr_model", "asr_device", "log_transcript", "min_silence_ms", "max_segment_seconds", "reformat_hotkey", "llm_model", "llm_device", "commit_mode", "cleanup_level", "cleanup_timeout_ms", "per_app_formatting", "cleanup_provider", "groq_cleanup_model", "ptt_enabled", "ptt_key", "cancel_key", "sound_on_start", "input_device", "paste_last_hotkey", "copy_last_hotkey", "autolearn_enabled", "hands_free_double_tap", "toggle_enabled"}

_log = logging.getLogger("winwhispr.gui")


def _initials(name: str) -> str:
    parts = [p for p in name.strip().split() if p]
    if not parts:
        return "B"
    return (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()


def _greeting() -> str:
    h = datetime.now().hour
    if h < 12:
        return "Good morning"
    if h < 18:
        return "Good afternoon"
    return "Good evening"


def _fmt_saved(minutes: float) -> tuple[str, str]:
    if minutes >= 60:
        return f"{minutes / 60:.1f}", "hrs"
    return f"{round(minutes)}", "min"


def _time_ago(iso: str) -> str:
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    diff = (datetime.now() - then).total_seconds()
    if diff < 60:
        return "just now"
    if diff < 3600:
        return f"{int(diff // 60)}m ago"
    if diff < 86400:
        return f"{int(diff // 3600)}h ago"
    return then.strftime("%b %d")


class EngineBridge(QObject):
    """Marshals engine callbacks (background threads) onto the Qt main thread."""

    note = Signal(str, int, float)
    state = Signal(bool)
    ready = Signal(bool)
    busy = Signal(str)
    error = Signal(str)
    speakers_changed = Signal()
    llm_state = Signal(str)
    #: Overlay pill state: idle / recording / locked / transcribing / done / ...
    bar_state = Signal(str)
    #: A failure the user needs to know about: headline, detail.
    diagnostic = Signal(str, str)
    #: Live mic levels for the overlay waveform.
    levels = Signal(list)


class MainWindow(QMainWindow):
    def __init__(self, config: dict):
        super().__init__()
        self._config = config
        self._bridge = EngineBridge()
        self._listener: HotkeyListener | None = None
        self._listener_lock = threading.Lock()
        self._collapsed = False
        #: Whether the user collapsed the sidebar themselves, as opposed to the
        #: window being too narrow for it. A deliberate choice outlives a resize.
        self._user_collapsed = False
        self._auto_collapsed = False
        self._note_cards: list[NoteCard] = []
        # Bootup readiness: the main status chip stays in the "loading" state
        # until BOTH the ASR engine and the reformatter LLM have finished
        # downloading/compiling, so LLM warm-up is visible, not silent.
        self._asr_ready = False
        self._llm_ready = False
        # One store shared with the engine, so an edit here takes effect on the
        # next dictation without an engine rebuild.
        self._dictionary = DictionaryStore(paths.dictionary_path()).load()

        self.setObjectName("Root")
        self.setWindowTitle("WinWhispr")
        self.resize(1180, 760)
        # Small enough to sit beside the app you are dictating into, which is
        # the normal way this window gets used. Everything below reflows.
        self.setMinimumSize(680, 460)
        if os.path.isfile(_ICON_PNG):
            self.setWindowIcon(QIcon(_ICON_PNG))

        central = QWidget()
        central.setObjectName("Root")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._sidebar = self._build_sidebar()
        # Animated with min/max width rather than setFixedWidth so the panel can
        # actually move; Qt clamps a fixed width instantly.
        self._sidebar_anim = QPropertyAnimation(self._sidebar, b"maximumWidth", self)
        self._sidebar_anim.setDuration(180)
        self._sidebar_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._sidebar_anim.valueChanged.connect(
            lambda value: self._sidebar.setMinimumWidth(int(value))
        )
        root.addWidget(self._sidebar)
        root.addWidget(self._build_content(), 1)

        self._bridge.note.connect(self._on_note)
        self._bridge.state.connect(self._on_state)
        self._bridge.ready.connect(self._on_ready)
        self._bridge.busy.connect(self._on_busy)
        self._bridge.error.connect(self._on_error)
        self._bridge.speakers_changed.connect(self._reload_speakers)
        self._bridge.llm_state.connect(self._on_llm_state)
        self._bridge.bar_state.connect(self._on_bar_state)
        self._bridge.diagnostic.connect(self._on_diagnostic)
        self._bridge.levels.connect(self._on_levels)

        # The overlay pill is how dictation reports itself while another app is
        # focused — which is nearly always.
        self._pill = FlowPill(theme.COLORS) if self._config.get("pill_enabled", True) else None

        # Lay out for the starting size before anything is shown, so the first
        # paint is already correct rather than snapping on the first resize.
        self._apply_breakpoints(self.width())

        self._build_tray()
        self._refresh_stats()
        self._load_notes()
        self._reload_speakers()
        self._start_engine()

    # ---- sidebar ----------------------------------------------------------

    def _build_sidebar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("Sidebar")
        bar.setMinimumWidth(280)
        bar.setMaximumWidth(280)
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(12, 16, 12, 12)
        outer.setSpacing(10)

        # brand row
        brand = QHBoxLayout()
        brand.setSpacing(10)
        mark = QLabel("B")
        mark.setObjectName("BrandMark")
        mark.setFixedSize(34, 34)
        mark.setAlignment(Qt.AlignCenter)
        brand.addWidget(mark)
        name_col = QVBoxLayout()
        name_col.setSpacing(0)
        self._brand_name = QLabel("WinWhispr")
        self._brand_name.setObjectName("BrandName")
        self._brand_sub = QLabel("Offline dictation")
        self._brand_sub.setObjectName("BrandSub")
        name_col.addWidget(self._brand_name)
        name_col.addWidget(self._brand_sub)
        brand.addLayout(name_col)
        brand.addStretch(1)
        self._collapse_btn = QPushButton("\u276e")  # ❮
        self._collapse_btn.setObjectName("CollapseBtn")
        self._collapse_btn.setFixedSize(30, 30)
        self._collapse_btn.setCursor(Qt.PointingHandCursor)
        self._collapse_btn.clicked.connect(self._toggle_sidebar)
        brand.addWidget(self._collapse_btn)
        outer.addLayout(brand)

        self._nav_label = QLabel("CONFIGURATION")
        self._nav_label.setObjectName("NavLabel")
        outer.addWidget(self._nav_label)

        # Sections live in their own scroll area: there are more of them than
        # fit a laptop screen, and the window is meant to be usable at half
        # height beside whatever you are dictating into.
        self._sidebar_sections = []
        sections_host = QWidget()
        sections_col = QVBoxLayout(sections_host)
        sections_col.setContentsMargins(0, 0, 6, 0)  # room for the scrollbar
        sections_col.setSpacing(10)

        # Ordered by how often a person actually opens them: first run needs a
        # key, then the models, then behaviour, then the rarely-touched knobs.
        section_specs = [
            ("\u2601", "Cloud (Groq)", True, self._build_cloud_section),
            ("\u25a0", "Speech model", True, self._build_model_section),
            ("\u2728", "Cleanup", True, self._build_cleanup_section),
            ("\u2328", "Dictation keys", False, self._build_behaviour_section),
            ("\u2726", "Dictionary", False, self._build_dictionary_section),
            ("\u270e", "Reformatter (LLM)", False, self._build_reformat_section),
            ("\u2261", "Voice detection", False, self._build_vad_section),
            ("\u25c9", "Speaker ID", False, self._build_speaker_section),
        ]
        for glyph, title, expanded, builder in section_specs:
            section = CollapsibleSection(glyph, title, expanded=expanded)
            try:
                builder(section)
            except Exception:
                # A broken section (e.g. device enumeration failing on some
                # machines) must not take the rest of the sidebar down with it.
                _log.exception("Sidebar section %r failed to build", title)
                err = QLabel("Unavailable \u2014 see logs")
                err.setProperty("class", "FieldLabel")
                section.add_widget(err)
            sections_col.addWidget(section)
            self._sidebar_sections.append(section)
        sections_col.addStretch(1)

        self._sidebar_scroll = QScrollArea()
        self._sidebar_scroll.setWidgetResizable(True)
        self._sidebar_scroll.setFrameShape(QFrame.NoFrame)
        self._sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._sidebar_scroll.setWidget(sections_host)
        outer.addWidget(self._sidebar_scroll, 1)

        # Footer: the one destructive action, kept away from everything else.
        self._foot = QWidget()
        foot_col = QVBoxLayout(self._foot)
        foot_col.setContentsMargins(2, 8, 2, 2)
        foot_col.setSpacing(6)

        self._reset_btn = QPushButton("\u21bb  Reset all data")
        self._reset_btn.setProperty("class", "DangerGhost")
        self._reset_btn.setCursor(Qt.PointingHandCursor)
        self._reset_btn.setToolTip("Erase usage metrics and the activity log")
        self._reset_btn.clicked.connect(self._reset_data)
        foot_col.addWidget(self._reset_btn)

        outer.addWidget(self._foot)

        return bar

    def _build_model_section(self, section: CollapsibleSection) -> None:
        lbl = QLabel("Active model")
        lbl.setProperty("class", "FieldLabel")
        section.add_widget(lbl)

        self._model_combo = QComboBox()
        models = list_model_names()
        current = self._config.get("asr_model", DEFAULT_MODEL_DISPLAY)
        if current not in models:
            models = [current, *models]
        self._model_combo.addItems(models)
        self._model_combo.setCurrentText(current)
        self._model_combo.currentTextChanged.connect(self._on_model_changed)
        section.add_widget(self._model_combo)

        dev_lbl = QLabel("Compute device")
        dev_lbl.setProperty("class", "FieldLabel")
        section.add_widget(dev_lbl)

        self._device_combo = QComboBox()
        devices = available_devices()
        current_dev = self._config.get("asr_device", "GPU")
        if current_dev not in devices:
            devices = [current_dev, *devices]
        self._device_combo.addItems(devices)
        self._device_combo.setCurrentText(current_dev)
        self._device_combo.currentTextChanged.connect(self._on_device_changed)
        section.add_widget(self._device_combo)

        self._log_check = QCheckBox("Log transcript to console")
        self._log_check.setChecked(bool(self._config.get("log_transcript", False)))
        self._log_check.toggled.connect(self._on_log_toggled)
        section.add_widget(self._log_check)

        hint = QLabel("Runs fully offline via OpenVINO. Switching reloads the engine.")
        hint.setProperty("class", "Hint")
        hint.setWordWrap(True)
        section.add_widget(hint)

    def _build_cloud_section(self, section: CollapsibleSection) -> None:
        key_label = QLabel("Groq API key")
        key_label.setProperty("class", "FieldLabel")
        section.add_widget(key_label)

        self._groq_key_edit = QLineEdit()
        self._groq_key_edit.setEchoMode(QLineEdit.Password)
        self._groq_key_edit.setPlaceholderText("gsk_…")
        self._groq_key_edit.returnPressed.connect(self._save_groq_key)
        section.add_widget(self._groq_key_edit)

        save_btn = QPushButton("Save key")
        save_btn.setProperty("class", "Ghost")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.clicked.connect(self._save_groq_key)
        section.add_widget(save_btn)

        self._groq_key_status = QLabel("")
        self._groq_key_status.setProperty("class", "Hint")
        self._groq_key_status.setWordWrap(True)
        section.add_widget(self._groq_key_status)
        self._refresh_groq_key_status()

        hint = QLabel(
            "Stored in Windows Credential Manager, never in a settings file. "
            "Free tier: 20 requests a minute, 2000 a day — WinWhispr sends one "
            "request per dictation (two if cleanup also runs on Groq)."
        )
        hint.setProperty("class", "Hint")
        hint.setWordWrap(True)
        section.add_widget(hint)

    def _refresh_groq_key_status(self) -> None:
        if secrets.has_key("groq_api_key"):
            self._groq_key_status.setText("Key saved ✓")
        else:
            self._groq_key_status.setText(
                "No key set — cloud models will not run until one is saved."
            )

    def _save_groq_key(self) -> None:
        value = self._groq_key_edit.text().strip()
        if not secrets.set_key("groq_api_key", value):
            QMessageBox.warning(
                self,
                "WinWhispr",
                "Could not write to Windows Credential Manager. See the log.",
            )
            return
        # Never keep the secret sitting in a widget after it is stored.
        self._groq_key_edit.clear()
        self._refresh_groq_key_status()
        self._rebuild_engine()

    #: The optional language model on top of the always-on rules.
    _CLEANUP_PROVIDERS = [
        ("Rules only — instant, offline", "none"),
        ("Local model — slower, handles corrections", "local"),
        ("Groq — fast, leaves this machine", "groq"),
    ]

    _CLEANUP_LEVELS = [
        ("None", "none", "Paste exactly what you said, including mistakes."),
        ("Light (recommended)", "light", "Remove filler words and fix grammar."),
        ("Medium", "medium", "Also tighten wording for clarity."),
        ("High", "high", "Rewrite for brevity and polish."),
    ]

    def _build_cleanup_section(self, section: CollapsibleSection) -> None:
        lbl = QLabel("Auto cleanup")
        lbl.setProperty("class", "FieldLabel")
        section.add_widget(lbl)

        self._cleanup_combo = QComboBox()
        for title, _value, _hint in self._CLEANUP_LEVELS:
            self._cleanup_combo.addItem(title)
        current = str(self._config.get("cleanup_level", "light")).lower()
        values = [v for _t, v, _h in self._CLEANUP_LEVELS]
        self._cleanup_combo.setCurrentIndex(values.index(current) if current in values else 1)
        self._cleanup_combo.currentIndexChanged.connect(self._on_cleanup_level_changed)
        section.add_widget(self._cleanup_combo)

        self._cleanup_hint = QLabel("")
        self._cleanup_hint.setProperty("class", "Hint")
        self._cleanup_hint.setWordWrap(True)
        section.add_widget(self._cleanup_hint)
        self._update_cleanup_hint()

        run_label = QLabel("Cleanup runs on")
        run_label.setProperty("class", "FieldLabel")
        section.add_widget(run_label)

        self._cleanup_provider_combo = QComboBox()
        for title, _value in self._CLEANUP_PROVIDERS:
            self._cleanup_provider_combo.addItem(title)
        values = [value for _t, value in self._CLEANUP_PROVIDERS]
        current = str(self._config.get("cleanup_provider", "none")).lower()
        self._cleanup_provider_combo.setCurrentIndex(
            values.index(current) if current in values else 0
        )
        self._cleanup_provider_combo.currentIndexChanged.connect(
            lambda i: self._update_config({"cleanup_provider": values[i]})
        )
        self._cleanup_provider_combo.setToolTip(
            "Filler words, stutters, spoken punctuation and capitalization are "
            "always handled on this machine, instantly. A language model adds "
            "spoken self-corrections and per-app tone — at a cost in latency, "
            "or in privacy if you pick the cloud."
        )
        section.add_widget(self._cleanup_provider_combo)

        self._per_app_check = QCheckBox("Match the app I'm typing into")
        self._per_app_check.setToolTip(
            "Shapes tone and structure for email, chat, or documents."
        )
        self._per_app_check.setChecked(bool(self._config.get("per_app_formatting", True)))
        self._per_app_check.toggled.connect(
            lambda on: self._update_config({"per_app_formatting": bool(on)})
        )
        section.add_widget(self._per_app_check)

        self._stream_check = QCheckBox("Type as I speak (no cleanup)")
        self._stream_check.setToolTip(
            "Text appears live instead of once at the end. Cleanup needs the "
            "whole sentence, so it is skipped in this mode."
        )
        self._stream_check.setChecked(
            str(self._config.get("commit_mode", "buffered")) == "stream"
        )
        self._stream_check.toggled.connect(self._on_stream_toggled)
        section.add_widget(self._stream_check)

        if self._stream_check.isChecked():
            self._cleanup_combo.setEnabled(False)
            self._per_app_check.setEnabled(False)

    def _update_cleanup_hint(self) -> None:
        idx = self._cleanup_combo.currentIndex()
        streaming = str(self._config.get("commit_mode", "buffered")) == "stream"
        if streaming:
            self._cleanup_hint.setText(
                "Disabled while “type as I speak” is on."
            )
            return
        self._cleanup_hint.setText(self._CLEANUP_LEVELS[idx][2])

    def _on_cleanup_level_changed(self, index: int) -> None:
        self._update_config({"cleanup_level": self._CLEANUP_LEVELS[index][1]})
        self._update_cleanup_hint()

    def _on_stream_toggled(self, on: bool) -> None:
        self._update_config({"commit_mode": "stream" if on else "buffered"})
        self._cleanup_combo.setEnabled(not on)
        self._per_app_check.setEnabled(not on)
        self._update_cleanup_hint()

    def _build_behaviour_section(self, section: CollapsibleSection) -> None:
        # Two controls, stated as a sentence. Everything else here is opt-in,
        # so nobody has to learn four key combinations to dictate.
        summary = QLabel(
            f"Hold <b>{self._config.get('ptt_key', 'right ctrl').title()}</b> and "
            f"speak. Let go and your words appear. "
            f"<b>{self._config.get('cancel_key', 'esc').title()}</b> throws the "
            f"recording away."
        )
        summary.setProperty("class", "Hint")
        summary.setWordWrap(True)
        section.add_widget(summary)

        key_label = QLabel("Talk key")
        key_label.setProperty("class", "FieldLabel")
        section.add_widget(key_label)

        self._ptt_key_edit = QLineEdit(self._config.get("ptt_key", "right ctrl"))
        self._ptt_key_edit.setPlaceholderText("right ctrl")
        self._ptt_key_edit.setToolTip(
            "Any single key: right ctrl, right alt, f13… Use a key you do not "
            "type with. On keyboards with AltGr, prefer f13 or right alt."
        )
        self._ptt_key_edit.editingFinished.connect(
            lambda: self._update_config({"ptt_key": self._ptt_key_edit.text().strip()})
        )
        section.add_widget(self._ptt_key_edit)

        self._ptt_check = QCheckBox("Hold a key to talk")
        self._ptt_check.setChecked(bool(self._config.get("ptt_enabled", True)))
        self._ptt_check.toggled.connect(
            lambda on: self._update_config({"ptt_enabled": bool(on)})
        )
        section.add_widget(self._ptt_check)

        extras = QLabel("EXTRA WAYS TO START")
        extras.setObjectName("NavLabel")
        section.add_widget(extras)

        self._lock_check = QCheckBox("Tap twice to keep recording")
        self._lock_check.setToolTip(
            "Off by default: a mistyped key that starts a recording which does "
            "not stop when you let go is surprising in the wrong direction."
        )
        self._lock_check.setChecked(bool(self._config.get("hands_free_double_tap", False)))
        self._lock_check.toggled.connect(
            lambda on: self._update_config({"hands_free_double_tap": bool(on)})
        )
        section.add_widget(self._lock_check)

        self._toggle_check = QCheckBox("Also use a press-on / press-off combo")
        self._toggle_check.setChecked(bool(self._config.get("toggle_enabled", False)))
        self._toggle_check.toggled.connect(self._on_toggle_enabled)
        section.add_widget(self._toggle_check)

        self._hotkey_edit = QLineEdit(self._config.get("hotkey", "ctrl+shift+space"))
        self._hotkey_edit.setPlaceholderText("ctrl+shift+space")
        self._hotkey_edit.setEnabled(self._toggle_check.isChecked())
        self._hotkey_edit.editingFinished.connect(
            lambda: self._update_config({"hotkey": self._hotkey_edit.text().strip()})
        )
        section.add_widget(self._hotkey_edit)

        mic_label = QLabel("Microphone")
        mic_label.setProperty("class", "FieldLabel")
        section.add_widget(mic_label)

        self._mic_combo = QComboBox()
        devices = input_devices()
        current = self._config.get("input_device", "") or "System default"
        if current not in devices:
            devices = [current, *devices]
        self._mic_combo.addItems(devices)
        self._mic_combo.setCurrentText(current)
        self._mic_combo.currentTextChanged.connect(
            lambda name: self._update_config(
                {"input_device": "" if name == "System default" else name}
            )
        )
        section.add_widget(self._mic_combo)

        self._sound_check = QCheckBox("Beep when recording starts")
        self._sound_check.setChecked(bool(self._config.get("sound_on_start", True)))
        self._sound_check.toggled.connect(
            lambda on: self._update_config({"sound_on_start": bool(on)})
        )
        section.add_widget(self._sound_check)

        self._autostart_check = QCheckBox("Start WinWhispr with Windows")
        self._autostart_check.setChecked(autostart.is_enabled())
        self._autostart_check.toggled.connect(self._on_autostart_toggled)
        section.add_widget(self._autostart_check)

    def _on_toggle_enabled(self, on: bool) -> None:
        self._hotkey_edit.setEnabled(bool(on))
        self._update_config({"toggle_enabled": bool(on)})

    def _on_autostart_toggled(self, on: bool) -> None:
        if not autostart.set_enabled(bool(on)):
            QMessageBox.warning(
                self,
                "WinWhispr",
                "Could not change the Windows startup setting. See the log for details.",
            )
            # Show what is actually true, not what was clicked.
            self._autostart_check.blockSignals(True)
            self._autostart_check.setChecked(autostart.is_enabled())
            self._autostart_check.blockSignals(False)

    def _build_dictionary_section(self, section: CollapsibleSection) -> None:
        self._dict_word = QLineEdit()
        self._dict_word.setPlaceholderText("Word (e.g. ChargeBee)")
        section.add_widget(self._dict_word)

        self._dict_mishears = QLineEdit()
        self._dict_mishears.setPlaceholderText("Also heard as (comma separated)")
        self._dict_mishears.returnPressed.connect(self._add_dictionary_entry)
        section.add_widget(self._dict_mishears)

        add_btn = QPushButton("Add word")
        add_btn.setProperty("class", "Ghost")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._add_dictionary_entry)
        section.add_widget(add_btn)

        self._dict_list = QListWidget()
        self._dict_list.setMaximumHeight(150)
        section.add_widget(self._dict_list)

        remove_btn = QPushButton("Remove selected")
        remove_btn.setProperty("class", "DangerGhost")
        remove_btn.setCursor(Qt.PointingHandCursor)
        remove_btn.clicked.connect(self._remove_dictionary_entry)
        section.add_widget(remove_btn)

        hint = QLabel(
            "Names and terms dictation keeps getting wrong. WinWhispr uses these as "
            "the spelling authority — it never blindly swaps the words."
        )
        hint.setProperty("class", "Hint")
        hint.setWordWrap(True)
        section.add_widget(hint)

        self._autolearn_check = QCheckBox("Learn names when I correct them")
        self._autolearn_check.setToolTip(
            "After pasting, WinWhispr reads the field back once to see whether you "
            "fixed a word. It reads whatever field has focus, so leave this off "
            "if you dictate into sensitive forms."
        )
        self._autolearn_check.setChecked(bool(self._config.get("autolearn_enabled", False)))
        self._autolearn_check.toggled.connect(
            lambda on: self._update_config({"autolearn_enabled": bool(on)})
        )
        section.add_widget(self._autolearn_check)

        self._refresh_dictionary_list()

    def _refresh_dictionary_list(self) -> None:
        self._dict_list.clear()
        for entry in self._dictionary.entries():
            label = entry.correct
            if entry.mishears:
                label += f"  ← {', '.join(entry.mishears)}"
            if entry.source == SOURCE_AUTO:
                label = f"✨ {label}"  # learned from a correction
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, entry.correct)
            self._dict_list.addItem(item)

    def _add_dictionary_entry(self) -> None:
        word = self._dict_word.text().strip()
        if not word:
            return
        mishears = [m.strip() for m in self._dict_mishears.text().split(",") if m.strip()]
        self._dictionary.add(word, mishears)
        self._dict_word.clear()
        self._dict_mishears.clear()
        self._refresh_dictionary_list()

    def _remove_dictionary_entry(self) -> None:
        item = self._dict_list.currentItem()
        if item is None:
            return
        self._dictionary.remove(item.data(Qt.UserRole))
        self._refresh_dictionary_list()

    def _build_vad_section(self, section: CollapsibleSection) -> None:
        row = QHBoxLayout()
        lbl = QLabel("Sensitivity threshold")
        lbl.setProperty("class", "FieldLabel")
        self._vad_value = QLabel(f"{float(self._config.get('vad_threshold', 0.5)):.2f}")
        self._vad_value.setProperty("class", "FieldValue")
        self._vad_value.setAlignment(Qt.AlignRight)
        row.addWidget(lbl)
        row.addWidget(self._vad_value)
        wrap = QWidget()
        wrap.setLayout(row)
        section.add_widget(wrap)

        self._vad_slider = QSlider(Qt.Horizontal)
        self._vad_slider.setMinimum(5)
        self._vad_slider.setMaximum(95)
        self._vad_slider.setValue(int(float(self._config.get("vad_threshold", 0.5)) * 100))
        self._vad_slider.valueChanged.connect(self._on_vad_preview)
        self._vad_slider.sliderReleased.connect(self._on_vad_commit)
        section.add_widget(self._vad_slider)

        hint = QLabel("Higher = clearer speech required before a segment is captured.")
        hint.setProperty("class", "Hint")
        hint.setWordWrap(True)
        section.add_widget(hint)

    def _build_speaker_section(self, section: CollapsibleSection) -> None:
        self._speaker_name = QLineEdit()
        self._speaker_name.setPlaceholderText("Speaker name")
        section.add_widget(self._speaker_name)

        self._speaker_btn = QPushButton("\u25cf  Enroll voice sample")
        self._speaker_btn.setProperty("class", "Primary")
        self._speaker_btn.setCursor(Qt.PointingHandCursor)
        self._speaker_btn.clicked.connect(self._record_speaker)
        section.add_widget(self._speaker_btn)

        self._speaker_list = QVBoxLayout()
        self._speaker_list.setSpacing(6)
        holder = QWidget()
        holder.setLayout(self._speaker_list)
        section.add_widget(holder)

        hint = QLabel("Record a short sample per person for speaker identification.")
        hint.setProperty("class", "Hint")
        hint.setWordWrap(True)
        section.add_widget(hint)

    def _build_reformat_section(self, section: CollapsibleSection) -> None:
        # LLM status
        status_row = QHBoxLayout()
        status_lbl = QLabel("Model status")
        status_lbl.setProperty("class", "FieldLabel")
        self._llm_status = QLabel("Not loaded")
        self._llm_status.setProperty("class", "FieldValue")
        self._llm_status.setAlignment(Qt.AlignRight)
        status_row.addWidget(status_lbl)
        status_row.addWidget(self._llm_status)
        status_wrap = QWidget()
        status_wrap.setLayout(status_row)
        section.add_widget(status_wrap)

        # LLM model
        model_lbl = QLabel("LLM model")
        model_lbl.setProperty("class", "FieldLabel")
        section.add_widget(model_lbl)

        self._llm_combo = QComboBox()
        llm_models = list_llm_model_names()
        current_llm = self._config.get("llm_model", DEFAULT_LLM_DISPLAY)
        if current_llm not in llm_models:
            llm_models = [current_llm, *llm_models]
        self._llm_combo.addItems(llm_models)
        self._llm_combo.setCurrentText(current_llm)
        self._llm_combo.currentTextChanged.connect(self._on_llm_model_changed)
        section.add_widget(self._llm_combo)

        # LLM device
        dev_lbl = QLabel("Compute device")
        dev_lbl.setProperty("class", "FieldLabel")
        section.add_widget(dev_lbl)

        self._llm_device_combo = QComboBox()
        devices = available_devices()
        current_dev = self._config.get("llm_device", "CPU")
        if current_dev not in devices:
            devices = [current_dev, *devices]
        self._llm_device_combo.addItems(devices)
        self._llm_device_combo.setCurrentText(current_dev)
        self._llm_device_combo.currentTextChanged.connect(self._on_llm_device_changed)
        section.add_widget(self._llm_device_combo)

        # Reformat hotkey
        hk_lbl = QLabel("Reformat hotkey")
        hk_lbl.setProperty("class", "FieldLabel")
        section.add_widget(hk_lbl)

        self._reformat_hotkey_edit = QLineEdit(
            self._config.get("reformat_hotkey", "ctrl+alt+r")
        )
        self._reformat_hotkey_edit.setPlaceholderText("ctrl+alt+r")
        self._reformat_hotkey_edit.returnPressed.connect(self._apply_reformat_hotkey)
        section.add_widget(self._reformat_hotkey_edit)

        apply_btn = QPushButton("Apply reformat hotkey")
        apply_btn.setProperty("class", "Ghost")
        apply_btn.setCursor(Qt.PointingHandCursor)
        apply_btn.clicked.connect(self._apply_reformat_hotkey)
        section.add_widget(apply_btn)

        hint = QLabel(
            "Press the reformat hotkey to rewrite all text in the focused app "
            "using the selected LLM."
        )
        hint.setProperty("class", "Hint")
        hint.setWordWrap(True)
        section.add_widget(hint)

    # ---- content ----------------------------------------------------------

    def _build_content(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        page = QWidget()
        page.setObjectName("Root")
        col = QVBoxLayout(page)
        col.setContentsMargins(34, 28, 34, 34)
        col.setSpacing(22)
        self._content_layout = col

        col.addLayout(self._build_header())
        col.addWidget(self._build_metrics())
        col.addWidget(self._build_activity(), 1)

        scroll.setWidget(page)
        return scroll

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(16)

        avatar = QLabel(_initials(self._config.get("user_name", "there")))
        avatar.setObjectName("Avatar")
        avatar.setFixedSize(52, 52)
        avatar.setAlignment(Qt.AlignCenter)
        row.addWidget(avatar)

        greet_col = QVBoxLayout()
        greet_col.setSpacing(2)
        greeting = QLabel(f"{_greeting()}, {self._config.get('user_name', 'there')}")
        greeting.setObjectName("Greeting")
        date_line = QLabel(datetime.now().strftime("%A, %B %d, %Y"))
        date_line.setObjectName("DateLine")
        greet_col.addWidget(greeting)
        greet_col.addWidget(date_line)
        row.addLayout(greet_col)
        row.addStretch(1)

        # status chip
        chip = QFrame()
        chip.setObjectName("StatusChip")
        chip_l = QHBoxLayout(chip)
        chip_l.setContentsMargins(14, 8, 16, 8)
        chip_l.setSpacing(8)
        self._status_dot = QLabel()
        self._status_dot.setFixedSize(9, 9)
        self._set_dot("#7a8199")
        self._status_text = QLabel("Starting engine\u2026")
        self._status_text.setObjectName("StatusText")
        chip_l.addWidget(self._status_dot)
        chip_l.addWidget(self._status_text)
        # Indeterminate "busy" bar shown while the engine loads / compiles.
        self._loading_bar = QProgressBar()
        self._loading_bar.setObjectName("LoadingBar")
        self._loading_bar.setRange(0, 0)
        self._loading_bar.setTextVisible(False)
        self._loading_bar.setFixedSize(96, 8)
        self._loading_bar.setStyleSheet(
            "QProgressBar{border:none;background:#2a2f45;border-radius:4px;}"
            f"QProgressBar::chunk{{background:{theme.COLORS['accent']};border-radius:4px;}}"
        )
        chip_l.addWidget(self._loading_bar)
        row.addWidget(chip)

        # hotkey hint
        hint = QFrame()
        hint.setObjectName("HotkeyHint")
        hint_l = QHBoxLayout(hint)
        hint_l.setContentsMargins(14, 8, 14, 8)
        hint_l.setSpacing(8)
        htext = QLabel("Hold to dictate")
        htext.setObjectName("HintText")
        hint_l.addWidget(htext)
        # Shows the key you actually use, so the reminder can never drift from
        # the setting.
        hint_l.addWidget(kbd(self._config.get("ptt_key", "right ctrl").title()))
        self._hotkey_hint = hint
        self._hint_chip = hint
        row.addWidget(hint)

        quit_btn = QPushButton("\u23fb")  # power symbol
        quit_btn.setObjectName("QuitBtn")
        quit_btn.setFixedSize(38, 38)
        quit_btn.setCursor(Qt.PointingHandCursor)
        quit_btn.setToolTip("Quit WinWhispr")
        quit_btn.clicked.connect(self._quit)
        row.addWidget(quit_btn)
        return row

    def _build_metrics(self) -> QWidget:
        wrap = QWidget()
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)

        title = QLabel("OVERVIEW")
        title.setProperty("class", "SectionTitle")
        col.addWidget(title)

        self._metrics_grid = QGridLayout()
        self._metrics_grid.setSpacing(14)
        self._card_words = MetricCard("\u25a4", "Words dictated", theme.COLORS["accent"])
        self._card_saved = MetricCard("\u25f7", "Time saved vs typing", theme.COLORS["success"])
        self._card_wpm = MetricCard("\u2197", "Words / minute", theme.COLORS["accent2"])
        self._card_streak = MetricCard("\u25c8", "Day streak", theme.COLORS["amber"])
        self._metric_cards = (
            self._card_words, self._card_saved, self._card_wpm, self._card_streak,
        )
        self._metric_columns = 0  # forces the first layout pass
        self._layout_metrics(4)
        col.addLayout(self._metrics_grid)
        return wrap

    def _layout_metrics(self, columns: int) -> None:
        """Reflow the metric cards into ``columns`` columns.

        Four cards side by side need ~1100px. Below that they squeeze until the
        numbers truncate, so they wrap instead.
        """
        if columns == self._metric_columns:
            return
        self._metric_columns = columns
        for card in self._metric_cards:
            self._metrics_grid.removeWidget(card)
        for index, card in enumerate(self._metric_cards):
            self._metrics_grid.addWidget(card, index // columns, index % columns)

    def _build_activity(self) -> QWidget:
        wrap = QWidget()
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel("ACTIVITY LOG")
        title.setProperty("class", "SectionTitle")
        head.addWidget(title)
        head.addStretch(1)
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search transcripts…")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.setFixedWidth(240)
        self._search_box.textChanged.connect(lambda _t: self._load_notes())
        head.addWidget(self._search_box)
        self._count_pill = QLabel("0 entries")
        self._count_pill.setObjectName("CountPill")
        head.addWidget(self._count_pill)
        col.addLayout(head)

        self._notes_container = QVBoxLayout()
        self._notes_container.setSpacing(12)
        holder = QWidget()
        holder.setLayout(self._notes_container)
        col.addWidget(holder)

        self._empty = self._build_empty_state()
        self._notes_container.addWidget(self._empty)
        self._notes_container.addStretch(1)
        return wrap

    def _build_empty_state(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("EmptyState")
        v = QVBoxLayout(frame)
        v.setContentsMargins(20, 44, 20, 44)
        v.setSpacing(8)
        v.setAlignment(Qt.AlignCenter)
        title = QLabel("No activity yet")
        title.setObjectName("EmptyTitle")
        title.setAlignment(Qt.AlignCenter)
        body = QLabel(
            "Focus any app (Gmail, Chrome, Word\u2026), press your global hotkey, "
            "and dictated text is typed there \u2014 every entry is logged here."
        )
        body.setObjectName("EmptyBody")
        body.setAlignment(Qt.AlignCenter)
        body.setWordWrap(True)
        v.addWidget(title)
        v.addWidget(body)
        return frame

    # ---- tray + titlebar --------------------------------------------------

    def _build_tray(self) -> None:
        icon = QIcon(_ICON_PNG) if os.path.isfile(_ICON_PNG) else self.windowIcon()
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("WinWhispr \u2014 offline dictation")
        menu = QMenu()
        show_action = QAction("Show WinWhispr", self)
        show_action.triggered.connect(self._show_from_tray)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def apply_dark_titlebar(self) -> None:
        """Ask Windows DWM for a dark title bar (Windows 10 2004+ / 11)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes

            hwnd = int(self.winId())
            value = ctypes.c_int(1)
            for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new, old)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
                )
        except Exception:
            pass

    # ---- engine wiring ----------------------------------------------------

    def _start_engine(self) -> None:
        threading.Thread(target=self._build_listener, daemon=True).start()

    def _build_listener(self) -> None:
        with self._listener_lock:
            model = self._config.get("asr_model", DEFAULT_MODEL_DISPLAY)
            device = self._config.get("asr_device", "GPU")
            _log.info("Building engine: model=%s device=%s", model, device)
            self._asr_ready = False
            self._llm_ready = False
            self._bridge.busy.emit(f"Loading {model} on {device}\u2026")
            try:
                import keyboard

                keyboard.clear_all_hotkeys()
            except Exception:
                pass
            try:
                listener = HotkeyListener(
                    hotkey=self._config["hotkey"],
                    model_name=self._config["asr_model"],
                    vad_threshold=self._config["vad_threshold"],
                    log_transcript=self._config["log_transcript"],
                    device=device,
                    min_silence_ms=self._config["min_silence_ms"],
                    max_segment_seconds=self._config["max_segment_seconds"],
                    reformat_hotkey=self._config["reformat_hotkey"],
                    llm_model=self._config["llm_model"],
                    llm_device=self._config["llm_device"],
                    commit_mode=self._config.get("commit_mode", "buffered"),
                    cleanup_level=self._config.get("cleanup_level", "light"),
                    cleanup_provider=self._config.get("cleanup_provider", "local"),
                    groq_cleanup_model=self._config.get("groq_cleanup_model"),
                    cleanup_timeout_ms=self._config.get("cleanup_timeout_ms", 4000),
                    per_app_formatting=self._config.get("per_app_formatting", True),
                    dictionary=self._dictionary,
                    autolearn_enabled=self._config.get("autolearn_enabled", False),
                    ptt_enabled=self._config.get("ptt_enabled", True),
                    ptt_key=self._config.get("ptt_key", "right ctrl"),
                    cancel_key=self._config.get("cancel_key", "esc"),
                    hands_free_double_tap=self._config.get("hands_free_double_tap", False),
                    toggle_enabled=self._config.get("toggle_enabled", False),
                    sound_on_start=self._config.get("sound_on_start", True),
                    paste_last_hotkey=self._config.get("paste_last_hotkey", "ctrl+alt+v"),
                    copy_last_hotkey=self._config.get("copy_last_hotkey", "ctrl+alt+c"),
                    input_device=self._config.get("input_device") or None,
                    on_note=lambda t, w, d: self._bridge.note.emit(t, w, d),
                    on_state=lambda r: self._bridge.state.emit(r),
                    on_llm_state=lambda s: self._bridge.llm_state.emit(s),
                    on_bar=lambda s: self._bridge.bar_state.emit(s),
                    on_diagnostic=lambda h, d: self._bridge.diagnostic.emit(h, d),
                    on_level=lambda lv: self._bridge.levels.emit(lv),
                )
                listener.start()
                self._listener = listener
                _log.info("Engine ready: model=%s device=%s", model, device)
                self._bridge.ready.emit(True)
            except Exception as exc:  # pragma: no cover - runtime/model dependent
                _log.exception("Engine failed to start: model=%s device=%s", model, device)
                self._bridge.error.emit(str(exc))

    def _rebuild_engine(self) -> None:
        threading.Thread(target=self._build_listener, daemon=True).start()

    # ---- slots ------------------------------------------------------------

    @Slot(str, int, float)
    def _on_note(self, text: str, words: int, duration: float) -> None:
        # A whole dictation session was just written as one entry; reflect it.
        self._refresh_stats()
        self._load_notes(mark_fresh=True)

    @Slot(bool)
    def _on_state(self, recording: bool) -> None:
        if recording:
            self._set_dot(theme.COLORS["danger"])
            self._status_text.setText("Listening")
        else:
            self._refresh_engine_status()

    @Slot(list)
    def _on_levels(self, levels: list) -> None:
        if self._pill is not None:
            self._pill.set_levels(levels)

    @Slot(str)
    def _on_bar_state(self, state: str) -> None:
        if self._pill is not None:
            self._pill.set_state(state)
            # Only visible when something is happening: an always-on-top blob
            # during idle is clutter, not feedback.
            self._pill.setVisible(state != "idle")

        if state in ("recording", "locked"):
            self._set_dot(theme.COLORS["danger"])
            self._status_text.setText("Listening" + (" (locked)" if state == "locked" else ""))
        elif state == "transcribing":
            self._set_dot(theme.COLORS["amber"])
            self._status_text.setText("Cleaning up…")
        elif state == "cancelled":
            self._status_text.setText("Discarded")
        elif state == "idle":
            self._refresh_engine_status()

    @Slot(str, str)
    def _on_diagnostic(self, headline: str, detail: str) -> None:
        _log.warning("%s — %s", headline, detail)
        if self._pill is not None:
            self._pill.set_state("error", headline)
            self._pill.setVisible(True)
        self._set_dot(theme.COLORS["danger"])
        self._status_text.setText(headline)
        self._status_text.setToolTip(detail)

    @Slot(bool)
    def _on_ready(self, _ready: bool) -> None:
        self._asr_ready = True
        self._set_engine_controls_enabled(True)
        self._refresh_engine_status()

    @Slot(str)
    def _on_busy(self, message: str) -> None:
        self._set_dot(theme.COLORS["muted"])
        self._status_text.setText(message)
        self._loading_bar.setVisible(True)
        self._set_engine_controls_enabled(False)

    @Slot(str)
    def _on_error(self, message: str) -> None:
        self._set_dot(theme.COLORS["danger"])
        self._status_text.setText("Engine error")
        # "Engine error" alone sends people to the log; the first line of the
        # exception usually names the actual problem (model download, device).
        first_line = (message or "").strip().splitlines()[0] if message else ""
        self._status_text.setToolTip(first_line or "See the log for details.")
        self._loading_bar.setVisible(False)
        self._set_engine_controls_enabled(True)
        _log.error("Engine error reported to UI: %s", message)

    def _refresh_engine_status(self) -> None:
        """Reflect combined ASR + reformatter-LLM readiness in the status chip.

        Keeps the loading indicator visible until the LLM (downloaded/warmed
        in the background on a separate thread) is also ready, so bootup LLM
        loading is never silently hidden behind an already-cleared bar.
        """
        if not self._asr_ready:
            return
        if not self._llm_ready:
            self._set_dot(theme.COLORS["muted"])
            self._status_text.setText("Idle \u00b7 warming reformatter LLM\u2026")
            self._loading_bar.setVisible(True)
        else:
            self._set_dot(theme.COLORS["success"])
            self._status_text.setText("Idle \u00b7 running in background")
            self._loading_bar.setVisible(False)

    def _set_engine_controls_enabled(self, enabled: bool) -> None:
        """Disable model/device switching while the engine is (re)loading."""
        for widget in (getattr(self, "_model_combo", None), getattr(self, "_device_combo", None)):
            if widget is not None:
                widget.setEnabled(enabled)

    @Slot(str)
    def _on_llm_state(self, status: str) -> None:
        labels = {
            "loading": "Loading\u2026",
            "ready": "Ready",
            "reformatting": "Reformatting\u2026",
            "error": "Error",
            "unloaded": "Not loaded",
        }
        colors = {
            "loading": theme.COLORS["muted"],
            "ready": theme.COLORS["success"],
            "reformatting": theme.COLORS["accent"],
            "error": theme.COLORS["danger"],
            "unloaded": "#7a8199",
        }
        if getattr(self, "_llm_status", None) is not None:
            self._llm_status.setText(labels.get(status, status))
            self._llm_status.setStyleSheet(f"color: {colors.get(status, '#7a8199')};")

        if status in ("loading",):
            self._llm_ready = False
            self._refresh_engine_status()
        elif status in ("ready", "error"):
            self._llm_ready = True
            self._refresh_engine_status()

    # ---- config handlers --------------------------------------------------

    def _on_model_changed(self, value: str) -> None:
        self._update_config({"asr_model": value})

    def _on_device_changed(self, value: str) -> None:
        self._update_config({"asr_device": value})

    def _on_log_toggled(self, checked: bool) -> None:
        self._update_config({"log_transcript": bool(checked)})

    def _on_llm_model_changed(self, value: str) -> None:
        self._update_config({"llm_model": value})

    def _on_llm_device_changed(self, value: str) -> None:
        self._update_config({"llm_device": value})

    def _apply_reformat_hotkey(self) -> None:
        text = self._reformat_hotkey_edit.text().strip() or "ctrl+alt+r"
        self._update_config({"reformat_hotkey": text})

    def _on_vad_preview(self, value: int) -> None:
        self._vad_value.setText(f"{value / 100:.2f}")

    def _on_vad_commit(self) -> None:
        self._update_config({"vad_threshold": round(self._vad_slider.value() / 100, 2)})

    def _update_config(self, patch: dict) -> None:
        rebuild = any(k in _PIPELINE_KEYS for k in patch)
        self._config.update(patch)
        save_config(self._config)
        if rebuild:
            self._rebuild_engine()

    # ---- speakers ---------------------------------------------------------

    def _record_speaker(self) -> None:
        name = self._speaker_name.text().strip() or "Speaker"
        self._speaker_btn.setEnabled(False)
        self._speaker_btn.setText("\u25cf  Recording 5s\u2026")

        def worker() -> None:
            try:
                speaker.record_speaker(name, seconds=5.0)
            except Exception as exc:  # pragma: no cover - device dependent
                print(f"[WinWhispr][gui] speaker record failed: {exc}")
            self._bridge.speakers_changed.emit()

        threading.Thread(target=worker, daemon=True).start()

    @Slot()
    def _reload_speakers(self) -> None:
        self._speaker_btn.setEnabled(True)
        self._speaker_btn.setText("\u25cf  Enroll voice sample")
        self._speaker_name.clear()
        while self._speaker_list.count():
            item = self._speaker_list.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for sp in speaker.list_speakers():
            self._speaker_list.addWidget(SpeakerRow(sp["name"], sp["seconds"]))

    # ---- data -------------------------------------------------------------

    def _refresh_stats(self) -> None:
        # Stored timestamps are local time read back as if UTC, so "now" is
        # built the same way and the offset is zero. See get_session_records.
        now_unix = int(datetime.now().replace(tzinfo=timezone.utc).timestamp())
        stats = summary(db_manager.get_session_records(), 0, now_unix)

        self._card_words.set_value(f"{stats.total_words:,}")
        val, unit = _fmt_saved(stats.time_saved_secs / 60.0)
        self._card_saved.set_value(val, unit)
        self._card_wpm.set_value(str(stats.avg_wpm))
        self._card_wpm.set_label(
            f"Words / minute \u00b7 best {stats.best_wpm}" if stats.best_wpm else "Words / minute"
        )
        self._card_streak.set_value(str(stats.day_streak))
        self._card_streak.set_label(
            f"Day streak \u00b7 {stats.words_today:,} words today"
            if stats.words_today
            else "Day streak"
        )

    def _load_notes(self, mark_fresh: bool = False) -> None:
        search = self._search_box.text() if hasattr(self, "_search_box") else ""
        notes = db_manager.get_notes(limit=200, search=search)
        for card in self._note_cards:
            card.setParent(None)
            card.deleteLater()
        self._note_cards.clear()
        self._empty.setVisible(not notes)
        newest_id = notes[0]["id"] if notes else None
        for note in reversed(notes):  # oldest first, so newest ends on top
            self._prepend_note(
                note_id=note["id"],
                text=note["text"],
                meta=self._note_meta(note),
                fresh=(mark_fresh and note["id"] == newest_id),
            )
        self._count_pill.setText(f"{len(notes)} entries")

    @staticmethod
    def _note_meta(note: dict) -> str:
        bits = [
            _time_ago(note["timestamp"]),
            f"{note['word_count']} words",
            f"{note['duration_seconds']}s",
        ]
        if note.get("app"):
            bits.append(str(note["app"]))
        if note.get("cleaned"):
            bits.append("cleaned")
        return "  ·  ".join(bits)

    def _prepend_note(self, note_id: int, text: str, meta: str, fresh: bool) -> None:
        self._empty.setVisible(False)
        card = NoteCard(note_id, text, meta, fresh=fresh)
        card.deleted.connect(self._delete_note)
        # index 0 is the empty state; insert notes right after it (top of the list)
        self._notes_container.insertWidget(1, card)
        self._note_cards.insert(0, card)

    @Slot(int)
    def _delete_note(self, note_id: int) -> None:
        if note_id >= 0:
            db_manager.delete_note(note_id)
        self._load_notes()

    def _reset_data(self) -> None:
        """Wipe usage metrics + activity log after user confirmation."""
        reply = QMessageBox.warning(
            self,
            "Reset all data",
            "This permanently erases all usage metrics and the activity log "
            "(words dictated, time saved, sessions, notes). This cannot be undone.\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if db_manager.reset_all():
            _log.info("User reset all analytics/notes data")
        else:
            _log.error("Failed to reset analytics/notes data")
        self._refresh_stats()
        self._load_notes()

    # ---- responsive layout -------------------------------------------------

    #: Below this window width the sidebar folds itself away, because 280px of
    #: settings plus a readable activity log does not fit.
    NARROW_WIDTH = 860
    #: Below this, four metric cards side by side start truncating their values.
    METRICS_TWO_COL = 1080
    METRICS_ONE_COL = 620

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_breakpoints(self.width())

    def _apply_breakpoints(self, width: int) -> None:
        """Adapt the layout to the current window width."""
        if width < self.METRICS_ONE_COL:
            self._layout_metrics(1)
        elif width < self.METRICS_TWO_COL:
            self._layout_metrics(2)
        else:
            self._layout_metrics(4)

        # Tighter gutters when there is less room to give away.
        margin = 20 if width < self.NARROW_WIDTH else 34
        self._content_layout.setContentsMargins(margin, margin - 6, margin, margin)

        # The search field earns its width only when there is width to spare.
        self._search_box.setVisible(width >= 720)

        # The hotkey hint is a reminder, not a control: first thing to go.
        self._hint_chip.setVisible(width >= 1000)

        cramped = width < self.NARROW_WIDTH
        if cramped != self._auto_collapsed:
            self._auto_collapsed = cramped
            # Never fight a deliberate choice: only auto-collapse a sidebar the
            # user has not already collapsed themselves.
            if cramped and not self._collapsed:
                self._set_sidebar_collapsed(True)
            elif not cramped and self._collapsed and not self._user_collapsed:
                self._set_sidebar_collapsed(False)

    # ---- sidebar collapse -------------------------------------------------

    def _toggle_sidebar(self) -> None:
        self._user_collapsed = not self._collapsed
        self._set_sidebar_collapsed(not self._collapsed)

    def _set_sidebar_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        target = 64 if collapsed else 280
        self._brand_name.setVisible(not collapsed)
        self._brand_sub.setVisible(not collapsed)
        self._nav_label.setVisible(not collapsed)
        self._foot.setVisible(not collapsed)
        self._collapse_btn.setText("\u276f" if collapsed else "\u276e")
        for section in self._sidebar_sections:
            section.set_mini(collapsed)

        # Ease-out, under 300ms: the panel should arrive as fast as the click.
        self._sidebar_anim.stop()
        self._sidebar_anim.setStartValue(self._sidebar.width())
        self._sidebar_anim.setEndValue(target)
        self._sidebar_anim.start()

    # ---- helpers ----------------------------------------------------------

    def _hotkey_keys(self) -> list[str]:
        return [
            k.strip().capitalize()
            for k in self._config.get("hotkey", "ctrl+shift+space").split("+")
            if k.strip()
        ]

    def _set_dot(self, color: str) -> None:
        self._status_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")

    # ---- tray / lifecycle -------------------------------------------------

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_from_tray()

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self) -> None:
        self._tray.hide()
        QApplication.quit()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Keep running in the background instead of exiting.
        event.ignore()
        self.hide()
        self._tray.showMessage(
            "WinWhispr",
            "Still running in the background. Use your hotkey any time.",
            QSystemTrayIcon.Information,
            2500,
        )


def run() -> None:
    """Launch the native desktop application."""
    config = load_config()
    db_manager.init_db()

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("WinWhispr")
    if os.path.isfile(_ICON_PNG):
        app.setWindowIcon(QIcon(_ICON_PNG))
    app.setStyleSheet(theme.stylesheet())
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow(config)
    window.show()
    window.apply_dark_titlebar()
    sys.exit(app.exec())
