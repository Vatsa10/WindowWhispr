"""Which model each class of machine gets.

These thresholds decide what a stranger's laptop does on first run, so they
are pinned here rather than left to be rediscovered from behaviour.
"""

from core.asr.tiering import (
    LATENCY_BUDGET_MS,
    TAIL_SECONDS,
    Hardware,
    calibrate,
    choose,
)


def test_supported_gpu_with_headroom_gets_the_large_distilled_model():
    choice = choose(Hardware(cuda_devices=1, vram_mb=8151, compute_capability=8.9,
                             cpu_threads=24))
    assert choice.model == "distil-large-v3"
    assert choice.device == "cuda"
    assert choice.compute_type == "float16"


def test_small_supported_gpu_falls_back_within_the_gpu():
    choice = choose(Hardware(cuda_devices=1, vram_mb=2048, compute_capability=7.5,
                             cpu_threads=8))
    assert choice.device == "cuda"
    assert choice.model == "small.en"


def test_gpu_too_new_for_the_library_is_not_used():
    # Blackwell (sm_120): CTranslate2 has no kernels, so CUDA JIT-compiles PTX
    # and lands slower than the CPU. Measured 2.8s for a 2s tail on an RTX 5050.
    choice = choose(Hardware(cuda_devices=1, vram_mb=8151, compute_capability=12.0,
                             cpu_threads=24))
    assert choice.device == "cpu"
    assert "compute capability" in choice.reason


def test_gpu_too_old_for_the_library_is_not_used():
    choice = choose(Hardware(cuda_devices=1, vram_mb=4096, compute_capability=6.1))
    assert choice.device == "cpu"


def test_many_cores_do_not_buy_a_bigger_model():
    # Measured: small.en costs ~1.3s on 24 threads, four times the budget.
    assert choose(Hardware(cpu_threads=24)).model == "base.en"


def test_ordinary_laptop_gets_base():
    assert choose(Hardware(cpu_threads=8)).model == "base.en"


def test_very_weak_machine_gets_tiny():
    assert choose(Hardware(cpu_threads=2)).model == "tiny.en"


def test_everything_unknown_still_produces_a_working_choice():
    choice = choose(Hardware())
    assert choice.model and choice.device == "cpu"


def test_calibrate_keeps_a_choice_that_meets_the_budget():
    choice = choose(Hardware(cpu_threads=24))
    assert calibrate(choice, 48.0) == choice


def test_calibrate_downgrades_a_machine_that_is_too_slow():
    choice = choose(Hardware(cpu_threads=24))       # base.en
    slower = calibrate(choice, 400.0)               # 800ms projected
    assert slower.model == "tiny.en"
    assert "over budget" in slower.reason


def test_calibrate_stops_at_the_smallest_model():
    tiny = choose(Hardware(cpu_threads=1))
    assert calibrate(tiny, 5000.0) == tiny


def test_calibrate_downgrades_within_the_gpu_rather_than_off_it():
    big = choose(Hardware(cuda_devices=1, vram_mb=8151, compute_capability=8.9))
    slower = calibrate(big, 500.0)
    assert slower.device == "cuda"
    assert slower.model == "small.en"


def test_budget_is_measured_against_the_tail_not_the_whole_utterance():
    # The point of the design: a long dictation must not cost more at release.
    assert TAIL_SECONDS <= 2.0
    assert LATENCY_BUDGET_MS <= 300
