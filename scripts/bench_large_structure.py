"""Per-stage capability probe on a large structure (performance + honest limits).

Answers "how big can this actually go?" by timing every stage on a real large
structure instead of guessing.  Defaults to the largest Cr-based MOF in the bundled
CoRE MOF 2024 dataset (11152 atoms), which is also the nearest available relative
of MIL-101 (see ``scripts/audit_dataset_coverage.py`` and limitation C2).

    .venv\\Scripts\\python.exe scripts\\bench_large_structure.py [--entry KEY] [--supercell 2x2x1]

The script **never** expands a supercell by default: it reports the projected atom
count so the boundary is explicit rather than discovered by a machine that runs out
of memory.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENTRY = "SI/NCR/Chen_Manz/am9b13361_si_002_ASR_pacman.cif"


def _load(entry: str, archive: Path, raw: bytes):
    from pymatgen.core import Structure

    with tempfile.NamedTemporaryFile("wb", suffix=".cif", delete=False) as handle:
        handle.write(raw)
        path = handle.name
    try:
        return Structure.from_file(path)
    finally:
        Path(path).unlink(missing_ok=True)


def _fraction_to_tuple(text: str) -> tuple[int, int, int]:
    parts = text.lower().replace(" ", "").split("x")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise argparse.ArgumentTypeError("expected NxNxN, e.g. 2x2x1")
    return tuple(int(p) for p in parts)  # type: ignore[return-value]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", default=DEFAULT_ENTRY, help="member path inside the CoRE zip")
    ap.add_argument("--archive", default=str(ROOT / "_cache" / "core-mof-2024" / "CoREMOF2024DB.zip"))
    ap.add_argument("--supercell", type=_fraction_to_tuple, default=None,
                    help="actually build this supercell (off by default)")
    ap.add_argument("--json", default=str(ROOT / "runs" / "bench_large_structure.json"))
    args = ap.parse_args()

    archive = Path(args.archive)
    if not archive.is_file():
        print(f"archive not found: {archive}")
        return 1

    report: dict = {"entry": args.entry, "stages": []}

    def stage(name: str, fn):
        started = time.perf_counter()
        try:
            value = fn()
            report["stages"].append({"stage": name, "ok": True,
                                     "seconds": round(time.perf_counter() - started, 2),
                                     "value": value if isinstance(value, dict) else None})
            print(f"[ok  ] {name:28s} {report['stages'][-1]['seconds']:8.2f}s {value}")
            return value
        except Exception as exc:  # noqa: BLE001
            report["stages"].append({"stage": name, "ok": False,
                                     "seconds": round(time.perf_counter() - started, 2),
                                     "error": f"{type(exc).__name__}: {exc}"})
            print(f"[FAIL] {name:28s} {report['stages'][-1]['seconds']:8.2f}s "
                  f"{type(exc).__name__}: {exc}")
            return None

    with zipfile.ZipFile(archive) as zf:
        if args.entry not in zf.namelist():
            print(f"entry not in archive: {args.entry}")
            return 1
        raw = zf.read(args.entry)
    report["cif_bytes"] = len(raw)

    holder: dict = {}

    def load():
        structure = _load(args.entry, archive, raw)
        holder["structure"] = structure
        report["n_atoms"] = len(structure)
        report["formula"] = structure.composition.reduced_formula
        return {"n_atoms": len(structure), "formula": structure.composition.reduced_formula}

    if stage("load_structure", load) is None:
        return 1
    structure = holder["structure"]

    def bonds():
        from cifkit.repair.bonds import perceive_bonds

        graph = perceive_bonds(structure)
        holder["graph"] = graph
        return {"bonds": len(graph.unique_bonds()), "metals": sum(graph.metals),
                "organometallic": graph.organometallic_bonds, "warnings": len(graph.warnings)}

    stage("perceive_bonds", bonds)

    def demand():
        from cifkit.repair.bonds import hydrogen_demand

        demands = hydrogen_demand(holder["graph"])
        total = sum(max(0, d.missing) for d in demands)
        return {"atoms_needing_h": sum(1 for d in demands if d.missing > 0), "total_h": total}

    stage("hydrogen_demand", demand)

    def features():
        from cifkit.features import extract_features

        row = extract_features(structure, rdf=False)
        return {"natoms": row["natoms"], "density": row.get("density_g_cm3"),
                "spacegroup": row.get("spacegroup_number")}

    stage("features(no rdf)", features)

    def rings():
        from cifkit.features import extract_features

        row = extract_features(structure, rdf=False, rings=True)
        return {"ring_basis": row.get("ring_basis"), "truncated": row.get("rings_truncated")}

    stage("features(rings)", rings)

    def validate():
        from cifkit.validate import validate_structure

        rep = validate_structure(structure)
        return {"ok": rep.ok, "checks": len(rep.checks)}

    stage("validate", validate)

    factor = args.supercell or (2, 2, 1)
    projected = len(structure) * factor[0] * factor[1] * factor[2]
    report["projected_supercell"] = {"factor": list(factor), "atoms": projected}
    if args.supercell:
        def build_supercell():
            big = structure.copy()
            big.make_supercell(factor)
            return {"n_atoms": len(big)}

        stage(f"supercell {factor[0]}x{factor[1]}x{factor[2]}", build_supercell)
    else:
        print(f"(supercell {factor[0]}x{factor[1]}x{factor[2]} NOT built: would be {projected} atoms; "
              f"pass --supercell to try it)")

    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
