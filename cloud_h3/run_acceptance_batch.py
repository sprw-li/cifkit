#!/usr/bin/env python3
"""Run every prepared case for one code, in one job (round 55, high-batch H3c).

Installing the code is the expensive part (LAMMPS took 244 s, GROMACS similar), so a
job should install once and then run **all** the cases prepared by
``.probe/gen_batch_cases.py`` (``cases/batch/<code>__<structure>/``).

Prints one ``ACCEPTANCE …`` line per case and writes ``acceptance_batch.json``:

    python3 run_acceptance_batch.py --code lammps
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

CASES = {
    "lammps": {"packages": ["lammps"], "binary": ("lmp", "lmp_mpi", "lmp_serial"),
               "input": "in.min", "run": ["{binary}", "-in", "in.min"],
               "normal": ("Total wall time", "Loop time"),
               "evidence": r"Nlocal:\s+(\d+)",
               "failure": ("ERROR",)},
    "gromacs": {"packages": ["gromacs"], "binary": ("gmx", "gmx_mpi"),
                "input": "conf.gro",
                "run": ["{binary}", "editconf", "-f", "conf.gro", "-o", "out.gro"],
                # 'gmx editconf, 2023.3' is the real banner; the *quantity* is what
                # proves parsing, so both are required below
                "normal": ("gmx editconf", "GROMACS reminds you"),
                "evidence": r"Read\s+(\d+)\s+atoms",
                "failure": ("Fatal error", "Error in user input", "Invalid")},
    "nwchem": {"packages": ["nwchem"], "binary": ("nwchem",), "input": "mol.nw",
               "run": ["{binary}", "mol.nw"],
               "normal": ("Total times",), "failure": ("MPI_ABORT", "out of heap memory")},
}


def memory_directive(fraction: float = 0.6) -> str:
    total_mb = 8192
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    total_mb = int(line.split()[1]) // 1024
                    break
    except OSError:
        pass
    total = max(1024, int(total_mb * fraction))
    stack = max(200, total // 12)
    heap = max(512, int((total - stack) * 0.45))
    return (f"memory total {total} mb stack {stack} mb heap {heap} mb "
            f"global {total - stack - heap} mb")


def install(packages: list[str]) -> bool:
    import os

    proc = subprocess.run(["bash", "-lc",
                           "export DEBIAN_FRONTEND=noninteractive; "
                           "apt-get update -qq && apt-get install -y -qq "
                           "--no-install-recommends " + " ".join(packages)],
                          capture_output=True, text=True,
                          env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
                          timeout=2400)
    print(f"apt-get exit={proc.returncode}", flush=True)
    if proc.returncode != 0:
        print((proc.stdout or "")[-600:])
        print((proc.stderr or "")[-600:])
    return proc.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", required=True, choices=sorted(CASES))
    parser.add_argument("--max-seconds", type=int, default=1200)
    args = parser.parse_args()
    spec = CASES[args.code]

    if not install(spec["packages"]):
        print(f"ACCEPTANCE_BATCH code={args.code} status=install-failed")
        return 1
    binary = next((shutil.which(name) for name in spec["binary"] if shutil.which(name)), None)
    print(f"binary: {binary}", flush=True)
    if binary is None:
        print(f"ACCEPTANCE_BATCH code={args.code} status=no-binary")
        return 1

    cases = sorted(path for path in Path("cases/batch").glob(f"{args.code}__*") if path.is_dir())
    print(f"cases: {[path.name for path in cases]}", flush=True)
    results = []
    for case in cases:
        workdir = Path("batch_run") / case.name
        if workdir.exists():
            shutil.rmtree(workdir)
        workdir.mkdir(parents=True)
        for source in case.iterdir():
            if source.is_file():
                shutil.copy2(source, workdir / source.name)
        if args.code == "nwchem":
            target = workdir / spec["input"]
            target.write_text(memory_directive() + "\n" + target.read_text(encoding="utf-8"),
                              encoding="utf-8")
        command = [part.format(binary=binary) for part in spec["run"]]
        started = time.time()
        try:
            proc = subprocess.run(command, cwd=str(workdir), capture_output=True,
                                  text=True, timeout=args.max_seconds)
            blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
            code = proc.returncode
        except subprocess.TimeoutExpired as exc:
            blob = str(exc.stdout or "") + "\n" + str(exc.stderr or "")
            code = "timeout"
        (workdir / "run.log").write_text(blob, encoding="utf-8")
        normal = next((m for m in spec["normal"] if m in blob), None)
        failure = next((m for m in spec["failure"] if m in blob), None)
        # quantitative evidence: how many atoms did the code report reading?
        reported = None
        pattern = spec.get("evidence")
        if pattern:
            found = re.search(pattern, blob)
            if found:
                reported = int(found.group(1))
        expected = _input_atom_count(workdir / spec["input"])
        atoms_match = (reported is not None and expected is not None
                       and reported == expected)
        status = ("accepted" if (normal and not failure and (atoms_match or expected is None))
                  else "failed-marker" if failure else "no-normal-marker")
        results.append({"case": case.name, "status": status, "exit": code,
                        "normal_marker": normal, "failure_marker": failure,
                        "atoms_reported": reported, "atoms_expected": expected,
                        "atoms_match": atoms_match,
                        "seconds": round(time.time() - started, 1)})
        print(f"ACCEPTANCE code={args.code} case={case.name} status={status} exit={code} "
              f"normal={normal!r} failure={failure!r}", flush=True)

    payload = {"code": args.code, "binary": binary, "results": results,
               "n_accepted": sum(1 for row in results if row["status"] == "accepted"),
               "n_total": len(results), "when": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    Path("acceptance_batch.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
    print(f"ACCEPTANCE_BATCH code={args.code} accepted={payload['n_accepted']}/"
          f"{payload['n_total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

def _input_atom_count(path: Path) -> int | None:
    """Atom count recorded in the shipped coordinate file (gro: line 2; lammps: header)."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    if path.suffix == ".gro" and len(lines) > 1:
        try:
            return int(lines[1].strip())
        except ValueError:
            return None
    for line in lines[:40]:
        if line.strip().endswith("atoms"):
            try:
                return int(line.split()[0])
            except (ValueError, IndexError):
                return None
    return None
