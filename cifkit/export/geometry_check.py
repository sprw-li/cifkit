"""Round 44: raise the third-party read-back from *atom count* to *geometry*.

``verify_formats`` used to assert only ``len(readback) == len(structure)``.  A file
could therefore pass while having the wrong lattice, the wrong positions, or a
different species assignment.  This module compares the actual geometry with
pymatgen's ``StructureMatcher`` and reports the worst deviation.

Formats that cannot carry periodicity (PDB, SDF, MOL, ...) are compared on
**positions only** — and that limitation is reported, not hidden.
"""
from __future__ import annotations

from dataclasses import dataclass

#: formats whose container has no periodic cell; positions still must match
NON_PERIODIC = {"pdb", "sdf", "mol", "xyz", "res", "turbomole", "dmol", "gaussian",
                "orca", "nwchem", "siesta", "cp2k", "abacus", "castep", "qe", "vasp"}

#: formats with documented precision loss (3 decimals in .gro, etc.)
LOOSE_TOLERANCE = {"gromacs": 1e-2, "sdf": 1e-3, "mol": 1e-3, "pdb": 1e-3,
                   "dmol": 1e-3, "gaussian": 1e-3}


@dataclass
class GeometryCheck:
    ok: bool
    periodic: bool
    max_deviation: float | None
    tolerance: float
    detail: str = ""

    def as_dict(self) -> dict:
        return {"ok": self.ok, "periodic": self.periodic,
                "max_deviation_A": self.max_deviation, "tolerance_A": self.tolerance,
                "detail": self.detail}


def _to_pymatgen(back):
    """Normalise a read-back object to a pymatgen Structure (or ``None``)."""
    from pymatgen.core import Lattice, Structure

    if back is None:
        return None
    if isinstance(back, Structure):
        return back
    if hasattr(back, "get_scaled_positions"):            # ase.Atoms
        import numpy as np

        cell = np.array(back.cell)
        coords = back.get_positions()
        symbols = back.get_chemical_symbols()
        if cell.shape == (3, 3) and abs(np.linalg.det(cell)) > 1e-8:
            return Structure(Lattice(cell), symbols, coords, coords_are_cartesian=True)
        # no usable cell: a big box keeps the distances identical to a cluster
        span = float(np.ptp(coords, axis=0).max()) + 10.0
        return Structure(Lattice.cubic(span), symbols, coords, coords_are_cartesian=True)
    return None


def _has_cell(structure) -> bool:
    import numpy as np

    try:
        return abs(float(np.linalg.det(structure.lattice.matrix))) > 1e-6
    except Exception:  # noqa: BLE001
        return False


def _cell_matches(other, structure, rtol: float = 0.02, atol: float = 0.25) -> bool:
    """Does the read-back reproduce the *source* lattice (not just any lattice)?

    ASE invents a bounding-box cell for containers without one (xyz, mol, sdf,
    turbomole, lammps-data), so "has a cell" cannot decide the comparison mode.
    """
    import numpy as np

    if not (_has_cell(other) and _has_cell(structure)):
        return False
    try:
        left = sorted(float(x) for x in other.lattice.parameters)
        right = sorted(float(x) for x in structure.lattice.parameters)
    except Exception:  # noqa: BLE001
        return False
    return all(abs(a - b) <= max(atol, rtol * abs(b)) for a, b in zip(left, right))


def _distance_fingerprint(structure) -> list[float]:
    """Sorted pairwise distances: a lattice-free geometric signature."""
    import numpy as np

    cart = structure.cart_coords
    diff = cart[:, None, :] - cart[None, :, :]
    distances = np.sqrt((diff ** 2).sum(-1))
    iu = np.triu_indices(len(cart), k=1)
    return sorted(float(value) for value in distances[iu])


def compare(structure, back, fmt: str, *, tolerance: float | None = None) -> GeometryCheck:
    """Compare ``back`` with the exported ``structure``.

    Periodic read-backs go through ``StructureMatcher`` (order-independent);
    lattice-free ones use the sorted pairwise-distance fingerprint.
    """
    from pymatgen.analysis.structure_matcher import StructureMatcher

    target = tolerance if tolerance is not None else LOOSE_TOLERANCE.get(fmt, 1e-3)
    other = _to_pymatgen(back)
    if other is None:
        return GeometryCheck(False, False, None, target,
                             f"unsupported read-back type {type(back).__name__}")
    if len(other) != len(structure):
        return GeometryCheck(False, _has_cell(other), None, target,
                             f"atom count {len(other)} != {len(structure)}")

    if _cell_matches(other, structure):
        matcher = StructureMatcher(ltol=max(target, 1e-4), stol=max(target, 1e-4),
                                   angle_tol=5.0, primitive_cell=False, scale=False)
        try:
            rms = matcher.get_rms_dist(other, structure)
        except Exception as exc:  # noqa: BLE001
            return GeometryCheck(False, True, None, target,
                                 f"matcher error: {type(exc).__name__}: {exc}")
        if rms is None:
            return GeometryCheck(False, True, None, target,
                                 f"no matching geometry within {target} A")
        _rms, max_distance = rms
        ok = float(max_distance) <= max(target, 1e-6)
        return GeometryCheck(ok, True, float(max_distance), target,
                             "ok" if ok else f"max displacement {max_distance:.4f} A")

    # lattice-free: compare the distance fingerprints
    try:
        left = _distance_fingerprint(other)
        right = _distance_fingerprint(structure)
    except Exception as exc:  # noqa: BLE001
        return GeometryCheck(False, False, None, target,
                             f"fingerprint error: {type(exc).__name__}: {exc}")
    worst = max((abs(a - b) for a, b in zip(left, right)), default=0.0)
    ok = worst <= max(target, 1e-6)
    return GeometryCheck(ok, False, worst, target,
                         "ok (lattice-free positions)" if ok
                         else f"distance deviation {worst:.4f} A (no lattice in container)")
