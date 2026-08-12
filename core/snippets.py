"""Text expansion: say a short trigger, paste a long block.

Signatures, addresses, boilerplate — the things that are tedious to dictate and
that speech recognition mangles anyway. Triggers match as whole phrases,
case-insensitively, anywhere in the transcript.

Storage is the same shape as the dictionary: a small JSON file the user can
also edit by hand.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

_log = logging.getLogger("winwhispr.snippets")


def expand(text: str, table: dict) -> str:
    """Replace every whole-phrase trigger in ``text`` with its expansion.

    Longest triggers win, so "my work email" beats "my email".
    """
    if not text or not table:
        return text or ""
    out = text
    for trigger in sorted(table, key=len, reverse=True):
        out = _replace_phrase(out, trigger, str(table[trigger]))
    return out


def _replace_phrase(text: str, phrase: str, replacement: str) -> str:
    """Case-insensitive whole-phrase replacement.

    Hand-rolled rather than a regex so the boundary rule ("not alphanumeric on
    either side") is stated once and cannot be defeated by a trigger containing
    regex metacharacters.
    """
    phrase = phrase.strip()
    if not phrase:
        return text
    lowered = text.lower()
    needle = phrase.lower()
    out = []
    i = 0
    n = len(text)
    step = len(needle)
    while i < n:
        j = lowered.find(needle, i)
        if j == -1:
            out.append(text[i:])
            break
        before_ok = j == 0 or not text[j - 1].isalnum()
        after = j + step
        after_ok = after == n or not text[after].isalnum()
        if before_ok and after_ok:
            out.append(text[i:j])
            out.append(replacement)
            i = after
        else:
            out.append(text[i:after])
            i = after
    return "".join(out)


def load(path: Path | str) -> dict:
    """Read the snippet table; a missing or broken file means no snippets."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return {str(k): str(v) for k, v in raw.get("snippets", {}).items() if str(k).strip()}
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        _log.warning("Could not read snippets (%s); continuing without them", exc)
        return {}


def save(path: Path | str, table: dict) -> None:
    path = Path(path)
    tmp = f"{path}.tmp"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"snippets": table}, fh, indent=2)
        os.replace(tmp, path)
    except OSError as exc:
        _log.warning("Could not write snippets: %s", exc)
        try:
            os.remove(tmp)
        except OSError:
            pass
