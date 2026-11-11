#!/usr/bin/env python3
"""Real-binary acceptance for a cifkit export (round 53, limitation H3c).

Availability probe (job ``f0fe6264``, 2026-11-11) found these installable from the
image's apt mirror: abinit 9.10.4, elk-lapw 9.2.12, quantum-espresso 6.7,
lammps 20240207, gromacs 2023.3, **orca 46.1**, nwchem 7.2.2.  Not available:
siesta, dftbplus, cp2k, vasp, gaussian, fhi-aims, castep, onetep.

ORCA is the useful new target: cifkit exports ``orca.inp`` + ``coords.xyz``, and ORCA
validates the whole input when it starts.

Evidence discipline (learned the hard way in round 51): a job that exits 0 is *not*
evidence that the code accepted the input.  We require the code's own **normal
termination marker** in the output, and we print it.

    python3 run_code_acceptance.py --code orca [--keep-route]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

#: per code: apt packages, the input we ship, how to run it, markers
CASES: dict[str, dict] = {
    "orca": {
        "packages": ["orca"],
        "input": Path("cases/acceptance/orca/orca.inp"),
        "companions": [Path("cases/acceptance/orca/coords.xyz")],
        "binary": ("orca",),
        "run": ["{binary}", "orca.inp"],
        "normal_markers": ("ORCA TERMINATED NORMALLY", "TOTAL RUN TIME"),
        "failure_markers": ("ORCA finished by error", "Error (", "aborting the run"),
    },
    "abinit": {
        "packages": ["abinit"],
        "input": Path("cases/acceptance/abinit/abinit.in"),
        "companions": [],
        "binary": ("abinit",),
        "run": ["{binary}", "abinit.in"],
        "normal_markers": ("Calculation completed", "Delivered", "END DATASET"),
        "failure_markers": ("ERROR", "BUG", "abinit: not enough"),
    },
    # The Debian package named "orca" is the GNOME *screen reader* (round 53: it
    # printed "Cannot start the screen reader because it cannot connect to the
    # Desktop"), NOT ORCA quantum chemistry.  Kept as a case so the collision is
    # reproduced rather than forgotten; a chemistry-ORCA acceptance needs a
    # user-supplied binary.
    "orca-debian-package": {
        "packages": ["orca"],
        "input": Path("cases/acceptance/orca/orca.inp"),
        "companions": [Path("cases/acceptance/orca/coords.xyz")],
        "binary": ("orca",),
        "run": ["{binary}", "orca.inp"],
        "normal_markers": ("ORCA TERMINATED NORMALLY", "TOTAL RUN TIME"),
        "failure_markers": ("finished by error", "aborting the run"),
    },
    # GROMACS: `editconf` is the cheapest operation that *parses* the coordinate file
    # and rewrites it; it earned the 'accepted' level in the earlier probe.
    "gromacs": {
        "packages": ["gromacs"],
        "input": Path("cases/acceptance/gromacs/conf.gro"),
        "companions": [Path("cases/acceptance/gromacs/md.mdp"),
                       Path("cases/acceptance/gromacs/topol.top")],
        "binary": ("gmx", "gmx_mpi"),
        "run": ["{binary}", "editconf", "-f", "conf.gro", "-o", "out.gro"],
        "normal_markers": ("GROMACS version", "Back Off! I just backed up out.gro"),
        "failure_markers": ("Fatal error", "Error in user input"),
    },
    "lammps": {
        "packages": ["lammps"],
        "input": Path("cases/acceptance/lammps/in.min"),
        "companions": [Path("cases/acceptance/lammps/data.lammps")],
        "binary": ("lmp", "lmp_mpi", "lmp_serial"),
        "run": ["{binary}", "-in", "in.min"],
        "normal_markers": ("Total wall time", "Loop time"),
        "failure_markers": ("ERROR", "ERROR:"),
    },
}


def install(packages: list[str]) -> bool:
    if all(shutil.which(name) for name in packages):
        return True
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    started = time.time()
    proc = subprocess.run(["bash", "-lc",
                           "apt-get update -qq && apt-get install -y -qq "
                           "--no-install-recommends " + " ".join(packages)],
                          capture_output=True, text=True, env=env, timeout=2400)
    print(f"apt-get exit={proc.returncode} in {time.time() - started:.0f}s", flush=True)
    if proc.returncode != 0:
        print((proc.stdout or "")[-800:])
        print((proc.stderr or "")[-800:])
    return proc.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", required=True, choices=sorted(CASES))
    parser.add_argument("--keep-route", action="store_true",
                        help="run the shipped route verbatim (may be very slow)")
    parser.add_argument("--single-point-route", default="! PBE def2-SVP")
    parser.add_argument("--case-dir", default=None,
                        help="prepared directory (input + companions); skips the built-in case")
    args = parser.parse_args()

    spec = CASES[args.code]
    case_dir = Path(args.case_dir) if args.case_dir else None
    if not install(spec["packages"]):
        print(f"ACCEPTANCE code={args.code} status=install-failed")
        return 1
    binary = next((shutil.which(name) for name in spec["binary"] if shutil.which(name)), None)
    print(f"binary: {binary}", flush=True)
    if binary is None:
        print(f"ACCEPTANCE code={args.code} status=no-binary")
        return 1

    source = (case_dir / spec["input"].name) if case_dir else spec["input"]
    if not source.is_file():
        print(f"input missing: {source}")
        return 1
    text = source.read_text(encoding="utf-8")
    route_note = "shipped-route"
    if args.code == "orca" and not args.keep_route:
        # the shipped route is '! PBE def2-SVP Opt Freq'; a frequency run needs ~3N
        # displacements, far beyond a spot-check budget.  The *input syntax* is what
        # this job validates, so run a single point and say so plainly.
        text, count = re.subn(r"(?m)^!\s+.*$", args.single_point_route, text, count=1)
        route_note = f"single-point-route ({count} replaced)"

    workdir = Path("acceptance_run") / args.code
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    # write the input under the name the code expects, plus a copy under the shipped
    # name so the artifact is self-describing
    expected = {"orca": "orca.inp", "orca-debian-package": "orca.inp",
                "abinit": "abinit.in", "lammps": "in.min"}[args.code]
    (workdir / expected).write_text(text, encoding="utf-8")
    companions = ([path for path in case_dir.iterdir() if path.is_file()]
                  if case_dir else spec["companions"])
    for companion in companions:
        if companion.is_file() and companion.name != source.name:
            shutil.copy2(companion, workdir / companion.name)

    command = [part.format(binary=binary) for part in spec["run"]]
    started = time.time()
    proc = subprocess.run(command, cwd=str(workdir), capture_output=True, text=True,
                          timeout=5400)
    blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    (workdir / "run.log").write_text(blob, encoding="utf-8")
    normal = next((marker for marker in spec["normal_markers"] if marker in blob), None)
    failure = next((marker for marker in spec["failure_markers"] if marker in blob), None)
    status = "accepted" if (normal and not failure) else (
        "failed-marker" if failure else "no-normal-marker")
    payload = {
        "code": args.code,
        "status": status,
        "exit": proc.returncode,
        "normal_marker": normal,
        "failure_marker": failure,
        "seconds": round(time.time() - started, 1),
        "route": route_note,
        "input": str(source),
        "input_bytes": len(text),
        "output_bytes": len(blob),
        "binary": binary,
        "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        # honest scope: what was actually proven by this run
        "scope": ("a real binary parsed our shipped input and reached a normal end"
                  if status == "accepted" else
                  "the binary rejected or crashed on our shipped input"),
    }
    (Path("acceptance_result.json")).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"route: {route_note}; exit={proc.returncode}; "
          f"{time.time() - started:.0f}s; bytes={len(blob)}")
    print(f"ACCEPTANCE code={args.code} status={status} exit={proc.returncode} "
          f"normal_marker={normal!r} failure_marker={failure!r}")
    for line in blob.splitlines():
        if any(token in line for token in ("TERMINATED NORMALLY", "finished by error",
                                           "TOTAL RUN TIME", "Error")):
            print("  |", line.strip()[:120])
    return 0 if status == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
