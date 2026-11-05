"""Surface-plane selection: known-prototype map + planar atomic density fallback.

``choose_densest_plane`` first tries the textbook rule for the common metallic
prototypes (fcc->(111), bcc->(110), hcp->(0001), sc->(100), diamond->(111)).
Everything else (alpha-Mn, alpha-Ga, alpha-U, beta-Sn, bct In/Pa, R-3m Hg/Bi/Sm)
is decided by the planar atomic density of the low-index planes, as requested.

Planar density
--------------
For a plane family (hkl) (always reduced to coprime indices, canonical sign) the
normal is ``n`` and the interplanar distance is ``d``:

* build the 2D lattice of the plane from the two shortest independent lattice
  vectors ``b1, b2`` with ``(i,j,k)·(h,k,l) = 0``; ``A2D = |b1 x b2|``;
* group the atoms into planes by ``(r·n) mod d`` (tolerance 0.30 Å);
* for each plane group, wrap the projected coordinates into the ``b1, b2`` cell
  and deduplicate them (in-plane tolerance 0.25 Å) -> ``Nk`` atoms per 2D cell;
* ``rho(hkl) = max_k Nk / A2D``  [atoms / Å²].

Because the layers are grouped before deduplication, a two-atom-basis layer
(e.g. the A/B sublattices of a corrugated plane) is counted correctly, and the
known textbook values are reproduced: fcc(111) ``4/(sqrt(3)a^2)``,
bcc(110) ``2/(sqrt(2)a^2)``, hcp(0001) ``2/(sqrt(3)a^2)``.
"""
from __future__ import annotations

import itertools
import math
from functools import lru_cache

import numpy as np
from pymatgen.core import Structure

#: textbook densest plane by (spacegroup number, atoms in the conventional cell)
KNOWN_PLANES: dict[tuple[int, int], tuple[int, int, int]] = {
    (225, 4): (1, 1, 1),  # fcc, A1
    (229, 2): (1, 1, 0),  # bcc, A2
    (194, 2): (0, 0, 1),  # hcp, A3
    (194, 4): (0, 0, 1),  # dhcp, hP4
    (221, 1): (1, 0, 0),  # simple cubic
    (227, 8): (1, 1, 1),  # diamond, A4
}
#: human-readable reason for the known entries
KNOWN_LABEL = {
    (225, 4): "fcc close-packed (111)",
    (229, 2): "bcc close-packed (110)",
    (194, 2): "hcp basal plane (0001)",
    (194, 4): "dhcp basal plane (0001)",
    (221, 1): "simple-cubic (100)",
    (227, 8): "diamond (111)",
}

#: tolerance for grouping atoms into planes (Å, along the normal)
LAYER_TOL = 0.30
#: tolerance for deduplicating projected coordinates (Å, in plane)
PROJ_TOL = 0.25


@lru_cache(maxsize=1)
def _int_grid(limit: int = 6) -> np.ndarray:
    """All integer triples in [-limit, limit]^3 as an (N,3) array (cached)."""
    vals = range(-limit, limit + 1)
    return np.array(list(itertools.product(vals, repeat=3)), dtype=int)


def canonical_hkl(hkl) -> tuple[int, int, int]:
    """Reduce to coprime indices with a canonical sign (first non-zero > 0)."""
    triple = [int(v) for v in hkl]
    if all(v == 0 for v in triple):
        raise ValueError("hkl cannot be (0,0,0)")
    g = math.gcd(math.gcd(abs(triple[0]), abs(triple[1])), abs(triple[2]))
    if g > 1:
        triple = [v // g for v in triple]
    for v in triple:
        if v != 0:
            if v < 0:
                triple = [-x for x in triple]
            break
    return tuple(triple)  # type: ignore[return-value]


@lru_cache(maxsize=1)
def candidate_hkls() -> tuple[tuple[int, int, int], ...]:
    """Unique low-index plane families (coprime, canonical sign, max index 2)."""
    seen: dict[tuple[int, int, int], None] = {}
    for hkl in itertools.product(range(-2, 3), repeat=3):
        if not any(hkl):
            continue
        seen.setdefault(canonical_hkl(hkl), None)
    return tuple(seen)


def _in_plane_basis(lattice, hkl: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Two shortest independent lattice vectors in the (hkl) plane + the normal."""
    hkl_arr = np.asarray(hkl, dtype=int)
    recip = lattice.reciprocal_lattice.matrix  # rows a*, b*, c* (2*pi included)
    g = hkl_arr @ recip
    norm = np.linalg.norm(g)
    if norm == 0:
        raise ValueError(f"invalid hkl {hkl}")
    n = g / norm
    ints = _int_grid()
    mask = (ints @ hkl_arr) == 0
    mask &= np.any(ints != 0, axis=1)
    sel = ints[mask]
    cart = sel @ np.asarray(lattice.matrix, dtype=float)
    lengths = np.linalg.norm(cart, axis=1)
    order = np.argsort(lengths)
    b1 = cart[order[0]]
    b2 = None
    for idx in order[1:]:
        vec = cart[idx]
        cross = np.cross(b1, vec)
        if np.linalg.norm(cross) > 1e-4 * max(1e-12, np.linalg.norm(b1) * np.linalg.norm(vec)):
            b2 = vec
            break
    if b2 is None:
        raise ValueError(f"in-plane lattice of {hkl} is one-dimensional")
    return b1, b2, n


def planar_density(structure: Structure, hkl) -> dict:
    """Densest-layer planar atom density of the ``hkl`` family, atoms/Å²."""
    hkl = canonical_hkl(hkl)
    lattice = structure.lattice
    b1, b2, n = _in_plane_basis(lattice, hkl)
    a2d = float(np.linalg.norm(np.cross(b1, b2)))
    d = float(
        2.0
        * math.pi
        / np.linalg.norm(np.asarray(hkl, dtype=int) @ lattice.reciprocal_lattice.matrix)
    )

    cart = np.asarray(structure.cart_coords, dtype=float)
    height = cart @ n
    phase = (height / d) % 1.0

    # circular clustering of the phases (the first and last group may wrap)
    order = np.argsort(phase)
    ph = phase[order]
    tol = LAYER_TOL / d
    groups: list[list[int]] = []
    start = 0
    for i in range(1, len(ph)):
        if ph[i] - ph[i - 1] > tol:
            groups.append(order[start:i].tolist())
            start = i
    groups.append(order[start:].tolist())
    if len(groups) > 1 and (1.0 - ph[-1]) + ph[0] <= tol:  # merge wrap-around
        groups[0] = groups[-1] + groups[0]
        groups.pop()

    # in-plane orthonormal basis and the (b1,b2) -> cartesian 2x2 matrix
    e1 = b1 / np.linalg.norm(b1)
    e2 = np.cross(n, e1)
    e2 /= np.linalg.norm(e2)
    mat = np.array([[b1 @ e1, b2 @ e1], [0.0, b2 @ e2]])
    mat_inv = np.linalg.inv(mat)
    scale = np.array([np.linalg.norm(b1), np.linalg.norm(b2)])  # Å per frac unit

    best_n = 0
    best_group: list[int] = []
    for group in groups:
        pts = cart[group]
        plane_xy = np.column_stack((pts @ e1, pts @ e2))
        frac = (plane_xy @ mat_inv.T) % 1.0
        grid = np.round((frac * scale) / PROJ_TOL).astype(int)
        n_atoms = int(len(np.unique(grid, axis=0)))
        if n_atoms > best_n:
            best_n = n_atoms
            best_group = group

    return {
        "rho": best_n / a2d,
        "hkl": hkl,
        "a2d": a2d,
        "d": d,
        "n_atoms_per_cell": best_n,
        "n_layers_distinct": len(groups),
        "layer_sizes": sorted({len(g) for g in groups}),
    }


def periodic_min_distance(structure: Structure, rmax: float = 6.0) -> float:
    """Shortest interatomic distance including periodic images (bulk NN distance).

    ``structure.distance_matrix`` only covers atom pairs *inside* one cell, so it
    misses shorter lattice translations (e.g. bct In: intra-cell 3.371 Å but the
    true nearest neighbour is a = 3.246 Å).
    """
    try:
        neighbours = structure.get_all_neighbors(rmax)
        distances = [
            float(nb.nn_distance)
            for site_neighbours in neighbours
            for nb in site_neighbours
            if float(nb.nn_distance) > 1e-6
        ]
        if distances:
            return min(distances)
    except Exception:  # noqa: BLE001 - fall back to the in-cell matrix
        pass
    dm = np.asarray(structure.distance_matrix, dtype=float)
    np.fill_diagonal(dm, np.inf)
    return float(dm.min())


def choose_densest_plane(structure: Structure, sg_number: int, natoms_conv: int) -> dict:
    """Pick the densest plane; prototype rule first, planar-density fallback second."""
    key = (int(sg_number), int(natoms_conv))
    if key in KNOWN_PLANES:
        hkl = KNOWN_PLANES[key]
        dens = planar_density(structure, hkl)
        return {
            "hkl": hkl,
            "method": "prototype_rule",
            "rule": KNOWN_LABEL[key],
            "rho": dens["rho"],
            "top3": [(hkl, dens["rho"])],
            "plane_confidence": "textbook",
            "n_layers_distinct": dens["n_layers_distinct"],
        }

    scored = []
    for hkl in candidate_hkls():
        try:
            dens = planar_density(structure, hkl)
        except Exception:  # noqa: BLE001 - skip degenerate plane families
            continue
        scored.append((dens["rho"], hkl))
    if not scored:
        raise RuntimeError("planar-density fallback found no usable plane")
    scored.sort(key=lambda t: (-t[0], sum(abs(v) for v in t[1]), t[1]))
    best_rho, best_hkl = scored[0]
    best = planar_density(structure, best_hkl)
    # Sanity bound: in a single atomic plane no two atoms can be closer than the
    # bulk nearest-neighbour distance, so the maximum possible planar density is
    # the triangular-packing value 2/(sqrt(3) d_nn^2).  A larger computed rho
    # means the "plane" is corrugated and the layer group could not be resolved
    # -> flag the result as low confidence.
    d_nn = periodic_min_distance(structure)
    max_rho = 2.0 / (np.sqrt(3.0) * d_nn * d_nn)
    if best_rho > 1.02 * max_rho:
        confidence = "low"
    else:
        confidence = "computed"
    return {
        "hkl": best_hkl,
        "method": "planar_density",
        "rule": (
            "max planar atom density over low-index planes: "
            + ", ".join(f"({h[0]}{h[1]}{h[2]}) {r:.4f} atoms/A^2" for r, h in scored[:3])
            + f" (atoms/A^2; single-plane packing limit {max_rho:.4f})"
        ),
        "rho": best_rho,
        "top3": [(h, r) for r, h in scored[:3]],
        "plane_confidence": confidence,
        "n_layers_distinct": best["n_layers_distinct"],
        "max_possible_rho": max_rho,
    }
