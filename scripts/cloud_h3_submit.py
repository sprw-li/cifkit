"""Wrapper that runs the cloud-GPU escalation path for the H3 acceptance job.

Encodes the ``cloud-gpu-bohrium`` skill's "省钱顺序" (probe → dry-run → tiny probe
job → target job) as one command, with hard gates so a careless call cannot spend
photons:

* **no credentials → exit 1, no request** (it never invents a base URL);
* **no ``--go`` → dry-run only** (payload + catalog-price exposure, zero network);
* **``--go`` → probe first**, then submit the *tiny* job (default) unless
  ``--stage target`` is given, and record the cost history.

    .venv\\Scripts\\python.exe scripts\\cloud_h3_submit.py --check
    .venv\\Scripts\\python.exe scripts\\cloud_h3_submit.py --dry-run
    .venv\\Scripts\\python\\Scripts\\... --go            # tiny probe job

Evidence lands in ``runs/cloud_h3/`` (payload reports, cost history, fetched
artifacts).  Nothing here fabricates a result: without a real run the H3 limitation
stays open.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = Path(r"D:\agent-library\catalog\cloud-gpu-bohrium")
CLI = SKILL / "scripts" / "cloud_gpu.py"
BUNDLE = ROOT / "cloud_h3"
OUT = ROOT / "runs" / "cloud_h3"

CREDENTIAL_VARS = ("RELAYBENCH_GPU_BASE_URL", "BOHR_ACCESS_KEY", "BOHR_SECRET_KEY")

#: (label, command, max_run_time, max_wait_time, extra flags)
STAGES = {
    "probe": ("cifkit-h3-probe", "python run_acceptance.py", 5, 30, []),
    "cp2k": ("cifkit-h3-cp2k", "python run_acceptance.py --install cp2k", 60, 60, []),
}
DEFAULT_PRICE = 5.5


def credentials_state() -> dict[str, bool]:
    state = {}
    for name in CREDENTIAL_VARS:
        state[name] = bool(os.environ.get(name))
    return state


def build_zip() -> Path:
    target = OUT / "input.zip"
    OUT.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in BUNDLE.rglob("*") if p.is_file())
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(BUNDLE).as_posix())
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print(f"input bundle: {target} ({target.stat().st_size} bytes, {len(files)} files)")
    print(f"  sha256: {digest}")
    return target


def run_cli(args: list[str], *, network: bool) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(["py", "-3", str(CLI), *args], cwd=str(ROOT), env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=1800)
    print(proc.stdout.strip()[-2500:])
    if proc.returncode != 0 and proc.stderr.strip():
        print("stderr:", proc.stderr.strip()[-600:], file=sys.stderr)
    (OUT / f"cli_{args[0]}{'_' + args[1] if args and args[0] == 'dry-run' else ''}.log").write_text(
        (proc.stdout or "") + "\n--- stderr ---\n" + (proc.stderr or ""), encoding="utf-8")
    return proc


def bohr_cli() -> Path | None:
    """Locate the desktop Bohrium CLI (the *working* pipeline on this machine).

    Round 28 finding: the machine has a valid access key installed by the Bohrium
    desktop app (``bohr doctor`` → ``auth_validity: pass``) but **no** REST
    credentials in the environment; the official ``bohr batchjob`` module is then
    the correct entry point, and photons (not the CNY balance) must pay for it.
    """
    try:
        version = (Path(r"D:\App\Bohrium\active-version").read_text(encoding="utf-8").strip())
    except OSError:
        return None
    candidate = Path(r"D:\App\Bohrium\versions") / version / "bohr.exe"
    return candidate if candidate.is_file() else None


def run_bohr(args: list[str]) -> subprocess.CompletedProcess:
    """Run ``bohr <args>``; prints the CLI output and records it under runs/cloud_h3."""
    cli = bohr_cli()
    if cli is None:
        raise SystemExit("bohr CLI not found (D:\\App\\Bohrium\\active-version)")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run([str(cli), *args], cwd=str(ROOT), env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=3600)
    print(proc.stdout.strip()[-3000:])
    name = "_".join(part for part in args[:3] if not part.startswith("-"))
    (OUT / f"bohr_{name}.log").write_text(
        (proc.stdout or "") + "\n--- stderr ---\n" + (proc.stderr or ""), encoding="utf-8")
    return proc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report credential presence (no network)")
    ap.add_argument("--bohr", action="store_true",
                    help="用桌面端 bohr CLI（本机实测可用的管线，光子付费）")
    ap.add_argument("--bohr-status", action="store_true", help="bohr doctor + auth + billing(只读)")
    ap.add_argument("--dry-run", action="store_true", help="build the payload; zero network")
    ap.add_argument("--go", action="store_true", help="actually probe + submit (needs credentials)")
    ap.add_argument("--stage", choices=sorted(STAGES), default="probe")
    ap.add_argument("--image", default=None, help="image with CP2K/QE baked in (skips apt install)")
    ap.add_argument("--job-id", default=None, help="status/logs/fetch this existing job")
    ap.add_argument("--fetch-dest", default=str(OUT / "artifacts"))
    ap.add_argument("--sku-price-rmb-per-hour", type=float, default=DEFAULT_PRICE)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)

    if args.bohr_status or args.bohr:
        cli = bohr_cli()
        print(f"bohr CLI: {cli}")
        if cli is None:
            print("not installed — the REST path (RELAYBENCH_GPU_BASE_URL/… ) is the only option here")
            return 1
        for sub in (["doctor", "-o", "json"], ["auth", "status", "-o", "json"],
                    ["billing", "balance", "-o", "json"]):
            run_bohr(sub)
        if args.bohr_status and not args.bohr:
            print("\nread-only checks done. Re-run with --bohr --go to submit via `bohr batchjob`.")
            print("NOTE: this machine's CNY balance is insufficient; use photons via the CLIENT's")
            print("      --payment-source photon (the wrapper does that automatically).")
            return 0

    state = credentials_state()
    missing = [name for name, present in state.items() if not present]
    print("credentials:", {k: ("set" if v else "unset") for k, v in state.items()})

    if args.job_id:
        if missing:
            print(f"missing credentials: {', '.join(missing)} — refusing (no request sent)")
            return 1
        run_cli(["status", "--job-id", args.job_id,
                 "--cost-history", str(OUT / "cost_history.jsonl")], network=True)
        run_cli(["logs", "--job-id", args.job_id, "--tail", "200"], network=True)
        run_cli(["fetch", "--job-id", args.job_id, "--dest", args.fetch_dest], network=True)
        return 0

    bundle = build_zip()
    if args.check and not (args.dry_run or args.go):
        print("next: set the three variables in this shell (values never go into chat or files),")
        print("      then run:  scripts\\cloud_h3_submit.py --go")
        return 0 if not missing else 1

    label, command, run_minutes, wait_minutes, _ = STAGES[args.stage]
    if args.image:
        command = command.replace(" --install cp2k", "")  # the image already has it
        label = f"{label}-image"
    common = ["--name", label, "--input-zip", str(bundle), "--command", command,
              "--max-run-time", str(run_minutes), "--max-wait-time", str(wait_minutes),
              "--sku-price-rmb-per-hour", str(args.sku_price_rmb_per_hour),
              "--output-path", f"/sandbox-nas/runs/{label}"]
    if args.image:
        common += ["--image", args.image]

    report = OUT / f"dryrun_{args.stage}.json"
    dry = run_cli(["dry-run", *common, "--report", str(report)], network=False)
    if dry.returncode != 0:
        print("dry-run failed; not proceeding", file=sys.stderr)
        return dry.returncode
    if report.is_file():
        payload = json.loads(report.read_text(encoding="utf-8"))
        cost = payload.get("cost_estimate", {})
        print(f"cost exposure: run-only <= {cost.get('run_only_upper_bound_rmb')} RMB, "
              f"run+wait <= {cost.get('run_plus_wait_upper_bound_rmb')} RMB")

    if not args.go:
        print("\ndry-run only. Add --go to probe + submit (spends photons).")
        return 0

    if missing:
        print(f"\nmissing credentials: {', '.join(missing)}")
        print("refusing to submit — set the variables in this shell, then rerun with --go.")
        print("(The pipeline never invents a base URL; see the skill's hard rules.)")
        return 1

    if args.bohr:
        image = args.image or "registry.dp.tech/infra/pytorch:2.13.0-cuda12.6-cudnn9-runtime"
        machine = "c4_m8_cpu" if args.stage != "probe" else "c2_m4_cpu"
        command = command + (" --install cp2k" if args.image is None and args.stage != "probe" else "")
        dry = run_bohr(["batchjob", "submit", "--dry-run", "--name", label,
                        "--image", image, "--machine-type", machine,
                        "--command", command, "--input", str(BUNDLE),
                        "--max-run-time", f"{run_minutes}m", "--max-wait-time", f"{wait_minutes}m",
                        "-o", "json"])
        if dry.returncode != 0:
            return dry.returncode
        submit = run_bohr(["batchjob", "submit", "--yes", "--payment-source", "photon",
                           "--name", label, "--image", image, "--machine-type", machine,
                           "--command", command, "--input", str(BUNDLE),
                           "--max-run-time", f"{run_minutes}m",
                           "--max-wait-time", f"{wait_minutes}m",
                           "--out-file", "acceptance_result.json", "-o", "json"])
        if submit.returncode != 0:
            print("bohr submit failed — inspect the message; do not blindly retry", file=sys.stderr)
            return submit.returncode
        print("\njob submitted. Poll with:")
        print(f"  bohr batchjob describe <jobId> -o json   （或 --bohr-status 查看余额/光子）")
        return 0

    print("\n== probe (auth + SKU list; first thing after getting credentials) ==")
    probe = run_cli(["probe"], network=True)
    if probe.returncode != 0:
        print("probe failed — the REST paths/auth headers are *modelled*, not measured; "
              "do NOT retry submit; fix the modelling or the base URL.", file=sys.stderr)
        return probe.returncode

    print(f"\n== submit {label} (--confirm-cost) ==")
    submit = run_cli(["submit", "--confirm-cost", *common,
                      "--cost-history", str(OUT / "cost_history.jsonl"),
                      "--report", str(OUT / f"submit_{args.stage}.json")], network=True)
    if submit.returncode != 0:
        return submit.returncode

    submit_report = OUT / f"submit_{args.stage}.json"
    if submit_report.is_file():
        data = json.loads(submit_report.read_text(encoding="utf-8"))
        job_id = data.get("job_id") or (data.get("response") or {}).get("jobId")
        print(f"\njob id: {job_id}")
        print("poll with:  scripts\\cloud_h3_submit.py --job-id <id>")
        record = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "stage": args.stage,
                  "job_id": job_id, "image": args.image, "command": command,
                  "max_run_time_minutes": run_minutes, "payload_report": str(report)}
        (OUT / "submissions.jsonl").open("a", encoding="utf-8").write(
            json.dumps(record, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
