"""Failure injection: disk full, read-only cache, corrupt JSON, permission denied (A7).

These tests do not merely assert "it raises" — they check the *state* after the
failure: no partial file left behind, the previous good file still intact, and a
message that names the cause.  Faults are injected with monkeypatch so the suite
runs anywhere (no need for a real full disk).
"""
from __future__ import annotations

import errno
import json
import os
from pathlib import Path

import pytest

from cifkit import locks
from cifkit.locks import LockTimeout, atomic_write_json, atomic_write_text, file_lock


# --------------------------------------------------------------------- locks
def test_file_lock_times_out_and_cleans_up_on_success(tmp_path):
    lock = tmp_path / "x.lock"
    with file_lock(lock, timeout=1.0):
        assert lock.is_file()
        with pytest.raises(LockTimeout):
            with file_lock(lock, timeout=0.2, poll=0.01):
                pass
    assert not lock.exists(), "the lock must be released even after a timeout"


def test_stale_lock_is_recovered(tmp_path):
    lock = tmp_path / "stale.lock"
    lock.write_text("pid=999999 ts=0", encoding="utf-8")
    old = 3600.0
    os.utime(lock, (lock.stat().st_atime - old, lock.stat().st_mtime - old))
    with file_lock(lock, timeout=1.0, stale=1.0):
        assert lock.is_file()


def test_lock_survives_a_crashed_writer(tmp_path, monkeypatch):
    """A writer that dies before unlinking must not dead-lock the next one."""
    lock = tmp_path / "crash.lock"

    def boom():
        with file_lock(lock, timeout=1.0):
            raise RuntimeError("writer crashed")

    with pytest.raises(RuntimeError):
        boom()
    assert not lock.exists()
    with file_lock(lock, timeout=1.0):
        pass


# ------------------------------------------------------------- atomic writes
def test_atomic_write_keeps_previous_content_on_disk_full(tmp_path, monkeypatch):
    target = tmp_path / "index.json"
    atomic_write_json(target, {"good": 1})
    before = target.read_bytes()

    real_replace = os.replace

    def failing_replace(src, dst):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError) as excinfo:
        atomic_write_json(target, {"bad": 2})
    assert excinfo.value.errno == errno.ENOSPC
    monkeypatch.setattr(os, "replace", real_replace)

    assert target.read_bytes() == before, "a failed write must not touch the old file"
    leftovers = [p.name for p in tmp_path.iterdir() if ".tmp" in p.name]
    assert leftovers == [], f"temp files left behind: {leftovers}"
    assert json.loads(target.read_text(encoding="utf-8")) == {"good": 1}


def test_atomic_write_cleans_up_when_the_write_itself_fails(tmp_path, monkeypatch):
    target = tmp_path / "out.txt"

    class _Boom:
        def __init__(self, *args, **kwargs):
            raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(Path, "write_text", lambda self, *a, **k: _Boom())
    with pytest.raises(OSError):
        atomic_write_text(target, "data")
    assert not target.exists()
    assert [p.name for p in tmp_path.iterdir() if ".tmp" in p.name] == []


def test_atomic_write_into_read_only_directory(tmp_path):
    """Read-only directory (POSIX) or Windows ACL: the error must be an OSError."""
    target_dir = tmp_path / "ro"
    target_dir.mkdir()
    target = target_dir / "f.json"
    atomic_write_json(target, {"ok": 1})
    try:
        os.chmod(target_dir, 0o500)
    except OSError:  # pragma: no cover
        pytest.skip("cannot chmod on this filesystem")
    if os.name == "nt":  # pragma: no cover - NTFS read-only dirs are not enforced
        pytest.skip("Windows does not enforce read-only directories the same way")
    try:
        with pytest.raises(OSError):
            atomic_write_json(target_dir / "g.json", {"ok": 2})
    finally:
        os.chmod(target_dir, 0o700)


# ------------------------------------------------------- consumers of the cache
def test_corrupt_index_json_is_rebuilt_not_fatal(tmp_path, monkeypatch):
    """A truncated index.json (e.g. crash mid-write) must not break the next run."""
    from cifkit.sources import core_mof

    cache = tmp_path / "cache"
    src = cache / "core-mof-2024"
    src.mkdir(parents=True)
    real = Path(__file__).resolve().parents[1] / "_cache" / "core-mof-2024"
    required = ("CoREMOF2024DB.zip", "ASR_data_SI_20250204.csv", "NCR_ASR_SI.xlsx")
    if not all((real / name).is_file() for name in required):
        pytest.skip("CoRE MOF 2024 cache not present")
    for name in required:
        import shutil

        shutil.copyfile(real / name, src / name)
    (src / "index.json").write_text('{"entries": {"truncated', encoding="utf-8")

    monkeypatch.setenv("CIFKIT_CACHE", str(cache))
    monkeypatch.setattr(core_mof, "_INDEX_CACHE", None)
    monkeypatch.setattr(core_mof, "_META_CACHE", None)
    index = core_mof.build_index()
    assert index["n_entries"] > 0
    assert json.loads((src / "index.json").read_text(encoding="utf-8"))["n_entries"] == index["n_entries"]


def test_corrupt_manifest_does_not_stop_a_dataset_build(tmp_path):
    """A corrupt run manifest must be reported, and every other run still built."""
    import shutil

    from cifkit.dataset import build_dataset

    zif8 = Path(__file__).resolve().parent / "data" / "zif8_cr_sod.cif"
    runs = tmp_path / "runs"
    for name in ("run_a", "run_c"):
        run = runs / name
        run.mkdir(parents=True)
        shutil.copyfile(zif8, run / "standardized.cif")
        (run / "manifest.json").write_text(json.dumps({
            "ok": True,
            "artifacts": {"standardized.cif": str(run / "standardized.cif")},
            "source": {"source": "local", "record": {"record_id": f"local:{name}"}},
        }), encoding="utf-8")
    broken = runs / "run_b"
    broken.mkdir()
    (broken / "manifest.json").write_text('{"ok": true,', encoding="utf-8")

    summary = build_dataset(runs, tmp_path / "ds", rdf=False)
    assert summary["n_runs"] == 3
    assert summary["n_ok"] == 2 and summary["n_failed"] == 1
    assert any("parse failed" in str(err) for err in summary["errors"])
    assert (tmp_path / "ds" / "dataset.csv").is_file()


def test_cache_write_failure_surfaces_as_oserror(tmp_path, monkeypatch):
    """If the cache directory cannot be written, callers get a clear OSError."""
    def deny(self, *args, **kwargs):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(Path, "write_text", deny)
    with pytest.raises(PermissionError):
        locks.atomic_write_text(tmp_path / "x.txt", "hello")


def test_manifest_survives_a_write_failure_during_pipeline_run(tmp_path, monkeypatch):
    """Nothing half-written: a failing manifest write leaves no manifest file."""
    target = tmp_path / "manifest.json"
    atomic_write_json(target, {"ok": True})
    good = target.read_bytes()

    def deny(self, *args, **kwargs):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(Path, "write_text", deny)
    with pytest.raises(PermissionError):
        atomic_write_json(target, {"ok": False})
    assert target.read_bytes() == good
