"""Minimal Groq API client: Whisper transcription and chat completions.

Built on ``urllib`` rather than an SDK or ``requests``. Two endpoints and one
auth header do not justify a dependency that PyInstaller then has to bundle.

Every failure is raised as a ``GroqError`` carrying a ``kind``, so callers can
tell "you have no key" from "you are rate limited" from "the network is down"
and show the user something useful instead of a stack trace.
"""

from __future__ import annotations

import io
import json
import logging
import urllib.error
import urllib.request
import uuid
import wave

_log = logging.getLogger("winwhispr.groq")

BASE_URL = "https://api.groq.com/openai/v1"
TRANSCRIPTION_URL = f"{BASE_URL}/audio/transcriptions"
CHAT_URL = f"{BASE_URL}/chat/completions"

DEFAULT_ASR_MODEL = "whisper-large-v3"
DEFAULT_CHAT_MODEL = "llama-3.3-70b-versatile"

#: Groq rejects uploads past 25 MB. 16-bit 16 kHz mono is 32 KB/s, so a chunk
#: this long lands around 15 MB — comfortably inside the limit with headroom for
#: the multipart envelope.
MAX_CHUNK_SECONDS = 480

REQUEST_TIMEOUT = 60

#: Identify the app. Without this urllib sends "Python-urllib/3.x", which
#: Cloudflare blocks outright (HTTP 403, error 1010) before Groq ever sees the
#: request — indistinguishable from a rejected key unless you read the body.
USER_AGENT = "WinWhispr/0.1.0 (+https://github.com/Vatsa10/WindowWhispr)"


class GroqError(RuntimeError):
    """A Groq request failed. ``kind`` says how."""

    NO_KEY = "no_key"
    AUTH = "auth"
    BLOCKED = "blocked"
    RATE_LIMIT = "rate_limit"
    TOO_LARGE = "too_large"
    SERVER = "server"
    NETWORK = "network"

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def transcribe(audio, api_key: str, model: str = DEFAULT_ASR_MODEL,
               sample_rate: int = 16000, language: str | None = "en") -> str:
    """Transcribe float32 mono audio. Long audio is sent in sequential chunks."""
    if not api_key:
        raise GroqError(GroqError.NO_KEY, "No Groq API key configured.")
    if audio is None or len(audio) == 0:
        return ""

    chunk_samples = MAX_CHUNK_SECONDS * sample_rate
    parts: list[str] = []
    for start in range(0, len(audio), chunk_samples):
        wav = wav_bytes(audio[start:start + chunk_samples], sample_rate)
        fields = {"model": model, "response_format": "json"}
        if language:
            fields["language"] = language
        payload = _post_multipart(TRANSCRIPTION_URL, api_key, fields, wav)
        text = (payload.get("text") or "").strip()
        if text:
            parts.append(text)
    return " ".join(parts).strip()


def chat(messages, api_key: str, model: str = DEFAULT_CHAT_MODEL,
         temperature: float = 0.2, max_tokens: int = 1024) -> str:
    """Run a chat completion and return the assistant's text."""
    if not api_key:
        raise GroqError(GroqError.NO_KEY, "No Groq API key configured.")
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        CHAT_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
        method="POST",
    )
    payload = _send(request)
    choices = payload.get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("message", {}).get("content") or "").strip()


def wav_bytes(audio, sample_rate: int = 16000) -> bytes:
    """Encode float32 mono samples in [-1, 1] as a 16-bit PCM WAV."""
    import numpy as np

    samples = np.asarray(audio, dtype=np.float32)
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return buf.getvalue()


def build_multipart(fields: dict, wav: bytes, boundary: str,
                    filename: str = "audio.wav") -> bytes:
    """Assemble a multipart/form-data body with one file part."""
    crlf = b"\r\n"
    marker = f"--{boundary}".encode("ascii")
    out = bytearray()
    for name, value in fields.items():
        out += marker + crlf
        out += f'Content-Disposition: form-data; name="{name}"'.encode("utf-8") + crlf
        out += crlf
        out += str(value).encode("utf-8") + crlf
    out += marker + crlf
    out += (
        f'Content-Disposition: form-data; name="file"; filename="{filename}"'
    ).encode("utf-8") + crlf
    out += b"Content-Type: audio/wav" + crlf + crlf
    out += wav + crlf
    out += marker + b"--" + crlf
    return bytes(out)


def _post_multipart(url: str, api_key: str, fields: dict, wav: bytes) -> dict:
    boundary = f"----winwhispr{uuid.uuid4().hex}"
    body = build_multipart(fields, wav, boundary)
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
        method="POST",
    )
    return _send(request)


def _send(request) -> dict:
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from exc
    except urllib.error.URLError as exc:
        raise GroqError(GroqError.NETWORK, f"Could not reach Groq: {exc.reason}") from exc
    except (ValueError, TimeoutError) as exc:
        raise GroqError(GroqError.NETWORK, f"Bad response from Groq: {exc}") from exc


def _http_error(exc) -> GroqError:
    status = getattr(exc, "code", 0)
    body = ""
    detail = ""
    try:
        body = exc.read().decode("utf-8", "replace")
        detail = (json.loads(body).get("error", {}) or {}).get("message", "") or body[:200]
    except Exception:
        pass
    if status == 403 and "error code:" in body.lower():
        # Cloudflare's own block page, not a Groq response. Calling this "bad
        # key" sends people off checking a key that was fine all along.
        return GroqError(
            GroqError.BLOCKED,
            f"The request was blocked before reaching Groq ({body.strip()[:80]}).",
        )
    if status in (401, 403):
        return GroqError(GroqError.AUTH, detail or "Groq rejected the API key.")
    if status == 429:
        return GroqError(GroqError.RATE_LIMIT, detail or "Groq rate limit reached.")
    if status == 413:
        return GroqError(GroqError.TOO_LARGE, detail or "Audio too large for Groq.")
    return GroqError(GroqError.SERVER, detail or f"Groq returned HTTP {status}.")
