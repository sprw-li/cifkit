#!/usr/bin/env python3
"""Cloud-side acceptance probe for real calculation software (H3).

Runs inside the Bohrium container.  It does exactly what
``scripts/check_software.py`` does on the host, but standalone (stdlib only):

1. detect calculation codes on ``PATH``;
2. run a **minimal self-contained** case for each code found;
3. check a code-specific success marker;
4. write ``acceptance_result.json`` (and echo a short report) so the host can
   ``fetch`` it.

Optional: ``python run_acceptance.py --install cp2k`` tries to install a code with
``apt-get`` first (needs network in the container; bandwidth is ~100 kB/s, so this
is a deliberate, explicit choice — see the skill's reference/limits.md).

Exit code: 0 when at least one code reaches ``verified``; 1 when nothing is
installed (a useful result: it means the *image* lacks the software, not that the
harness failed).
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

HERE = Path(__file__).resolve().parent

CODES = {
    "VASP": {"binaries": ["vasp_std", "vasp_gam", "vasp"], "marker": "General timing",
             "case": None, "needs": "POTCAR (licensed)"},
    "Quantum ESPRESSO": {"binaries": ["pw.x"], "marker": "JOB DONE",
                         "case": "cases/qe_h2o.in", "needs": "UPF pseudopotentials"},
    "CP2K": {"binaries": ["cp2k.psmp", "cp2k.popt", "cp2k.ssmp", "cp2k"],
             "marker": "PROGRAM ENDED AT", "case": "cases/cp2k_h2o.inp", "needs": "CP2K data dir"},
    "ORCA": {"binaries": ["orca"], "marker": "ORCA TERMINATED NORMALLY",
             "case": "cases/orca_h2.inp", "needs": "none (STO-3G is built in)"},
    "DFTB+": {"binaries": ["dftb+"], "marker": "Total Energy", "case": None,
              "needs": "Slater-Koster .skf files"},
    "NWChem": {"binaries": ["nwchem"], "marker": "Total times", "case": "cases/nwchem_h2.nw",
               "needs": "none"},
    "Gaussian": {"binaries": ["g16", "g09"], "marker": "Normal termination", "case": None,
                 "needs": "license"},
    "LAMMPS": {"binaries": ["lmp", "lmp_mpi"], "marker": "Total wall time", "case": None,
               "needs": "force field"},
    "GROMACS": {"binaries": ["gmx"], "marker": "Finished mdrun", "case": None,
                "needs": "force field"},
}


def find(binaries: list[str]) -> str | None:
    for name in binaries:
        path = shutil.which(name)
        if path:
            return path
    return None


def command_for(code: str, binary: str, case: str | None, workdir: Path) -> str | None:
    if case is None:
        return None
    case_path = HERE / case
    if not case_path.is_file():
        return None
    name = case_path.name
    local = workdir / name
    shutil.copyfile(case_path, local)
    if code == "Quantum ESPRESSO":
        return f'"{binary}" -in {name}'
    if code == "CP2K":
        data = os.environ.get("CIFKIT_CP2K_DATA") or str(Path(binary).parent / "data")
        return f'"{binary}" -i {name} --data-dir "{data}"'
    return f'"{binary}" {name}'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="append", default=[],
                        help="apt-get install this package before probing (needs network)")
    parser.add_argument("--out", default="acceptance_result.json")
    args = parser.parse_args()

    report: dict = {
        "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "hostname": os.uname().nodename if hasattr(os, "uname") else os.environ.get("HOSTNAME", "?"),
        "python": sys.version.split()[0],
        "cuda": cuda_summary(),
        "install_requests": args.install,
        "installs": [],
        "codes": [],
    }

    for package in args.install:
        started = time.time()
        proc = subprocess.run(["bash", "-lc", f"apt-get update -qq && apt-get install -y {package}"],
                              capture_output=True, text=True)
        report["installs"].append({"package": package, "exit": proc.returncode,
                                   "seconds": round(time.time() - started, 1),
                                   "tail": (proc.stdout or "")[-400:]})
        print(f"[install] {package}: exit {proc.returncode}")

    verified: list[str] = []
    for code, spec in CODES.items():
        binary = find(spec["binaries"])
        row: dict = {"code": code, "binary": binary, "needs": spec["needs"], "status": "not-installed"}
        if binary:
            import tempfile

            with tempfile.TemporaryDirectory(prefix=f"acc-{code.split()[0].lower()}-") as tmp:
                command = command_for(code, binary, spec["case"], Path(tmp))
                if command is None:
                    row["status"] = "no-minimal-case"
                else:
                    started = time.time()
                    try:
                        proc = subprocess.run(command, shell=True, cwd=tmp, capture_output=True,
                                              text=True, timeout=600)
                        blob = f"{proc.stdout or ''}\n{proc.stderr or ''}"
                        if spec["marker"] in blob:
                            row["status"] = "verified"
                            verified.append(code)
                        elif proc.returncode == 0:
                            row["status"] = "ran-no-marker"
                        else:
                            row["status"] = "failed"
                        row["exit"] = proc.returncode
                        row["tail"] = blob[-500:]
                    except subprocess.TimeoutExpired:
                        row["status"] = "timeout"
                    row["seconds"] = round(time.time() - started, 1)
        report["codes"].append(row)
        print(f"[{row['status']:>14s}] {code:18s} {binary or '-'}")

    report["verified"] = verified
    report["ok"] = bool(verified)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nverified: {verified or 'none'}")
    print(f"report written: {args.out}")
    return 0 if verified else 1


def cuda_summary() -> dict:
    """Best-effort CUDA visibility report (the image is a CUDA runtime image)."""
    summary: dict = {"nvidia_smi": False}
    try:
        proc = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
                               "--format=csv,noheader"], capture_output=True, text=True, timeout=60)
        summary["nvidia_smi"] = proc.returncode == 0
        summary["gpus"] = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    except Exception as exc:  # noqa: BLE001
        summary["error"] = f"{type(exc).__name__}: {exc}"
    return summary


if __name__ == "__main__":
    raise SystemExit(main())
