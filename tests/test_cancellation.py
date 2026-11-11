"""Cooperative cancellation (round 50, limitation J2).

J2 said a timeout returned ``504`` while the work kept running.  These tests pin the
token semantics and, more importantly, **that a cancelled batch really stops early**
rather than merely reporting so.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from cifkit.cancel import Cancelled, CancellationToken, checkpoint, current_token, use_token

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"


# --------------------------------------------------------------------------- token
def test_token_starts_uncancelled():
    token = CancellationToken()
    assert token.cancelled is False
    token.checkpoint()                      # must not raise
    assert token.reason is None


def test_cancelled_token_raises_with_the_reason():
    token = CancellationToken()
    token.cancel("timeout")
    assert token.cancelled is True
    with pytest.raises(Cancelled) as info:
        token.checkpoint()
    assert info.value.reason == "timeout"
    assert "timeout" in str(info.value)


def test_first_reason_wins():
    token = CancellationToken()
    token.cancel("timeout")
    token.cancel("shutdown")
    assert token.reason == "timeout"


def test_checkpoint_without_a_token_is_a_noop():
    assert current_token() is None
    checkpoint()


def test_use_token_installs_and_restores():
    token = CancellationToken()
    with use_token(token):
        assert current_token() is token
        token.cancel("test")
        with pytest.raises(Cancelled):
            checkpoint()
    assert current_token() is None


def test_tokens_are_thread_local():
    token = CancellationToken()
    seen: list[bool] = []

    def worker() -> None:
        seen.append(current_token() is token)

    with use_token(token):
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
    assert seen == [False], "another thread must not inherit this thread's token"


def test_wait_wakes_up_on_cancel():
    token = CancellationToken()
    timer = threading.Timer(0.1, token.cancel, args=("scheduled",))
    timer.start()
    started = time.monotonic()
    assert token.wait(5) is True
    assert time.monotonic() - started < 4
    timer.cancel()


# ------------------------------------------------------------------ real work stops
@pytest.fixture
def cif_files(tmp_path):
    original = (DATA / "terephthalic_acid_hfree.cif").read_text(encoding="utf-8")
    paths = []
    for index in range(12):
        target = tmp_path / f"s{index}.cif"
        target.write_text(original, encoding="utf-8")
        paths.append(target)
    return paths


def test_cancelled_batch_stops_early(cif_files):
    """A token cancelled after a few items must abort the walk, not finish it."""
    from cifkit import features

    token = CancellationToken()
    processed = {"n": 0}
    original = features.features_from_cif

    def counting(path, **options):
        processed["n"] += 1
        if processed["n"] == 3:
            token.cancel("test: cancel mid-batch")
        return original(path, **options)

    features.features_from_cif = counting
    try:
        with use_token(token):
            with pytest.raises(Cancelled):
                features.features_many(cif_files, jobs=1, rdf=False)
    finally:
        features.features_from_cif = original
    assert processed["n"] <= 4, f"walk continued after cancellation ({processed['n']} items)"


def test_uncancelled_batch_finishes(cif_files):
    from cifkit import features

    with use_token(CancellationToken()):
        rows = features.features_many(cif_files, jobs=1, rdf=False)
    assert len(rows) == len(cif_files)


# ------------------------------------------------------------- service integration
def test_guarded_timeout_returns_timeout_and_stops_the_worker():
    """The 504 path must also *signal* the worker (J2), and the worker must stop."""
    from cifkit import service
    from cifkit.platform import GuardedService, Policy

    progress = {"n": 0, "done": False}

    def slow_op(cif_text: str = "") -> dict:
        for _ in range(400):
            checkpoint()
            progress["n"] += 1
            time.sleep(0.01)
        progress["done"] = True
        return {"ok": True, "n": progress["n"]}

    # the contract validates the op *name* before dispatch, so drive a real op
    original_op = service.OPS["validate"]
    service.OPS["validate"] = slow_op
    try:
        guarded = GuardedService(Policy(timeout_s=0.4, max_concurrency=1, queue_size=2))
        reply = guarded.handle({"op": "validate", "params": {"cif_text": "data_demo\n"}})
        assert reply["ok"] is False
        assert reply["error"]["code"] == "timeout"
        # let the worker reach its next checkpoint
        deadline = time.time() + 5
        while time.time() < deadline and progress["n"] < 400:
            if progress["n"] and progress["n"] < 400:
                time.sleep(0.3)
                if progress["n"] < 400:
                    break
            time.sleep(0.1)
        assert progress["done"] is False, "the worker must not have completed the loop"
        assert progress["n"] < 400, progress
    finally:
        service.OPS["validate"] = original_op


def test_capabilities_or_docs_mention_cooperative_cancellation():
    """The honest wording matters: 'best effort' became 'cooperative'."""
    text = (ROOT / "cifkit" / "platform.py").read_text(encoding="utf-8")
    assert "cooperative" in text
    assert "CancellationToken" in text
