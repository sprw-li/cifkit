"""几何层：标准化 / 超胞 / 切面 / 真空 / 金属簇-SBU。

Owner: geom teammate. Public API (frozen in DESIGN.md §6 / §6f, do not change
without the Lead):

    standardize(structure, *, target="conventional") -> Structure
    make_supercell(structure, reps) -> Structure
    make_slab(structure, hkl, *, slab_thickness=15.0, vacuum=15.0,
              termination=None, reps=None, frame="slab") -> tuple[Structure, dict]
    set_vacuum(structure, vacuum, axis=2) -> tuple[Structure, float]
    extract_cluster(structure, *, mode="sbu") -> Structure

Implementation notes and known caveats live in ``docs/GEOM.md``.
"""
from __future__ import annotations

from cifkit.geom.cluster import extract_cluster
from cifkit.geom.standardize import standardize
from cifkit.geom.supercell import make_supercell
from cifkit.geom.surface import make_slab
from cifkit.geom.vacuum import set_vacuum

__all__ = [
    "standardize",
    "make_supercell",
    "make_slab",
    "set_vacuum",
    "extract_cluster",
]
