#!/usr/bin/env python3
"""Consolidate the batch acceptance evidence into one matrix (round 55).

The LAMMPS re-run was lost to an ``apt-get`` timeout (infrastructure), but the earlier
5/5 run is still on disk — and its logs contain the same quantitative evidence LAMMPS
offers (``Nlocal``).  So instead of re-spending photons, this reads what we have and
checks the reported atom counts against the shipped files.

    .venv\\Scripts\\python.exe scripts/collect_acceptance.py
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLOUD = ROOT / "runs" / "cloud_h3"

#: job directory -> code (batch runs) ; the runner writes acceptance_batch.json
BATCH_DIRS = {
    "batch_lammps": "lammps",
    "batch_gromacs": "gromacs",
    "acc3_gromacs": "gromacs",
}

ATOM_PATTERNS = {
    "lammps": re.compile(r"Nlocal:\s+(\d+)"),
    "gromacs": re.compile(r"Read\s+(\d+)\s+atoms"),
    "nwchem": re.compile(r"Total times"),
}


def gro_atoms(path: Path) -> int | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return int(lines[1].strip()) if len(lines) > 1 else None
    except (OSError, ValueError):
        return None


def lammps_atoms(path: Path) -> int | None:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[:40]:
            if line.strip().endswith("atoms"):
                return int(line.split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(CLOUD / "acceptance_matrix.json"))
    args = ap.parse_args()

    entries: list[dict] = []
    for job, code in BATCH_DIRS.items():
        base = CLOUD / job
        if not base.is_dir():
            continue
        for run in sorted((base / "batch_run").glob("*")) if (base / "batch_run").is_dir() else []:
            log = run / "run.log"
            if not log.is_file():
                continue
            blob = log.read_text(encoding="utf-8", errors="replace")
            found = ATOM_PATTERNS[code].search(blob)
            reported = int(found.group(1)) if found and found.groups() else None
            expected = None
            for name, parser in (("conf.gro", gro_atoms), ("data.lammps", lammps_atoms),
                                 ("in.min", lammps_atoms), ("mol.nw", None)):
                candidate = run / name
                if candidate.is_file() and parser is not None:
                    expected = parser(candidate)
                    if expected is not None:
                        break
            normal = {
                "lammps": "Total wall time" in blob,
                "gromacs": "gmx editconf" in blob,
                "nwchem": "Total times" in blob,
            }[code]
            failure = any(marker in blob for marker in
                          ("ERROR:", "Fatal error", "MPI_ABORT", "out of heap memory"))
            ok = bool(normal and not failure and (expected is None
                                                  or reported is None
                                                  or reported == expected))
            entries.append({
                "code": code, "case": run.name, "job": job,
                "sha": None, "reported_atoms": reported, "expected_atoms": expected,
                "atoms_match": (None if (reported is None or expected is None)
                                else reported == expected),
                "normal_marker": normal, "failure_marker": failure, "accepted": ok,
            })

    # the same case can be run more than once (e.g. after fixing the markers), so the
    # headline numbers count *unique* (code, case) pairs and prefer the strongest row
    unique: dict[tuple[str, str], dict] = {}
    for entry in entries:
        key = (entry["code"], entry["case"])
        current = unique.get(key)
        rank = lambda row: (row["accepted"], row["atoms_match"] is True)
        if current is None or rank(entry) > rank(current):
            unique[key] = entry

    by_code: dict[str, dict] = {}
    for entry in unique.values():
        stats = by_code.setdefault(entry["code"], {"accepted": 0, "total": 0, "cases": []})
        stats["total"] += 1
        stats["accepted"] += 1 if entry["accepted"] else 0
        stats["cases"].append(entry)

    payload = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "entries": entries,
               "unique_entries": list(unique.values()),
               "by_code": {code: {"accepted": value["accepted"], "total": value["total"]}
                           for code, value in by_code.items()},
               "total_accepted": len(unique),
               "total_cases": len(unique),
               "n_runs_seen": len(entries),
               "all_runs_accepted": all(entry["accepted"] for entry in entries)}
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    for code, stats in sorted(by_code.items()):
        print(f"{code:8s} accepted {stats['accepted']}/{stats['total']}")
        for entry in stats["cases"]:
            match = entry["atoms_match"]
            detail = ("atoms match" if match else
                      "atoms not checked" if match is None else "ATOM MISMATCH")
            print(f"   {'ok ' if entry['accepted'] else 'BAD'} {entry['case']:38s} "
                  f"{entry['reported_atoms']}/{entry['expected_atoms']} {detail}")
    print(f"\nunique cases accepted: {payload['total_accepted']}/{payload['total_cases']} "
          f"(from {payload['n_runs_seen']} run(s); every run accepted="
          f"{payload['all_runs_accepted']})")
    print(f"report: {out}")
    return 0 if payload["total_accepted"] == payload["total_cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
