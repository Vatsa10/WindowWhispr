"""Turn raw mic frames into the handful of levels the overlay waveform draws.

Pure and allocation-light on purpose: this runs on the PortAudio callback
thread, where blocking or heavy work causes dropouts in the recording itself.
"""

from __future__ import annotations

import math

#: How many levels one audio block becomes. The overlay interpolates these up
#: to its own bar count.
BARS = 6

#: RMS of ordinary speech is small (~0.05); scale it into a visible range.
LEVEL_GAIN = 14.0


def rms_to_bars(frames, bars: int = BARS, gain: float = LEVEL_GAIN) -> list[float]:
    """Split ``frames`` into ``bars`` slices and return each slice's level.

    Levels are clamped to [0, 1]. An empty or silent block returns zeros rather
    than raising, so a dead microphone shows a flat line instead of an error.
    """
    n = len(frames)
    if n == 0 or bars <= 0:
        return [0.0] * max(bars, 0)
    out: list[float] = []
    step = n / bars
    for i in range(bars):
        start = int(i * step)
        end = int((i + 1) * step) if i < bars - 1 else n
        chunk = frames[start:end]
        if len(chunk) == 0:
            out.append(0.0)
            continue
        total = 0.0
        for sample in chunk:
            total += float(sample) * float(sample)
        rms = math.sqrt(total / len(chunk))
        out.append(min(1.0, max(0.0, rms * gain)))
    return out
