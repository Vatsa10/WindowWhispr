"""CUDA library discovery.

The failure this guards against is specific and nasty: with the NVIDIA wheels
installed but their DLL directories unregistered, a model loads on the GPU and
then dies on the first encode with "cublas64_12.dll is not found". So the
registration must happen before CTranslate2 is imported, and must be honest
about whether it found anything.
"""

import sys
import types
from pathlib import Path

import pytest

from core.asr import cuda_runtime


@pytest.fixture(autouse=True)
def reset_registration(monkeypatch):
    monkeypatch.setattr(cuda_runtime, "_registered", False)


def _fake_nvidia_package(tmp_path, libs=("cublas", "cudnn")):
    for lib in libs:
        (tmp_path / lib / "bin").mkdir(parents=True)
    module = types.ModuleType("nvidia")
    module.__path__ = [str(tmp_path)]
    return module


def test_finds_wheel_dll_directories(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "nvidia", _fake_nvidia_package(tmp_path))
    found = {Path(p).parent.name for p in map(str, cuda_runtime._dll_directories())}
    assert found == {"cublas", "cudnn"}


def test_ignores_libraries_that_are_not_installed(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "nvidia", _fake_nvidia_package(tmp_path, ("cublas",)))
    dirs = cuda_runtime._dll_directories()
    assert len(dirs) == 1


def test_no_nvidia_package_is_not_an_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "nvidia", None)
    monkeypatch.delitem(sys.modules, "nvidia")

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "nvidia":
            raise ImportError("no nvidia")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    assert cuda_runtime._dll_directories() == []


def test_ensure_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "nvidia", _fake_nvidia_package(tmp_path))
    calls = []
    if hasattr(cuda_runtime.os, "add_dll_directory"):
        monkeypatch.setattr(cuda_runtime.os, "add_dll_directory",
                            lambda p: calls.append(p))
    monkeypatch.setattr(cuda_runtime.sys, "platform", "win32")

    cuda_runtime.ensure()
    first = len(calls)
    cuda_runtime.ensure()
    assert len(calls) == first, "second call must not re-register"


def test_reports_false_when_nothing_was_found(monkeypatch):
    monkeypatch.setattr(cuda_runtime.sys, "platform", "win32")
    monkeypatch.setattr(cuda_runtime, "_dll_directories", list)
    assert cuda_runtime.ensure() is False
