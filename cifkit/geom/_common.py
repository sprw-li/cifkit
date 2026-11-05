"""Internal helpers shared by the geometry layer.

Not part of the frozen public API (see :mod:`cifkit.geom`).

The helpers here deliberately avoid ``pymatgen``'s high level neighbours for
the vacuum measurement: a slab produced by ``SlabGenerator`` may have a
*c*-axis that is **not** perpendicular to the surface plane (LLL reduction
mixes the basis vectors), so the vacuum gap must be measured with cartesian
projections onto the surface normal and with true periodic images.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Iterable, Sequence

import numpy as np
from pymatgen.core import Lattice, Structure
from scipy.spatial import cKDTree

try:  # ase carries a compact covalent-radius table; pymatgen's Element does not
    from ase.data import atomic_numbers as _ASE_Z
    from ase.data import covalent_radii as _ASE_RCOV
except Exception:  # pragma: no cover - ase is a hard dependency, but stay safe
    _ASE_Z = {}
    _ASE_RCOV = None

BOND_SCALE = 1.2  # bond if d < scale * (rcov_i + rcov_j)
BOND_CAP = 3.2  # Å, hard upper bound for any considered bond
BOND_FLOOR = 0.55  # Å, hard lower bound for any considered bond
DEFAULT_RCOV = 0.8


# ---------------------------------------------------------------------------
# species helpers
# ---------------------------------------------------------------------------
def element_symbol(site) -> str:
    """Dominant element symbol of a (possibly disordered) site."""
    try:
        comp = site.species
        items = list(comp.items())
        if items:
            specie, _occ = max(items, key=lambda kv: kv[1])
            return getattr(specie, "symbol", None) or str(specie)
    except Exception:  # noqa: BLE001 - fall through to species_string
        pass
    text = str(getattr(site, "species_string", ""))
    return "".join(ch for ch in text if ch.isalpha()) or "X"


def site_symbols(structure: Structure) -> list[str]:
    return [element_symbol(s) for s in structure]


def covalent_radius(symbol: str) -> float:
    if _ASE_RCOV is None:  # pragma: no cover
        return DEFAULT_RCOV
    try:
        z = _ASE_Z[symbol]
        r = float(_ASE_RCOV[z])
    except Exception:  # noqa: BLE001
        return DEFAULT_RCOV
    return r if r > 0 else DEFAULT_RCOV


def bond_cutoff(sym1: str, sym2: str, scale: float = BOND_SCALE, cap: float = BOND_CAP) -> float:
    """Distance below which two elements are considered bonded (Å)."""
    d = (covalent_radius(sym1) + covalent_radius(sym2)) * scale
    return float(min(max(d, BOND_FLOOR), cap))


# ---------------------------------------------------------------------------
# structure rebuilding / de-duplication
# ---------------------------------------------------------------------------
def rebuild_structure(
    structure: Structure,
    lattice: Lattice,
    frac_coords: Sequence[Sequence[float]],
    *,
    wrap: bool = True,
) -> Structure:
    """Build a new Structure with the same species/site-properties but a new cell."""
    keys: set[str] = set()
    for site in structure:
        keys.update(site.properties.keys())
    props = {k: [site.properties.get(k) for site in structure] for k in sorted(keys)}
    frac = np.asarray(frac_coords, dtype=float).reshape((-1, 3))
    if wrap:
        frac = frac - np.floor(frac)
    return Structure(
        lattice,
        [site.species for site in structure],
        frac,
        site_properties=props or None,
        charge=structure.charge,
        validate_proximity=False,
    )


def dedupe_sites(structure: Structure, tol: float = 0.05) -> tuple[Structure, int]:
    """Drop sites that sit on top of an earlier site of the *same* element.

    Returns ``(structure, removed_count)``. Different elements that are almost
    on top of each other are kept (that is a real problem reported by
    :mod:`cifkit.validate`, not something to hide here).
    """
    n = len(structure)
    if n < 2:
        return structure, 0
    tol = float(max(tol, 1e-6))
    syms = site_symbols(structure)
    keep = np.ones(n, dtype=bool)
    if n <= 2500:
        dm = np.asarray(structure.distance_matrix, dtype=float)
        for i in range(n):
            if not keep[i]:
                continue
            close = np.nonzero((dm[i] < tol) & (np.arange(n) > i))[0]
            for j in close:
                if keep[j] and syms[j] == syms[i]:
                    keep[j] = False
    else:  # pragma: no cover - large structures use a neighbour list
        neighbours = structure.get_all_neighbors(tol)
        for i, nbs in enumerate(neighbours):
            if not keep[i]:
                continue
            for nb in nbs:
                j = int(nb.index)
                if j > i and keep[j] and syms[j] == syms[i] and float(nb.nn_distance) < tol:
                    keep[j] = False
    removed = int(n - keep.sum())
    if removed == 0:
        return structure, 0
    keep_idx = np.nonzero(keep)[0]
    return structure[keep_idx], removed  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# lattice geometry / vacuum
# ---------------------------------------------------------------------------
def axis_geometry(lattice: Lattice, axis: int = 2) -> tuple[np.ndarray, float, tuple[int, int]]:
    """Unit normal of the plane spanned by the two other vectors + interplanar spacing.

    For ``axis=2`` the normal is ``a x b`` (the slab surface normal) and the
    spacing is ``c . n`` (``|c|`` only when the cell is orthogonal in c).
    """
    axis = int(axis) % 3
    mat = np.asarray(lattice.matrix, dtype=float)
    others = tuple(k for k in range(3) if k != axis)
    n = np.cross(mat[others[0]], mat[others[1]])
    norm = float(np.linalg.norm(n))
    if norm < 1e-10:  # pragma: no cover - degenerate cell
        raise ValueError("degenerate lattice: the two in-plane vectors are parallel")
    n = n / norm
    d_perp = abs(float(np.dot(mat[axis], n)))
    return n, d_perp, others  # type: ignore[return-value]


def along_normal(structure: Structure, axis: int = 2) -> tuple[np.ndarray, float, np.ndarray]:
    """Return ``(unit normal, interplanar spacing, per-atom height along normal)``."""
    n, d_perp, _ = axis_geometry(structure.lattice, axis=axis)
    cart = np.asarray(structure.cart_coords, dtype=float)
    height = cart @ n
    return n, d_perp, height


def min_image_gap(structure: Structure, axis: int = 2) -> float:
    """Smallest cartesian distance between an atom and a periodic image across the boundary.

    This is a **minimum periodic-image distance**, not the vacuum-layer thickness:
    for a slab whose two surfaces are laterally offset the closest cross-boundary
    atom pair can be farther apart than the perpendicular gap. Use
    :func:`vacuum_metrics` (``vacuum_perp``) for the vacuum-layer thickness and
    this value only as the "no atom is closer than this"-style bound.
    """
    if len(structure) < 1:
        raise ValueError("vacuum cannot be measured on an empty structure")
    cart = np.asarray(structure.cart_coords, dtype=float)
    axis_vec = np.asarray(structure.lattice.matrix, dtype=float)[int(axis) % 3]
    tree = cKDTree(cart)
    gap_up = float(tree.query(cart + axis_vec, k=1)[0].min())
    gap_down = float(tree.query(cart - axis_vec, k=1)[0].min())
    return min(gap_up, gap_down)


def vacuum_metrics(structure: Structure, axis: int = 2) -> dict[str, Any]:
    """Slab thickness + vacuum along the axis normal (cartesian aware).

    Two distinct numbers are reported (see ``docs/GEOM.md`` §5):

    ``vacuum_perp`` (also exposed as ``vacuum``, the main/report quantity)
        **Perpendicular vacuum-layer thickness** ``d_perp - thickness`` where
        ``d_perp = c . n`` is the interplanar spacing and ``thickness`` the atom
        extent along the surface normal. This is the standard surface-science
        definition and is exactly the target value after
        :func:`cifkit.geom.set_vacuum`.
    ``min_image_distance``
        Smallest 3-D cartesian distance between an atom and any periodic image
        across the boundary. For a slab with laterally offset termination
        surfaces this is *larger* than ``vacuum_perp``: it is a safe lower bound
        ("atoms never come closer than this across the boundary"), not the
        vacuum-layer thickness.
    """
    if len(structure) == 0:
        raise ValueError("cannot measure vacuum of an empty structure")
    n, d_perp, height = along_normal(structure, axis=axis)
    thickness = float(height.max() - height.min())
    frac_span = (thickness / d_perp) if d_perp > 0 else 1.0
    vacuum_perp = float(d_perp - thickness)
    return {
        "axis": int(axis) % 3,
        "normal": [float(x) for x in n],
        "d_perp": float(d_perp),
        "thickness": thickness,
        "frac_span": float(frac_span),
        # main quantity used by reports / checks / pipeline "measured vacuum"
        "vacuum_perp": vacuum_perp,
        "vacuum": vacuum_perp,
        # honest cross-boundary lower bound (never smaller than vacuum_perp)
        "min_image_distance": float(min_image_gap(structure, axis=axis)),
        # kept for backwards compatibility: same as vacuum_perp
        "gap_geometric": vacuum_perp,
    }


def gaps_all_axes(structure: Structure) -> list[float]:
    """Minimum periodic-image distance measured along each of the three axes.

    This is the ``min_image_distance`` notion (a safe lower bound for the vacuum
    in that direction), used for slab/cluster classification; it is not the
    perpendicular vacuum-layer thickness reported for slabs.
    """
    out: list[float] = []
    for axis in range(3):
        try:
            out.append(min_image_gap(structure, axis=axis))
        except Exception:  # noqa: BLE001
            out.append(float("nan"))
    return out


# ---------------------------------------------------------------------------
# bonding / coordination numbers
# ---------------------------------------------------------------------------
def coordination_numbers(
    structure: Structure,
    *,
    scale: float = BOND_SCALE,
    cap: float = BOND_CAP,
) -> np.ndarray:
    """Periodic coordination number of every site using covalent-radius cutoffs."""
    syms = site_symbols(structure)
    cn = np.zeros(len(structure), dtype=int)
    for i, neighbours in enumerate(structure.get_all_neighbors(cap)):
        si = syms[i]
        count = 0
        for nb in neighbours:
            sj = str(getattr(nb, "species_string", "")) or element_symbol(nb)
            sj = "".join(ch for ch in sj if ch.isalpha()) or sj
            if float(nb.nn_distance) <= bond_cutoff(si, sj, scale=scale, cap=cap):
                count += 1
        cn[i] = count
    return cn


def median_coordination_by_element(
    structure: Structure,
    cn: np.ndarray | None = None,
    mask: np.ndarray | None = None,
) -> dict[str, float]:
    """Median coordination number per element (optionally restricted by ``mask``)."""
    if cn is None:
        cn = coordination_numbers(structure)
    syms = site_symbols(structure)
    groups: dict[str, list[int]] = {}
    for i, el in enumerate(syms):
        if mask is not None and not bool(mask[i]):
            continue
        groups.setdefault(el, []).append(int(cn[i]))
    return {el: float(np.median(vals)) for el, vals in groups.items() if vals}


def element_counts(structure: Structure) -> dict[str, int]:
    return dict(Counter(site_symbols(structure)))


def is_slab_like(structure: Structure, *, threshold: float = 6.0) -> bool:
    """True when the structure has a vacuum gap along *c* like a slab/film."""
    if len(structure) < 2:
        return False
    try:
        return bool(vacuum_metrics(structure, axis=2)["vacuum"] > threshold)
    except Exception:  # noqa: BLE001
        return False


def is_cluster_like(structure: Structure, *, threshold: float = 6.0) -> bool:
    """True when the structure is isolated in all three directions (a cluster)."""
    if len(structure) < 2:
        return True
    gaps = gaps_all_axes(structure)
    return all(g > threshold for g in gaps if not math.isnan(g))


def attach_geom_info(structure: Structure, info: dict[str, Any]) -> Structure:
    """Best-effort: stash step metadata on the returned structure object."""
    try:  # pragma: no cover - pymatgen Structure allows attributes
        structure._cifkit_geom_info = dict(info)
    except Exception:  # noqa: BLE001
        pass
    return structure
