"""WinWhispr entry point.

Default: launch the native PySide6 desktop app (a standalone Windows window)
which also runs the background dictation engine (global hotkey + ASR).

    python main.py            # native desktop app (default)
    python main.py headless   # engine only, no window (global hotkey)
    python main.py setup      # download + optimize models, then exit
    python main.py models     # what is on disk, and how to reclaim it
"""

import sys
import threading
import traceback

# Configured before any other core import so print()/exceptions during those
# imports are captured too (critical for the --noconsole packaged build,
# where sys.stdout/sys.stderr are None). Logs land in ~/.cache/winwhispr/logs/.
from core.logging_setup import setup_logging

setup_logging()

from core.config_store import load_config
from core.hotkey_listener import HotkeyListener
from database import db_manager


def main():
    """Launch the native desktop application."""
    from desktop import run

    run()


def headless():
    """Run the engine with no window: global hotkey + background dictation."""
    config = load_config()
    db_manager.init_db()

    listener = HotkeyListener(
        hotkey=config["hotkey"],
        model_name=config["asr_model"],
        vad_threshold=config["vad_threshold"],
        log_transcript=config["log_transcript"],
        min_silence_ms=config["min_silence_ms"],
        max_segment_seconds=config["max_segment_seconds"],
        reformat_hotkey=config["reformat_hotkey"],
        llm_model=config["llm_model"],
        llm_device=config["llm_device"],
    )
    listener.start()

    print(
        f"[WinWhispr] Running headless. Hotkey: {config['hotkey']}. "
        f"Reformat: {config['reformat_hotkey']}. Press Ctrl+C to quit."
    )
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("[WinWhispr] Shutting down.")


def setup():
    """Download and optimize all runtime models, then exit.

    Meant to run once on the target machine (e.g. right after install). It
    downloads the ASR, VAD and LLM assets into ``~/.cache/winwhispr`` and warms
    the OpenVINO compile cache for the configured devices -- the device-specific
    "optimization" that cannot be pre-baked into the installer. Devices fall
    back to CPU automatically when a GPU is unavailable.
    """
    from core.processor import TextPipeline
    from core.reformatter import Reformatter

    config = load_config()
    db_manager.init_db()

    print("[WinWhispr][setup] Downloading + optimizing ASR/VAD models...")
    try:
        TextPipeline(
            model_display_name=config["asr_model"],
            vad_threshold=config["vad_threshold"],
            log_transcript=False,
            device=config["asr_device"],
            min_silence_ms=config["min_silence_ms"],
            max_segment_seconds=config["max_segment_seconds"],
        )
        print("[WinWhispr][setup] ASR/VAD ready.")
    except Exception as exc:  # pragma: no cover - runtime/model dependent
        print(f"[WinWhispr][setup] ASR/VAD preparation failed: {exc}")
        print(traceback.format_exc())

    print("[WinWhispr][setup] Downloading + optimizing reformatter LLM...")
    try:
        Reformatter(
            model_display_name=config["llm_model"],
            device=config["llm_device"],
        ).load()
        print("[WinWhispr][setup] LLM ready.")
    except Exception as exc:  # pragma: no cover - runtime/model dependent
        print(f"[WinWhispr][setup] LLM preparation failed: {exc}")
        print(traceback.format_exc())

    print("[WinWhispr][setup] Done.")


def models():
    """List downloaded models and their disk usage, or delete one.

        python main.py models                  # what is on disk
        python main.py models --remove NAME    # delete one by name
        python main.py models --purge-cache    # drop the OpenVINO compile cache
    """
    from core import model_store

    config = load_config()
    active = (str(config.get("asr_model", "")), str(config.get("llm_model", "")))

    args = sys.argv[2:]
    if "--remove" in args:
        wanted = args[args.index("--remove") + 1].lower() if len(args) > args.index("--remove") + 1 else ""
        for model in model_store.installed(active):
            if wanted and wanted in model.name.lower():
                if model.in_use:
                    print(f"[WinWhispr] {model.name} is the configured model; "
                          f"pick another one in the sidebar first.")
                    return
                ok = model_store.remove(model)
                print(f"[WinWhispr] {'Removed' if ok else 'Could not remove'} "
                      f"{model.name} ({model.size_mb:.0f} MB)")
                return
        print(f"[WinWhispr] No downloaded model matching {wanted!r}.")
        return

    if "--purge-cache" in args:
        cache = model_store.compile_cache()
        ok = model_store.remove(cache)
        print(f"[WinWhispr] {'Freed' if ok else 'Could not free'} "
              f"{cache.size_mb:.0f} MB of compile cache "
              f"(it rebuilds automatically on the next model load).")
        return

    print(model_store.report(active))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    print(f"[WinWhispr] Starting mode={mode or 'gui'}")
    if mode == "headless":
        headless()
    elif mode == "setup":
        setup()
    elif mode == "models":
        models()
    else:
        main()
