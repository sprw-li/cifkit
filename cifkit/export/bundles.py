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
        "description": "GROMACS .gro coordinates + .mdp + .top skeleton (placeholder FF)",
        "missing": [
            "force-field atom types/charges (the shipped .top lists real atoms and "
            "bonds but its types/charges are PLACEHOLDERS)",
            "box/charge equilibration",
        ],
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
    """Write the bundle's ``README.md`` and declare it in ``files`` (round 58).

    Every bundle writes this file, so it is part of what the bundle *produced*:
    leaving it out of the returned ``files`` made every caller undercount the
    bundle by one (``api.convert`` reports the raw return value).
    """
    info = BUNDLE_INFO[code]
    listing = [*files, "README.md"]
    lines = [
        f"# {code} input bundle",
        "",
        f"Structure: {_formula(structure)} ({len(structure)} atoms)",
        f"Files: {', '.join(listing)}",
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
    files.append("README.md")


def write_bundle(
    structure: Structure,
    code: str,
    outdir: str | Path,
    *,
    title: str | None = None,
) -> dict[str, Any]:
    """Write a computation-software input bundle; returns file list + missing items.

    ``files`` lists **every file the bundle wrote**, including ``README.md`` (round
    58 — it used to be omitted, so callers that count the returned list undercounted
    each bundle by one).  ``missing`` keeps its own meaning: things *the user* must
    supply, which the bundle deliberately does not contain.
    """
    from cifkit.export.disorder_guard import guard_ordered

    from cifkit.export.format_limits import guard_atom_limit

    # same contract as write_structure (round 55): the *guard* error, not the
    # library's opaque ValueError, must be what a caller sees
    for fmt_name in _bundle_ordered_formats(str(code or "").strip().lower()):
        guard_ordered(fmt_name, structure)
        guard_atom_limit(fmt_name, structure)

    key = str(code or "").strip().lower()
    if key not in BUNDLE_INFO:
        raise ValueError(f"unsupported bundle {code!r}; available: {', '.join(sorted(BUNDLE_INFO))}")
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    # files that were already there before this call (a reused outdir must not have
    # its unrelated contents reported as part of *this* bundle)
    pre_existing = {p.name for p in out.iterdir() if p.is_file()}
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
        # LAMMPS comments use '#'.  A ';' is not a comment: it is an *unknown command*
        # and aborts the run (measured 2026-11-11, job b0b85bc0).  Never use ';' here.
        #
        # The DEFAULT is lj/cut with placeholder parameters, because `pair_style zero`
        # evaluates no forces at all (measured 2026-11-11, job 060f75f5: "Iterations,
        # force evaluations = 1 0").  Placeholder LJ does real work - 200 minimisation
        # steps / 200 force evaluations on these cells - but it is NOT a fitted force
        # field, so a production study must replace the parameters.
        _txt("in.min", """# LAMMPS minimisation (cifkit)
# The data file has masses and atom types but NO force field.  The pair_coeff below
# is a PLACEHOLDER (epsilon 0.0103 eV, sigma 3.4 A, cutoff 10 A): it makes LAMMPS
# evaluate real forces so the geometry relaxes, but it is not a fitted force field.
# Replace it with UFF/DREIDING/EAM (see the options at the bottom) for real chemistry.
units           metal
atom_style      atomic
boundary        p p p
read_data       data.lammps
pair_style      lj/cut 10.0
pair_coeff      * * 0.0103 3.4
neighbor        2.0 bin

# --- option A: geometry-only check (NO force evaluation; for file validation) ---
# pair_style    zero 10.0
# pair_coeff    * *

# --- option B: a real force field (needs its own files) ------------------------
# pair_style    eam/alloy
# pair_coeff    * * <potential>.eam.alloy <elements...>
# pair_style    uff          # if your LAMMPS build has it (the Debian package does not)
# pair_coeff    * * <element per type>

thermo          10
thermo_style    custom step pe etotal press
min_style       cg
minimize        1e-6 1e-8 200 2000
""")
        _txt("in.readme", """`data.lammps` carries coordinates, atom types and masses (written by cifkit);
the force field does not exist yet - that is the user's choice.  `in.min` shows
three options: `zero` (geometry-only), a generic LJ placeholder, or a real FF.
For a periodic MOF the usual starting points are UFF/DREIDING (via a converter)
or an EAM/alloy potential for the metal nodes.""")
    elif key == "gromacs":
        _w("gromacs", "conf.gro")
        _w("xyz", "coords.xyz")
        _txt("topol.top", _gromacs_topology(structure, title))
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
        _txt("TOP.readme", """`topol.top` is a SKELETON: it lists every atom (with element masses), the bonds
cifkit perceived, and all required sections, but the [ atomtypes ]/[ atoms ]
charges and Lennard-Jones parameters are PLACEHOLDERS - no force field can be
derived from a CIF.  Replace them with your FF (UFF/DREIDING via a converter, or
a MOF-specific force field) before running GROMACS.""")
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
    # round 58: the returned list is the bundle's contract, so it must match what is
    # on disk.  Any file this branch produced without declaring it (the class of bug
    # that omitted README.md) is appended here instead of being silently dropped.
    written = {p.name for p in out.iterdir() if p.is_file()} - pre_existing
    for name in sorted(written - set(files)):
        files.append(name)
    return {
        "code": key,
        "outdir": str(out),
        "files": files,
        "template": True,
        "missing": list(BUNDLE_INFO[key]["missing"]),
        "note": "输入模板 + 几何；POTCAR/UPF/skf/basis 等未提供，未在目标软件中真实运行。",
    }



def _gromacs_topology(structure: Structure, title: str | None) -> str:
    """A GROMACS ``.top`` skeleton with real atoms/bonds and placeholder types.

    Round 42 (limitation E4): the bundle used to ship only ``conf.gro``, so the
    GROMACS user had to rebuild the whole topology.  cifkit already perceives bonds,
    so the *connectivity* can be handed over; what cannot be derived are force-field
    atom types, charges and parameters - those stay explicit ``TODO`` placeholders.
    """
    from cifkit.repair.bonds import perceive_bonds

    symbols = [element_symbol(site) for site in structure]
    masses = {}
    for site in structure:
        symbol = element_symbol(site)
        masses.setdefault(symbol, _atomic_mass(symbol))
    order = sorted(masses)
    # atom types: one placeholder per element (never a silent guess)
    type_index = {symbol: index + 1 for index, symbol in enumerate(order)}

    bonds: set[tuple[int, int]] = set()
    try:
        graph = perceive_bonds(structure)
        # BondGraph exposes ``adj`` / ``unique_bonds``; use whichever is present so
        # a future rename cannot silently produce an empty bond list.
        unique = getattr(graph, "unique_bonds", None)
        if callable(unique):
            unique = unique()
        if unique is None:
            unique = []
            for items in (getattr(graph, "adj", {}) or {}).values():
                unique.extend(items)
        for bond in unique:
            i, j = int(getattr(bond, "i")), int(getattr(bond, "j"))
            if i != j:
                bonds.add((min(i, j) + 1, max(i, j) + 1))
    except Exception:  # noqa: BLE001 - topology is optional, never fatal
        bonds = set()

    lines = [
        f"; GROMACS topology skeleton written by cifkit: {_comment(structure, title)}",
        "; The ATOM TYPES and CHARGES below are PLACEHOLDERS (0 charge, type = 1,2,3...).",
        "; Assign a real force field (e.g. UFF/DREIDING via a converter, or a MOF FF)",
        "; before production, and set [ atomtypes ] to match it.",
        "",
        "[ defaults ]",
        "; nbfunc  comb-rule  gen-pairs  fudgeLJ  fudgeQQ",
        "1         2           yes        0.5      0.5",
        "",
        "[ atomtypes ]",
        "; name  at.num  mass  charge  ptype  sigma  epsilon   <- placeholders!",
    ]
    for symbol in order:
        number = _atomic_number(symbol)
        lines.append(f"  {symbol:4s} {number:4d} {masses[symbol]:8.3f} 0.0 A 0.30 0.40")
    lines += ["", "[ moleculetype ]", "; name  nrexcl", f"{_formula(structure):12s} 3", ""]
    lines.append("[ atoms ]")
    lines.append("; nr  type  resnr  residue  atom  cgnr  charge  mass")
    for index, site in enumerate(structure, start=1):
        symbol = element_symbol(site)
        lines.append(f"{index:5d} {type_index[symbol]:5d} 1      MOL      {symbol}{index:<4d} "
                     f"{index:5d} 0.0 {masses[symbol]:8.3f}")
    lines += ["", "[ bonds ]", "; ai  aj  funct"]
    for i, j in sorted(bonds):
        lines.append(f"{i:5d} {j:5d} 1")
    if not bonds:
        lines.append("; (no bonds perceived - add them from your own chemistry)")
    lines += ["", "[ system ]", _formula(structure), "", "[ molecules ]",
              "; name  count", f"{_formula(structure):12s} 1", ""]
    return "\n".join(lines)


def _atomic_mass(symbol: str) -> float:
    from pymatgen.core import Element

    try:
        return float(Element(symbol).atomic_mass)
    except Exception:  # noqa: BLE001
        return 1.0


def _atomic_number(symbol: str) -> int:
    from pymatgen.core import Element

    try:
        return int(Element(symbol).Z)
    except Exception:  # noqa: BLE001
        return 0


__all__ = ["BUNDLE_INFO", "supported_bundles", "write_bundle"]

#: bundle code -> the single-format writer whose ordering requirement applies
def _bundle_ordered_formats(code: str) -> tuple[str, ...]:
    """Which format's ordering requirement applies to this bundle's coordinates."""
    return {
        "vasp": ("vasp",),
        "qe": ("qe",),
        "gromacs": ("gromacs",),
        "lammps": ("lammps",),
        "nwchem": ("nwchem",),
        "aims": ("aims",),
        "gaussian": ("gaussian",),
        "dftb": ("gen",),
        "orca": ("xyz",),
        "cp2k": (),
        "siesta": ("siesta",),
        "abacus": ("abacus",),
    }.get(code, ())
