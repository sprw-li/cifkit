"""Cache robustness: advisory file locks, atomic writes, concurrent index builds."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from cifkit.locks import LockTimeout, atomic_write_text, file_lock

ROOT = Path(__file__).resolve().parents[1]


def test_file_lock_acquire_release(tmp_path):
    lock_path = tmp_path / "x.lock"
    with file_lock(lock_path, timeout=2.0):
        assert lock_path.exists()
    assert not lock_path.exists()


def test_file_lock_timeout_when_held(tmp_path):
    lock_path = tmp_path / "held.lock"
    with file_lock(lock_path, timeout=2.0):
        with pytest.raises(LockTimeout):
            with file_lock(lock_path, timeout=0.25):
                pass  # pragma: no cover - should not be reached
    assert not lock_path.exists()


def test_file_lock_removes_stale_lock(tmp_path):
    lock_path = tmp_path / "stale.lock"
    lock_path.write_text("pid=999999 ts=0", encoding="utf-8")
    old = time.time() - 3600
    os.utime(lock_path, (old, old))
    with file_lock(lock_path, timeout=2.0, stale=60.0):
        assert lock_path.exists()
    assert not lock_path.exists()


def test_atomic_write_text_leaves_no_tmp(tmp_path):
    target = tmp_path / "sub" / "index.json"
    atomic_write_text(target, '{"a": 1}')
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
    leftovers = [p.name for p in target.parent.iterdir() if ".tmp" in p.name]
    assert leftovers == []


CACHE_DIR = ROOT / "_cache" / "core-mof-2024"


@pytest.mark.skipif(
    not (CACHE_DIR / "CoREMOF2024DB.zip").is_file(), reason="CoRE MOF 2024 cache not present"
)
def test_concurrent_index_build_is_safe(tmp_path):
    """Three processes build the index at once; the lock + atomic write must keep it valid."""
    tmp_cache = tmp_path / "cache"
    src = tmp_cache / "core-mof-2024"
    src.mkdir(parents=True)
    for name in ("CoREMOF2024DB.zip", "ASR_data_SI_20250204.csv", "NCR_ASR_SI.xlsx"):
        source = CACHE_DIR / name
        if source.is_file():
            shutil.copyfile(source, src / name)

    env = dict(os.environ)
    env["CIFKIT_CACHE"] = str(tmp_cache)
    env["PYTHONIOENCODING"] = "utf-8"
    code = (
        "from cifkit.sources.core_mof import build_index;"
        "idx = build_index();"
        "print(idx['n_entries'], idx['n_computation_ready'])"
    )
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        for _ in range(3)
    ]
    outputs = [p.communicate(timeout=120) for p in procs]
    for proc, (out, err) in zip(procs, outputs):
        assert proc.returncode == 0, err
        assert out.split()[0].isdigit(), out

    index_file = src / "index.json"
    assert index_file.is_file()
    index = json.loads(index_file.read_text(encoding="utf-8"))
    assert index["n_entries"] == 8300
    assert len(index["entries"]) == index["n_entries"]
    assert not (src / "index.json.lock").exists()


def test_bootstrap_check_mode_on_empty_cache(tmp_path):
    """`bootstrap_data.py --check` must fail clearly when the cache is empty."""
    env = dict(os.environ)
    env["CIFKIT_CACHE"] = str(tmp_path / "empty-cache")
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "scripts/bootstrap_data.py", "--check"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode != 0
    combined = (proc.stdout + proc.stderr).lower()
    assert "missing" in combined or "缺少" in combined or "not" in combined


def _python(code: str, env: dict, *, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


CACHE_DIR2 = ROOT / "_cache" / "core-mof-2024"


@pytest.mark.skipif(
    not (CACHE_DIR2 / "CoREMOF2024DB.zip").is_file(), reason="CoRE MOF 2024 cache not present"
)
def test_eight_concurrent_index_builds(tmp_path):
    """8 processes building the index simultaneously must all succeed."""
    tmp_cache = tmp_path / "cache"
    src = tmp_cache / "core-mof-2024"
    src.mkdir(parents=True)
    for name in ("CoREMOF2024DB.zip", "ASR_data_SI_20250204.csv", "NCR_ASR_SI.xlsx"):
        source = CACHE_DIR2 / name
        if source.is_file():
            shutil.copyfile(source, src / name)
    env = dict(os.environ)
    env["CIFKIT_CACHE"] = str(tmp_cache)
    code = "from cifkit.sources.core_mof import build_index; print(build_index()['n_entries'])"
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code], cwd=str(ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        )
        for _ in range(8)
    ]
    outputs = [proc.communicate(timeout=180) for proc in procs]
    for proc, (out, err) in zip(procs, outputs):
        assert proc.returncode == 0, err
        assert out.strip() == "8300", out
    index = json.loads((src / "index.json").read_text(encoding="utf-8"))
    assert len(index["entries"]) == 8300
    assert not (src / "index.json.lock").exists()


def test_lock_recovery_after_killed_holder(tmp_path):
    """A process killed while holding the lock must not dead-lock later writers."""
    lock_path = tmp_path / "crash.lock"
    env = dict(os.environ)
    child_code = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "from cifkit.locks import file_lock\n"
        "lock = Path(sys.argv[1])\n"
        "with file_lock(lock, timeout=10):\n"
        "    print('locked', flush=True)\n"
        "    time.sleep(30)\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", child_code, str(lock_path)],
        cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8",
    )
    try:
        deadline = time.time() + 20
        while not lock_path.exists() and time.time() < deadline:
            time.sleep(0.05)
        assert lock_path.exists(), "child never acquired the lock"
        assert child.stdout.readline().strip() == "locked"
        child.kill()
        child.wait(timeout=20)
    finally:
        if child.poll() is None:
            child.kill()
    # the stale lock file remains; a new writer must recover it after `stale` seconds
    with file_lock(lock_path, timeout=5.0, stale=1.0):
        assert lock_path.exists()
    assert not lock_path.exists()
