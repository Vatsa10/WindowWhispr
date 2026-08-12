# Which model should I use?

Measured on the developer's machine (Intel iGPU, Windows 11) with the real
cleanup prompt, on the sentence:

> *"um so i think we should uh meet at 2 actually 3 period does that work
> question mark"*

Correct output is `So I think we should meet at 3. Does that work?` — filler
removed, the spoken self-correction resolved (2 → 3), spoken punctuation
applied, and the question **not** answered.

## Cleanup model

| Model | Where | Latency (median) | Got it right? |
| --- | --- | --- | --- |
| **`llama-3.3-70b-versatile`** | Groq | **~0.3s** | yes |
| `openai/gpt-oss-20b` | Groq | ~0.9s | yes |
| `openai/gpt-oss-120b` | Groq | ~0.9s | yes |
| `LFM2.5 350M` (int8) | local, CPU | ~3.1s | **no** — kept the filler, mangled the correction |
| `LFM2.5 350M` (int8) | local, iGPU | ~3.1s | **no** — same |
| `Qwen2.5-1.5B Instruct` (int4) | local, iGPU | ~6.1s | yes |

**Default: `llama-3.3-70b-versatile` on Groq.** It was both the fastest and
correct. Cleanup sits between you releasing the key and the text appearing, so
latency here is latency you feel on every single dictation.

**If you want everything on-device**, use `Qwen2.5-1.5B Instruct` and expect to
wait ~6s per dictation, or set cleanup to **None** and paste the raw
transcript instantly. `LFM2.5 350M` is fast to load but too small for this task
— it fails the self-correction case, and the safety gates then reject its
output and paste raw anyway, so you pay 3 seconds for nothing.

Change it in the sidebar: **Cleanup → "Cleanup runs on"**, and
**Reformatter (LLM)** for which local model.

## Speech-to-text

| Model | Where | Notes |
| --- | --- | --- |
| **`whisper-large-v3`** | Groq | Default. Nothing to download, one request per dictation. |
| `whisper-large-v3-turbo` | Groq | Faster, slightly less accurate. Not wired up yet. |
| `Aditya02/cohere-transcribe-03-2026-ov-fp16` | local | 4.4 GB download, runs on the iGPU. |
| `OpenVINO/whisper-large-v3-int4-ov` | local | INT4 Whisper via OpenVINO GenAI. |

## Groq free-tier limits

The published limit people quote is 20 requests/minute, but the one you
actually hit first is **8000 tokens per minute**. The cleanup prompt is roughly
1000 tokens, so that is about **6–8 dictations a minute** before Groq asks you
to wait a moment. WinWhispr sends the full demonstration set only to local
models; hosted models get a trimmed prompt, which buys back some headroom.

Transcription is billed by audio, not tokens, so speech-to-text is not what
runs you into the ceiling.

## If Groq stops working

- **"Request blocked before Groq"** — something between you and Groq refused
  the request (VPN, proxy, network filtering). Your key is fine.
- **"Groq rate limit reached"** — the tokens-per-minute ceiling above. Wait, or
  switch cleanup to a local model.
- Model IDs change. `llama-3.3-70b-versatile` is current as of August 2026, but
  Groq deprecates models with notice; if it disappears, `openai/gpt-oss-20b` is
  the closest replacement. Set it in the sidebar under Cleanup.
