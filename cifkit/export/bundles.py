"""Computation-software input bundles: structure + input template + notes.

``write_bundle(structure, code, outdir)`` writes everything needed to *start* a
calculation with a given code: the geometry in the code's native format, a
minimal input template, and a ``README.md`` listing what the user must supply
(pseudopotentials, basis sets, k-points, Slater-Koster files, ...).

Templates are explicitly marked: nothing here is a converged, runnable
calculation.  ``BUNDLE_INFO[code]["missing"]`` lists the files/parameters that
the user has to provide.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pymatgen.core import Structure

from cifkit.export.writers import _comment, _formula, element_symbol, write_structure

BUNDLE_INFO: dict[str, dict[str, Any]] = {
    "vasp": {
        "description": "VASP POSCAR + INCAR (relax/static) + KPOINTS + POTCAR notes",
        "missing": ["POTCAR (choose PAW potentials for your POTCAR version)"],
        "template": True,
    },
    "qe": {
        "description": "Quantum ESPRESSO pw.x input + k-point advice",
        "missing": ["*.UPF pseudopotentials", "converged cutoff/k-points"],
        "template": True,
    },
    "cp2k": {
        "description": "CP2K input skeleton (CELL/COORD/DFT)",
        "missing": ["BASIS_SET / POTENTIAL (or a global basis file)", "cutoff convergence"],
        "template": True,
    },
    "lammps": {
        "description": "LAMMPS data file + in.min (minimization) template",
        "missing": ["pair_style/force field", "masses if not in data file"],
        "template": True,
    },
    "gromacs": {
        "description": "GROMACS .gro coordinates + .mdp + topology notes",
        "missing": ["force-field .top/.itp", "box/charge equilibration"],
        "template": True,
    },
    "gaussian": {
        "description": "Gaussian .gjf (route + coordinates)",
        "missing": ["method/basis choice", "charge/multiplicity (defaults 0/1)"],
        "template": True,
    },
    "orca": {
        "description": "ORCA .inp + .xyz coordinates",
        "missing": ["method/basis", "charge/multiplicity (defaults 0/1)"],
        "template": True,
    },
    "abacus": {
        "description": "ABACUS STRU + notes",
        "missing": ["*.upf pseudopotentials", "*.orb numerical orbitals", "INPUT file (ecut/k-points)"],
        "template": True,
    },
    "dftb": {
        "description": "DFTB+ gen geometry + dftb_in.hsd template",
        "missing": ["Slater-Koster files (slakos/)", "charge/SCC convergence"],
        "template": True,
    },
    "siesta": {
        "description": "SIESTA .fdf template",
        "missing": ["*.psf pseudopotentials", "basis/PAO parameters", "k-points"],
        "template": True,
    },
    "nwchem": {
        "description": "NWChem .nw template",
        "missing": ["theory/basis block", "charge/multiplicity",
                    "periodic systems get the verified plane-wave pattern (nwpw + cutoff + "
                    "task pspw energy; NWChem finds its own libraryps pseudopotentials); "
                    "raise cutoff/xc for production"],
        "template": True,
    },
    "aims": {
        "description": "FHI-aims geometry.in",
        "missing": ["control.in (species defaults, k-grid, xc)"],
        "template": True,
    },
}


def supported_bundles() -> dict[str, str]:
    return {code: info["description"] for code, info in BUNDLE_INFO.items()}


def _README(path: Path, structure: Structure, code: str, files: list[str]) -> None:
    info = BUNDLE_INFO[code]
    lines = [
        f"# {code} input bundle",
        "",
        f"Structure: {_formula(structure)} ({len(structure)} atoms)",
        f"Files: {', '.join(files)}",
        "",
        "## What you must supply / review",
    ]
    for item in info["missing"]:
        lines.append(f"- {item}")
    lines += [
        "",
        "## Notes",
        "- The geometry is written in Angstrom by cifkit.",
        "- This is a *template*, not a converged input: review cutoffs, k-points, functional,",
        "  charges/spins and pseudopotential names before running.",
        "- cifkit does not provide POTCAR/UPF/skf files (licensing/size); no calculation has",
        "  been run or validated against the target code in this bundle.",
        "",
    ]
    (path / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_bundle(
    structure: Structure,
    code: str,
    outdir: str | Path,
    *,
    title: str | None = None,
) -> dict[str, Any]:
    """Write a computation-software input bundle; returns file list + missing items."""
    key = str(code or "").strip().lower()
    if key not in BUNDLE_INFO:
        raise ValueError(f"unsupported bundle {code!r}; available: {', '.join(sorted(BUNDLE_INFO))}")
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    stem = "structure" if not title else str(title).replace(" ", "_")[:40]
    form = _formula(structure)

    def _w(fmt: str, name: str | None = None) -> Path:
        p = out / (name or f"{stem}.{fmt}")
        write_structure(structure, p, fmt, title=title or form)
        files.append(p.name)
        return p

    def _txt(name: str, text: str) -> None:
        (out / name).write_text(text, encoding="utf-8")
        files.append(name)

    if key == "vasp":
        _w("vasp", "POSCAR")
        _txt("INCAR", """# VASP relaxation template (cifkit) — review ENCUT/ISMEAR/k-points
SYSTEM = %s
PREC = Accurate
ENCUT = 520
EDIFF = 1E-5
IBRION = 2
ISIF = 3
NSW = 100
ISMEAR = 0
SIGMA = 0.05
LREAL = Auto
LWAVE = .FALSE.
LCHARG = .FALSE.
""" % form)
        _txt("INCAR.static", """# VASP static template (cifkit) — use after relaxation
SYSTEM = %s
PREC = Accurate
ENCUT = 520
EDIFF = 1E-6
IBRION = -1
NSW = 0
ISMEAR = -5
LWAVE = .FALSE.
LCHARG = .FALSE.
""" % form)
        _txt("KPOINTS", """Automatic k-mesh (cifkit default; converge it)
0
Gamma
2 2 2
0.0 0.0 0.0
""")
        _txt("POTCAR.readme", """POTCAR is NOT included (VASP licensing). Build it from your licensed
PAW potentials in the POSCAR species order, e.g.:
  cat $VASP_PP/POTPAW_PBE/Zn/POTCAR ... > POTCAR
Check that the POTCAR species lines match the POSCAR title/species order.""")
    elif key == "qe":
        _w("qe", "pw.in")
        _txt("README.KPOINTS", "Suggested starting mesh: 2x2x2 (or Gamma-only for molecules); converge ecutwfc/ecutrho.\n")
        _txt("PSEUDO.readme", "Provide <Element>.UPF pseudopotential files named as in pw.in ATOMIC_SPECIES (or edit the names).\n")
    elif key == "cp2k":
        _w("cp2k", "cp2k.inp")
    elif key == "lammps":
        _w("lammps", "data.lammps")
        _txt("in.min", """# LAMMPS minimization template (cifkit) — choose a force field!
units metal
atom_style atomic
boundary p p p
read_data data.lammps
# mass 1 65.38   # add masses if the data file has none
# pair_style ... / pair_coeff ...
# kspace_style ewald 1e-6   # for charged systems
neighbor 2.0 bin
thermo 100
thermo_style custom step pe etotal press temp
min_style cg
minimize 1e-8 1e-10 10000 100000
""")
    elif key == "gromacs":
        _w("gromacs", "conf.gro")
        _txt("md.mdp", """; GROMACS .mdp template (cifkit) — EM/eq/run; adjust force field & T/P
integrator = steep
emtol = 1000.0
emstep = 0.01
nsteps = 5000
cutoff-scheme = Verlet
coulombtype = PME
rcoulomb = 1.0
rvdw = 1.0
pbc = xyz
""")
        _txt("TOP.readme", """The .top/.itp force-field topology is NOT generated (needs a force field and
bond perception). Build it with your preferred FF (e.g. GAFF/OPLS/UFF) and
include conf.gro as the starting coordinates.""")
    elif key == "gaussian":
        _w("gaussian", "mol.gjf")
    elif key == "orca":
        _w("orca", "orca.inp")
        _w("xyz", "coords.xyz")
    elif key == "abacus":
        _w("abacus", "STRU")
        _txt("INPUT.readme", "Provide an ABACUS INPUT file (ecutwfc, k-points, basis_type='lcao' or 'pw').\n")
    elif key == "dftb":
        _w("gen", "geo.gen")
        _w("dftb", "dftb_in.hsd")
        _txt("SLKO.readme", "Place the Slater-Koster .skf files under ./slakos/ with the prefix/separator/suffix "
                            "configured in dftb_in.hsd.\n")
    elif key == "siesta":
        _w("siesta", "structure.fdf")
    elif key == "nwchem":
        _w("nwchem", "mol.nw")
    elif key == "aims":
        _w("aims", "geometry.in")
        _txt("control.readme", "Provide control.in with species defaults (basis, xc, k-grid) for FHI-aims.\n")

    _README(out, structure, key, files)
    return {
        "code": key,
        "outdir": str(out),
        "files": files,
        "template": True,
        "missing": list(BUNDLE_INFO[key]["missing"]),
        "note": "输入模板 + 几何；POTCAR/UPF/skf/basis 等未提供，未在目标软件中真实运行。",
    }


__all__ = ["BUNDLE_INFO", "supported_bundles", "write_bundle"]
