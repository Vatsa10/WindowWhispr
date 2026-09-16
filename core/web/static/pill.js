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

//: How long to let Chrome finish a take after being asked to stop, before
//: aborting it outright. Long enough for a normal finalisation, short enough
//: that a stuck recognizer does not look like a hung app.
const STOP_GRACE_MS = 1200;

//: How many times the speech service may fail to answer before the pill stops
//: calling it a blip and says so. The recognizer restarts itself between
//: these, so this is a count of attempts, not of seconds.
const NETWORK_RETRIES = 3;

//: Base wait before retrying a failed service, multiplied by how many times it
//: has failed in a row, so a service having a bad moment is given longer each
//: time rather than being hammered.
const NETWORK_RETRY_MS = 400;

const token = new URLSearchParams(location.search).get("token")
  || localStorage.getItem("winwhispr-token")
  || "";
if (token) localStorage.setItem("winwhispr-token", token);

// The window host is the process that launched this page: it owns the Edge
// window the page is drawn in and is the only thing that can move or resize
// it. It says so by putting its control port in the URL, so a page opened in
// an ordinary browser simply has no host and every call below is a no-op.
const CONTROL_PORT = new URLSearchParams(location.search).get("ctl");

// Kept as a promise because the rest of the file waits on it before asking for
// its first resize -- the port is known at load time now, but a host that
// arrives later would only have to resolve this.
export const bridgeReady = Promise.resolve(Boolean(CONTROL_PORT));

// Every call goes through here. A missing host, or a host without this route,
// must never take the UI down. The reply is never read: these are all side
// effects on a window, and keepalive lets them survive the page being busy.
function bridge(method, value) {
  if (!CONTROL_PORT) return false;
  const route = BRIDGE_ROUTES[method];
  if (!route) return false;
  const query = value === undefined ? "" : "?v=" + encodeURIComponent(value);
  try {
    fetch("http://127.0.0.1:" + CONTROL_PORT + route + query,
          { mode: "no-cors", keepalive: true }).catch(() => {});
    return true;
  } catch {
    return false;
  }
}

const BRIDGE_ROUTES = {
  set_size: "/size",
  set_corner: "/corner",
  open_app: "/open-app",
  drag: "/drag",
  quit: "/quit",
};

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
  //: The part of the buffer already typed by streaming.
  const streamed = useRef("");
  //: start() has been called but onstart has not arrived. Calling start()
  //: again in that window throws and desynchronises everything.
  const starting = useRef(false);
  const stopTimer = useRef(0);
  //: Consecutive "network" errors. Reset by any successful result, and by
  //: each new press, so a bad minute never poisons the next take.
  const networkFailures = useRef(0);
  const retryTimer = useRef(0);

  const [needsArming, setNeedsArming] = useState(true);

  // Phrases typed already, so the release does not type them a second time.
  const sendPhrase = useCallback((chunk) => {
    const phrase = (chunk || "").trim();
    if (!phrase) return;
    streamed.current += chunk;
    post("/api/stream", { text: phrase }).catch(() => {
      // A failed phrase stays in the buffer, so the release still types it.
      streamed.current = streamed.current.slice(0, -chunk.length);
    });
  }, []);

  const flush = useCallback(async () => {
    // Only what streaming did not already type: normally nothing, but a
    // phrase the recognizer never finalised still has to reach the document.
    const text = buffer.current.slice(streamed.current.length).trim();
    const spoke = buffer.current.trim();
    buffer.current = "";
    streamed.current = "";
    if (!text && spoke) {
      // Everything was typed as it was said. Say so rather than "nothing
      // heard", which would be a lie about a take that worked.
      onSize("dot");
      return onStatus("idle", "Ready");
    }
    if (!text) {
      onSize("dot");
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
        if (!want.current) onSize("dot");
      }, SHRINK_DELAY_MS);
    } catch (err) {
      onStatus("error", "Not connected", String(err.message || err));
    }
  }, [onStatus, onSize]);

  // `live` is set by the recognizer's own onstart/onend, never here. Setting
  // it optimistically was the whole bug: start() throws if the recognizer is
  // still running, the throw was swallowed, and `live` stayed false while the
  // recognizer stayed on. After that the state was wrong forever -- releasing
  // the key called flush() instead of stop(), so nothing ended, and the next
  // press could not start anything either.
  const start = useCallback(() => {
    if (live.current || starting.current || !armed.current || !recognition.current) {
      return;
    }
    starting.current = true;
    try {
      recognition.current.start();
    } catch {
      // Already running: onend will arrive and drive the next decision.
      starting.current = false;
    }
  }, []);

  // Asking Chrome to stop is a request, not a guarantee -- it can sit there
  // with the take open. Without this the pill stays green with the key long
  // released and nothing ever typed.
  const stop = useCallback(() => {
    if (!recognition.current) return;
    try {
      recognition.current.stop();
    } catch { /* not running */ }
    clearTimeout(stopTimer.current);
    stopTimer.current = setTimeout(() => {
      if (!live.current || want.current) return;
      try {
        recognition.current.abort();   // abort always ends it
      } catch { /* already gone */ }
      live.current = false;
      flush();
    }, STOP_GRACE_MS);
  }, [flush]);

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
      // Anything came back, so whatever was wrong with the service is over.
      networkFailures.current = 0;
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const chunk = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          buffer.current += chunk;
          // Typed the moment the recognizer commits to it, so the words land
          // in the document while you are still talking. Interim words are
          // not sent: the recognizer revises those, and text already typed
          // into somebody else's application cannot be taken back.
          sendPhrase(chunk);
        } else {
          interim += chunk;
        }
      }
      if (want.current) {
        const heard = (buffer.current + interim).trim();
        onStatus("live", "Listening", heard || "…");
      }
    };

    rec.onstart = () => {
      starting.current = false;
      live.current = true;
    };

    rec.onerror = (event) => {
      if (event.error === "no-speech" || event.error === "aborted") return;

      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        armed.current = false;
        setNeedsArming(true);
        return onStatus("error", "Microphone blocked",
          "Allow the microphone for this page, then arm it again.");
      }

      // "network" means the microphone worked and the speech service did not
      // answer. It is usually brief, and onend restarts the take by itself, so
      // the first few are reported as reconnecting rather than as a failure --
      // an error message for something that fixes itself in a second teaches
      // people to distrust the error messages that matter.
      if (event.error === "network") {
        networkFailures.current += 1;
        if (networkFailures.current < NETWORK_RETRIES && want.current) {
          return onStatus("busy", "Reconnecting…", "The speech service did not answer.");
        }
        // Naming the setting matters: the microphone plainly works, so
        // "check your connection" sends people to look at the wrong thing.
        // Windows blocks the speech service outright until online speech
        // recognition has been accepted, and that is where this usually ends.
        return onStatus("error", "Speech service refused",
          "Turn on Settings > Privacy > Speech > Online speech recognition.");
      }

      onStatus("error", "Recognizer error", event.error);
    };

    rec.onend = () => {
      starting.current = false;
      live.current = false;
      clearTimeout(stopTimer.current);
      if (!want.current) return flush();

      // Straight back in after a normal end, so a pause mid-sentence does not
      // cost a word. After a network failure, a beat first: restarting
      // instantly against a service that just refused would spend every retry
      // inside the same bad second and report failure before it had waited at
      // all.
      if (networkFailures.current > 0) {
        clearTimeout(retryTimer.current);
        retryTimer.current = setTimeout(() => {
          if (want.current) start();
        }, NETWORK_RETRY_MS * networkFailures.current);
        return;
      }
      start();
    };

    recognition.current = rec;
    return () => {
      rec.onend = null;   // do not restart a recognizer that is going away
      clearTimeout(retryTimer.current);
      try { rec.abort(); } catch { /* already stopped */ }
    };
  }, [onStatus, start, flush, sendPhrase]);

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

  const arm = useCallback(async (silent) => {
    // Try it without asking first. The window this runs in grants the
    // microphone to its own page, so in the normal case there is nothing for
    // the user to approve and no reason to make them tap a button every
    // launch. The button only appears when this actually fails.
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Release it immediately: the recognizer opens its own, and holding a
      // second one lights the microphone-in-use indicator for no reason.
      stream.getTracks().forEach((track) => track.stop());
      armed.current = true;
      setNeedsArming(false);
      onSize("dot");
      onStatus("idle", "Ready");
      loadLanguage();
      return true;
    } catch {
      if (!silent) {
        onStatus("error", "Microphone blocked",
          "Allow the microphone for this page and try again.");
      }
      return false;
    }
  }, [onStatus, onSize, loadLanguage]);

  // On every launch, once. A failure here is not an error the user needs to
  // see -- it just means the button stays up and they tap it.
  useEffect(() => {
    if (!Recognition) return;
    arm(true);
  }, [arm]);

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
        streamed.current = "";
        networkFailures.current = 0;
        clearTimeout(shrinkTimer.current);
        clearTimeout(stopTimer.current);
        onSize("live");
        onStatus("live", "Listening", "…");
        start();
        clearTimeout(retryTimer.current);
      } else if (live.current || starting.current) {
        // Still running, or still coming up: stop() covers both, because its
        // watchdog fires whether or not onstart ever arrived.
        stop();
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
  // Waits for the bridge rather than assuming it, so the very first size --
  // the one that shrinks the window to a dot -- is never the one that is lost.
  useEffect(() => {
    let cancelled = false;
    bridgeReady.then(() => { if (!cancelled) bridge("set_size", size); });
    return () => { cancelled = true; };
  }, [size]);

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
    onSize("dot");
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
    return html`<div class="overlay arm">
      <button type="button" onClick=${() => arm(false)}>
        Tap to enable the microphone
      </button>
    </div>`;
  }

  const openApp = () => bridge("open_app", location.origin + "/app");

  // Idle is a dot. There is no room in it for a word, and after a day of
  // seeing it there is no need for one either.
  if (size === "dot") {
    return html`<div class="dot-wrap" onDoubleClick=${openApp}
      title=${`WinWhispr - ${status.label}`}>
      <span class=${"dot-core " + status.kind}></span>
    </div>`;
  }

  return html`<div class="pill" onDoubleClick=${openApp}>
    <span class=${"led " + status.kind}></span>
    <div class="lines">
      <div class="state">${status.label}</div>
      <div class="detail" role="status" aria-live="polite">${status.detail}</div>
    </div>
    ${status.kind === "live" && html`<${Icon} name="mic" size=${15} />`}
  </div>`;
}

ReactDOM.createRoot(document.getElementById("root")).render(html`<${Pill} />`);
