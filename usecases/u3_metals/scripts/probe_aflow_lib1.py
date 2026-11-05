"""Probe AFLOW LIB1 for pure-element entries of all 87 metals (cached JSON).

Writes ``data/aflow_lib1_candidates.json`` so the resolver can pick entries
without re-querying AFLUX.  Read-only w.r.t. everything outside u3_metals.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from pymatgen.core import Element  # noqa: E402

from usecases._common import aflow_db as db  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "aflow_lib1_candidates.json"
FIELDS = "spacegroup_relax,Pearson_symbol_relax,energy_atom,prototype,nspecies,natoms,compound"


def main() -> int:
    els = [e.symbol for e in Element if e.is_metal]
    prev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    for i, el in enumerate(els, 1):
        if el in prev:
            print(f"[{i:2d}/87] {el:3s} cached ({len(prev[el])} rows)")
            continue
        t = time.time()
        try:
            rows = db.aflux(
                f"species({el}),nspecies(1),catalog(LIB1),{FIELDS}", paging=(0, 60)
            )
        except Exception as exc:  # noqa: BLE001 - record and continue
            print(f"[{i:2d}/87] {el:3s} FAIL {type(exc).__name__}: {exc}")
            prev[el] = [{"_error": f"{type(exc).__name__}: {exc}"}]
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
            continue
        keep = []
        for r in rows:
            try:
                e = float(r.get("energy_atom"))
            except (TypeError, ValueError):
                continue
            keep.append(
                {
                    "aurl": r.get("aurl"),
                    "spacegroup_relax": r.get("spacegroup_relax"),
                    "pearson": r.get("Pearson_symbol_relax"),
                    "prototype": r.get("prototype"),
                    "energy_atom": e,
                    "natoms": r.get("natoms"),
                    "compound": r.get("compound"),
                }
            )
        keep.sort(key=lambda d: d["energy_atom"])
        prev[el] = keep
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
        sgs = sorted({str(k["spacegroup_relax"]) for k in keep})
        print(f"[{i:2d}/87] {el:3s} {len(keep):2d} rows sg={sgs[:8]} ({time.time() - t:.1f}s)")
    print(f"\nwrote {OUT} ({len(prev)} elements)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
