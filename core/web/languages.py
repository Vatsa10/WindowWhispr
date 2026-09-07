"""The languages the browser recognizer can be set to.

Chosen once, in settings, and then left alone -- the point of a dictation app
is that it works without being configured every time. The value is a BCP-47
tag because that is what ``SpeechRecognition.lang`` takes.

This list is deliberately short: it is the languages Edge and Chrome recognize
well, not every tag they will accept. A tag they accept but transcribe badly
is worse than one that is missing, because the user blames the app.
"""

from __future__ import annotations

#: Follow the operating system's language rather than pinning one.
AUTO = "auto"

#: (tag, display name), in the order the dropdown shows them.
LANGUAGES: tuple[tuple[str, str], ...] = (
    (AUTO, "Automatic (system language)"),
    ("en-US", "English (United States)"),
    ("en-GB", "English (United Kingdom)"),
    ("en-IN", "English (India)"),
    ("en-AU", "English (Australia)"),
    ("hi-IN", "Hindi"),
    ("es-ES", "Spanish (Spain)"),
    ("es-MX", "Spanish (Mexico)"),
    ("fr-FR", "French"),
    ("de-DE", "German"),
    ("it-IT", "Italian"),
    ("pt-BR", "Portuguese (Brazil)"),
    ("nl-NL", "Dutch"),
    ("pl-PL", "Polish"),
    ("ru-RU", "Russian"),
    ("tr-TR", "Turkish"),
    ("ar-SA", "Arabic"),
    ("zh-CN", "Chinese (Mandarin, Simplified)"),
    ("zh-TW", "Chinese (Mandarin, Traditional)"),
    ("ja-JP", "Japanese"),
    ("ko-KR", "Korean"),
    ("id-ID", "Indonesian"),
    ("vi-VN", "Vietnamese"),
    ("th-TH", "Thai"),
    ("sv-SE", "Swedish"),
    ("da-DK", "Danish"),
    ("nb-NO", "Norwegian"),
    ("fi-FI", "Finnish"),
    ("cs-CZ", "Czech"),
    ("uk-UA", "Ukrainian"),
    ("he-IL", "Hebrew"),
    ("el-GR", "Greek"),
)

TAGS = frozenset(tag for tag, _ in LANGUAGES)


def display_name(tag: str) -> str:
    """The name for a tag, or the tag itself if it is not one we list."""
    for known, name in LANGUAGES:
        if known == tag:
            return name
    return tag


def normalize(tag: str) -> str:
    """A stored setting into a tag we are willing to use.

    Case and separator are forgiving because this value survives config files,
    hand edits and older releases; anything unrecognized falls back to
    following the system rather than failing to dictate at all.
    """
    cleaned = (tag or "").strip().replace("_", "-")
    if not cleaned or cleaned.lower() == AUTO:
        return AUTO
    for known in TAGS:
        if known.lower() == cleaned.lower():
            return known
    # "en" should still find "en-US" rather than silently becoming Automatic.
    prefix = cleaned.split("-", 1)[0].lower()
    for known, _ in LANGUAGES:
        if known.split("-", 1)[0].lower() == prefix:
            return known
    return AUTO
