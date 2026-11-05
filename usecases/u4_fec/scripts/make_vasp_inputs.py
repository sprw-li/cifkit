#!/usr/bin/env python
"""Generate the VASP input templates shipped in ``vasp_inputs/``.

For every structure in ``structures/*.POSCAR`` (plus two elemental reference
cells) this writes:

    vasp_inputs/<name>/POSCAR          copy of the structure (canonical copy lives
                                       in structures/, this one is for convenience)
    vasp_inputs/<name>/INCAR           relaxation (ISIF=3) template
    vasp_inputs/<name>/INCAR.static    single-point template (NSW=0, ISMEAR=-5)
    vasp_inputs/<name>/KPOINTS         k-mesh for the relaxation
    vasp_inputs/<name>/KPOINTS.static  denser k-mesh for the single point
    vasp_inputs/<name>/POTCAR.readme   which PAW potentials to concatenate + how
                                       to compute E_form from your own totals

No POTCAR is shipped (VASP licence).  Run from the repository root::

    .venv\\Scripts\\python.exe usecases\\u4_fec\\scripts\\make_vasp_inputs.py

All numbers (ENCUT, SIGMA, ...) are *starting suggestions* reviewed for
metallic Fe-C carbides, not converged settings for publication.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent

EN_CUT = 520
RELAX_KPPA = 1200
STATIC_KPPA = 4000
REL_TOL = 1e-6

INCAR_RELAX = """SYSTEM = {name}  ({formula}, SG {sg})
# ---- Fe-C carbide relaxation template (VASP 5/6, PAW PBE) -------------------
PREC   = Accurate
ENCUT  = {encut}
EDIFF  = 1E-6
EDIFFG = -0.02
NSW    = 200
IBRION = 2
ISIF   = 3
ISMEAR = 1
SIGMA  = 0.2
ISPIN  = 2
MAGMOM = {magmom}
LORBIT = 11
LWAVE  = .FALSE.
LCHARG = .FALSE.
# -----------------------------------------------------------------------------
# NOTE: MAGMOM above is only a starting guess (Fe ~2.2 muB, C ~0).
#       Fe-C carbides are ferromagnetic; keep ISPIN=2 also for the final static
#       run or the total energy is not comparable.
"""

INCAR_STATIC = """SYSTEM = {name}  ({formula}, SG {sg})  -- single point
# ---- static (single point) template, use the relaxed CONTCAR as POSCAR -------
PREC   = Accurate
ENCUT  = {encut}
EDIFF  = 1E-7
NSW    = 0
IBRION = -1
ISMEAR = -5
ISPIN  = 2
MAGMOM = {magmom}
LORBIT = 11
LWAVE  = .FALSE.
LCHARG = .FALSE.
# -----------------------------------------------------------------------------
# ISMEAR=-5 (tetrahedron with Bloechl corrections) is good for the final energy
# of metals PROVIDED the k-mesh is dense (see KPOINTS.static).
"""

POTCAR_README = """POTCAR for {name} = {formula}   (space group {sg}, {pearson})
=================================================================

Recommended PAW-PBE potentials (VASP 5.4 / VASP 6 distribution
"potpaw_PBE.54" or newer):

    Fe_pv   (Fe, 3p6 3d7 4s1, 14 valence electrons)   <-- preferred for Fe-C
    C       (C,  2s2 2p2,    4 valence electrons)

If Fe_pv is not available, Fe (8 valence electrons) is acceptable, but then
*all* structures and reference states must use the same Fe potential.

The POTCAR file is NOT shipped with this kit (VASP licence).  Build it so that
the element order matches the POSCAR species line:

    cat ~/potpaw_PBE/Fe_pv/POTCAR ~/potpaw_PBE/C/POTCAR > POTCAR

The POSCAR of this folder starts with the line:  {species_line}

--- how E_form is obtained from your own VASP totals ------------------------
E_form(Fe_x C_y) = [E_tot(Fe_x C_y) - x*E_Fe - y*E_C] / (x + y)     [eV/atom]

Use the SAME POTCAR / ENCUT / k-mesh family for the references:
    E_Fe : ferromagnetic bcc Fe   (vasp_inputs/ref_fe_bcc)
    E_C  : graphite               (vasp_inputs/ref_c_graphite)
AFLOW's elemental C reference is the diamond-like cF8 structure; if you want to
compare directly with the AFLOW numbers shipped in data/, also run
    vasp_inputs/ref_c_diamond.
Then write a CSV ``my_energies.csv`` with columns

    x_C,energy_formation_eV_per_atom,comment

and rebuild the hull with

    python scripts/build_hull.py --energies my_energies.csv --out-png figures/my_hull.png

--- sanity / known pitfalls ------------------------------------------------
* check the magnetic state: Fe-C carbides are ferromagnetic; a non-magnetic
  run can shift the energy by 0.1 eV/atom and more;
* use EDIFFG=-0.02 eV/A for relaxation, then a static run for the final energy;
* do not compare total energies computed with different ENCUT or POTCAR;
* PBE (AFLOW LIB2 uses PBE) is not the same functional as PBEsol/SCAN.
"""


def structure_info(poscar: Path) -> tuple[str, str, str, str]:
    from pymatgen.core import Structure
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    s = Structure.from_file(poscar)
    sga = SpacegroupAnalyzer(s, symprec=0.01)
    return (s.composition.reduced_formula,
            f"{sga.get_space_group_number()} ({sga.get_space_group_symbol()})",
            "", s)


def magmom(s) -> str:
    """MAGMOM string, e.g. ``12*2.2 4*0.0``."""
    counts: dict[str, int] = {}
    for site in s:
        el = site.specie.symbol
        counts[el] = counts.get(el, 0) + 1
    # order must match the POSCAR species order
    order: list[str] = []
    for site in s:
        if site.specie.symbol not in order:
            order.append(site.specie.symbol)
    parts = []
    for el in order:
        m = {"Fe": "2.2", "C": "0.0"}.get(el, "0.0")
        parts.append(f"{counts[el]}*{m}")
    return " ".join(parts)


def kpoints_text(s, kppa: float) -> str:
    from pymatgen.io.vasp.inputs import Kpoints

    k = Kpoints.automatic_density(s, kppa)
    grid = k.kpts[0]
    gamma = k.style.name == "Gamma"
    header = ("Gamma-centered mesh" if gamma else "Monkhorst-Pack mesh")
    return (f"{header} (generated by pymatgen automatic_density, kppa={kppa})\n"
            "0\n" + ("Gamma\n" if gamma else "Monkhorst-Pack\n") +
            f"{grid[0]} {grid[1]} {grid[2]}\n0 0 0\n")


def write_reference_cells(vasp_dir: Path) -> None:
    """bcc Fe (ferromagnetic) + graphite + diamond, conventional cells."""
    from pymatgen.core import Lattice, Structure

    refs = {
        "ref_fe_bcc": Structure(
            Lattice.cubic(2.870), ["Fe", "Fe"], [[0, 0, 0], [0.5, 0.5, 0.5]]
        ),
        "ref_c_graphite": Structure(
            Lattice.hexagonal(2.464, 6.711),
            ["C", "C", "C", "C"],
            [[0, 0, 0], [0, 0, 0.5], [1 / 3, 2 / 3, 0], [2 / 3, 1 / 3, 0.5]],
        ),
        "ref_c_diamond": Structure(
            Lattice.cubic(3.567),
            ["C"] * 8,
            [[0, 0, 0], [0, 0.5, 0.5], [0.5, 0, 0.5], [0.5, 0.5, 0],
             [0.25, 0.25, 0.25], [0.25, 0.75, 0.75], [0.75, 0.25, 0.75],
             [0.75, 0.75, 0.25]],
        ),
    }
    header = ("# reference cell generated locally from the standard prototype "
              "(a = experimental lattice constant, NOT a database entry); "
              "relax it with the same settings as the carbides before use.\n")
    for name, s in refs.items():
        d = vasp_dir / name
        d.mkdir(parents=True, exist_ok=True)
        from cifkit.export import write_structure
        write_structure(s, d / "POSCAR", "vasp",
                        title=f"{name} {s.composition.reduced_formula} reference")
        formula = s.composition.reduced_formula
        sg = "229 (Im-3m)" if name == "ref_fe_bcc" else (
            "194 (P6_3/mmc)" if name == "ref_c_graphite" else "227 (Fd-3m)")
        mom = magmom(s)
        (d / "INCAR").write_text(INCAR_RELAX.format(
            name=name, formula=formula, sg=sg, encut=EN_CUT, magmom=mom),
            encoding="utf-8")
        (d / "INCAR.static").write_text(INCAR_STATIC.format(
            name=name, formula=formula, sg=sg, encut=EN_CUT, magmom=mom),
            encoding="utf-8")
        (d / "KPOINTS").write_text(kpoints_text(s, RELAX_KPPA), encoding="utf-8")
        (d / "KPOINTS.static").write_text(kpoints_text(s, STATIC_KPPA),
                                          encoding="utf-8")
        pot = "Fe_pv" if "fe" in name else "C"
        (d / "POTCAR.readme").write_text(header + POTCAR_README.format(
            name=name, formula=formula, sg=sg, pearson="(reference cell)",
            species_line=" ".join(dict.fromkeys(str(site.specie) for site in s))),
            encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kit", type=Path, default=None,
                    help="kit 根目录（默认 usecases/u4_fec；给出时读写都指向它）")
    args = ap.parse_args(argv)
    kit = Path(args.kit).expanduser().resolve() if args.kit else KIT

    vasp_dir = kit / "vasp_inputs"
    struct_dir = kit / "structures"
    if vasp_dir.exists():
        shutil.rmtree(vasp_dir)
    vasp_dir.mkdir(parents=True)

    # names that exist in both structures/ and data/fe_c_compounds.csv
    import csv as _csv
    names = []
    with (kit / "data" / "fe_c_compounds.csv").open(encoding="utf-8-sig") as fh:
        for row in _csv.DictReader(fh):
            names.append((row["name"], row["formula"],
                          f"{row['spacegroup_number']} ({row['spacegroup_symbol']})",
                          row["pearson_symbol"]))

    for name, formula, sg, pearson in names:
        src = struct_dir / f"{name}.POSCAR"
        if not src.exists():
            print(f"WARNING missing {src}", file=sys.stderr)
            continue
        d = vasp_dir / name
        d.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, d / "POSCAR")
        _formula, _sg, _p, s = structure_info(src)
        species = " ".join(dict.fromkeys(str(site.specie) for site in s))
        (d / "INCAR").write_text(INCAR_RELAX.format(
            name=name, formula=formula, sg=sg, encut=EN_CUT, magmom=magmom(s)),
            encoding="utf-8")
        (d / "INCAR.static").write_text(INCAR_STATIC.format(
            name=name, formula=formula, sg=sg, encut=EN_CUT, magmom=magmom(s)),
            encoding="utf-8")
        (d / "KPOINTS").write_text(kpoints_text(s, RELAX_KPPA), encoding="utf-8")
        (d / "KPOINTS.static").write_text(kpoints_text(s, STATIC_KPPA), encoding="utf-8")
        (d / "POTCAR.readme").write_text(POTCAR_README.format(
            name=name, formula=formula, sg=sg, pearson=pearson,
            species_line=species), encoding="utf-8")
        print(f"wrote vasp_inputs/{name}/  ({formula}, {s.num_sites} atoms, "
              f"{species})")

    write_reference_cells(vasp_dir)
    print("wrote vasp_inputs/ref_fe_bcc, ref_c_graphite, ref_c_diamond")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
