// The app window.
//
// Every setting on screen is bound to a config key by its element id, so
// adding a knob is adding a control to the HTML and a line to BINDINGS --
// there is no per-field wiring to forget. Saves are debounced and optimistic:
// the control already shows what you chose, so the round trip only has to
// report a failure.

const VIEWS = [
  { id: "dictation", glyph: "●", label: "Dictation" },
  { id: "cleanup", glyph: "✨", label: "Cleanup" },
  { id: "dictionary", glyph: "✦", label: "Dictionary" },
  { id: "activity", glyph: "≡", label: "Activity" },
  { id: "storage", glyph: "■", label: "Storage" },
];

// element id -> how to read and write it. Ids match config keys.
const BINDINGS = {
  speech_engine: "value",
  speech_language: "value",
  asr_model: "value",
  asr_device: "value",
  ptt_key: "value",
  cancel_key: "value",
  cleanup_level: "value",
  cleanup_timeout_ms: "number",
  startup_mode: "value",
  hands_free_double_tap: "checked",
  sound_on_start: "checked",
  per_app_formatting: "checked",
};

const SAVE_DEBOUNCE_MS = 250;
const TOAST_MS = 2600;

const $ = (id) => document.getElementById(id);
const toast = $("toast");

let config = {};
let toastTimer = 0;
let saveTimer = 0;
let pending = {};

// --- talking to WinWhispr -------------------------------------------------

async function ask(op, payload) {
  const res = await fetch("/api/app", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ op, payload: payload || {} }),
  });
  if (!res.ok) throw new Error("HTTP " + res.status);
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  return data;
}

function say(message, bad) {
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.className = "toast" + (bad ? " bad" : "");
  toast.hidden = false;
  toastTimer = setTimeout(() => { toast.hidden = true; }, TOAST_MS);
}

function status(kind, text) {
  $("status-dot").className = "dot " + kind;
  $("status-text").textContent = text;
}

// --- navigation -----------------------------------------------------------

function buildNav() {
  for (const host of [$("sidebar"), $("tabs")]) {
    for (const view of VIEWS) {
      const button = document.createElement("button");
      button.className = "navlink";
      button.type = "button";
      button.dataset.view = view.id;
      button.innerHTML = `<span class="glyph">${view.glyph}</span><span>${view.label}</span>`;
      button.addEventListener("click", () => showView(view.id));
      host.appendChild(button);
    }
  }
  showView(location.hash.slice(1) || VIEWS[0].id);
}

function showView(id) {
  if (!VIEWS.some((v) => v.id === id)) id = VIEWS[0].id;
  for (const section of document.querySelectorAll(".view")) {
    section.classList.toggle("active", section.id === "view-" + id);
  }
  for (const link of document.querySelectorAll(".navlink")) {
    link.setAttribute("aria-current", String(link.dataset.view === id));
  }
  // Remembered across reopenings, since the window is closed and rebuilt
  // rather than hidden.
  location.hash = id;
  if (id === "activity") loadActivity();
  if (id === "storage") loadModels();
  if (id === "dictionary") loadDictionary();
}

// --- settings -------------------------------------------------------------

function fill(select, options, selected) {
  select.textContent = "";
  for (const option of options) {
    const node = document.createElement("option");
    node.value = option.value;
    node.textContent = option.label;
    select.appendChild(node);
  }
  // A stored value the list does not offer (an older model, a hand-edited
  // config) is kept rather than silently switching the user to something else.
  if (selected != null && !options.some((o) => o.value === selected)) {
    const node = document.createElement("option");
    node.value = selected;
    node.textContent = selected + " (not installed)";
    select.appendChild(node);
  }
  if (selected != null) select.value = selected;
}

function paintConfig() {
  for (const [key, kind] of Object.entries(BINDINGS)) {
    const el = $(key);
    if (!el || config[key] === undefined) continue;
    if (kind === "checked") el.checked = !!config[key];
    else el.value = config[key];
  }
  applyEngineVisibility();
  $("brand-sub").textContent = `Hold ${config.ptt_key || "Right Ctrl"} and speak`;
}

function applyEngineVisibility() {
  // A model picker for an engine that is not running invites a change that
  // does nothing.
  $("local-model-card").hidden = config.speech_engine !== "local";
  $("speech_language").closest(".field").hidden = config.speech_engine === "local";
}

function bindInputs() {
  for (const [key, kind] of Object.entries(BINDINGS)) {
    const el = $(key);
    if (!el) continue;
    const event = kind === "checked" || el.tagName === "SELECT" ? "change" : "input";
    el.addEventListener(event, () => {
      let value;
      if (kind === "checked") value = el.checked;
      else if (kind === "number") value = Number(el.value);
      else value = el.value;
      config[key] = value;
      if (key === "speech_engine") applyEngineVisibility();
      queueSave({ [key]: value });
    });
  }
}

function queueSave(changes) {
  Object.assign(pending, changes);
  clearTimeout(saveTimer);
  saveTimer = setTimeout(flushSave, SAVE_DEBOUNCE_MS);
}

async function flushSave() {
  const changes = pending;
  pending = {};
  if (!Object.keys(changes).length) return;
  try {
    const result = await ask("save_config", changes);
    if (result.config) config = result.config;
    say(result.restart ? "Saved — restarting dictation" : "Saved");
  } catch (err) {
    say("Could not save: " + err.message, true);
  }
}

// --- activity -------------------------------------------------------------

const METRICS = [
  ["words_today", "Words today"],
  ["avg_wpm", "Words per minute"],
  ["best_wpm", "Best"],
  ["day_streak", "Day streak"],
  ["total_words", "Words all time"],
];

function humanSeconds(total) {
  if (!total) return "0m";
  const hours = Math.floor(total / 3600);
  const minutes = Math.round((total % 3600) / 60);
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

async function loadActivity() {
  try {
    const { stats } = await ask("stats");
    const host = $("metrics");
    host.textContent = "";
    for (const [key, label] of METRICS) {
      host.appendChild(metric(String(stats[key] ?? 0), label));
    }
    host.appendChild(metric(humanSeconds(stats.time_saved_secs), "Time saved"));
    paintSpark(stats.last7_words || []);
  } catch (err) {
    say("Could not load stats: " + err.message, true);
  }
  loadNotes();
}

function metric(value, label) {
  const node = document.createElement("div");
  node.className = "metric";
  node.innerHTML = `<div class="value"></div><div class="label"></div>`;
  node.querySelector(".value").textContent = value;
  node.querySelector(".label").textContent = label;
  return node;
}

function paintSpark(days) {
  const host = $("spark");
  host.textContent = "";
  const peak = Math.max(1, ...days);
  for (const count of days) {
    const bar = document.createElement("div");
    bar.style.height = Math.max(3, Math.round((count / peak) * 62)) + "px";
    bar.title = `${count} words`;
    host.appendChild(bar);
  }
}

async function loadNotes() {
  const host = $("log");
  try {
    const { notes } = await ask("notes", { search: $("log-search").value.trim() });
    host.textContent = "";
    if (!notes.length) {
      host.innerHTML = `<p class="empty">Nothing yet. Hold your talk key and speak.</p>`;
      return;
    }
    for (const note of notes) host.appendChild(noteCard(note));
  } catch (err) {
    host.innerHTML = `<p class="empty">Could not load the log.</p>`;
  }
}

function noteCard(note) {
  const card = document.createElement("div");
  card.className = "note";
  const text = document.createElement("p");
  text.textContent = note.text;
  const meta = document.createElement("div");
  meta.className = "meta";
  const parts = [when(note.timestamp), `${note.words} words`];
  if (note.app) parts.push(note.app);
  for (const part of parts) {
    const span = document.createElement("span");
    span.textContent = part;
    meta.appendChild(span);
  }
  card.append(text, meta);
  return card;
}

function when(stamp) {
  const then = new Date(stamp);
  if (Number.isNaN(then.getTime())) return stamp || "";
  const diff = (Date.now() - then.getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return then.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// --- dictionary -----------------------------------------------------------

async function loadDictionary() {
  try {
    render(await ask("dictionary"));
  } catch (err) {
    say("Could not load the dictionary: " + err.message, true);
  }
}

function render({ entries }) {
  const body = $("dict-table").querySelector("tbody");
  body.textContent = "";
  if (!entries.length) {
    body.innerHTML = `<tr><td class="empty">No words yet.</td></tr>`;
    return;
  }
  for (const entry of entries) {
    const row = document.createElement("tr");
    const word = document.createElement("td");
    word.textContent = entry.correct;
    if (entry.source !== "manual") {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = "learned";
      word.append(" ", tag);
    }
    const heard = document.createElement("td");
    heard.textContent = entry.mishears.join(", ");
    const actions = document.createElement("td");
    actions.className = "num";
    const remove = document.createElement("button");
    remove.className = "small";
    remove.textContent = "Remove";
    remove.addEventListener("click", async () => {
      try {
        render(await ask("dictionary_remove", { correct: entry.correct }));
      } catch (err) {
        say("Could not remove it: " + err.message, true);
      }
    });
    actions.appendChild(remove);
    row.append(word, heard, actions);
    body.appendChild(row);
  }
}

// --- storage --------------------------------------------------------------

async function loadModels() {
  try {
    paintModels(await ask("models"));
  } catch (err) {
    say("Could not read the model folder: " + err.message, true);
  }
}

function paintModels({ models }) {
  const body = $("models-table").querySelector("tbody");
  body.textContent = "";
  if (!models.length) {
    body.innerHTML = `<tr><td colspan="3" class="empty">Nothing downloaded.</td></tr>`;
    return;
  }
  for (const model of models) {
    const row = document.createElement("tr");
    const name = document.createElement("td");
    name.textContent = model.name;
    if (model.in_use) {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = "in use";
      name.append(" ", tag);
    }
    const size = document.createElement("td");
    size.className = "num";
    size.textContent = model.size_mb >= 1024
      ? (model.size_mb / 1024).toFixed(1) + " GB"
      : Math.round(model.size_mb) + " MB";
    const actions = document.createElement("td");
    actions.className = "num";
    const remove = document.createElement("button");
    remove.className = "small";
    remove.textContent = "Delete";
    remove.disabled = model.in_use;
    remove.addEventListener("click", async () => {
      remove.disabled = true;
      try {
        paintModels(await ask("model_remove", { name: model.name }));
        say("Deleted");
      } catch (err) {
        say(err.message, true);
        remove.disabled = false;
      }
    });
    actions.appendChild(remove);
    row.append(name, size, actions);
    body.appendChild(row);
  }
}

// --- wiring ---------------------------------------------------------------

$("log-search").addEventListener("input", debounce(loadNotes, 200));
$("log-refresh").addEventListener("click", loadActivity);

$("dict-add").addEventListener("click", async () => {
  const correct = $("dict-correct").value.trim();
  if (!correct) return say("Type the correct spelling first", true);
  const mishears = $("dict-mishears").value.split(",").map((s) => s.trim()).filter(Boolean);
  try {
    render(await ask("dictionary_add", { correct, mishears }));
    $("dict-correct").value = "";
    $("dict-mishears").value = "";
    say("Added");
  } catch (err) {
    say(err.message, true);
  }
});

$("reset").addEventListener("click", async () => {
  // Destructive and irreversible, so it asks -- once, plainly.
  if (!confirm("Erase all usage metrics and the activity log?")) return;
  try {
    await ask("reset");
    say("Erased");
    loadActivity();
  } catch (err) {
    say(err.message, true);
  }
});

function debounce(fn, ms) {
  let timer = 0;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

// Unsaved edits must survive the window being closed from the title bar.
window.addEventListener("beforeunload", flushSave);

async function boot() {
  buildNav();
  bindInputs();
  try {
    const [{ config: loaded }, choices] = await Promise.all([
      ask("config"), ask("choices"),
    ]);
    config = loaded;
    fill($("speech_language"),
         choices.languages.map((l) => ({ value: l.tag, label: l.name })),
         config.speech_language);
    fill($("asr_model"),
         choices.models.map((m) => ({ value: m, label: m })),
         config.asr_model);
    fill($("asr_device"),
         choices.devices.map((d) => ({ value: d, label: d })),
         config.asr_device);
    paintConfig();
    status("ready", config.speech_engine === "local" ? "Local model" : "Browser engine");
  } catch (err) {
    status("error", "Not connected");
    say("Could not reach WinWhispr: " + err.message, true);
  }
}

boot();
