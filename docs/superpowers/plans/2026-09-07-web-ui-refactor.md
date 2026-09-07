# Plan: refactor the browser dictation UI

## Context

`core/web/static/` is the browser front end for WinWhispr dictation. It works,
but it was written to prove the engine wiring, not to be looked at. This plan
refactors it into an interface worth shipping, without changing a single API
contract: `/api/stt`, `/api/tidy`, `/api/paste`, `/api/health` stay exactly as
they are, and the two-engine listener design in `app.js` (Web Speech primary,
MediaRecorder + local Whisper fallback) is not to be touched.

Primary surface is a phone held one-handed. Second is a desktop browser.

## Global Constraints

Binding on every task. A violation is a defect, not a preference.

1. **No API changes.** `app.js`'s exports, the fetch paths, and the JSON shapes
   are fixed. `createListener`, `api`, `encodeWav`, `toBase64`,
   `webSpeechAvailable` keep their names and signatures.
2. **No dependencies.** No frameworks, no CSS libraries, no icon packages, no
   build step. Plain HTML, CSS and ES modules served from disk.
3. **No emoji as icons.** Inline SVG only, one visual family, consistent
   1.75px stroke, `currentColor` fill so theming works.
4. **Touch targets ≥ 44×44 CSS px**, with ≥ 8px between adjacent targets.
5. **Contrast ≥ 4.5:1** for body text and ≥ 3:1 for large text and meaningful
   glyphs, in both colour schemes.
6. **Semantic colour tokens only.** Components reference `--surface`,
   `--text-muted` and similar; no raw hex outside the token block.
7. **Spacing on a 4px rhythm** (4/8/12/16/24/32/48), exposed as tokens.
8. **Animate transform and opacity only**, 150–300ms, ease-out for entrances.
   Everything inside `@media (prefers-reduced-motion: reduce)` must reduce to a
   non-moving equivalent, not vanish.
9. **Both colour schemes.** Dark is primary; light comes from
   `prefers-color-scheme: light` and must be designed, not inverted.
10. **Safe areas honoured** via `env(safe-area-inset-*)`; no fixed element may
    sit under a notch or a home indicator.
11. **Nothing may regress** `uv run --extra dev pytest`.

## Task 1: Markup and visual system

Rewrite `core/web/static/index.html` and `core/web/static/style.css` together;
they are one layer and splitting them would mean two passes over the same
decisions.

**index.html**

- Semantic landmarks: a real `<header>`, `<main>`, and a `<footer>` for the
  secondary actions. One `<h1>`.
- The talk control is a `<button>` carrying `aria-pressed` and an
  `aria-describedby` pointing at the status line.
- Status line is `role="status"` with `aria-live="polite"` so a transcript
  arriving is announced without stealing focus.
- The transcript `<textarea>` keeps a visible `<label>`, not a placeholder
  standing in for one.
- The two switches keep real `<input type="checkbox">` elements with visible
  labels; style the control, do not replace it with a div.
- Inline `<svg>` icons defined once in a `<svg hidden>` sprite and referenced
  with `<use>`: microphone, stop, copy, trash, send. `stroke="currentColor"`,
  `stroke-width="1.75"`, 24×24 viewBox.
- Keep every id the existing `ui.js` queries: `talk`, `talk-label`, `waveform`,
  `text`, `status`, `engine`, `continuous`, `autosend`, `autosend-wrap`,
  `send`, `copy`, `clear`. Renaming them is out of scope for this task.

**style.css**

- A token block on `:root`: colour, spacing (4px rhythm), radius, type scale
  (12/14/16/18/24/32), and two motion tokens (`--ease-out`, `--dur`).
- A designed light scheme under `@media (prefers-color-scheme: light)`,
  overriding tokens only.
- Layout: single column, `max-width: 34rem`, centred, `min-height: 100dvh`,
  padding that includes the safe-area insets.
- The talk control is the visual anchor: the largest element, the only filled
  accent surface, with distinct rest / hover / active / listening / disabled
  states. `:active` scales to 0.98; listening does not change its bounds.
- `:focus-visible` rings on every interactive element, 2px, offset 2px,
  never removed.
- Ship the same file's motion inside a `prefers-reduced-motion` block.

Do not change `ui.js` or `app.js` in this task.

## Task 2: Interaction and feedback

Rewrite `core/web/static/ui.js` against the new markup. Behaviour to keep
exactly: the session loop, "keep listening" re-arming, "type on PC", token
prompting on 401, append-not-replace, Space to toggle, Escape to cancel.

Add what the current version lacks:

- `aria-pressed` on the talk button tracks listening state.
- Disabled state while a take is being transcribed, so a second tap cannot
  start an overlapping session; re-enabled in a `finally` so a thrown error
  cannot strand it.
- Status messages auto-clear after 4s, except errors, which stay until the
  next action.
- Every error message says what to do next, not only what failed.
- The copy button confirms, then returns to its label after 2s.
- Icons swap between microphone and stop via the sprite, matching state.

Structure the file so the DOM lookups happen once at the top and the session
loop reads as the state machine it is. No behaviour may depend on a CSS class
name that Task 1 did not define.

## Task 3: Waveform

The waveform is the only moving element and it currently animates twelve DOM
nodes from a `Date.now()` call inside a per-bar loop.

Replace it with a `<canvas>` rendered from a single `requestAnimationFrame`
loop in a new `core/web/static/waveform.js`, exporting `createWaveform(canvas)`
returning `{ setLevel(level), start(), stop() }`.

- Device-pixel-ratio aware; re-measure on resize.
- Idle state is a gentle shimmer, not a flat line: silence must still look
  like listening.
- The loop stops when not listening; it must not spin at 60fps on an idle page.
- Under `prefers-reduced-motion`, render a static level meter that still
  reflects amplitude — reduced, not removed.
- `ui.js` calls it; `app.js` is untouched.

## Task 4: Guard the invariants

Extend `tests/test_web_server.py` with tests that fail if the interface
regresses. All of them run against the already-served page, using the existing
fixtures — no browser, no new dependency.

- Every `id` referenced by `ui.js` exists in `index.html`.
- No emoji anywhere in `index.html` (the constraint that quietly rots).
- `<meta name="viewport">` exists and does not disable zoom.
- The status element carries `role="status"` and `aria-live`.
- Every `<input type="checkbox">` has a label bound by `for`.
- The stylesheet defines both colour schemes and a reduced-motion block.
- Every asset referenced by the page is served (already covered; keep it).

Then run the full suite and the Node syntax check on all three JS files.
