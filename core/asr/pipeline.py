"""Transcribe while the user is still talking.

The wait a user feels is the gap between releasing the key and seeing text. If
transcription starts at release, that wait grows with the length of what they
said — a twenty second thought costs a multiple of a five second one, which is
exactly backwards from what people expect.

So closed speech segments are transcribed as the voice-activity detector emits
them, on a worker thread, while the user keeps speaking. At release only the
trailing fragment is left. The wait becomes a function of how long ago the user
last paused — normally a second or two — and stops depending on total length.

Engines that cannot be called freely (a metered API) opt out via
``caps.supports_pipelining`` and are given the whole utterance at the end, as
before.
"""

from __future__ import annotations

import logging
import queue
import threading
import time

_log = logging.getLogger("winwhispr.asr.pipeline")


class TranscriptionSession:
    """One dictation, from key-down to committed text."""

    def __init__(self, engine, log_transcript: bool = False):
        self._engine = engine
        self._log_transcript = log_transcript
        self._pipelined = bool(getattr(engine.caps, "supports_pipelining", False))

        self._jobs: queue.Queue = queue.Queue()
        self._results: dict[int, str] = {}
        #: Audio held back for engines that must be called once (metered APIs).
        self._pending_audio: list = []
        self._results_lock = threading.Lock()
        self._next_index = 0
        self._worker: threading.Thread | None = None
        self._error: Exception | None = None
        #: Time spent transcribing after the key was released.
        self.tail_ms = 0.0
        #: Segments that were already done before the user let go.
        self.pipelined_segments = 0

    # ---- during the hold ---------------------------------------------------

    def start(self) -> None:
        self._jobs = queue.Queue()
        with self._results_lock:
            self._results.clear()
        self._pending_audio.clear()
        self._next_index = 0
        self._error = None
        self.tail_ms = 0.0
        self.pipelined_segments = 0
        if self._pipelined:
            self._worker = threading.Thread(
                target=self._run_worker, daemon=True, name="winwhispr-asr"
            )
            self._worker.start()

    def submit(self, audio) -> None:
        """Hand over a closed speech segment. Returns immediately."""
        if audio is None or len(audio) == 0:
            return
        if not self._pipelined:
            # Metered engine: hold the audio and send it all at once later.
            self._pending_audio.append(audio)
            return
        index = self._next_index
        self._next_index += 1
        self._jobs.put((index, audio))
        self.pipelined_segments += 1

    def _run_worker(self) -> None:
        while True:
            item = self._jobs.get()
            if item is None:  # shutdown sentinel
                return
            index, audio = item
            try:
                text = self._engine.transcribe(audio)
                if self._log_transcript and text:
                    print(f"[WinWhispr][asr] segment {index}: {text}")
            except Exception as exc:  # surfaced on the caller's thread at finish()
                _log.warning("segment %d failed: %s", index, exc)
                self._error = exc
                text = ""
            with self._results_lock:
                self._results[index] = text

    # ---- at release --------------------------------------------------------

    def finish(self, tail_audio=None) -> str:
        """Transcribe whatever is left and return the whole utterance."""
        started = time.monotonic()
        try:
            if self._pipelined:
                if tail_audio is not None and len(tail_audio):
                    self.submit(tail_audio)
                    self.pipelined_segments -= 1  # the tail is not "free" work
                self._drain()
                with self._results_lock:
                    ordered = [self._results[i] for i in sorted(self._results)]
                if self._error is not None:
                    raise self._error
                return " ".join(part for part in ordered if part).strip()

            # Not pipelined: one call with everything, concatenated in order.
            chunks = list(self._pending_audio)
            if tail_audio is not None and len(tail_audio):
                chunks.append(tail_audio)
            if not chunks:
                return ""
            import numpy as np

            whole = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
            return self._engine.transcribe(whole).strip()
        finally:
            self.tail_ms = (time.monotonic() - started) * 1000

    def _drain(self, timeout: float = 30.0) -> None:
        """Wait for queued segments, then stop the worker.

        Polled rather than using ``queue.join()``: that needs ``task_done()``
        bookkeeping in the worker's error paths too, and this queue is never
        more than a few items deep.

        The deadline and the liveness check matter more than they look: without
        them, a worker that died — or a session whose results were dropped —
        leaves this loop spinning forever, taking the dictation thread with it.
        """
        deadline = time.monotonic() + timeout
        while True:
            with self._results_lock:
                done = len(self._results)
            if done >= self._next_index:
                break
            if self._worker is None or not self._worker.is_alive():
                _log.warning("ASR worker stopped with %d/%d segments done",
                             done, self._next_index)
                break
            if time.monotonic() > deadline:
                _log.warning("ASR drain timed out with %d/%d segments done",
                             done, self._next_index)
                break
            time.sleep(0.005)
        if self._worker is not None:
            self._jobs.put(None)
            self._worker.join(timeout=1.0)
            self._worker = None

    def abandon(self) -> None:
        """Cancelled session: stop the worker and drop everything.

        The segment counter resets alongside the results — otherwise a later
        ``finish()`` would sit waiting for transcripts that no longer exist.
        """
        if self._worker is not None:
            self._jobs.put(None)
            self._worker.join(timeout=1.0)
            self._worker = None
        with self._results_lock:
            self._results.clear()
        self._pending_audio.clear()
        self._next_index = 0
