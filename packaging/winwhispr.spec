# PyInstaller spec for WinWhispr (native PySide6 app + dictation engine).
#
# Do not run this file directly -- use packaging\build.ps1, which is the only
# entry point for building WinWhispr (handles the venv, PyInstaller, and the
# optional Inno Setup installer in one command).
#
# Produces a one-directory bundle at dist/WinWhispr/ with WinWhispr.exe.
# Models are NOT bundled: they download + compile into ~/.cache/winwhispr on first
# run (or via "WinWhispr.exe setup"), which the installer triggers post-install.

import os

from PyInstaller.utils.hooks import collect_all

block_cipher = None

# SPECPATH (injected by PyInstaller) is this file's folder: packaging/.
_PACKAGING_DIR = os.path.abspath(SPECPATH)
_ROOT = os.path.dirname(_PACKAGING_DIR)

# Heavy native packages whose data files, DLLs and hidden imports PyInstaller's
# static analysis alone does not fully capture.
_datas = []
_binaries = []
_hiddenimports = []

for _pkg in (
    "openvino",
    "openvino_genai",
    "openvino_tokenizers",
    "onnxruntime",
    "librosa",
    "soundfile",
    "sounddevice",
    "tokenizers",
    "numba",
    "llvmlite",
    # UI Automation bindings for auto-learning dictionary entries. comtypes
    # generates its wrappers at runtime into paths.data_dir(), because the
    # default location inside a frozen bundle is read-only.
    "comtypes",
    "keyring",
):
    try:
        d, b, h = collect_all(_pkg)
        _datas += d
        _binaries += b
        _hiddenimports += h
    except Exception:
        pass

# huggingface_hub powers snapshot_download() for first-run model fetching.
for _pkg in ("huggingface_hub",):
    try:
        d, b, h = collect_all(
            _pkg, include_py_files=False, exclude_datas=["**/*.pt", "**/*.h5"]
        )
        _datas += d
        _binaries += b
        _hiddenimports += h
    except Exception:
        pass

_hiddenimports += [
    "core.paths",
    "core.logging_setup",
    "core.processor",
    "core.reformatter",
    "core.hotkey_listener",
    "core.model_manager",
    "core.model_registry",
    "core.config_store",
    "core.active_window",
    "core.speaker",
    "core.diagnostics",
    "core.cleanup",
    "core.cleanup.gates",
    "core.cleanup.levels",
    "core.cleanup.normalize",
    "core.cleanup.orchestrator",
    "core.cleanup.prompts",
    "core.cleanup.provider_local",
    "core.autostart",
    "core.commands",
    "core.groq_client",
    "core.secrets",
    "core.cleanup.provider_groq",
    # keyring finds its backends through entry points, which PyInstaller's
    # static analysis cannot see; without these the credential store silently
    # has no backend in the frozen build.
    "keyring.backends.Windows",
    "keyring.backends.null",
    "win32ctypes.core",
    "win32ctypes.pywin32.win32cred",
    "core.snippets",
    "core.stats",
    "core.dictionary",
    "core.dictionary.autolearn",
    "core.dictionary.observer_win",
    "core.dictionary.similarity",
    "core.state",
    "core.state.actions",
    "core.state.events",
    "core.state.machine",
    "core.state.timing",
    "database.db_manager",
    "database.migrations",
    "core.audio_meter",
    "desktop.main_window",
    "desktop.pill",
    "desktop.theme",
    "desktop.waveform",
    "desktop.widgets",
    "keyboard",
    "pyperclip",
]

a = Analysis(
    [os.path.join(_ROOT, "main.py")],
    pathex=[_ROOT],
    binaries=_binaries,
    datas=_datas + [(os.path.join(_ROOT, "assets"), "assets")],
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join(_PACKAGING_DIR, "hooks", "rthook_dll_dirs.py")],
    excludes=["torch", "tensorflow", "transformers", "tkinter", "matplotlib"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WinWhispr",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowed app (no console)
    disable_windowed_traceback=False,
    icon=os.path.join(_ROOT, "assets", "winwhispr.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="WinWhispr",
)
