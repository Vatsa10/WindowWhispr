# Third-party notices

## WhimprFlow

Parts of WinWhispr are a Python translation of logic from **WhimprFlow**, an
MIT-licensed Rust/Tauri dictation proof of concept. The behavior — not the
code — was carried over; every file below is a fresh Python implementation of
the corresponding Rust module.

| WinWhispr | Ported from |
| --- | --- |
| `core/cleanup/prompts.py` | `crates/whimpr-core/src/cleanup/prompts.rs` (system prompt, few-shot set, per-app formatting modes) |
| `core/cleanup/levels.py` | `crates/whimpr-core/src/cleanup/levels.rs` |
| `core/cleanup/gates.py` | `crates/whimpr-core/src/cleanup/gates.rs` |
| `core/cleanup/normalize.py`, `core/cleanup/__init__.py` | `crates/whimpr-core/src/cleanup/mod.rs` |
| `core/state/` | `crates/whimpr-core/src/state/` |
| `core/dictionary/__init__.py` | `crates/whimpr-core/src/dictionary/mod.rs` |
| `core/dictionary/autolearn.py` | `src-tauri/src/autolearn.rs` |
| `core/stats.py` | `crates/whimpr-core/src/stats.rs` |
| `core/diagnostics.py` | `crates/whimpr-core/src/diagnostics.rs` |
| `desktop/pill.py`, `desktop/waveform.py` | `ui/src/overlay/FlowBar.tsx` |

Their license, reproduced in full:

```
MIT License

Copyright (c) 2026 WhimprFlow contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Models

Speech and language models are downloaded at runtime from Hugging Face and are
covered by their own licenses. See the model table in `README.md`.
