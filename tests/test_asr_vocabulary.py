"""Vocabulary biasing and audio normalization.

The dictionary used to reach only the cleanup model, which repairs a mis-heard
name after the fact — and often cannot, because "ChargeBee" heard as "charge B"
has already lost the information. These pin the decode-time hints instead.
"""

import numpy as np

from core.asr.faster_whisper_engine import (
    ASR_PROMPT,
    TARGET_PEAK,
    FasterWhisperEngine,
    _normalize_peak,
)
from core.asr.tiering import ModelChoice

CHOICE = ModelChoice("base.en", "cpu", "int8", "test")


def engine() -> FasterWhisperEngine:
    return FasterWhisperEngine(CHOICE)


def test_no_vocabulary_sends_no_hints():
    # An empty hint is not the same as no hint: passing empty strings makes
    # Whisper condition on nothing useful.
    assert engine()._decode_options() == {}


def test_vocabulary_becomes_both_hints():
    e = engine()
    e.set_vocabulary(["ChargeBee", "Manvi"])
    options = e._decode_options()
    assert options["hotwords"] == "ChargeBee, Manvi"
    assert options["initial_prompt"].startswith(ASR_PROMPT)
    assert "ChargeBee, Manvi" in options["initial_prompt"]


def test_vocabulary_is_cleaned_and_deduplicated():
    e = engine()
    e.set_vocabulary(["  ChargeBee ", "", None, "ChargeBee", "Manvi"])
    assert e._decode_options()["hotwords"] == "ChargeBee, Manvi"


def test_quiet_audio_is_brought_up_to_level():
    quiet = np.full(1000, 0.02, dtype=np.float32)
    louder = _normalize_peak(quiet)
    assert abs(float(np.abs(louder).max()) - TARGET_PEAK) < 1e-5


def test_silence_is_not_amplified():
    # Scaling room noise to full scale invents speech that was never there.
    silence = np.zeros(1000, dtype=np.float32)
    assert float(np.abs(_normalize_peak(silence)).max()) == 0.0

    near_silence = np.full(1000, 1e-6, dtype=np.float32)
    assert float(np.abs(_normalize_peak(near_silence)).max()) < 1e-5


def test_normalization_preserves_shape_and_dtype():
    audio = np.random.default_rng(0).uniform(-0.3, 0.3, 800).astype(np.float32)
    out = _normalize_peak(audio)
    assert out.shape == audio.shape and out.dtype == np.float32


def test_every_engine_accepts_vocabulary():
    # The pipeline hands vocabulary over without asking what kind of engine it
    # has, so a missing method would be an AttributeError mid-dictation.
    from core.asr.openvino_engine import OpenVinoEngine
    from core.asr.remote_engine import GroqEngine

    for other in (GroqEngine("whisper-large-v3"), OpenVinoEngine("Whisper Large")):
        other.set_vocabulary(["ChargeBee"])
