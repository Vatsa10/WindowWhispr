# WinWhispr — Architecture

WinWhispr is a **native, single-process** Windows app: the PySide6 (Qt) window and
the background dictation engine share memory directly — no browser, WebView,
Node, Rust, IPC, or sidecar.

```
        ┌────────────────────────────────────────┐
        │         Native UI (PySide6 / Qt)        │   activity logger:
        │   dashboard · activity log · sidebar    │   dashboard + live log;
        │         system tray · dark theme        │   never a paste target
        └────────────────────┬───────────────────┘
                     in-process calls + Qt signals
        ┌────────────────────┴───────────────────┐
        │         Dictation engine (Python)       │──▶ Global hotkey (keyboard)
        │   sounddevice · Silero VAD · OpenVINO   │    keystroke/clipboard inject
        │         ASR · SQLite analytics          │    into the FOCUSED app
        └─────────────────────────────────────────┘
```

Everything runs in **one Python process**: the Qt window and the background
hotkey engine share memory directly. Engine callbacks (which fire on background
threads) are marshalled onto the UI thread with Qt signals.

## How it works

- WinWhispr runs **in the background** (system tray). You work in any app —
  Gmail, Chrome, Word, a text field — and press the **global hotkey**.
- Recognized text is injected **into whatever app currently has focus**
  (via clipboard paste, restoring your previous clipboard afterward). It is
  **never** shown or pasted onto WinWhispr's own window.
- The desktop window is a **logger**: it displays what happened — usage metrics
  and a live activity log of every dictation — plus the settings sidebar. It
  is read-only and does not capture your dictation focus.

## Pipeline (dictation)

```
key ─▶ state machine ─▶ AudioCapture ─▶ Silero VAD ─▶ ASR (OpenVINO) ─▶ cleanup ─▶ gates ─▶ paste + log
       hold/tap/lock    16k mono f32    speech segs      text           local LLM   pass?   focused app
                                                                                      └ fail ─▶ paste raw
```

Two commit modes:

- **buffered** (default) — the whole utterance is accumulated, cleaned once, and
  pasted once. Cleanup gates compare the *whole* raw text against the *whole*
  cleaned text, so per-chunk ratios would be meaningless; discard-on-cancel and
  auto-learn also need a single paste to exist at all.
- **stream** — each VAD-closed chunk is pasted as you speak, as WinWhispr worked
  before cleanup existed. Cleanup, cancel, and auto-learn are unavailable here.

ASR runs one of two ways. A **local** OpenVINO model transcribes each VAD-closed
segment as it completes. A **cloud** model (Groq Whisper large-v3, the default)
batches instead: audio accumulates for the whole session and goes up in a single
request when you release the key. Per-segment cloud calls would burn the request
allowance — 20/minute on the free tier — and throw away the context that makes a
large model worth calling. Sessions longer than the upload limit are split into
sequential chunks by `core/groq_client.py`.

**Cleanup is an enhancement, never a gate.** A provider error, a timeout, an
empty result, or any gate rejection all end the same way: the user's raw words
get pasted. Gate rejections are logged with their reason so the per-level
thresholds can be tuned against real dictation rather than guesses.

## State machine

`core/state/machine.py` is a pure `step(event) -> [action]` reducer — no clock,
no microphone, no keyboard hook. Time arrives as `Tick`, key events as
`Down`/`Up`/`Cancel`. That makes hold-vs-tap, double-tap-to-lock, cancel,
cooldown, and the session cap fully unit-testable, and it keeps the keyboard
hook callback free to do nothing but enqueue an event — anything slow there
stalls system-wide keyboard input.

## Repository layout

```
WinWhispr/
  main.py                   Entry point: native app (default) · headless · setup
  config.json               Persisted user configuration (source runs)
  pyproject.toml            Python package + dependencies
  packaging/                Everything packaging-related (single entry point)
    build.ps1               Build the app bundle + optional installer
    winwhispr.spec             PyInstaller bundle definition
    hooks/rthook_dll_dirs.py  PyInstaller runtime hook (native DLL search paths)
    installer/winwhispr.iss    Inno Setup installer script
  assets/                   App icon (winwhispr.png / winwhispr.ico)
  desktop/                  Native PySide6 UI (the app)
    main_window.py          Window: sidebar · dashboard · activity log · tray
    pill.py                 Floating always-on-top status pill
    waveform.py             Dot-bar level display inside the pill
    widgets.py              Metric cards, collapsible sections, note cards
    theme.py                Dark Qt stylesheet + palette
  core/
    paths.py                Centralized data/asset path resolution
    config_store.py         Shared config load/save (versioned, atomic writes)
    hotkey_listener.py      Global hooks · state-machine driver · commit path
    processor.py            AudioCapture · Silero VAD · OpenVINO ASR pipeline
    audio_meter.py          Mic frames → level bars for the pill
    groq_client.py          Groq Whisper + chat over urllib (no SDK)
    secrets.py              API keys in Windows Credential Manager
    reformatter.py          OpenVINO GenAI LLM (clipboard reformat + cleanup)
    diagnostics.py          User-facing copy for every failure mode
    stats.py                Usage aggregation (WPM, streak, time saved)
    commands.py             Trailing spoken commands ("…press enter")
    snippets.py             Text expansion
    autostart.py            Run-at-login registry toggle
    state/                  Pure dictation state machine (hold · lock · cancel)
    cleanup/                Prompts · levels · gates · normalization · provider
    dictionary/             Personal dictionary · similarity · auto-learn
    model_manager.py        First-run model download/verify
    model_registry.py       Display-name → registry-ID mapping
    speaker.py              Speaker-enrollment WAV recorder
  database/
    db_manager.py           SQLite logging (words, duration, time saved, notes)
    migrations.py           PRAGMA user_version schema migrations
  tests/                    pytest suite over the pure modules
```

## Testing

`uv run --extra dev pytest`. Everything under `tests/` is pure logic — no
PySide6, no `keyboard`, no `sounddevice`, no models — so the suite runs
anywhere. The gate, normalization, dictionary, auto-learn, state-machine, and
stats tests are ported assertions: they define the behavior, not just cover it.

## Runtime data location

All writable runtime data lives under `%USERPROFILE%\.cache\winwhispr` (never in a
synced folder): downloaded models, the OpenVINO compile cache, `config.json`,
`app_metrics.db`, `dictionary.json`, `snippets.json`, and speaker samples. When running from a source checkout,
pre-existing in-repo `.models/`, `config.json`, and `app_metrics.db` are reused
if present.
