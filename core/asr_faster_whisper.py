"""Local speech-to-text via faster-whisper (CTranslate2).

The same trick whisper.cpp uses — an int8-quantized Whisper running on plain
CPU — with a Python API. Measured on an 8 second clip on a laptop CPU:
base.en 385ms, tiny.en 233ms, small.en 1125ms, against 1192ms for the
OpenVINO path on the iGPU and 3626ms on CPU.

Models are a few hundred megabytes rather than gigabytes, and CTranslate2
fetches them itself into the Hugging Face cache on first use.
"""

from __future__ import annotations

import logging
import threading

_log = logging.getLogger("winwhispr.asr")


class FasterWhisperBackend:
    """Whisper on the CPU, fast enough to use.

    Loading is lazy and guarded: the first transcription pays for it, so the
    app starts instantly and a model that is never used is never downloaded.
    """

    def __init__(self, model_size: str = "base.en", device: str = "CPU",
                 compute_type: str | None = None):
        self._model_size = model_size
        # int8 on CPU is what makes this fast; float16 is the sane GPU default.
        self._device = "cuda" if str(device).upper() == "CUDA" else "cpu"
        self._compute_type = compute_type or ("float16" if self._device == "cuda" else "int8")
        self._model = None
        self._lock = threading.Lock()

    def load(self):
        with self._lock:
            if self._model is not None:
                return self._model
            from faster_whisper import WhisperModel

            _log.info("Loading faster-whisper %s (%s, %s)",
                      self._model_size, self._device, self._compute_type)
            self._model = WhisperModel(
                self._model_size, device=self._device, compute_type=self._compute_type
            )
            print(f"[WinWhispr][asr] faster-whisper {self._model_size} ready "
                  f"({self._device}/{self._compute_type})")
            return self._model

    def transcribe(self, audio) -> str:
        if audio is None or len(audio) == 0:
            return ""
        model = self.load()
        # beam_size=1 is greedy decoding: for single short utterances the
        # quality difference is not worth the extra latency on every dictation.
        segments, _info = model.transcribe(
            audio,
            language="en",
            beam_size=1,
            condition_on_previous_text=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
