// The pill, in React.
//
// You arm it once and then forget it exists. From that point the hotkey on the
// PC drives it: hold the talk key in any application, speak, let go, and the
// words are typed where your cursor already was. Edge does the listening and
// the transcribing; the app owns the hotkey and the typing.
//
// Why refs and not state for the recognizer: the browser's speech object stops
// whenever it feels like it and has to be restarted underneath the user, and
// its `onend` handler is a closure created once. Reading React state in there
// would read the value from the render that installed it -- stale by exactly
// the amount that matters. Refs always read now. State is only what the pill
// draws.

import { html, ReactDOM, useCallback, useEffect, useRef, useState } from "/static/app/react.js";
import { Icon } from "/static/app/ui.js";

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;

//: How long a finished transcript stays readable before the pill shrinks.
const SHRINK_DELAY_MS = 2200;

const token = new URLSearchParams(location.search).get("token")
  || localStorage.getItem("winwhispr-token")
  || "";
if (token) localStorage.setItem("winwhispr-token", token);

// The native bridge is optional. pywebview injects `window.pywebview.api`
// only once the window is bound, and a build without a method simply does not
// have it -- neither may take the UI down, so every call goes through here.
function bridge(method, ...args) {
  const api = window.pywebview && window.pywebview.api;
  const fn = api && api[method];
  if (typeof fn !== "function") return false;
  try {
    const result = fn.apply(api, args);
    // pywebview returns a promise; a rejection here is not the page's problem.
    if (result && typeof result.catch === "function") result.catch(() => {});
    return true;
  } catch {
    return false;
  }
}

async function post(path, body) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["X-WinWhispr-Token"] = token;
  const res = await fetch(path, { method: "POST", headers, body: JSON.stringify(body) });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

// --- the recognizer -------------------------------------------------------

function useRecognizer({ onStatus, onSize }) {
  const want = useRef(false);      // the hotkey is held (pushed from the PC)
  const live = useRef(false);      // recognition is actually running
  const armed = useRef(false);     // the microphone has been granted
  const buffer = useRef("");       // finals collected since the key went down
  const language = useRef("");
  const recognition = useRef(null);
  const shrinkTimer = useRef(0);

  const [needsArming, setNeedsArming] = useState(true);

  const flush = useCallback(async () => {
    const text = buffer.current.trim();
    buffer.current = "";
    if (!text) {
      onSize("idle");
      return onStatus("idle", "Ready");
    }
    onSize("live");
    onStatus("busy", "Typing…", text);
    try {
      const result = await post("/api/final", { text });
      onStatus("idle", "Ready",
        result.pasted ? "Typed at your cursor." : "Typing is disabled on the PC.");
      // Shrink a moment later, so the words that were just typed stay
      // readable rather than vanishing with the window they were in.
      clearTimeout(shrinkTimer.current);
      shrinkTimer.current = setTimeout(() => {
        if (!want.current) onSize("idle");
      }, SHRINK_DELAY_MS);
    } catch (err) {
      onStatus("error", "Not connected", String(err.message || err));
    }
  }, [onStatus, onSize]);

  const start = useCallback(() => {
    if (live.current || !armed.current || !recognition.current) return;
    try {
      recognition.current.start();
      live.current = true;
    } catch {
      // start() throws while a previous session is still unwinding; onend
      // calls back here when it has.
    }
  }, []);

  // Built once. Chrome ends a session on its own after a lull and after every
  // stop(), so restarting while the key is still held is what makes a long
  // dictation behave as one take instead of going deaf mid-sentence.
  useEffect(() => {
    if (!Recognition) return;
    const rec = new Recognition();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = language.current || navigator.language || "en-US";

    rec.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const chunk = event.results[i][0].transcript;
        if (event.results[i].isFinal) buffer.current += chunk;
        else interim += chunk;
      }
      if (want.current) {
        onStatus("live", "Listening", (buffer.current + interim).trim() || "…");
      }
    };

    rec.onerror = (event) => {
      if (event.error === "no-speech" || event.error === "aborted") return;
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        armed.current = false;
        setNeedsArming(true);
        return onStatus("error", "Microphone blocked",
          "Allow the microphone for this page, then arm it again.");
      }
      onStatus("error", "Recognizer error", event.error);
    };

    rec.onend = () => {
      live.current = false;
      if (want.current) start();
      else flush();
    };

    recognition.current = rec;
    return () => {
      rec.onend = null;   // do not restart a recognizer that is going away
      try { rec.abort(); } catch { /* already stopped */ }
    };
  }, [onStatus, start, flush]);

  const loadLanguage = useCallback(async () => {
    try {
      const health = await (await fetch("/api/health")).json();
      // "auto" means follow the operating system, which is what the browser
      // already reports; leaving it empty does exactly that.
      language.current = health.language && health.language !== "auto" ? health.language : "";
    } catch {
      language.current = "";
    }
    if (recognition.current) {
      recognition.current.lang = language.current || navigator.language || "en-US";
    }
  }, []);

  const arm = useCallback(async () => {
    // The microphone prompt needs a click, and the grant is only remembered
    // after one.
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true });
      armed.current = true;
      setNeedsArming(false);
      onSize("idle");
      onStatus("idle", "Ready");
      loadLanguage();
    } catch {
      onStatus("error", "Microphone blocked",
        "Allow the microphone for this page and try again.");
    }
  }, [onStatus, onSize, loadLanguage]);

  // The hotkey, arriving from the PC over server-sent events rather than a
  // poll: Chrome throttles timers in a background tab to once a minute, so a
  // polled pill would answer the key a minute late.
  useEffect(() => {
    if (!Recognition) return undefined;
    const url = "/api/events" + (token ? "?token=" + encodeURIComponent(token) : "");
    const stream = new EventSource(url);

    stream.onmessage = (event) => {
      const message = JSON.parse(event.data);
      // The tray asks for the settings window through here, because the
      // windows live in this process rather than the one with the tray icon.
      if (message.open_app) return void bridge("open_app", location.origin + "/app");
      const next = !!message.listening;
      if (next === want.current) return;
      want.current = next;
      if (next) {
        buffer.current = "";
        clearTimeout(shrinkTimer.current);
        onSize("live");
        onStatus("live", "Listening", "…");
        start();
      } else if (live.current) {
        recognition.current?.stop();
      } else {
        flush();
      }
    };

    stream.onopen = () => {
      if (armed.current && !want.current) onStatus("idle", "Ready");
    };
    // EventSource reconnects by itself; say so rather than looking broken.
    stream.onerror = () => {
      if (!want.current) onStatus("error", "Reconnecting…", "WinWhispr is not answering.");
    };

    return () => stream.close();
  }, [onStatus, onSize, start, flush]);

  useEffect(() => { loadLanguage(); }, [loadLanguage]);

  return { needsArming, arm, supported: !!Recognition };
}

// --- the pill -------------------------------------------------------------

function Pill() {
  const [status, setStatus] = useState({ kind: "idle", label: "Starting…", detail: "" });
  const [size, setSizeState] = useState("arm");
  const [menuOpen, setMenuOpen] = useState(false);

  const onStatus = useCallback((kind, label, detail = "") => {
    setStatus({ kind, label, detail });
  }, []);

  // Naming a state is all the page does. Telling the host to resize is a side
  // effect, so it belongs in an effect -- React runs a state updater during
  // render, and a throw in there unmounts the whole tree rather than failing
  // the one call.
  const onSize = useCallback((next) => setSizeState(next), []);

  const { needsArming, arm, supported } = useRecognizer({ onStatus, onSize });

  useEffect(() => {
    if (!supported) {
      onStatus("error", "No speech engine", "This window needs the WebView2 runtime.");
    } else if (needsArming) {
      onStatus("idle", "Not armed", "Tap once to allow the microphone.");
    }
  }, [supported, needsArming, onStatus]);

  // The host process owns the geometry; this is the one place that tells it.
  useEffect(() => { bridge("set_size", size); }, [size]);

  // The body carries both states: the pill's offset shadow changes colour with
  // status, and the idle size hides the second line.
  useEffect(() => {
    document.body.className = `size-${size} state-${status.kind}`;
  }, [size, status.kind]);

  const openMenu = useCallback((event) => {
    event.preventDefault();
    if (needsArming) return;
    setMenuOpen(true);
    onSize("menu");
  }, [needsArming, onSize]);

  const closeMenu = useCallback(() => {
    setMenuOpen(false);
    onSize("idle");
  }, [onSize]);

  useEffect(() => {
    document.addEventListener("contextmenu", openMenu);
    return () => document.removeEventListener("contextmenu", openMenu);
  }, [openMenu]);

  if (menuOpen) {
    return html`<div class="overlay menu">
      <button class="quit" type="button"
        onClick=${() => bridge("quit")}>Quit WinWhispr</button>
      <button type="button" onClick=${closeMenu}>Keep running</button>
    </div>`;
  }

  if (needsArming && supported) {
    return html`<button class="overlay arm" type="button" onClick=${arm}>
      Tap to enable the microphone
    </button>`;
  }

  return html`<div class="pill"
    onDoubleClick=${() => bridge("open_app", location.origin + "/app")}>
    <span class=${"dot " + status.kind}></span>
    <div class="lines">
      <div class="state">${status.label}</div>
      <div class="detail" role="status" aria-live="polite">${status.detail}</div>
    </div>
    ${status.kind === "live" && html`<${Icon} name="mic" size=${15} />`}
  </div>`;
}

ReactDOM.createRoot(document.getElementById("root")).render(html`<${Pill} />`);
