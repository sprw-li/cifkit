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

def test_process_token_is_stable_for_this_process():
    from cifkit.locks import _process_token

    first = _process_token()
    assert first
    assert first == _process_token(), "the token must not change while we run"
    # The token is pid-prefixed on every platform; only the start-time suffix needs
    # OS support (`/proc` on Linux, `GetProcessTimes` on Windows), so macOS/BSD fall
    # back to the bare pid - see cifkit/locks.py.  Round 58 CI caught the old
    # assertion (which demanded the 'pid:start' form) failing on macOS.
    assert first.startswith(str(os.getpid())), first


def test_recycled_pid_is_detected_as_a_different_process(tmp_path):
    """A lock whose token no longer matches the live PID must be reclaimed."""
    lock = tmp_path / "recycled.lock"
    # alive pid, but a token from a different instance of it
    lock.write_text(f"pid={os.getpid()} token={os.getpid()}:1 ts={time.time()}",
                    encoding="utf-8")
    started = time.monotonic()
    with file_lock(lock, timeout=5, stale=3600):
        elapsed = time.monotonic() - started
    assert elapsed < 2.0, f"a recycled PID must not pin the lock ({elapsed:.1f}s)"


def test_lock_records_pid_and_token(tmp_path):
    lock = tmp_path / "recorded.lock"
    with file_lock(lock, timeout=5):
        body = lock.read_text(encoding="utf-8")
        assert f"pid={os.getpid()}" in body
        assert "token=" in body

def test_empty_lock_file_is_stale(tmp_path):
    """A half-written or neutralised lock must not block anyone."""
    lock = tmp_path / "empty.lock"
    lock.write_text("", encoding="utf-8")
    started = time.monotonic()
    with file_lock(lock, timeout=5, stale=3600):
        pass
    assert time.monotonic() - started < 2.0
    assert not lock.exists()


def test_neutralised_lock_is_reclaimed(tmp_path):
    lock = tmp_path / "neutral.lock"
    lock.write_text("pid=0 token=0 ts=0", encoding="utf-8")
    with file_lock(lock, timeout=5, stale=3600):
        pass
    assert not lock.exists()


def test_release_removes_the_lock_even_if_unlink_is_flaky(tmp_path, monkeypatch):
    """If the OS refuses the delete, the lock must be neutralised, not left held."""
    from cifkit import locks

    lock = tmp_path / "flaky.lock"
    calls = {"n": 0}
    real_unlink = Path.unlink

    def flaky_unlink(self, *args, **kwargs):
        if self.name == "flaky.lock":
            calls["n"] += 1
            raise PermissionError(13, "in use", str(self))
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    with locks.file_lock(lock, timeout=5, stale=3600):
        pass
    monkeypatch.undo()
    assert calls["n"] >= 2, "release must retry"
    assert lock.exists(), "the file could not be removed"
    assert "pid=0" in lock.read_text(encoding="utf-8"), "it must be neutralised"
    # and the next caller reclaims it immediately
    started = time.monotonic()
    with locks.file_lock(lock, timeout=5, stale=3600):
        pass
    assert time.monotonic() - started < 2.0

def test_windows_eacces_on_create_is_treated_as_held(tmp_path, monkeypatch):
    """O_EXCL collisions surface as EACCES on Windows; that must not crash."""
    import errno

    from cifkit import locks

    real_open = locks.os.open
    state = {"calls": 0}

    def flaky_open(path, flags, *args, **kwargs):
        # first attempt: pretend another process has the file open
        if state["calls"] == 0:
            state["calls"] += 1
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(locks.os, "open", flaky_open)
    lock = tmp_path / "eacces.lock"
    lock.write_text("pid=0 token=0 ts=0", encoding="utf-8")   # nothing holding it
    with locks.file_lock(lock, timeout=5, stale=3600):
        assert lock.exists()
    assert state["calls"] == 1
    assert not lock.exists()
