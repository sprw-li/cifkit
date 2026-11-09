"""Lock contention robustness: a slow *peer* must not fail the waiter.

Found by running the full suite on a heavily loaded machine: with 8 concurrent
index builds, one waiter hit the 120 s lock timeout.  The build is idempotent, so a
waiter should re-check the cache (the peer may have just finished) and retry the
lock for a bounded total time, instead of raising immediately.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from cifkit.sources import core_mof

ROOT = Path(__file__).resolve().parents[1]
REAL_CACHE = ROOT / "_cache" / "core-mof-2024"
REQUIRED = ("CoREMOF2024DB.zip", "ASR_data_SI_20250204.csv", "NCR_ASR_SI.xlsx")


@pytest.fixture()
def core_cache(tmp_path, monkeypatch):
    if not all((REAL_CACHE / name).is_file() for name in REQUIRED):
        pytest.skip("CoRE MOF 2024 cache not present")
    cache = tmp_path / "cache"
    target = cache / "core-mof-2024"
    target.mkdir(parents=True)
    for name in REQUIRED:
        shutil.copyfile(REAL_CACHE / name, target / name)
    monkeypatch.setenv("CIFKIT_CACHE", str(cache))
    monkeypatch.setattr(core_mof, "_INDEX_CACHE", None)
    monkeypatch.setattr(core_mof, "_META_CACHE", None)
    return target


def test_lock_timeout_uses_index_written_by_the_slow_peer(core_cache, monkeypatch):
    """Waiter scenario: no cache → peer holds the lock → peer finishes during our wait."""
    built = core_mof.build_index()
    n_entries = built["n_entries"]
    assert n_entries > 0
    index_file = core_mof.index_path()
    payload = index_file.read_bytes()
    index_file.unlink()  # force build_index() down the locked path

    calls = {"n": 0}

    class _PeerFinished:
        def __enter__(self_inner):
            calls["n"] += 1
            index_file.write_bytes(payload)          # the peer just finished
            raise TimeoutError("simulated slow peer holding the lock")

        def __exit__(self_inner, *args):
            return False

    monkeypatch.setattr(core_mof, "file_lock", lambda path, *, timeout=120.0: _PeerFinished())
    monkeypatch.setenv("CIFKIT_LOCK_TIMEOUT", "0.05")
    monkeypatch.setenv("CIFKIT_LOCK_TOTAL_TIMEOUT", "30")
    monkeypatch.setattr(core_mof, "_INDEX_CACHE", None)
    monkeypatch.setattr(core_mof, "_META_CACHE", None)

    index = core_mof.build_index()                    # must not raise
    assert index["n_entries"] == n_entries
    assert calls["n"] == 1, "the waiter should have re-checked the cache after the timeout"


def test_lock_timeout_without_peer_result_eventually_raises(core_cache, monkeypatch):
    """If nobody ever produces the index, failing loudly is the honest behaviour."""
    built = core_mof.build_index()
    assert built["n_entries"] > 0
    core_mof.index_path().unlink()                    # no cache to fall back on

    class _AlwaysContended:
        def __enter__(self_inner):
            raise TimeoutError("always contended")

        def __exit__(self_inner, *args):
            return False

    monkeypatch.setattr(core_mof, "file_lock", lambda path, *, timeout=120.0: _AlwaysContended())
    monkeypatch.setenv("CIFKIT_LOCK_TIMEOUT", "0.02")
    monkeypatch.setenv("CIFKIT_LOCK_TOTAL_TIMEOUT", "0.3")
    monkeypatch.setattr(core_mof, "_INDEX_CACHE", None)
    monkeypatch.setattr(core_mof, "_META_CACHE", None)
    with pytest.raises(Exception):  # noqa: B017 - the lock layer's own error type
        core_mof.build_index()


def test_lock_env_knobs_are_documented_defaults(monkeypatch):
    """The knobs exist with sane defaults (120 s per attempt, 900 s total)."""
    import inspect

    source = inspect.getsource(core_mof.build_index)
    assert "CIFKIT_LOCK_TIMEOUT" in source and "CIFKIT_LOCK_TOTAL_TIMEOUT" in source
    assert '"120"' in source and '"900"' in source
