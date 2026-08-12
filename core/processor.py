"""Audio -> VAD -> ASR processing pipeline.

This module captures microphone audio, chunks speech with ONNX Silero VAD,
passes chunks through a low-overhead ASR queue, and returns merged text.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import queue
import threading
import time

import numpy as np

from core.audio_meter import rms_to_bars
from core.model_manager import ensure_required_models
from core.model_registry import CLOUD_BACKENDS, resolve_backend, resolve_model_id

_log = logging.getLogger("winwhispr.asr")


def _ov_cache_dir() -> str | None:
    """Directory for OpenVINO compiled-model caching under ~/.cache/winwhispr.

    Keeping the multi-GB compiled blob outside any OneDrive-synced folder
    avoids uploading / dehydrating it, which would force a slow recompile on
    the next boot.
    """
    try:
        from core import paths

        return str(paths.ov_cache_dir())
    except Exception:  # pragma: no cover - env dependent
        return None


def input_devices() -> list[str]:
    """Names of the available microphones, newest query each call.

    The default device is offered as an explicit choice so a user who changes
    their Windows default does not have to come back here.
    """
    names = ["System default"]
    try:
        import sounddevice as sd

        for info in sd.query_devices():
            if int(info.get("max_input_channels", 0)) > 0:
                name = str(info.get("name", "")).strip()
                if name and name not in names:
                    names.append(name)
    except Exception as exc:  # pragma: no cover - device enumeration dependent
        print(f"[WinWhispr][audio] Could not list input devices: {exc}")
    return names


def available_devices() -> list[str]:
    """List selectable OpenVINO compute devices for the UI (AUTO + detected)."""
    devices = ["AUTO"]
    try:
        import openvino as ov

        for name in ov.Core().available_devices:
            base = name.split(".")[0]
            if base not in devices:
                devices.append(base)
    except Exception:  # pragma: no cover - env dependent
        pass
    for fallback in ("GPU", "CPU"):
        if fallback not in devices:
            devices.append(fallback)
    return devices


class SileroVADChunker:
    """Chunk speech segments from float32 mono audio using ONNX Silero VAD."""

    _WINDOW = 512  # Silero v5 requires exactly 512 samples per frame at 16 kHz
    _CONTEXT = 64  # Silero v5 prepends the last 64 samples of the previous frame

    def __init__(self, model_path: str, sample_rate: int = 16000, threshold: float = 0.5,
                 min_silence_ms: float = 300.0):
        self._sample_rate = sample_rate
        self._model_path = model_path
        self._threshold = max(0.05, min(0.95, float(threshold)))
        # Silence gap (ms) that must follow speech before a chunk is closed.
        self._min_silence = int(sample_rate * max(0.05, float(min_silence_ms) / 1000.0))
        self._session = None
        self._load()

    def _load(self) -> None:
        # Run the ONNX model directly through onnxruntime -- no torch / silero
        # package needed (which would pull in PyTorch and slow startup).
        try:
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
            self._session = ort.InferenceSession(
                self._model_path,
                sess_options=opts,
                providers=["CPUExecutionProvider"],
            )
        except Exception as exc:  # pragma: no cover - runtime environment dependent
            print(f"[WinWhispr][vad] Failed to load Silero VAD ONNX, fallback mode: {exc}")
            self._session = None

    def chunk(self, audio: np.ndarray) -> list[np.ndarray]:
        if audio.size == 0:
            return []

        if self._session is None:
            return self._energy_fallback(audio)

        try:
            segments = self._speech_timestamps(audio)
            chunks = [audio[start:end] for start, end in segments]
            return [chunk for chunk in chunks if chunk.size > 0]
        except Exception as exc:  # pragma: no cover - model behavior dependent
            print(f"[WinWhispr][vad] ONNX VAD failed, fallback mode: {exc}")
            return self._energy_fallback(audio)

    def _frame_probs(self, audio: np.ndarray) -> list[float]:
        """Run Silero VAD per 512-sample window, carrying hidden state + context.

        Silero VAD v5 expects each 512-sample window to be prefixed with the
        final 64 samples of the previous window (576 samples total). Omitting
        this context makes the model score nearly every frame as silence, so no
        speech segments are ever emitted.
        """
        session = self._session
        state = np.zeros((2, 1, 128), dtype=np.float32)
        context = np.zeros(self._CONTEXT, dtype=np.float32)
        sr = np.array(self._sample_rate, dtype=np.int64)
        window = self._WINDOW
        probs: list[float] = []
        for start in range(0, len(audio), window):
            frame = audio[start:start + window]
            if len(frame) < window:
                frame = np.pad(frame, (0, window - len(frame)))
            model_input = np.concatenate((context, frame)).reshape(1, -1).astype(np.float32)
            out, state = session.run(
                ["output", "stateN"],
                {
                    "input": model_input,
                    "state": state,
                    "sr": sr,
                },
            )
            context = frame[-self._CONTEXT:]
            probs.append(float(out[0, 0]))
        return probs

    def _speech_timestamps(self, audio: np.ndarray) -> list[tuple[int, int]]:
        """Reproduce Silero's segmenter (lenient defaults) from frame probs."""
        sr = self._sample_rate
        threshold = self._threshold
        neg_threshold = max(0.15, threshold - 0.15)
        min_speech = int(sr * 0.25)    # 250 ms
        min_silence = self._min_silence  # configurable silence gap
        pad = int(sr * 0.20)           # 200 ms padding (lenient)
        window = self._WINDOW
        total = len(audio)

        probs = self._frame_probs(audio)
        segments: list[tuple[int, int]] = []
        triggered = False
        current_start = 0
        temp_end = 0
        for i, prob in enumerate(probs):
            sample = window * i
            if prob >= threshold and temp_end:
                temp_end = 0
            if prob >= threshold and not triggered:
                triggered = True
                current_start = sample
                continue
            if prob < neg_threshold and triggered:
                if not temp_end:
                    temp_end = sample
                if sample - temp_end < min_silence:
                    continue
                if temp_end - current_start > min_speech:
                    segments.append((current_start, temp_end))
                temp_end = 0
                triggered = False
        if triggered and (total - current_start) > min_speech:
            segments.append((current_start, total))

        return [(max(0, s - pad), min(total, e + pad)) for s, e in segments]

    def segment_stream(
        self, audio: np.ndarray, max_segment_samples: int | None = None
    ) -> tuple[list[np.ndarray], int]:
        """Segment a rolling buffer, emitting only *completed* speech segments.

        Unlike :meth:`chunk`, this never cuts speech that is still in progress.
        A segment is emitted only once trailing silence (>= ``min_silence``) is
        seen, or once it grows past ``max_segment_samples`` (a safety flush so a
        never-ending monologue still produces output and the buffer stays
        bounded).

        Returns ``(chunks, consumed)`` where ``chunks`` are finished speech
        segments ready for ASR and ``consumed`` is the number of leading samples
        the caller may drop from its buffer. Samples after ``consumed`` are
        speech still in progress (or a short pre-roll of silence) and must be
        retained for the next call.
        """
        if audio.size == 0:
            return [], 0
        if self._session is None:
            # No ONNX model -> fall back to whole-buffer energy chunking.
            return self._energy_fallback(audio), len(audio)

        try:
            return self._segment_stream_onnx(audio, max_segment_samples)
        except Exception as exc:  # pragma: no cover - model behavior dependent
            print(f"[WinWhispr][vad] ONNX stream VAD failed, fallback mode: {exc}")
            return self._energy_fallback(audio), len(audio)

    def _segment_stream_onnx(
        self, audio: np.ndarray, max_segment_samples: int | None
    ) -> tuple[list[np.ndarray], int]:
        sr = self._sample_rate
        threshold = self._threshold
        neg_threshold = max(0.15, threshold - 0.15)
        min_speech = int(sr * 0.25)    # 250 ms
        min_silence = self._min_silence  # configurable silence gap
        pad = int(sr * 0.20)           # 200 ms padding
        window = self._WINDOW
        total = len(audio)

        probs = self._frame_probs(audio)
        chunks: list[np.ndarray] = []
        consumed = 0
        triggered = False
        current_start = 0
        temp_end = 0

        for i, prob in enumerate(probs):
            sample = window * i
            if prob >= threshold and temp_end:
                temp_end = 0
            if prob >= threshold and not triggered:
                triggered = True
                current_start = sample
                continue
            # Safety flush: a single segment has grown too long -> cut it now.
            if (
                triggered
                and max_segment_samples
                and (sample - current_start) >= max_segment_samples
            ):
                seg_start = max(consumed, current_start - pad)
                seg_end = min(total, sample + pad)
                if seg_end > seg_start:
                    chunks.append(audio[seg_start:seg_end])
                consumed = sample
                current_start = sample  # ongoing speech continues as new segment
                temp_end = 0
                continue
            if prob < neg_threshold and triggered:
                if not temp_end:
                    temp_end = sample
                if sample - temp_end < min_silence:
                    continue
                if temp_end - current_start > min_speech:
                    seg_start = max(consumed, current_start - pad)
                    seg_end = min(total, temp_end + pad)
                    if seg_end > seg_start:
                        chunks.append(audio[seg_start:seg_end])
                consumed = sample
                temp_end = 0
                triggered = False

        if triggered:
            # Speech still ongoing -> retain from its start (keep left-pad).
            consumed = max(consumed, max(0, current_start - pad))
        else:
            # Only silence remains -> drop it but keep a short pre-roll.
            consumed = max(consumed, total - pad)
        consumed = max(0, min(consumed, total))
        return chunks, consumed

    def _energy_fallback(self, audio: np.ndarray) -> list[np.ndarray]:
        frame = int(self._sample_rate * 0.03)
        hop = frame
        threshold = max(0.002, self._threshold * 0.03)
        min_frames = 8
        silence_frames = 6

        segments = []
        active_start = None
        silent = 0
        voiced = 0

        for idx in range(0, max(len(audio) - frame, 1), hop):
            window = audio[idx:idx + frame]
            rms = float(np.sqrt(np.mean(window * window) + 1e-9))
            if rms >= threshold:
                if active_start is None:
                    active_start = idx
                voiced += 1
                silent = 0
            elif active_start is not None:
                silent += 1
                if silent >= silence_frames:
                    end = idx
                    if voiced >= min_frames:
                        segments.append(audio[active_start:end])
                    active_start = None
                    silent = 0
                    voiced = 0

        if active_start is not None and voiced >= min_frames:
            segments.append(audio[active_start:])
        return [seg for seg in segments if seg.size > 0]


class OVASRBackend:
    """Cohere OpenVINO IR ASR wrapper (KV-cache decode), preferring GPU."""

    def __init__(
        self,
        model_dir: str,
        device: str = "GPU",
        max_kv_tokens: int = 256,
        kv_evict_ratio: float = 0.25,
    ):
        self._model_dir = model_dir
        self._device = device
        self._ctx = None
        self._sample_rate = 16000
        self._max_new_tokens = 200
        self._warmup_samples = self._sample_rate
        # Self-attention KV-cache guard: never let the decode cache grow past
        # ``max_kv_tokens``; when it does, evict the oldest tokens so only the
        # most recent ``(1 - kv_evict_ratio)`` fraction is kept (sliding window).
        self._max_kv_tokens = max(1, int(max_kv_tokens))
        self._kv_evict_ratio = min(0.9, max(0.0, float(kv_evict_ratio)))
        self._load()

    def _load_ctx(self, device: str) -> bool:
        """Load Cohere OpenVINO IR graphs for direct KV-cache decoding."""
        model_dir = Path(self._model_dir)
        meta_path = model_dir / "ov_cohere_transcribe_kvcache.json"
        if not meta_path.is_file():
            nested_dir = model_dir / "models"
            nested_meta = nested_dir / "ov_cohere_transcribe_kvcache.json"
            if nested_meta.is_file():
                model_dir = nested_dir
                meta_path = nested_meta
            else:
                return False

        try:
            import openvino as ov
            from core.cohere_processor import CohereNPProcessor
        except Exception as exc:
            print(f"[WinWhispr][asr] Fallback dependencies unavailable: {exc}")
            return False

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            # Torch-free processor: the upstream CohereAsrProcessor hard-depends
            # on PyTorch, but we only run the OpenVINO IR graphs, so we
            # reproduce its mel frontend + tokenizer in NumPy/librosa instead.
            processor = CohereNPProcessor(str(model_dir))
            core = ov.Core()
            # Cache compiled kernels to local disk so subsequent boots skip the
            # expensive recompilation (much faster startup, far less CPU).
            try:
                cache_dir = _ov_cache_dir()
                if cache_dir:
                    core.set_property({"CACHE_DIR": cache_dir})
            except Exception as cache_exc:  # pragma: no cover - env dependent
                print(f"[WinWhispr][asr] Model cache unavailable: {cache_exc}")
            encoder = core.compile_model(model_dir / meta["encoder_ir"], device)
            prefill = core.compile_model(model_dir / meta["decoder_ir"], device)
            decode = core.compile_model(model_dir / meta["decoder_with_past_ir"], device)
            eos = meta["eos_token_id"]
            eos_set = set(eos) if isinstance(eos, (list, tuple)) else {eos}
            num_layers = int(meta["num_layers"])

            self._ctx = {
                "processor": processor,
                "encoder": encoder,
                "prefill": prefill,
                "decode": decode,
                "eos_set": eos_set,
                "num_layers": num_layers,
            }
            print(f"[WinWhispr][asr] Loaded KV-cache ASR pipeline on {device}")
            return True
        except Exception as exc:
            print(f"[WinWhispr][asr] KV-cache init failed on {device}: {exc}")
            _log.exception("KV-cache ASR init failed on %s", device)
            return False

    @staticmethod
    def _to_named_outputs(result: dict) -> dict:
        named = {}
        for key, value in result.items():
            if hasattr(key, "get_any_name"):
                named[key.get_any_name()] = value
            else:
                named[str(key)] = value
        return named

    @staticmethod
    def _np(x, dtype):
        return np.asarray(x.cpu() if hasattr(x, "cpu") else x).astype(dtype)

    def _evict_kv(self, self_kv):
        """Bound the self-attention KV cache; drop oldest tokens past the cap."""
        if not self_kv:
            return self_kv
        seq_len = self_kv[0][0].shape[2]
        if seq_len <= self._max_kv_tokens:
            return self_kv
        keep = max(1, int(self._max_kv_tokens * (1.0 - self._kv_evict_ratio)))
        return [(k[:, :, -keep:, :], v[:, :, -keep:, :]) for k, v in self_kv]

    def _transcribe(self, audio_chunk: np.ndarray) -> str:
        ctx = self._ctx
        if not ctx:
            return ""

        processor = ctx["processor"]
        encoder = ctx["encoder"]
        prefill = ctx["prefill"]
        decode = ctx["decode"]
        eos_set = ctx["eos_set"]
        num_layers = ctx["num_layers"]

        inputs = processor(audio_chunk, sampling_rate=self._sample_rate, language="en", return_tensors="np")
        feat = self._np(inputs["input_features"], np.float32)
        amask = self._np(inputs["attention_mask"], bool)
        prompt = self._np(inputs["decoder_input_ids"], np.int64)

        enc_res = encoder({"input_features": feat, "attention_mask": amask})
        ehs = enc_res["encoder_hidden_states"]
        emask = enc_res["encoder_attention_mask"]

        pf = prefill(
            {
                "decoder_input_ids": prompt,
                "encoder_hidden_states": ehs,
                "encoder_attention_mask": emask,
            }
        )
        pf = self._to_named_outputs(pf)

        self_kv = [
            (pf[f"present.{i}.self.key"], pf[f"present.{i}.self.value"])
            for i in range(num_layers)
        ]
        cross_kv = [
            (pf[f"present.{i}.cross.key"], pf[f"present.{i}.cross.value"])
            for i in range(num_layers)
        ]

        next_id = int(pf["logits"][0, -1].argmax())
        generated = [next_id]

        for _ in range(self._max_new_tokens):
            if next_id in eos_set:
                break

            seq_len = self_kv[0][0].shape[2] if self_kv else 0
            self_mask = np.ones((1, seq_len + 1), dtype=np.int64)
            feed = {
                "decoder_input_ids": np.array([[next_id]], dtype=np.int64),
                "encoder_hidden_states": ehs,
                "encoder_attention_mask": emask,
                "self_attention_mask": self_mask,
            }
            for i in range(num_layers):
                feed[f"past.{i}.self.key"] = self_kv[i][0]
                feed[f"past.{i}.self.value"] = self_kv[i][1]
                feed[f"past.{i}.cross.key"] = cross_kv[i][0]
                feed[f"past.{i}.cross.value"] = cross_kv[i][1]

            step = decode(feed)
            step = self._to_named_outputs(step)
            self_kv = [
                (step[f"present.{i}.self.key"], step[f"present.{i}.self.value"])
                for i in range(num_layers)
            ]
            self_kv = self._evict_kv(self_kv)

            next_id = int(step["logits"][0, -1].argmax())
            generated.append(next_id)

        text = processor.batch_decode([generated], skip_special_tokens=True)[0]
        return str(text).strip()

    def _load(self) -> None:
        if self._load_ctx(self._device):
            self._warmup_once()
            return
        if self._device != "CPU" and self._load_ctx("CPU"):
            self._warmup_once()
            return
        print("[WinWhispr][asr] ASR backend unavailable after KV-cache init attempts")

    def _warmup_once(self) -> None:
        """Prime one-off frontend/runtime lazy paths before user inference."""
        if self._ctx is None:
            return
        warmup_audio = np.zeros((self._warmup_samples,), dtype=np.float32)
        start = time.time()
        try:
            self._transcribe(warmup_audio)
            print(f"[WinWhispr][asr] Warmup completed in {time.time() - start:.2f}s")
        except Exception as exc:  # pragma: no cover - model/runtime dependent
            print(f"[WinWhispr][asr] Warmup failed: {exc}")

    def transcribe(self, audio_chunk: np.ndarray) -> str:
        if audio_chunk.size == 0:
            return ""
        if self._ctx is None:
            return ""
        try:
            return self._transcribe(audio_chunk)
        except Exception as exc:  # pragma: no cover - model behavior dependent
            print(f"[WinWhispr][asr] Transcription failed: {exc}")
            return ""


class WhisperOVBackend:
    """Whisper ASR via OpenVINO GenAI WhisperPipeline."""

    def __init__(self, model_dir: str, device: str = "GPU"):
        self._pipe = None
        self._load(str(model_dir), device)

    def _load(self, model_dir: str, device: str) -> None:
        try:
            import openvino_genai as ov_genai
        except Exception as exc:
            print(f"[WinWhispr][asr] openvino_genai unavailable: {exc}")
            return
        cache_dir = _ov_cache_dir()
        # Try GPU then CPU; for each, prefer the disk cache but fall back to no
        # cache in case the CACHE_DIR property is rejected by this build.
        attempts = []
        for dev in (device, "CPU"):
            if cache_dir:
                attempts.append((dev, {"CACHE_DIR": cache_dir}))
            attempts.append((dev, {}))
        for dev, cfg in attempts:
            try:
                self._pipe = ov_genai.WhisperPipeline(model_dir, dev, **cfg)
                print(f"[WinWhispr][asr] Loaded Whisper pipeline on {dev}")
                return
            except Exception as exc:
                print(f"[WinWhispr][asr] Whisper init failed on {dev}: {exc}")
        self._pipe = None

    def transcribe(self, audio_chunk: np.ndarray) -> str:
        if self._pipe is None or audio_chunk.size == 0:
            return ""
        try:
            result = self._pipe.generate(audio_chunk.astype(np.float32, copy=False))
            texts = getattr(result, "texts", None)
            text = texts[0] if texts else str(result)
            return str(text).strip()
        except Exception as exc:  # pragma: no cover - model behavior dependent
            print(f"[WinWhispr][asr] Whisper transcription failed: {exc}")
            return ""


class AudioCapture:
    """Continuous mono PCM capture with a single persistent input stream.

    A previous design opened a fresh ``InputStream`` for every 3 s window and
    closed it during VAD/ASR -- so anything spoken while the model was busy was
    lost. Here one stream stays open for the whole dictation session and its
    callback keeps filling a queue *during* inference, so no audio is dropped;
    ``capture`` simply drains the next window from that always-running queue.
    """

    def __init__(self, sample_rate: int = 16000, block_seconds: float = 0.25,
                 on_level=None, device=None):
        self._sample_rate = sample_rate
        # None means "whatever Windows calls the default input device".
        self._device = device
        self._block_size = int(sample_rate * block_seconds)
        self._stream = None
        self._frame_queue: queue.SimpleQueue[np.ndarray] = queue.SimpleQueue()
        # Optional live level meter for the overlay. Called on the PortAudio
        # thread, so it must be fast and non-blocking.
        self._on_level = on_level

    def start(self) -> None:
        """Open the persistent input stream (idempotent)."""
        if self._stream is not None:
            return
        import sounddevice as sd

        # Drop any stale frames buffered from a previous session.
        try:
            while True:
                self._frame_queue.get_nowait()
        except queue.Empty:
            pass

        def _callback(indata, _frames, _time_info, _status) -> None:
            mono = indata[:, 0].copy()
            self._frame_queue.put(mono)
            if self._on_level is not None:
                try:
                    self._on_level(rms_to_bars(mono))
                except Exception:  # pragma: no cover - a meter must never
                    pass          # break the recording it is measuring

        stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self._block_size,
            callback=_callback,
            device=self._device,
        )
        stream.start()
        self._stream = stream

    def stop(self) -> None:
        """Close the stream and release the microphone."""
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:  # pragma: no cover - device teardown guard
                pass

    def capture(self, seconds: float = 3.0, stop_event: threading.Event | None = None) -> np.ndarray:
        """Drain ``seconds`` of audio from the running stream (starts it lazily)."""
        if self._stream is None:
            try:
                self.start()
            except Exception as exc:
                print(f"[WinWhispr][audio] Capture failed: {exc}")
                return np.empty((0,), dtype=np.float32)

        total_samples = int(self._sample_rate * seconds)
        collected = []
        captured = 0
        start = time.time()
        while (
            captured < total_samples
            and (time.time() - start) < (seconds + 2.0)
            and (stop_event is None or not stop_event.is_set())
        ):
            try:
                block = self._frame_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            collected.append(block)
            captured += len(block)

        if not collected:
            return np.empty((0,), dtype=np.float32)
        return np.concatenate(collected).astype(np.float32, copy=False)

    def drain_available(self) -> np.ndarray:
        """Non-blocking: return all audio currently queued (may be empty)."""
        collected = []
        try:
            while True:
                collected.append(self._frame_queue.get_nowait())
        except queue.Empty:
            pass
        if not collected:
            return np.empty((0,), dtype=np.float32)
        return np.concatenate(collected).astype(np.float32, copy=False)


class GroqASRBackend:
    """Whisper large-v3 on Groq.

    Unlike the local backends this is billed and rate limited (20 requests a
    minute), so the pipeline sends one request per dictation session rather
    than one per speech segment. Long sessions are split by the client to stay
    under the upload limit.
    """

    def __init__(self, model: str = "whisper-large-v3", sample_rate: int = 16000):
        self._model = model
        self._sample_rate = sample_rate

    def transcribe(self, audio: np.ndarray) -> str:
        from core import secrets
        from core.groq_client import transcribe

        return transcribe(
            audio,
            api_key=secrets.get_key("groq_api_key"),
            model=self._model,
            sample_rate=self._sample_rate,
        )


class TextPipeline:
    """Queue-based low-overhead speech pipeline.

    Flow:
        mic stream -> silero vad chunks -> asr queue -> merged text
    """

    # How much audio to pull from the mic per loop iteration. This only sets
    # responsiveness/latency granularity -- chunk *boundaries* come from VAD.
    _READ_SECONDS = 0.5
    # Safety cap so a non-stop monologue still flushes and the buffer stays
    # bounded (segments are normally cut on silence, not on length).
    _MAX_SEGMENT_SECONDS = 15.0

    def __init__(
        self,
        model_display_name: str,
        vad_threshold: float = 0.5,
        log_transcript: bool = False,
        device: str = "GPU",
        min_silence_ms: float = 300.0,
        max_segment_seconds: float | None = None,
        on_level=None,
        input_device=None,
    ):
        self._model_display_name = model_display_name
        self._log_transcript = log_transcript
        model_paths = ensure_required_models(model_display_name)

        self._sample_rate = 16000
        max_seconds = (
            self._MAX_SEGMENT_SECONDS if max_segment_seconds is None
            else max(1.0, float(max_segment_seconds))
        )
        self._max_segment_samples = int(self._sample_rate * max_seconds)

        self._capture = AudioCapture(
            sample_rate=16000, on_level=on_level, device=input_device
        )
        self._vad = SileroVADChunker(
            model_paths["vad_model_path"],
            sample_rate=16000,
            threshold=vad_threshold,
            min_silence_ms=min_silence_ms,
        )
        backend = resolve_backend(model_display_name)
        # Cloud ASR is batched per session: transcribing every VAD segment
        # separately would burn the request allowance and lose the context that
        # makes a large model worth calling.
        self._batch_whole_session = backend in CLOUD_BACKENDS
        if backend == "groq_whisper":
            self._asr = GroqASRBackend(resolve_model_id(model_display_name))
        elif backend == "whisper_genai":
            self._asr = WhisperOVBackend(model_paths["asr_model_dir"], device=device)
        else:
            self._asr = OVASRBackend(model_paths["asr_model_dir"], device=device)

        self._buffer = np.empty((0,), dtype=np.float32)
        # Session-wide audio bookkeeping: lets an empty transcript say whether
        # the microphone was silent or the model simply heard nothing.
        self._session_samples = 0
        self._session_peak = 0.0

    #: Peak sample below which a session counts as silence, not quiet speech.
    SILENCE_PEAK = 0.005

    def session_audio_stats(self) -> dict:
        """What the microphone actually delivered during the last session."""
        return {
            "samples": self._session_samples,
            "seconds": round(self._session_samples / float(self._sample_rate), 2),
            "peak": round(self._session_peak, 4),
            "silent": self._session_peak < self.SILENCE_PEAK,
        }

    def _note_audio(self, audio: np.ndarray) -> None:
        if audio.size == 0:
            return
        self._session_samples += int(audio.size)
        self._session_peak = max(self._session_peak, float(np.max(np.abs(audio))))

    def start_capture(self) -> None:
        """Open the continuous microphone stream for a dictation session."""
        self._buffer = np.empty((0,), dtype=np.float32)
        self._session_samples = 0
        self._session_peak = 0.0
        try:
            self._capture.start()
        except Exception as exc:  # pragma: no cover - device dependent
            print(f"[WinWhispr][audio] Could not start capture stream: {exc}")

    def stop_capture(self) -> None:
        """Close the microphone stream at the end of a dictation session."""
        self._capture.stop()
        self._buffer = np.empty((0,), dtype=np.float32)

    def _transcribe_chunks(
        self, chunks: list[np.ndarray], stop_event: threading.Event | None
    ) -> str:
        parts = []
        for chunk in chunks:
            if stop_event is not None and stop_event.is_set():
                break
            text = self._asr.transcribe(chunk)
            if text:
                parts.append(text)
                if self._log_transcript:
                    print(f"[WinWhispr][asr] chunk: {text}")
        merged = " ".join(parts).strip()
        if self._log_transcript and merged:
            print(f"[WinWhispr][asr] transcript: {merged}")
        return merged

    def process(
        self,
        stop_event: threading.Event | None = None,
    ) -> tuple[str, float]:
        """Pull a short read window, segment the rolling buffer by VAD silence,
        transcribe only *completed* segments, and return merged text + elapsed.

        Speech in progress stays buffered across calls, so continuous speech is
        cut on real pauses (or the max-segment safety cap) -- not on a fixed
        capture window.
        """
        start = time.time()
        audio = self._capture.capture(seconds=self._READ_SECONDS, stop_event=stop_event)
        self._note_audio(audio)
        if audio.size:
            self._buffer = (
                np.concatenate([self._buffer, audio]) if self._buffer.size else audio
            )
        if self._buffer.size == 0:
            return "", time.time() - start

        if self._batch_whole_session:
            # Hold everything until flush(): one request, full context.
            return "", time.time() - start

        chunks, consumed = self._vad.segment_stream(
            self._buffer, max_segment_samples=self._max_segment_samples
        )
        merged = self._transcribe_chunks(chunks, stop_event)
        if consumed > 0:
            self._buffer = self._buffer[consumed:]
        return merged, time.time() - start

    def flush(
        self,
        stop_event: threading.Event | None = None,
    ) -> tuple[str, float]:
        """Drain any remaining audio and transcribe the final in-progress speech.

        Called once when dictation stops so the last utterance (which has no
        trailing silence) is not lost.
        """
        start = time.time()
        tail = self._capture.drain_available()
        self._note_audio(tail)
        if tail.size:
            self._buffer = (
                np.concatenate([self._buffer, tail]) if self._buffer.size else tail
            )
        if self._buffer.size == 0:
            return "", time.time() - start

        if self._batch_whole_session:
            # One request for the whole utterance. Skipping the VAD split here
            # is deliberate: a large model handles its own pauses, and every
            # extra segment would be another billed round trip.
            audio, self._buffer = self._buffer, np.empty((0,), dtype=np.float32)
            text = self._asr.transcribe(audio)
            if self._log_transcript and text:
                print(f"[WinWhispr][asr] transcript: {text}")
            return text, time.time() - start

        # End of stream == silence, so `chunk` closes the trailing segment.
        chunks = self._vad.chunk(self._buffer)
        self._buffer = np.empty((0,), dtype=np.float32)
        merged = self._transcribe_chunks(chunks, stop_event=None)
        return merged, time.time() - start

