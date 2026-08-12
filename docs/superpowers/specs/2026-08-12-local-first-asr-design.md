# Local-first speech recognition

**Status:** implemented, with one open decision (GPU acceleration on unsupported
architectures — see the end).

## Why

WinWhispr's promise is offline dictation. The Groq path made it fast but broke
that promise: no network, no dictation, and every transcript left the machine.
The local path that existed was worse than the cloud on both counts — the
OpenVINO Cohere model took 3.6s on CPU and 1.2s on an iGPU for 8 seconds of
audio, and the local cleanup model took 3s to produce a wrong edit.

So: make local the default, fast enough to feel instant, accurate enough for
names and technical terms, on hardware ranging from a cheap laptop to a gaming
GPU.

## Decisions

| Question | Decision |
| --- | --- |
| Latency after releasing the key | Target under 300ms |
| Install size | Small base install; download only what the machine needs |
| Accuracy bar | English including Indian English, names, technical terms |
| Cloud | Kept, off by default, clearly labelled |
| Cleanup | Deterministic rules by default; the LLM is optional |

## The insight that makes it possible

Transcription used to start when the user released the key, so the wait grew
with how long they spoke — a 20 second thought cost four times a 5 second one.
That is the complaint behind "13.9 seconds for 7 words".

Now each voice-activity-closed segment is transcribed on a worker thread *while
the user is still talking*. At release only the trailing fragment remains. The
wait stops depending on utterance length and becomes the cost of a single
inference.

```
hold ──segment──segment──segment──┐ release
        │        │        │       │
        └────────┴────────┴───────┤  transcribed during the hold (free)
                                  └─ tail: one inference ── paste
```

## Components

| Unit | Purpose | Testable alone |
| --- | --- | --- |
| `core/asr/engine.py` | The seam: `transcribe`, `warmup`, `caps` | n/a (protocol) |
| `core/asr/tiering.py` | **Pure.** Hardware facts → model choice | yes, and tested |
| `core/asr/probe.py` | Reads the machine (CUDA, VRAM, cores) | no, deliberately thin |
| `core/asr/cuda_runtime.py` | Puts NVIDIA wheel DLLs on the Windows search path | yes |
| `core/asr/pipeline.py` | The pipelined session: order, tail, cancellation | yes, and tested |
| `core/asr/faster_whisper_engine.py` | CTranslate2 inference | no |
| `core/asr/{remote,openvino}_engine.py` | Groq and OpenVINO behind the same seam | no |
| `core/cleanup/deterministic.py` | **Pure.** Rules-only cleanup | yes, and tested |

Judgement lives in the pure modules; the untestable glue is kept small and dumb.

## Measurements

All on an i7-14650HX (24 threads) / RTX 5050 Laptop 8GB, int8 on CPU and
float16 on GPU, transcribing a real 6.8s utterance and a 2s tail.

| Model | Where | 2s tail | Meets 300ms? |
| --- | --- | --- | --- |
| tiny.en | CPU | 190ms | yes, but fails the accuracy bar |
| **base.en** | **CPU** | **~380ms** | close |
| small.en | CPU | 1184ms | no |
| base.en | RTX 5050 | 259ms | yes — but see below |
| small.en | RTX 5050 | 721ms | no |
| distil-large-v3 | RTX 5050 | 2802ms | no |

Two findings overturned the original design:

1. **Latency barely depends on audio length.** Whisper's encoder pads every
   input to a 30 second window: a 1s tail costs 191ms and a 6.8s clip 195ms on
   tiny.en. `chunk_length` does not change this — CTranslate2 encodes the full
   window regardless. Pipelining still pays, but the tail costs one whole
   inference, so the model choice decides whether the budget is met.
2. **More CPU cores do not buy a bigger model.** small.en costs ~1.3s on 24
   threads and ~1.2s on 8. The tiering table originally handed many-core
   machines small.en; measurement says base.en for everyone with 4+ threads.

## GPU support

CTranslate2 needs cuBLAS and cuDNN 9 at runtime. WinWhispr installs them as pip
wheels (`uv sync --extra cuda`) and registers their DLL directories before
CTranslate2 is imported — without that the model loads and then fails on the
first word with `cublas64_12.dll is not found`.

That fix works for every CUDA GPU **the library has kernels for**, which today
means compute capability 7.0 through 9.x (Turing, Ampere, Ada). It does not
include Blackwell (RTX 50 series, sm_120): int8 fails outright and float16 runs
through JIT-compiled PTX, measured *slower than the CPU*. `tiering.choose`
therefore treats such a GPU as unusable and says why, rather than silently
picking a path that is worse.

## Cleanup

Deterministic rules — fillers, stutters, spoken punctuation, capitalization —
run always, in microseconds, offline. They are not a "provider"; there is no
configuration in which cleanup does nothing. The LLM sits on top and is
optional, because the only thing it adds that rules cannot is judgement about
meaning (is "actually" a correction or an intensifier?).

Every fallback path — no provider, timeout, error, gate rejection — lands on
rules-only output. "Cleanup unavailable" still means clean text.

## Open decision

The 300ms target is met by `tiny.en` (too inaccurate) and by GPUs the library
supports. On a modern CPU, `base.en` lands at ~380ms — 27% over budget, and
still the best accuracy available inside half a second.

To do better on machines like the RTX 5050 the NVIDIA path needs a different
inference stack: whisper.cpp built against CUDA 12.8+, or ONNX Runtime with the
DirectML backend (which would also cover AMD and Intel GPUs on Windows). Both
are real work — a new engine, a new model format, more wheels — and neither is
started.
