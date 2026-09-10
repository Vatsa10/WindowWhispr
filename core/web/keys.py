"""Which keys can be the talk key, and what they are called.

Right Ctrl is the default because it is under your right hand and nothing else
uses it. Plenty of laptops do not have one -- compact and 60% layouts drop it,
and some ship a Fn key in its place -- so the key is rebindable, and this is
the vocabulary both ends agree on.

The names are the ones the ``keyboard`` library reports from a real key press,
because that is what the hook matches on. Do not invent friendlier spellings
here: a name that does not come back from a real event silently never fires.
"""

from __future__ import annotations

DEFAULT_TALK_KEY = "right ctrl"
DEFAULT_CANCEL_KEY = "esc"

#: Offered in the settings screen, in the order someone would try them.
#: Every one of these is a key that no application binds on its own, which is
#: what makes it safe to hold down for a few seconds.
SUGGESTED_TALK_KEYS: tuple[tuple[str, str], ...] = (
    ("right ctrl", "Right Ctrl"),
    ("right alt", "Right Alt"),
    ("right shift", "Right Shift"),
    ("caps lock", "Caps Lock"),
    ("scroll lock", "Scroll Lock"),
    ("pause", "Pause"),
    ("menu", "Menu"),
    ("insert", "Insert"),
    ("f13", "F13"),
)

#: Keys that must never become the talk key, whatever the user presses.
#: Holding one of these for a sentence would either type into their document
#: or take the keyboard away from every other application.
FORBIDDEN: frozenset[str] = frozenset({
    "space", "enter", "backspace", "tab", "delete",
    "ctrl", "left ctrl", "alt", "left alt", "shift", "left shift",
    "windows", "left windows", "right windows",
    "up", "down", "left", "right",
})


def is_usable(name: str) -> bool:
    """Whether a key can be held down for a sentence without breaking things.

    A single character is rejected too: binding the talk key to "a" means the
    letter never reaches the document again.
    """
    cleaned = (name or "").strip().lower()
    if not cleaned or cleaned in FORBIDDEN:
        return False
    return len(cleaned) > 1


def normalize(name: str, fallback: str = DEFAULT_TALK_KEY) -> str:
    """A key name into one the hook can match, or the fallback."""
    cleaned = (name or "").strip().lower()
    return cleaned if is_usable(cleaned) else fallback


def describe(name: str) -> str:
    """The display name for a key, title-cased if it is not one we list."""
    cleaned = (name or "").strip().lower()
    for known, label in SUGGESTED_TALK_KEYS:
        if known == cleaned:
            return label
    return cleaned.title() if cleaned else ""
