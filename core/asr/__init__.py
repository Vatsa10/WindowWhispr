"""Speech-to-text: choosing an engine, and running it while the user speaks.

    probe() -> Hardware -> tiering.choose() -> ModelChoice -> engine
                                                                |
                                    TranscriptionSession(engine)

``build_engine`` is the only entry point the rest of the app needs.
"""

from __future__ import annotations

import logging

from core.asr.engine import AsrEngine, EngineCaps
from core.asr.pipeline import TranscriptionSession
from core.asr.tiering import Hardware, ModelChoice, choose

_log = logging.getLogger("winwhispr.asr")

#: Config value meaning "work out what this machine should run".
AUTO = "auto"

__all__ = [
    "AUTO",
    "AsrEngine",
    "EngineCaps",
    "Hardware",
    "ModelChoice",
    "TranscriptionSession",
    "build_engine",
    "choose",
    "describe_auto_choice",
]


def build_engine(model_display_name: str, device: str = "auto", log=print):
    """Construct the engine for a configured model name.

    ``auto`` inspects the machine. Anything else is taken literally, so a user
    who picked a specific model keeps it even if the hardware suggests another.
    """
    from core.model_registry import resolve_backend, resolve_model_id

    if model_display_name.strip().lower() == AUTO:
        return _build_auto(log=log)

    backend = resolve_backend(model_display_name)
    model_id = resolve_model_id(model_display_name)

    if backend == "faster_whisper":
        from core.asr.faster_whisper_engine import FasterWhisperEngine
        from core.asr.probe import probe

        hw = probe()
        forced = ModelChoice(
            model_id,
            "cuda" if (device.lower() == "cuda" and hw.cuda_devices) else "cpu",
            "float16" if device.lower() == "cuda" and hw.cuda_devices else "int8",
            "chosen in settings",
        )
        return FasterWhisperEngine(forced, cpu_threads=hw.cpu_threads)

    if backend == "groq_whisper":
        from core.asr.remote_engine import GroqEngine

        return GroqEngine(model_id)

    from core.asr.openvino_engine import OpenVinoEngine

    return OpenVinoEngine(model_display_name, device=device)


def _build_auto(log=print):
    from core.asr.faster_whisper_engine import FasterWhisperEngine
    from core.asr.probe import probe

    hw = probe()
    choice = choose(hw)
    log(f"[WinWhispr][asr] {hw.cpu_threads} threads, "
        f"{hw.cuda_devices} CUDA device(s) (compute {hw.compute_capability:g}), "
        f"{hw.vram_mb}MB VRAM -> {choice.label}: {choice.reason}")
    # Automatic choices are checked against the machine at warmup and downgraded
    # if the guess was optimistic.
    return FasterWhisperEngine(choice, cpu_threads=hw.cpu_threads,
                               calibrate_on_warmup=True)


def describe_auto_choice() -> str:
    """What ``auto`` would pick here, for the settings UI."""
    from core.asr.probe import probe

    return choose(probe()).label
