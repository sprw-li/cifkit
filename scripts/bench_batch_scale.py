"""Batch concurrency scaling: measure `--jobs 1…16` instead of assuming it.

Limitation G1 said batch concurrency had only been tested at 3.  This benchmark
runs the same number of real pipeline jobs at several pool sizes and reports wall
clock, speed-up, and efficiency, so the documented "start at 4" advice has numbers
behind it.

    .venv\\Scripts\\python.exe scripts\\bench_batch_scale.py [--jobs 8] [--repeats 1]
                                                             [--out runs/bench_batch_scale.json]

Method notes (honesty):
* one warm-up batch first, so index/cache builds do not land in the first sample;
* the same queries every time, each into its own outdir, so the compared work is
  identical;
* wall clock only — the machine is shared (``scripts/bench_api.py`` measured 4
  threads at 0.78x on a pure Python loop), so this is order-of-magnitude evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ("帮我下载典型的 RCSR 为 sod 的 MOF，需要碳上补充氢，创建一个 2x2x1 的超胞（Supercell），"
        "沿(111)面切出表面，并加上15Å的真空层，导出为计算化学软件使用的格式。")
LEVELS = (1, 2, 4, 8, 16)


def run_batch(spec_file: Path, outdir: Path, jobs: int, timeout: int = 3600) -> tuple[float, int]:
    started = time.time()
    proc = subprocess.run(
        [sys.executable, "-m", "cifkit", "batch", "--specs-file", str(spec_file),
         "--jobs", str(jobs), "--outdir", str(outdir)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout,
    )
    return time.time() - started, proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=8, help="number of parallel jobs to run per level")
    ap.add_argument("--levels", default="1,2,4,8,16")
    ap.add_argument("--out", default=str(ROOT / "runs" / "bench_batch_scale.json"))
    ap.add_argument("--workdir", default=str(ROOT / "runs" / "_batch_scale"))
    args = ap.parse_args()

    levels = [int(x) for x in args.levels.split(",") if x.strip()]
    work = Path(args.workdir)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    spec_file = work / "specs.jsonl"
    spec_file.write_text("\n".join(json.dumps({"spec": SPEC}) for _ in range(args.jobs)) + "\n",
                         encoding="utf-8")

    report: dict = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "n_jobs_per_level": args.jobs, "levels": levels,
                    "cpu_count": os.cpu_count(), "rows": []}

    # warm-up: populate caches with a single job
    warm_dir = work / "warm"
    warm_time, warm_code = run_batch(spec_file, warm_dir, 1, timeout=1800)
    print(f"warm-up: {warm_time:.1f}s (exit {warm_code})")
    report["warmup_seconds"] = round(warm_time, 1)

    baseline = None
    for level in levels:
        outdir = work / f"jobs_{level:02d}"
        try:
            seconds, code = run_batch(spec_file, outdir, level)
        except subprocess.TimeoutExpired:
            report["rows"].append({"jobs": level, "seconds": None, "error": "timeout"})
            print(f"jobs={level:2d}  TIMEOUT")
            continue
        speedup = (baseline / seconds) if baseline else 1.0
        efficiency = speedup / level
        if level == levels[0]:
            baseline = seconds
            speedup = 1.0
        row = {"jobs": level, "seconds": round(seconds, 2), "exit": code,
               "speedup": round(speedup, 2), "efficiency": round(efficiency, 2)}
        report["rows"].append(row)
        print(f"jobs={level:2d}  {seconds:7.1f}s  speedup {speedup:4.2f}x  "
              f"efficiency {efficiency:4.2f}  (exit {code})")

    valid = [row for row in report["rows"] if row.get("seconds")]
    if valid:
        report["best"] = max(valid, key=lambda row: row["speedup"])
        report["conclusion"] = (
            f"{args.jobs} 个真实 pipeline 作业：jobs=1 用时 {valid[0]['seconds']}s；"
            f"最佳加速在 jobs={report['best']['jobs']}（{report['best']['speedup']}x，"
            f"效率 {report['best']['efficiency']}）。机器 {os.cpu_count()} 核、共享，"
            "数字是数量级证据而非承诺。"
        )
        print("\n" + report["conclusion"])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("report:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
