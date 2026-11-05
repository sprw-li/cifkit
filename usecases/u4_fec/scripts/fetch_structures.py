#!/usr/bin/env python
"""Download + verify the Fe-C structures shipped with this kit (network step).

For every candidate entry (AFLOW LIB2 for DFT entries, AFLOW ICSD_WEB for
experimental entries) this script:

1. downloads the CIF through ``usecases/_common/aflow_db.fetch_structure``
   (cifkit AFLOW adapter, cached under ``_cache/aflow/`` at repo root);
2. re-derives the symmetry with **spglib** (symprec=0.01) and compares it with
   pymatgen's ``SpacegroupAnalyzer`` (used to build the conventional cell);
3. writes ``structures/<name>.cif`` (verbatim AFLOW CIF, source-faithful) and
   ``structures/<name>.POSCAR`` (conventional standard cell, pymatgen SGA);
4. records sha256 of both files + source URL + AFLOW formation enthalpy in
   ``data/fe_c_compounds.csv``.

Usage (repository root):
    .venv\\Scripts\\python.exe usecases\\u4_fec\\scripts\\fetch_structures.py
"""
from __future__ import annotations

import csv
import hashlib
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
REPO = KIT.parents[1]
sys.path.insert(0, str(REPO / "usecases" / "_common"))

import spglib  # noqa: E402
from pymatgen.core import Structure  # noqa: E402
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer  # noqa: E402

from aflow_db import fetch_structure, save_table_csv  # noqa: E402
from cifkit.export import write_structure  # noqa: E402

STRUCT_DIR = KIT / "structures"
OUT_CSV = KIT / "data" / "fe_c_compounds.csv"

CANDIDATES = [
    dict(
        name="fe3c_cementite",
        formula="Fe3C",
        aurl="aflowlib.duke.edu:AFLOWDATA/LIB2_WEB/CFe_pv/180",
        source="AFLOW LIB2 (DFT, PBE)",
        note="渗碳体 cementite；AFLOW prototype 180（oP16, Pnma），"
             "AFLOW 形成焓 +0.0456 eV/atom（LIB2 中 25 at%C 处最低值，仍是亚稳相）",
    ),
    dict(
        name="fe5c2_hagg",
        formula="Fe5C2",
        aurl="aflowlib.duke.edu:AFLOWDATA/ICSD_WEB/MCLC/C2Fe5_ICSD_43194",
        source="AFLOW ICSD_WEB (experimental, ICSD 43194)",
        note="Hägg 碳化物 χ-Fe5C2（单斜 C2/c）；ICSD 实验结构，AFLOW 未给形成焓（不进 hull）",
    ),
    dict(
        name="fe7c3_hex",
        formula="Fe7C3",
        aurl="aflowlib.duke.edu:AFLOWDATA/ICSD_WEB/HEX/C3Fe7_ICSD_167345",
        source="AFLOW ICSD_WEB (experimental, ICSD 167345)",
        note="六方 Fe7C3（P6_3mc, hP20）；ICSD 实验结构，AFLOW 未给形成焓（不进 hull）",
    ),
    dict(
        name="fe2c_ortho",
        formula="Fe2C",
        aurl="aflowlib.duke.edu:AFLOWDATA/ICSD_WEB/ORC/C1Fe2_ICSD_162104",
        source="AFLOW ICSD_WEB (experimental, ICSD 162104)",
        note="正交 Fe2C（Pnnm, oP6）；ICSD 实验结构，AFLOW 未给形成焓（不进 hull）",
        dft_counterpart="AFLOW LIB2 C2Fe4 prototype 257（同型，Pnnm oP6），"
                        "E_form=+0.0516 eV/atom；StructureMatcher 与 ICSD 162104 匹配（rms 0.009）",
    ),
    dict(
        name="fe2c_hex",
        formula="Fe2C",
        aurl="aflowlib.duke.edu:AFLOWDATA/ICSD_WEB/HEX/C1Fe2_ICSD_162103",
        source="AFLOW ICSD_WEB (experimental, ICSD 162103)",
        note="六方 Fe2C（P6/mmm, hP3）；ICSD 实验结构，AFLOW 未给形成焓（不进 hull）",
    ),
    dict(
        name="fec_wc_type",
        formula="FeC",
        aurl="aflowlib.duke.edu:AFLOWDATA/LIB2_WEB/CFe_pv/116",
        source="AFLOW LIB2 (DFT, PBE)",
        note="FeC 的 WC 型结构（P-6m2, hP2）——AFLOW 构造的 DFT 原型，非实验相；"
             "LIB2 中 50 at%C 处最低焓（+0.396 eV/atom）",
    ),
    dict(
        name="fe23c6",
        formula="Fe23C6",
        aurl="aflowlib.duke.edu:AFLOWDATA/ICSD_WEB/FCC/C6Fe23_ICSD_168294",
        source="AFLOW ICSD_WEB (experimental, ICSD 168294)",
        note="Cr23C6 型碳化物 Fe23C6（Fm-3m, cF116）；ICSD 实验结构，AFLOW 未给形成焓（不进 hull）",
    ),
]

_CRYSTAL = [
    (1, 2, "a"), (3, 15, "m"), (16, 74, "o"), (75, 142, "t"),
    (143, 167, "h"), (168, 194, "h"), (195, 230, "c"),
]
_CENTER = {
    "m": {"P": "P", "C": "S", "A": "S", "I": "S", "F": "S"},
    "o": {"P": "P", "C": "S", "A": "S", "I": "I", "F": "F"},
    "t": {"P": "P", "I": "I"},
    "h": {"P": "P", "R": "R"},
    "c": {"P": "P", "I": "I", "F": "F"},
}


def pearson_symbol(sg_num: int, hall_symbol: str, natoms_conv: int) -> str:
    """Pearson symbol from SG number + centering letter + conventional atom count."""
    letter = next(c for lo, hi, c in _CRYSTAL if lo <= sg_num <= hi)
    centering = hall_symbol[0] if hall_symbol else "P"
    # rhombohedral SGs (143-167) with R centering -> hR
    if 143 <= sg_num <= 167:
        letter = "h"
    cent = _CENTER.get(letter, {}).get(centering, centering)
    return f"{letter}{cent}{natoms_conv}"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    STRUCT_DIR.mkdir(parents=True, exist_ok=True)

    # formation enthalpies + prototypes from the LIB2 export
    energies: dict[str, tuple[float, str, str]] = {}
    energies_csv = KIT / "data" / "aflow_fe_c_energies.csv"
    if energies_csv.exists():
        with energies_csv.open(encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                if row.get("enthalpy_formation_atom"):
                    energies[row["aurl"]] = (
                        float(row["enthalpy_formation_atom"]),
                        row.get("compound", ""),
                        row.get("prototype", ""),
                    )

    rows, failures = [], []
    for cand in CANDIDATES:
        name = cand["name"]
        print(f"[{name}] {cand['aurl']}")
        try:
            structure, prov, _rec = fetch_structure(cand["aurl"])
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"   FAILED: {type(exc).__name__}: {exc}")
            failures.append((name, str(exc)))
            continue

        dataset = spglib.get_symmetry_dataset(
            (structure.lattice.matrix, structure.frac_coords,
             [site.specie.Z for site in structure]),
            symprec=0.01,
        )
        sg_num = int(dataset.number)
        sg_sym = str(dataset.international)
        wyckoff_groups = len(set(dataset.equivalent_atoms.tolist()))

        sga = SpacegroupAnalyzer(structure, symprec=0.01)
        conv = sga.get_conventional_standard_structure()
        prim = sga.get_primitive_standard_structure()
        if sga.get_space_group_number() != sg_num:
            print(f"   WARNING pymatgen/spglib SG mismatch: "
                  f"{sga.get_space_group_number()} vs {sg_num}")

        cif_dst = STRUCT_DIR / f"{name}.cif"
        shutil.copyfile(Path(str(prov.get("cif_path"))), cif_dst)

        poscar_dst = STRUCT_DIR / f"{name}.POSCAR"
        write_structure(
            conv, poscar_dst, "vasp",
            title=f"{name} {conv.composition.reduced_formula} SG{sg_num} "
                  f"conventional cell (pymatgen SGA, symprec=0.01)",
        )

        formula = conv.composition.reduced_formula
        natoms = conv.num_sites
        n_c = sum(1 for s in conv if s.specie.symbol == "C")
        if formula != cand["formula"]:
            print(f"   WARNING composition mismatch: {formula} != {cand['formula']}")
        energy = energies.get(cand["aurl"])
        pe = pearson_symbol(sg_num, sg_sym, natoms)
        # the saved POSCAR must round-trip
        rt = Structure.from_file(poscar_dst)
        assert rt.num_sites == natoms and rt.composition.reduced_formula == formula

        rows.append({
            "name": name,
            "formula": formula,
            "at_percent_C": round(100.0 * n_c / natoms, 4),
            "x_C": round(n_c / natoms, 6),
            "spacegroup_number": sg_num,
            "spacegroup_symbol": sg_sym,
            "pearson_symbol": pe,
            "prototype": "" if energy is None else energy[2],
            "natoms_conventional": natoms,
            "natoms_primitive": prim.num_sites,
            "wyckoff_groups": wyckoff_groups,
            "source_kind": cand["source"],
            "aurl": cand["aurl"],
            "cif_url": prov.get("url"),
            "aflow_cif_sha256": prov.get("cif_sha256"),
            "file_sha256_cif": sha256_file(cif_dst),
            "file_sha256_poscar": sha256_file(poscar_dst),
            "aflow_enthalpy_formation_eV_atom": "" if energy is None else f"{energy[0]:.9f}",
            "dft_counterpart": cand.get("dft_counterpart", ""),
            "note": cand["note"],
        })
        print(f"   {formula:8s} conv/prim natoms={natoms}/{prim.num_sites}  "
              f"SG {sg_num} {sg_sym}  {pe}  wyckoff_groups={wyckoff_groups}  "
              f"E_form={'n/a' if energy is None else f'{energy[0]:+.4f}'}")

    save_table_csv(rows, OUT_CSV)
    print(f"\nwrote {OUT_CSV}  ({len(rows)} structures in {STRUCT_DIR})")
    if failures:
        print("FAILURES:", failures)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
