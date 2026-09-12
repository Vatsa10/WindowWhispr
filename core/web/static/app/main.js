// WinWhispr's window.
//
// One store (`useSettings`) owns the config and every write to it: controls
// read from it and call `set`, which updates locally, debounces, and posts.
// That is deliberate -- a settings screen where each control does its own
// fetch is a settings screen where two of them race and the file loses one.

import { html, ReactDOM, useCallback, useEffect, useRef, useState } from "/static/app/react.js";
import {
  Button, Card, Dialog, Empty, Field, Icon, KeyCapture, Metric, Select, Skeleton,
  Switch, TextInput,
} from "/static/app/ui.js";
import { describeKey } from "/static/app/keys.js";

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
  const suggestions = choices.keys || [];
  const describe = useCallback(
    (name) => describeKey(name, suggestions), [suggestions]);

  return html`<div>
    <p class="view-lede">Hold your talk key in any application, speak, and let
      go. The words are cleaned up and typed where your cursor already was.</p>

    <${Card} icon="mic" title="Language"
      hint="Set once. WinWhispr uses the speech engine already on this PC, so
            there is nothing to download when you change it.">
      <div class="grid">
        <${Field} label="Dictation language" id="lang">
          <${Select} id="lang" value=${config.speech_language}
            onChange=${(v) => set("speech_language", v)}
            options=${(choices.languages || []).map((l) => ({ value: l.tag, label: l.name }))} />
        <//>
      </div>
    <//>

    <${Card} title="Keys"
      hint="Right Ctrl is the default because nothing else uses it. Plenty of
            laptops do not have one, so press Change and hit whichever key you
            never reach for.">
      <div class="grid">
        <${Field} label="Talk key" help="Hold it to dictate.">
          <${KeyCapture} value=${config.ptt_key} describe=${describe}
            suggestions=${suggestions}
            onChange=${(v) => set("ptt_key", v)} />
        <//>
        <${Field} label="Cancel key" help="Throws away what you just said.">
          <${KeyCapture} value=${config.cancel_key} describe=${describe}
            onChange=${(v) => set("cancel_key", v)} />
        <//>
      </div>
      <div style=${{ marginTop: "12px" }}>
        <${Switch} id="doubletap" checked=${config.hands_free_double_tap}
          onChange=${(v) => set("hands_free_double_tap", v)}
          title="Tap twice to keep listening"
          help="Hands-free, so a long dictation is not a held key. Tap once more to stop." />
        <${Switch} id="sound" checked=${config.sound_on_start}
          onChange=${(v) => set("sound_on_start", v)}
          title="Sound when recording starts" />
      </div>
    <//>

    <${Card} title="Where the dot sits"
      hint="WinWhispr keeps a small dot on screen while it waits. It has to
            stay visible to keep listening, so put it somewhere you do not
            look. It grows into a pill only while you are speaking.">
      <div class="grid">
        <${Field} label="Corner" id="corner">
          <${Select} id="corner" value=${config.pill_corner}
            onChange=${(v) => set("pill_corner", v)}
            options=${(choices.corners || []).map((c) => ({
              value: c,
              label: c.split("-").map((w) => w[0].toUpperCase() + w.slice(1)).join(" "),
            }))} />
        <//>
      </div>
    <//>
  </div>`;
}

function Cleanup({ config, set }) {
  const on = config.cleanup_level !== "none";
  return html`<div>
    <p class="view-lede">Speech comes out messy. WinWhispr tidies it before it
      reaches your cursor, using fixed rules rather than a model, so the result
      is the same every time and nothing is ever invented.</p>

    <${Card} icon="sparkles" title="Tidy up what I say">
      <${Switch} id="tidy" checked=${on}
        onChange=${(v) => set("cleanup_level", v ? "light" : "none")}
        title="Clean up transcripts"
        help="Turn this off to have your words typed exactly as they were heard." />
    <//>

    <${Card} title="What it does">
      <div class="rows">
        ${[
          ["Removes fillers", "“um”, “uh”, “you know”, and repeated words"],
          ["Applies spoken punctuation", "say “comma” or “new line” and you get one"],
          ["Capitalises sentences", "and fixes the spacing around punctuation"],
          ["Uses your dictionary", "names it keeps mishearing, from the Dictionary tab"],
          ["Expands your snippets", "say a trigger, get the whole block"],
        ].map(([title, sub]) => html`<div class="rowitem" key=${title}>
          <div class="rowitem-main">
            <div class="rowitem-title">${title}</div>
            <div class="rowitem-sub">${sub}</div>
          </div>
        </div>`)}
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
  const [confirming, setConfirming] = useState(false);

  const wipe = async () => {
    setConfirming(false);
    try { await ask("reset"); notify("Erased"); }
    catch (err) { notify(err.message, "bad"); }
  };

  return html`<div>
    <p class="view-lede">What WinWhispr keeps on this machine, and how it starts.</p>

    <${Card} icon="drive" title="Start with Windows"
      hint="WinWhispr is small and idle until you hold the talk key, so leaving
            it running is what keeps the key always ready.">
      <div class="grid">
        <${Field} label="At login, start" id="startup">
          <${Select} id="startup" value=${config.startup_mode}
            onChange=${(v) => set("startup_mode", v)}
            options=${[
              { value: "app", label: "WinWhispr" },
              { value: "listen", label: "Dictation only, no settings window" },
            ]} />
        <//>
      </div>
    <//>

    <${Card} title="Erase history"
      hint="Deletes your usage figures and every transcript in the activity log.
            Settings and your dictionary are left alone.">
      <${Button} variant="danger" icon="trash"
        onClick=${() => setConfirming(true)}>Erase history<//>
    <//>

    ${confirming && html`<${Dialog} danger=${true} title="Erase all history?"
      body="Your usage figures and every logged transcript are deleted. This cannot be undone."
      confirm="Erase" onConfirm=${wipe} onCancel=${() => setConfirming(false)} />`}
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
          ${ready ? `Hold ${describeKey(config.ptt_key, choices.keys)} to speak` : "Starting…"}
        </div>
      </div>
    </header>

    <div class="topbar">
      <h1 class="topbar-title">${current.label}</h1>
      <span class="chip">
        <span class=${"led " + (ready ? "ok" : "busy")}></span>
        ${ready ? "Ready" : "Connecting"}
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
