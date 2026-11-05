"""金属簇 / SBU 提取（有限团簇，正确处理周期像）。

Owner: geom teammate. Public API (DESIGN.md §6):

    extract_cluster(structure, *, mode="sbu") -> Structure

Modes
-----
``sbu``
    Metal cluster (metals connected to each other by metal-metal bonds) plus the
    *complete* organic ligands that are bonded to those metals: the ligand
    fragment is grown through covalent bonds while only ever adding non-metal
    atoms, so it never walks into the neighbouring metal node.
``metal_cluster``
    Metal cluster + its first coordination shell (the atoms directly bonded to
    the metals).
``core``
    Only the metal atoms forming the connected metal cluster (inorganic core).

The returned object is a finite cluster: it is placed in an orthorhombic box
with :data:`BOX_PADDING` Å of vacuum, atoms deduplicated across periodic images.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np
from pymatgen.core import Element, Lattice, Structure

from cifkit.geom._common import (
    BOND_CAP,
    BOND_SCALE,
    attach_geom_info,
    bond_cutoff,
    element_symbol,
    site_symbols,
)

#: vacuum padding around the extracted cluster (Å)
BOX_PADDING = 20.0
#: hard cap on cluster size (guards against accidentally extracting the whole framework)
MAX_CLUSTER_ATOMS = 800

_MODES = ("sbu", "metal_cluster", "core")


def _is_metal(symbol: str) -> bool:
    try:
        return bool(Element(symbol).is_metal)
    except Exception:  # noqa: BLE001
        return False


def _build_bond_graph(structure: Structure):
    """Pre-computed periodic bond graph.

    Returns ``adj``: list over atoms of ``(neighbour_index, image_offset, cart_coords)``
    where ``image_offset`` is the integer lattice translation of the neighbour
    image relative to the periodic image of the source atom.
    """
    syms = site_symbols(structure)
    mat = np.asarray(structure.lattice.matrix, dtype=float)
    adj: list[list[tuple[int, tuple[int, int, int], np.ndarray]]] = []
    for i, neighbours in enumerate(structure.get_all_neighbors(BOND_CAP)):
        si = syms[i]
        row: list[tuple[int, tuple[int, int, int], np.ndarray]] = []
        for nb in neighbours:
            sj = str(getattr(nb, "species_string", "")) or element_symbol(nb)
            sj = "".join(ch for ch in sj if ch.isalpha()) or sj
            if float(nb.nn_distance) > bond_cutoff(si, sj, scale=BOND_SCALE, cap=BOND_CAP):
                continue
            image = tuple(int(round(float(v))) for v in np.atleast_1d(getattr(nb, "image", np.zeros(3))))
            if len(image) != 3:  # pragma: no cover - defensive
                image = (0, 0, 0)
            cart = np.asarray(nb.coords, dtype=float)
            row.append((int(nb.index), image, cart))
        adj.append(row)
    return syms, mat, adj


class _ClusterBuilder:
    """Cartesian-space BFS with periodic-image deduplication."""

    def __init__(self, syms: list[str], mat: np.ndarray, adj) -> None:
        self.syms = syms
        self.mat = mat
        self.adj = adj
        self.symbols: list[str] = []
        self.carts: list[np.ndarray] = []
        self._tol = 0.05

    # -- helpers -----------------------------------------------------------
    def _position(self, atom: int, image: tuple[int, int, int]) -> np.ndarray:
        base = np.asarray(self.mat, dtype=float)
        # cart coords of the (possibly shifted) periodic image of `atom`
        return self._base_cart(atom) + np.asarray(image, dtype=float) @ base

    def _base_cart(self, atom: int) -> np.ndarray:
        return self._cart0[atom]

    def attach_base(self, structure: Structure) -> None:
        self._cart0 = np.asarray(structure.cart_coords, dtype=float)

    def contains(self, cart: np.ndarray) -> bool:
        for existing in self.carts:
            if float(np.linalg.norm(existing - cart)) < self._tol:
                return True
        return False

    def add(self, atom: int, image: tuple[int, int, int], cart: np.ndarray | None = None) -> bool:
        position = self._position(atom, image) if cart is None else np.asarray(cart, dtype=float)
        if self.contains(position):
            return False
        self.symbols.append(self.syms[atom])
        self.carts.append(position)
        if len(self.symbols) > MAX_CLUSTER_ATOMS:
            raise ValueError(
                f"extract_cluster: cluster grew past {MAX_CLUSTER_ATOMS} atoms; "
                "the structure is probably fully connected (no molecular ligand to stop the BFS)"
            )
        return True


def _connected_metals(builder: _ClusterBuilder, seed: int, metal_set: frozenset[int]) -> list[tuple[int, tuple[int, int, int]]]:
    """BFS over metal-metal bonds starting from ``seed``; returns (atom, image) list."""
    start_image = (0, 0, 0)
    builder.add(seed, start_image)
    found = [(seed, start_image)]
    queue = [(seed, start_image)]
    while queue:
        atom, image = queue.pop(0)
        for nb_index, nb_image, _cart in builder.adj[atom]:
            if nb_index not in metal_set:
                continue
            total = (image[0] + nb_image[0], image[1] + nb_image[1], image[2] + nb_image[2])
            added = builder.add(nb_index, total)
            if added:
                found.append((nb_index, total))
                queue.append((nb_index, total))
    return found


def extract_cluster(structure: Structure, *, mode: str = "sbu") -> Structure:
    """Extract a metal cluster / SBU as a finite (non-periodic) structure.

    Args:
        structure: periodic input structure.
        mode: ``"sbu"``, ``"metal_cluster"`` or ``"core"``.

    Returns:
        A :class:`~pymatgen.core.Structure` with an orthorhombic box and
        :data:`BOX_PADDING` Å of vacuum around the cluster.

    Raises:
        ValueError: unknown mode, no metal atoms, or a runaway cluster.
    """
    key = str(mode or "sbu").strip().lower()
    if key in ("metal", "node", "first_shell"):
        key = "metal_cluster"
    if key in ("metal_core", "metals"):
        key = "core"
    if key not in _MODES:
        raise ValueError(f"extract_cluster: mode must be one of {_MODES}, got {mode!r}")
    if len(structure) == 0:
        raise ValueError("extract_cluster: empty structure")

    syms = site_symbols(structure)
    metal_indices = [i for i, s in enumerate(syms) if _is_metal(s)]
    if not metal_indices:
        raise ValueError(
            "extract_cluster: no metal atoms found (elements present: "
            + ", ".join(sorted(set(syms)))
            + ")"
        )
    metal_set = frozenset(metal_indices)
    graph_syms, mat, adj = _build_bond_graph(structure)
    builder = _ClusterBuilder(graph_syms, mat, adj)
    builder.attach_base(structure)

    # pick the most coordinated metal atom as the seed (deterministic)
    seed = max(metal_indices, key=lambda i: (len(adj[i]), -i))
    metals = _connected_metals(builder, seed, metal_set)

    first_shell: list[tuple[int, tuple[int, int, int]]] = []
    if key in ("sbu", "metal_cluster"):
        for atom, image in metals:
            for nb_index, nb_image, _cart in adj[atom]:
                total = (image[0] + nb_image[0], image[1] + nb_image[1], image[2] + nb_image[2])
                if builder.add(nb_index, total):
                    first_shell.append((nb_index, total))

    if key == "sbu":
        # grow each ligand through non-metal bonds only
        queue = list(first_shell)
        while queue:
            atom, image = queue.pop(0)
            for nb_index, nb_image, _cart in adj[atom]:
                if nb_index in metal_set:
                    continue
                total = (image[0] + nb_image[0], image[1] + nb_image[1], image[2] + nb_image[2])
                if builder.add(nb_index, total):
                    queue.append((nb_index, total))

    if len(builder.symbols) == 0 or (key != "core" and len(builder.symbols) <= 1):
        raise ValueError(
            f"extract_cluster(mode={key!r}): only extracted {len(builder.symbols)} atom(s); "
            "the seed metal has no bonds within the covalent-radius cutoffs"
        )

    carts = np.vstack(builder.carts)
    lo = carts.min(axis=0) - BOX_PADDING / 2.0
    extent = carts.max(axis=0) - carts.min(axis=0) + BOX_PADDING
    extent = np.maximum(extent, 2.0 * BOX_PADDING)
    lattice = Lattice.orthorhombic(*[float(x) for x in extent])
    frac = (carts - lo) @ np.linalg.inv(np.asarray(lattice.matrix, dtype=float))
    cluster = Structure(lattice, builder.symbols, frac, validate_proximity=False)

    counts = Counter(builder.symbols)
    info: dict[str, Any] = {
        "function": "extract_cluster",
        "mode": key,
        "natoms": len(cluster),
        "formula": cluster.composition.formula,
        "counts": dict(counts),
        "seed_metal_index": int(seed),
        "n_metals": len(metals),
        "box_padding": BOX_PADDING,
        "box": [float(x) for x in extent],
    }
    return attach_geom_info(cluster, info)
