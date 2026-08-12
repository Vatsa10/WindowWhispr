"""Speaker enrollment helper.

Records a short microphone sample and stores it as a 16 kHz mono WAV file under
``.speakers/`` so it can later be used for speaker identification / diarization.
"""

from __future__ import annotations

import os
import wave
from datetime import datetime

import numpy as np

from core import paths
from core.processor import AudioCapture

SPEAKERS_DIR = str(paths.speakers_dir())
SAMPLE_RATE = 16000


def _slugify(name: str) -> str:
    keep = [c if (c.isalnum() or c in "-_") else "_" for c in name.strip()]
    slug = "".join(keep).strip("_")
    return slug or "speaker"


def list_speakers() -> list[dict]:
    """Return enrolled speakers discovered in the speakers directory."""
    if not os.path.isdir(SPEAKERS_DIR):
        return []
    speakers = []
    for fname in sorted(os.listdir(SPEAKERS_DIR)):
        if not fname.lower().endswith(".wav"):
            continue
        path = os.path.join(SPEAKERS_DIR, fname)
        try:
            with wave.open(path, "rb") as wav:
                seconds = wav.getnframes() / float(wav.getframerate() or SAMPLE_RATE)
        except (OSError, wave.Error):
            seconds = 0.0
        speakers.append(
            {
                "name": os.path.splitext(fname)[0],
                "file": fname,
                "seconds": round(seconds, 1),
            }
        )
    return speakers


def record_speaker(name: str, seconds: float = 5.0) -> dict:
    """Record a mic sample for ``name`` and persist it as a WAV file."""
    os.makedirs(SPEAKERS_DIR, exist_ok=True)
    capture = AudioCapture(sample_rate=SAMPLE_RATE)
    audio = capture.capture(seconds=float(seconds))
    if audio.size == 0:
        raise RuntimeError("No audio captured. Check the microphone.")

    slug = _slugify(name)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    fname = f"{slug}-{stamp}.wav"
    path = os.path.join(SPEAKERS_DIR, fname)

    pcm16 = np.clip(audio, -1.0, 1.0)
    pcm16 = (pcm16 * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm16.tobytes())

    return {
        "name": os.path.splitext(fname)[0],
        "file": fname,
        "seconds": round(audio.size / float(SAMPLE_RATE), 1),
    }
