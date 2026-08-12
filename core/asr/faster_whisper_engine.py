"""Whisper on this machine, via CTranslate2.

The same int8/float16 quantized inference whisper.cpp performs, reached through
faster-whisper. Model weights are fetched and cached by the library itself, so
there is no downloader to maintain here.
"""

from __future__ import annotations

import logging
import threading

from core.asr import cuda_runtime
from core.asr.engine import EngineCaps
from core.asr.tiering import ModelChoice, calibrate, cpu_fallback

_log = logging.getLogger("winwhispr.asr")


class FasterWhisperEngine:
    """Local speech-to-text. Loads on first use, never on the hook thread."""

    def __init__(self, choice: ModelChoice, cpu_threads: int = 0,
                 calibrate_on_warmup: bool = False):
        self._choice = choice
        # Only for automatically chosen models. A deliberate choice by the user
        # is theirs to keep, however slow it turns out to be.
        self._calibrate = calibrate_on_warmup
        # 0 lets CTranslate2 choose. Capped because past a point extra threads
        # cost more in coordination than they return, and dictation shares the
        # machine with whatever the user is actually doing.
        self._cpu_threads = min(cpu_threads, 8) if cpu_threads else 0
        self._model = None
        self._lock = threading.Lock()
        #: Set once a GPU failure has pushed this engine onto the CPU, so the
        #: fallback is attempted exactly once rather than on every utterance.
        self._degraded = False
        #: What one utterance cost at warmup, in milliseconds. 0 until measured.
        self.measured_ms = 0.0
        self.caps = EngineCaps(supports_pipelining=True, label=choice.label)

    @property
    def choice(self) -> ModelChoice:
        return self._choice

    def warmup(self) -> None:
        """Load the weights *and* run one inference. Safe from any thread.

        Loading alone is not enough: the first real inference is where CUDA
        builds its kernels and the CPU path allocates its scratch buffers, and
        that cost is several seconds. Paying it here, at startup, keeps it out
        of the user's first dictation.
        """
        import time

        import numpy as np

        self._ensure_model()
        probe_seconds = 2.0
        clip = np.zeros(int(16000 * probe_seconds), dtype=np.float32)
        try:
            self._transcribe(clip)          # first call builds kernels
            started = time.monotonic()
            self._transcribe(clip)          # second is representative
            self.measured_ms = (time.monotonic() - started) * 1000
        except Exception as exc:  # pragma: no cover - hardware dependent
            _log.debug("warmup inference failed: %s", exc)
            return

        if self._calibrate:
            self._apply_calibration(probe_seconds)

    def _apply_calibration(self, probe_seconds: float) -> None:
        """Judge the machine on what it did, not on what its spec sheet says.

        Core counts and VRAM are a guess. This is the correction: a throttled
        GPU, a hot laptop, or a CPU the heuristics did not anticipate all show
        up here and nowhere else.
        """
        per_second = self.measured_ms / probe_seconds
        better = calibrate(self._choice, per_second)
        if better == self._choice:
            _log.info("%s measured %.0fms — keeping it", self._choice.label,
                      self.measured_ms)
            return
        print(f"[WinWhispr][asr] {self._choice.label} measured "
              f"{self.measured_ms:.0f}ms per utterance here — switching to "
              f"{better.model}")
        with self._lock:
            self._choice = better
            self.caps = EngineCaps(supports_pipelining=True, label=better.label)
            self._model = None
        self._ensure_model()

    def _ensure_model(self):
        with self._lock:
            if self._model is not None:
                return self._model
            if self._choice.device == "cuda":
                # Must happen before faster_whisper (and so CTranslate2) is
                # imported, or the CUDA DLLs will not be findable.
                cuda_runtime.ensure()
            from faster_whisper import WhisperModel

            from core import paths

            _log.info("loading %s", self._choice.label)
            # Keep the weights under WinWhispr's own models directory. The
            # library would otherwise put them in the shared Hugging Face
            # cache, where they are indistinguishable from every other
            # project's downloads and nobody can safely reclaim the space.
            download_root = str(paths.whisper_models_dir())
            try:
                self._model = WhisperModel(
                    self._choice.model,
                    device=self._choice.device,
                    compute_type=self._choice.compute_type,
                    cpu_threads=self._cpu_threads,
                    download_root=download_root,
                )
            except Exception as exc:
                if self._choice.device != "cuda":
                    raise
                # A CUDA device can be present while the libraries it needs
                # (cuDNN, cuBLAS) are not. Reporting "no speech model" here
                # would be a lie: the machine is fine, the GPU path is not.
                _log.warning("CUDA load failed (%s); falling back to CPU", exc)
                print(f"[WinWhispr][asr] GPU unavailable ({type(exc).__name__}); "
                      f"using CPU instead")
                self._choice = cpu_fallback(self._choice, self._cpu_threads or 8)
                self.caps = EngineCaps(supports_pipelining=True, label=self._choice.label)
                self._model = WhisperModel(
                    self._choice.model,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=self._cpu_threads,
                    download_root=download_root,
                )
            print(f"[WinWhispr][asr] {self._choice.label} ready — {self._choice.reason}")
            return self._model

    def transcribe(self, audio) -> str:
        if audio is None or len(audio) == 0:
            return ""
        try:
            return self._transcribe(audio)
        except Exception as exc:
            # A CUDA build can load a model and only then discover that cuBLAS
            # or cuDNN is missing — the failure surfaces on the first encode,
            # not at construction. Degrade to CPU and answer anyway; the user
            # wanted their words, not an explanation of their driver install.
            if self._choice.device != "cuda" or self._degraded:
                raise
            _log.warning("CUDA inference failed (%s); switching to CPU", exc)
            print(f"[WinWhispr][asr] GPU inference unavailable ({exc}); "
                  f"switching to CPU for the rest of this session")
            self._degrade_to_cpu()
            return self._transcribe(audio)

    def _degrade_to_cpu(self) -> None:
        """Rebuild this engine on the CPU after the GPU proved unusable."""
        with self._lock:
            self._degraded = True
            self._choice = cpu_fallback(self._choice, self._cpu_threads or 8)
            self.caps = EngineCaps(supports_pipelining=True, label=self._choice.label)
            self._model = None
        self._ensure_model()

    def _transcribe(self, audio) -> str:
        model = self._ensure_model()
        # Greedy decoding, and no carry-over between segments: this app sends
        # short independent utterances, and previous-text conditioning is what
        # makes Whisper repeat itself when a segment is mostly silence.
        segments, _info = model.transcribe(
            audio,
            language="en",
            beam_size=1,
            condition_on_previous_text=False,
            vad_filter=False,  # our own VAD already cut this audio
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
