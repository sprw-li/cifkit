#!/usr/bin/env python
"""Download the AFLOW LIB2 Fe-C binary formation enthalpies used by this kit.

Netzwork step. Produces ``data/aflow_fe_c_energies.csv`` (one row per AFLOW
LIB2 entry).  Run once; afterwards ``build_hull.py`` works fully offline.

Usage (from the repository root, Windows):

    .venv\\Scripts\\python.exe usecases\\u4_fec\\scripts\\fetch_aflow_data.py

The query is ``species(Fe,C),nspecies(2),catalog(LIB2),enthalpy_formation_atom,prototype``
(289 rows at the time of packaging).  Rows whose ``enthalpy_formation_atom`` is
null are kept but flagged; ``build_hull.py`` drops them.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
REPO = KIT.parents[1]
sys.path.insert(0, str(REPO / "usecases" / "_common"))

from aflow_db import aflux, save_table_csv  # noqa: E402

QUERY = "species(Fe,C),nspecies(2),catalog(LIB2),enthalpy_formation_atom,prototype"
OUT = KIT / "data" / "aflow_fe_c_energies.csv"

_TOKEN = re.compile(r"([A-Z][a-z]?)(\d*)")


def parse_formula(formula: str) -> dict[str, int]:
    """``C4Fe12`` -> ``{'C': 4, 'Fe': 12}`` (AFLOW ``compound`` field)."""
    counts: dict[str, int] = {}
    for el, num in _TOKEN.findall(formula or ""):
        if not el:
            continue
        counts[el] = counts.get(el, 0) + (int(num) if num else 1)
    return counts


def build_rows(raw: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for r in raw:
        counts = parse_formula(str(r.get("compound", "")))
        n_fe = counts.get("Fe", 0)
        n_c = counts.get("C", 0)
        natoms = n_fe + n_c
        if natoms == 0 or set(counts) - {"Fe", "C"}:
            # not a clean binary Fe-C formula -> skip (AFLOW compound may be an
            # ICSD-style id for entries without a reduced formula)
            continue
        h = r.get("enthalpy_formation_atom")
        try:
            h_val = float(h) if h is not None else None
        except (TypeError, ValueError):
            h_val = None
        rows.append({
            "compound": r.get("compound"),
            "auid": r.get("auid"),
            "aurl": r.get("aurl"),
            "catalog": r.get("catalog", "LIB2"),
            "spacegroup_relax": r.get("spacegroup_relax"),
            "pearson_symbol_relax": r.get("Pearson_symbol_relax"),
            "prototype": r.get("prototype"),
            "enthalpy_formation_atom": h_val,
            "n_Fe": n_fe,
            "n_C": n_c,
            "natoms": natoms,
            "x_C": round(n_c / natoms, 6),
            "at_percent_C": round(100.0 * n_c / natoms, 4),
        })
    rows.sort(key=lambda d: (d["x_C"], d["enthalpy_formation_atom"] is None,
                             d["enthalpy_formation_atom"] or 0.0))
    return rows


def main() -> int:
    print(f"AFLUX query: {QUERY}")
    raw = aflux(QUERY, paging=(0, 400))
    print(f"  raw rows returned: {len(raw)}")
    rows = build_rows(raw)
    n_null = sum(1 for r in rows if r["enthalpy_formation_atom"] is None)
    save_table_csv(rows, OUT)
    print(f"  rows written     : {len(rows)}  ({n_null} without formation enthalpy)")
    print(f"  compositions     : {len({r['x_C'] for r in rows})} distinct at%C values")
    print(f"  -> {OUT}")

    # sanity: cementite stoichiometry C4Fe12 = Fe3C = 25 at% C
    fe3c = [r for r in rows if r["compound"] == "C4Fe12" and r["enthalpy_formation_atom"] is not None]
    fe3c.sort(key=lambda r: r["enthalpy_formation_atom"])
    if fe3c:
        print(f"  sanity Fe3C (C4Fe12) lowest enthalpy_formation_atom = "
              f"{fe3c[0]['enthalpy_formation_atom']:+.4f} eV/atom "
              f"({fe3c[0]['spacegroup_relax']}/{fe3c[0]['pearson_symbol_relax']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
