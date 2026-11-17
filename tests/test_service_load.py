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


class CpuBoundService:
    """A stub that burns CPU holding the GIL — what the real service does."""

    def handle(self, request):
        total = 0
        for value in range(120_000):
            total += value * value
        return {"ok": True, "result": {"checksum": total % 7}}


def _paired_level_ratios(load, make_service, *, rounds: int, seconds: float,
                         low: int = 1, high: int = 4) -> tuple[float, float, list]:
    """Interleaved throughput/latency ratios of ``high`` vs ``low`` concurrency.

    Why paired (round 58): these tests used to measure level 1 and level 4 once
    each, back to back.  On a shared box that is not a controlled experiment — a
    parallel teammate (or any other process) can load the machine during one of
    the two windows only, and the two numbers are then not comparable.  That is
    exactly how a false red appeared (four-thread p50 "faster" than one-thread:
    8.15 ms vs 10.91 ms) even though the work is a fixed, GIL-serialised loop.

    Measuring low/high in the *same* round, alternating which goes first, makes
    drifting external load a common factor of the pair.  The median over the
    rounds then absorbs the remaining jitter.

    Returns ``(median_rps_ratio, median_p50_ratio, pairs)``.
    """
    import statistics

    pairs: list[tuple[float, float]] = []
    for index in range(rounds):
        order = (low, high) if index % 2 == 0 else (high, low)
        rows = {level: load.run_level(make_service(), "x", level=level, seconds=seconds)
                for level in order}
        pairs.append((rows[high]["throughput_rps"] / rows[low]["throughput_rps"],
                      rows[high]["p50_ms"] / max(1e-9, rows[low]["p50_ms"])))
    return (statistics.median(pair[0] for pair in pairs),
            statistics.median(pair[1] for pair in pairs),
            pairs)


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

    Paired/median measurement for the same anti-noise reason as the GIL test below;
    the effect is large (4 concurrent sleepers ≈ 4x the 1-thread rate), so a 2x
    floor stays far from the noise while still failing if the stub stops scaling.
    """
    service = StubService(delay=0.01)
    service.handle({})  # warm-up
    rps_ratio, _, pairs = _paired_level_ratios(
        load, lambda: StubService(delay=0.01), rounds=3, seconds=0.4)
    assert rps_ratio > 2.0, (rps_ratio, pairs)


def test_gil_bound_work_does_not_scale_with_threads(load):
    """CPU-bound work is what the real service does: threads must not invent rps.

    (A *sleeping* stub would scale, because sleep releases the GIL - which is exactly
    why this test burns CPU instead.)

    Anti-noise design (round 58): level 1 and level 4 are measured in the same
    interleaved round (see :func:`_paired_level_ratios`) and compared by the median
    ratio over ``rounds`` pairs.

    Bandwidths are physical, with measured headroom:

    * throughput — pure-Python bytecode is serialised by the GIL, so four threads
      can at best match one (~1.0x).  Measured paired medians: 0.91x idle and 1.05x
      while the box ran at ~100% (three CPU burners), worst single pair 1.16x.
      1.6x therefore leaves >35% headroom over the worst measurement while still
      failing hard for a stub with real parallelism (which would be ~4x).
    * p50 — the per-request work is fixed and adding threads only adds GIL handoff
      contention, so four-thread latency cannot drop.  Measured paired medians:
      1.27x idle, 2.74x loaded.  0.8x keeps the original "latency must not improve"
      claim with margin for scheduler jitter.
    """
    load.run_level(CpuBoundService(), "x", level=1, seconds=0.2)  # warm-up
    rps_ratio, p50_ratio, pairs = _paired_level_ratios(
        load, CpuBoundService, rounds=5, seconds=0.35)
    assert rps_ratio < 1.6, (rps_ratio, pairs)
    assert p50_ratio >= 0.8, (p50_ratio, pairs)


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
