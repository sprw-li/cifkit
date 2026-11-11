"""Hard structural limits of the target formats, as a typed contract (round 56).

A 320-structure corpus sweep found two failure modes where the *format itself* cannot
represent the structure:

* ``.mol`` / ``.sdf`` (MDL V2000) reject >999 atoms — the library raises, which is at
  least loud;
* ``.struct`` (WIEN2k) is a **fixed-width** format whose atom count lives in a
  3-character field.  ASE's reader does ``nat = int(pip[1][27:30])``, so a 2376-atom
  file reads back as **237 atoms** — silent truncation, caught only because every
  export is read back and compared.

Writing a file that silently loses 90% of the atoms is the worst possible outcome, so
these limits are checked *before* writing, with an error that names the limit and the
way out (the ``.cif``/``.json`` writers have no such limit; splitting the cell or using
a different format are the alternatives).
"""
from __future__ import annotations

from typing import Any

#: format -> (max atoms, why)
ATOM_LIMITS: dict[str, tuple[int, str]] = {
    "mol": (999, "MDL MOL V2000 stores the atom count in a 3-digit field"),
    "sdf": (999, "MDL SDF V2000 stores the atom count in a 3-digit field"),
    "struct": (999, "WIEN2k .struct puts the atom count in columns 27-30; a 4th digit "
                    "shifts the field and the reader truncates it"),
    "pdb": (99999, "PDB serial numbers are 5 digits wide"),
}


class FormatLimitError(ValueError):
    """Raised when a structure exceeds a format's hard structural limit."""

    code = "format-limit"

    def __init__(self, fmt: str, natoms: int, limit: int, why: str) -> None:
        self.fmt = fmt
        self.natoms = natoms
        self.limit = limit
        message = (
            f"format {fmt!r} cannot hold {natoms} atoms (limit {limit}): {why}. "
            "This is a property of the file format, not of the structure - use a "
            "format without the limit (cif, json, xyz, vasp, ...) or split the cell")
        super().__init__(message)


def guard_atom_limit(fmt: str, structure: Any) -> None:
    """Raise :class:`FormatLimitError` before a lossy or rejected write happens."""
    limit = ATOM_LIMITS.get(fmt)
    if limit is None:
        return
    natoms = len(structure)
    if natoms > limit[0]:
        raise FormatLimitError(fmt, natoms, limit[0], limit[1])


__all__ = ["ATOM_LIMITS", "FormatLimitError", "guard_atom_limit"]
