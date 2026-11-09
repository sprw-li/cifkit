"""Performance regression gate: record a baseline, then compare against it.

Library-sized projects regress silently; this makes throughput and peak memory
*measurable* against a stored baseline.

    .venv\\Scripts\\python.exe scripts\\perf_gate.py --record      # write the baseline
    .venv\\Scripts\\python.exe scripts\\perf_gate.py --check       # compare (exit 1 on regression)

Honesty about the environment: this box is shared and heavily loaded (the control
experiment in ``scripts/bench_api.py`` measured 4 threads at **0.78x** on a pure
Python loop — i.e. the machine can be slower *by itself*).  Therefore:

* each metric is the **median of several runs**, and the spread is reported;
* the default tolerances are wide (throughput may drop to 0.5x, memory may grow to
  2.0x) — the gate catches order-of-magnitude regressions, not noise;
* the baseline is machine-specific and lives in ``runs/`` (not a promise about
  other hardware);
* the gate is **opt-in** (``release_check --perf``), never part of the default run.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZIF8 = ROOT / "tests" / "data" / "zif8_cr_sod.cif"

DEFAULT_THRESHOLDS = {
    "min_throughput_ratio": 0.5,   # current/baseline
    "max_memory_ratio": 2.0,       # current/baseline
    "load_factor": 2.0,            # control-loop slowdown that voids time metrics
}


def _median_time(fn, repeats: int, *, warmup: int = 1) -> tuple[float, list[float]]:
    """Median of ``repeats`` runs **after** warm-up calls.

    Warm-up matters here: the first ``features``/``convert`` call pays for lazy
    imports (~0.5 s), which would otherwise dominate the median of a small sample
    and make the baseline meaningless.
    """
    for _ in range(max(0, warmup)):
        fn()
    samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - started)
    return statistics.median(samples), samples


def _dataset_peak(peak_runs: int) -> tuple[float, float]:
    """Wall time and tracemalloc peak for a streamed dataset build."""
    import shutil

    from cifkit.dataset import build_dataset

    with tempfile.TemporaryDirectory() as tmp:
        runs = Path(tmp) / "runs"
        sample = ZIF8.read_text(encoding="utf-8")
        for index in range(peak_runs):
            run = runs / f"run{index:03d}"
            run.mkdir(parents=True)
            (run / "standardized.cif").write_text(sample, encoding="utf-8")
            (run / "manifest.json").write_text(json.dumps({
                "ok": True,
                "artifacts": {"standardized.cif": str(run / "standardized.cif")},
                "source": {"source": "local", "record": {"record_id": f"local:{index}"}},
            }), encoding="utf-8")
        build_dataset(runs, Path(tmp) / "warm", rdf=False)      # warm-up: imports/caches
        tracemalloc.start()
        started = time.perf_counter()
        summary = build_dataset(runs, Path(tmp) / "out", rdf=False)
        wall = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert summary["max_rows_held"] == 1, "the streaming guarantee must hold"
        return wall, peak / 1048576


def _control_loop(iterations: int = 3_000_000) -> float:
    """Pure-Python CPU loop: a load reference that no library change can affect.

    Measured alongside the real metrics so a slow run can be classified as
    "machine is loaded" instead of "the code regressed" (see round 27: a release
    gate on a loaded box reported 2 metrics as REGRESSION purely from load).
    """
    started = time.perf_counter()
    total = 0
    for i in range(iterations):
        total += i * i % 97
    return time.perf_counter() - started


def measure(quick: bool = False) -> dict:
    """Run the compact benchmark; returns metrics in base units (seconds, MiB)."""
    from cifkit import api

    repeats = 3 if quick else 5
    peak_runs = 20 if quick else 60

    feature_no_rdf, samples_a = _median_time(lambda: api.features(path=ZIF8, rdf=False), repeats)
    feature_rdf, samples_b = _median_time(lambda: api.features(path=ZIF8, rdf=True), repeats)
    convert, samples_c = _median_time(lambda: api.convert(path=ZIF8, formats=["vasp", "xyz"]), repeats)
    dataset_wall, dataset_peak = _dataset_peak(peak_runs)

    def many():
        from cifkit.features import features_many

        features_many([ZIF8] * 6, jobs=1, rdf=False)

    many_median, samples_d = _median_time(many, repeats)
    control = statistics.median([_control_loop() for _ in range(3)])

    return {
        "machine": {"platform": platform.platform(), "python": platform.python_version(),
                    "cpu_count": __import__("os").cpu_count()},
        "metrics": {
            "features_no_rdf_s": round(feature_no_rdf, 5),
            "features_rdf_s": round(feature_rdf, 5),
            "convert_2_formats_s": round(convert, 5),
            "features_many_6_jobs1_s": round(many_median, 5),
            "dataset_wall_s": round(dataset_wall, 4),
            "dataset_peak_mib": round(dataset_peak, 3),
            "control_loop_s": round(control, 4),
        },
        "spread": {
            "features_no_rdf": [round(min(samples_a), 4), round(max(samples_a), 4)],
            "features_rdf": [round(min(samples_b), 4), round(max(samples_b), 4)],
            "convert": [round(min(samples_c), 4), round(max(samples_c), 4)],
            "features_many": [round(min(samples_d), 4), round(max(samples_d), 4)],
        },
        "dataset_runs": peak_runs,
    }


def compare(baseline: dict, current: dict,
            thresholds: dict | None = None) -> tuple[bool, list[dict]]:
    """Pure comparison: (ok, rows).  ``rows`` carries the ratios for the report.

    Load awareness: the control loop (pure Python, unaffected by library changes)
    is compared too.  If the machine is more than ``load_factor`` slower than when
    the baseline was taken, *time* metrics are reported as ``inconclusive`` rather
    than ``REGRESSION`` — publishing a load artefact as a performance regression
    would be dishonest.
    """
    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    load_factor = limits.get("load_factor", 2.0)
    base_metrics = baseline.get("metrics", {})
    cur_metrics = current.get("metrics", {})
    base_control = base_metrics.get("control_loop_s")
    cur_control = cur_metrics.get("control_loop_s")
    load_ratio = (cur_control / base_control) if (base_control and cur_control) else None
    loaded = bool(load_ratio and load_ratio > load_factor)

    rows: list[dict] = []
    ok = True
    for key, base_value in base_metrics.items():
        current_value = cur_metrics.get(key)
        if not base_value or current_value is None:
            rows.append({"metric": key, "baseline": base_value, "current": current_value,
                         "ratio": None, "verdict": "skip"})
            continue
        if key == "control_loop_s":
            rows.append({"metric": key, "baseline": base_value, "current": current_value,
                         "ratio": round(current_value / base_value, 3),
                         "verdict": "info", "note": f"load factor (limit {load_factor}x)"})
            continue
        ratio = current_value / base_value
        if key.endswith("_mib"):
            good = ratio <= limits["max_memory_ratio"]
            note = f"<= {limits['max_memory_ratio']}x allowed"
            verdict = "ok" if good else "REGRESSION"
        else:
            # for times, lower is better → the "throughput ratio" is baseline/current
            ratio = base_value / current_value
            good = ratio >= limits["min_throughput_ratio"]
            note = f">= {limits['min_throughput_ratio']}x allowed"
            if loaded and not good:
                verdict = "inconclusive"
                note += f"; machine is {load_ratio:.1f}x slower than baseline (control loop)"
            else:
                verdict = "ok" if good else "REGRESSION"
        rows.append({"metric": key, "baseline": base_value, "current": current_value,
                     "ratio": round(ratio, 3), "verdict": verdict, "note": note})
        ok = ok and verdict in ("ok", "inconclusive")
    return ok, rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", action="store_true", help="write the baseline")
    ap.add_argument("--check", action="store_true", help="compare against the baseline")
    ap.add_argument("--baseline", default=str(ROOT / "runs" / "perf_baseline.json"))
    ap.add_argument("--json", default=str(ROOT / "runs" / "perf_check.json"))
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--min-throughput-ratio", type=float, default=None)
    ap.add_argument("--max-memory-ratio", type=float, default=None)
    args = ap.parse_args()

    if not (args.record or args.check):
        ap.error("choose --record or --check")

    print("measuring (median of several runs; this machine is shared/loaded) ...")
    current = measure(quick=args.quick)
    current["measured_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    for key, value in current["metrics"].items():
        print(f"  {key:26s} {value}")

    baseline_path = Path(args.baseline)
    if args.record:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nbaseline written: {baseline_path}")
        print("note: this baseline is machine-specific; re-record after hardware/runtime changes")
        return 0

    if not baseline_path.is_file():
        print(f"no baseline at {baseline_path}; run --record first", file=sys.stderr)
        return 1
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    thresholds = {}
    if args.min_throughput_ratio is not None:
        thresholds["min_throughput_ratio"] = args.min_throughput_ratio
    if args.max_memory_ratio is not None:
        thresholds["max_memory_ratio"] = args.max_memory_ratio
    ok, rows = compare(baseline, current, thresholds)

    print(f"\n{'metric':26s} {'baseline':>12s} {'current':>12s} {'ratio':>7s}  verdict")
    for row in rows:
        print(f"{row['metric']:26s} {str(row['baseline']):>12s} {str(row['current']):>12s} "
              f"{str(row['ratio']):>7s}  {row['verdict']}  {row.get('note', '')}")
    print(f"\nbaseline: {baseline_path} ({baseline.get('measured_at', 'unknown')})")
    print(f"machine may be loaded; tolerances are wide on purpose")
    loaded = [r for r in rows if r["verdict"] == "inconclusive"]
    if loaded:
        print(f"NOTE: {len(loaded)} time metric(s) are inconclusive — the machine measured "
              f"slower than the baseline; do not read this as a code regression.")
    report = {"checked_at": current["measured_at"], "ok": ok, "rows": rows,
              "inconclusive": [r["metric"] for r in loaded],
              "baseline": str(baseline_path), "current": current,
              "spread": current["spread"]}
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
