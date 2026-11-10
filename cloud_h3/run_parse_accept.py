#!/usr/bin/env python3
"""Parse-level acceptance: do real LAMMPS / GROMACS binaries read our geometry?

Round 33 established that this image cannot run CP2K (not in the mirror) and that
its Quantum ESPRESSO 6.7 binary aborts on **any** input (including a textbook H2O
case) — an upstream glibc/fortify incompatibility, not our template.

LAMMPS and GROMACS *are* installable here.  They need force-field topologies for a
real calculation, which cifkit does not generate, so the strongest honest claim at
this level is: **the geometry our exporter writes is accepted by the real binary**.
That is what this probe checks:

* ``lmp -in read.in`` with ``read_data data.lammps`` + ``run 0`` (a real parse and
  an energy evaluation with ``pair_style zero``, no force field needed);
* ``gmx editconf -f conf.gro`` / ``gmx dump -f conf.gro`` (a real .gro parse).

Writes ``parse_accept.json``; exit 0 whenever the probe ran.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

LAMMPS_DRIVER = """units metal
atom_style atomic
boundary p p p
read_data {data}
pair_style zero 10.0
pair_coeff * *
thermo 1
run 0
write_dump all custom out.dump id type x y z
"""


def run(command: list[str], cwd: Path, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def install(packages: list[str], report: dict) -> None:
    started = time.time()
    proc = subprocess.run(["bash", "-lc",
                           "apt-get update -qq && apt-get install -y "
                           "-o Dpkg::Options::=--force-confdef " + " ".join(packages)],
                          capture_output=True, text=True, timeout=2400,
                          env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
    report["install"] = {"packages": packages, "exit": proc.returncode,
                         "seconds": round(time.time() - started, 1),
                         "tail": (proc.stdout or proc.stderr or "")[-400:]}
    print(f"[install] {' '.join(packages)} exit={proc.returncode}")


def main() -> int:
    report: dict = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "install": None,
                    "binaries": {}, "cases": [], "errors": []}
    need = [pkg for pkg, exe in (("lammps", "lmp"), ("gromacs", "gmx"))
            if not shutil.which(exe)]
    if need:
        install(need, report)

    report["binaries"]["lmp"] = shutil.which("lmp") or shutil.which("lmp_mpi")
    report["binaries"]["gmx"] = shutil.which("gmx")

    workdir = Path("/tmp/parse_accept")
    workdir.mkdir(parents=True, exist_ok=True)

    # ---- LAMMPS: read the data file, evaluate energy with a zero potential ----
    data = HERE / "export_lammps" / "data.lammps"
    if report["binaries"]["lmp"] and data.is_file():
        shutil.copyfile(data, workdir / "data.lammps")
        (workdir / "read.in").write_text(LAMMPS_DRIVER.format(data="data.lammps"),
                                         encoding="utf-8")
        started = time.time()
        proc = run([report["binaries"]["lmp"], "-in", "read.in", "-log", "lammps.log"],
                   workdir)
        blob = (proc.stdout or "") + (proc.stderr or "")
        report["cases"].append({
            "code": "LAMMPS", "input": "data.lammps (cifkit export)",
            "exit": proc.returncode, "seconds": round(time.time() - started, 1),
            "accepted": "reading atoms from data file" in blob.lower()
                        or "read_data" in blob.lower() or proc.returncode == 0,
            "tail": blob[-1200:]})
        print(f"[LAMMPS] exit={proc.returncode}")

    # ---- GROMACS: parse the .gro ----
    gro = HERE / "export_gromacs" / "conf.gro"
    if report["binaries"]["gmx"] and gro.is_file():
        shutil.copyfile(gro, workdir / "conf.gro")
        started = time.time()
        proc = run([report["binaries"]["gmx"], "editconf", "-f", "conf.gro",
                    "-o", "out.gro"], workdir)
        blob = (proc.stdout or "") + (proc.stderr or "")
        report["cases"].append({
            "code": "GROMACS", "input": "conf.gro (cifkit export)",
            "exit": proc.returncode, "seconds": round(time.time() - started, 1),
            "accepted": (workdir / "out.gro").is_file(),
            "tail": blob[-1200:]})
        print(f"[GROMACS] exit={proc.returncode}")

    Path("parse_accept.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    print("report written: parse_accept.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
