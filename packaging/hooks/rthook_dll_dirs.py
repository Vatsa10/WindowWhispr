"""PyInstaller runtime hook: register every bundled folder with DLLs so
Windows' dependent-DLL loader can resolve cross-folder native dependencies.

Root cause this fixes: packages like ``openvino_tokenizers`` place their DLL
under ``<pkg>/lib/`` while the DLLs it depends on (``openvino.dll``,
``tbb12.dll`` under ``openvino/libs/``) live in a sibling package folder.
Windows' default dependent-DLL search only checks the loading DLL's own
directory, System32, the executable's directory, and PATH -- NOT arbitrary
sibling folders inside PyInstaller's ``_internal`` tree. Without this, native
extensions raise "Cannot load library ...: 126" (module not found) even
though every file is actually present in the bundle.

Must run before any of those native libraries are imported, which is why it's
registered as a PyInstaller ``runtime_hook`` (executed at process bootstrap).
"""

import os
import sys

if sys.platform == "win32":
    _base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    for _root, _dirs, _files in os.walk(_base):
        if any(f.lower().endswith(".dll") for f in _files):
            try:
                os.add_dll_directory(_root)
            except (OSError, AttributeError):
                pass
