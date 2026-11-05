"""计算化学格式写出。

Owner: geom teammate. Public API (DESIGN.md §6):

    write_structure(structure, path, fmt, *, title=None) -> str
    supported_formats() -> dict[str, str]

Every write is followed by a read-back check where a reader is available;
VASP/CIF/XYZ are verified strictly (atom count + parseable file), the other
formats at least get a content check. An unknown ``fmt`` raises ``ValueError``
listing the supported names.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from functools import partial

import numpy as np
from pymatgen.core import Structure

from cifkit.geom._common import element_symbol

#: canonical format name -> human readable description
FORMAT_INFO: dict[str, str] = {
    "vasp": "VASP POSCAR/CONTCAR (VASP5, species line; pymatgen Poscar)",
    "cif": "Crystallographic Information File (pymatgen CifWriter, symprec=None, no symmetry folding)",
    "xyz": "XYZ cartesian coordinates (ASE writer, cell recorded in the comment line; non-periodic)",
    "extxyz": "Extended XYZ with Lattice/Properties metadata (ASE, periodic, machine-learning friendly)",
    "json": "pymatgen Structure JSON (full lattice + sites + oxidation states)",
    "pdb": "Protein Data Bank (ASE proteindatabank writer; CRYST1 cell recorded)",
    "sdf": "MDL SDF (ASE writer, bonds perceived; periodic cell not represented)",
    "mol": "MDL MOL (ASE writer, bonds perceived; periodic cell not represented)",
    "cfg": "AtomEye CFG (ASE writer, periodic)",
    "gromacs": "GROMACS .gro coordinates (ASE writer; pair it with a .top from your force field)",
    "gen": "DFTB+ / general .gen geometry (ASE writer, periodic cell + species)",
    "aims": "FHI-aims geometry.in (ASE writer, fragment/cell sections)",
    "castep": "CASTEP .cell (ASE castep-cell writer; needs .param/keywords for a real run)",
    "abinit": "ABINIT input (ASE abinit-in writer; pseudos/variables must be completed)",
    "crystal": "CRYSTAL input (ASE writer; basis sets/hamiltonian must be completed)",
    "gaussian": "Gaussian .gjf (ASE gaussian-in writer; route/charge/multiplicity must be reviewed)",
    "nwchem": "NWChem .nw (ASE nwchem-in writer; theory/basis block must be completed)",
    "onetep": "ONETEP input (ASE writer; pseudo/params must be completed)",
    "dmol": "DMol3 .arc (ASE writer; theory/params must be completed)",
    "turbomole": "Turbomole coord (ASE writer; control file must be generated separately)",
    "res": "SHELX .res (ASE writer; for crystallographic refinement, not DFT)",
    "struct": "ASE .struct (ASE writer, periodic)",
    "lammps": "LAMMPS data file (atom style 'atomic'; ASE lammps-data writer)",
    "qe": "Quantum ESPRESSO pw.x input (ASE espresso-in writer, needs PAW pseudopotentials at run time)",
    "cp2k": "CP2K input skeleton (CELL + COORD; basis/potential must be supplied by the user)",
    "siesta": "SIESTA .fdf input template (CELL + AtomicCoordinates; species/pseudos must be supplied)",
    "abacus": "ABACUS STRU input template (ATOMIC_SPECIES/NUMERICAL_ORBITAL/LATTICE_CONSTANT/LATTICE_VECTORS/ATOMIC_POSITIONS)",
    "orca": "ORCA input template (.inp) + coordinates; basis/route must be reviewed",
    "dftb": "DFTB+ dftb_in.hsd template (Geometry gen or HSD; Slater-Koster files needed)",
    "xsf": "XCrySDen .xsf (periodic crystal, ASE writer)",
}

_ALIASES: dict[str, str] = {
    "poscar": "vasp",
    "contcar": "vasp",
    "vasp5": "vasp",
    "pymatgen-vasp": "vasp",
    "cif2": "cif",
    "mcif": "cif",
    "xyz2": "xyz",
    "extended-xyz": "extxyz",
    "ext_xyz": "extxyz",
    "pymatgen-json": "json",
    "structure-json": "json",
    "proteindatabank": "pdb",
    "protein-databank": "pdb",
    "mdl-sdf": "sdf",
    "mdl-mol": "mol",
    "atomeye": "cfg",
    "gro": "gromacs",
    "gromos": "gromacs",
    "dftb-gen": "gen",
    "dftb+": "dftb",
    "dftb_in": "dftb",
    "fhi-aims": "aims",
    "fhi_aims": "aims",
    "castep-cell": "castep",
    "castep-geom": "castep",
    "abinit-in": "abinit",
    "crystal-in": "crystal",
    "gaussian-in": "gaussian",
    "gaussian-gjf": "gaussian",
    "gjf": "gaussian",
    "nwchem-in": "nwchem",
    "onetep-in": "onetep",
    "dmol-arc": "dmol",
    "dmol3": "dmol",
    "turbomole-coord": "turbomole",
    "shelx": "res",
    "lammps-data": "lammps",
    "lammps_data": "lammps",
    "data": "lammps",
    "espresso": "qe",
    "espresso-in": "qe",
    "pwscf": "qe",
    "quantum-espresso": "qe",
    "cp2k-in": "cp2k",
    "cp2k_input": "cp2k",
    "siesta-fdf": "siesta",
    "fdf": "siesta",
    "abacus-stru": "abacus",
    "stru": "abacus",
    "orca-inp": "orca",
    "xcrysden": "xsf",
}


# ---------------------------------------------------------------------------
def normalize_format(fmt: str) -> str:
    """Canonicalise a format name / alias."""
    if not isinstance(fmt, str):
        raise ValueError(f"format must be a string, got {type(fmt).__name__}")
    key = fmt.strip().lower().replace(" ", "")
    key = _ALIASES.get(key, key)
    if key not in FORMAT_INFO:
        raise ValueError(
            f"unsupported export format {fmt!r}; available: {', '.join(sorted(FORMAT_INFO))} "
            f"(aliases: {', '.join(sorted(_ALIASES))})"
        )
    return key


def supported_formats() -> dict[str, str]:
    """Return ``{format: description}`` for every supported format."""
    return dict(FORMAT_INFO)


# ---------------------------------------------------------------------------
def _formula(structure: Structure) -> str:
    try:
        return structure.composition.formula.replace(" ", "")
    except Exception:  # noqa: BLE001
        return f"{len(structure)} atoms"


def _comment(structure: Structure, title: str | None) -> str:
    if title:
        return str(title).replace("\n", " ").strip()
    return f"{_formula(structure)} ({len(structure)} atoms)"


def _ase_atoms(structure: Structure):
    from pymatgen.io.ase import AseAtomsAdaptor

    return AseAtomsAdaptor.get_atoms(structure)


def _write_vasp(structure: Structure, path: Path, title: str | None) -> None:
    from pymatgen.io.vasp import Poscar

    Poscar(structure, comment=_comment(structure, title)).write_file(str(path))


def _write_cif(structure: Structure, path: Path, title: str | None) -> None:
    from pymatgen.io.cif import CifWriter

    CifWriter(structure, symprec=None).write_file(str(path))


def _write_xyz(structure: Structure, path: Path, title: str | None) -> None:
    cells = np.asarray(structure.lattice.matrix, dtype=float)
    comment = (
        f"{_comment(structure, title)} | "
        f"cell=({','.join(f'{v:.6f}' for v in structure.lattice.abc)}) "
        f"angles=({','.join(f'{v:.4f}' for v in structure.lattice.angles)})"
    )
    lines = [str(len(structure)), comment]
    for site, cart in zip(structure, np.asarray(structure.cart_coords, dtype=float)):
        lines.append(f"{element_symbol(site):2s} {cart[0]:18.10f} {cart[1]:18.10f} {cart[2]:18.10f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    del cells


def _write_lammps(structure: Structure, path: Path, title: str | None) -> None:
    import ase.io

    ase.io.write(str(path), _ase_atoms(structure), format="lammps-data")


def _qe_pseudopotentials(structure: Structure, pseudopotentials: dict[str, str] | None = None) -> dict[str, str]:
    """Default QE pseudopotential names for every element in the structure.

    ASE's ``espresso-in`` writer crashes with a bare ``KeyError`` when an element
    has no pseudopotential entry, so we always provide a placeholder
    ``<Element>.UPF`` name (the file itself is only needed when actually running
    Quantum ESPRESSO) and raise a descriptive ``ValueError`` for pseudo-elements
    or for a user mapping that misses an element.
    """
    from ase.data import atomic_numbers

    elements = sorted({element_symbol(site) for site in structure})
    unknown = [el for el in elements if el not in atomic_numbers]
    if unknown:
        raise ValueError(
            f"QE export: cannot generate pseudopotential names for element(s) {unknown} "
            f"(not a real element symbol); valid elements in this structure: "
            f"{[el for el in elements if el in atomic_numbers]}"
        )
    mapping = {el: f"{el}.UPF" for el in elements}
    if pseudopotentials:
        for el, name in pseudopotentials.items():
            symbol = "".join(ch for ch in str(el) if ch.isalpha())
            if symbol in mapping and name:
                mapping[symbol] = str(name)
        missing = [el for el in elements if not mapping.get(el)]
        if missing:
            raise ValueError(
                f"QE export: missing pseudopotential for element(s) {missing}; "
                f"pass e.g. write_structure(..., fmt='qe', pseudopotentials={{'Zn': 'Zn.pbe-vdz.UPF'}})"
            )
    return mapping


def _write_qe(
    structure: Structure,
    path: Path,
    title: str | None,
    pseudopotentials: dict[str, str] | None = None,
) -> None:
    import ase.io

    ase.io.write(
        str(path),
        _ase_atoms(structure),
        format="espresso-in",
        pseudopotentials=_qe_pseudopotentials(structure, pseudopotentials),
    )



def _write_xsf(structure: Structure, path: Path, title: str | None) -> None:
    import ase.io

    ase.io.write(str(path), _ase_atoms(structure), format="xsf")


def _write_cp2k(structure: Structure, path: Path, title: str | None) -> None:
    lat = structure.lattice
    abc = " ".join(f"{float(v):.10f}" for v in lat.abc)
    angles = " ".join(f"{float(v):.6f}" for v in lat.angles)
    lines = [
        f"# {_comment(structure, title)}",
        "# Minimal CP2K input skeleton written by cifkit; add BASIS_SET / POTENTIAL /",
        "# &KIND sections (or an &KIND per element) before running a real calculation.",
        "&FORCE_EVAL",
        "  METHOD Quickstep",
        "  &SUBSYS",
        "    &CELL",
        f"      ABC {abc}",
        f"      ALPHA_BETA_GAMMA {angles}",
        "      PERIODIC XYZ",
        "    &END CELL",
        "    &COORD",
    ]
    for site, frac in zip(structure, np.asarray(structure.frac_coords, dtype=float)):
        lines.append(f"      {element_symbol(site):2s} {frac[0]:18.10f} {frac[1]:18.10f} {frac[2]:18.10f}")
    lines += [
        "    &END COORD",
        "  &END SUBSYS",
        "  &DFT",
        "    &MGRID",
        "      CUTOFF 400",
        "      NGRIDS 4",
        "    &END MGRID",
        "  &END DFT",
        "&END FORCE_EVAL",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


#: cifkit format -> ASE writer name (periodic crystal formats)
def _write_castep(structure: Structure, path: Path, title: str | None) -> None:
    """CASTEP .cell skeleton: LATTICE_CART + POSITIONS_FRAC + species."""
    lat = structure.lattice
    lines = [
        "# CASTEP .cell skeleton written by cifkit; .param and pseudopotentials are not included.",
        "%BLOCK LATTICE_CART",
        "  Ang",
    ]
    for vec in lat.matrix:
        lines.append("  " + " ".join(f"{float(v):.10f}" for v in vec))
    lines.append("%ENDBLOCK LATTICE_CART")
    lines.append("")
    lines.append("%BLOCK POSITIONS_FRAC")
    for site, frac in zip(structure, structure.frac_coords):
        lines.append(f"  {element_symbol(site):2s} {frac[0]:18.10f} {frac[1]:18.10f} {frac[2]:18.10f}")
    lines.append("%ENDBLOCK POSITIONS_FRAC")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


_ASE_WRITERS: dict[str, str] = {
    "extxyz": "extxyz",
    "sdf": "sdf",
    "mol": "mol",
    "cfg": "cfg",
    "gromacs": "gromacs",
    "gen": "gen",
    "aims": "aims",
    "abinit": "abinit-in",
    "crystal": "crystal",
    "gaussian": "gaussian-in",
    "nwchem": "nwchem-in",
    "onetep": "onetep-in",
    "dmol": "dmol-arc",
    "turbomole": "turbomole",
    "res": "res",
    "struct": "struct",
    "pdb": "proteindatabank",
}

_ASE_READBACK: dict[str, str] = {
    "extxyz": "extxyz",
    "sdf": "sdf",
    "mol": "mol",
    "cfg": "cfg",
    "gromacs": "gromacs",
    "gen": "gen",
    "aims": "aims",
    "abinit": "abinit-in",
    "crystal": "crystal",
    "gaussian": "gaussian-in",
    "nwchem": "nwchem-in",
    "onetep": "onetep-in",
    "dmol": "dmol-arc",
    "turbomole": "turbomole",
    "res": "res",
    "struct": "struct",
    "pdb": "proteindatabank",
}

_TEMPLATE_FORMATS = ("siesta", "abacus", "orca", "dftb")


def _write_ase(structure: Structure, path: Path, title: str | None, *, ase_format: str) -> None:
    import ase.io

    atoms = _ase_atoms(structure)
    if title:
        atoms.info["comment"] = _comment(structure, title)
    ase.io.write(str(path), atoms, format=ase_format)


def _write_json(structure: Structure, path: Path, title: str | None) -> None:
    import json

    payload = structure.as_dict()
    if title:
        payload["cifkit_title"] = str(title)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_siesta(structure: Structure, path: Path, title: str | None) -> None:
    """SIESTA .fdf skeleton: lattice + fractional coordinates + species block."""
    lat = structure.lattice
    lines = [
        f"# SIESTA input skeleton written by cifkit: {_comment(structure, title)}",
        "# Add SpeciesLabel/PAO.Basis or use the SIESTA pseudopotential database; lattice in Ang.",
        "SystemName %s" % _formula(structure),
        f"NumberOfAtoms {len(structure)}",
        "NumberOfSpecies %d" % len({element_symbol(site) for site in structure}),
        "LatticeConstant 1.0 Ang",
        "%block LatticeVectors",
    ]
    for vec in lat.matrix:
        lines.append("  " + " ".join(f"{float(v):.10f}" for v in vec))
    lines += ["%endblock LatticeVectors", "AtomicCoordinatesFormat Fractional", "%block AtomicCoordinatesAndAtomicSpecies"]
    species = sorted({element_symbol(site) for site in structure})
    index = {el: i + 1 for i, el in enumerate(species)}
    for site, frac in zip(structure, structure.frac_coords):
        lines.append(f"  {frac[0]:18.10f} {frac[1]:18.10f} {frac[2]:18.10f} {index[element_symbol(site)]}")
    lines += ["%endblock AtomicCoordinatesAndAtomicSpecies", "%block ChemicalSpeciesLabel"]
    for el, idx in index.items():
        lines.append(f"  {idx} {structure.composition.get(el, 1):.0f} {el}")
    lines += ["%endblock ChemicalSpeciesLabel"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_abacus(structure: Structure, path: Path, title: str | None) -> None:
    """ABACUS STRU skeleton (Angstrom lattice, cartesian atoms, magmom=0)."""
    lat = structure.lattice
    species = sorted({element_symbol(site) for site in structure})
    lines = [
        "ATOMIC_SPECIES",
    ]
    for el in species:
        mass = 1.0
        try:
            from pymatgen.core import Element

            mass = float(Element(el).atomic_mass)
        except Exception:  # noqa: BLE001
            pass
        lines.append(f"{el:2s} {mass:10.4f} {el}_ONCV_PBE-1.0.upf")
    lines += ["", "NUMERICAL_ORBITAL"] + [f"{el}_gga_8au_100Ry_2s1p1d.orb" for el in species]
    lines += ["", "LATTICE_CONSTANT", "1.0", "", "LATTICE_VECTORS"]
    for vec in lat.matrix:
        lines.append("  " + " ".join(f"{float(v):.10f}" for v in vec))
    lines += ["", "ATOMIC_POSITIONS", "Cartesian", ""]
    for el in species:
        lines.append(el)
        lines.append("0.0")
        lines.append(str(sum(1 for site in structure if element_symbol(site) == el)))
        for site, cart in zip(structure, structure.cart_coords):
            lines.append(f"  {cart[0]:18.10f} {cart[1]:18.10f} {cart[2]:18.10f} 0 0 0")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_orca(structure: Structure, path: Path, title: str | None) -> None:
    lines = [
        "# ORCA input template written by cifkit; review the route, charge and multiplicity.",
        "! PBE def2-SVP Opt Freq",
        f"# {_comment(structure, title)}",
        "%pal nprocs 4 end",
        f"* xyz {0} {1}",
    ]
    for site, cart in zip(structure, structure.cart_coords):
        lines.append(f"  {element_symbol(site):2s} {cart[0]:16.8f} {cart[1]:16.8f} {cart[2]:16.8f}")
    lines += ["*", ""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_dftb(structure: Structure, path: Path, title: str | None) -> None:
    lat = structure.lattice
    lines = [
        "Geometry = GenFormat {",
        '  <<< "geo.gen"',
        "}",
        "# DFTB+ input skeleton written by cifkit. Provide the Slater-Koster files in the",
        "# working directory and review the Hamiltonian/charges blocks.",
        "Hamiltonian = DFTB {",
        "  SCC = Yes",
        "  SCCTolerance = 1.0E-005",
        "  MaxSCCIterations = 100",
        "  SlaterKosterFiles = Type2FileNames {",
        '    Prefix = "./slakos/"',
        '    Separator = "-"',
        '    Suffix = ".skf"',
        "  }",
        "  MaxAngularMomentum = {",
    ]
    for el in sorted({element_symbol(site) for site in structure}):
        shell = "p" if el in ("H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne") else "d"
        lines.append(f'    {el} = "{shell}"')
    lines += ["  }", "}", "Options { WriteResultsTag = Yes }", ""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")



_WRITERS: dict[str, Callable[..., None]] = {
    "vasp": _write_vasp,
    "cif": _write_cif,
    "xyz": _write_xyz,
    "json": _write_json,
    "lammps": _write_lammps,
    "qe": _write_qe,
    "cp2k": _write_cp2k,
    "xsf": _write_xsf,
    "siesta": _write_siesta,
    "abacus": _write_abacus,
    "orca": _write_orca,
    "dftb": _write_dftb,
    "castep": _write_castep,
}
for _fmt, _ase_name in _ASE_WRITERS.items():
    _WRITERS[_fmt] = partial(_write_ase, ase_format=_ase_name)


# ---------------------------------------------------------------------------
def _readback_natoms(path: Path, fmt: str) -> int | None:
    """Try to read a written file back and return its atom count (``None`` if unsupported)."""
    if fmt == "vasp":
        from pymatgen.io.vasp import Poscar

        poscar = Poscar.from_file(str(path), check_for_potcar=False, read_velocities=False)
        return len(poscar.structure)
    if fmt == "cif":
        return len(Structure.from_file(str(path)))
    if fmt == "xyz":
        import ase.io

        return len(ase.io.read(str(path), format="xyz"))
    if fmt == "xsf":
        import ase.io

        return len(ase.io.read(str(path), format="xsf"))
    if fmt == "lammps":
        import ase.io

        return len(ase.io.read(str(path), format="lammps-data"))
    if fmt == "qe":
        import ase.io

        return len(ase.io.read(str(path), format="espresso-in"))
    if fmt == "json":
        import json as _json

        return len(Structure.from_dict(_json.loads(path.read_text(encoding="utf-8"))))
    if fmt in _ASE_READBACK:
        import ase.io

        return len(ase.io.read(str(path), format=_ASE_READBACK[fmt]))
    return None


def _verify(path: Path, fmt: str, natoms: int) -> None:
    if not path.is_file():
        raise RuntimeError(f"writer for {fmt!r} did not create {path}")
    size = path.stat().st_size
    if size <= 0:
        raise RuntimeError(f"writer for {fmt!r} produced an empty file: {path}")

    text = path.read_text(encoding="utf-8", errors="replace")
    if fmt == "vasp":
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) < 9:
            raise RuntimeError(f"VASP file {path} is too short to be a POSCAR ({len(lines)} non-empty lines)")
        if not lines[0].strip():
            raise RuntimeError(f"VASP file {path}: first (comment) line is empty")
    if fmt == "qe":
        for keyword in ("ATOMIC_SPECIES", "CELL_PARAMETERS", "ATOMIC_POSITIONS"):
            if keyword not in text:
                raise RuntimeError(f"QE input {path} is missing the {keyword} section")
    if fmt == "cp2k":
        if "&COORD" not in text or "&CELL" not in text:
            raise RuntimeError(f"CP2K file {path} is missing &CELL / &COORD sections")
        coord_lines = 0
        inside = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("&COORD"):
                inside = True
                continue
            if inside and stripped.upper().startswith("&END"):
                inside = False
            elif inside and stripped and not stripped.startswith("#"):
                coord_lines += 1
        if coord_lines != natoms:
            raise RuntimeError(f"CP2K file {path}: {coord_lines} coordinates for {natoms} atoms")
        return
    if fmt == "castep":
        for keyword in ("LATTICE_CART", "POSITIONS_FRAC"):
            if keyword not in text:
                raise RuntimeError(f"CASTEP .cell {path} is missing %BLOCK {keyword}")
        return
    if fmt in _TEMPLATE_FORMATS:
        required = {
            "siesta": ("LatticeVectors", "AtomicCoordinates"),
            "abacus": ("ATOMIC_SPECIES", "LATTICE_VECTORS", "ATOMIC_POSITIONS"),
            "orca": ("* xyz", "!"),
            "dftb": ("Geometry",),
        }[fmt]
        missing = [kw for kw in required if kw not in text]
        if missing:
            raise RuntimeError(f"{fmt} template {path} is missing required keyword(s): {missing}")
        return
    if fmt == "json":
        import json as _json

        Structure.from_dict(_json.loads(text))
        return

    readback = _readback_natoms(path, fmt)
    if readback is not None and readback != natoms:
        raise RuntimeError(f"{fmt} read-back mismatch: wrote {natoms} atoms, read {readback} from {path}")


# ---------------------------------------------------------------------------
def write_structure(
    structure: Structure,
    path,
    fmt: str,
    *,
    title: str | None = None,
    pseudopotentials: dict[str, str] | None = None,
) -> str:
    """Write ``structure`` to ``path`` in ``fmt`` and verify the result.

    Args:
        structure: structure to export (periodic or a cluster in a box).
        path: destination file path (parent directories are created).
        fmt: format name or alias, see :func:`supported_formats`.
        title: optional comment/title line (VASP comment, XYZ comment, ...).
        pseudopotentials: optional ``{element: UPF filename}`` mapping for the
            ``qe`` format; defaults to the placeholder ``<Element>.UPF`` names
            (the UPF files are only needed when running Quantum ESPRESSO).

    Returns:
        The absolute-ish path (as ``str``) of the written file.

    Raises:
        ValueError: unknown format, bad arguments, or an element without a
            usable QE pseudopotential name.
        RuntimeError: the file could not be written/verified (e.g. read-back
            atom count mismatch), which would indicate a real writer problem.
    """
    if not isinstance(structure, Structure):
        raise ValueError(f"write_structure: expected a pymatgen Structure, got {type(structure).__name__}")
    if len(structure) == 0:
        raise ValueError("write_structure: refusing to export an empty structure")
    key = normalize_format(fmt)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if key == "qe":
        _write_qe(structure, out, title, pseudopotentials)
    else:
        _WRITERS[key](structure, out, title)
    _verify(out, key, len(structure))
    return str(out)


__all__ = ["FORMAT_INFO", "normalize_format", "supported_formats", "write_structure"]
