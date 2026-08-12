"""What WinWhispr has downloaded, and how to get the space back.

Model weights are large, easy to accumulate by trying a few models, and
invisible: nobody goes looking in ``~/.cache`` to find out that a speech model
they used once is still holding a gigabyte. This module lists what is on disk
and deletes what is not wanted.

Everything lives under ``paths.data_dir()``, and deletion refuses to touch
anything outside it — a bug here would delete a user's files, so the boundary
is enforced rather than assumed.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from core import paths

_log = logging.getLogger("winwhispr.models")

#: Directory name -> what it holds, for the listing.
_KINDS = {
    "whisper": "Speech model (faster-whisper)",
    "asr": "Speech model (OpenVINO)",
    "llm": "Cleanup model (OpenVINO)",
    "vad": "Voice activity detection",
}


@dataclass(frozen=True)
class StoredModel:
    name: str
    kind: str
    path: Path
    size_bytes: int
    #: True when deleting this would break the current configuration.
    in_use: bool = False

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)

    def describe(self) -> str:
        flag = "  (in use)" if self.in_use else ""
        return f"{self.size_mb:8.0f} MB  {self.kind:32} {self.name}{flag}"


def _display_name(directory_name: str) -> str:
    """Turn a cache directory name into the model id a person recognizes.

    Hugging Face names directories ``models--Owner--repo``; showing that to
    someone deciding what to delete is needless decoding work.
    """
    if directory_name.startswith("models--"):
        return directory_name[len("models--"):].replace("--", "/")
    return directory_name.replace("--", "/")


def directory_size(path: Path) -> int:
    """Bytes used by a directory tree. Unreadable entries count as zero."""
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    pass
    except OSError:  # pragma: no cover - permissions
        pass
    return total


def installed(active_models: tuple[str, ...] = ()) -> list[StoredModel]:
    """Every downloaded model, largest first.

    ``active_models`` are marked in use so the caller can refuse to delete
    what the app is configured to run.
    """
    out: list[StoredModel] = []
    root = paths.models_dir()
    active = {a.lower() for a in active_models if a}

    for kind_dir, kind_label in _KINDS.items():
        directory = root / kind_dir
        if not directory.is_dir():
            continue
        for entry in sorted(directory.iterdir()):
            # Skip the download machinery's own bookkeeping directories: they
            # are not models and listing them invites deleting them.
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            name = _display_name(entry.name)
            out.append(
                StoredModel(
                    name=name,
                    kind=kind_label,
                    path=entry,
                    size_bytes=directory_size(entry),
                    in_use=any(a in name.lower() or name.lower() in a for a in active),
                )
            )
    return sorted(out, key=lambda m: m.size_bytes, reverse=True)


def compile_cache() -> StoredModel:
    """The OpenVINO compile cache: safe to delete, rebuilt on next model load."""
    path = paths.ov_cache_dir()
    return StoredModel(
        name="OpenVINO compile cache",
        kind="Rebuilt automatically when needed",
        path=path,
        size_bytes=directory_size(path),
    )


def total_bytes() -> int:
    return sum(m.size_bytes for m in installed()) + compile_cache().size_bytes


def remove(model: StoredModel) -> bool:
    """Delete a stored model. Returns True when the space was reclaimed."""
    target = model.path.resolve()
    root = paths.data_dir().resolve()
    # Refuse anything outside the app's own directory. This function deletes
    # trees recursively; a wrong path here would be unrecoverable.
    if root not in target.parents:
        _log.error("refusing to delete %s: outside %s", target, root)
        return False
    if not target.is_dir():
        return False
    try:
        shutil.rmtree(target)
        _log.info("removed %s (%.0f MB)", target, model.size_mb)
        return True
    except OSError as exc:
        _log.error("could not remove %s: %s", target, exc)
        return False


def report(active_models: tuple[str, ...] = ()) -> str:
    """A human-readable summary of what is using disk."""
    models = installed(active_models)
    cache = compile_cache()
    lines = [f"Models are stored under {paths.models_dir()}", ""]
    if not models:
        lines.append("  nothing downloaded yet")
    else:
        lines.extend("  " + m.describe() for m in models)
    if cache.size_bytes:
        lines += ["", f"  {cache.size_mb:8.0f} MB  {cache.name} — {cache.kind}"]
    total = sum(m.size_bytes for m in models) + cache.size_bytes
    lines += ["", f"  {total / (1024 ** 3):.2f} GB total"]
    return "\n".join(lines)
