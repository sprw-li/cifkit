"""Export lattice + densest-surface data for the 87 metallic elements.

Output layout (all under ``usecases/u3_metals/``)::

    elements/<El>/bulk.cif               conventional cell (CIF)
    elements/<El>/bulk_POSCAR            conventional cell (VASP POSCAR, VASP5)
    elements/<El>/slab.cif               densest-plane slab + 15 A vacuum
    elements/<El>/slab_POSCAR            same slab as VASP POSCAR
    elements/<El>/lattice.csv            one-row bulk lattice table
    elements/<El>/INCAR, KPOINTS         per-element static-slab templates
    surface_energy/{INCAR,KPOINTS,README.md}   global templates
    data/records.json                    per-element result records (checkpoint)
    data/failures.json                   elements that could not be resolved
    data/aflow_lib1_candidates.json      cached AFLUX LIB1 rows (probe)
    lattice.csv                          all bulk lattices
    metals_summary.csv                   all bulk + surface fields
    data/run_report.csv                  ok/failed + reason per element

The script is resumable: an element is skipped when its record exists, its
files are on disk and ``--force`` is not given.  Re-run it to rebuild only the
missing/failed elements.

Usage::

    python usecases/u3_metals/scripts/export_metals.py            # all 87
    python usecases/u3_metals/scripts/export_metals.py --elements Fe,Cu,Mg
    python usecases/u3_metals/scripts/export_metals.py --force --elements Fe
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import traceback
from pathlib import Path

import numpy as np
from pymatgen.core import Element, Structure

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import groundstates as gs  # noqa: E402
import surface_planes as sp  # noqa: E402

from cifkit.export import write_structure  # noqa: E402
from cifkit.geom import make_slab  # noqa: E402
from cifkit.validate import validate_structure  # noqa: E402

OUT_ROOT = Path(__file__).resolve().parents[1]
DATA = OUT_ROOT / "data"
ELEMENTS_DIR = OUT_ROOT / "elements"
RECORDS = DATA / "records.json"
FAILURES = DATA / "failures.json"
CANDIDATES = DATA / "aflow_lib1_candidates.json"

SLAB_THICKNESS = 12.0  # A (>= 3-5 atomic layers for every metal here)
VACUUM = 15.0  # A
VASP_ENCUT = 400.0


def retarget(outdir) -> None:
    """Write elements/, data/ and the tables under ``<outdir>`` instead of the use case dir."""
    global OUT_ROOT, DATA, ELEMENTS_DIR, RECORDS, FAILURES, CANDIDATES
    out = Path(outdir).expanduser().resolve()
    OUT_ROOT = out
    DATA = out / "data"
    ELEMENTS_DIR = out / "elements"
    RECORDS = DATA / "records.json"
    FAILURES = DATA / "failures.json"
    CANDIDATES = DATA / "aflow_lib1_candidates.json"

#: elements that must get the textbook plane (verification set)
CRITICAL = {
    "Fe": (1, 1, 0),
    "Cu": (1, 1, 1),
    "Mg": (0, 0, 1),
    "Al": (1, 1, 1),
    "W": (1, 1, 0),
    "Ti": (0, 0, 1),
    "Nb": (1, 1, 0),
}


def metals() -> list[str]:
    return [e.symbol for e in Element if e.is_metal]


def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default
    return default


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
def layer_profile(slab: Structure, layer_spacing: float | None = None, tol: float = 0.4) -> dict:
    """Atomic layers along the slab normal (c axis after reorient_lattice).

    ``layer_spacing`` is the bulk interlayer distance along the normal,
    ``d_hkl / n_sublayers`` (a two-atom-basis plane family such as hcp (0001)
    has two layers per ``d_hkl``).  The number of layer *centers* in the slab is
    then ``round(thickness / layer_spacing) + 1``, and the heights are split at
    the largest gaps.  This stays meaningful for strongly corrugated planes
    (alpha-Mn, alpha-Pu), where a fixed 0.4 脜 gap threshold would collapse every
    atom into a single "layer".
    """
    normal = np.asarray(slab.lattice.matrix[2], dtype=float)
    normal = normal / np.linalg.norm(normal)
    heights = np.sort(np.asarray(slab.cart_coords, dtype=float) @ normal)
    thickness = float(heights[-1] - heights[0])

    n_layers = 0
    if layer_spacing and layer_spacing > 0:
        n_layers = int(round(thickness / layer_spacing)) + 1
    if n_layers >= 2 and len(heights) > n_layers:
        gaps = np.diff(heights)
        cut_idx = np.sort(np.argsort(gaps)[-(n_layers - 1):])
        bounds = [0] + (cut_idx + 1).tolist() + [len(heights)]
        counts = [bounds[i + 1] - bounds[i] for i in range(len(bounds) - 1)]
        centers = [
            float(np.mean(heights[bounds[i]:bounds[i + 1]])) for i in range(len(bounds) - 1)
        ]
        method = "interplanar_spacing"
    else:
        groups = [[heights[0]]]
        for h in heights[1:]:
            if h - groups[-1][-1] > tol:
                groups.append([h])
            else:
                groups[-1].append(h)
        counts = [len(g) for g in groups]
        centers = [float(np.mean(g)) for g in groups]
        method = "gap_threshold"
    spacings = [round(float(b - a), 3) for a, b in zip(centers, centers[1:])]
    return {
        "n_atomic_layers": len(counts),
        "atoms_per_layer": counts,
        "interlayer_spacings": spacings,
        "slab_thickness_from_layers": (
            round(float(centers[-1] - centers[0]), 3) if len(centers) > 1 else 0.0
        ),
        "layer_detection": method,
    }


def nearest_neighbor_distance(struct: Structure) -> float:
    """Shortest interatomic distance including periodic images."""
    return sp.periodic_min_distance(struct)


def kpoints_mesh(struct: Structure, target_length: float = 30.0) -> tuple[int, int, int]:
    """moderately conservative Gamma-centred mesh: ~30 A per k-point direction."""
    abc = [float(x) for x in struct.lattice.abc]
    n = [max(1, int(round(target_length / max(a, 1e-6)))) for a in abc[:2]]
    return n[0], n[1], 1  # kz = 1 for a slab


INCAR_TEMPLATE = """\
# ============================================================================
#  Static (single-point) calculation for the {el} ({plane}) surface energy
#  Workflow (both steps MUST use the same POTCAR / ENCUT / smearing):
#    1) bulk:  VASP run on bulk_POSCAR  -> E_bulk_cell  [eV]
#              mu = E_bulk_cell / {natoms}    (energy per atom, {natoms} atoms)
#    2) slab:  VASP run on slab_POSCAR  -> E_slab      [eV]
#              E_surf = (E_slab - N_slab * mu) / (2 * A)
#              N_slab = {slab_atoms} atoms, A = {area:.2f} A^2
#  Both slab surfaces are equivalent by construction (symmetric slab), hence 2A.
# ============================================================================
SYSTEM = {el}_slab_{plane}
PREC = Accurate
ENCUT = {encut}          # must be the same in the bulk reference run
EDIFF = 1E-6             # tight: surface energies are energy differences
ISMEAR = 1               # Methfessel-Paxton (metal)
SIGMA = 0.1
ALGO = Fast
LREAL = Auto
ISPIN = 2
LWAVE = .FALSE.
LCHARG = .FALSE.
# --- static: no ionic relaxation here -------------------------------------
NSW = 0
IBRION = -1
ISIF = 2
# To relax the slab instead, replace the three lines above with:
#   NSW = 200
#   IBRION = 2
#   ISIF = 2
# and freeze the bottom layers in slab_POSCAR (Selective dynamics: F F F).
# Keep at least the two bottom layers frozen; relax the rest.
"""

KPOINTS_TEMPLATE = """\
Automatic generation
0
Gamma
  {k1}  {k2}  1
  0.0  0.0  0.0
# {el} {plane} slab: kz = 1 (slab), in-plane ~30 A per k-point (moderately
# conservative; converge E_surf w.r.t. the mesh before publishing). For the
# bulk reference use an equivalent 3D mesh, e.g. {k1} {k2} {k3}.
"""


def _write_inputs(el: str, plane: str, natoms: int, slab_atoms: int, area: float,
                  struct: Structure, out: Path) -> None:
    (out / "INCAR").write_text(
        INCAR_TEMPLATE.format(
            el=el, plane=plane, natoms=natoms, slab_atoms=slab_atoms, area=area, encut=VASP_ENCUT
        ),
        encoding="utf-8",
    )
    k1, k2, k3 = kpoints_mesh(struct)
    (out / "KPOINTS").write_text(
        KPOINTS_TEMPLATE.format(el=el, plane=plane, k1=k1, k2=k2, k3=k3), encoding="utf-8"
    )


def is_hexagonal(struct: Structure, tol: float = 1e-3) -> bool:
    """True for a hexagonal/trigonal cell in the hexagonal setting (a=b, gamma=120)."""
    a, b, _c = struct.lattice.abc
    return abs(a - b) < tol * max(a, 1.0) and abs(struct.lattice.angles[2] - 120.0) < 0.5


def plane_label(hkl, struct: Structure | None = None) -> str:
    """Miller label; hexagonal cells get the 4-index Miller-Bravais form.

    A c-axis plane ``(0,0,1)`` of an hcp crystal is written ``(0001)`` and
    ``(1,0,-2)`` becomes ``(10-12)``.
    """
    h, k, l = (int(v) for v in hkl)
    if struct is not None and is_hexagonal(struct):
        i = -(h + k)
        return f"({h}{k}{i}{l})"
    return f"({h}{k}{l})"


# ---------------------------------------------------------------------------
def export_one(el: str, records: dict, failures: dict, *, force: bool = False) -> dict:
    out = ELEMENTS_DIR / el
    required = ["bulk.cif", "bulk_POSCAR", "slab.cif", "slab_POSCAR", "lattice.csv", "INCAR", "KPOINTS"]
    if not force and el in records and all((out / f).exists() for f in required):
        rec = dict(records[el])
        rec["status"] = "ok_cached"
        return rec

    t0 = time.time()
    cands = load_json(CANDIDATES, {}).get(el) or []
    res = gs.resolve(el, cands)
    struct: Structure = res["structure"]
    out.mkdir(parents=True, exist_ok=True)

    # ---- bulk files ------------------------------------------------------
    write_structure(struct, out / "bulk.cif", "cif", title=f"{el} conventional cell")
    write_structure(
        struct, out / "bulk_POSCAR", "vasp", title=f"{el} conventional cell ({res['structure_type']})"
    )

    # ---- bulk lattice metrics -------------------------------------------
    abc = [round(float(x), 5) for x in struct.lattice.abc]
    angles = [round(float(x), 4) for x in struct.lattice.angles]
    natoms = len(struct)
    vol_per_atom = round(float(struct.volume) / natoms, 4)
    nn_bulk = round(nearest_neighbor_distance(struct), 4)

    # ---- densest plane + slab -------------------------------------------
    pick = sp.choose_densest_plane(struct, res["sg_check"], res["natoms_conventional"])
    hkl = tuple(int(v) for v in pick["hkl"])
    d_hkl = float(
        2.0
        * math.pi
        / np.linalg.norm(np.asarray(hkl, dtype=int) @ struct.lattice.reciprocal_lattice.matrix)
    )
    slab, info = make_slab(struct, hkl, slab_thickness=SLAB_THICKNESS, vacuum=VACUUM)
    vacuum_measured = float(info["vacuum_measured"])
    if vacuum_measured + 1e-6 < VACUUM:
        raise RuntimeError(
            f"slab vacuum {vacuum_measured:.2f} A < required {VACUUM:.1f} A"
        )
    if float(info["slab_thickness"]) < 8.0:
        raise RuntimeError(
            f"slab too thin: {info['slab_thickness']:.2f} A (target {SLAB_THICKNESS} A)"
        )
    area = float(info["surface_area"])
    write_structure(
        slab, out / "slab_POSCAR", "vasp", title=f"{el} {plane_label(hkl, struct)} slab, {VACUUM:.0f} A vacuum"
    )
    write_structure(slab, out / "slab.cif", "cif", title=f"{el} {plane_label(hkl, struct)} slab")

    layer_spacing = d_hkl / max(1, int(pick.get("n_layers_distinct") or 1))
    layers = layer_profile(slab, layer_spacing=layer_spacing)
    surface_atoms = int(info["chosen"]["surface_atoms"])
    report = validate_structure(slab)  # vacuum is reported; spec enforces it when given
    vac_from_validate = report.metrics.get("vacuum_measured")
    if not report.ok:
        failing = [c.to_dict() if hasattr(c, "to_dict") else str(c) for c in report.checks if not c.ok and getattr(c, "severity", "") == "error"]
        raise RuntimeError(f"validate_structure failed on slab: {failing}")

    # ---- per-element tables ---------------------------------------------
    row = {
        "element": el,
        "Z": natoms,
        "prototype": res["pearson"],
        "spacegroup_number": res["sg_check"],
        "spacegroup_symbol": res["sg_symbol"],
        "a": abc[0],
        "b": abc[1],
        "c": abc[2],
        "alpha": angles[0],
        "beta": angles[1],
        "gamma": angles[2],
        "V_per_atom": vol_per_atom,
        "source_aurl": res.get("source_aurl") or "",
        "source_energy_atom": res.get("source_energy_atom"),
        "natoms": natoms,
        "structure_type": res["structure_type"],
        "lattice_source": res["lattice_source"],
        "structure_confidence": res["structure_confidence"],
        "sg_check": res["sg_check"],
        "pearson_primitive": res.get("pearson_primitive"),
    }
    import csv as _csv

    with (out / "lattice.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = _csv.DictWriter(fh, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)

    _write_inputs(el, plane_label(hkl, struct), natoms, len(slab), area, slab, out)

    rec = dict(row)
    rec.update(
        {
            "status": "ok",
            "densest_plane": plane_label(hkl, struct),
            "plane_hkl": list(hkl),
            "plane_method": pick["method"],
            "plane_confidence": pick.get("plane_confidence", ""),
            "plane_rule": pick["rule"],
            "plane_rho": round(float(pick["rho"]), 6),
            "plane_n_layers_distinct": pick.get("n_layers_distinct"),
            "interplanar_d": round(d_hkl, 4),
            "layer_spacing": round(layer_spacing, 4),
            "surface_atoms": surface_atoms,
            "slab_atoms": len(slab),
            "slab_thickness": round(float(info["slab_thickness"]), 3),
            "vacuum_measured": round(vacuum_measured, 3),
            "vacuum_from_validate": round(float(vac_from_validate), 3) if vac_from_validate else None,
            "surface_area": round(area, 3),
            "n_atomic_layers": layers["n_atomic_layers"],
            "atoms_per_layer": "/".join(str(c) for c in layers["atoms_per_layer"]),
            "interlayer_spacing": "/".join(f"{s:.3f}" for s in layers["interlayer_spacings"]),
            "layer_detection": layers["layer_detection"],
            "near_neighbor_bulk": nn_bulk,
            "validate_ok": bool(report.ok),
            "validate_min_distance": report.metrics.get("min_distance"),
            "validate_duplicate_pairs": report.metrics.get("duplicate_pairs"),
            "structure_notes": res.get("notes", ""),
            "aflow_meta": res.get("aflow_meta") or {},
            "elapsed_s": round(time.time() - t0, 2),
        }
    )
    if el in CRITICAL and tuple(hkl) != CRITICAL[el]:
        rec["status"] = "plane_mismatch"
        rec["reason"] = f"expected {CRITICAL[el]} got {hkl}"
    return rec


# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--elements", default="", help="comma separated subset (default: all 87)")
    ap.add_argument("--force", action="store_true", help="recompute even if a record exists")
    ap.add_argument("--limit", type=int, default=0, help="only the first N elements")
    ap.add_argument("--list", action="store_true", help="print the element list and exit")
    ap.add_argument("--outdir", type=Path, default=None,
                    help="output root (default: usecases/u3_metals)")
    args = ap.parse_args(argv)
    if args.outdir:
        retarget(args.outdir)

    els = metals()
    if args.elements:
        wanted = [e.strip() for e in args.elements.split(",") if e.strip()]
        unknown = [e for e in wanted if e not in els]
        if unknown:
            print(f"not metallic / unknown elements: {unknown}", file=sys.stderr)
            return 2
        els = wanted
    if args.limit:
        els = els[: args.limit]
    if args.list:
        print(",".join(els))
        return 0

    records = load_json(RECORDS, {})
    failures = load_json(FAILURES, {})
    print(f"exporting {len(els)} element(s) -> {OUT_ROOT}")
    for i, el in enumerate(els, 1):
        t = time.time()
        try:
            rec = export_one(el, records, failures, force=args.force)
            records[el] = rec
            failures.pop(el, None)
            print(
                f"[{i:2d}/{len(els)}] {el:3s} {rec['status']:14s} "
                f"sg={rec.get('sg_check')} {rec.get('densest_plane')} "
                f"slab={rec.get('slab_atoms')} atoms vac={rec.get('vacuum_measured')} "
                f"({time.time() - t:.1f}s)"
            )
        except Exception as exc:  # noqa: BLE001 - one failing element must not stop the run
            reason = f"{type(exc).__name__}: {exc}"
            failures[el] = {"element": el, "reason": reason, "elapsed_s": round(time.time() - t, 2)}
            records.pop(el, None)
            print(f"[{i:2d}/{len(els)}] {el:3s} FAILED {reason[:160]}")
            if args.elements and len(els) == 1:  # single-element debug: show the traceback
                traceback.print_exc()
        save_json(RECORDS, records)
        save_json(FAILURES, failures)
    print(f"\nok={len(records)} failed={len(FAILURES and load_json(FAILURES, {}))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



