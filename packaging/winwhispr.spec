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

# Only what the shipping path needs. The local speech model is not bundled:
# it pulled openvino, llvmlite, ctranslate2, av, scipy, onnxruntime, numba and
# sklearn behind it, about 580MB of an 815MB download, for an engine the app
# does not use. Anyone who wants it can run from source, where uv installs the
# lot in one command.
for _pkg in (
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

_hiddenimports += [
    "core.paths",
    "core.logging_setup",
    "core.hotkey_listener",
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
    "core.cleanup.deterministic",
    "core.web",
    "core.web.server",
    "core.web.bridge",
    "core.web.languages",
    "core.web.corrections",
    "core.web.keys",
    "core.web.pill_host",
    "core.web.session",
    "core.web.app_api",
    "desktop.tray",
    "webview",
    "core.web.paste",
    "core.autostart",
    "core.shortcuts",
    "core.updates",
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
    "core.dictionary.promotion",
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
    datas=_datas + [
        (os.path.join(_ROOT, "assets"), "assets"),
        # The running version, which the update check compares against the
        # latest release. Without it a packaged build has no idea how old
        # it is.
        (os.path.join(_ROOT, "VERSION"), "."),
        # The browser front end is served from disk at runtime, so its
        # static files have to travel with the executable.
        (os.path.join(_ROOT, "core", "web", "static"),
         os.path.join("core", "web", "static")),
    ],
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join(_PACKAGING_DIR, "hooks", "rthook_dll_dirs.py")],
    excludes=[
        # The local speech stack and everything it drags in. Excluded rather
        # than merely not imported, because a transitive import would pull
        # hundreds of megabytes back in without anyone noticing.
        "torch", "tensorflow", "transformers", "tkinter", "matplotlib",
        "openvino", "openvino_genai", "openvino_tokenizers",
        "faster_whisper", "ctranslate2", "onnxruntime",
        "librosa", "soundfile", "sounddevice", "av",
        "numba", "llvmlite", "scipy", "sklearn", "tokenizers",
        "huggingface_hub", "hf_xet", "pandas",
    ],
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
