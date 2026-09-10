"""WinWhispr, as a tray icon and nothing else.

Every window this app has is a web page now: the pill and the settings screen
both live in the WebView2 child process, which is the only place a speech
recognizer will run and the only layout engine here that reflows without being
told how. What is left in Qt is the part a web page cannot be -- a tray icon
that outlives every window, a global hotkey, and the engine.

    [Qt, this process]                [WebView2, child process]
      tray icon                          the pill    (always)
      global hotkey        --SSE-->      settings    (on demand)
      HTTP server + engine <--HTTP--

Closing the settings window leaves the app running, because the pill and the
hotkey are the app; the window is only how you talk to it.
"""

from __future__ import annotations

import logging
import os
import sys
import threading

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from core import paths
from core.config_store import load_config
from core.web.app_api import AppApi, needs_restart
from core.web.session import BrowserDictation
from database import db_manager

_log = logging.getLogger("winwhispr.tray")

_ICON_PNG = str(paths.resource_dir() / "assets" / "winwhispr.png")

class TrayApp:
    """The whole application, minus its windows."""

    def __init__(self, config: dict):
        self._config = config
        self._browser: BrowserDictation | None = None
        self._listener = None
        self._lock = threading.Lock()

        icon = QIcon(_ICON_PNG) if os.path.isfile(_ICON_PNG) else QIcon()
        self._tray = QSystemTrayIcon(icon)
        self._tray.setToolTip("WinWhispr")
        self._tray.setContextMenu(self._menu())
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

        self.start_engine()

    # -- menu -------------------------------------------------------------

    def _menu(self) -> QMenu:
        """The right-click menu.

        Every part of it is kept on ``self``. A QMenu built as a local and
        handed to setContextMenu is owned by nothing on the Python side, so it
        is garbage collected the moment this returns and right-clicking the
        tray icon does nothing at all.
        """
        menu = QMenu()

        self._open_action = QAction("Open WinWhispr", menu)
        self._open_action.triggered.connect(self.open_window)
        menu.addAction(self._open_action)

        self._restart_action = QAction("Restart dictation", menu)
        self._restart_action.triggered.connect(self.start_engine)
        menu.addAction(self._restart_action)

        menu.addSeparator()

        self._quit_action = QAction("Quit WinWhispr", menu)
        self._quit_action.triggered.connect(self.quit)
        menu.addAction(self._quit_action)

        self._tray_menu = menu
        return menu

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.open_window()

    def open_window(self) -> None:
        """Ask the child process for the settings window."""
        if self._browser is None:
            return self._notify("Dictation is not running", "Restart WinWhispr.")
        if not self._browser.show_app():
            self._notify("No window to open",
                         "The dictation window is not running.")

    def _notify(self, title: str, detail: str) -> None:
        self._tray.showMessage(title, detail, QSystemTrayIcon.Information, 3000)

    # -- engine -----------------------------------------------------------

    def start_engine(self) -> None:
        threading.Thread(target=self._build, daemon=True, name="winwhispr-engine").start()

    def _build(self) -> None:
        with self._lock:
            self._stop_engine()
            if self._config.get("speech_engine", "browser") == "local":
                self._build_local()
            else:
                self._build_browser()

    def _build_browser(self) -> None:
        browser = BrowserDictation(
            on_transcript=self._on_transcript,
            key=self._config.get("ptt_key", "right ctrl"),
        )
        browser.corner = self._config.get("pill_corner", "bottom-right")
        browser.app_api = AppApi(on_config=self._on_config_changed)
        try:
            browser.start()
        except Exception as exc:
            _log.exception("browser dictation failed to start")
            return self._notify("Dictation could not start", str(exc))
        self._browser = browser
        browser.watch(self._on_window_closed)
        _log.info("browser dictation ready at %s", browser.url)

    def _build_local(self) -> None:
        from core.hotkey_listener import HotkeyListener

        try:
            listener = HotkeyListener(
                hotkey=self._config["hotkey"],
                model_name=self._config["asr_model"],
                vad_threshold=self._config["vad_threshold"],
                log_transcript=self._config["log_transcript"],
                device=self._config.get("asr_device", "GPU"),
                min_silence_ms=self._config["min_silence_ms"],
                max_segment_seconds=self._config["max_segment_seconds"],
                reformat_hotkey=self._config["reformat_hotkey"],
                llm_model=self._config["llm_model"],
                llm_device=self._config["llm_device"],
                commit_mode=self._config.get("commit_mode", "buffered"),
                cleanup_level=self._config.get("cleanup_level", "light"),
                cleanup_provider=self._config.get("cleanup_provider", "local"),
                cleanup_timeout_ms=self._config.get("cleanup_timeout_ms", 4000),
                per_app_formatting=self._config.get("per_app_formatting", True),
                ptt_enabled=self._config.get("ptt_enabled", True),
                ptt_key=self._config.get("ptt_key", "right ctrl"),
                cancel_key=self._config.get("cancel_key", "esc"),
                hands_free_double_tap=self._config.get("hands_free_double_tap", False),
                toggle_enabled=self._config.get("toggle_enabled", False),
                sound_on_start=self._config.get("sound_on_start", True),
                keep_mic_open=self._config.get("keep_mic_open", False),
                input_device=self._config.get("input_device") or None,
            )
            listener.start()
        except Exception as exc:
            _log.exception("local engine failed to start")
            return self._notify("Dictation could not start", str(exc))
        self._listener = listener
        # The settings window still has to exist with the local engine, so the
        # server and the pill process run either way -- the pill simply never
        # gets told to listen.
        self._build_browser_shell()

    def _build_browser_shell(self) -> None:
        """The server and window host, without hooking the key.

        With the local engine the hotkey belongs to the listener; a second hook
        on the same key would dictate twice.
        """
        shell = BrowserDictation(key="")
        shell.app_api = AppApi(on_config=self._on_config_changed)
        try:
            shell.start()
        except Exception:
            _log.warning("could not start the settings server", exc_info=True)
            return
        self._browser = shell

    def _stop_engine(self) -> None:
        browser, self._browser = self._browser, None
        if browser is not None:
            browser.stop()
        self._listener = None
        try:
            import keyboard

            keyboard.clear_all_hotkeys()
        except Exception:
            pass

    # -- callbacks --------------------------------------------------------

    def _on_transcript(self, text: str, words: int, seconds: float) -> None:
        try:
            db_manager.log_entry(words, seconds, text=text)
        except Exception:
            _log.warning("could not log a dictation", exc_info=True)

    def _on_config_changed(self, changes: dict) -> None:
        self._config.update(changes)
        if needs_restart(changes):
            _log.info("restarting the engine for %s", sorted(changes))
            self.start_engine()

    def _on_window_closed(self) -> None:
        """The user closed the pill. That is how this app is quit."""
        _log.info("the dictation window was closed; quitting")
        QApplication.quit()

    # -- teardown ---------------------------------------------------------

    def quit(self) -> None:
        self._stop_engine()
        self._tray.hide()
        QApplication.quit()


def run() -> None:
    """Launch WinWhispr: a tray icon, a hotkey, and web windows."""
    config = load_config()
    db_manager.init_db()

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("WinWhispr")
    if os.path.isfile(_ICON_PNG):
        app.setWindowIcon(QIcon(_ICON_PNG))
    # There is no Qt window to close, so this must never end the process.
    app.setQuitOnLastWindowClosed(False)

    tray = TrayApp(config)
    app.aboutToQuit.connect(tray._stop_engine)
    sys.exit(app.exec())
