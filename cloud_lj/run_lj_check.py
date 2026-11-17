#!/usr/bin/env python3
"""LAMMPS `run 0` energy for the exact data files we ship (round 57).

A controlled physics check: ``run 0`` evaluates the energy at the **unrelaxed** exported
coordinates, so it can be compared directly with an independent evaluation of the same
LJ sum.  The parameters come from our generated ``in.min`` defaults.

Input bundle is deliberately tiny (this directory only): the earlier upload of the whole
``cloud_h3`` tree failed with a transient storage error.

    python3 run_lj_check.py
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

EPSILON = 0.0103      # eV   (placeholder UFF-like value shipped in in.min)
SIGMA = 3.4           # A
CUTOFF = 10.0         # A


def apt(package: str) -> bool:
    proc = subprocess.run(
        ["bash", "-lc", f"export DEBIAN_FRONTEND=noninteractive; apt-get update -qq && "
                       f"apt-get install -y -qq --no-install-recommends {package}"],
        capture_output=True, text=True,
        env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"}, timeout=1800)
    print(f"apt {package}: exit={proc.returncode}", flush=True)
    return proc.returncode == 0


def main() -> None:
    if not apt("lammps"):
        Path("lj_check.json").write_text(json.dumps({"error": "apt failed"}), encoding="utf-8")
        return
    binary = shutil.which("lmp") or shutil.which("lmp_mpi") or shutil.which("lmp_serial")
    results = []
    for data in sorted(glob.glob("data/*/*.lammps")):
        case = Path(data).parent.name
        work = Path("lj") / case
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        shutil.copy2(data, work / "data.lammps")
        script = f"""units           metal
atom_style      atomic
boundary        p p p
read_data       data.lammps
pair_style      lj/cut {CUTOFF}
pair_coeff      * * {EPSILON} {SIGMA}
neighbor        2.0 bin
thermo          1
thermo_style    custom step pe etotal
run             0
"""
        (work / "in.run0").write_text(script, encoding="utf-8")
        started = time.time()
        proc = subprocess.run([binary, "-in", "in.run0"], cwd=str(work),
                              capture_output=True, text=True, timeout=900)
        blob = (proc.stdout or "") + (proc.stderr or "")
        (work / "run0.log").write_text(blob, encoding="utf-8")
        energies = re.findall(r"^\s*(\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)", blob, re.M)
        atoms = re.search(r"^\s*(\d+) atoms", blob, re.M)
        results.append({"case": case, "exit": proc.returncode,
                        "atoms": int(atoms.group(1)) if atoms else None,
                        "E_pair_eV": float(energies[-1][1]) if energies else None,
                        "error": next((line.strip() for line in blob.splitlines()
                                       if "ERROR" in line), None),
                        "seconds": round(time.time() - started, 1)})
        print(f"  {case}: exit={proc.returncode} atoms={results[-1]['atoms']} "
              f"E_pair={results[-1]['E_pair_eV']} err={results[-1]['error']}", flush=True)
    payload = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "parameters": {"epsilon_eV": EPSILON, "sigma_A": SIGMA, "cutoff_A": CUTOFF},
               "results": results}
    Path("lj_check.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    print("LJ_DONE")


if __name__ == "__main__":
    main()
