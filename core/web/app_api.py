"""What the app window is allowed to read and change.

The desktop window is a web page now, so everything it used to reach by
calling Python directly it asks for over HTTP instead. This module is that
surface, and it is deliberately one file: a settings screen that can quietly
grow new powers is how a local server turns into a liability.

Nothing here touches Qt, a window, or a model. It is dictionaries in and
dictionaries out, so the whole data layer is testable without a screen.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

_log = logging.getLogger("winwhispr.web")

#: Settings the page may write. Anything else is ignored rather than rejected,
#: so an older page against a newer app degrades instead of failing.
WRITABLE = frozenset({
    "speech_engine", "speech_language", "asr_model", "asr_device",
    "cleanup_level", "cleanup_provider", "cleanup_timeout_ms",
    "per_app_formatting", "commit_mode", "log_transcript",
    "ptt_key", "cancel_key", "ptt_enabled", "hands_free_double_tap",
    "toggle_enabled", "hotkey", "reformat_hotkey", "paste_last_hotkey",
    "copy_last_hotkey", "sound_on_start", "keep_mic_open",
    "vad_threshold", "min_silence_ms", "max_segment_seconds",
    "input_device", "llm_model", "llm_device", "pill_enabled",
    "autolearn_enabled", "startup_mode", "history_retention_days",
})

#: Changing one of these means the engine has to be rebuilt.
RESTARTS_ENGINE = frozenset({
    "speech_engine", "asr_model", "asr_device", "ptt_key", "cancel_key",
    "ptt_enabled", "hotkey", "vad_threshold", "min_silence_ms",
    "max_segment_seconds", "input_device", "llm_model", "llm_device",
    "commit_mode", "cleanup_level", "cleanup_provider", "cleanup_timeout_ms",
    "toggle_enabled", "hands_free_double_tap", "keep_mic_open",
})


def writable_changes(payload: dict) -> dict:
    """The subset of a request the page is actually allowed to write."""
    return {key: value for key, value in (payload or {}).items() if key in WRITABLE}


def needs_restart(changes: dict) -> bool:
    return any(key in RESTARTS_ENGINE for key in changes)


def _tz_offset_minutes() -> int:
    offset = datetime.now().astimezone().utcoffset()
    return int(offset.total_seconds() // 60) if offset else 0


class AppApi:
    """The app window's whole vocabulary.

    ``on_config`` is called with the accepted changes, so the owner can rebuild
    the engine or repaint; it is not called for a request that changed nothing.
    """

    def __init__(self, on_config=None):
        self._on_config = on_config

    # -- settings ---------------------------------------------------------

    def config(self) -> dict:
        from core.config_store import load_config

        return {"config": load_config()}

    def save_config(self, payload: dict) -> dict:
        from core.config_store import load_config, save_config

        changes = writable_changes(payload)
        if not changes:
            return {"saved": False, "restart": False}
        merged = {**load_config(), **changes}
        save_config(merged)
        if self._on_config is not None:
            self._on_config(changes)
        return {"saved": True, "restart": needs_restart(changes), "config": merged}

    def choices(self) -> dict:
        """Everything the dropdowns need, gathered in one round trip."""
        from core.model_registry import list_model_names
        from core.web.languages import LANGUAGES

        try:
            from core.processor import available_devices

            devices = list(available_devices())
        except Exception:  # device enumeration fails on some machines
            _log.warning("could not enumerate devices", exc_info=True)
            devices = ["CPU"]
        return {
            "languages": [{"tag": tag, "name": name} for tag, name in LANGUAGES],
            "models": list(list_model_names()),
            "devices": devices,
        }

    # -- what happened ----------------------------------------------------

    def stats(self) -> dict:
        from core import stats as stats_module
        from database import db_manager

        try:
            records = db_manager.get_session_records()
            summary = stats_module.summary(records, _tz_offset_minutes(),
                                           int(time.time()))
        except Exception:
            _log.warning("could not summarize stats", exc_info=True)
            return {"stats": {}}
        return {"stats": {
            "total_words": summary.total_words,
            "total_sessions": summary.total_sessions,
            "words_today": summary.words_today,
            "wpm_today": summary.wpm_today,
            "avg_wpm": summary.avg_wpm,
            "best_wpm": summary.best_wpm,
            "day_streak": summary.day_streak,
            "time_saved_secs": int(summary.time_saved_secs),
            "last7_words": list(summary.last7_words),
        }}

    def notes(self, payload: dict) -> dict:
        from database import db_manager

        search = (payload or {}).get("search") or None
        limit = int((payload or {}).get("limit") or 200)
        rows = db_manager.get_notes(limit=limit, search=search)
        return {"notes": [_note(row) for row in rows]}

    def reset(self) -> dict:
        from database import db_manager

        db_manager.reset_all()
        return {"reset": True}

    # -- vocabulary -------------------------------------------------------

    def dictionary(self) -> dict:
        from core import paths
        from core.dictionary import DictionaryStore

        store = DictionaryStore(paths.dictionary_path()).load()
        return {"entries": [
            {"correct": entry.correct, "mishears": list(entry.mishears),
             "source": entry.source}
            for entry in store.entries()
        ]}

    def dictionary_add(self, payload: dict) -> dict:
        from core import paths
        from core.dictionary import DictionaryStore

        correct = (payload.get("correct") or "").strip()
        if not correct:
            return {"error": "a spelling is required"}
        mishears = [m.strip() for m in (payload.get("mishears") or []) if m.strip()]
        store = DictionaryStore(paths.dictionary_path()).load()
        store.add(correct, mishears, source="manual")
        store.save()
        return self.dictionary()

    def dictionary_remove(self, payload: dict) -> dict:
        from core import paths
        from core.dictionary import DictionaryStore

        store = DictionaryStore(paths.dictionary_path()).load()
        store.remove((payload.get("correct") or "").strip())
        store.save()
        return self.dictionary()

    # -- disk -------------------------------------------------------------

    def models(self) -> dict:
        from core import model_store
        from core.config_store import load_config

        config = load_config()
        active = (str(config.get("asr_model", "")), str(config.get("llm_model", "")))
        return {"models": [
            {"name": model.name, "size_mb": round(model.size_mb, 1),
             "in_use": model.in_use}
            for model in model_store.installed(active)
        ]}

    def model_remove(self, payload: dict) -> dict:
        from core import model_store
        from core.config_store import load_config

        wanted = (payload.get("name") or "").strip().lower()
        config = load_config()
        active = (str(config.get("asr_model", "")), str(config.get("llm_model", "")))
        for model in model_store.installed(active):
            if model.name.lower() == wanted:
                if model.in_use:
                    return {"error": "that is the model in use; pick another first"}
                model_store.remove(model)
                return self.models()
        return {"error": "no downloaded model by that name"}


def _note(row) -> dict:
    """One activity-log row, as the page wants it.

    Only the fields the log actually shows: the raw transcript and the cleanup
    flag stay on the server until there is a screen that uses them.
    """
    return {
        "id": row.get("id", 0),
        "text": row.get("text", "") or "",
        "timestamp": row.get("timestamp", "") or "",
        "app": row.get("app", "") or "",
        "words": row.get("word_count", 0) or 0,
        "seconds": round(float(row.get("duration_seconds") or 0.0), 1),
    }
