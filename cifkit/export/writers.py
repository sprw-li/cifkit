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

import numpy as np
from pymatgen.core import Structure

from cifkit.geom._common import element_symbol

#: canonical format name -> human readable description
FORMAT_INFO: dict[str, str] = {
    "vasp": "VASP POSCAR/CONTCAR (VASP5, species line; pymatgen Poscar)",
    "cif": "Crystallographic Information File (pymatgen CifWriter, symprec=None, no symmetry folding)",
    "xyz": "XYZ cartesian coordinates (ASE writer, cell recorded in the comment line; non-periodic)",
    "lammps": "LAMMPS data file (atom style 'atomic'; ASE lammps-data writer)",
    "qe": "Quantum ESPRESSO pw.x input (ASE espresso-in writer, needs PAW pseudopotentials at run time)",
    "cp2k": "CP2K input skeleton (CELL + COORD; basis/potential must be supplied by the user)",
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
    "lammps-data": "lammps",
    "lammps_data": "lammps",
    "data": "lammps",
    "espresso": "qe",
    "espresso-in": "qe",
    "pwscf": "qe",
    "quantum-espresso": "qe",
    "cp2k-in": "cp2k",
    "cp2k_input": "cp2k",
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


_WRITERS: dict[str, Callable[..., None]] = {
    "vasp": _write_vasp,
    "cif": _write_cif,
    "xyz": _write_xyz,
    "lammps": _write_lammps,
    "qe": _write_qe,
    "cp2k": _write_cp2k,
    "xsf": _write_xsf,
}


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
