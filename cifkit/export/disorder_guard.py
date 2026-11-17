"""Round 55g: guarded export of partially-occupied structures.

The corpus sweep (round 55) exported a 348-atom *disordered* ZIF-8 and got 22 raw
library failures:

    ValueError: ASE Atoms only supports ordered structures
    ValueError: Disordered structure with partial occupancies cannot be converted
                into POSCAR!

Those exceptions come from ASE/pymatgen, not from cifkit, and they are only raised
*deep inside* the writer — so a platform sees an opaque ``ValueError`` with no
statement about what to do.  This module makes it a first-class contract:

* :func:`structure_is_ordered` — does the structure have partial occupancies?
* :class:`DisorderedStructureError` — a typed error with code ``disordered``, naming
  the format and the fix (resolve the disorder first, e.g. the pipeline's repair
  stage, then export);
* formats that *can* carry disorder keep working unchanged.
"""
from __future__ import annotations

from typing import Any

from cifkit.export.refusals import ExportRefusalError

#: formats that cannot carry partial occupancies.  Determined empirically by the
#: corpus sweep, not guessed.  Most of these raise inside ASE/pymatgen; ``castep`` is
#: special — it *writes* the majority species silently, which loses information, so it
#: is guarded here even though it does not raise on its own (round 55).  ``dftb`` is
#: guarded because its coordinates live in the sibling ``geo.gen`` (round 58), which is
#: an ASE ``gen`` write and therefore ordered-only too.
ORDERED_ONLY = frozenset({
    "abinit", "aims", "castep", "cfg", "crystal", "dftb", "dmol", "extxyz", "gaussian",
    "gen", "gromacs", "lammps", "mol", "nwchem", "onetep", "pdb", "qe", "res",
    "sdf", "struct", "turbomole", "vasp", "xsf", "xyz",
})


class DisorderedStructureError(ExportRefusalError):
    """Raised when a format cannot express a partially-occupied structure."""

    code = "disordered"

    def __init__(self, fmt: str, detail: str = "") -> None:
        self.fmt = fmt
        message = (
            f"format {fmt!r} cannot express a structure with partial occupancies; "
            "resolve the disorder first (the pipeline's repair stage expands "
            "occupancies, or run cifkit.geom.standardize on the structure) and then "
            "export")
        if detail:
            message += f" [{detail}]"
        super().__init__(message)


def structure_is_ordered(structure: Any) -> bool:
    """True when every site has full occupancy (round 55).

    A site is considered partially occupied when it carries more than one species or
    an occupancy below 1 (allowing a small tolerance for floating-point noise).
    """
    for site in structure:
        if site.is_ordered is False:
            return False
        occupancy = getattr(site, "occupancy", None)
        if occupancy is not None and float(occupancy) < 1.0 - 1e-6:
            return False
        species = getattr(site, "species", None)
        if species is not None and len(species) > 1:
            fractions = getattr(species, "values", None)
            if fractions is not None and len(fractions) > 1:
                return False
    return True


def guard_ordered(fmt: str, structure: Any) -> None:
    """Raise :class:`DisorderedStructureError` before the writer does it opaquely."""
    if fmt in ORDERED_ONLY and not structure_is_ordered(structure):
        raise DisorderedStructureError(fmt)


__all__ = ["ORDERED_ONLY", "DisorderedStructureError", "structure_is_ordered",
           "guard_ordered"]
