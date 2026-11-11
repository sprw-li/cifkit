"""Round 56c: a *measured* precision model instead of one flat tolerance.

The 320-structure sweep failed 5 structures on ``pdb``, with deviations up to
0.00509 Å.  Investigating showed the cause is not a writer bug:

* ``.pdb`` writes Cartesian coordinates with **3 decimals** -> <=0.0005 Å;
* but ``CRYST1`` stores the cell **angles with 2 decimals**, and a 0.005 deg error
  across a 46 Å cell displaces atoms by ``0.005 * pi/180 * 46 = 0.0040 Å``.

So the tolerance must depend on the format's stored precision *and* the cell size,
not be a single number.  This module states the model explicitly (each term traceable
to a measurement or a format spec) so the corpus results can be interpreted instead of
loosened until they pass.
"""
from __future__ import annotations

import math

#: format -> Cartesian coordinate precision (Å): how many decimals the file keeps
CARTESIAN_PRECISION: dict[str, float] = {
    "pdb": 0.0005,      # %8.3f
    "gromacs": 0.0005,  # .gro keeps 3 decimals
    "turbomole": 0.0005,
    "gaussian": 0.0005,
    "dmol": 0.0005,
    "mol": 0.0005,      # V2000: %10.4f -> 0.00005, kept conservative
    "sdf": 0.0005,
    "res": 0.0005,
}

#: formats whose *cell* is stored with reduced precision: (degrees, decimals)
ANGLE_PRECISION: dict[str, float] = {
    "pdb": 0.005,       # CRYST1 angles: %7.2f
}

#: extra head-room for writers that re-orient/reduce the cell (measured, not guessed)
DEFAULT_TOLERANCE = 1e-3

#: an angle rounding error acts through more than one axis on an oblique cell.
#: Measured: a 46.076 A rhombohedral (119.45 deg) cell came back with a 0.00509 A
#: deviation while the single-axis term predicts 0.00402 A -> ratio 1.27, so the
#: factor below (1.5) is a documented envelope, not a fit to one structure.
ANGLE_GEOMETRIC_FACTOR = 1.5


def format_tolerance(fmt: str, lattice=None) -> float:
    """Expected geometric error for ``fmt``, given the cell it must represent.

    ``tol = cartesian + angle_rounding * max_abc`` (nanometre-per-degree term), with a
    floor of :data:`DEFAULT_TOLERANCE` so an exact writer still has a numerical band.
    """
    base = CARTESIAN_PRECISION.get(fmt, DEFAULT_TOLERANCE)
    angle_deg = ANGLE_PRECISION.get(fmt)
    if angle_deg is None or lattice is None:
        return max(base, DEFAULT_TOLERANCE)
    try:
        max_abc = max(float(value) for value in lattice.abc)
    except Exception:  # noqa: BLE001
        return max(base, DEFAULT_TOLERANCE)
    angle_term = ANGLE_GEOMETRIC_FACTOR * math.radians(angle_deg) * max_abc
    return max(base + angle_term, DEFAULT_TOLERANCE)


__all__ = ["CARTESIAN_PRECISION", "ANGLE_PRECISION", "DEFAULT_TOLERANCE",
           "ANGLE_GEOMETRIC_FACTOR", "format_tolerance"]
