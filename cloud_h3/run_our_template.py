#!/usr/bin/env python3
"""Run **cifkit's own NWChem export** in a real NWChem binary (H3b probe).

Round 29 history:
  * job 3: our export declared a periodic system but asked for ``task dft`` ->
    ``dft_rdinput: detected periodicity = 3``;
  * job 4: a stray ``end`` from the removed ``dft`` block ->
    ``input_parse: unknown directive end``;
  * job 5: ``nwpw`` + ``ecut`` -> ``nwpw_input: unknown directive: ecut``;
  * probe: the pattern that actually finished is ``nwpw`` + ``cutoff`` +
    ``xc`` + ``end`` + ``task pspw energy`` (verified in NWChem 7.2.2);
  * job 6/7: our regenerated file parses and starts the SCF, then hits
    ``out of heap memory`` — NWChem's default heap is too small for a 138-atom
    cell at cutoff 20, so this runner now passes ``-memory`` explicitly and the
    verification uses a small cell.

Usage:
    python run_our_template.py --install [--case cases/mol_small.nw]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CASE = "cases/mol.nw"


def available_mb() -> int:
    """Total RAM in MB (Linux container)."""
    try:
        text = Path("/proc/meminfo").read_text(encoding="utf-8")
        match = re.search(r"MemTotal:\s+(\d+)\s+kB", text)
        if match:
            return int(match.group(1)) // 1024
    except OSError:
        pass
    return 4096


def memory_directive(fraction: float = 0.6) -> str:
    """NWChem needs an explicit heap, and this build has no ``-memory`` option.

    Round 29: ``nwchem -memory "total …"`` and even ``nwchem -help`` both failed
    with "failed to open the input file" — Debian's NWChem 7.2.2 treats every
    extra word as an input filename.  The supported way is a ``memory`` directive
    at the top of the input, so the runner prepends one (the template itself stays
    machine-independent).
    """
    # NWChem requires the parts to *add up*: total = stack + heap + global.
    # A spec where heap+global alone exceeds total aborts with
    # "Memory_Defaults: Inconsistent memory specification" (round 29, job v8).
    total = max(1024, int(available_mb() * fraction))
    stack = max(200, total // 12)
    heap = max(512, int((total - stack) * 0.45))
    global_mem = total - stack - heap
    return (f"memory total {total} mb stack {stack} mb "
            f"heap {heap} mb global {global_mem} mb")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true", help="apt-get install nwchem first")
    parser.add_argument("--case", default=DEFAULT_CASE, help="input file inside the bundle")
    parser.add_argument("--memory-fraction", type=float, default=0.6)
    parser.add_argument("--out", default="our_template_result.json")
    args = parser.parse_args()

    report: dict = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "case": args.case,
                    "install": None, "nwchem": None, "memory_flags": [], "ram_mb": available_mb(),
                    "exit": None, "finished_normally": False, "tail": "", "errors": []}

    report["memory_directive"] = memory_directive(args.memory_fraction)

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

    source = HERE / args.case
    if not source.is_file():
        source = HERE / Path(args.case).name
    if not source.is_file():
        report["errors"].append(f"case not found: {args.case}")
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("case not found")
        return 0

    workdir = Path(os.environ.get("TMPDIR", "/tmp")) / "nwchem_run"
    workdir.mkdir(parents=True, exist_ok=True)
    name = Path(args.case).name
    body = source.read_text(encoding="utf-8")
    prepared = workdir / f"run_{name}"
    prepared.write_text(report["memory_directive"] + "\n" + body, encoding="utf-8")
    report["input_bytes"] = prepared.stat().st_size

    command = [binary, prepared.name]
    report["command"] = " ".join(command)
    started = time.time()
    proc = subprocess.run(command, cwd=workdir, capture_output=True, text=True, timeout=1800)
    report["seconds"] = round(time.time() - started, 1)
    report["exit"] = proc.returncode
    blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    report["finished_normally"] = "Total times" in blob and proc.returncode == 0
    for line in blob.splitlines():
        low = line.lower()
        if "nwchem version" in low or low.strip().startswith("nwchem"):
            report.setdefault("version", line.strip()[:120])
        if any(marker in low for marker in
               ("error", "cannot", "failed", "not found", "aborting", "out of heap")):
            report["errors"].append(line.strip()[:200])
    report["tail"] = blob[-2500:]
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"nwchem exit={report['exit']} finished_normally={report['finished_normally']} "
          f"({report['seconds']}s)")
    print(report["tail"][-1200:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
