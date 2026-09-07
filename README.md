# WinWhispr

WinWhispr is offline dictation for Windows. Hold a key, speak, and your words
are typed into whatever application has focus.

It comes two ways:

- **A desktop app** that lives in the system tray, transcribing on this machine
  with Whisper. Nothing leaves the computer.
- **A browser page** you can open from your phone or another laptop, which uses
  the browser's own speech engine where it has one. See
  [Dictate from a browser](#dictate-from-a-browser).

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the internal design.

## Features

- **Standalone native Windows app** — PySide6 (Qt) desktop window, dark theme.
  No browser, no WebView, no web toolchain.
- **System tray + collapsible settings sidebar**; runs in the background.
- **Two keys, that's it**: hold **`Right Ctrl`** and speak, let go and your
  words appear. **`Esc`** throws the recording away. (Tap-twice-to-lock and a
  press-on/press-off combo exist too, both off by default.)
- **Floating status pill** near the bottom of the screen — a live waveform while
  recording, "Cleaning up…" while it thinks, and the specific problem when
  something goes wrong.
- Microphone capture at 16 kHz, mono, `float32`.
- Voice-activity chunking with **Silero VAD** (ONNX).
- **Speech-to-text sized to your machine.** The default inspects the hardware
  and picks a local Whisper model, then measures it and drops to a smaller one
  if it is too slow. Cloud (Groq) is available but off by default. See
  [Supported models](#supported-models).
- **Automatic cleanup** of the finished transcript by a local LLM: fillers gone,
  spoken self-corrections resolved ("meet at 2, actually 3" → "3"), spoken
  punctuation and lists applied, tone matched to the app you are typing into.
  Four levels (None / Light / Medium / High); Light is the default.
- **Deterministic safety gates** on every cleanup: if the model answers your
  dictation, drops a phone number or URL, deletes too much, or rewrites past the
  level's limit, WinWhispr pastes your **raw words** instead. Cleanup can only
  improve the text — it can never lose it.
- **Personal dictionary** for names and terms recognition keeps missing, used as
  a spelling authority rather than a blind find-and-replace. It can optionally
  **learn a name** when you correct one right after pasting (off by default).
- **Snippets** (say a trigger, paste a block) and trailing spoken commands
  ("…press enter").
- Injects recognized text into **whatever app currently has focus** and logs it.
- Optional **clipboard reformatter** — a small local LLM cleans up selected text
  on a second hotkey (`Ctrl+Alt+R`).
- **Paste / copy the last transcript** again with `Ctrl+Alt+V` / `Ctrl+Alt+C`.
- Usage analytics in SQLite — words dictated, words per minute (and your best),
  day streak, and time saved versus typing — plus a searchable activity log.
- **Can run fully offline** — pick the local ASR model and local cleanup, and
  nothing leaves the machine after the one-time model download.
- **Reset all data** button in the sidebar to wipe usage metrics and the
  activity log.

## Dictate with the browser's speech engine

```powershell
uv run python main.py listen
```

Hold **`Right Ctrl`** in any application, speak, let go — the words are typed
at your cursor. Nothing to download and no model to load, so it is ready the
moment it starts.

The recognizer is Edge's, running in a small always-on-top pill at the bottom
of the screen. Approve the microphone once, on the pill, and it is remembered.
Set the language once in **Dictation language** in the sidebar; it is picked up
without a restart.

The pill is a lozenge the width of a word while it waits, grows while you
speak, and shrinks again once the words have been typed. Right-click it to
quit; drag it anywhere you prefer.

> It stays on screen on purpose. Chromium freezes the renderer of a window
> that is hidden or off-screen, and a frozen renderer hears nothing —
> measured: neither produced so much as an `onstart`. Small is the answer;
> hidden is not available.

To have it running whenever you are, tick **Start WinWhispr with Windows** in
the sidebar and set the dropdown under it to **Start browser dictation**. It
stays up until you quit it from the pill.

Two things to know before choosing this over the local model: the audio goes to
Microsoft's speech service, so this mode is not offline; and it needs the
WebView2 runtime, which ships with Windows 11 and installs with Edge on
Windows 10.

```powershell
uv run python main.py listen --key "f13"    # a different talk key
uv run python main.py listen --no-window    # use your own browser tab instead
```

## Dictate from a browser

```powershell
uv run python main.py web              # this machine only
uv run python main.py web --lan        # reachable from your phone
uv run python main.py web --lan --allow-paste
```

Open the printed address. One button: tap, talk, pause. The words appear.

**Chrome, Edge and Safari transcribe in the browser itself** — their speech
engine returns a transcript the instant you stop talking, with nothing to
download and no model running on your PC. That is the fast path, and it is the
default wherever the browser provides it. Firefox has no such engine, so the
page records, detects the pause itself, and sends one WAV to the Whisper model
already running on your PC. Either way the audio stays on your network.

The transcript then goes through the same cleanup the desktop app uses: fillers
and stutters gone, spoken punctuation applied, sentences capitalized, snippets
expanded.

Two switches on the page:

- **Keep listening** — after each pause it re-arms, so a pause to think does not
  end the session. On by default.
- **Type on PC** — every finished sentence is typed into whatever window has
  focus on the PC. Dictate from the sofa, watch it land in the document.
  Requires `--allow-paste`.

`--lan` prints an access token, and the page asks for it once. That route types
into your machine, so a private network is not treated as a trusted one.

## How to use

1. Install WinWhispr (see [Installation](#installation)) and let the first-run
   setup download + optimize the models — see [Supported models](#supported-models)
   below to choose which ones.
2. WinWhispr starts minimized to the **system tray**. Put focus in any app (Gmail,
   Chrome, Word, a text box).
3. **Hold `Right Ctrl`**, say your sentence, and let go. The pill shows a
   waveform while you speak and "Cleaning up…" while WinWhispr tidies the
   transcript; the finished text is pasted at your cursor. Press `Esc` while
   recording to discard it.

   That is the whole thing. Two optional extras live in **Dictation keys** if
   you want them: *tap twice to keep recording* (hands-free, no holding), and a
   *press-on / press-off combo* like the old `Ctrl+Shift+Space`. Both are off by
   default so there is only ever one way to start.

   > Using a keyboard layout with **AltGr**? Windows sends a fake Ctrl with it.
   > Change the talk key to `f13` or `right alt` in **Dictation keys**.
4. Select text anywhere and press `Ctrl+Alt+R` to **reformat** it with the local
   LLM. Open the WinWhispr window to see analytics, the searchable activity log,
   and the settings sidebar (cleanup level, dictionary, dictation keys,
   microphone, models, VAD sensitivity).

If you want text to appear live as you speak instead of once at the end, turn on
**“Type as I speak”** in the Cleanup section — cleanup needs the whole sentence,
so it is skipped in that mode.

Settings persist to `config.json`; analytics persist in `app_metrics.db`; the
dictionary and snippets live in `dictionary.json` and `snippets.json` — all
under `%USERPROFILE%\.cache\winwhispr`.

> The `keyboard` library may need Administrator rights for global hooks in some
> apps. Run WinWhispr as Administrator if the hotkey is blocked in an elevated app.


## Cloud (Groq)

Speech-to-text runs locally by default. Groq is there for machines too slow for
a local model, and needs a free [Groq API key](https://console.groq.com/keys).

Paste it into the **Cloud (Groq)** section of the sidebar. It goes into
**Windows Credential Manager**, never into `config.json`. For development, the
`GROQ_API_KEY` environment variable works too.

WinWhispr sends **one request per dictation** — the whole utterance is uploaded
once when you release the key, rather than one request per pause. The free tier
allows 20 requests a minute and 2000 a day; turning cleanup on Groq as well
makes it two requests per dictation.

Prefer to stay offline? Pick `Cohere-transcribe` or `Whisper Large` in the ASR
Model section and leave cleanup on "This machine" — nothing leaves the
computer, at the cost of a one-time download.

## Supported models

Local models are pre-optimized **OpenVINO IR** and download on first run (or via
`WinWhispr.exe setup`) into `%USERPROFILE%\.cache\winwhispr`.

### Speech-to-text (ASR)

| Display name                 | Runs on | Notes |
| ---------------------------- | ------- | ----- |
| `Automatic (recommended)`    | This machine | **Default.** Picks a model to fit the hardware, then verifies it by measurement |
| `Whisper Base (local, fast)` | This machine | ~380ms per utterance on a modern CPU |
| `Whisper Small (local, accurate)` | This machine | ~1.2s, better on names |
| `Whisper Tiny (local, fastest)`   | This machine | ~190ms, weakest on proper nouns |
| `Groq Whisper Turbo`         | Groq | Needs an API key; the transcript leaves the machine |
| `Cohere-transcribe`          | This machine | OpenVINO FP16, 4.4 GB |
| `Whisper Large`              | This machine | OpenVINO INT4 |

### Clipboard reformatter (LLM)

| Display name             | Registry ID                                 | Precision |
| ------------------------ | ------------------------------------------- | --------- |
| `LFM2.5 350M`            | `OpenVINO/LFM2.5-350M-int8-ov`              | INT8      |
| `Qwen2.5-1.5B Instruct`  | `OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov`    | INT4      |
| `TinyLlama 1.1B Chat`    | `OpenVINO/TinyLlama-1.1B-Chat-v1.0-int4-ov` | INT4      |
| `Phi-3 Mini Instruct`    | `OpenVINO/Phi-3-mini-4k-instruct-int4-ov`   | INT4      |

### Voice activity detection

- **Silero VAD** (ONNX) — auto-downloaded to `.cache/winwhispr/vad/silero_vad.onnx`.

## Installation

### Option 1 — Download the installer

No release is published yet — build from source for now. Once one exists, the
installer is **per-user (no admin)**: it adds a Start Menu entry, optionally a
login **Startup** shortcut (background tray), and — when the *first-run setup*
task is selected — downloads and optimizes the models.

### Option 2 — Build from source

**Prerequisites**

- **Python 3.10+**
- [`uv`](https://docs.astral.sh/uv/) (package / venv manager)
- [Inno Setup 6](https://jrsoftware.org/isinfo.php) — only needed to build the
  installer (2b)

**Clean setup**

```powershell
git clone https://github.com/Vatsa10/WindowWhispr.git
cd WindowWhispr
uv venv
uv sync
```

**Run directly from source** (no packaging):

```powershell
uv run winwhispr                   # native desktop app (default)
uv run python main.py headless  # engine only, no window
uv run python main.py setup     # download + optimize models, then exit
```

**2a. Build the standalone app bundle**

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Produces `dist\WinWhispr\WinWhispr.exe` — a portable one-directory bundle you can zip
and copy to another machine.

**2b. Build the installer**

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Installer
```

Produces `packaging\installer\Output\WinWhispr-Setup-<version>.exe`. The script
auto-detects `ISCC.exe` from a machine-wide or per-user Inno Setup install.

> Models are **not** bundled. They download and are optimized (device-specific
> OpenVINO compile) on the target machine into `%USERPROFILE%\.cache\winwhispr`.

## Supported hardware (Windows on Intel AI PC)

WinWhispr runs entirely on **OpenVINO**, so it targets Intel AI PCs end to end:

- **OS:** Windows 10 / 11, x86-64.
- **CPU:** any modern Intel Core (used by default for the reformatter LLM, and as
  the automatic fallback for ASR).
- **GPU:** Intel Arc / Iris Xe integrated or discrete GPU (default device for
  ASR; falls back to CPU when no GPU is present).
- **NPU:** Intel Core Ultra (Meteor Lake / Lunar Lake / Arrow Lake) AI PCs —
  selectable as an OpenVINO device where supported.

Device selection is configurable per model (`asr_device`, `llm_device`) with
`AUTO` and CPU fallback, so WinWhispr works across the full Intel AI PC lineup.

## Logs

WinWhispr writes a rotating debug log to
`%USERPROFILE%\.cache\winwhispr\logs\winwhispr.log` (kept for both source and
installed runs). It captures startup, model load/compile, and any errors —
check it first if the engine fails to start or the UI behaves unexpectedly.

## Development

```powershell
uv run --extra dev pytest
```

Everything under `tests/` is pure logic — no Qt, no keyboard hooks, no
microphone, no models — so the suite runs anywhere in under a second. The
cleanup gates, layout normalization, dictionary matching, auto-learn filters,
dictation state machine, and stats maths all have tests that define the
behavior rather than merely cover it. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the internal design.

## Credits

The transcript cleanup design — the prompt, the few-shot set, the deterministic
gates, the push-to-talk state machine, the dictionary prefilter, and the
overlay pill — is a Python translation of logic from **WhimprFlow**, an
MIT-licensed Rust/Tauri dictation proof of concept. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the file-by-file mapping
and the original license.

## License

MIT — see [LICENSE](LICENSE).
