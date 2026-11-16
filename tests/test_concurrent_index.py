"""Cross-process append safety for ``library/index.jsonl`` (round 42, limitation G3).

The fix is only worth anything if it survives *real* concurrent writers, so these
tests spawn actual processes (not threads) that append to one index concurrently.
"""
from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

import pytest

from cifkit.locks import LockTimeout, append_jsonl_locked, file_lock

WRITER = """
import json, sys, time
from cifkit.locks import append_jsonl_locked
path, worker, count = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
for index in range(count):
    append_jsonl_locked(path, {"worker": worker, "index": index,
                               "payload": "x" * 200}, timeout=30, fsync=False)
"""


def _run_writers(target: Path, workers: int, per_worker: int) -> None:
    script = target.parent / "writer.py"
    script.write_text(WRITER, encoding="utf-8")
    procs = [mp.Process(target=_spawn, args=(script, target, worker, per_worker))
             for worker in range(workers)]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(timeout=120)
        assert proc.exitcode == 0, f"writer exited {proc.exitcode}"


def _spawn(script: Path, target: Path, worker: int, per_worker: int) -> None:
    import subprocess
    import sys

    proc = subprocess.run([sys.executable, str(script), str(target), str(worker), str(per_worker)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise AssertionError(f"writer {worker} failed ({proc.returncode}):\n"
                             f"{proc.stdout[-500:]}\n{proc.stderr[-1500:]}")


def test_concurrent_appends_produce_no_torn_lines(tmp_path):
    target = tmp_path / "index.jsonl"
    workers, per_worker = 4, 15
    _run_writers(target, workers, per_worker)

    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == workers * per_worker
    records = [json.loads(line) for line in lines]   # every line must parse
    assert len({(r["worker"], r["index"]) for r in records}) == workers * per_worker
    assert not (target.parent / "index.jsonl.lock").exists(), "lock must be released"


def test_lock_is_exclusive(tmp_path):
    lock_path = tmp_path / "x.lock"
    with file_lock(lock_path, timeout=5):
        assert lock_path.exists()
        with pytest.raises(LockTimeout):
            with file_lock(lock_path, timeout=0.2):
                pass
    assert not lock_path.exists()


def test_stale_lock_is_reclaimed(tmp_path):
    import os
    import time

    lock_path = tmp_path / "y.lock"
    lock_path.write_text("pid=1 ts=0", encoding="utf-8")
    old = time.time() - 10_000
    os.utime(lock_path, (old, old))
    with file_lock(lock_path, timeout=2, stale=60):
        assert lock_path.exists()
    assert not lock_path.exists()


def test_append_creates_parent_directories(tmp_path):
    target = tmp_path / "deep" / "nested" / "index.jsonl"
    append_jsonl_locked(target, {"ok": True})
    assert json.loads(target.read_text(encoding="utf-8").strip()) == {"ok": True}


def test_atomic_write_survives_concurrent_thread_writers(tmp_path):
    """Round 57 adversarial F4/G10: the temp name used to contain only the pid,
    so two *threads* writing the same target shared one tmp file and clobbered
    each other (PermissionError / torn content).  Unique tmp names + a bounded
    replace retry must let every writer succeed and leave no tmp files behind."""
    import threading

    from cifkit.locks import atomic_write_json

    target = tmp_path / "out" / "manifest.json"
    errors: list[Exception] = []

    def writer(worker: int) -> None:
        try:
            for _ in range(20):
                atomic_write_json(target, {"worker": worker, "payload": "x" * 500})
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(w,)) for w in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not errors, errors
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["worker"] in (0, 1, 2, 3)  # one complete write won
    assert list(tmp_path.joinpath("out").glob("*.tmp*")) == []
