"""Launch **many GPU jobs at once** on Bohrium and aggregate the results.

This is the "超级 workflow" launcher: N independent batch jobs submitted
concurrently, polled together, every artifact downloaded and every photon counted.

    .venv\\Scripts\\python.exe scripts\\cloud_gpu_fanout.py --plan          # zero-network plan
    .venv\\Scripts\\python.exe scripts\\cloud_gpu_fanout.py --go --jobs 8   # spend photons

Hard gates (a careless call cannot burn the allowance):

* ``--go`` is required; without it nothing is submitted;
* ``--max-photons`` (default 300) aborts the whole run if the *remaining* photon
  balance cannot cover the worst case (jobs x max_run_time x price);
* the CNY balance is never used: submission always goes through
  ``--payment-source photon`` (this account's cash balance is negative);
* ``--dry-run`` on every job first, so a malformed input never reaches the cloud.

Cost model: ``price_rmb_per_hour`` comes from the SKU catalog; photons are
observed per job *after* the fact (settlement is asynchronous), so the report keeps
**all** observations instead of a single "final cost".
"""
from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOHR_ROOT = Path(r"D:\App\Bohrium")
BUNDLE = ROOT / "cloud_gpu"
OUT = ROOT / "runs" / "cloud_gpu"
DEFAULT_IMAGE = "registry.dp.tech/infra/pytorch:2.13.0-cuda12.6-cudnn9-runtime"
DEFAULT_SKU = "c16_m64_1 * NVIDIA 4090"


def bohr() -> Path:
    version = (BOHR_ROOT / "active-version").read_text(encoding="utf-8").strip()
    return BOHR_ROOT / "versions" / version / "bohr.exe"


def call(args: list[str], timeout: int = 600) -> tuple[int, str]:
    proc = subprocess.run([str(bohr()), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def json_from(text: str) -> dict:
    """Parse the first complete JSON object in possibly-noisy CLI output."""
    depth = 0
    start = -1
    for index, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(text[start:index + 1])
                except json.JSONDecodeError:
                    start = -1
    return {}


JOB_ID_RE = __import__("re").compile(r'"jobId"\s*:\s*"([0-9a-f]{16,})"')


def extract_job_id(text: str, payload: dict) -> str | None:
    """Find the job id even when the CLI printed progress lines around the JSON.

    Round 30: ``submit`` exited 0 and created a billed job, but the stdout was a
    stream of upload-progress objects followed by the payload, so the naive parse
    produced ``{}`` and the job was never polled -> untracked spend.
    """
    data = payload.get("data") or {}
    job_id = data.get("jobId") or data.get("job_id")
    if job_id:
        return str(job_id)
    match = JOB_ID_RE.search(text)
    return match.group(1) if match else None


def photons() -> int | None:
    code, out = call(["billing", "balance", "-o", "json"])
    payload = json_from(out)
    value = (payload.get("data") or {}).get("photon")
    return int(value) if isinstance(value, (int, float)) else None


def plan(jobs: int, run_minutes: int, wait_minutes: int, price: float, sku: str,
         photon_per_rmb: float) -> dict:
    """Worst-case exposure: run time **plus** queue time, at catalog price.

    Queue time is exposure, not free time — the platform bills the job record, and
    a job may sit ``--max-wait-time`` before it ever starts.
    """
    worst_run = jobs * run_minutes / 60.0 * price
    worst_wait = jobs * wait_minutes / 60.0 * price
    worst_total = worst_run + worst_wait
    return {"jobs": jobs, "sku": sku, "image": DEFAULT_IMAGE,
            "max_run_time_minutes": run_minutes, "max_wait_time_minutes": wait_minutes,
            "worst_case_run_only_rmb": round(worst_run, 3),
            "worst_case_with_queue_rmb": round(worst_total, 3),
            "photon_per_rmb": photon_per_rmb,
            "worst_case_photons": round(worst_total * photon_per_rmb, 1),
            "note": "catalog price x (run + wait); not a quote, not a settlement"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--sku", default=DEFAULT_SKU)
    ap.add_argument("--image", default=DEFAULT_IMAGE)
    ap.add_argument("--run-minutes", type=int, default=6)
    ap.add_argument("--wait-minutes", type=int, default=25)
    ap.add_argument("--price", type=float, default=6.00, help="catalog RMB/h (4090 = 6.00)")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--max-photons", type=int, default=300)
    ap.add_argument("--photon-per-rmb", type=float, default=95.0,
                    help="conversion used for the worst-case gate (observed: 4090 407 s ~ 64 photons "
                         "at 5.5-6 RMB/h => ~95 photons per RMB of catalog price)")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--out", default=str(OUT / "fanout.json"))
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    budget = plan(args.jobs, args.run_minutes, args.wait_minutes, args.price, args.sku,
                  args.photon_per_rmb)
    print(json.dumps(budget, ensure_ascii=False, indent=2))

    if args.plan or not args.go:
        available = photons()
        print(f"photon balance: {available}")
        print("plan only — add --go to submit (spends photons).")
        return 0

    available = photons()
    print(f"photon balance before: {available}")
    if available is None:
        print("refusing: photon balance unknown (gate must never fail open)")
        return 1
    projected = budget["worst_case_photons"]
    if projected > args.max_photons:
        print(f"refusing: projected worst case {projected} photons > --max-photons "
              f"{args.max_photons} (lower --jobs/--run-minutes or raise the cap)")
        return 1
    if available < args.max_photons:
        print(f"refusing: balance {available} photons < --max-photons {args.max_photons}")
        return 1

    # dry-run first: validates the input tree without creating anything
    code, out = call(["batchjob", "submit", "--dry-run", "--name", "gpu-fanout-probe",
                      "--image", args.image, "--machine-type", args.sku,
                      "--command", "python gpu_bench.py",
                      "--input", str(BUNDLE), "--max-run-time", f"{args.run_minutes}m",
                      "--max-wait-time", f"{args.wait_minutes}m", "-o", "json"])
    print("dry-run exit:", code)
    if code != 0:
        print(out[-600:])
        return code

    ledger_path = OUT / "submissions.jsonl"
    already: dict[int, dict] = {}
    if ledger_path.is_file():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("job_id"):
                already[int(row["index"])] = row
    if already:
        print(f"resuming: {len(already)} job(s) already in the ledger "
              f"({sorted(already)}) — they will not be submitted again")

    submitted: list[dict] = []
    lock = threading.Lock()

    def submit(index: int) -> dict:
        if index in already:
            row = dict(already[index])
            with lock:
                submitted.append(row)
            print(f"[skip {index:02d}] already submitted job={row['job_id']}")
            return row
        name = f"gpu-fanout-{index:02d}"
        cmd = ["batchjob", "submit", "--yes", "--payment-source", "photon",
               "--name", name, "--image", args.image, "--machine-type", args.sku,
               "--command", "python gpu_bench.py", "--input", str(BUNDLE),
               "--max-run-time", f"{args.run_minutes}m",
               "--max-wait-time", f"{args.wait_minutes}m",
               "--out-file", "gpu_result.json", "-o", "json"]
        try:
            code, text = call(cmd)
        except Exception as exc:  # noqa: BLE001 — a timeout must not abort the batch
            row = {"index": index, "name": name, "job_id": None,
                   "submit_exit": None, "submitted": False,
                   "error": f"{type(exc).__name__}: {exc}"}
            with lock:
                submitted.append(row)
            print(f"[submit {index:02d}] ERROR {row['error'][:120]}")
            return row
        payload = json_from(text)
        job_id = extract_job_id(text, payload)
        row = {"index": index, "name": name, "job_id": job_id, "submit_exit": code,
               "submitted": code == 0 and bool(job_id)}
        with lock:
            submitted.append(row)
            if job_id:
                with ledger_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"[submit {index:02d}] exit={code} job={job_id}")
        return row

    started = time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        list(pool.map(submit, range(1, args.jobs + 1)))
    print(f"submitted {sum(1 for r in submitted if r['submitted'])}/{args.jobs} "
          f"in {time.time() - started:.1f}s")

    orphans = [row for row in submitted if row.get("submit_exit") == 0 and not row.get("job_id")]
    if orphans:
        print(f"ABORT: {len(orphans)} submission(s) exited 0 without a job id — a billed job "
              f"may be running untracked; inspect `bohr batchjob list` before rerunning")
        return 1

    # stale artifacts from a previous run must not be attributed to this one
    run_started = time.time()
    for stale in OUT.glob("job_*"):
        if stale.is_dir():
            __import__("shutil").rmtree(stale, ignore_errors=True)

    live = [row for row in submitted if row.get("job_id")]
    terminal = {"succeeded", "failed", "cancelled", "stopped", "error"}
    results: dict[str, dict] = {}
    deadline = time.time() + (args.wait_minutes + args.run_minutes + 5) * 60
    while live and time.time() < deadline:
        still: list[dict] = []
        for row in live:
            try:
                code, text = call(["batchjob", "describe", row["job_id"], "-o", "json"],
                                  timeout=120)
            except Exception:  # noqa: BLE001
                still.append(row)
                continue
            data = json_from(text).get("data") or {}
            results[row["job_id"]] = {
                "status": data.get("status_name"),
                "reason": data.get("statusReason"),
                "exit_code": data.get("exitCode"),
                "spend_time_s": data.get("spendTime"),
                "photon_cost": data.get("photonCost"),
                "machine": data.get("machineType"),
            }
            if data.get("status_name") not in terminal:
                still.append(row)
        print(time.strftime("%H:%M:%S"),
              "states:", sorted({results[r["job_id"]]["status"] for r in live}), flush=True)
        live = still
        if live:
            time.sleep(20)

    if live:
        print(f"deadline reached with {len(live)} job(s) alive — killing them so they stop billing")
        for row in live:
            try:
                code, text = call(["batchjob", "kill", row["job_id"], "--yes", "-o", "json"],
                                  timeout=120)
                print(f"[kill {row['job_id']}] exit={code}")
            except Exception as exc:  # noqa: BLE001
                print(f"[kill {row['job_id']}] failed: {exc}")

    # fetch artifacts for terminal, downloaded jobs
    fetched: list[str] = []
    for row in submitted:
        job_id = row.get("job_id")
        if not job_id or results.get(job_id, {}).get("status") != "succeeded":
            continue
        dest = OUT / f"job_{row['index']:02d}"
        code, text = call(["batchjob", "download", job_id, "--dest", str(dest),
                           "--timeout", "8m", "-o", "json"], timeout=900)
        if code == 0:
            fetched.append(str(dest))

    metrics = []
    for row in submitted:
        job_id = row.get("job_id")
        dest = OUT / f"job_{row['index']:02d}" / "gpu_result.json"
        if not job_id or not dest.is_file():
            continue
        if dest.stat().st_mtime < run_started:
            print(f"[skip stale] {dest} predates this run")
            continue
        try:
            payload = json.loads(dest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            metrics.append({"index": row["index"], "job_id": job_id,
                            "error": f"unparseable result: {exc}"})
            continue
        metrics.append({
            "index": row["index"], "job_id": job_id,
            "device": payload.get("device_name"),
            "fp32_gflops": (payload.get("fp32") or {}).get("gflops"),
            "fp16_gflops": (payload.get("fp16") or {}).get("gflops"),
            "copy_gbps": payload.get("copy_gbps"),
            "checksum": payload.get("checksum"),
            "status": payload.get("status"),
            "state": results.get(job_id, {}).get("status"),
            "photon_cost": results.get(job_id, {}).get("photon_cost"),
            "spend_time_s": results.get(job_id, {}).get("spend_time_s"),
        })

    report = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "plan": budget,
              "photon_balance_before": available,
              "photon_balance_after": photons(),
              "submitted": submitted, "states": results, "fetched": fetched,
              "metrics": metrics}
    summary = {
        "jobs_requested": args.jobs,
        "jobs_submitted": sum(1 for r in submitted if r.get("job_id")),
        "succeeded": sum(1 for r in results.values() if r.get("status") == "succeeded"),
        "failed": sum(1 for r in results.values() if r.get("status") == "failed"),
        "with_metrics": len(metrics),
        "gpus_seen": sorted({m.get("device") for m in metrics if m.get("device")}),
        "fp32_gflops_range": [min((m["fp32_gflops"] for m in metrics if m.get("fp32_gflops")), default=None),
                              max((m["fp32_gflops"] for m in metrics if m.get("fp32_gflops")), default=None)],
        "total_photon_cost": sum((r.get("photon_cost") or 0) for r in results.values()),
        "total_photon_cost_note": "summed over every observed job record, including failures",
        "total_spend_time_s": sum(m.get("spend_time_s") or 0 for m in metrics),
        "wall_seconds": round(time.time() - started, 1),
    }
    report["summary"] = summary
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
