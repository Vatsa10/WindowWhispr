"""API keys, stored in Windows Credential Manager.

Never in ``config.json``: that file is plain text, gets copied around, and ends
up in screenshots. ``keyring`` puts the value in the OS credential store, where
it is protected by the user's login.

An environment variable is honoured as a fallback so a developer can run with a
throwaway key without saving it anywhere.
"""

from __future__ import annotations

import logging
import os

_log = logging.getLogger("winwhispr.secrets")

SERVICE = "WinWhispr"

#: logical name -> environment variable consulted when the store has nothing.
ENV_FALLBACKS = {"groq_api_key": "GROQ_API_KEY"}


def get_key(name: str) -> str:
    """Return the stored key, or the environment fallback, or ""."""
    try:
        import keyring

        value = keyring.get_password(SERVICE, name)
        if value and value.strip():
            return value.strip()
    except Exception as exc:  # pragma: no cover - backend dependent
        _log.warning("Could not read %s from the credential store: %s", name, exc)

    env = ENV_FALLBACKS.get(name)
    if env:
        return (os.environ.get(env) or "").strip()
    return ""


def set_key(name: str, value: str) -> bool:
    """Store (or clear, when ``value`` is empty) a key. True when it stuck."""
    try:
        import keyring

        if value and value.strip():
            keyring.set_password(SERVICE, name, value.strip())
        else:
            try:
                keyring.delete_password(SERVICE, name)
            except Exception:
                pass  # nothing stored is the state we wanted anyway
        return True
    except Exception as exc:  # pragma: no cover - backend dependent
        _log.warning("Could not write %s to the credential store: %s", name, exc)
        return False


def has_key(name: str) -> bool:
    return bool(get_key(name))
