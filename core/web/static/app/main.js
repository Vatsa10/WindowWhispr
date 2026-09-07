// WinWhispr's window.
//
// One store (`useSettings`) owns the config and every write to it: controls
// read from it and call `set`, which updates locally, debounces, and posts.
// That is deliberate -- a settings screen where each control does its own
// fetch is a settings screen where two of them race and the file loses one.

import { html, ReactDOM, useCallback, useEffect, useRef, useState } from "/static/app/react.js";
import {
  Button, Card, Dialog, Empty, Field, Icon, Metric, Select, Skeleton, Switch, TextInput,
} from "/static/app/ui.js";

const SAVE_DEBOUNCE_MS = 300;
const TOAST_MS = 3200;

const VIEWS = [
  { id: "dictation", icon: "mic", label: "Dictation" },
  { id: "cleanup", icon: "sparkles", label: "Cleanup" },
  { id: "dictionary", icon: "book", label: "Dictionary" },
  { id: "activity", icon: "activity", label: "Activity" },
  { id: "storage", icon: "drive", label: "Storage" },
];

// --- talking to WinWhispr ---------------------------------------------------

async function ask(op, payload) {
  const res = await fetch("/api/app", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ op, payload: payload || {} }),
  });
  if (!res.ok) throw new Error(`WinWhispr answered ${res.status}`);
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  return data;
}

// --- toasts -----------------------------------------------------------------

function useToasts() {
  const [toasts, setToasts] = useState([]);
  const next = useRef(1);
  const push = useCallback((message, kind = "good") => {
    const id = next.current++;
    setToasts((all) => [...all, { id, message, kind }]);
    setTimeout(() => setToasts((all) => all.filter((t) => t.id !== id)), TOAST_MS);
  }, []);
  return [toasts, push];
}

function Toasts({ toasts }) {
  return html`<div class="toasts" role="status" aria-live="polite">
    ${toasts.map((t) => html`<div key=${t.id} class=${"toast " + t.kind}>
      <${Icon} name=${t.kind === "bad" ? "alert" : "check"} size=${15} />
      ${t.message}
    </div>`)}
  </div>`;
}

// --- settings store ---------------------------------------------------------

function useSettings(notify) {
  const [config, setConfig] = useState(null);
  const [choices, setChoices] = useState(null);
  const pending = useRef({});
  const timer = useRef(0);

  useEffect(() => {
    Promise.all([ask("config"), ask("choices")])
      .then(([c, ch]) => { setConfig(c.config); setChoices(ch); })
      .catch((err) => notify(err.message, "bad"));
  }, [notify]);

  const flush = useCallback(async () => {
    const changes = pending.current;
    pending.current = {};
    if (!Object.keys(changes).length) return;
    try {
      const result = await ask("save_config", changes);
      if (result.restart) notify("Saved — restarting dictation");
      else notify("Saved");
    } catch (err) {
      notify("Could not save: " + err.message, "bad");
    }
  }, [notify]);

  const set = useCallback((key, value) => {
    // Optimistic: the control already shows the new value, so waiting on the
    // round trip would only add lag to something that essentially never fails.
    setConfig((old) => ({ ...old, [key]: value }));
    pending.current[key] = value;
    clearTimeout(timer.current);
    timer.current = setTimeout(flush, SAVE_DEBOUNCE_MS);
  }, [flush]);

  // Closing the window mid-edit must not lose the edit.
  useEffect(() => {
    const onLeave = () => flush();
    window.addEventListener("beforeunload", onLeave);
    return () => window.removeEventListener("beforeunload", onLeave);
  }, [flush]);

  return { config, choices, set };
}

// --- views ------------------------------------------------------------------

function Dictation({ config, choices, set }) {
  const browser = config.speech_engine !== "local";
  return html`<div>
    <p class="view-lede">Hold your talk key in any application, speak, and let
      go. The words are cleaned up and typed where your cursor already was.</p>

    <${Card} icon="mic" title="Speech engine"
      hint="The browser engine works the moment WinWhispr is installed and sends
            audio to Microsoft's speech service. The local model keeps everything
            on this machine, after a one-time download.">
      <div class="grid">
        <${Field} label="Engine" id="engine">
          <${Select} id="engine" value=${config.speech_engine}
            onChange=${(v) => set("speech_engine", v)}
            options=${[
              { value: "browser", label: "Browser — instant, nothing to download" },
              { value: "local", label: "This machine — fully offline" },
            ]} />
        <//>
        ${browser && html`<${Field} label="Language"
          help="Set once. Applies to the browser engine." id="lang">
          <${Select} id="lang" value=${config.speech_language}
            onChange=${(v) => set("speech_language", v)}
            options=${(choices.languages || []).map((l) => ({ value: l.tag, label: l.name }))} />
        <//>`}
      </div>
    <//>

    ${!browser && html`<${Card} title="Local model"
      hint="Automatic sizes the model to this machine, then measures it and drops
            to a smaller one if it turns out too slow.">
      <div class="grid">
        <${Field} label="Model" id="model">
          <${Select} id="model" value=${config.asr_model}
            onChange=${(v) => set("asr_model", v)}
            options=${(choices.models || []).map((m) => ({ value: m, label: m }))} />
        <//>
        <${Field} label="Compute device" id="device">
          <${Select} id="device" value=${config.asr_device}
            onChange=${(v) => set("asr_device", v)}
            options=${(choices.devices || []).map((d) => ({ value: d, label: d }))} />
        <//>
      </div>
    <//>`}

    <${Card} title="Keys">
      <div class="grid">
        <${Field} label="Talk key" help="Hold it to dictate." id="ptt">
          <${TextInput} id="ptt" value=${config.ptt_key}
            onChange=${(v) => set("ptt_key", v)} placeholder="right ctrl" />
        <//>
        <${Field} label="Cancel key" help="Throws the recording away." id="cancel">
          <${TextInput} id="cancel" value=${config.cancel_key}
            onChange=${(v) => set("cancel_key", v)} placeholder="esc" />
        <//>
      </div>
      <div style=${{ marginTop: "8px" }}>
        <${Switch} id="doubletap" checked=${config.hands_free_double_tap}
          onChange=${(v) => set("hands_free_double_tap", v)}
          title="Tap twice to keep recording"
          help="Hands-free, so a long dictation does not mean a held key." />
        <${Switch} id="sound" checked=${config.sound_on_start}
          onChange=${(v) => set("sound_on_start", v)}
          title="Sound when recording starts" />
      </div>
    <//>
  </div>`;
}

function Cleanup({ config, set }) {
  return html`<div>
    <p class="view-lede">Fillers removed, spoken punctuation applied, sentences
      capitalized. If cleanup ever looks like it changed what you said, your raw
      words are pasted instead — it can only improve the text, never lose it.</p>

    <${Card} icon="sparkles" title="How much to change">
      <div class="grid">
        <${Field} label="Level" id="level">
          <${Select} id="level" value=${config.cleanup_level}
            onChange=${(v) => set("cleanup_level", v)}
            options=${[
              { value: "none", label: "None — paste exactly what was heard" },
              { value: "light", label: "Light — fillers and punctuation" },
              { value: "medium", label: "Medium — also tighten wording" },
              { value: "high", label: "High — rewrite for brevity" },
            ]} />
        <//>
        <${Field} label="Timeout" help="Milliseconds before it gives up and pastes the raw words." id="timeout">
          <${TextInput} id="timeout" type="number" value=${config.cleanup_timeout_ms}
            onChange=${(v) => set("cleanup_timeout_ms", Number(v) || 0)} />
        <//>
      </div>
      <div style=${{ marginTop: "8px" }}>
        <${Switch} id="perapp" checked=${config.per_app_formatting}
          onChange=${(v) => set("per_app_formatting", v)}
          title="Match the app I am typing into"
          help="An email reads differently from a chat message." />
      </div>
    <//>
  </div>`;
}

function Dictionary({ notify }) {
  const [entries, setEntries] = useState(null);
  const [correct, setCorrect] = useState("");
  const [mishears, setMishears] = useState("");

  const load = useCallback(() => {
    ask("dictionary").then((d) => setEntries(d.entries))
      .catch((err) => notify(err.message, "bad"));
  }, [notify]);
  useEffect(load, [load]);

  const add = async () => {
    if (!correct.trim()) return notify("Type the correct spelling first", "bad");
    try {
      const d = await ask("dictionary_add", {
        correct: correct.trim(),
        mishears: mishears.split(",").map((s) => s.trim()).filter(Boolean),
      });
      setEntries(d.entries);
      setCorrect(""); setMishears("");
      notify("Added");
    } catch (err) { notify(err.message, "bad"); }
  };

  const remove = async (word) => {
    try {
      setEntries((await ask("dictionary_remove", { correct: word })).entries);
      notify("Removed");
    } catch (err) { notify(err.message, "bad"); }
  };

  return html`<div>
    <p class="view-lede">Names and terms recognition keeps missing. They are
      given to the recognizer as a spelling authority, not swapped in
      afterwards, so they cannot corrupt a word that merely sounds similar.</p>

    <${Card} icon="plus" title="Add a spelling">
      <div class="grid">
        <${Field} label="Correct spelling" id="dc">
          <${TextInput} id="dc" value=${correct} onChange=${setCorrect} placeholder="ChargeBee" />
        <//>
        <${Field} label="What it hears" help="Comma separated. Optional." id="dm">
          <${TextInput} id="dm" value=${mishears} onChange=${setMishears} placeholder="charge bee, charge b" />
        <//>
      </div>
      <div class="row" style=${{ marginTop: "16px" }}>
        <${Button} variant="primary" icon="plus" onClick=${add}>Add word<//>
      </div>
    <//>

    <${Card} title="Known words">
      ${entries === null
        ? html`<${Skeleton} height=${58} />`
        : entries.length === 0
        ? html`<${Empty}>No words yet. Add one above.<//>`
        : html`<div class="rows">
            ${entries.map((e) => html`<div class="rowitem" key=${e.correct}>
              <div class="rowitem-main">
                <div class="rowitem-title">
                  ${e.correct} ${e.source !== "manual" && html`<span class="badge">learned</span>`}
                </div>
                ${e.mishears.length > 0 &&
                  html`<div class="rowitem-sub">heard as ${e.mishears.join(", ")}</div>`}
              </div>
              <${Button} size="sm" icon="trash" onClick=${() => remove(e.correct)}
                aria-label=${`Remove ${e.correct}`}>Remove<//>
            </div>`)}
          </div>`}
    <//>
  </div>`;
}

const METRICS = [
  ["words_today", "Words today"],
  ["avg_wpm", "Words per minute"],
  ["best_wpm", "Personal best"],
  ["day_streak", "Day streak"],
];

const DAY_LABELS = ["6d", "5d", "4d", "3d", "2d", "Yst", "Today"];

function humanSeconds(total) {
  if (!total) return "0m";
  const hours = Math.floor(total / 3600);
  const minutes = Math.round((total % 3600) / 60);
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

function ago(stamp) {
  const then = new Date(stamp);
  if (Number.isNaN(then.getTime())) return stamp || "";
  const diff = (Date.now() - then.getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return then.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function Activity({ notify }) {
  const [stats, setStats] = useState(null);
  const [notes, setNotes] = useState(null);
  const [search, setSearch] = useState("");

  const loadStats = useCallback(() => {
    ask("stats").then((d) => setStats(d.stats)).catch((err) => notify(err.message, "bad"));
  }, [notify]);

  useEffect(loadStats, [loadStats]);

  // Debounced, so typing in the box is not one query per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      ask("notes", { search }).then((d) => setNotes(d.notes)).catch(() => setNotes([]));
    }, 220);
    return () => clearTimeout(timer);
  }, [search]);

  const days = stats?.last7_words || [];
  const peak = Math.max(1, ...days);

  return html`<div>
    <p class="view-lede">Everything dictated on this machine. It never leaves it.</p>

    <div class="metrics">
      ${stats === null
        ? [0, 1, 2, 3].map((i) => html`<${Skeleton} key=${i} height=${86} />`)
        : html`${METRICS.map(([key, label]) =>
            html`<${Metric} key=${key} value=${stats[key] ?? 0} label=${label} />`)}`}
    </div>

    <${Card} icon="activity" title="Last seven days"
      hint=${stats ? `${humanSeconds(stats.time_saved_secs)} saved versus typing, all time.` : null}>
      ${stats === null ? html`<${Skeleton} height=${96} />` : html`<div class="bars">
        ${days.map((count, i) => html`<div class="bars-col" key=${i}>
          <div class=${"bars-bar" + (count ? "" : " zero")}
            style=${{ height: `${Math.max(3, Math.round((count / peak) * 74))}px` }}
            title=${`${count} words`} />
          <span class="bars-day">${DAY_LABELS[i]}</span>
        </div>`)}
      </div>`}
    <//>

    <div class="row" style=${{ marginBottom: "12px" }}>
      <div class="field" style=${{ flex: "1 1 220px" }}>
        <label class="sr-only" for="q">Search transcripts</label>
        <${TextInput} id="q" type="search" value=${search} onChange=${setSearch}
          placeholder="Search transcripts" />
      </div>
      <${Button} icon="refresh" onClick=${loadStats}>Refresh<//>
    </div>

    ${notes === null
      ? html`<${Skeleton} height=${64} />`
      : notes.length === 0
      ? html`<${Empty}>${search ? "Nothing matches that." : "Nothing yet. Hold your talk key and speak."}<//>`
      : notes.map((n) => html`<div class="entry" key=${n.id}>
          <div class="entry-text">${n.text}</div>
          <div class="entry-meta">
            <span>${ago(n.timestamp)}</span>
            <span>${n.words} words</span>
            ${n.app && html`<span>${n.app}</span>`}
          </div>
        </div>`)}
  </div>`;
}

function Storage({ config, set, notify }) {
  const [models, setModels] = useState(null);
  const [confirming, setConfirming] = useState(null);

  useEffect(() => {
    ask("models").then((d) => setModels(d.models)).catch((err) => notify(err.message, "bad"));
  }, [notify]);

  const remove = async (name) => {
    setConfirming(null);
    try {
      setModels((await ask("model_remove", { name })).models);
      notify("Deleted");
    } catch (err) { notify(err.message, "bad"); }
  };

  const wipe = async () => {
    setConfirming(null);
    try { await ask("reset"); notify("Erased"); }
    catch (err) { notify(err.message, "bad"); }
  };

  const size = (mb) => (mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`);

  return html`<div>
    <p class="view-lede">Models downloaded to this machine. Deleting one frees
      the space; it downloads again if you pick it later.</p>

    <${Card} icon="drive" title="Downloaded models">
      ${models === null
        ? html`<${Skeleton} height=${58} />`
        : models.length === 0
        ? html`<${Empty}>Nothing downloaded — the browser engine needs no model.<//>`
        : html`<div class="rows">
            ${models.map((m) => html`<div class="rowitem" key=${m.name}>
              <div class="rowitem-main">
                <div class="rowitem-title">
                  ${m.name} ${m.in_use && html`<span class="badge grey">in use</span>`}
                </div>
              </div>
              <span class="rowitem-num">${size(m.size_mb)}</span>
              <${Button} size="sm" icon="trash" disabled=${m.in_use}
                onClick=${() => setConfirming({ kind: "model", name: m.name })}
                aria-label=${`Delete ${m.name}`}>Delete<//>
            </div>`)}
          </div>`}
    <//>

    <${Card} title="Start with Windows">
      <div class="grid">
        <${Field} label="At login, start" id="startup">
          <${Select} id="startup" value=${config.startup_mode}
            onChange=${(v) => set("startup_mode", v)}
            options=${[
              { value: "app", label: "The app" },
              { value: "listen", label: "Browser dictation only" },
            ]} />
        <//>
      </div>
    <//>

    <${Card} title="Reset"
      hint="Erases usage metrics and the activity log. Settings, the dictionary
            and downloaded models are left alone.">
      <${Button} variant="danger" icon="trash"
        onClick=${() => setConfirming({ kind: "reset" })}>Erase metrics and log<//>
    <//>

    ${confirming && (confirming.kind === "reset"
      ? html`<${Dialog} danger=${true} title="Erase your history?"
          body="Usage metrics and every logged transcript are deleted. This cannot be undone."
          confirm="Erase" onConfirm=${wipe} onCancel=${() => setConfirming(null)} />`
      : html`<${Dialog} danger=${true} title=${`Delete ${confirming.name}?`}
          body="It is removed from disk and downloads again if you pick it later."
          confirm="Delete" onConfirm=${() => remove(confirming.name)}
          onCancel=${() => setConfirming(null)} />`)}
  </div>`;
}

// --- shell ------------------------------------------------------------------

function App() {
  const [toasts, notify] = useToasts();
  const { config, choices, set } = useSettings(notify);
  const [view, setView] = useState(() => location.hash.slice(1) || "dictation");

  // The window is destroyed and rebuilt rather than hidden, so the hash is
  // what makes it reopen where you left it.
  useEffect(() => { location.hash = view; }, [view]);

  const current = VIEWS.find((v) => v.id === view) || VIEWS[0];
  const ready = config && choices;

  return html`<div class="shell">
    <header class="brand">
      <span class="brand-mark"><${Icon} name="mic" size=${17} /></span>
      <div style=${{ minWidth: 0 }}>
        <div class="brand-name">WinWhispr</div>
        <div class="brand-sub">
          ${ready ? `Hold ${config.ptt_key || "right ctrl"} and speak` : "Starting…"}
        </div>
      </div>
    </header>

    <div class="topbar">
      <h1 class="topbar-title">${current.label}</h1>
      <span class="chip">
        <span class=${"led " + (ready ? "ok" : "busy")}></span>
        ${!ready ? "Connecting" : config.speech_engine === "local" ? "Local model" : "Browser engine"}
      </span>
    </div>

    <nav class="nav" aria-label="Sections">
      ${VIEWS.map((v) => html`<button key=${v.id} class="navitem" type="button"
        aria-current=${view === v.id ? "page" : undefined}
        onClick=${() => setView(v.id)}>
        <${Icon} name=${v.icon} size=${16} />${v.label}
      </button>`)}
    </nav>

    <main class="main"><div class="main-inner">
      ${!ready
        ? html`<${Skeleton} height=${180} />`
        : view === "dictation" ? html`<${Dictation} config=${config} choices=${choices} set=${set} />`
        : view === "cleanup" ? html`<${Cleanup} config=${config} set=${set} />`
        : view === "dictionary" ? html`<${Dictionary} notify=${notify} />`
        : view === "activity" ? html`<${Activity} notify=${notify} />`
        : html`<${Storage} config=${config} set=${set} notify=${notify} />`}
    </div></main>

    <${Toasts} toasts=${toasts} />
  </div>`;
}

ReactDOM.createRoot(document.getElementById("root")).render(html`<${App} />`);
