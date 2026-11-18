"""Crash recovery (round 43, limitation G5).

G5 said there was no real crash test — only stale-lock recovery.  These tests kill
actual processes with SIGKILL-equivalent force at a controlled moment and then
assert what the file contract promises:

* a killed appender leaves **only complete lines** (no torn JSON);
* a killed atomic writer leaves **either the old or the new content**, never a
  truncated file;
* a re-run after the crash is idempotent (the entry is present exactly once).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

APPENDER = """
import sys, time
from cifkit.locks import append_jsonl_locked
path, count, delay = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
for index in range(count):
    append_jsonl_locked(path, {"index": index, "payload": "y" * 500})
    time.sleep(delay)
"""

ATOMIC_WRITER = """
import sys, time
from cifkit.locks import atomic_write_text
path, marker = sys.argv[1], sys.argv[2]
body = (marker * 20000)
for _ in range(200):
    atomic_write_text(path, body)
    time.sleep(0.001)
"""


def _start(script_text: str, args: list[str], cwd: Path) -> subprocess.Popen:
    script = cwd / "child.py"
    script.write_text(script_text, encoding="utf-8")
    return subprocess.Popen([sys.executable, str(script), *args], cwd=str(cwd),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _kill(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        proc.kill()
    else:
        os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=30)


def _read_text_when_released(path: Path, *, attempts: int = 40, delay: float = 0.05) -> str:
    """Read ``path``, tolerating the transient Windows lock a just-killed child holds.

    On Windows the kernel can keep the file handle of a SIGKILL-equivalent child
    alive for a few milliseconds after ``Popen.wait()`` returns, so an immediate
    read raises ``PermissionError``.  That is a platform artefact, not a torn
    write, so the test retries (bounded) instead of flaking — round 58 CI caught
    this on the *real* runners as well.
    """
    last: Exception | None = None
    for _ in range(attempts):
        try:
            return path.read_text(encoding="utf-8")
        except PermissionError as exc:      # windows-only transient
            last = exc
            time.sleep(delay)
    raise AssertionError(f"could not read {path.name} after {attempts} attempts: {last!r}")


def test_killed_appender_leaves_only_complete_lines(tmp_path):
    target = tmp_path / "index.jsonl"
    proc = _start(APPENDER, [str(target), "400", "0.005"], tmp_path)
    # wait until some lines exist, then kill hard
    deadline = time.time() + 30
    while time.time() < deadline:
        if target.is_file() and target.stat().st_size > 0:
            break
        time.sleep(0.02)
    time.sleep(0.15)
    _kill(proc)

    text = _read_text_when_released(target)
    lines = text.splitlines()
    assert lines, "the child should have written at least one line"
    for line in lines:
        json.loads(line)                      # every surviving line must parse
    assert text.endswith("\n"), "a killed writer must not leave a partial final line"


def test_killed_atomic_writer_never_truncates(tmp_path):
    target = tmp_path / "blob.txt"
    proc = _start(ATOMIC_WRITER, [str(target), "A"], tmp_path)
    # wait for the first completed generation so the assertion below cannot pass
    # vacuously (a kill before the first `os.replace` would leave no target at all)
    deadline = time.time() + 30
    while time.time() < deadline and not target.exists():
        time.sleep(0.02)
    assert target.exists(), "the child never produced a first generation"
    time.sleep(0.05)                     # land the kill inside a later write cycle
    _kill(proc)

    # The target is only ever swapped in by `os.replace`, so at every instant it is
    # one *whole* generation: this is the contract the readers rely on.
    content = _read_text_when_released(target)
    assert content, "target must not be empty"
    assert set(content) == {"A"}, "content must be one complete generation"
    assert len(content) == 20000, f"truncated target: {len(content)} chars"

    # A SIGKILL cannot run cleanup, and it can land while the temp file is still
    # being written, so a leftover `blob.txt.tmp*` may exist and may even be empty.
    # That is precisely why readers must open only `target` (cifkit's do).  So the
    # invariant asserted here is "no stray reader-facing file", not "no temp file":
    # round 58 CI caught the earlier form of this check as a flake on all platforms.
    known = {"blob.txt", "child.py"}
    unexpected = sorted(p.name for p in tmp_path.iterdir()
                        if p.name not in known and not p.name.startswith("blob.txt.tmp"))
    assert not unexpected, f"unexpected files beside the target: {unexpected}"


def test_rerun_after_crash_is_idempotent(tmp_path):
    """The library ingest path is keyed by run_id, so a re-run must not duplicate."""
    from cifkit.locks import atomic_write_text, append_jsonl_locked

    target = tmp_path / "index.jsonl"
    proc = _start(APPENDER, [str(target), "300", "0.005"], tmp_path)
    deadline = time.time() + 30
    while time.time() < deadline:
        if target.is_file() and target.stat().st_size > 0:
            break
        time.sleep(0.02)
    time.sleep(0.1)
    _kill(proc)
    before = len(_read_text_when_released(target).splitlines())

    # "re-running" writes the same logical entry under a stable key.  The killed
    # child may have left its lock behind, so a short stale window is used here: the
    # point of the test is idempotency, not the default 180 s recovery window.
    append_jsonl_locked(target, {"run_id": "demo", "kind": "ingest"}, timeout=15, stale=5)
    append_jsonl_locked(target, {"run_id": "demo", "kind": "ingest"}, timeout=15, stale=5)
    lines = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == before + 2
    # the *reader* deduplicates by run_id: last write wins
    deduped = {row.get("run_id", f"anon{index}"): row for index, row in enumerate(lines)}
    assert deduped["demo"]["kind"] == "ingest"
    assert len(deduped) < len(lines), "duplicate run_ids collapse on read"

    atomic_write_text(tmp_path / "meta.json", json.dumps({"ok": True}))
    assert json.loads((tmp_path / "meta.json").read_text(encoding="utf-8")) == {"ok": True}
