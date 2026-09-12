# STT Quality: hallucination, accent, code-switching, names, learning

Date: 2026-09-12
Status: approved, ready for implementation planning

## Problem

Five recurring speech-to-text failures, reported against the shipping app:

1. **Hallucination.** Transcripts contain words nobody said — canonically
   "thank you for watching" and similar YouTube-caption residue from Whisper's
   training data.
2. **Accent bias.** Accented English is transcribed poorly, and sometimes
   transcribed *into the accent's language* — English spoken with a Russian
   accent coming back as Russian text.
3. **Code-switching.** One sentence containing two languages is forced into
   one language.
4. **Name spelling.** "Shaun" vs "Sean" cannot be recovered from audio, and the
   app has no memory that makes the choice once and keeps it.
5. **No learning.** The user corrects the same misspelling repeatedly and the
   app makes the same mistake again.

## Decisions taken

| Question | Decision |
|---|---|
| Which engine | Both: local faster-whisper gets real fixes, browser gets the post-hoc subset |
| Multilingual model | Declared language **pair** (one primary + one optional secondary), never open-ended detection |
| Dual-language cost | Detect-then-decode-once (`detect_language` per segment, clamp to pair) |
| Learning visibility | Silent promotion, passively logged in the dictionary UI as `source=auto`, removable |

## Non-goals (explicitly out of scope for v1)

- **Cleanup-diff learning.** Mining repeated raw-vs-cleaned rewrites from the
  cleanup model as a second correction corpus. Richer signal, separate failure
  modes, deferred.
- **Low-confidence re-decode escalation.** Re-decoding a segment in the other
  declared language when the first decode returns poor `avg_logprob`. Deferred
  until real logprob distributions exist to threshold against; guessing the
  threshold today produces an untunable knob. This spec adds the logging that
  makes it thresholdable later.
- **Prefilter at decode time.** `DictionaryStore.prefilter()` needs an
  utterance to filter against, which does not exist before decoding. It stays
  in use for cleanup only. See §5b.
- **Browser parity.** Accent and code-switching fixes are impossible against
  `SpeechRecognition`. The UI states this rather than implying parity.

## Verified environment facts

- `faster-whisper` pinned at **1.2.1** (`uv.lock`), declared `>=1.0.0`.
- `WhisperModel.detect_language(audio=None, features=None, vad_filter=False,
  vad_parameters=None, language_detection_segments=1,
  language_detection_threshold=0.5) -> tuple[str, float, list[tuple[str, float]]]`
  is present and confirmed. The third element is the full per-language
  probability list §4 clamps against.

---

## 1. Engine seam: segments, not a bare string

**Problem this solves:** `AsrEngine.transcribe(audio) -> str` discards
`avg_logprob` and `no_speech_prob`. Every fix below needs those signals. This is
the architectural blocker and must land first.

In `core/asr/engine.py`:

```python
@dataclass(frozen=True)
class Segment:
    text: str
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0
    language: str = ""

class AsrEngine(Protocol):
    caps: EngineCaps
    def warmup(self) -> None: ...
    def transcribe(self, audio) -> str: ...
    def transcribe_rich(self, audio) -> list[Segment]: ...
```

Contract: `transcribe()` returns the space-joined, stripped text of
`transcribe_rich()`. Engines that cannot supply confidence return a single
`Segment` carrying the text and default scores — which is neutral against every
threshold in §2, so they behave exactly as today.

**Blast radius is deliberately near zero.** `core/asr/pipeline.py`,
`core/processor.py`, and `core/web/server.py` keep calling `transcribe()` and
are untouched. `remote_engine.py` and `openvino_engine.py` get the trivial
single-segment implementation. Only `FasterWhisperEngine` implements
`transcribe_rich` for real.

## 2. Hallucination

Three independent guards, cheapest first. Each is separately defensible; none
depends on another being correct.

### 2a. Gain ceiling

`core/asr/faster_whisper_engine.py:_normalize_peak` currently scales any
non-silent buffer to 0.95 peak. A room-tone segment whose peak is 0.02 gets
amplified ~47x, and Whisper reliably invents speech in amplified noise. This is
the single largest hallucination contributor in the current code.

```python
MAX_GAIN = 8.0  # ponytail: flat ceiling, not a compressor. Revisit if quiet mics regress.

peak = float(np.abs(audio).max()) if len(audio) else 0.0
if peak < 1e-4:
    return audio
gain = min(TARGET_PEAK / peak, MAX_GAIN)
return (audio * gain).astype(np.float32, copy=False)
```

The existing silence short-circuit stays. Genuinely quiet speech still gets up
to 8x, which covers a low mic; only noise floors get clamped.

### 2b. Decode thresholds

Passed to `model.transcribe()`, letting faster-whisper discard its own bad
segments:

```python
no_speech_threshold=0.6,
log_prob_threshold=-1.0,
compression_ratio_threshold=2.4,
```

`compression_ratio_threshold` is specifically the repetition-loop guard: a
segment that degenerates into repeated text compresses far better than natural
speech and is rejected.

### 2c. Phrase blocklist

New module `core/asr/hallucination.py`, backed by a plain data file shared with
the browser path. Contents are Whisper's known training-data residue:
"thank you for watching", "thanks for watching", "please subscribe",
"subtitles by", "amara.org", music glyphs, and similar.

**This is not an unconditional string filter.** A user genuinely saying "thanks
for watching" must survive. The gate:

```python
def is_hallucinated(segment) -> bool:
    return (normalize(segment.text) in BLOCKLIST
            and segment.no_speech_prob > 0.4)
```

A real utterance of a blocklisted phrase carries low `no_speech_prob` and
passes. A phrase invented over silence carries high `no_speech_prob` and is
dropped.

**Browser variant:** no confidence signal exists, so the browser path drops a
blocklisted phrase only when it is the *entire* transcript — the case where
there is nothing to lose. Mid-transcript occurrences are always kept.

## 3. Accent

Decode parameters only; no new module.

```python
temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
beam_size=5 if self._choice.device == "cuda" else 1,
```

The temperature ladder is inert until one of the §2b thresholds trips, so clean
speech costs nothing — only segments that were already going to be wrong pay
for retries. This is why §2b must land with §3 and not after it: without the
thresholds, the fallback ladder never triggers.

Beam 5 on GPU is affordable against the warmup budget already measured by
`core/asr/tiering.py`. CPU stays greedy, reusing the existing device decision
rather than adding a user-facing knob.

Note `language` is currently hardcoded `"en"` at
`faster_whisper_engine.py:226`. That hardcoding is what prevents
Russian-accented English from being emitted as Russian today, and §4 must
preserve that protection rather than regress it.

## 4. Code-switching

New module `core/asr/decode_policy.py`.

### Configuration

Two new keys in `core/config_store.py`:

- `asr_language_primary` — default `"en"`
- `asr_language_secondary` — default `""` (off)

**Secondary empty means a hard language pin, byte-identical to today's
behavior.** Existing users take on no new risk and see no change unless they
opt in.

### Per-segment resolution

When a secondary is declared, per VAD segment:

```python
DETECT_FLOOR = 0.6

def resolve(model, audio, primary: str, secondary: str) -> str:
    if not secondary:
        return primary
    _lang, _prob, all_probs = model.detect_language(audio=audio)
    probs = dict(all_probs)
    candidates = {primary: probs.get(primary, 0.0),
                  secondary: probs.get(secondary, 0.0)}
    best = max(candidates, key=candidates.get)
    if candidates[best] < DETECT_FLOOR:
        return primary          # short or noisy segment: do not gamble
    return best
```

Two properties matter and must be preserved by any refactor:

- **Clamping to the declared pair is what fixes problem 2 even with
  multilingual on.** Russian is never a candidate unless the user declared it.
  Open-ended detection would reintroduce the exact bug this spec closes.
- **The floor biases toward primary on doubt, asymmetrically and on purpose.**
  Wrong-language output is far more damaging to the user than a missed switch.

Cost is one encoder-only pass over ~30 frames per segment, ~1.1x total, mostly
hidden behind the existing pipelined worker in `core/asr/pipeline.py`.

### Logging for the deferred escalation

Every segment logs its resolved language, detection probability, and resulting
`avg_logprob` at debug level. This is the dataset that makes the deferred
re-decode escalation thresholdable later.

## 5. Name spelling

Two genuine wiring bugs and one deliberate non-change.

### 5a. Cap hotwords by usage

`core/web/server.py:404` and `core/hotkey_listener.py:459` push *every*
dictionary entry as hotwords. Past roughly 15 terms, hotword bias measurably
dilutes — `MAX_VOCAB = 15` already exists in `core/dictionary/__init__.py` and
documents exactly this.

`DictionaryEntry` gains a `uses: int = 0` counter, incremented when an entry's
spelling appears in a committed transcript. Both call sites rank by `uses`
descending and take `MAX_VOCAB`, so the names actually spoken hold the slots.

### 5b. `prefilter()` stays out of the decode path

It is not dead code to revive: it requires an utterance to filter against,
which by definition does not exist before decoding. Reviving it pre-decode
would require a two-pass decode, which is out of proportion to the gain. The
frequency cap in 5a is the correct fix. `prefilter()` remains live for cleanup,
where the utterance does exist.

### 5c. Mishears stay out of the decoder

Mishears must never enter `hotwords` or `initial_prompt`: feeding "Monvi" to
the decoder biases it toward producing the mistake. They belong only in
post-hoc `core/web/corrections.py` and in the cleanup spelling-authority block,
where they already are. Any future change here should re-read this section
first.

### 5d. On "Shaun" vs "Sean"

Unrecoverable from audio; the waveform does not carry the information, and no
model or parameter recovers it. It is solved by §6 learning the spelling once
and §5a biasing toward it from then on. The spec states this so the limitation
is not mistaken for an implementation defect.

## 6. Learning

New module `core/dictionary/promotion.py` plus a widening of
`core/dictionary/autolearn.py`.

### Pending store

Sidecar `pending.json` next to the dictionary:

```json
{"pending": [{"mishear": "Monvi", "correct": "Manvi", "count": 1,
              "last_seen": "2026-09-12T10:00:00Z"}]}
```

Same durability rules as `DictionaryStore`: atomic replace via tempfile, and a
corrupt or missing file never blocks dictation.

### Widened detection

`autolearn.detect_correction` is currently too narrow to fire in practice:

- **Drop the `correct[0].isupper()` requirement.** It currently blocks every
  lowercase technical term outright. Replace with: rejected if in `STOPLIST` or
  in a common-English-word list.
- **Allow 1→2 and 2→1 token swaps**, not strictly 1→1. This is what catches
  "charge bee" → "ChargeBee", the exact case the dictionary module's own
  docstring is written around.

Existing guards stay: minimum word length, alphabetic-only, case-only edits
rejected, and the `MAX_DISTANCE` similarity bound.

### Promotion rule

- Each detected correction increments `count` for its `(mishear, correct)` pair.
- At **`count >= 2`**, promote into `DictionaryStore` with
  `source=SOURCE_AUTO`, then clear the pending row.
- Pending rows expire after **30 days**, so an isolated typo never accumulates
  into a promotion.
- Promoted entries appear in the existing dictionary UI tagged `auto` and are
  removable. No prompt, no interruption.

This converts "fix it three times, still wrong" into "fix it twice, never
again". The `source=SOURCE_AUTO` constant and the UI surface already exist.

### Platform note

The before/after signal comes from `core/dictionary/observer_win.py`, which is
Windows-only. `promotion.py` and the widened `autolearn.py` are pure logic with
no platform dependency, so a future observer on another platform needs no
change here.

## 7. Testing

Assert-based, one file per new module, no fixtures or frameworks beyond the
existing pytest setup.

- **`test_hallucination.py`** — blocklisted phrase at high `no_speech_prob` is
  dropped; the same phrase at low `no_speech_prob` is kept; gain ceiling caps
  amplification on a room-tone buffer; the silence short-circuit still returns
  audio untouched.
- **`test_decode_policy.py`** — empty secondary is a hard pin on primary;
  detection above the floor selects the secondary; detection below the floor
  falls back to primary; a high-probability language outside the declared pair
  is never selected.
- **`test_promotion.py`** — `count == 1` does not promote; `count == 2`
  promotes with `source=auto`; an expired pending row is dropped rather than
  promoted; `uses` ranking caps the hotword list at `MAX_VOCAB`.
- **`test_autolearn.py`** — the widened 1→2 and 2→1 shapes are detected; a
  lowercase technical term is now detected; `STOPLIST` words and case-only
  edits are still rejected.
- **`test_engine_seam.py`** — `transcribe()` equals the join of
  `transcribe_rich()`; a default-score `Segment` passes every §2 threshold.

## 8. Implementation order

Order is load-bearing: each step is independently shippable, and §3 is inert
without §2b.

1. §1 engine seam — unblocks everything, no behavior change.
2. §2a gain ceiling — largest single hallucination win, smallest diff.
3. §2b thresholds + §2c blocklist — local and browser.
4. §3 accent parameters — requires §2b to be live.
5. §5a hotword cap by `uses`.
6. §6 pending store, widened detection, promotion.
7. §4 language pair — largest change, opt-in by default, lands last.
