import math

from core.audio_meter import BARS, rms_to_bars


def test_silence_reads_zero():
    assert rms_to_bars([0.0] * 100) == [0.0] * BARS


def test_empty_block_is_safe():
    assert rms_to_bars([]) == [0.0] * BARS


def test_levels_are_clamped():
    assert all(0.0 <= v <= 1.0 for v in rms_to_bars([1.0] * 100))
    assert rms_to_bars([1.0] * 100) == [1.0] * BARS


def test_louder_audio_reads_higher():
    quiet = rms_to_bars([0.01] * 100)
    loud = rms_to_bars([0.05] * 100)
    assert loud[0] > quiet[0]


def test_bars_track_position_in_the_block():
    # First half silent, second half loud -> the level rises across the bars.
    frames = [0.0] * 50 + [0.5] * 50
    levels = rms_to_bars(frames, bars=2)
    assert levels[0] == 0.0
    assert levels[1] > 0.0


def test_bar_count_is_configurable():
    assert len(rms_to_bars([0.1] * 64, bars=3)) == 3


def test_rms_is_actually_rms():
    levels = rms_to_bars([0.5, -0.5, 0.5, -0.5], bars=1, gain=1.0)
    assert math.isclose(levels[0], 0.5, rel_tol=1e-6)
