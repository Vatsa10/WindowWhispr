"""Make the CUDA libraries loadable on Windows.

CTranslate2 needs cuBLAS and cuDNN 9 at runtime. NVIDIA publishes both as pip
wheels, which is how WinWhispr gets them — no CUDA toolkit install, no driver
surgery. But the wheels drop their DLLs in ``site-packages/nvidia/*/bin``,
which is not on the Windows DLL search path, so loading fails anyway with

    RuntimeError: Library cublas64_12.dll is not found or cannot be loaded

and, worse, it fails on the first *encode* rather than at model construction —
the model loads happily, then dies the first time someone speaks.

``ensure()`` registers those directories before CTranslate2 is imported. It
must be called before ``import faster_whisper`` anywhere in the process, and it
is safe to call repeatedly.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_log = logging.getLogger("winwhispr.asr.cuda")

#: Wheel subdirectories holding the DLLs, in load order.
_DLL_DIRS = ("cublas", "cudnn", "cuda_runtime")

_registered = False


def ensure() -> bool:
    """Put the NVIDIA wheel DLLs on the search path. True if any were found."""
    global _registered
    if _registered:
        return True
    if sys.platform != "win32":
        _registered = True
        return True  # Linux wheels set RPATH correctly; nothing to do

    found = False
    for directory in _dll_directories():
        try:
            os.add_dll_directory(str(directory))
            # PATH too: some loaders consult it rather than the added dirs.
            os.environ["PATH"] = f"{directory}{os.pathsep}{os.environ.get('PATH', '')}"
            found = True
            _log.debug("registered CUDA DLL directory %s", directory)
        except OSError as exc:  # pragma: no cover - path-dependent
            _log.debug("could not register %s: %s", directory, exc)

    _registered = True
    if not found:
        _log.info("no NVIDIA CUDA wheels found; GPU acceleration unavailable")
    return found


def _dll_directories() -> list[Path]:
    """Existing ``site-packages/nvidia/<lib>/bin`` directories."""
    out: list[Path] = []
    try:
        import nvidia
    except ImportError:
        return out

    for root in getattr(nvidia, "__path__", []):
        for name in _DLL_DIRS:
            candidate = Path(root) / name / "bin"
            if candidate.is_dir():
                out.append(candidate)
    return out


def available() -> bool:
    """True when CUDA libraries are present and a device can be used.

    Answers the question the settings screen asks — "can this machine use its
    GPU?" — rather than "does this machine have one", which is what a device
    count alone tells you.
    """
    if not ensure():
        return False
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # pragma: no cover - install dependent
        return False
