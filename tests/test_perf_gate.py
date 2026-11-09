"""Performance regression gate (round 26): comparison logic must be exact."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("perf_gate", ROOT / "scripts" / "perf_gate.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def perf():
    return _load()


def _baseline(**metrics):
    return {"metrics": {"features_no_rdf_s": 0.02, "dataset_peak_mib": 1.0, **metrics}}


def test_no_change_is_ok(perf):
    ok, rows = perf.compare(_baseline(), _baseline())
    assert ok
    assert {row["verdict"] for row in rows} == {"ok"}
    assert all(row["ratio"] == 1.0 for row in rows)


def test_slower_time_is_a_regression(perf):
    ok, rows = perf.compare(_baseline(), _baseline(features_no_rdf_s=0.10))  # 5x slower
    assert not ok
    row = next(r for r in rows if r["metric"] == "features_no_rdf_s")
    assert row["verdict"] == "REGRESSION" and row["ratio"] == pytest.approx(0.2)


def test_faster_time_is_fine(perf):
    ok, _ = perf.compare(_baseline(), _baseline(features_no_rdf_s=0.01))
    assert ok


def test_memory_growth_is_a_regression(perf):
    ok, rows = perf.compare(_baseline(), _baseline(dataset_peak_mib=4.0))  # 4x
    assert not ok
    row = next(r for r in rows if r["metric"] == "dataset_peak_mib")
    assert row["verdict"] == "REGRESSION" and row["ratio"] == pytest.approx(4.0)


def test_tolerances_are_wide_by_default_and_overridable(perf):
    current = _baseline(features_no_rdf_s=0.06)      # 3x slower: inside default 0.5x? no
    ok_default, _ = perf.compare(_baseline(), current)
    assert perf.DEFAULT_THRESHOLDS["min_throughput_ratio"] == 0.5
    # 0.6x is above the default tolerance, so it must pass
    ok_within, _ = perf.compare(_baseline(),
                                _baseline(features_no_rdf_s=0.02 / 0.6))
    assert ok_within
    # ... and a stricter threshold turns it into a failure
    ok_strict, _ = perf.compare(_baseline(), _baseline(features_no_rdf_s=0.02 / 0.6),
                                {"min_throughput_ratio": 0.9})
    assert not ok_strict


def test_missing_metric_is_skipped_not_failed(perf):
    ok, rows = perf.compare({"metrics": {"x_s": 1.0}}, {"metrics": {}})
    assert ok
    assert rows[0]["verdict"] == "skip"


def test_a_loaded_machine_makes_time_metrics_inconclusive_not_failed(perf):
    """Round 27 lesson: a 30-min release run reported false perf regressions."""
    baseline = {"metrics": {"features_no_rdf_s": 0.02, "control_loop_s": 0.2}}
    # control loop 5x slower => the box is loaded; the 4x slower metric must not fail
    current = {"metrics": {"features_no_rdf_s": 0.08, "control_loop_s": 1.0}}
    ok, rows = perf.compare(baseline, current)
    assert ok, rows
    row = next(r for r in rows if r["metric"] == "features_no_rdf_s")
    assert row["verdict"] == "inconclusive"
    assert "slower than baseline" in row["note"]


def test_a_real_regression_on_an_idle_machine_still_fails(perf):
    baseline = {"metrics": {"features_no_rdf_s": 0.02, "control_loop_s": 0.2}}
    current = {"metrics": {"features_no_rdf_s": 0.08, "control_loop_s": 0.21}}
    ok, rows = perf.compare(baseline, current)
    assert not ok
    row = next(r for r in rows if r["metric"] == "features_no_rdf_s")
    assert row["verdict"] == "REGRESSION"


def test_memory_is_never_excused_by_load(perf):
    """Memory is not load-sensitive: a memory blow-up must fail even when loaded."""
    baseline = {"metrics": {"dataset_peak_mib": 1.0, "control_loop_s": 0.2}}
    current = {"metrics": {"dataset_peak_mib": 5.0, "control_loop_s": 1.0}}
    ok, rows = perf.compare(baseline, current)
    assert not ok
    assert next(r for r in rows if r["metric"] == "dataset_peak_mib")["verdict"] == "REGRESSION"


def test_control_metric_is_reported_as_info(perf):
    baseline = {"metrics": {"control_loop_s": 0.2}}
    _ok, rows = perf.compare(baseline, {"metrics": {"control_loop_s": 0.4}})
    assert rows[0]["verdict"] == "info"
    assert "load factor" in rows[0]["note"]


def test_baseline_file_shape_if_present(perf):
    import json

    path = ROOT / "runs" / "perf_baseline.json"
    if not path.is_file():
        pytest.skip("no baseline recorded yet")
    baseline = json.loads(path.read_text(encoding="utf-8"))
    assert {"metrics", "spread", "machine", "measured_at"} <= set(baseline)
    assert baseline["metrics"]["features_no_rdf_s"] > 0
    assert baseline["metrics"]["dataset_peak_mib"] > 0
