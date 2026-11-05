"""Aggregate the per-element records into the deliverable tables and the zip.

Reads ``data/records.json`` / ``data/failures.json`` written by
``export_metals.py`` and produces:

* ``lattice.csv``                  all bulk lattice tables (task schema first)
* ``metals_summary.csv``           bulk + densest-surface data per element
* ``data/run_report.csv``          ok / failed + reason for all 87 metals
* ``data/slab_validation.csv``     independent re-validation of >= 10 slabs
* ``surface_energy/{INCAR,KPOINTS,README.md}``  global static-slab templates
* ``metals_kit.zip``               the whole kit (caches excluded)

Usage::

    python usecases/u3_metals/scripts/finalize_metals.py
    python usecases/u3_metals/scripts/finalize_metals.py --zip
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
from pymatgen.core import Structure

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from export_metals import (  # noqa: E402
    DATA,
    ELEMENTS_DIR,
    FAILURES,
    OUT_ROOT,
    RECORDS,
    VACUUM,
    VASP_ENCUT,
    load_json,
    metals,
)
from cifkit.types import TaskSpec  # noqa: E402
from cifkit.validate import validate_structure  # noqa: E402

LATTICE_COLUMNS = [
    "element", "Z", "prototype", "spacegroup_number", "spacegroup_symbol",
    "a", "b", "c", "alpha", "beta", "gamma", "V_per_atom",
    "source_aurl", "source_energy_atom", "natoms",
    "structure_type", "lattice_source", "structure_confidence", "sg_check",
    "pearson_primitive",
]
SUMMARY_COLUMNS = LATTICE_COLUMNS + [
    "densest_plane", "plane_hkl", "plane_method", "plane_confidence", "plane_rho",
    "interplanar_d", "layer_spacing",
    "surface_atoms", "slab_atoms", "slab_thickness", "vacuum_measured",
    "surface_area", "n_atomic_layers", "atoms_per_layer", "interlayer_spacing",
    "near_neighbor_bulk", "validate_ok", "validate_min_distance",
    "validate_duplicate_pairs", "status",
]
REPORT_COLUMNS = [
    "element", "status", "reason", "structure_type", "structure_confidence",
    "sg_check", "lattice_source", "densest_plane", "slab_atoms",
    "vacuum_measured", "source_aurl", "elapsed_s",
]

#: slabs re-validated from the files on disk (>= 10, includes the critical set)
VALIDATION_PICKS = [
    "Fe", "Cu", "Mg", "Al", "W", "Ti", "Nb", "Ni", "Zn", "Co",
    "In", "Sn", "Hg", "Sm", "Bi", "Mn", "Ga", "U", "Pa",
]


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


# ---------------------------------------------------------------------------
def write_tables(records: dict[str, dict], failures: dict[str, dict]) -> dict[str, Any]:
    els = metals()
    ok = [el for el in els if el in records]
    missing = [el for el in els if el not in records]
    lattice_rows = [records[el] for el in ok]
    summary_rows = [records[el] for el in ok]
    write_csv(OUT_ROOT / "lattice.csv", lattice_rows, LATTICE_COLUMNS)
    write_csv(OUT_ROOT / "metals_summary.csv", summary_rows, SUMMARY_COLUMNS)

    report_rows = []
    for el in els:
        if el in records:
            rec = records[el]
            report_rows.append(
                {
                    "element": el,
                    "status": rec.get("status", "ok"),
                    "reason": "exported (bulk + densest-plane slab)",
                    "structure_type": rec.get("structure_type"),
                    "structure_confidence": rec.get("structure_confidence"),
                    "sg_check": rec.get("sg_check"),
                    "lattice_source": rec.get("lattice_source"),
                    "densest_plane": rec.get("densest_plane"),
                    "slab_atoms": rec.get("slab_atoms"),
                    "vacuum_measured": rec.get("vacuum_measured"),
                    "source_aurl": rec.get("source_aurl"),
                    "elapsed_s": rec.get("elapsed_s"),
                }
            )
        else:
            fail = failures.get(el, {})
            report_rows.append(
                {
                    "element": el,
                    "status": "failed",
                    "reason": fail.get("reason", "not exported"),
                    "structure_type": "",
                    "structure_confidence": "",
                    "sg_check": "",
                    "lattice_source": "",
                    "densest_plane": "",
                    "slab_atoms": "",
                    "vacuum_measured": "",
                    "source_aurl": "",
                    "elapsed_s": fail.get("elapsed_s", ""),
                }
            )
    write_csv(DATA / "run_report.csv", report_rows, REPORT_COLUMNS)

    by_conf: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for el in ok:
        rec = records[el]
        by_conf[rec.get("structure_confidence", "?")] = by_conf.get(rec.get("structure_confidence", "?"), 0) + 1
        src = str(rec.get("lattice_source", ""))
        if "ASE" in src:
            src_key = "ASE reference_states (Kittel)"
        elif "COD" in src:
            src_key = "COD (experimental)"
        elif "AFLOW" in src:
            src_key = "AFLOW (client-side SG filter)"
        else:
            src_key = "other"
        by_source[src_key] = by_source.get(src_key, 0) + 1
    plane_counts: dict[str, int] = {}
    for el in ok:
        plane_counts[records[el]["densest_plane"]] = plane_counts.get(records[el]["densest_plane"], 0) + 1
    stats = {
        "n_metals_total": len(els),
        "n_exported": len(ok),
        "n_missing": len(missing),
        "missing_elements": missing,
        "failure_reasons": {el: failures.get(el, {}).get("reason", "") for el in missing},
        "by_confidence": by_conf,
        "by_source": by_source,
        "plane_counts": dict(sorted(plane_counts.items(), key=lambda kv: -kv[1])),
        "element_dirs": len([p for p in ELEMENTS_DIR.iterdir() if p.is_dir()]) if ELEMENTS_DIR.exists() else 0,
    }
    return stats


# ---------------------------------------------------------------------------
def validate_slabs(picks: list[str] | None = None) -> list[dict[str, Any]]:
    """Re-read every picked slab from disk and validate it independently."""
    picks = picks or VALIDATION_PICKS
    spec = TaskSpec(query="metal slab surface energy", vacuum=VACUUM)
    rows = []
    for el in picks:
        path = ELEMENTS_DIR / el / "slab.cif"
        if not path.exists():
            rows.append({"element": el, "file_ok": False, "reason": "slab.cif missing"})
            continue
        try:
            struct = Structure.from_file(str(path))
        except Exception as exc:  # noqa: BLE001
            rows.append({"element": el, "file_ok": False, "reason": f"parse: {exc}"})
            continue
        report = validate_structure(struct, spec=spec)
        m = report.metrics
        errors = [c for c in report.checks if not c.ok and getattr(c, "severity", "") == "error"]
        rows.append(
            {
                "element": el,
                "file_ok": True,
                "ok": bool(report.ok),
                "natoms": m.get("natoms"),
                "vacuum_measured": m.get("vacuum_measured"),
                "vacuum_requirement": VACUUM,
                "vacuum_ok": (m.get("vacuum_measured") or 0) + 1e-6 >= VACUUM,
                "min_distance": m.get("min_distance"),
                "duplicate_pairs": m.get("duplicate_pairs"),
                "duplicates_ok": (m.get("duplicate_pairs") or 0) == 0,
                "is_slab": m.get("is_slab"),
                "surface_area": m.get("surface_area"),
                "slab_thickness": m.get("slab_thickness"),
                "failed_error_checks": "; ".join(f"{c.name}: {c.detail}" for c in errors) or "",
            }
        )
    columns = [
        "element", "file_ok", "ok", "natoms", "vacuum_measured", "vacuum_requirement",
        "vacuum_ok", "min_distance", "duplicate_pairs", "duplicates_ok", "is_slab",
        "surface_area", "slab_thickness", "failed_error_checks",
    ]
    write_csv(DATA / "slab_validation.csv", rows, columns)
    return rows


# ---------------------------------------------------------------------------
SURFACE_INCAR = """\
# ============================================================================
#  Static single-point template for a metal slab surface-energy calculation
#  (generated by usecases/u3_metals/scripts/finalize_metals.py)
#
#  Workflow
#    1) bulk reference: run VASP on elements/<El>/bulk_POSCAR with the SAME
#       POTCAR / ENCUT / smearing -> E_bulk_cell [eV]
#         mu = E_bulk_cell / natoms_bulk          (energy per atom)
#    2) slab: run VASP on elements/<El>/slab_POSCAR -> E_slab [eV]
#    3) E_surf = (E_slab - N_slab * mu) / (2 * A)
#         N_slab = atoms in slab_POSCAR, A = |a x b| in A^2
#         (2A because both slab surfaces are equivalent by construction)
#  See surface_energy/README.md for details and the per-element numbers.
# ============================================================================
SYSTEM = <Element>_slab_<hkl>
PREC = Accurate
ENCUT = {encut}
EDIFF = 1E-6
ISMEAR = 1
SIGMA = 0.1
ALGO = Fast
LREAL = Auto
ISPIN = 2
LWAVE = .FALSE.
LCHARG = .FALSE.
NSW = 0
IBRION = -1
ISIF = 2
# Slab relaxation (optional): NSW = 200, IBRION = 2, ISIF = 2 and freeze the
# bottom two layers with Selective dynamics (F F F) in slab_POSCAR.
""".format(encut=VASP_ENCUT)

SURFACE_KPOINTS = """\
Automatic generation
0
Gamma
  12  12  1
  0.0  0.0  0.0
# Generic template: replace 12 12 1 with elements/<El>/KPOINTS, which is
# generated per element (~30 A per k-point in plane, kz = 1 for the slab).
# Converge E_surf with respect to the mesh before publishing.
"""

SURFACE_README = """\
# Surface-energy inputs (`surface_energy/`)

Static VASP templates for the densest-plane slab of every metal in this kit.

## Files

| file | meaning |
|---|---|
| `INCAR` | static single-point template (no ionic relaxation), see the comments |
| `KPOINTS` | generic Gamma-centred template; each element has its own tuned one in `elements/<El>/KPOINTS` |

## Formula

For a symmetric slab with two equivalent surfaces

    E_surf = (E_slab - N_slab * mu) / (2 * A)

* `E_slab` 鈥?total energy of `elements/<El>/slab_POSCAR` (eV)
* `mu` 鈥?bulk energy per atom: `E_bulk_cell / Z` from `elements/<El>/bulk_POSCAR`
  (`Z` is given in `lattice.csv`; `E_bulk_cell` is the VASP energy of that cell)
* `N_slab` 鈥?number of atoms in `slab_POSCAR` (also in `metals_summary.csv`)
* `A` 鈥?surface area of the slab cell, `|a x b|` in 脜虏 (also in
  `metals_summary.csv` as `surface_area`)
* `2A` 鈥?top and bottom surfaces (the slabs are built symmetric, so both have
  the same termination)

Equivalently with per-atom energies: `E_surf = (E_slab/N_slab - mu) * N_slab/(2A)`.

## Procedure

1. **Bulk reference** 鈥?run VASP on `elements/<El>/bulk_POSCAR` (k-mesh: the
   `KPOINTS` comment suggests the matching 3D mesh) and extract the total energy.
2. **Slab** 鈥?run VASP on `elements/<El>/slab_POSCAR` (vacuum 鈮?15 脜 in `c`;
   `KPOINTS` has `kz = 1`). To relax the surface, set `NSW`/`IBRION` as noted in
   `INCAR` and freeze the two bottom layers with Selective dynamics.
3. Apply the formula above with `N_slab` and `A` from `metals_summary.csv`.

## Notes / limitations

* Both surfaces of each slab are equivalent by construction 鈥?do **not** double
  count; the `2A` in the denominator already accounts for both.
* Use the same `POTCAR`, `ENCUT` and smearing for bulk and slab, otherwise the
  energy difference is not meaningful.
* The slabs are ideal (unrelaxed) crystallographic cuts at the experimental
  (Kittel / AFLOW / ICSD) lattice constants; a real surface energy needs the
  relaxed geometry and a convergence study (`ENCUT`, k-mesh, slab thickness,
  vacuum).
* `ISPIN = 2` is set for all elements; for non-magnetic metals the spin moment
  converges to zero (harmless, slightly slower).
* These files are inputs/templates only 鈥?**no VASP energies are included or
  claimed** in this kit.
"""


def write_surface_templates() -> None:
    d = OUT_ROOT / "surface_energy"
    d.mkdir(parents=True, exist_ok=True)
    (d / "INCAR").write_text(SURFACE_INCAR, encoding="utf-8")
    (d / "KPOINTS").write_text(SURFACE_KPOINTS, encoding="utf-8")
    (d / "README.md").write_text(SURFACE_README, encoding="utf-8")


# ---------------------------------------------------------------------------
def build_zip() -> Path:
    """Zip the kit; exclude caches/logs but keep scripts + tables + records."""
    zip_path = OUT_ROOT / "metals_kit.zip"
    include = [
        OUT_ROOT / "README.md",
        OUT_ROOT / "lattice.csv",
        OUT_ROOT / "metals_summary.csv",
        OUT_ROOT / "surface_energy",
        OUT_ROOT / "elements",
        OUT_ROOT / "scripts",
        DATA / "run_report.csv",
        DATA / "slab_validation.csv",
        DATA / "records.json",
        DATA / "failures.json",
        DATA / "summary_stats.json",
    ]
    skip_names = {"aflow_lib1_candidates.json", "export_log.txt", "__pycache__"}
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for item in include:
            if not item.exists():
                continue
            if item.is_file():
                if item.name in skip_names:
                    continue
                zf.write(item, item.relative_to(OUT_ROOT).as_posix())
                continue
            for path in sorted(item.rglob("*")):
                if path.is_dir() or path.name in skip_names or path.suffix == ".pyc":
                    continue
                zf.write(path, path.relative_to(OUT_ROOT).as_posix())
    return zip_path


# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zip", action="store_true", help="also build metals_kit.zip")
    ap.add_argument("--skip-validation", action="store_true")
    ap.add_argument("--validate-elements", default="", help="override the validation picks")
    args = ap.parse_args(argv)

    records = load_json(RECORDS, {})
    failures = load_json(FAILURES, {})
    if not records:
        print("no records: run export_metals.py first", file=sys.stderr)
        return 2
    stats = write_tables(records, failures)
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "summary_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(
        f"tables written: exported={stats['n_exported']}/{stats['n_metals_total']} "
        f"missing={stats['n_missing']} dirs={stats['element_dirs']}"
    )
    print(f"  by_source={stats['by_source']}  by_confidence={stats['by_confidence']}")
    print(f"  planes={stats['plane_counts']}")
    if stats["missing_elements"]:
        print(f"  missing: {', '.join(stats['missing_elements'])}")

    if not args.skip_validation:
        picks = [e.strip() for e in args.validate_elements.split(",") if e.strip()] or None
        rows = validate_slabs(picks)
        bad = [r for r in rows if not (r.get("ok") and r.get("vacuum_ok") and r.get("duplicates_ok"))]
        print(f"slab validation: {len(rows)} checked, {len(bad)} failed")
        for r in bad:
            print(f"  FAIL {r['element']}: {r}")
    write_surface_templates()
    print("surface_energy/{INCAR,KPOINTS,README.md} written")
    if args.zip:
        path = build_zip()
        print(f"zip: {path} ({path.stat().st_size / 1024:.0f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

