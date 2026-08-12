"""The original OpenVINO speech-to-text paths, behind the engine interface.

Kept because they are the Intel AI PC story — an iGPU or NPU runs these where
CTranslate2 would fall back to CPU. Measured slower than faster-whisper on a
plain CPU, so ``auto`` does not select them; a user picks them deliberately.
"""

from __future__ import annotations

from core.asr.engine import EngineCaps


class OpenVinoEngine:
    """Wraps the existing OVASRBackend / WhisperOVBackend classes."""

    def __init__(self, model_display_name: str, device: str = "GPU"):
        self._model_display_name = model_display_name
        self._device = "GPU" if str(device).lower() in ("auto", "gpu") else device
        self._backend = None
        self.caps = EngineCaps(
            supports_pipelining=True,
            label=f"{model_display_name} (OpenVINO/{self._device})",
        )

    def warmup(self) -> None:
        self._ensure_backend()

    def _ensure_backend(self):
        if self._backend is not None:
            return self._backend
        from core.model_manager import ensure_asr_model
        from core.model_registry import resolve_backend
        from core.processor import OVASRBackend, WhisperOVBackend

        model_dir = ensure_asr_model(self._model_display_name)
        if resolve_backend(self._model_display_name) == "whisper_genai":
            self._backend = WhisperOVBackend(model_dir, device=self._device)
        else:
            self._backend = OVASRBackend(model_dir, device=self._device)
        return self._backend

    def transcribe(self, audio) -> str:
        return self._ensure_backend().transcribe(audio)
