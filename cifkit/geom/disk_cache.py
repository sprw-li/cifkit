"""On-disk slab cache (round 47, limitation G2).

The slab memo was **in-process only** (24 entries), so a batch of separate processes
recomputed identical slabs.  This adds a small file-backed layer under the project
cache:

* key = the same tuple the in-process cache uses (structure digest + all geometry
  arguments), stored as ``<sha1>.json`` with the slab as CIF text;
* writes are atomic and locked (``cifkit.locks``), so concurrent processes cannot
  publish half an entry;
* **any** problem (missing dir, unreadable/corrupt JSON, CIF that no longer parses)
  degrades to a cache miss — the cache must never break geometry;
* disabled by ``CIFKIT_SLAB_DISK_CACHE=0``.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from cifkit.locks import atomic_write_text, file_lock

#: bump whenever the on-disk *format* changes: older entries are then ignored and
#: removed, because serving them would silently change the returned types/values.
CACHE_VERSION = 2

#: counters are process-local observability only (tests / 'slab cache info')
_STATS = {"disk_hits": 0, "disk_misses": 0, "disk_writes": 0, "disk_corrupt": 0,
          "disk_disabled": 0}



_TUPLE_MARKER = "__cifkit_tuple__"


def _encode(value: Any) -> Any:
    """JSON-safe copy that preserves tuples (lists must stay lists)."""
    if isinstance(value, tuple):
        return {_TUPLE_MARKER: [_encode(item) for item in value]}
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _encode(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _decode(value: Any) -> Any:
    if isinstance(value, dict):
        if list(value.keys()) == [_TUPLE_MARKER]:
            return tuple(_decode(item) for item in value[_TUPLE_MARKER])
        return {key: _decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode(item) for item in value]
    return value

def enabled() -> bool:
    return os.environ.get("CIFKIT_SLAB_DISK_CACHE", "1").strip().lower() not in (
        "0", "false", "no", "off")


def cache_dir() -> Path:
    """Where disk entries live (``$CIFKIT_CACHE`` else ``<project>/_cache``)."""
    override = os.environ.get("CIFKIT_CACHE")
    if override:
        base = Path(override)
    else:
        from cifkit.provenance import project_root

        base = project_root() / "_cache"
    return base / "slabs"


def _canonical(key: tuple[Any, ...]) -> str:
    """Canonical text for a key: JSON so nested tuples/lists compare equal."""
    return json.dumps(list(key), ensure_ascii=False, sort_keys=True, default=str)


def _digest(key: tuple[Any, ...]) -> str:
    return hashlib.sha1(_canonical(key).encode("utf-8")).hexdigest()


def _entry_path(key: tuple[Any, ...]) -> Path:
    return cache_dir() / f"{_digest(key)}.json"


def lookup(key: tuple[Any, ...]) -> tuple[Any, dict[str, Any]] | None:
    """Return ``(structure, info)`` from disk, or ``None`` on any problem."""
    if not enabled():
        _STATS["disk_disabled"] += 1
        return None
    path = _entry_path(key)
    if not path.is_file():
        _STATS["disk_misses"] += 1
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("cache_version") != CACHE_VERSION:
            raise ValueError(f"cache version {payload.get('cache_version')!r} "
                             f"!= {CACHE_VERSION}")
        stored = payload.get("digest")
        if stored is not None and stored != _digest(key):
            raise ValueError("key mismatch")
        if stored is None and json.dumps(payload.get("key") or [], sort_keys=True,
                                         default=str) != _canonical(key):
            # JSON turns tuples into lists, so compare canonical text, not objects
            raise ValueError("key mismatch")
        from pymatgen.core import Structure

        structure = Structure.from_str(payload["cif"], fmt="cif")
        decoded = _decode(payload.get("info") or {})
        info = dict(decoded) if isinstance(decoded, dict) else {}
    except Exception:  # noqa: BLE001 - a bad cache entry is a miss, never an error
        _STATS["disk_corrupt"] += 1
        with contextlib.suppress(OSError):
            path.unlink()
        return None
    _STATS["disk_hits"] += 1
    return structure, info


def store(key: tuple[Any, ...], structure: Any, info: dict[str, Any]) -> bool:
    """Persist ``structure`` under ``key``; best-effort, never raises."""
    if not enabled():
        return False
    try:
        from pymatgen.io.cif import CifWriter

        text = str(CifWriter(structure, symprec=None))
        payload = json.dumps({"cache_version": CACHE_VERSION, "digest": _digest(key),
                              "key": _encode(key), "info": _encode(info), "cif": text},
                             ensure_ascii=False, default=str)
        path = _entry_path(key)
        with file_lock(path.with_suffix(".lock"), timeout=30):
            atomic_write_text(path, payload)
        _STATS["disk_writes"] += 1
        return True
    except Exception:  # noqa: BLE001
        return False


def stats() -> dict[str, Any]:
    return {**_STATS, "dir": str(cache_dir()), "enabled": enabled()}


def clear() -> int:
    """Remove every cached entry; returns how many files were deleted."""
    removed = 0
    directory = cache_dir()
    if directory.is_dir():
        for path in directory.glob("*.json"):
            with contextlib.suppress(OSError):
                path.unlink()
                removed += 1
    for key in _STATS:
        _STATS[key] = 0
    return removed


__all__ = ["enabled", "cache_dir", "lookup", "store", "stats", "clear"]
