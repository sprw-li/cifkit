"""Service load-curve tooling (round 46, limitation J5).

The *numbers* come from ``scripts/load_service.py`` (machine-specific, recorded in
``runs/service_load*.json``).  These tests pin the measurement logic itself, so a
broken harness cannot silently produce a flattering curve: percentile selection,
error accounting, and the closed-loop driver — all against a stub service that
sleeps a known amount.
"""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def load():
    return _load("load_service", ROOT / "scripts" / "load_service.py")


class StubService:
    """Answers after a fixed delay; rejects with `busy` when told to."""

    def __init__(self, delay: float = 0.005, busy_every: int = 0):
        self.delay = delay
        self.busy_every = busy_every
        self.calls = 0
        self.lock = __import__("threading").Lock()

    def handle(self, request):
        with self.lock:
            self.calls += 1
            n = self.calls
        time.sleep(self.delay)
        if self.busy_every and n % self.busy_every == 0:
            return {"ok": False, "error": {"code": "busy"}}
        return {"ok": True, "result": {"natoms": 138}}


def test_percentile_edges(load):
    assert load.percentile([], 0.5) is None
    assert load.percentile([1.0], 0.99) == 1.0
    values = [float(i) for i in range(101)]
    assert load.percentile(values, 0.50) == 50.0
    assert load.percentile(values, 0.90) == 90.0
    assert load.percentile(values, 0.99) == 99.0


def test_closed_loop_measures_throughput(load):
    service = StubService(delay=0.005)
    row = load.run_level(service, "not used", level=1, seconds=0.5)
    assert row["ok"] > 10, row
    # 5 ms per call -> ~200 rps ceiling; assert we are in the right order of magnitude
    assert 50 < row["throughput_rps"] < 250, row
    assert row["errors"] == {}
    assert row["p50_ms"] > 0


def test_a_sleeping_stub_does_scale(load):
    """Sleep releases the GIL, so *this* stub scales - the real service does not.

    Pinning this keeps the distinction honest: a load curve measured with a sleeping
    stub would be meaningless for a CPU-bound service.
    """
    service = StubService(delay=0.01)
    one = load.run_level(service, "x", level=1, seconds=0.5)
    four = load.run_level(service, "x", level=4, seconds=0.5)
    assert four["throughput_rps"] > 2 * one["throughput_rps"], (one, four)


def test_gil_bound_work_does_not_scale_with_threads(load):
    """CPU-bound work is what the real service does: threads must not invent rps.

    (A *sleeping* stub would scale, because sleep releases the GIL - which is exactly
    why this test burns CPU instead.)
    """

    class CpuBound:
        def handle(self, request):
            total = 0
            for value in range(120_000):
                total += value * value
            return {"ok": True, "result": {"checksum": total % 7}}

    one = load.run_level(CpuBound(), "x", level=1, seconds=0.4)
    four = load.run_level(CpuBound(), "x", level=4, seconds=0.4)
    assert four["throughput_rps"] < 1.6 * one["throughput_rps"], (one, four)
    # latency must not *improve* with more CPU-bound threads; allow noise around it
    assert four["p50_ms"] >= 0.8 * one["p50_ms"], (one, four)


def test_busy_replies_are_counted_not_swallowed(load):
    service = StubService(delay=0.001, busy_every=3)
    row = load.run_level(service, "x", level=2, seconds=0.4)
    assert row["errors"].get("busy", 0) > 0
    assert row["requests"] == row["ok"] + sum(row["errors"].values())


def test_exceptions_do_not_kill_the_driver(load):
    class Exploding:
        def handle(self, request):
            raise RuntimeError("boom")

    row = load.run_level(Exploding(), "x", level=2, seconds=0.3)
    assert row["errors"].get("RuntimeError", 0) > 0
    assert row["ok"] == 0


def test_recorded_curve_is_self_consistent():
    import json

    path = ROOT / "runs" / "service_load.json"
    if not path.is_file():
        pytest.skip("load curve not measured in this checkout")
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["levels"], "a curve without levels proves nothing"
    assert report["policy"]["max_concurrency"] >= 1
    # the recorded curve must not claim super-linear scaling on a shared box
    assert max(report["scaling"].values()) < 2.0, report["scaling"]
    for row in report["levels"]:
        assert row["requests"] == row["ok"] + sum(row["errors"].values())
        assert row["p50_ms"] <= row["p99_ms"] or row["p99_ms"] == 0
