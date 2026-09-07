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

const talk = document.getElementById("talk");
const talkLabel = document.getElementById("talk-label");
const waveform = document.getElementById("waveform");
const text = document.getElementById("text");
const status = document.getElementById("status");
const engineLabel = document.getElementById("engine");
const continuousBox = document.getElementById("continuous");
const autosendBox = document.getElementById("autosend");
const autosendWrap = document.getElementById("autosend-wrap");
const sendBtn = document.getElementById("send");

const BARS = 12;
const bars = [];
for (let i = 0; i < BARS; i++) {
  const bar = document.createElement("i");
  waveform.appendChild(bar);
  bars.push(bar);
}

let listener = null;
let session = false;   // the user wants to dictate; survives individual takes
let listening = false; // a take is in flight right now

// Remember the toggles, so a phone propped up for dictation comes back the
// way it was left.
const remembered = (key, box, fallback) => {
  const saved = localStorage.getItem(key);
  box.checked = saved === null ? fallback : saved === "1";
  box.addEventListener("change", () => localStorage.setItem(key, box.checked ? "1" : "0"));
};
remembered("winwhispr-continuous", continuousBox, true);
remembered("winwhispr-autosend", autosendBox, false);

function setLevel(level) {
  // Each bar gets a phase offset so the row reads as motion rather than a
  // single block rising and falling.
  bars.forEach((bar, i) => {
    const wobble = 0.75 + 0.25 * Math.sin(Date.now() / 180 + i);
    const height = Math.max(0.12, Math.min(1, level * wobble));
    bar.style.transform = "scaleY(" + height.toFixed(3) + ")";
  });
}

function setStatus(message, kind) {
  status.textContent = message || "";
  status.className = "status" + (kind ? " " + kind : "");
}

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
    setStatus(res.error, "error");
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
    setStatus("Token saved. Try again.");
  } else {
    setStatus("A token is required to reach this WinWhispr.", "error");
  }
}

async function runTake() {
  listener = createListener();
  listening = true;
  talk.classList.add("live");
  talkLabel.textContent = "Listening...";

  const result = await listener.listen({
    onLevel: setLevel,
    onPartial: (partial) => {
      // Web Speech streams partials, so the words appear as they are spoken.
      talkLabel.textContent = partial ? partial.slice(-70) : "Listening...";
    },
    onPhase: (phase) => {
      if (phase === "thinking") talkLabel.textContent = "Transcribing...";
    },
    onError: (message) => setStatus(message, "error"),
  });

  listening = false;
  setLevel(0);
  return result;
}

// A dictation session is a loop of takes. Web Speech ends a take at every real
// pause, which is what makes the transcript arrive instantly; re-arming keeps
// the session alive so a pause to think does not mean pressing the button
// again.
async function runSession() {
  session = true;
  talk.classList.add("live");
  setStatus("");

  while (session) {
    const result = await runTake();

    if (result === null) break;            // cancelled, or already reported
    if (result === "") {
      if (!continuousBox.checked) {
        setStatus("Nothing heard.");
        break;
      }
      continue;                            // silence: just listen again
    }

    const cleaned = await tidy(result);
    append(cleaned);

    if (autosendBox.checked && !autosendWrap.hidden) {
      const sent = await sendToPc(cleaned);
      setStatus(sent ? "Typed on the PC." : "");
    } else {
      setStatus("");
    }

    if (!continuousBox.checked) break;
  }

  session = false;
  talk.classList.remove("live");
  talkLabel.textContent = "Tap to talk";
  setLevel(0);
}

function stopSession() {
  session = false;
  listener?.stop();
}

talk.addEventListener("click", () => {
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

document.getElementById("copy").addEventListener("click", async () => {
  if (!text.value.trim()) return;
  try {
    await navigator.clipboard.writeText(text.value);
    setStatus("Copied.");
  } catch {
    // Clipboard access needs a secure context, which plain http on a LAN
    // address is not. Selecting the text is the honest fallback.
    text.select();
    setStatus("Press Ctrl+C to copy.");
  }
});

document.getElementById("clear").addEventListener("click", () => {
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
    setStatus("WinWhispr is not reachable from here.", "error");
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
