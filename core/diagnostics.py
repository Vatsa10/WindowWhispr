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
}


def diagnose(kind: Failure) -> Diagnostic:
    """Return the user-facing copy for ``kind``."""
    headline, detail = _COPY[kind]
    return Diagnostic(kind=kind, headline=headline, detail=detail)


def all_diagnostics() -> list[Diagnostic]:
    """Every diagnostic, for tests and for an onboarding self-check screen."""
    return [diagnose(kind) for kind in Failure]
