"""The personal dictionary: names and terms speech recognition keeps missing.

Entries are handed to the cleanup model as a *spelling authority*, never
string-substituted into the transcript. That distinction is the whole point:
substitution would corrupt homophones ("Mark" the person vs "mark the date"),
while telling the model "when this text refers to that entry, spell it this
way" keeps the decision context-aware.

Only the entries phonetically relevant to the current utterance are sent —
fewer distractors, higher precision.

Ported from WhimprFlow's ``whimpr-core/src/dictionary/mod.rs``.
"""

from __future__ import annotations

import json
import logging
import os
import string
import threading
from dataclasses import dataclass, field
from pathlib import Path

from core.dictionary.similarity import close

_log = logging.getLogger("winwhispr.dictionary")

#: Most entries to send with one utterance. A long vocabulary block costs
#: prefill latency and dilutes the model's attention.
MAX_VOCAB = 15

SOURCE_MANUAL = "manual"
SOURCE_AUTO = "auto"


@dataclass
class DictionaryEntry:
    """An authoritative spelling plus the mishears that map to it."""

    correct: str
    mishears: list[str] = field(default_factory=list)
    #: "manual" (typed by the user) or "auto" (learned from a correction).
    source: str = SOURCE_MANUAL

    def to_json(self) -> dict:
        return {"correct": self.correct, "mishears": list(self.mishears),
                "source": self.source}

    @classmethod
    def from_json(cls, raw: dict) -> "DictionaryEntry":
        return cls(
            correct=str(raw.get("correct", "")).strip(),
            mishears=[str(m).strip() for m in raw.get("mishears", []) if str(m).strip()],
            source=str(raw.get("source", SOURCE_MANUAL)),
        )


class DictionaryStore:
    """A JSON-backed dictionary. Never raises for a missing or corrupt file."""

    def __init__(self, path: Path | str):
        self._path = Path(path)
        self._entries: list[DictionaryEntry] = []
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    def entries(self) -> list[DictionaryEntry]:
        with self._lock:
            return list(self._entries)

    def load(self) -> "DictionaryStore":
        with self._lock:
            self._entries = []
            try:
                with open(self._path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                self._entries = [
                    e for e in (DictionaryEntry.from_json(r) for r in raw.get("entries", []))
                    if e.correct
                ]
            except FileNotFoundError:
                pass
            except (OSError, json.JSONDecodeError, AttributeError) as exc:
                # A broken dictionary must never block dictation.
                _log.warning("Could not read dictionary (%s); starting empty", exc)
        return self

    def save(self) -> None:
        with self._lock:
            payload = {"entries": [e.to_json() for e in self._entries]}
        tmp = f"{self._path}.tmp"
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp, self._path)
        except OSError as exc:
            _log.warning("Could not write dictionary: %s", exc)
            try:
                os.remove(tmp)
            except OSError:
                pass

    def add(self, correct: str, mishears=(), source: str = SOURCE_MANUAL) -> bool:
        """Add or extend an entry. Returns True when something changed.

        Matching on ``correct`` is case-insensitive, and an existing entry keeps
        its original source — an auto-learned hit on a word the user typed by
        hand must not demote it to a machine guess.
        """
        correct = (correct or "").strip()
        if not correct:
            return False
        new_mishears = [str(m).strip() for m in mishears if str(m).strip()]
        with self._lock:
            for entry in self._entries:
                if entry.correct.lower() == correct.lower():
                    known = {m.lower() for m in entry.mishears}
                    added = [m for m in new_mishears
                             if m.lower() not in known and m.lower() != correct.lower()]
                    if not added:
                        return False
                    entry.mishears.extend(added)
                    self.save()
                    return True
            self._entries.append(
                DictionaryEntry(correct=correct, mishears=new_mishears, source=source)
            )
        self.save()
        return True

    def remove(self, correct: str) -> bool:
        """Delete an entry by spelling (case-insensitive)."""
        target = (correct or "").strip().lower()
        with self._lock:
            before = len(self._entries)
            self._entries = [e for e in self._entries if e.correct.lower() != target]
            changed = len(self._entries) != before
        if changed:
            self.save()
        return changed

    def prefilter(self, utterance: str, max_entries: int = MAX_VOCAB) -> list[DictionaryEntry]:
        """The entries phonetically relevant to this utterance."""
        grams = _grams(utterance)
        if not grams:
            return []
        picked: list[DictionaryEntry] = []
        for entry in self.entries():
            targets = [entry.correct.lower()] + [m.lower() for m in entry.mishears]
            if any(close(gram, target) for gram in grams for target in targets):
                picked.append(entry)
                if len(picked) >= max_entries:
                    break
        return picked


def _grams(utterance: str) -> list[str]:
    """Unigrams plus adjacent-pair concatenations.

    The pairs are how a name split across two words gets caught: recognition
    hears "charge bee", the gram "chargebee" matches the entry "ChargeBee".
    """
    words = [w.strip(string.punctuation).lower() for w in (utterance or "").split()]
    words = [w for w in words if w]
    grams = list(words)
    grams.extend(a + b for a, b in zip(words, words[1:]))
    return grams
