// The recognizer tab.
//
// This page does not look like much on purpose: you arm it once and then
// forget it exists. From that point the hotkey on the PC drives it -- hold
// Right Ctrl in any application, speak, let go, and the words are typed where
// your cursor already was. Chrome does the listening and the transcribing;
// this process only owns the hotkey and the typing.
//
// Three pieces of state, because the browser's recognizer stops whenever it
// feels like it and has to be restarted underneath the user:
//
//   want  the hotkey is held  (the truth, pushed from the PC)
//   live  recognition is actually running
//   buffer  finals collected since the key went down

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;

const dot = document.getElementById("dot");
const state = document.getElementById("state");
const detail = document.getElementById("detail");
const arm = document.getElementById("arm");

const token = new URLSearchParams(location.search).get("token")
  || localStorage.getItem("winwhispr-token")
  || "";
if (token) localStorage.setItem("winwhispr-token", token);

// The recognizer language, chosen once in settings. Fetched rather than
// baked in, so changing it in the app does not need this page rebuilt.
let language = "";

let want = false;
let live = false;
let armed = false;
let buffer = "";

function show(kind, label, note) {
  dot.className = "dot " + kind;
  state.textContent = label;
  if (note !== undefined) detail.textContent = note;
}

// --- talking to the PC ---------------------------------------------------

async function post(path, body) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["X-WinWhispr-Token"] = token;
  const res = await fetch(path, { method: "POST", headers, body: JSON.stringify(body) });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

async function flush() {
  const text = buffer.trim();
  buffer = "";
  if (!text) {
    show("idle", "Ready", "Nothing heard.");
    return;
  }
  show("busy", "Typing\u2026", text);
  try {
    const result = await post("/api/final", { text });
    show("idle", "Ready", result.pasted ? "Typed at your cursor." : "Typing is disabled on the PC.");
    // Between utterances is free time: pick up a language changed in settings
    // without the user having to restart anything.
    loadLanguage().then(applyLanguage);
  } catch (err) {
    show("error", "Could not reach WinWhispr", String(err.message || err));
  }
}

// --- the recognizer ------------------------------------------------------

let recognition = null;

async function loadLanguage() {
  try {
    const health = await (await fetch("/api/health")).json();
    // "auto" means follow the operating system, which is what the browser
    // already reports; leaving it empty does exactly that.
    language = health.language && health.language !== "auto" ? health.language : "";
  } catch {
    language = "";
  }
}

function currentLang() {
  return language || navigator.language || "en-US";
}

function applyLanguage() {
  if (recognition) recognition.lang = currentLang();
}

function build() {
  const rec = new Recognition();
  rec.continuous = true;
  rec.interimResults = true;
  rec.lang = currentLang();

  rec.onresult = (event) => {
    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const chunk = event.results[i][0].transcript;
      if (event.results[i].isFinal) buffer += chunk;
      else interim += chunk;
    }
    if (want) show("live", "Listening", (buffer + interim).trim() || "\u2026");
  };

  rec.onerror = (event) => {
    if (event.error === "no-speech" || event.error === "aborted") return;
    if (event.error === "not-allowed" || event.error === "service-not-allowed") {
      armed = false;
      arm.hidden = false;
      show("error", "Microphone blocked", "Allow the microphone for this page, then arm it again.");
      return;
    }
    show("error", "Recognizer error", event.error);
  };

  // Chrome ends a session on its own after a lull, and after every stop().
  // Restarting while the key is still held is what makes a long dictation
  // look like one continuous take; otherwise it goes deaf mid-sentence.
  rec.onend = () => {
    live = false;
    if (want) start();
    else flush();
  };

  return rec;
}

function start() {
  if (live || !armed) return;
  try {
    recognition.start();
    live = true;
  } catch {
    // start() throws if the previous session has not finished unwinding yet;
    // onend will call back here.
  }
}

function stop() {
  if (live) recognition.stop();
  else flush();
}

// --- the hotkey, arriving from the PC ------------------------------------

function listen() {
  const url = "/api/events" + (token ? "?token=" + encodeURIComponent(token) : "");
  const stream = new EventSource(url);

  stream.onmessage = (event) => {
    const next = !!JSON.parse(event.data).listening;
    if (next === want) return;
    want = next;
    if (want) {
      buffer = "";
      show("live", "Listening", "\u2026");
      start();
    } else {
      stop();
    }
  };

  stream.onopen = () => {
    if (armed && !want) show("idle", "Ready", "Hold Right Ctrl anywhere on the PC.");
  };

  // EventSource reconnects by itself; say so rather than looking broken.
  stream.onerror = () => {
    if (!want) show("error", "Reconnecting\u2026", "WinWhispr is not answering.");
  };
}

// --- arming --------------------------------------------------------------

// The microphone prompt needs a click, and Chrome only remembers the grant
// after one. Arming is that click: it starts and immediately stops a session
// so every later start is silent.
arm.addEventListener("click", async () => {
  arm.disabled = true;
  try {
    await navigator.mediaDevices.getUserMedia({ audio: true });
    armed = true;
    arm.hidden = true;
    show("idle", "Ready", "Hold Right Ctrl anywhere on the PC.");
  } catch {
    show("error", "Microphone blocked", "Allow the microphone for this page and try again.");
  } finally {
    arm.disabled = false;
  }
});

if (!Recognition) {
  arm.hidden = true;
  show("error", "No speech engine here", "This page needs Chrome or Edge. Firefox has no recognizer.");
} else {
  recognition = build();
  show("idle", "Not armed", "Tap once to allow the microphone.");
  // The language must be known before a session starts, not before the page
  // renders, so this does not block arming.
  loadLanguage().then(applyLanguage);
  listen();
}
