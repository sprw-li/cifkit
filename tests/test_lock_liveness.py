"""Stale-lock detection by liveness (round 43).

A SIGKILLed lock holder leaves the file behind with a *fresh* mtime; age alone
therefore cannot tell a crashed writer from an active one, and every later writer
would wait the full timeout.  These tests pin the liveness rule.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from cifkit.locks import LockTimeout, _pid_alive, file_lock


def test_current_process_is_alive():
    assert _pid_alive(os.getpid()) is True


def test_dead_pid_is_not_alive():
    # a very high pid is not in use on any real system
    assert _pid_alive(4_000_000) is False


def test_lock_with_dead_owner_is_reclaimed_immediately(tmp_path):
    lock = tmp_path / "x.lock"
    lock.write_text("pid=4000000 ts=0", encoding="utf-8")   # fresh mtime, dead pid
    started = time.monotonic()
    with file_lock(lock, timeout=5, stale=3600):
        elapsed = time.monotonic() - started
    assert elapsed < 2.0, f"should not wait for the age-based timeout ({elapsed:.1f}s)"
    assert not lock.exists()


def test_lock_with_live_owner_is_not_stolen(tmp_path):
    lock = tmp_path / "y.lock"
    lock.write_text(f"pid={os.getpid()} ts={time.time()}", encoding="utf-8")
    with pytest.raises(LockTimeout):
        with file_lock(lock, timeout=0.3, stale=3600):
            pass


def test_ancient_lock_is_reclaimed_even_if_the_pid_is_alive(tmp_path):
    """Age still wins: a lock held by a live-but-stuck process must not block forever."""
    lock = tmp_path / "z.lock"
    lock.write_text(f"pid={os.getpid()} ts=0", encoding="utf-8")
    old = time.time() - 10_000
    os.utime(lock, (old, old))
    with file_lock(lock, timeout=2, stale=60):
        pass
    assert not lock.exists()
