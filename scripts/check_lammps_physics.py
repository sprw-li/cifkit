"""Round 57: make the LAMMPS physics cross-check a permanent, executable gate.

The earlier claim was "LAMMPS accepted our file".  Stronger: LAMMPS's **reported LJ
energy** is reproduced by an independent implementation (``cifkit.lammps_reference``)
reading the **same shipped data file**, so the input drives the physics the parameters
describe - not merely a successful parse.

The recorded LAMMPS values come from cloud job ``060f75f5`` (LAMMPS ``7 Feb 2024 -
Update 1``, ``pair_style lj/cut 10.0``, ``pair_coeff * * 0.0103 3.4``), which are
exactly the parameters our shipped ``in.min`` now defaults to.  They are the
``Energy initial`` line of the ``minimize`` run - i.e. the energy at the *unrelaxed*
exported coordinates, which is what this reference computes.  The raw artifact is
``runs/cloud_h3/real_physics2/realphysics_probe.json`` (gitignored, local evidence);
the same three values are also in ``runs/cloud_h3/real_physics2/log``.
The job probed the first three sorted batches, which is why ``cloud_lj`` ships four
bundles (the fourth is ``lammps__zif8_cr_sod``) but only three have a recorded energy.

The tolerance is 1e-8.  That is not decoration: with the old 1e-5 the gate *passed*
while the reference silently dropped the body-diagonal lattice shifts of the cubic
cells (mof5 was off by 1.5e-7 relative, hkust1 by 4.0e-9).  With the image handling
fixed the three cases agree with LAMMPS to ~1e-12 relative, so 1e-8 keeps four orders
of margin against summation-order noise while still failing a broken enumerator.

This script is the gate: it exits non-zero if any case drifts beyond tolerance, so a
future change to the writer (coordinates, box, precision) cannot silently break the
physics agreement.  Offline checkouts that do not ship ``cloud_lj/`` are an explicit
skip (exit 0, no report written) rather than a pass on zero cases.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: LAMMPS-reported energy at the exported coordinates (job 060f75f5, 2026-11-11)
RECORDED: dict[str, dict] = {
    "lammps__hkust1_hfree": {"E_pair_eV": 409124.98253649, "atoms": 132},
    "lammps__mof5_hfree": {"E_pair_eV": 173145.377770684, "atoms": 82},
    "lammps__terephthalic_acid_hfree": {"E_pair_eV": 178719.393379894, "atoms": 16},
}

PARAMETERS = {"epsilon_eV": 0.0103, "sigma_A": 3.4, "cutoff_A": 10.0}
#: the reference reproduces the recorded values to ~1e-12; 1e-8 is the gate
DEFAULT_RTOL = 1e-8


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rtol", type=float, default=DEFAULT_RTOL)
    ap.add_argument("--json", default=str(ROOT / "runs" / "lammps_physics.json"))
    args = ap.parse_args()

    bundles = {case: ROOT / "cloud_lj" / "data" / case / "data.lammps"
               for case in RECORDED}
    present = {case: path for case, path in bundles.items() if path.is_file()}
    missing = sorted(set(bundles) - set(present))
    if not present:
        # No data at all: an honest skip, not a vacuous pass.  Do not write a report
        # (a stale runs/lammps_physics.json from another checkout must not be
        # presented as the result of this run).
        print("[skip] no cloud_lj/data bundles in this checkout - the physics gate "
              "needs the shipped data.lammps files; nothing was verified")
        return 0

    from pymatgen.core import Lattice, Structure

    from cifkit.lammps_data import read_data_lammps
    from cifkit.lammps_reference import compare_with_lammps

    rows = []
    failures = 0
    for case, expected in sorted(present.items()):
        lattice, positions, _types = read_data_lammps(expected)
        structure = Structure(Lattice(lattice), ["C"] * len(positions), positions,
                              coords_are_cartesian=True)
        verdict = compare_with_lammps(structure,
                                      epsilon_ev=PARAMETERS["epsilon_eV"],
                                      sigma_a=PARAMETERS["sigma_A"],
                                      cutoff_a=PARAMETERS["cutoff_A"],
                                      lammps_energy=RECORDED[case]["E_pair_eV"],
                                      rtol=args.rtol)
        verdict["case"] = case
        verdict["atoms_expected"] = RECORDED[case]["atoms"]
        rows.append(verdict)
        ok = verdict["match"] and len(structure) == RECORDED[case]["atoms"]
        failures += 0 if ok else 1
        print(f"[{'ok ' if ok else 'FAIL'}] {case:34s} "
              f"natoms={len(structure):4d}/{RECORDED[case]['atoms']:4d} "
              f"ours={verdict['ours_eV']:18.6f} "
              f"lammps={verdict['lammps_eV']:18.6f} rel={verdict['relative']:.2e}")
    for case in missing:
        print(f"[skip] {case}: {bundles[case]} not found")

    payload = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "parameters": PARAMETERS, "rtol": args.rtol,
               "cases": rows, "missing": missing,
               "ok": failures == 0 and not missing,
               "source": "cloud job 060f75f5 (LAMMPS 7 Feb 2024 - Update 1), "
                         "Energy initial at the exported coordinates"}
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = payload["ok"]
    print(f"\nphysics cross-check: {'PASS' if ok else 'FAIL'} "
          f"({len(rows) - failures}/{len(RECORDED)} cases"
          + (f", missing {missing}" if missing else "") + f") — {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
