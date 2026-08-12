"""Read what this machine can do.

Deliberately thin and dumb: every question it answers is one that cannot be
answered on a different machine, so there is nothing here worth testing. All
the judgement lives in ``tiering``, which is pure.

Nothing in here may raise. A machine that refuses to describe itself gets the
conservative defaults and still dictates.
"""

from __future__ import annotations

import logging
import os

from core.asr.tiering import Hardware

_log = logging.getLogger("winwhispr.asr.probe")


def probe() -> Hardware:
    """Describe this machine, falling back to modest assumptions."""
    return Hardware(
        cuda_devices=_cuda_devices(),
        vram_mb=_vram_mb(),
        compute_capability=_compute_capability(),
        cpu_threads=_cpu_threads(),
        cpu_int8=_cpu_supports_int8(),
    )


def _compute_capability() -> float:
    """CUDA compute capability, e.g. 8.9 (Ada) or 12.0 (Blackwell). 0 unknown.

    This decides whether the GPU is worth using at all: a card newer than the
    inference library runs through JIT-compiled PTX and lands slower than the
    CPU, so the number matters more than the presence of a device.
    """
    import subprocess

    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
        return max(float(line.strip()) for line in out.splitlines() if line.strip())
    except Exception as exc:  # pragma: no cover - depends on the machine
        _log.debug("no compute capability reading: %s", exc)
        return 0.0


def _cuda_devices() -> int:
    """Usable CUDA devices.

    A device the libraries cannot drive is worse than no device: it loads a
    model and then fails on the first word. So the CUDA runtime is registered
    and checked here, and a machine that cannot load it reports zero.
    """
    from core.asr import cuda_runtime

    if not cuda_runtime.ensure():
        return 0
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count())
    except Exception as exc:  # pragma: no cover - depends on the install
        _log.debug("no CUDA via ctranslate2: %s", exc)
        return 0


def _vram_mb() -> int:
    """Largest CUDA device's memory, via nvidia-smi. 0 when unknown."""
    import subprocess

    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
        return max(int(line.strip()) for line in out.splitlines() if line.strip())
    except Exception as exc:  # pragma: no cover - depends on the machine
        _log.debug("no VRAM reading: %s", exc)
        return 0


def _cpu_threads() -> int:
    return os.cpu_count() or 4


def _cpu_supports_int8() -> bool:
    try:
        import ctranslate2

        return "int8" in ctranslate2.get_supported_compute_types("cpu")
    except Exception:  # pragma: no cover - depends on the install
        return True  # int8 is universal enough that assuming it is safe
