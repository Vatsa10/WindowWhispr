# UI Refactor: from generated-dashboard to instrument

Date: 2026-09-16
Status: approved, ready for implementation planning

## Problem

The app works and its CSS is better reasoned than it looks. It still reads as
AI-generated. The cause is not one bad choice, it is three:

1. **Two surfaces speak two dialects.** `core/web/static/app/style.css`
   (settings) and `core/web/static/style.css` (pill) share no token name, no
   type scale, no radius scale, no palette. `style.css:1` claims "Same palette
   as the desktop window". It is not.
2. **The palette is the Tailwind default scale, unmodified.** `#0f172a` is
   `slate-900`, `#22c55e` is `green-500`, `#94a3b8` is `slate-400`, `#ef4444`
   is `red-500`. Anyone who has seen a generated dashboard recognises it.
3. **The chrome is the generated-admin chrome.** Sidebar, topbar, and 14
   bordered card boxes stacked down a scroll, where nothing is actually
   elevated above anything else.

Plus one outright tell: the brand mark at `style.css:104` is a
`linear-gradient(135deg, #7c5cff, #22d3ee)` rounded square. Purple-to-cyan
diagonal gradient is the single most recognisable LLM design signature, and it
is the app's only logo.

## Goal

A tool that reads as a precision instrument. Quiet by default, with enough
character that it is obviously designed by someone rather than assembled from
defaults. Every existing piece of correct reasoning survives.

## Decisions taken

| Question | Decision |
|---|---|
| Redesign mode | Preserve semantics, replace the visual language |
| Accent meaning | Unchanged: one accent, it means the microphone is live |
| Accent colour | Green to instrument teal |
| Ground | Blue-slate to warm neutral |
| Display face | Space Grotesk, replacing Geist and the pill's Segoe UI |
| Mono face | JetBrains Mono, replacing Geist Mono |
| Icons | Phosphor, replacing the inlined Lucide paths |
| Motion | Dial 3 to 5, every animation individually motivated |

Design read: desktop utility for people who dictate all day, currently wearing
an admin-dashboard costume, should read as a precision instrument.
Dials: `DESIGN_VARIANCE 4 / MOTION_INTENSITY 5 / VISUAL_DENSITY 7`. Low variance
because a settings panel that surprises you is a bad settings panel. High
density because this is a tool, not a brochure.

## Hard constraint: no build step

There is no `node_modules`, no bundler, no `package.json` build. React and htm
are vendored ES modules loaded from `static/vendor/`. Fonts are vendored woff2.

Consequences that shape every section below:

- `npm install @phosphor-icons/react` is not available. Icons stay inlined
  paths in `ui.js`. Only the family and the geometry change.
- Every font is a file committed to `static/vendor/`.
- No Tailwind. All styling is hand-written CSS custom properties.
- No tree-shaking, so "just import the library" is never the cheap option.

## Non-goals

- **No IA change.** Same five views, same order, same labels, same routes.
  Nothing the user has built muscle memory for moves.
- **No copy rewrite.** The prose in the views is good and stays. The only
  exception is `app/style.css`'s palette comment, which becomes false when the
  accent changes and must be rewritten with it.
- **No new dependencies.** See the build-step constraint.
- **No component-level polish pass in this spec.** Optical alignment,
  concentric radii, hit areas: a separate follow-up using the `better-ui`
  skill, after the visual language lands. Doing both at once means neither
  gets reviewed properly.

---

## 1. Token unification (precondition, zero visual change)

New file `core/web/static/vendor/tokens.css`, imported by both stylesheets
before anything else.

The settings file's naming wins because it is the more disciplined of the two.
The pill's parallel vocabulary is deleted:

| Concept | Kept | Deleted |
|---|---|---|
| Spacing | `--s1`..`--s8` | `--sp-1`..`--sp-12` |
| Type scale | `--t-xs`..`--t-2xl` | `--fs-xs`..`--fs-2xl` |
| Radius | `--r-sm`, `--r`, `--r-lg`, `--r-full` | `--radius-sm`, `--radius-md`, `--radius-lg` |
| Text | `--fg`, `--fg-2`, `--fg-3` | `--text`, `--text-muted` |
| Motion | `--ease`, `--fast`, `--med` | `--ease-out`, `--dur` |
| Surfaces | `--bg`, `--surface`, `--surface-2`, `--surface-3` | `--surface2` |

**This step ships alone and changes nothing visible.** It is the precondition
for every step after it: with two vocabularies, a palette change means editing
two files and drifting them apart again.

Verification: the app looks pixel-identical before and after. Any visible
difference at this step is a migration bug, not a design change.

## 2. Palette

```css
/* Surfaces. Warm neutral, not blue-slate. No pure black: it flattens depth. */
--bg          #0f0f10;
--surface     #161617;
--surface-2   #1d1d1f;
--surface-3   #26262a;
--border      #2b2b30;
--border-lit  #3a3a41;

/* Text. Warm off-white against the warm ground. Three steps, as before. */
--fg          #f2f1ee;
--fg-2        #a3a09b;
--fg-3        #6f6d69;

/* The one accent, and the one alarm. */
--live        #1fd4c3;
--live-lit    #5fe6d8;
--live-soft   #1fd4c31c;
--bad         #ff5c47;
--bad-lit     #ff8a78;
--bad-soft    #ff5c471c;
```

**Why teal and not amber.** Both signals appear as 7px dots (`.chip .led`, the
pill's `.dot-core`). At that size the live state and the error state must be
unmistakable. Amber and red are neighbours on the wheel. Teal and red are
opposite, and stay distinguishable at 7px and for the most common colour
vision deficiencies.

**Why a warm neutral ground.** Cool text on blue-slate is the specific
combination that reads as generated. Warm off-white on warm near-black is the
larger half of the change, more than the accent swap is.

**The semantic rule survives verbatim.** One accent, it means the microphone is
live, nothing else is allowed to use it. `app/style.css:4` currently documents
this as a fact about green. Rewrite the comment to document it as a fact about
the accent. Do not delete it: it is the reason the rule exists, and without it
the next person adds a second teal thing.

**Follow-on edits** where the old palette is hardcoded outside the token block:

- `.btn.primary` colour `#052e16` (dark green for text on the green button)
  becomes `#06231f`.
- `.btn.danger` border `#7f1d1d` and hover `#ef44442e` move onto `--bad`
  derivatives.
- `.toast.good` border `#166534` moves onto a `--live` derivative.
- `select.control`'s inlined SVG chevron has `stroke='%2394a3b8'` baked into a
  data URI. Update to the new `--fg-2`.
- `.scrim` background `#020617cc` becomes a neutral-derived scrim.

Contrast requirements, verified before this step is called done: `--fg` on
`--bg` at AAA; `--fg-2` on `--surface` at AA; near-black on `--live` for the
primary button at AA; `--bad-lit` on `--bad-soft` at AA.

## 3. Type

**Space Grotesk** (UI and display) and **JetBrains Mono** (values), both
vendored as variable woff2 into `static/vendor/`, both OFL.

Replaces Geist, Geist Mono, and the pill's `"Segoe UI", system-ui` stack. The
two Geist files are deleted in the same commit.

```css
--font: "Space Grotesk", system-ui, -apple-system, "Segoe UI", sans-serif;
--mono: "JetBrains Mono", ui-monospace, "Cascadia Mono", Consolas, monospace;
```

**Why Space Grotesk.** It has real character in the `a`, `g`, and `t` without
being a costume. It is the half-step past a neutral grotesque that makes an
interface look chosen rather than defaulted, and it holds up at 13px body size,
which most characterful grotesques do not.

**Why JetBrains Mono.** The keycap, durations, word counts, dictionary entries,
and metric values are all read as *values*, not sentences. JetBrains Mono's
figures are unambiguous at 10px, which is the size the entry metadata runs at.
It pairs with Space Grotesk without competing, because their x-heights are
close and their personalities live in different letters.

**Space Grotesk needs tighter tracking than Geist did** at display sizes. The
existing `letter-spacing: -.011em` on headings and `-.02em` on `.metric-value`
were tuned for Geist. Retune both after the swap: Space Grotesk's default
fitting is looser, so expect to go further negative on `--t-2xl` and roughly
neutral at body size. This is a look-at-it change, not a computed one.

`font-display: swap` and the existing vendored-not-linked reasoning both stay.
The window is served from this machine and a CDN font would leave it unstyled
on a laptop that is offline or behind a filter.

## 4. Icons

**Phosphor**, at regular weight, replacing the Lucide paths inlined in
`app/ui.js`.

The delivery mechanism does not change and should not: twelve glyphs, an
offline desktop app, and no bundler to shake a tree with. The existing comment
at `ui.js:1` defending inlining stays true. What changes is the drawing.
Phosphor's geometry is rounder and more considered; Lucide is the set every
generated app reaches for, and it looks like it.

Mechanical changes to `Icon()`:

- `viewBox` from `0 0 24 24` to `0 0 256 256` (Phosphor's native box).
- `stroke-width` from `1.75` to `16` (equivalent visual weight in a 256 box).
- Default `size` stays `17`. Call sites do not change.

Glyphs needed: `microphone`, `sparkle`, `book-open`, `pulse`, `hard-drives`,
`trash`, `plus`, `magnifying-glass`, `arrows-clockwise`, `check`, `warning`.
Plus whatever the pill's overlay states use.

One family, one weight, one box. Mixing icon sets is the most reliable way to
make an interface look assembled rather than designed, and that rule is why
this is a full swap rather than a partial one.

## 5. Shape and density

### Radius

Unified to **4 / 8 / 12**, down from settings' 6/10/14 and the pill's 10/14/20.

```css
--r-sm: 4px;
--r:    8px;
--r-lg: 12px;
--r-full: 999px;
```

Sharper reads as instrument. `--r-full` survives for exactly two things: the
live dot and the status chip. Both are genuinely pill-shaped objects, not boxes
that happened to get rounded.

### Cards to hairlines

The largest single change to the generated-dashboard read.

Currently every settings group is a `.card`: `--surface` background, 1px
border, `--r-lg` radius, 20px padding. There are 14 of them across five views.
Nothing in a settings panel is elevated above anything else, so the elevation
is decoration.

Replace with hairline groups: a group title, a `border-top`, the fields, and
space. No background change, no border box, no radius.

`Card` survives as a primitive for the two places where something genuinely is
elevated above the page:

- `Dialog` (the erase-history confirmation), which sits over a scrim.
- The dictionary add-form, which is an input surface distinct from the list
  below it.

Everywhere else, `Card` call sites become the hairline group. The `.card`,
`.card-head`, `.card-title`, `.card-hint` rules stay for those two uses.

### Density

`VISUAL_DENSITY 7`. Removing card chrome frees room, so take it back:

- View padding `--s6` to `--s5`.
- Group spacing `--s4` to `--s3`.
- `.view-lede` bottom margin `--s6` to `--s5`.

Target: the Dictation view fits without scrolling at the default window size.
Verify this specifically, it is the view opened most.

## 6. Motion

`MOTION_INTENSITY 5`, up from an effective 3. Every animation below is
justified in one sentence. Anything that cannot be is not added.

Already present and correct, keep as-is:

- `breathe` on the live dot. Communicates: recording is active right now.
- Switch thumb `transform`. Communicates: state changed. Already
  compositor-only, already documented why.
- `.btn:active { transform: scale(.98) }`. Communicates: the press registered.
- Toast `rise`, dialog `pop`, scrim `appear`. Communicate: this arrived, it was
  not always here.
- Skeleton `fade`. Communicates: content is loading, and this is its shape.

Added:

- **View transition.** Switching nav views cross-fades the main pane over
  `--fast` with a 4px upward settle. Communicates: the pane changed, you did
  not navigate away. Without it, view switching is an instant repaint that
  reads as a flicker.
- **Keycap press.** The keycap's 2px bottom border collapses to 1px on
  `:active` with the cap translating down 1px. Communicates: this is a physical
  key, and it is the one you press. The keycap already carries the bottom-border
  affordance, this finishes it.
- **Dot to pill morph.** The pill's dot and expanded states currently swap. A
  spring on width and radius makes it one object changing shape rather than two
  objects trading places. Communicates: this is the same thing, still listening.

Rules that hold for all of it: `transform` and `opacity` only, never `width`
and `height` outside the morph's contained case, and the existing global
`prefers-reduced-motion` block collapses all of it. That block already exists
and already works. Do not add a second one.

## 7. The pill

The pill is the product. It is what the user sees almost all of the time; the
settings window is opened twice and abandoned. It is currently designed second
and inherits nothing. Invert that.

- **Gradient mark deleted.** No replacement graphic. The mark becomes the live
  dot itself, a filled teal circle, which is the one shape the user already
  associates with the app. Deleting `.mark` also deletes the app's single worst
  AI tell.
- **Adopts `tokens.css`,** so it stops being a separate dialect. After step 1
  this is mostly deletion.
- **Light mode reaches parity.** The pill already implements
  `prefers-color-scheme`. Settings hardcodes `color-scheme: dark`. Today a
  light-mode user gets a light pill inside a dark window. Settings gains the
  light token block, and both surfaces follow the system.

Light-mode tokens are derived from the dark set, not invented separately, so
the two cannot drift. Same contrast requirements as section 2, verified in both
modes.

## 8. Character layer

Sections 1 through 7 remove what is wrong. This section is what makes it look
like someone designed it. Without this the result is correct and forgettable.

- **The metric numerals carry the page.** `.metric-value` is already mono and
  tabular at `--t-2xl`. Push it: JetBrains Mono at display size with tight
  negative tracking, `--fg` at full strength, against a hairline group with no
  box. Large precise figures in a good mono face are the entire instrument
  aesthetic in one element, and this app already has four of them.
- **The activity bars become a real readout.** `.bars` currently renders flat
  teal bars. Give the zero-state bars a 1px baseline rule instead of a filled
  `--surface-3` block, so an empty day reads as a measured zero rather than a
  missing bar. Instruments show you the zero.
- **Hairlines do the structural work.** With cards gone, the `border-top` on
  each group is the page's only structure. That makes hairline quality matter:
  one colour, one weight, consistent inset, never doubled where two groups
  meet.
- **The keycap is the hero object.** It is the one control that is unique to
  this app. It already has the bottom-border affordance. With JetBrains Mono, a
  press animation, and `--live` when listening, it becomes the thing a
  screenshot is built around.

Explicitly not doing, because each is the slop we are removing: glow or neon on
the accent, glassmorphism, gradient anything, decorative status dots beyond the
two that carry real state, animated background texture, a custom cursor.

## 9. Copy rules for any new or edited string

- No em-dash and no en-dash anywhere visible. Use a hyphen, a comma, a colon,
  or two sentences.
- No version labels, no build stamps, no locale or time strips.
- Existing view copy is not rewritten. See non-goals.

## 10. Verification

There are no UI tests in this repo and this spec does not add a framework. What
it requires instead, per step:

1. **Token migration:** app is pixel-identical before and after. Any visible
   difference is a bug.
2. **Palette:** contrast ratios measured, not eyeballed, for the four pairs
   named in section 2. Both themes once step 7 lands.
3. **Fonts:** every view opened and checked for reflow. Space Grotesk has
   different metrics from Geist, so fixed-width controls (`.keycap` at
   `min-width: 88px`, `.control` at `min-height: 38px`) need re-checking for
   clipping.
4. **Icons:** all eleven glyphs render at 15px and 17px. A wrong `viewBox`
   shows up as an invisible or a giant icon, not a subtly wrong one.
5. **Cards to hairlines:** Dictation view fits without scrolling at the default
   window size.
6. **Motion:** every added animation checked with `prefers-reduced-motion:
   reduce` forced on. All three must collapse to static.
7. **Pill:** dot state, expanded state, and the morph between them, in both
   themes, at the pill's actual window size rather than in a browser tab.

Screenshot each view before starting, for comparison at the end.

## 11. Implementation order

Each step ships alone, is separately revertible, and leaves the app usable.

1. **`tokens.css` and both files migrated onto it.** Zero visual change.
2. **Palette swap.** One file, now that step 1 is done.
3. **Fonts vendored and swapped.** Includes tracking retune and the reflow
   check. Deletes the Geist files.
4. **Icons to Phosphor.** Mechanical, contained to `ui.js`.
5. **Cards to hairlines, radius, density.** Largest diff, touches every view.
6. **Motion additions.**
7. **Pill: mark deleted, light-mode parity for settings.**
8. **Character layer.** Last on purpose. It is judgement work and it wants the
   rest of the language already in place to judge against.

Steps 1 through 4 are mechanical and low-risk. Step 5 is where review matters
most. Step 8 is where taste matters most.

## 12. Follow-up, not in this spec

Component-level polish using the `better-ui` skill: concentric border radii,
optical alignment, hit-area sizing, focus-ring quality, disabled-state
treatment. It wants the visual language settled first, and folding it in here
would mean neither pass gets reviewed properly.
