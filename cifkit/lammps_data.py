"""Parse a cifkit-written ``data.lammps`` and evaluate the LJ energy independently.

The first cross-check used the CIF as the source of coordinates, which mixes in any
export difference.  This reads the **exact file we ship**, so a mismatch can only come
from the physics evaluation (image enumeration, cutoff convention), not from export.

The parser mirrors LAMMPS's own restricted-triclinic header convention
(``read_data``): the three edge vectors are

* **A** = ``(xhi - xlo, 0, 0)``
* **B** = ``(xy, yhi - ylo, 0)``
* **C** = ``(xz, yz, zhi - zlo)``

with the box origin at ``(xlo, ylo, zlo)`` and the atom coordinates given in that
Cartesian frame (LAMMPS wraps them into the parallelepiped).  Only the frame used by
cifkit's writer (``cifkit.export.writers._write_lammps``, origin at the box corner) is
supported; malformed or truncated files raise ``ValueError`` with the offending line
rather than returning a half-parsed structure.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

__all__ = ["read_data_lammps", "frac_to_cart"]

_BOX_KEYS = ("xlo xhi", "ylo yhi", "zlo zhi")


def _find_keyword(lines: list[str], key: str) -> int:
    """Index of the header line ending in ``key``, or -1 when absent."""
    for index, line in enumerate(lines):
        if line.strip().endswith(key):
            return index
    return -1


def _header_pair(lines: list[str], key: str) -> tuple[float, float]:
    index = _find_keyword(lines, key)
    if index < 0:
        raise ValueError(f"not a LAMMPS data file: no '{key}' header line")
    parts = lines[index].split()
    if len(parts) < 2:
        raise ValueError(f"malformed '{key}' header line {index + 1}: {lines[index]!r}")
    try:
        return float(parts[0]), float(parts[1])
    except ValueError as exc:
        raise ValueError(
            f"non-numeric '{key}' header line {index + 1}: {lines[index]!r}") from exc


def read_data_lammps(path: str | Path) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """Return ``(lattice_vectors, cart_positions, type_ids)`` from an atomic-style file.

    ``lattice_vectors`` has one edge vector per row; ``cart_positions`` is an ``(n, 3)``
    array in Angstrom; ``type_ids`` are the LAMMPS atom types in file order (1-based).
    Raises ``ValueError`` when a required header or the ``Atoms`` section is missing.
    """
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()

    xlo, xhi = _header_pair(lines, "xlo xhi")
    ylo, yhi = _header_pair(lines, "ylo yhi")
    zlo, zhi = _header_pair(lines, "zlo zhi")
    xy = xz = yz = 0.0
    tilt = _find_keyword(lines, "xy xz yz")
    if tilt >= 0:
        parts = lines[tilt].split()
        if len(parts) < 3:
            raise ValueError(f"malformed 'xy xz yz' header line {tilt + 1}: "
                             f"{lines[tilt]!r}")
        try:
            xy, xz, yz = float(parts[0]), float(parts[1]), float(parts[2])
        except ValueError as exc:
            raise ValueError(f"non-numeric 'xy xz yz' header line {tilt + 1}: "
                             f"{lines[tilt]!r}") from exc

    lattice = np.array([[xhi - xlo, 0.0, 0.0],
                        [xy, yhi - ylo, 0.0],
                        [xz, yz, zhi - zlo]], dtype=float)

    # Atoms section: "id type x y z" (atom_style atomic).  The line after the section
    # keyword is always skipped by LAMMPS; values then run until a line that is not a
    # 5+ field atom record (a blank line or the next section).
    atoms_start = -1
    for section, line in enumerate(lines):
        if line.strip().lower().startswith("atoms"):
            atoms_start = section + 2
            break
    if atoms_start < 0:
        raise ValueError("no 'Atoms' section in the LAMMPS data file")
    positions: list[list[float]] = []
    types: list[int] = []
    for offset, line in enumerate(lines[atoms_start:], start=atoms_start + 1):
        stripped = line.strip()
        if not stripped:
            if positions:
                break
            continue
        parts = stripped.split()
        if len(parts) < 5:
            if positions:
                break
            raise ValueError(f"expected an atom line 'id type x y z' at line {offset}, "
                             f"got {line!r}")
        try:
            types.append(int(parts[1]))
            positions.append([float(parts[2]), float(parts[3]), float(parts[4])])
        except ValueError as exc:
            raise ValueError(f"malformed atom line {offset}: {line!r}") from exc
    if not positions:
        raise ValueError("the 'Atoms' section contains no atoms")

    cart = np.array(positions, dtype=float)
    # LAMMPS triclinic boxes store positions relative to (xlo, ylo, zlo)
    cart[:, 0] += xlo
    cart[:, 1] += ylo
    cart[:, 2] += zlo
    return lattice, cart, types


def frac_to_cart(lattice: np.ndarray, frac: np.ndarray) -> np.ndarray:
    """Fractional coordinates (one row per atom) to Cartesian, box origin at zero."""
    return np.asarray(frac, dtype=float) @ np.asarray(lattice, dtype=float)
