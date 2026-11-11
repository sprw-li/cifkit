"""Cross-platform advisory file locks + atomic writes for cache/index files.

Why: several ``cifkit`` commands (``fetch``, ``pipeline``, ``batch``) can run in
parallel processes and share the same cache directory (``$CIFKIT_CACHE`` or
``<project>/_cache``).  Building the CoRE index or writing JSON metadata while
another process reads it can corrupt the cache, so writers take a lock and
replace files atomically.

The lock is an ``O_CREAT|O_EXCL`` lock file next to the protected path; stale
locks (older than ``stale`` seconds, e.g. after a crash) are removed.  This is
advisory only: readers that do not use :func:`file_lock` can still see a
partially written file unless writers use :func:`atomic_write_text`.
"""
from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any, Iterator


class LockTimeout(RuntimeError):
    """Raised when a lock cannot be acquired within the timeout."""


@contextlib.contextmanager
def file_lock(
    path: str | Path,
    *,
    timeout: float = 60.0,
    stale: float = 180.0,
    poll: float = 0.05,
) -> Iterator[Path]:
    """Acquire an advisory lock file at ``path`` (``.lock`` suffix recommended)."""
    lock = Path(path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(0.0, timeout)
    handle: int | None = None
    while True:
        try:
            handle = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(handle, f"pid={os.getpid()} ts={time.time():.3f}".encode())
            break
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                age = 0.0
            if age > stale:
                # crashed writer: best-effort stale-lock removal and retry
                with contextlib.suppress(OSError):
                    lock.unlink()
                continue
            if time.monotonic() >= deadline:
                raise LockTimeout(f"等待文件锁超时：{lock}（{timeout:.1f}s）")
            time.sleep(poll)
    try:
        yield lock
    finally:
        if handle is not None:
            with contextlib.suppress(OSError):
                os.close(handle)
        with contextlib.suppress(OSError):
            lock.unlink()


def atomic_write_text(path: str | Path, text: str, *, encoding: str = "utf-8") -> Path:
    """Write ``text`` to ``path`` atomically (same-directory temp file + ``os.replace``)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.tmp{os.getpid()}")
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, target)
    finally:
        with contextlib.suppress(OSError):
            if tmp.exists():
                tmp.unlink()
    return target


def atomic_write_json(path: str | Path, data: Any, *, ensure_ascii: bool = False) -> Path:
    return atomic_write_text(path, json.dumps(data, ensure_ascii=ensure_ascii, separators=(",", ":")))

def append_jsonl_locked(
    path: str | Path,
    data: Any,
    *,
    timeout: float = 60.0,
    stale: float = 180.0,
    fsync: bool = True,
    ensure_ascii: bool = False,
) -> Path:
    """Append one JSON object as a line, holding a lock across the write.

    Round 42 (limitation G3): ``library/index.jsonl`` was appended without any
    cross-process coordination, so two concurrent ``--ingest`` runs could interleave
    (a reader could even observe a half-written line).  Locking around the write and
    ``fsync``-ing makes the append atomic *as observed by other lock users*, and the
    newline is written in the same call so a torn line cannot survive a crash.

    Readers that do not take the lock can still see a partial line mid-write; the
    documented contract is "no half-lines survive a crash", not "lock-free readers
    are safe".  ``iter_index`` in :mod:`cifkit.provenance` skips unparsable lines so
    a lock-free reader degrades to skipping rather than crashing.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(data, ensure_ascii=ensure_ascii) + "\n"
    with file_lock(target.with_name(f"{target.name}.lock"), timeout=timeout, stale=stale):
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            if fsync:
                os.fsync(handle.fileno())
    return target
