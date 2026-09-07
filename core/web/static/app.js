// Voice input in the browser. Two engines, one interface.
//
//   Web Speech API where the browser has one (Chrome, Edge, Safari): streaming
//   partials, its own endpointing, no round trip. The transcript is ready the
//   moment you stop talking.
//
//   MediaRecorder plus this machine's Whisper everywhere else (mainly Firefox):
//   records, detects the pause itself, uploads one WAV. Note the difference
//   from the usual version of this design: the fallback is not a cloud STT
//   vendor, it is the same local model the desktop app uses, so audio never
//   leaves your network either way.

const HANG_MS = 1500;      // trailing quiet that ends a take
const MAX_TAKE_MS = 60000; // hard cap so a stuck mic cannot record forever
const TARGET_SR = 16000;

export async function api(path, body) {
  try {
    const headers = { "Content-Type": "application/json" };
    const token = localStorage.getItem("winwhispr-token");
    if (token) headers["X-WinWhispr-Token"] = token;
    const res = await fetch(path, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      return { error: res.status === 401 ? "unauthorized" : "server error " + res.status };
    }
    return await res.json();
  } catch {
    return { error: "could not reach WinWhispr" };
  }
}

class LevelMeter {
  constructor() {
    this.raf = 0;
  }

  async start(onLevel) {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const AC = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AC();
      this.ctx.resume().catch(() => {}); // may start suspended until a gesture
      const src = this.ctx.createMediaStreamSource(this.stream);
      const analyser = this.ctx.createAnalyser();
      analyser.fftSize = 1024;
      src.connect(analyser);
      const buf = new Uint8Array(analyser.fftSize);
      const tick = () => {
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128;
          sum += v * v;
        }
        onLevel(Math.min(1, Math.sqrt(sum / buf.length) * 4));
        this.raf = requestAnimationFrame(tick);
      };
      this.raf = requestAnimationFrame(tick);
    } catch {
      // No meter is survivable; dictation still works without the waveform.
    }
  }

  stop() {
    cancelAnimationFrame(this.raf);
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close().catch(() => {});
    this.stream = undefined;
    this.ctx = undefined;
  }
}

export function encodeWav(samples, sampleRate) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buf);
  const wr = (off, s) => {
    for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i));
  };
  wr(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  wr(8, "WAVE");
  wr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  wr(36, "data");
  view.setUint32(40, samples.length * 2, true);
  let off = 44;
  for (let i = 0; i < samples.length; i++, off += 2) view.setInt16(off, samples[i], true);
  return buf;
}

export function toBase64(buf) {
  const bytes = new Uint8Array(buf);
  let bin = "";
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  return btoa(bin);
}

// MediaRecorder produces webm/opus; the server wants PCM. Decoding and
// resampling here means the machine doing the transcribing does not also pay
// for format conversion.
async function blobToWavBase64(blob) {
  const AC = window.AudioContext || window.webkitAudioContext;
  const tmp = new AC();
  const decoded = await tmp.decodeAudioData(await blob.arrayBuffer());
  tmp.close().catch(() => {});
  const frames = Math.ceil(decoded.duration * TARGET_SR);
  if (frames < 1) return null;
  const OAC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
  const offline = new OAC(1, frames, TARGET_SR);
  const src = offline.createBufferSource();
  src.buffer = decoded;
  src.connect(offline.destination);
  src.start();
  const rendered = await offline.startRendering();
  const ch = rendered.getChannelData(0);
  const pcm = new Int16Array(ch.length);
  for (let i = 0; i < ch.length; i++) {
    const s = Math.max(-1, Math.min(1, ch[i]));
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return toBase64(encodeWav(pcm, TARGET_SR));
}

export function webSpeechAvailable() {
  return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
}

class WebSpeechListener {
  constructor() {
    this.meter = new LevelMeter();
    this.cancelled = false;
    this.label = "browser speech engine";
  }

  listen(cb) {
    return new Promise((resolve) => {
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      const rec = new SR();
      this.rec = rec;
      // en-US on purpose. navigator.language is often en-IN or en-GB, which
      // selects an accent model that mishears more than it helps.
      rec.lang = window.WINWHISPR_LANG || "en-US";
      // continuous, because otherwise the engine finalizes at the first pause
      // and cuts the sentence in half. End of speech is decided below instead:
      // a silence timer, reset every time something is heard.
      rec.continuous = true;
      rec.interimResults = true;
      rec.maxAlternatives = 1;

      let finalText = "";
      let lastFull = "";
      let settled = false;
      let silence = null;
      const clearSil = () => {
        if (silence) {
          clearTimeout(silence);
          silence = null;
        }
      };
      const done = (val) => {
        if (settled) return;
        settled = true;
        clearSil();
        this.meter.stop();
        cb.onLevel?.(0);
        resolve(val);
      };
      const armSilence = () => {
        clearSil();
        silence = setTimeout(() => {
          try {
            rec.stop();
          } catch {}
        }, HANG_MS);
      };

      rec.onresult = (e) => {
        let interim = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const r = e.results[i];
          if (r.isFinal) finalText += r[0].transcript;
          else interim += r[0].transcript;
        }
        lastFull = (finalText + interim).trim();
        cb.onPartial?.(lastFull);
        armSilence();
      };
      rec.onerror = (e) => {
        if (this.cancelled) return done(null);
        if (e?.error === "no-speech") return done("");
        cb.onError?.(e?.error || "speech recognition failed");
        done(null);
      };
      // Prefer accumulated finals; fall back to the last interim when the
      // engine did not finalize the tail before stopping.
      rec.onend = () => done(this.cancelled ? null : finalText.trim() || lastFull);

      this.meter.start((l) => cb.onLevel?.(l));
      try {
        rec.start();
      } catch {
        done(null);
      }
    });
  }

  stop() {
    try {
      this.rec?.stop();
    } catch {}
  }

  cancel() {
    this.cancelled = true;
    try {
      this.rec?.abort();
    } catch {}
    this.meter.stop();
  }
}

class RecorderListener {
  constructor() {
    this.cancelled = false;
    this.stopped = false;
    this.label = "local Whisper";
  }

  pickMime() {
    const options = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
    for (const m of options) {
      if (window.MediaRecorder?.isTypeSupported(m)) return m;
    }
    return "";
  }

  async listen(cb) {
    this.cancelled = false;
    this.stopped = false;
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      cb.onError?.("microphone permission denied");
      return null;
    }
    // A cancel during the permission prompt must not leave the mic open.
    if (this.cancelled) {
      stream.getTracks().forEach((t) => t.stop());
      return null;
    }

    const AC = window.AudioContext || window.webkitAudioContext;
    const ctx = new AC();
    ctx.resume().catch(() => {});
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(analyser);
    const buf = new Uint8Array(analyser.fftSize);

    const mime = this.pickMime();
    const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    this.rec = rec;
    const chunks = [];
    rec.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data);
    };
    rec.start(100);

    const blob = await new Promise((resolve) => {
      let spoke = false;
      let lastVoice = performance.now();
      let noiseFloor = 0.015; // adapts, so endpointing survives a noisy room
      const startedAt = performance.now();
      let raf = 0;

      const finish = () => {
        if (this.stopped) return;
        this.stopped = true;
        cancelAnimationFrame(raf);
        rec.onstop = () => {
          stream.getTracks().forEach((t) => t.stop());
          ctx.close().catch(() => {});
          resolve(chunks.length ? new Blob(chunks, { type: chunks[0].type }) : null);
        };
        try {
          rec.stop();
        } catch {
          resolve(null);
        }
      };
      this.finish = finish;

      const tick = () => {
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128;
          sum += v * v;
        }
        const rms = Math.sqrt(sum / buf.length);
        cb.onLevel?.(Math.min(1, rms * 4));
        const now = performance.now();
        const threshold = Math.max(0.012, noiseFloor * 2.2);
        if (rms > threshold) {
          spoke = true;
          lastVoice = now;
        } else {
          noiseFloor = noiseFloor * 0.97 + rms * 0.03;
        }
        const ended = spoke && now - lastVoice > HANG_MS && now - startedAt > 450;
        if (ended || now - startedAt > MAX_TAKE_MS) {
          finish();
          return;
        }
        raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    });

    cb.onLevel?.(0);
    if (this.cancelled || !blob) return null;
    cb.onPhase?.("thinking");

    const wav = await blobToWavBase64(blob).catch(() => null);
    if (!wav) {
      cb.onError?.("could not encode the recording");
      return null;
    }
    const res = await api("/api/stt", { audio: wav });
    if (!res || res.error) {
      cb.onError?.(res?.error || "transcription failed");
      return null;
    }
    return (res.text || "").trim();
  }

  stop() {
    this.finish?.();
  }

  cancel() {
    this.cancelled = true;
    this.finish?.();
  }
}

export function createListener() {
  return webSpeechAvailable() ? new WebSpeechListener() : new RecorderListener();
}
