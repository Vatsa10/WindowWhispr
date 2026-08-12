"""Which model this machine should run.

Pure: hardware facts in, a model choice out. No imports of torch, ctranslate2,
Windows APIs, or anything else that varies by machine — so every branch here is
testable on any machine, which matters precisely because this file's whole job
is to reason about machines we do not have.

The tiers are calibrated against measurements, and the measurements overturned
two assumptions worth writing down.

**Latency barely depends on audio length.** Whisper's encoder pads every input
to a 30 second window, so transcribing a 2 second tail costs about what 7
seconds costs. On an i7-14650HX (24 threads), int8 on CPU:

    model      1s tail   2s tail   6.8s
    tiny.en      191ms     190ms    195ms
    base.en      ~330ms    384ms    427ms
    small.en    1231ms    1184ms   1337ms

Pipelining still pays — segments transcribed while the user talks are free by
the time they let go — but the tail costs one whole inference, so the model
choice is what decides whether the budget is met.

**A GPU is only useful if the library has kernels for it.** CTranslate2 has
none for Blackwell (sm_120, the RTX 50 series): int8 fails outright and float16
falls back to JIT-compiled PTX, which measured *slower* than the CPU —
distil-large-v3 took 2.8 seconds for a 2 second tail on an RTX 5050. So the
GPU tiers are gated on a compute capability the library actually supports,
rather than on the presence of a GPU.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

#: What the user waits for after releasing the key, in milliseconds. Chosen to
#: feel instant rather than fast.
LATENCY_BUDGET_MS = 300

#: Audio left to transcribe at release, in seconds. A speaker who pauses
#: normally leaves well under this; the cap on segment length bounds it.
TAIL_SECONDS = 2.0


#: CUDA compute capabilities CTranslate2 ships kernels for. Below the floor the
#: architecture is too old; above the ceiling it is too new, and CUDA silently
#: JIT-compiles PTX instead — which runs, slowly enough to be worse than the CPU.
MIN_COMPUTE_CAPABILITY = 7.0
MAX_COMPUTE_CAPABILITY = 9.9


@dataclass(frozen=True)
class Hardware:
    """What we could learn about this machine. Unknown fields stay conservative."""

    cuda_devices: int = 0
    #: VRAM of the largest CUDA device, in MB.
    vram_mb: int = 0
    #: CUDA compute capability, e.g. 8.9 for Ada, 12.0 for Blackwell. 0 unknown.
    compute_capability: float = 0.0
    #: Logical processors.
    cpu_threads: int = 4
    #: Whether CTranslate2 reports int8 support on this CPU.
    cpu_int8: bool = True

    @property
    def gpu_is_usable(self) -> bool:
        """A GPU the inference library can actually drive."""
        return (
            self.cuda_devices > 0
            and MIN_COMPUTE_CAPABILITY <= self.compute_capability <= MAX_COMPUTE_CAPABILITY
        )


@dataclass(frozen=True)
class ModelChoice:
    """A concrete engine configuration, ready to construct."""

    model: str
    device: str          # "cuda" | "cpu"
    compute_type: str    # "float16" | "int8_float16" | "int8"
    reason: str

    @property
    def label(self) -> str:
        return f"{self.model} ({self.device}/{self.compute_type})"


# GPU tiers. distil-large-v3 is ~6x faster than large-v3 at close to the same
# English accuracy, which is the trade this app wants: the accuracy difference
# is invisible next to a wait the user can feel.
_CUDA_LARGE = ModelChoice(
    "distil-large-v3", "cuda", "float16",
    "CUDA with room for a large distilled model",
)
_CUDA_SMALL = ModelChoice(
    "small.en", "cuda", "int8_float16",
    "CUDA with limited VRAM",
)

# CPU tiers. Measured: small.en costs ~1.3s per utterance even on 24 threads,
# which is four times the budget, so it is never chosen automatically — it is
# there for someone who deliberately trades latency for accuracy. base.en is
# the automatic choice: ~330-430ms, and markedly better than tiny.en on names
# and technical terms.
_CPU_SMALL = ModelChoice("small.en", "cpu", "int8", "accuracy over speed")
_CPU_BASE = ModelChoice("base.en", "cpu", "int8", "best accuracy inside the budget")
_CPU_TINY = ModelChoice("tiny.en", "cpu", "int8", "few CPU cores")

#: VRAM needed before a large distilled model is worth loading. Below this it
#: competes with the desktop compositor and games for memory.
LARGE_MODEL_VRAM_MB = 4500


def choose(hw: Hardware) -> ModelChoice:
    """Pick the best model this machine can run inside the latency budget."""
    if hw.gpu_is_usable:
        if hw.vram_mb >= LARGE_MODEL_VRAM_MB:
            return _CUDA_LARGE
        return _CUDA_SMALL

    if hw.cuda_devices > 0:
        # A GPU is present but the library cannot use it. Saying so is the
        # difference between "this app ignores my GPU" and a known limitation.
        return replace(
            _CPU_BASE,
            reason=(
                f"GPU compute capability {hw.compute_capability:g} is outside "
                f"what CTranslate2 supports ({MIN_COMPUTE_CAPABILITY:g}-"
                f"{MAX_COMPUTE_CAPABILITY:g}); using the CPU, which is faster here"
            ),
        )

    # CPU. More cores do not buy a bigger model: measured, small.en costs about
    # 1.3s on 24 threads, barely different from 8.
    if hw.cpu_threads >= 4:
        return _CPU_BASE
    return _CPU_TINY


#: Rough cost of one second of audio, in milliseconds, per model. Used only to
#: decide whether a measured machine should be downgraded.
_FALLBACK_ORDER = [_CPU_SMALL, _CPU_BASE, _CPU_TINY]


def cpu_fallback(choice: ModelChoice, cpu_threads: int = 8) -> ModelChoice:
    """The CPU choice to use when a GPU turns out to be unusable.

    A distilled large model is a poor CPU citizen, so this drops to whatever
    the CPU tier would have picked rather than keeping the GPU-sized model.
    """
    fallback = choose(Hardware(cpu_threads=cpu_threads))
    return replace(
        fallback,
        reason=f"GPU unavailable, fell back from {choice.model}",
    )


def calibrate(choice: ModelChoice, measured_ms_per_audio_second: float) -> ModelChoice:
    """Downgrade a choice that turned out too slow on the real machine.

    Guessing from core counts is a heuristic; this is the correction. A machine
    is judged on what it actually did, not on what its spec sheet implies —
    thermal throttling, a busy laptop, and an unusual CPU all show up here and
    nowhere else.
    """
    projected = measured_ms_per_audio_second * TAIL_SECONDS
    if projected <= LATENCY_BUDGET_MS:
        return choice

    # GPU that cannot keep up: drop to the smaller GPU model rather than to CPU,
    # which would be slower still.
    if choice.device == "cuda":
        if choice == _CUDA_LARGE:
            return replace(
                _CUDA_SMALL,
                reason=f"downgraded: distil-large-v3 projected {projected:.0f}ms, over budget",
            )
        return choice

    try:
        index = _FALLBACK_ORDER.index(choice)
    except ValueError:
        return choice
    if index + 1 >= len(_FALLBACK_ORDER):
        return choice  # already the smallest; nothing left to give up
    return replace(
        _FALLBACK_ORDER[index + 1],
        reason=f"downgraded: {choice.model} projected {projected:.0f}ms, over budget",
    )
