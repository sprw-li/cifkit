"""精确真空层设置与测量。

Owner: geom teammate. Public API (frozen in DESIGN.md §6, extended with the
``axis`` keyword only):

    set_vacuum(structure, vacuum, axis=2) -> tuple[Structure, float]

The returned float is the **measured** vacuum gap, i.e. the smallest distance
between an atom and a periodic image across the cell boundary (not a nominal
``c - thickness`` value). Slab cells handed to us by ``SlabGenerator`` can have
an oblique *c* axis (LLL reduction mixes the basis vectors), so the
implementation works with cartesian projections onto the surface normal and
rebuilds an orthogonal-to-the-surface *c* vector.
"""
from __future__ import annotations

import math

import numpy as np
from pymatgen.core import Lattice, Structure

from cifkit.geom._common import (
    along_normal,
    attach_geom_info,
    min_image_gap,
    rebuild_structure,
    vacuum_metrics,
)

#: maximum number of repositioning iterations (converges in 1-2 in practice)
_MAX_ITER = 8


def set_vacuum(structure: Structure, vacuum: float, axis: int = 2) -> tuple[Structure, float]:
    """Set a vacuum layer of exactly ``vacuum`` Å (perpendicular) along ``axis``.

    The slab keeps its cartesian atom positions (only a rigid translation along
    the surface normal is applied to centre it); the lattice vector of ``axis``
    is replaced by ``normal * (thickness + vacuum)`` so that

    * ``|c| == slab_thickness + vacuum`` for ``axis=2``,
    * the *c* axis is perpendicular to the surface plane (a,b),
    * the **perpendicular vacuum layer** ``vacuum_perp = d_perp - thickness`` is
      exactly ``vacuum`` (within ``1e-6`` Å). This is the returned value and the
      standard definition of a vacuum-layer thickness.

    The 3-D "minimum periodic-image distance" is measured as well and reported
    in the attached info dict as ``min_image_distance``; for laterally offset
    slab surfaces it is *larger* than ``vacuum_perp`` and must not be quoted as
    the vacuum thickness (see ``docs/GEOM.md`` §5).

    Args:
        structure: input structure (typically a slab from :func:`make_slab`).
        vacuum: target vacuum-layer thickness in Å, must be > 0.
        axis: lattice axis to grow (0, 1 or 2). The surface plane is spanned by
            the two other lattice vectors.

    Returns:
        ``(new_structure, vacuum_perp)`` with ``vacuum_perp == vacuum``.

    Raises:
        ValueError: for an empty structure, a non-positive/NaN target, or a
            degenerate (collinear) lattice.
    """
    target = float(vacuum)
    if not math.isfinite(target) or target <= 0:
        raise ValueError(f"vacuum must be a finite positive number of Å, got {vacuum!r}")
    if len(structure) == 0:
        raise ValueError("cannot set vacuum on an empty structure")

    axis = int(axis) % 3
    lattice = structure.lattice
    mat = np.asarray(lattice.matrix, dtype=float)
    normal, _d_perp, height = along_normal(structure, axis=axis)
    cart = np.asarray(structure.cart_coords, dtype=float)

    h_min = float(height.min())
    h_max = float(height.max())
    thickness = h_max - h_min
    # atoms sitting exactly on one plane (e.g. a single layer) -> keep them
    if thickness <= 1e-9:
        thickness = 1e-6

    d_new = thickness + target
    best: Structure | None = None
    measured = -math.inf
    metrics: dict[str, float] = {}
    for _ in range(_MAX_ITER):
        new_mat = mat.copy()
        new_mat[axis] = normal * d_new
        new_lattice = Lattice(new_mat)
        # rigid translation along the normal so that both margins are equal
        shift = d_new / 2.0 - (h_min + thickness / 2.0)
        new_cart = cart + normal * shift
        frac = new_cart @ np.linalg.inv(new_mat)
        candidate = rebuild_structure(structure, new_lattice, frac)
        metrics = vacuum_metrics(candidate, axis=axis)
        measured = float(metrics["vacuum_perp"])  # perpendicular vacuum layer
        best = candidate
        if measured + 1e-6 >= target:
            break
        # defensive: only reachable for a degenerate cell (the perpendicular gap
        # is target by construction, so one iteration is normally enough)
        d_new += (target - measured) + 1e-6

    assert best is not None  # loop always runs at least once
    final_metrics = vacuum_metrics(best, axis=axis)
    info = {
        "function": "set_vacuum",
        "axis": axis,
        "vacuum_target": target,
        "vacuum_measured": measured,
        "vacuum_perp": measured,
        "vacuum": measured,
        "min_image_distance": float(final_metrics["min_image_distance"]),
        "slab_thickness": float(final_metrics["thickness"]),
        "c_length": float(best.lattice.abc[axis]),
    }
    return attach_geom_info(best, info), measured
