// Icons and primitives.
//
// The icons are Lucide paths inlined rather than a package: this app ships
// offline and needs six glyphs, so a dependency would be 300KB to save writing
// six `d` attributes. One family, one 1.75 stroke, one 24-box -- mixing icon
// sets is the single most reliable way to make an interface look assembled
// rather than designed.

import { html, useCallback, useEffect, useRef, useState } from "/static/app/react.js";
import { isUsable, keyName } from "/static/app/keys.js";

const PATHS = {
  mic: ["M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z", "M19 10v2a7 7 0 0 1-14 0v-2", "M12 19v3"],
  sparkles: ["M12 3l1.9 4.6L18.5 9.5 13.9 11.4 12 16l-1.9-4.6L5.5 9.5l4.6-1.9z", "M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"],
  book: ["M4 19.5A2.5 2.5 0 0 1 6.5 17H20", "M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"],
  activity: ["M22 12h-4l-3 9L9 3l-3 9H2"],
  drive: ["M22 12H2", "M5.5 5h13l3.5 7v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-5z", "M6 17h.01", "M10 17h.01"],
  trash: ["M3 6h18", "M8 6V4h8v2", "M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"],
  plus: ["M12 5v14", "M5 12h14"],
  search: ["M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z", "m21 21-4.3-4.3"],
  refresh: ["M3 12a9 9 0 0 1 15-6.7L21 8", "M21 3v5h-5", "M21 12a9 9 0 0 1-15 6.7L3 16", "M3 21v-5h5"],
  check: ["M20 6 9 17l-5-5"],
  alert: ["M12 9v4", "M12 17h.01", "M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"],
};

export function Icon({ name, size = 17, ...rest }) {
  const paths = PATHS[name] || [];
  return html`<svg width=${size} height=${size} viewBox="0 0 24 24" fill="none"
    stroke="currentColor" stroke-width="1.75" stroke-linecap="round"
    stroke-linejoin="round" aria-hidden="true" ...${rest}>
    ${paths.map((d, i) => html`<path key=${i} d=${d} />`)}
  </svg>`;
}

// --- primitives ------------------------------------------------------------

export function Card({ title, hint, icon, children }) {
  return html`<section class="card">
    ${(title || hint) && html`<div class="card-head">
      ${title && html`<h3 class="card-title">
        ${icon && html`<${Icon} name=${icon} size=${15} />`}${title}
      </h3>`}
      ${hint && html`<p class="card-hint">${hint}</p>`}
    </div>`}
    ${children}
  </section>`;
}

export function Field({ label, help, children, id }) {
  return html`<div class="field">
    <label class="field-label" for=${id}>${label}</label>
    ${children}
    ${help && html`<span class="field-help">${help}</span>`}
  </div>`;
}

export function Select({ id, value, options, onChange, disabled }) {
  // A stored value the list does not offer -- an older model, a hand-edited
  // config -- is shown rather than silently swapped for something else.
  const known = options.some((o) => o.value === value);
  const all = known || value == null
    ? options
    : [...options, { value, label: `${value} (not installed)` }];
  return html`<select class="control" id=${id} value=${value ?? ""}
    disabled=${!!disabled} onChange=${(e) => onChange(e.target.value)}>
    ${all.map((o) => html`<option key=${o.value} value=${o.value}>${o.label}</option>`)}
  </select>`;
}

export function TextInput({ id, value, onChange, placeholder, type = "text", ...rest }) {
  return html`<input class="control" id=${id} type=${type} value=${value ?? ""}
    placeholder=${placeholder} spellcheck="false"
    onChange=${(e) => onChange(e.target.value)} ...${rest} />`;
}

export function Switch({ id, checked, onChange, title, help }) {
  return html`<label class="switch" for=${id}>
    <input type="checkbox" id=${id} checked=${!!checked}
      onChange=${(e) => onChange(e.target.checked)} />
    <span class="switch-track"><span class="switch-thumb"></span></span>
    <span class="switch-text">
      <span class="switch-title">${title}</span>
      ${help && html`<span class="switch-help">${help}</span>`}
    </span>
  </label>`;
}

export function Button({ children, icon, variant = "", size = "", ...rest }) {
  return html`<button class=${`btn ${variant} ${size}`.trim()} type="button" ...${rest}>
    ${icon && html`<${Icon} name=${icon} size=${15} />`}${children}
  </button>`;
}

// Press a key, get that key. The only rebinding UI that works on a keyboard
// this app has never seen -- a dropdown of key names cannot know whether the
// laptop in front of you actually has a Right Ctrl.
export function KeyCapture({ value, onChange, suggestions, describe }) {
  const [listening, setListening] = useState(false);
  const [rejected, setRejected] = useState("");
  const box = useRef(null);

  const stop = useCallback(() => { setListening(false); }, []);

  useEffect(() => {
    if (!listening) return undefined;
    const onKey = (event) => {
      // Every key, including Escape and Tab: while capturing, the keyboard
      // belongs to this control. Escape cancels rather than binding.
      event.preventDefault();
      event.stopPropagation();
      if (event.key === "Escape") return stop();
      const name = keyName(event);
      if (!isUsable(name)) {
        setRejected(name);
        return;
      }
      setRejected("");
      onChange(name);
      stop();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [listening, onChange, stop]);

  return html`<div>
    <div class="row" ref=${box}>
      <span class=${"keycap" + (listening ? " listening" : "")}>
        ${listening ? "Press a key…" : describe(value)}
      </span>
      <${Button} size="sm" onClick=${() => (listening ? stop() : setListening(true))}>
        ${listening ? "Cancel" : "Change"}
      <//>
    </div>
    ${rejected && html`<p class="field-help" role="alert" style=${{ marginTop: "6px" }}>
      ${describe(rejected)} is needed for typing. Try a key you never use.
    </p>`}
    ${!listening && suggestions && html`<div class="row" style=${{ marginTop: "8px", gap: "6px" }}>
      ${suggestions.filter((k) => k.value !== value).slice(0, 4).map((k) =>
        html`<${Button} key=${k.value} size="sm" onClick=${() => onChange(k.value)}>
          ${k.label}
        <//>`)}
    </div>`}
  </div>`;
}

export function Metric({ value, label }) {
  return html`<div class="metric">
    <div class="metric-value">${value}</div>
    <div class="metric-label">${label}</div>
  </div>`;
}

export function Empty({ children }) {
  return html`<p class="empty">${children}</p>`;
}

export function Skeleton({ height = 16, width = "100%" }) {
  return html`<div class="skel" style=${{ height: `${height}px`, width }} />`;
}

export function Dialog({ title, body, confirm, onConfirm, onCancel, danger }) {
  // Escape closes it, because a modal with no way out on the keyboard is a
  // trap -- and the cancel button is focused first, not the destructive one.
  const onKey = (e) => { if (e.key === "Escape") onCancel(); };
  return html`<div class="scrim" onClick=${onCancel} onKeyDown=${onKey}>
    <div class="dialog" role="dialog" aria-modal="true" aria-label=${title}
      onClick=${(e) => e.stopPropagation()}>
      <h2>${title}</h2>
      <p>${body}</p>
      <div class="row end">
        <${Button} onClick=${onCancel} autofocus=${true}>Cancel<//>
        <${Button} variant=${danger ? "danger" : "primary"} onClick=${onConfirm}>
          ${confirm}
        <//>
      </div>
    </div>
  </div>`;
}
