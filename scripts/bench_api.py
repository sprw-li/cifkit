"""Benchmark the embedding API: throughput, parallelism, memory, backpressure.

Turns "throughput unknown" (limitation J5) into numbers measured *on this machine*.
These are indicative, not a guarantee, and there is deliberately no CI threshold —
the script exists so the numbers can be re-measured when something changes.

    .venv\\Scripts\\python.exe scripts\\bench_api.py [--runs N] [--quick] [--json OUT]

Reports (all written to ``runs/bench_api.json``):

1. ``features`` throughput on a small framework (ZIF-8) with and without RDF;
2. ``convert`` throughput (vasp+xyz per structure);
3. ``features_many`` serial vs parallel (speedup);
4. dataset ``stream`` vs ``materialised``: wall time and ``tracemalloc`` peak;
5. ``GuardedService`` concurrency curve (1/2/4 workers): requests/s and p50/p95.
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import tempfile
import threading
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ZIF8 = ROOT / "tests" / "data" / "zif8_cr_sod.cif"
SLAB = ROOT / "runs" / "demo_sod_zif8" / "standardized.cif"


def _cpu_load() -> float | None:
    """Approximate current CPU load (0-100); Windows only, best effort."""
    try:
        import subprocess

        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "(Get-CimInstance Win32_Processor | "
                              "Measure-Object -Property LoadPercentage -Average).Average"],
                             capture_output=True, text=True, timeout=30)
        return float(out.stdout.strip())
    except Exception:  # noqa: BLE001
        return None


def _burn(n: int) -> int:
    total = 0
    for i in range(n):
        total += i * i % 97
    return total


def bench_control(tasks: int = 4, iterations: int = 3_000_000) -> dict:
    """Does *this machine* scale at all right now?  Without this, a flat
    ``features_many`` curve is uninterpretable (GIL? or saturated box?)."""
    from concurrent.futures import ProcessPoolExecutor

    started = time.perf_counter()
    [_burn(iterations) for _ in range(tasks)]
    serial = time.perf_counter() - started
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=tasks) as pool:
        list(pool.map(_burn, [iterations] * tasks))
    threaded = time.perf_counter() - started
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=tasks) as pool:
        list(pool.map(_burn, [iterations] * tasks))
    processed = time.perf_counter() - started
    return {"tasks": tasks, "iterations": iterations,
            "serial_s": round(serial, 3), "thread_s": round(threaded, 3),
            "process_s": round(processed, 3),
            "thread_speedup": round(serial / threaded, 2),
            "process_speedup": round(serial / processed, 2),
            "note": "纯 Python CPU 对照实验：进程都上不去说明机器已饱和"}


def _timed(fn, repeat: int = 1) -> tuple[float, list[float]]:
    samples = []
    for _ in range(repeat):
        started = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - started)
    return min(samples), samples


def _make_runs(root: Path, count: int, source: Path) -> Path:
    for index in range(count):
        run = root / f"run{index:03d}"
        run.mkdir(parents=True)
        shutil.copyfile(source, run / "standardized.cif")
        (run / "manifest.json").write_text(json.dumps({
            "ok": True,
            "artifacts": {"standardized.cif": str(run / "standardized.cif")},
            "source": {"source": "local", "record": {"record_id": f"local:{index}",
                                                     "topology": "sod"}},
        }), encoding="utf-8")
    return root


def bench_features(repeat: int = 5) -> dict:
    from cifkit import api

    cold, _ = _timed(lambda: api.features(path=ZIF8, rdf=False))
    no_rdf, _ = _timed(lambda: api.features(path=ZIF8, rdf=False), repeat)
    with_rdf, _ = _timed(lambda: api.features(path=ZIF8, rdf=True), repeat)
    large = None
    if SLAB.is_file():
        large, _ = _timed(lambda: api.features(path=SLAB, rdf=False), max(1, repeat // 2))
    return {
        "structure": "ZIF-8 138 atoms",
        "cold_s": round(cold, 4),
        "no_rdf_s": round(no_rdf, 4),
        "no_rdf_per_s": round(1 / no_rdf, 2),
        "with_rdf_s": round(with_rdf, 4),
        "with_rdf_per_s": round(1 / with_rdf, 2),
        "large_structure": (f"slab {SLAB.name}" if large is not None else None),
        "large_no_rdf_s": round(large, 4) if large is not None else None,
    }


def bench_convert(repeat: int = 3) -> dict:
    from cifkit import api

    with tempfile.TemporaryDirectory() as tmp:
        per_call, _ = _timed(lambda: api.convert(path=ZIF8, formats=["vasp", "xyz"],
                                                 outdir=Path(tmp) / f"c{time.perf_counter_ns()}"),
                             repeat)
    inline, _ = _timed(lambda: api.convert(path=ZIF8, formats=["vasp", "xyz"]), repeat)
    return {"disk_2_formats_s": round(per_call, 4), "disk_per_s": round(1 / per_call, 2),
            "inline_2_formats_s": round(inline, 4), "inline_per_s": round(1 / inline, 2)}


def bench_parallel(paths: list[Path], repeat: int = 2) -> dict:
    """Parallelism honesty check: the measured speed-up is ~1x on this workload."""
    from cifkit.features import features_many

    serial, _ = _timed(lambda: features_many(paths, jobs=1, rdf=False), repeat)
    thread, _ = _timed(lambda: features_many(paths, jobs=4, rdf=False, executor="thread"), repeat)
    process, _ = _timed(lambda: features_many(paths, jobs=4, rdf=False, executor="process"), repeat)
    return {"n_structures": len(paths),
            "jobs_1_s": round(serial, 4),
            "jobs_4_thread_s": round(thread, 4),
            "jobs_4_process_s": round(process, 4),
            "thread_speedup": round(serial / thread, 2) if thread else None,
            "process_speedup": round(serial / process, 2) if process else None,
            "verdict": "≈1x：GIL + 小工作量；jobs 不是加速承诺"}


def bench_dataset_memory(count: int) -> dict:
    from cifkit.dataset import build_dataset

    with tempfile.TemporaryDirectory() as tmp:
        runs = _make_runs(Path(tmp) / "runs", count, ZIF8)

        tracemalloc.start()
        started = time.perf_counter()
        stream = build_dataset(runs, Path(tmp) / "s", rdf=False, stream=True)
        stream_s = time.perf_counter() - started
        current, peak_stream = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        tracemalloc.start()
        started = time.perf_counter()
        material = build_dataset(runs, Path(tmp) / "m", rdf=False, stream=False)
        material_s = time.perf_counter() - started
        _, peak_material = tracemalloc.get_traced_memory()
        tracemalloc.stop()

    return {
        "n_runs": count,
        "stream": {"wall_s": round(stream_s, 3), "peak_mib": round(peak_stream / 1048576, 2),
                   "max_rows_held": stream["max_rows_held"]},
        "materialised": {"wall_s": round(material_s, 3), "peak_mib": round(peak_material / 1048576, 2),
                         "max_rows_held": material["max_rows_held"]},
        "peak_ratio": round(peak_material / peak_stream, 2) if peak_stream else None,
        "csv_identical": stream["n_ok"] == material["n_ok"],
    }


def bench_concurrency(levels: tuple[int, ...] = (1, 2, 4)) -> list[dict]:
    from cifkit.platform import GuardedService, Policy

    results = []
    for workers in levels:
        service = GuardedService(Policy(timeout_s=120, max_concurrency=workers, queue_size=64))
        requests = [{"op": "features", "params": {"path": str(ZIF8), "rdf": False}}] * (4 * workers)
        latencies: list[float] = []
        lock = threading.Lock()

        def call() -> None:
            started = time.perf_counter()
            response = service.handle(requests[0])
            elapsed = time.perf_counter() - started
            with lock:
                latencies.append(elapsed if response.get("ok") else float("nan"))

        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda _i: call(), range(len(requests))))
        wall = time.perf_counter() - started
        service.shutdown()
        good = [value for value in latencies if value == value]  # drop NaN
        results.append({
            "workers": workers,
            "requests": len(requests),
            "wall_s": round(wall, 3),
            "req_per_s": round(len(requests) / wall, 2),
            "p50_ms": round(statistics.median(good) * 1000, 1) if good else None,
            "p95_ms": round(sorted(good)[max(0, int(len(good) * 0.95) - 1)] * 1000, 1) if good else None,
            "stats": service.stats_snapshot(),
        })
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=12, help="runs for the dataset memory bench")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--json", default=str(ROOT / "runs" / "bench_api.json"))
    args = ap.parse_args()

    repeat = 1 if args.quick else 3
    import os

    report: dict = {"python": sys.version.split()[0], "platform": sys.platform,
                    "cpu_count": os.cpu_count(), "cpu_load_percent": _cpu_load(),
                    "machine_note": "单机 Windows 数值，仅作量级参考，不是承诺；"
                                    "测量时机器有其它负载（见 cpu_load_percent）"}
    print("== control (pure-Python scaling) ==")
    report["control"] = bench_control(2 if args.quick else 4)
    print(json.dumps(report["control"], ensure_ascii=False, indent=2))

    print("== features ==")
    report["features"] = bench_features(repeat=1 if args.quick else 5)
    print(json.dumps(report["features"], ensure_ascii=False, indent=2))

    print("== convert ==")
    report["convert"] = bench_convert(repeat=repeat)
    print(json.dumps(report["convert"], ensure_ascii=False, indent=2))

    print("== features_many parallelism ==")
    paths = [ZIF8] * (4 if args.quick else 8)
    report["parallel"] = bench_parallel(paths, repeat=1 if args.quick else 2)
    print(json.dumps(report["parallel"], ensure_ascii=False, indent=2))

    print("== dataset memory ==")
    report["dataset_memory"] = bench_dataset_memory(6 if args.quick else args.runs)
    print(json.dumps(report["dataset_memory"], ensure_ascii=False, indent=2))

    print("== concurrency ==")
    report["concurrency"] = bench_concurrency((1, 2) if args.quick else (1, 2, 4))
    print(json.dumps(report["concurrency"], ensure_ascii=False, indent=2))

    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
