#!/usr/bin/env python3
"""Run **cifkit's own NWChem export** in a real NWChem binary (H3b probe).

This is deliberately different from ``run_acceptance.py``: that one verifies a
hand-written minimal case, this one feeds NWChem the file *we* generate, so the
result says something about our exporter, not about the harness.

    python run_our_template.py [--install]

Writes ``our_template_result.json`` with the exit code, the NWChem version line,
whether the run finished normally, and the diagnostic lines on failure.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASE = "mol.nw"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true", help="apt-get install nwchem first")
    parser.add_argument("--out", default="our_template_result.json")
    args = parser.parse_args()

    report: dict = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "case": CASE,
                    "install": None, "nwchem": None, "version": None,
                    "exit": None, "finished_normally": False, "tail": "", "errors": []}

    if args.install and not shutil.which("nwchem"):
        started = time.time()
        proc = subprocess.run(["bash", "-lc", "apt-get update -qq && apt-get install -y nwchem"],
                              capture_output=True, text=True)
        report["install"] = {"exit": proc.returncode, "seconds": round(time.time() - started, 1)}
        print(f"[install] nwchem exit {proc.returncode} in {report['install']['seconds']}s")

    binary = shutil.which("nwchem")
    report["nwchem"] = binary
    if not binary:
        report["errors"].append("nwchem not installed")
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("nwchem not installed")
        return 0

    workdir = Path(os.environ.get("TMPDIR", "/tmp")) / "nwchem_run"
    workdir.mkdir(parents=True, exist_ok=True)
    source = HERE / "cases" / CASE
    if not source.is_file():
        source = HERE / CASE
    shutil.copyfile(source, workdir / CASE)
    report["input_bytes"] = (workdir / CASE).stat().st_size

    started = time.time()
    proc = subprocess.run([binary, CASE], cwd=workdir, capture_output=True, text=True, timeout=900)
    report["seconds"] = round(time.time() - started, 1)
    report["exit"] = proc.returncode
    blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    report["finished_normally"] = "Total times" in blob and proc.returncode == 0
    for line in blob.splitlines():
        low = line.lower()
        if "nwchem version" in low or low.strip().startswith("nwchem"):
            report["version"] = report["version"] or line.strip()[:120]
        if any(marker in low for marker in ("error", "cannot", "failed", "not found", "aborting")):
            report["errors"].append(line.strip()[:200])
    report["tail"] = blob[-2500:]
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"nwchem exit={report['exit']} finished_normally={report['finished_normally']} "
          f"({report['seconds']}s)")
    print(report["tail"][-1200:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
