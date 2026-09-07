// The page. One button, a transcript, and the two engines behind createListener.
//
// Web Speech is the primary path and the reason this front end exists: Chrome
// and Edge return a transcript the instant you stop talking, with no model to
// download and no audio leaving the browser process. The recorder path is the
// fallback for browsers without it, and sends audio to this machine's Whisper.
//
// Dictation appends rather than replaces, because a second thought after a
// pause is a continuation, not a correction of the first one.

import { api, createListener, webSpeechAvailable } from "/static/app.js";

// --- DOM lookups, once ------------------------------------------------

const talk = document.getElementById("talk");
const talkIconUse = talk.querySelector(".talk-icon use");
const talkLabel = document.getElementById("talk-label");
const waveform = document.getElementById("waveform");
const text = document.getElementById("text");
const status = document.getElementById("status");
const engineLabel = document.getElementById("engine");
const continuousBox = document.getElementById("continuous");
const autosendBox = document.getElementById("autosend");
const autosendWrap = document.getElementById("autosend-wrap");
const sendBtn = document.getElementById("send");
const copyBtn = document.getElementById("copy");
const copyLabel = copyBtn.querySelector("span");
const clearBtn = document.getElementById("clear");

const COPY_LABEL = copyLabel.textContent;
const STATUS_CLEAR_MS = 4000;
const COPY_RESET_MS = 2000;

// Seam for Task 3: `createWaveform(canvas)` from waveform.js will be attached
// here and its returned `onLevel`-style callback wired into runTake(). Until
// then the level callback is a no-op so nothing touches the DOM.
let waveformRenderer = null; // set by Task 3, e.g. waveformRenderer = createWaveform(waveform);
function onLevel(level) {
  waveformRenderer?.onLevel?.(level);
}

let listener = null;
let session = false;   // the user wants to dictate; survives individual takes
let statusClearTimer = 0;
let copyResetTimer = 0;

// --- persisted toggles -------------------------------------------------

// Remember the toggles, so a phone propped up for dictation comes back the
// way it was left.
const remembered = (key, box, fallback) => {
  const saved = localStorage.getItem(key);
  box.checked = saved === null ? fallback : saved === "1";
  box.addEventListener("change", () => localStorage.setItem(key, box.checked ? "1" : "0"));
};
remembered("winwhispr-continuous", continuousBox, true);
remembered("winwhispr-autosend", autosendBox, false);

// --- status line ---------------------------------------------------------

function setStatus(message, kind) {
  clearTimeout(statusClearTimer);
  status.textContent = message || "";
  status.className = "status" + (kind ? " " + kind : "");
  // Errors stay put until the next action; everything else fades on its own.
  if (message && kind !== "error") {
    statusClearTimer = setTimeout(() => {
      status.textContent = "";
      status.className = "status";
    }, STATUS_CLEAR_MS);
  }
}

// --- talk button visual state --------------------------------------------

function setTalkState(listening) {
  talk.setAttribute("aria-pressed", listening ? "true" : "false");
  talkIconUse.setAttribute("href", listening ? "#icon-stop" : "#icon-mic");
}

function setTalkBusy(busy) {
  talk.disabled = busy;
}

// --- transcript ------------------------------------------------------

function append(transcript) {
  if (!transcript) return;
  const existing = text.value.trim();
  text.value = existing ? existing + " " + transcript : transcript;
  text.scrollTop = text.scrollHeight;
}

async function tidy(raw) {
  // The same rules the desktop app applies: fillers, stutters, spoken
  // punctuation, capitalization, snippets. Failure returns the raw words.
  const res = await api("/api/tidy", { text: raw });
  if (res?.error === "unauthorized") {
    askForToken();
    return raw;
  }
  return res && res.text ? res.text : raw;
}

async function sendToPc(body) {
  const res = await api("/api/paste", { text: body });
  if (res?.error === "unauthorized") {
    askForToken();
    return false;
  }
  if (res?.error) {
    setStatus(res.error + " Check that WinWhispr is still running on the PC, then try again.", "error");
    return false;
  }
  return true;
}

// A server reachable from the network asks for a token. Prompting once and
// storing it beats printing instructions nobody reads.
function askForToken() {
  const entered = window.prompt(
    "This WinWhispr is on your network and needs its access token.\n" +
    "It was printed in the terminal that started it."
  );
  if (entered) {
    localStorage.setItem("winwhispr-token", entered.trim());
    setStatus("Token saved. Tap the mic to try again.");
  } else {
    setStatus("A token is required to reach this WinWhispr. Enter it to continue.", "error");
  }
}

// --- session state machine -----------------------------------------------
//
// A dictation session is a loop of takes. Web Speech ends a take at every real
// pause, which is what makes the transcript arrive instantly; re-arming keeps
// the session alive so a pause to think does not mean pressing the button
// again.

async function runTake() {
  listener = createListener();
  setTalkState(true);
  talkLabel.textContent = "Listening...";

  const result = await listener.listen({
    onLevel,
    onPartial: (partial) => {
      // Web Speech streams partials, so the words appear as they are spoken.
      talkLabel.textContent = partial ? partial.slice(-70) : "Listening...";
    },
    onPhase: (phase) => {
      if (phase === "thinking") talkLabel.textContent = "Transcribing...";
    },
    onError: (message) => setStatus(message + " Tap the mic to try again.", "error"),
  });

  onLevel(0);
  return result;
}

async function runSession() {
  session = true;
  setStatus("");

  try {
    while (session) {
      const result = await runTake();

      if (result === null) break;            // cancelled, or already reported
      if (result === "") {
        if (!continuousBox.checked) {
          setStatus("Nothing heard. Tap the mic and try speaking again.");
          break;
        }
        continue;                            // silence: just listen again
      }

      setTalkBusy(true);
      try {
        const cleaned = await tidy(result);
        append(cleaned);

        if (autosendBox.checked && !autosendWrap.hidden) {
          const sent = await sendToPc(cleaned);
          setStatus(sent ? "Typed on the PC." : "");
        } else {
          setStatus("");
        }
      } finally {
        setTalkBusy(false);
      }

      if (!continuousBox.checked) break;
    }
  } finally {
    session = false;
    setTalkState(false);
    setTalkBusy(false);
    talkLabel.textContent = "Tap to talk";
    onLevel(0);
  }
}

function stopSession() {
  session = false;
  listener?.stop();
}

// --- wiring ----------------------------------------------------------

talk.addEventListener("click", () => {
  if (talk.disabled) return;
  if (session) stopSession();
  else runSession();
});

// Space toggles, the way a key does on the desktop — except while typing in
// the transcript, where space is just a space.
document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && document.activeElement !== text) {
    e.preventDefault();
    talk.click();
  }
  if (e.key === "Escape" && session) {
    session = false;
    listener?.cancel();
  }
});

copyBtn.addEventListener("click", async () => {
  if (!text.value.trim()) return;
  try {
    await navigator.clipboard.writeText(text.value);
    confirmCopy("Copied");
  } catch {
    // Clipboard access needs a secure context, which plain http on a LAN
    // address is not. Selecting the text is the honest fallback.
    text.select();
    setStatus("Clipboard is unavailable here. Press Ctrl+C to copy the selection.", "error");
  }
});

function confirmCopy(message) {
  clearTimeout(copyResetTimer);
  copyLabel.textContent = message;
  copyResetTimer = setTimeout(() => {
    copyLabel.textContent = COPY_LABEL;
  }, COPY_RESET_MS);
}

clearBtn.addEventListener("click", () => {
  text.value = "";
  setStatus("");
  text.focus();
});

sendBtn.addEventListener("click", async () => {
  const body = text.value.trim();
  if (!body) return;
  if (await sendToPc(body)) setStatus("Sent to the focused window on the PC.");
});

// Say which engine is in use, because the two behave differently: the browser
// one streams partials as you speak, the server one arrives all at once.
(async () => {
  const local = webSpeechAvailable();
  let health = {};
  try {
    health = await (await fetch("/api/health")).json();
  } catch {
    setStatus("WinWhispr is not reachable from here. Check the PC is on and reload this page.", "error");
  }

  const canPaste = !!health.paste;
  sendBtn.hidden = !canPaste;
  autosendWrap.hidden = !canPaste;

  if (local) {
    engineLabel.textContent = "Browser speech engine - instant, nothing to install";
  } else if (health.server_stt) {
    engineLabel.textContent = "Local Whisper on the PC - this browser has no speech engine";
  } else {
    engineLabel.textContent = "No speech engine available";
    talk.disabled = true;
  }
})();
