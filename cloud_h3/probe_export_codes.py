#!/usr/bin/env python3
"""Probe which electronic-structure codes this image can install (round 53, H3c).

The earlier probe found quantum-espresso/gromacs/lammps/nwchem/elk-lapw installable
and cp2k absent.  This asks specifically about the codes **cifkit can export to**, so
an acceptance test can be added for whichever are available:

    python3 probe_export_codes.py
"""
from __future__ import annotations

import shutil
import subprocess

#: cifkit export formats that are real codes (bundle names)
CODES = {
    "abinit": "abinit",
    "siesta": "siesta",
    "elk": "elk-lapw",
    "dftb": "dftbplus",
    "cp2k": "cp2k",
    "qe": "quantum-espresso",
    "lammps": "lammps",
    "gromacs": "gromacs",
    "nwchem": "nwchem",
    "orca": "orca",
    "vasp": "vasp",
    "gaussian": "gaussian",
    "aims": "fhi-aims",
    "castep": "castep",
    "onetep": "onetep",
}

APT_BINARIES = {
    "abinit": ("abinit",),
    "siesta": ("siesta",),
    "elk": ("elk", "elk-lapw"),
    "dftb": ("dftb+", "dftbplus"),
    "cp2k": ("cp2k.popt", "cp2k.psmp", "cp2k"),
    "qe": ("pw.x",),
    "lammps": ("lmp", "lmp_mpi", "lammps"),
    "gromacs": ("gmx", "gmx_mpi"),
    "nwchem": ("nwchem",),
}


def apt_policy(package: str) -> str:
    proc = subprocess.run(["apt-cache", "policy", package], capture_output=True,
                          text=True, timeout=120)
    for line in (proc.stdout or "").splitlines():
        if "Candidate:" in line:
            return line.split("Candidate:", 1)[1].strip()
    return "(no Candidate line)"


def main() -> None:
    print("== already installed ==")
    for code, binaries in APT_BINARIES.items():
        found = next((shutil.which(binary) for binary in binaries if shutil.which(binary)), None)
        print(f"{code:9s} binary={found}")

    print("== apt candidates ==")
    for code, package in CODES.items():
        print(f"{code:9s} package={package:20s} candidate={apt_policy(package)}")

    print("== versions of installed codes ==")
    for binary, args in (("gmx", ["--version"]), ("lmp", ["-h"]), ("nwchem", []),
                         ("abinit", ["--version"]), ("siesta", ["--version"]),
                         ("elk", ["-v"])):
        path = shutil.which(binary)
        if not path:
            continue
        try:
            proc = subprocess.run([path, *args], capture_output=True, text=True, timeout=60)
            head = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()[:2]
            print(f"{binary}: {' | '.join(line.strip() for line in head)}")
        except Exception as exc:  # noqa: BLE001
            print(f"{binary}: version probe failed: {type(exc).__name__}")


if __name__ == "__main__":
    main()
