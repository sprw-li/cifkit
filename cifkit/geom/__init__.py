"""几何层：标准化 / 超胞 / 切面 / 真空 / 金属簇-SBU。

Owner: geom teammate. Public API (do not change without Lead):

    standardize(structure, *, target="conventional") -> Structure
    make_supercell(structure, reps) -> Structure
    make_slab(structure, hkl, *, slab_thickness=15.0, vacuum=15.0, termination=None)
        -> tuple[Structure, dict]
    set_vacuum(structure, vacuum, axis=2) -> tuple[Structure, float]
    extract_cluster(structure, *, mode="sbu") -> Structure
"""
from __future__ import annotations


def standardize(structure, *, target: str = "conventional"):
    raise NotImplementedError("geom.standardize not implemented yet")


def make_supercell(structure, reps):
    raise NotImplementedError("geom.make_supercell not implemented yet")


def make_slab(structure, hkl, *, slab_thickness: float = 15.0, vacuum: float = 15.0, termination=None):
    raise NotImplementedError("geom.make_slab not implemented yet")


def set_vacuum(structure, vacuum: float, axis: int = 2):
    raise NotImplementedError("geom.set_vacuum not implemented yet")


def extract_cluster(structure, *, mode: str = "sbu"):
    raise NotImplementedError("geom.extract_cluster not implemented yet")
