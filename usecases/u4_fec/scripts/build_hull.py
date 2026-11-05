#!/usr/bin/env python
"""Build the 0 K convex hull of the Fe-C system from AFLOW LIB2 formation
enthalpies, and write ``data/hull_points.csv`` (+ the figure).

Fully offline: only reads ``data/aflow_fe_c_energies.csv`` (exported by
``fetch_aflow_data.py``) and, optionally, a user-supplied energies CSV that
overrides / extends it (e.g. your own VASP results).

Energy definition
-----------------
``enthalpy_formation_atom`` from AFLOW is already the formation enthalpy in
eV/atom relative to the elemental reference states:

    E_form(Fe_x C_y) = [E_tot(Fe_x C_y) - x*E(Fe_ref) - y*E(C_ref)] / (x + y)

so the pure-element endpoints sit at exactly 0 eV/atom by construction.
The 0 K hull of a binary system with both endpoints at 0 is the lower convex
envelope E_hull(x_C); for any composition, ``E_above_hull = E_form - E_hull``.

Usage (repository root, Windows)::

    .venv\\Scripts\\python.exe usecases\\u4_fec\\scripts\\build_hull.py
    # with your own energies (columns: x_C,energy_formation_eV_per_atom):
    .venv\\Scripts\\python.exe usecases\\u4_fec\\scripts\\build_hull.py \\
        --energies my_vasp_formation_energies.csv \\
        --out-png figures/my_hull.png
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent

E_TOL = 1e-6


def read_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def composition_minima(rows: list[dict]) -> dict[float, dict]:
    """Lowest formation enthalpy per composition (x_C) over all LIB2 entries."""
    best: dict[float, dict] = {}
    for row in rows:
        raw = row.get("enthalpy_formation_atom")
        if raw in (None, "", "None", "null", "nan"):
            continue  # ICSD entries have no AFLOW enthalpy -> cannot enter the hull
        energy = float(raw)
        x = round(float(row["x_C"]), 6)
        row = dict(row)
        row["_energy"] = energy
        row["_x"] = x
        if x not in best or energy < best[x]["_energy"]:
            best[x] = row
    return best


def lower_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Lower convex envelope of 2D points (monotone chain, O(n log n))."""
    pts = sorted(points)
    hull: list[tuple[float, float]] = []

    def cross(o, a, b) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    for p in pts:
        while len(hull) >= 2 and cross(hull[-2], hull[-1], p) <= 0:
            hull.pop()
        hull.append(p)
    return hull


def hull_energy(hull: list[tuple[float, float]], x: float) -> float:
    """Linear interpolation of the hull at composition ``x``."""
    if x <= hull[0][0]:
        return hull[0][1]
    if x >= hull[-1][0]:
        return hull[-1][1]
    for (x0, y0), (x1, y1) in zip(hull, hull[1:]):
        if x0 <= x <= x1:
            if abs(x1 - x0) < 1e-12:
                return min(y0, y1)
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    raise RuntimeError(f"x={x} outside hull")


def load_user_energies(path: Path) -> dict[float, float]:
    """User CSV: ``x_C`` (or ``at_percent_C``) + ``energy_formation_eV_per_atom``."""
    out: dict[float, float] = {}
    for row in read_rows(path):
        if row.get("x_C") not in (None, ""):
            x = float(row["x_C"])
        elif row.get("at_percent_C") not in (None, ""):
            x = float(row["at_percent_C"]) / 100.0
        else:
            continue
        energy = row.get("energy_formation_eV_per_atom")
        if energy in (None, ""):
            continue
        out[round(x, 6)] = float(energy)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--energies-csv", type=Path,
                    default=KIT / "data" / "aflow_fe_c_energies.csv",
                    help="AFLOW LIB2 export (default: data/aflow_fe_c_energies.csv)")
    ap.add_argument("--energies", type=Path, default=None,
                    help="optional user CSV (x_C,energy_formation_eV_per_atom) "
                         "that overrides / extends the AFLOW values")
    ap.add_argument("--out-csv", type=Path, default=KIT / "data" / "hull_points.csv")
    ap.add_argument("--out-png", type=Path, default=KIT / "figures" / "fe_c_hull.png")
    args = ap.parse_args(argv)

    rows = read_rows(args.energies_csv)
    n_raw = len(rows)
    n_with_h = sum(1 for r in rows if r.get("enthalpy_formation_atom") not in (None, ""))
    print(f"read {n_raw} AFLOW LIB2 rows ({n_with_h} with formation enthalpy) "
          f"from {args.energies_csv}")

    minima = composition_minima(rows)
    n_comp = len(minima)
    print(f"compositions with an enthalpy: {n_comp}")

    override: dict[float, float] = {}
    if args.energies:
        override = load_user_energies(args.energies)
        print(f"user energy override: {len(override)} compositions from {args.energies}")

    # endpoints: pure Fe (x=0) and pure C (x=1) at 0 eV/atom by definition.
    # a user override for x=0 / x=1 replaces the default 0 values.
    points: dict[float, float] = {0.0: 0.0, 1.0: 0.0}
    for x, row in minima.items():
        points[x] = row["_energy"]
    for x, energy in override.items():
        points[x] = energy

    hull = lower_hull(list(points.items()))
    print(f"lower hull vertices: {[(round(x, 4), round(y, 6)) for x, y in hull]}")

    # annotate every input composition
    out_rows = []
    for x in sorted(points):
        if x in override:
            source = f"user override ({args.energies.name})"
            best = None
        elif x in minima:
            best = minima[x]
            source = "AFLOW LIB2"
        else:
            best = None
            source = "element endpoint (AFLOW LIB2 reference state)"
        energy = points[x]
        e_hull = hull_energy(hull, x)
        above = energy - e_hull
        on_hull = abs(above) <= E_TOL
        if best is not None:
            out_rows.append({
                "x_C": f"{x:.6f}",
                "at_percent_C": f"{100.0 * x:.4f}",
                "compound": best.get("compound", ""),
                "aurl": best.get("aurl", ""),
                "spacegroup": best.get("spacegroup_relax", ""),
                "pearson_symbol": best.get("pearson_symbol_relax", ""),
                "prototype": best.get("prototype", ""),
                "energy_formation_eV_per_atom": f"{energy:.9f}",
                "hull_energy_eV_per_atom": f"{e_hull:.9f}",
                "energy_above_hull_eV_per_atom": f"{above:.9f}",
                "on_hull": "yes" if on_hull else "no",
                "status": ("stable (element)" if x in (0.0, 1.0) else "stable")
                          if on_hull else "metastable",
                "n_entries_at_composition": sum(
                    1 for r in rows
                    if r.get("enthalpy_formation_atom") not in (None, "")
                    and abs(float(r["x_C"]) - x) < 1e-6),
                "energy_source": source,
            })
        else:
            out_rows.append({
                "x_C": f"{x:.6f}",
                "at_percent_C": f"{100.0 * x:.4f}",
                "compound": "Fe" if x == 0.0 else ("C" if x == 1.0 else ""),
                "aurl": "",
                "spacegroup": "229" if x == 0.0 else ("194" if x == 1.0 else ""),
                "pearson_symbol": "cI2" if x == 0.0 else ("hP4" if x == 1.0 else ""),
                "prototype": "A2" if x == 0.0 else ("A9" if x == 1.0 else ""),
                "energy_formation_eV_per_atom": f"{energy:.9f}",
                "hull_energy_eV_per_atom": f"{e_hull:.9f}",
                "energy_above_hull_eV_per_atom": f"{above:.9f}",
                "on_hull": "yes" if on_hull else "no",
                "status": ("stable (element)" if x in (0.0, 1.0) else "stable")
                          if on_hull else "metastable",
                "n_entries_at_composition": 0,
                "energy_source": source,
            })

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(out_rows[0]))
        writer.writeheader()
        writer.writerows(out_rows)
    print(f"wrote {args.out_csv}  ({len(out_rows)} composition rows)")

    # ---- headline numbers -------------------------------------------------
    def lookup(x_query: float) -> dict | None:
        for row in out_rows:
            if abs(float(row["x_C"]) - x_query) < 1e-6:
                return row
        return None

    print("\nkey numbers (grid: 100 at%C = pure C, 0 at%C = pure Fe):")
    for label, x_query in [("Fe3C", 0.25), ("Fe2C", 1 / 3), ("FeC", 0.5),
                           ("Fe23C6", 6 / 29), ("Fe7C3", 0.30), ("Fe5C2", 2 / 7)]:
        row = lookup(x_query)
        if row is None:
            print(f"  {label:6s} x_C={x_query:.4f}: 无 AFLOW 形成焓，无法进入 0 K hull")
            continue
        print(f"  {label:6s} x_C={x_query:.4f} ({row['at_percent_C']} at%C): "
              f"E_form={float(row['energy_formation_eV_per_atom']):+.4f}  "
              f"E_above_hull={float(row['energy_above_hull_eV_per_atom']):+.4f} eV/atom  "
              f"[{row['compound']} {row['spacegroup']}/{row['pearson_symbol']}] "
              f"{row['status']}")

    # self-check: Fe3C value must equal the AFLOW export exactly
    fe3c = lookup(0.25)
    if fe3c is not None:
        best = minima[0.25]
        assert abs(float(fe3c["energy_formation_eV_per_atom"]) - best["_energy"]) < 1e-8
        print(f"\nself-check OK: Fe3C E_form={float(fe3c['energy_formation_eV_per_atom']):.6f} "
              f"== AFLOW C4Fe12 lowest enthalpy {best['_energy']:.6f} eV/atom")

    # ---- figure -----------------------------------------------------------
    sys.path.insert(0, str(HERE))
    from plot_hull import plot_hull

    plot_hull(rows, out_rows, args.out_png)
    print(f"wrote {args.out_png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
