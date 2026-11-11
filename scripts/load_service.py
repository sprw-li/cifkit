#!/usr/bin/env python3
"""Service load curve: measure throughput and latency percentiles (round 46, J5).

Limitation J5 said the guarded service had back-pressure (``max_concurrency``,
``queue_size`` → 503 ``busy``) but **no measured pressure curve**.  This script
measures one, honestly:

* the workload is an in-process op on a small real structure (a real code path, not
  a sleep);
* closed-loop clients at increasing concurrency, so the numbers answer "what
  happens when N callers share this service?";
* p50/p90/p99 latency, throughput, and the count of ``busy``/``timeout`` replies;
* the result JSON is what the docs quote — machine-specific, and labelled as such.

    .venv\\Scripts\\python.exe scripts\\load_service.py [--levels 1,2,4,8] [--seconds 5]
"""
from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CIF = ROOT / "tests" / "data" / "zif8_cr_sod.cif"


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def run_level(service, cif_text: str, level: int, seconds: float) -> dict:
    """Closed-loop load at ``level`` concurrent workers for ``seconds``."""
    latencies: list[float] = []
    errors: dict[str, int] = {}
    stop = threading.Event()
    lock = threading.Lock()

    def worker() -> None:
        while not stop.is_set():
            started = time.perf_counter()
            try:
                reply = service.handle({"op": "validate", "params": {"cif_text": cif_text}})
                elapsed = time.perf_counter() - started
                with lock:
                    if reply.get("ok"):
                        latencies.append(elapsed)
                    else:
                        key = str((reply.get("error") or {}).get("code", "error"))
                        errors[key] = errors.get(key, 0) + 1
            except Exception as exc:  # noqa: BLE001 - a load test must survive anything
                with lock:
                    key = type(exc).__name__
                    errors[key] = errors.get(key, 0) + 1

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(level)]
    started = time.perf_counter()
    for thread in threads:
        thread.start()
    time.sleep(seconds)
    stop.set()
    for thread in threads:
        thread.join(timeout=30)
    wall = time.perf_counter() - started
    return {
        "level": level,
        "wall_s": round(wall, 3),
        "requests": len(latencies) + sum(errors.values()),
        "ok": len(latencies),
        "throughput_rps": round(len(latencies) / wall, 3) if wall else 0.0,
        "p50_ms": round(1000 * (percentile(latencies, 0.50) or 0.0), 2),
        "p90_ms": round(1000 * (percentile(latencies, 0.90) or 0.0), 2),
        "p99_ms": round(1000 * (percentile(latencies, 0.99) or 0.0), 2),
        "mean_ms": round(1000 * statistics.fmean(latencies), 2) if latencies else None,
        "errors": errors,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", default="1,2,4,8")
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--max-concurrency", type=int, default=4)
    ap.add_argument("--queue-size", type=int, default=32)
    ap.add_argument("--json", default=str(ROOT / "runs" / "service_load.json"))
    args = ap.parse_args()

    from cifkit.platform import GuardedService, Policy
    from cifkit.service import handle as raw_handle

    cif_text = DEFAULT_CIF.read_text(encoding="utf-8")
    policy = Policy(max_concurrency=args.max_concurrency, queue_size=args.queue_size)
    service = GuardedService(policy)
    levels = [int(token) for token in args.levels.split(",")]

    # warm up so the first level is not paying import/JIT costs
    warmed = raw_handle({"op": "validate", "params": {"cif_text": cif_text}})
    if not warmed.get("ok"):
        print(f"warm-up failed: {warmed}")
        return 1

    report: dict = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "machine_note": "single shared box; numbers are machine-specific",
                    "policy": {"max_concurrency": args.max_concurrency,
                               "queue_size": args.queue_size},
                    "op": "validate", "levels": [], "ok": True}
    for level in levels:
        row = run_level(service, cif_text, level, args.seconds)
        row["speedup_vs_1"] = None
        report["levels"].append(row)
        print(f"level={level:2d} rps={row['throughput_rps']:7.2f} "
              f"p50={row['p50_ms']:7.2f}ms p90={row['p90_ms']:8.2f}ms "
              f"errors={row['errors']}")

    if report["levels"]:
        base = report["levels"][0]["throughput_rps"] or 1.0
        for row in report["levels"]:
            row["speedup_vs_1"] = round(row["throughput_rps"] / base, 3)
        report["scaling"] = {str(row["level"]): row["speedup_vs_1"] for row in report["levels"]}
        report["busy_replies"] = sum(row["errors"].get("busy", 0) for row in report["levels"])
        report["throughput_peak_rps"] = max(row["throughput_rps"] for row in report["levels"])
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nscaling: {report.get('scaling')}\nreport: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
