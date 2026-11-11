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

#: formats with documented precision loss (kept for callers that pass a fixed number)
LOOSE_TOLERANCE = {"gromacs": 1e-2, "sdf": 1e-3, "mol": 1e-3, "pdb": 1e-3,
                   "dmol": 1e-3, "gaussian": 1e-3}


def default_tolerance(fmt: str, structure=None) -> float:
    """Tolerance from the *format's stored precision* and the cell size (round 56).

    A flat 1e-3 was wrong for ``.pdb``: it keeps coordinates to 3 decimals but cell
    angles to only 2, which displaces atoms by ~0.004 Å in a 46 Å cell.  See
    :mod:`cifkit.export.precision_model`.
    """
    from cifkit.export.precision_model import format_tolerance

    lattice = getattr(structure, "lattice", None) if structure is not None else None
    return format_tolerance(fmt, lattice)


def _tolerance_for(fmt: str, structure, explicit: float | None) -> float:
    if explicit is not None:
        return explicit
    # an explicitly configured LOOSE_TOLERANCE entry wins (backwards compatible), but
    # the precision model raises it further when the cell is large
    from cifkit.export.precision_model import format_tolerance

    modelled = format_tolerance(fmt, getattr(structure, "lattice", None))
    return max(LOOSE_TOLERANCE.get(fmt, 0.0), modelled)


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



def _composition(structure) -> list[str]:
    try:
        return sorted(str(site.species_string) for site in structure)
    except Exception:  # noqa: BLE001
        return []


def _fingerprint_check(other, structure, target: float, *, reason: str) -> GeometryCheck:
    """Compare sorted pairwise distances (works when the cell is re-oriented).

    Distances alone cannot see a *substitution*: swapping one carbon for nitrogen keeps
    every distance identical.  The element composition is therefore checked first, so
    the more forgiving route stays strict about chemistry.
    """
    left_composition, right_composition = _composition(other), _composition(structure)
    if left_composition != right_composition:
        differing = sum(1 for a, b in zip(left_composition, right_composition) if a != b)
        return GeometryCheck(False, False, None, target,
                             f"element composition differs ({differing} site(s)); "
                             f"distance-only comparison cannot be used")
    try:
        left = _distance_fingerprint(other)
        right = _distance_fingerprint(structure)
    except Exception as exc:  # noqa: BLE001
        return GeometryCheck(False, False, None, target,
                             f"fingerprint error: {type(exc).__name__}: {exc}")
    worst = max((abs(a - b) for a, b in zip(left, right)), default=0.0)
    ok = worst <= max(target, 1e-6)
    detail = ("ok (lattice-free positions)" if ok
              else f"distance deviation {worst:.4f} A (no lattice in container)")
    return GeometryCheck(ok, False, worst, target,
                         detail if ok else f"{detail}; periodic route: {reason}")

def compare(structure, back, fmt: str, *, tolerance: float | None = None) -> GeometryCheck:
    """Compare ``back`` with the exported ``structure``.

    Periodic read-backs go through ``StructureMatcher`` (order-independent);
    lattice-free ones use the sorted pairwise-distance fingerprint.
    """
    from pymatgen.analysis.structure_matcher import StructureMatcher

    target = _tolerance_for(fmt, structure, tolerance)
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
        rms = None
        try:
            rms = matcher.get_rms_dist(other, structure)
        except Exception as exc:  # noqa: BLE001
            rms = None
            matcher_error = f"{type(exc).__name__}: {exc}"
        else:
            matcher_error = ""
        if rms is not None:
            _rms, max_distance = rms
            ok = float(max_distance) <= max(target, 1e-6)
            return GeometryCheck(ok, True, float(max_distance), target,
                                 "ok" if ok else f"max displacement {max_distance:.4f} A")
        # round 56e: the periodic route can fail even when the coordinates are
        # identical, because the reader may rebuild the box in another orientation.
        # Fall back to the distance fingerprint instead of reporting a false negative.
        fallback = _fingerprint_check(other, structure, target,
                                      reason=matcher_error or "periodic match failed")
        if fallback.ok:
            return fallback
        return GeometryCheck(False, True, fallback.max_deviation, target,
                             f"periodic and lattice-free comparison both failed "
                             f"({fallback.detail})")

    # lattice-free: compare the distance fingerprints
    return _fingerprint_check(other, structure, target, reason="container has no cell")
