"""User-facing copy for the ways dictation can fail.

Ported from WhimprFlow's ``whimpr-core/src/diagnostics.rs``, Windows wording
only. The point is that a failure must reach the *user*, not just a log line:
"text is not writing where the cursor is" bug reports trace back to failures
that only ever printed to a console nobody sees.

Pure data — no Qt, no Windows APIs — so every branch is testable anywhere.
Headlines stay short enough to fit the overlay pill without clipping.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

#: Longest headline the pill can show without clipping.
MAX_HEADLINE_CHARS = 40


class Failure(str, Enum):
    """Something went wrong between pressing the key and text appearing."""

    HOTKEY_HOOK_FAILED = "hotkey_hook_failed"
    MIC_BLOCKED = "mic_blocked"
    CLIPBOARD_UNAVAILABLE = "clipboard_unavailable"
    NO_AUDIO_CAPTURED = "no_audio_captured"
    EMPTY_TRANSCRIPT = "empty_transcript"
    ASR_UNAVAILABLE = "asr_unavailable"
    CLOUD_NO_KEY = "cloud_no_key"
    CLOUD_AUTH_REJECTED = "cloud_auth_rejected"
    CLOUD_RATE_LIMITED = "cloud_rate_limited"
    CLOUD_BLOCKED = "cloud_blocked"
    CLOUD_UNREACHABLE = "cloud_unreachable"


@dataclass(frozen=True)
class Diagnostic:
    """A failure rendered for humans."""

    kind: Failure
    headline: str
    detail: str


_COPY: dict[Failure, tuple[str, str]] = {
    Failure.HOTKEY_HOOK_FAILED: (
        "Dictation key isn't wired up",
        "The keyboard hook failed to install. WinWhispr keeps retrying, so this "
        "may clear on its own. If it does not, another app may be holding a "
        "global keyboard hook (some anti-cheat and security tools do) — close "
        "it, or restart WinWhispr.",
    ),
    Failure.MIC_BLOCKED: (
        "Microphone access blocked",
        "Windows is not letting WinWhispr hear you. Open Settings > Privacy & "
        'security > Microphone and turn on "Let desktop apps access your '
        'microphone", then try again.',
    ),
    Failure.CLIPBOARD_UNAVAILABLE: (
        "Couldn't paste",
        "WinWhispr transcribed your speech but could not write it into the "
        "focused app — another app may be holding the clipboard open. Try "
        "again, or paste manually.",
    ),
    Failure.NO_AUDIO_CAPTURED: (
        "No audio came in",
        "The microphone produced silence for that whole session. Check that "
        "the right input device is selected and that the mic is not muted.",
    ),
    Failure.EMPTY_TRANSCRIPT: (
        "Didn't catch that",
        "Audio came through but no words were recognized. Try speaking a "
        "little louder, or closer to the microphone.",
    ),
    Failure.ASR_UNAVAILABLE: (
        "Speech model not ready",
        "The speech-to-text model could not be loaded. Check the model "
        "settings in the sidebar and let the first-run download finish.",
    ),
    Failure.CLOUD_NO_KEY: (
        "Groq API key needed",
        "The selected model runs on Groq, which needs an API key. Paste one "
        "into the Cloud section of the sidebar, or pick a local model to keep "
        "everything on this machine.",
    ),
    Failure.CLOUD_AUTH_REJECTED: (
        "Groq rejected the API key",
        "The key was refused. Check it for a typo, confirm it has not been "
        "revoked, and paste it again in the Cloud section of the sidebar.",
    ),
    Failure.CLOUD_RATE_LIMITED: (
        "Groq rate limit reached",
        "You have used this key's allowance for now (20 requests a minute, "
        "2000 a day). Wait a moment and try again, or switch to a local model "
        "to keep dictating.",
    ),
    Failure.CLOUD_BLOCKED: (
        "Request blocked before Groq",
        "Something between this machine and Groq refused the request — often a "
        "VPN, a corporate proxy, or network filtering. Your API key is fine. "
        "Try a different network, or switch to a local model.",
    ),
    Failure.CLOUD_UNREACHABLE: (
        "Can't reach Groq",
        "The transcription request did not get through. Check your internet "
        "connection, or switch to a local model to work offline.",
    ),
}

#: GroqError.kind -> the failure we show the user.
CLOUD_FAILURES = {
    "no_key": Failure.CLOUD_NO_KEY,
    "auth": Failure.CLOUD_AUTH_REJECTED,
    "rate_limit": Failure.CLOUD_RATE_LIMITED,
    "blocked": Failure.CLOUD_BLOCKED,
    "network": Failure.CLOUD_UNREACHABLE,
    "too_large": Failure.CLOUD_UNREACHABLE,
    "server": Failure.CLOUD_UNREACHABLE,
}


def for_cloud_error(kind: str) -> Diagnostic:
    """Map a Groq failure kind onto user-facing copy."""
    return diagnose(CLOUD_FAILURES.get(kind, Failure.CLOUD_UNREACHABLE))


def diagnose(kind: Failure) -> Diagnostic:
    """Return the user-facing copy for ``kind``."""
    headline, detail = _COPY[kind]
    return Diagnostic(kind=kind, headline=headline, detail=detail)


def all_diagnostics() -> list[Diagnostic]:
    """Every diagnostic, for tests and for an onboarding self-check screen."""
    return [diagnose(kind) for kind in Failure]
