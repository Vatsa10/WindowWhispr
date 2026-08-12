"""Shared configuration load/save for WinWhispr.

A single source of truth for reading and writing ``config.json`` so the engine
entry point and the desktop UI stay in sync.
"""

from __future__ import annotations

import json
import os

from core import paths
from core.model_registry import DEFAULT_LLM_DISPLAY, DEFAULT_MODEL_DISPLAY

CONFIG_PATH = str(paths.config_path())

# Bump whenever a key needs *rewriting* (rename, value reshape). Purely additive
# keys need no bump: the ``{**DEFAULT_CONFIG, **loaded}`` merge already backfills
# them for existing users.
CONFIG_VERSION = 1

DEFAULT_CONFIG = {
    "config_version": CONFIG_VERSION,
    "hotkey": "ctrl+shift+space",
    "vad_threshold": 0.35,
    "asr_model": DEFAULT_MODEL_DISPLAY,
    "asr_device": "GPU",
    "log_transcript": False,
    "user_name": "there",
    "min_silence_ms": 300,
    "max_segment_seconds": 15,
    "reformat_hotkey": "ctrl+alt+r",
    "llm_model": DEFAULT_LLM_DISPLAY,
    "llm_device": "CPU",
    # "buffered" pastes the whole utterance once (required by the cleanup pass);
    # "stream" pastes each chunk live, as WinWhispr did before cleanup existed.
    "commit_mode": "buffered",
    # Cleanup pass over the finished transcript. "light" is deliberately the
    # default: an aggressive default is the top source of "it changed what I
    # said" complaints. "none" pastes the raw transcript with no model call.
    "cleanup_level": "light",
    # Deterministic rules always run: fillers, stutters, spoken punctuation and
    # capitalization, in microseconds and offline. This setting is only about
    # the *optional* language model on top, for spoken self-corrections and
    # per-app tone.
    #   "none"  - rules only. Offline, instant. The default.
    #   "local" - the on-device LLM. Measured ~3s and often wrong at 350M.
    #   "groq"  - hosted, ~0.3s, but the transcript leaves the machine.
    # Any API key lives in Windows Credential Manager, never here.
    "cleanup_provider": "none",
    "groq_cleanup_model": "llama-3.3-70b-versatile",
    "cleanup_timeout_ms": 4000,
    "per_app_formatting": True,
    # Dictation controls. The default is deliberately just two keys: hold to
    # talk, Esc to discard. The other two modes are real features but they make
    # the app harder to explain, so they are opt-in.
    "ptt_enabled": True,
    "ptt_key": "right ctrl",
    "cancel_key": "esc",
    # Tap the talk key twice to keep recording without holding it.
    "hands_free_double_tap": False,
    # The older press-to-start / press-to-stop chord (see "hotkey" above).
    "toggle_enabled": False,
    # Floating status pill near the bottom of the screen.
    "pill_enabled": True,
    "sound_on_start": True,
    # Reuse the last transcript without dictating it again.
    "paste_last_hotkey": "ctrl+alt+v",
    "copy_last_hotkey": "ctrl+alt+c",
    # Microphone name, or "" for whatever Windows calls the default.
    "input_device": "",
    # Off by default: learning a name means reading back the field you pasted
    # into, which can be a password box. Opt in explicitly.
    "autolearn_enabled": False,
}

# version -> function upgrading a config dict from that version to the next one.
# Keyed by the version being *upgraded from*, applied in ascending order.
MIGRATIONS: dict = {}


def migrate(config: dict) -> dict:
    """Run the migration chain over ``config`` until it reaches CONFIG_VERSION.

    Idempotent: an already-current config passes through untouched.
    """
    version = int(config.get("config_version", 0) or 0)
    while version < CONFIG_VERSION:
        step = MIGRATIONS.get(version)
        if step is not None:
            config = step(config)
        version += 1
        config["config_version"] = version
    return config


def load_config() -> dict:
    """Read config.json, creating it with defaults if missing or invalid."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                return migrate({**DEFAULT_CONFIG, **json.load(fh)})
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[WinWhispr] Bad config, using defaults: {exc}")
    save_config(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    """Persist the given config dict to config.json.

    Written to a sibling temp file and moved into place, so a crash mid-write
    can never leave a truncated config behind.
    """
    tmp = f"{CONFIG_PATH}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)
        os.replace(tmp, CONFIG_PATH)
    except OSError as exc:
        print(f"[WinWhispr] Could not write config: {exc}")
        try:
            os.remove(tmp)
        except OSError:
            pass
