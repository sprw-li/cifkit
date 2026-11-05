"""Periodic bond perception for the repair layer.

Everything the repair layer needs to reason about chemical valence is built
here, on top of a *geometric* bond model (no external chemistry toolkit is
required, but RDKit is used later by :mod:`cifkit.repair.hydrogen` for
cross-checking and for placing hydrogen coordinates):

* bond search with covalent radii and **periodic minimum images**
  (``Structure.get_neighbor_list``), with metal–ligand bonds flagged
  separately;
* 5- and 6-membered rings are detected with a translation-aware depth-first
  search (rings may cross the unit-cell boundary), then tested for
  planarity and aromatic character (all ring bonds shortened);
* bond orders: multiple bonds outside aromatic rings are assigned from
  bond-length ratios; the remaining pi bonds inside aromatic rings are
  completed with a small Kekulé matching (all ring carbons get exactly one
  ring pi bond when their valence sum requires it, heteroatoms optionally);
* per-atom bond-order sums, hybridisation and a **hydrogen demand** plan
  (how many H each atom still needs, and the chemical reason).

The algorithms are deliberately conservative: anything the geometry cannot
justify is reported in :attr:`BondGraph.warnings` instead of being guessed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
from pymatgen.core import Element, Structure

# ---------------------------------------------------------------------------
# Element data
# ---------------------------------------------------------------------------
# Covalent radii in Angstrom (Cordero et al. 2008, the same set ASE ships
# with by default).  Kept local so the repair layer has no hard dependency on
# ASE: pymatgen 2026 removed ``Element.covalent_radius``.
_RADII: dict[str, float] = {
    "H": 0.31, "He": 0.28, "Li": 1.28, "Be": 0.96, "B": 0.84, "C": 0.76,
    "N": 0.71, "O": 0.66, "F": 0.57, "Ne": 0.58, "Na": 1.66, "Mg": 1.41,
    "Al": 1.21, "Si": 1.11, "P": 1.07, "S": 1.05, "Cl": 1.02, "Ar": 1.06,
    "K": 2.03, "Ca": 1.76, "Sc": 1.70, "Ti": 1.60, "V": 1.53, "Cr": 1.39,
    "Mn": 1.39, "Fe": 1.32, "Co": 1.26, "Ni": 1.24, "Cu": 1.32, "Zn": 1.22,
    "Ga": 1.22, "Ge": 1.20, "As": 1.19, "Se": 1.20, "Br": 1.20, "Kr": 1.16,
    "Rb": 2.20, "Sr": 1.95, "Y": 1.90, "Zr": 1.75, "Nb": 1.64, "Mo": 1.54,
    "Tc": 1.47, "Ru": 1.46, "Rh": 1.42, "Pd": 1.39, "Ag": 1.45, "Cd": 1.44,
    "In": 1.42, "Sn": 1.39, "Sb": 1.39, "Te": 1.38, "I": 1.39, "Xe": 1.40,
    "Cs": 2.44, "Ba": 2.15, "La": 2.07, "Ce": 2.04, "Pr": 2.03, "Nd": 2.01,
    "Pm": 1.99, "Sm": 1.98, "Eu": 1.98, "Gd": 1.96, "Tb": 1.94, "Dy": 1.92,
    "Ho": 1.92, "Er": 1.89, "Tm": 1.90, "Yb": 1.87, "Lu": 1.87, "Hf": 1.75,
    "Ta": 1.70, "W": 1.62, "Re": 1.51, "Os": 1.44, "Ir": 1.41, "Pt": 1.36,
    "Au": 1.36, "Hg": 1.32, "Tl": 1.45, "Pb": 1.46, "Bi": 1.48, "Po": 1.40,
    "At": 1.50, "Rn": 1.50, "Fr": 2.60, "Ra": 2.21, "Ac": 2.15, "Th": 2.06,
    "Pa": 2.00, "U": 1.96, "Np": 1.90, "Pu": 1.87, "Am": 1.80, "Cm": 1.69,
}
_DEFAULT_RADIUS = 1.20

# Expected (neutral) valence used to count missing hydrogens.
VALENCE: dict[str, int] = {
    "H": 1, "B": 3, "C": 4, "N": 3, "O": 2, "F": 1,
    "Si": 4, "P": 3, "S": 2, "Cl": 1, "Br": 1, "I": 1, "Se": 2,
}
# Typical X-H bond length in Angstrom, used when placing new H atoms.
H_BOND_LENGTH: dict[str, float] = {
    "B": 1.19, "C": 1.09, "N": 1.01, "O": 0.96, "S": 1.34, "P": 1.42,
    "Si": 1.48, "Se": 1.46,
}
# Elements that can form aromatic rings / accept ring pi bonds.
AROMATIC_ELEMENTS = {"B", "C", "N", "O", "P", "S", "Se"}

_METAL_CACHE: dict[str, bool] = {}
_FALLBACK_METALS = {
    "Li", "Be", "Na", "Mg", "Al", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn",
    "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Rb", "Sr", "Y", "Zr", "Nb", "Mo",
    "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Cs", "Ba", "La", "Ce",
    "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
    "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb",
    "Bi", "Fr", "Ra", "Ac", "Th", "U", "Np", "Pu", "Am", "Cm",
}


def covalent_radius(symbol: str) -> float:
    """Covalent radius of an element in Angstrom."""
    return _RADII.get(symbol, _DEFAULT_RADIUS)


def is_metal(symbol: str) -> bool:
    """True for metals (used to separate coordination bonds from covalent ones)."""
    if symbol not in _METAL_CACHE:
        try:
            _METAL_CACHE[symbol] = bool(Element(symbol).is_metal)
        except Exception:  # noqa: BLE001 - unknown symbol
            _METAL_CACHE[symbol] = symbol in _FALLBACK_METALS
    return _METAL_CACHE[symbol]


def site_symbol(site) -> str:
    """Majority species symbol of a (possibly disordered) pymatgen site."""
    species = site.species
    if len(species) == 1:
        return next(iter(species)).symbol
    return max(species.items(), key=lambda kv: kv[1])[0].symbol


def site_occupancy(site) -> float:
    """Total occupancy of a pymatgen site."""
    try:
        return float(sum(site.species.values()))
    except Exception:  # noqa: BLE001
        return 1.0


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------
@dataclass
class Bond:
    """A directed bond entry: atom ``i`` bonds to atom ``j`` placed at
    ``cart[j] + image @ lattice``."""

    i: int
    j: int
    image: tuple[int, int, int]
    distance: float
    order: float = 1.0
    metal: bool = False
    aromatic: bool = False

    @property
    def is_hydrogen_bond(self) -> bool:  # pragma: no cover - tiny helper
        return self.order == 1.0


@dataclass(eq=False)
class Ring:
    """A small ring found in the periodic bond graph."""

    atoms: tuple[int, ...]
    shifts: tuple[tuple[int, int, int], ...]
    size: int = 0
    bond_keys: tuple[tuple, ...] = ()
    normal: np.ndarray | None = None
    centroid: np.ndarray | None = None
    planar: bool = False
    aromatic: bool = False
    max_bond_length: float = 0.0
    min_bond_length: float = 0.0
    max_plane_deviation: float = 0.0

    def __post_init__(self) -> None:
        if not self.size:
            self.size = len(self.atoms)


def bond_key(i: int, j: int, image: Iterable[int]) -> tuple[int, int, tuple[int, int, int]]:
    """Canonical key for an undirected bond with a translation image."""
    img = tuple(int(round(x)) for x in image)
    rev = tuple(-x for x in img)
    if (i, j, img) <= (j, i, rev):
        return (i, j, img)
    return (j, i, rev)


@dataclass
class BondGraph:
    """Periodic bond graph of a structure, with orders and ring information."""

    symbols: list[str]
    cart: np.ndarray
    lattice: np.ndarray
    adj: dict[int, list[Bond]]
    metals: list[bool]
    by_key: dict[tuple, list[Bond]] = field(default_factory=dict)
    virtual_pi: dict[int, float] = field(default_factory=dict)
    rings: list[Ring] = field(default_factory=list)
    aromatic_atoms: set[int] = field(default_factory=set)
    aromatic_bonds: set[tuple] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)

    # -- basic helpers ------------------------------------------------------
    @property
    def n_atoms(self) -> int:
        return len(self.symbols)

    def neighbors(self, atom: int) -> list[Bond]:
        return self.adj.get(atom, [])

    def order_sum(self, atom: int) -> float:
        """Sum of bond orders around an atom (metal bonds count as 1)."""
        total = float(sum(b.order for b in self.adj.get(atom, ())))
        return total + self.virtual_pi.get(atom, 0.0)

    def pi_count(self, atom: int) -> float:
        """Number of formal pi bonds around an atom."""
        total = float(sum(max(0.0, b.order - 1.0) for b in self.adj.get(atom, ())))
        return total + self.virtual_pi.get(atom, 0.0)

    def h_neighbor_count(self, atom: int) -> int:
        return sum(1 for b in self.adj.get(atom, ()) if self.symbols[b.j] == "H")

    def heavy_neighbors(self, atom: int) -> list[Bond]:
        return [b for b in self.adj.get(atom, ()) if self.symbols[b.j] != "H"]

    def metal_bond_count(self, atom: int) -> int:
        return sum(1 for b in self.adj.get(atom, ()) if b.metal)

    def unit_directions(self, atom: int) -> list[tuple[int, np.ndarray]]:
        """Unit vectors from ``atom`` to each bonded neighbour (with images)."""
        out: list[tuple[int, np.ndarray]] = []
        base = self.cart[atom]
        for bond in self.adj.get(atom, ()):
            vec = self.cart[bond.j] + np.asarray(bond.image, dtype=float) @ self.lattice - base
            norm = float(np.linalg.norm(vec))
            if norm > 1e-8:
                out.append((bond.j, vec / norm))
        return out

    def hybridization(self, atom: int) -> str:
        """Rough hybridisation label: ``sp``, ``sp2`` or ``sp3``.

        Aromatic ring atoms are always treated as ``sp2``: their hydrogen
        direction lies in the ring plane even when they carry a lone pair
        instead of a formal double bond (e.g. the pyrrole-type N of an
        imidazolate).
        """
        if atom in self.aromatic_atoms:
            return "sp2"
        pi = self.pi_count(atom)
        if pi >= 1.5:
            return "sp"
        if pi >= 0.5:
            return "sp2"
        return "sp3"

    def unique_bonds(self) -> list[Bond]:
        """One directed :class:`Bond` per physical bond."""
        out: list[Bond] = []
        seen: set[tuple] = set()
        for atom in range(self.n_atoms):
            for bond in self.adj.get(atom, ()):
                key = bond_key(bond.i, bond.j, bond.image)
                if key in seen:
                    continue
                seen.add(key)
                out.append(bond)
        return out


# ---------------------------------------------------------------------------
# Bond perception
# ---------------------------------------------------------------------------
def perceive_bonds(
    structure: Structure,
    *,
    covalent_factor: float = 1.15,
    metal_factor: float = 1.30,
) -> BondGraph:
    """Perceive periodic bonds, rings and bond orders.

    Parameters
    ----------
    structure:
        Any pymatgen ``Structure`` (periodic).  Disordered sites are reduced
        to their majority species for the bond model.
    covalent_factor:
        Bond if ``d < factor * (r_i + r_j)`` for organic pairs.
    metal_factor:
        Same criterion in front of pairs that involve a metal; metal bonds
        are flagged and never used to steal covalent valence, but they do
        saturate coordinate N/O/S atoms (no N–H on metal-bound imidazolate
        nitrogen).
    """
    symbols = [site_symbol(site) for site in structure]
    n = len(symbols)
    cart = np.asarray(structure.cart_coords, dtype=float)
    lattice = np.asarray(structure.lattice.matrix, dtype=float)
    if n == 0:
        return BondGraph(symbols=[], cart=cart, lattice=lattice, adj={}, metals=[])

    radii = np.asarray([covalent_radius(s) for s in symbols], dtype=float)
    metals = [is_metal(s) for s in symbols]
    max_radius = float(radii.max()) if n else 1.0
    search = max(covalent_factor, metal_factor) * 2.0 * max_radius

    adj: dict[int, list[Bond]] = {i: [] for i in range(n)}
    if n > 1:
        center, point, offsets, distances = structure.get_neighbor_list(search)
        # ``get_neighbor_list`` yields both directions of every pair; collect a
        # directed map (a, b, image) -> (distance, metal) and make sure the
        # reverse direction exists as well.
        directed: dict[tuple[int, int, int, int, int], tuple[float, bool]] = {}
        for ci, pi, off, dist in zip(center, point, offsets, distances):
            a, b = int(ci), int(pi)
            if a == b:
                continue  # self images are not bonds (handled by contacts)
            if metals[a] and metals[b]:
                continue  # metal–metal contacts are not coordination bonds
            if symbols[a] == "H" and symbols[b] == "H":
                continue
            img = tuple(int(x) for x in off)
            factor = metal_factor if (metals[a] or metals[b]) else covalent_factor
            if float(dist) >= factor * (radii[a] + radii[b]):
                continue
            directed[(a, b, img[0], img[1], img[2])] = (float(dist), bool(metals[a] or metals[b]))
        for (a, b, ix, iy, iz), (dist, metal_bond) in list(directed.items()):
            reverse = (b, a, -ix, -iy, -iz)
            if reverse not in directed:
                directed[reverse] = (dist, metal_bond)
        for (a, b, ix, iy, iz), (dist, metal_bond) in directed.items():
            adj[a].append(Bond(a, b, (ix, iy, iz), dist, order=1.0, metal=metal_bond))

    by_key: dict[tuple, list[Bond]] = {}
    for atom in range(n):
        for bond in adj[atom]:
            key = bond_key(bond.i, bond.j, bond.image)
            by_key.setdefault(key, []).append(bond)

    graph = BondGraph(
        symbols=symbols,
        cart=cart,
        lattice=lattice,
        adj=adj,
        metals=metals,
        by_key=by_key,
    )
    _assign_bond_orders(graph)
    return graph


# ---------------------------------------------------------------------------
# Ring perception
# ---------------------------------------------------------------------------
def _has_bond(graph: BondGraph, i: int, j: int, image: tuple[int, int, int]) -> bool:
    return bond_key(i, j, image) in graph.by_key


def find_rings(graph: BondGraph, *, sizes: tuple[int, ...] = (5, 6), max_rings: int = 20000) -> list[Ring]:
    """Find small simple rings, allowing them to wrap across cell boundaries."""
    sizes = tuple(sorted({int(s) for s in sizes if int(s) >= 3}))
    if not sizes:
        return []
    max_size = max(sizes)
    rings: list[Ring] = []
    seen: set[tuple[int, ...]] = set()
    n = graph.n_atoms

    for start in range(n):
        if graph.metals[start] or graph.symbols[start] == "H":
            continue
        # Iterative DFS: (current atom, accumulated shift, path atoms, path shifts)
        stack: list[tuple[int, tuple[int, int, int], tuple[int, ...], tuple[tuple[int, int, int], ...]]] = [
            (start, (0, 0, 0), (start,), ((0, 0, 0),))
        ]
        while stack and len(rings) < max_rings:
            atom, shift, path, shifts = stack.pop()
            for bond in graph.adj.get(atom, ()):
                j = bond.j
                if j == start:
                    new_shift = (
                        shift[0] + bond.image[0],
                        shift[1] + bond.image[1],
                        shift[2] + bond.image[2],
                    )
                    if len(path) not in sizes or new_shift != (0, 0, 0):
                        continue
                    key = tuple(sorted(path))
                    if key in seen:
                        continue
                    if _ring_has_chord(graph, path, shifts):
                        continue
                    seen.add(key)
                    rings.append(
                        Ring(
                            atoms=path,
                            shifts=shifts,
                            size=len(path),
                            bond_keys=_ring_bond_keys(path, shifts),
                        )
                    )
                    continue
                if j in path:
                    continue
                if len(path) >= max_size:
                    continue
                if graph.metals[j] or graph.symbols[j] == "H":
                    continue
                new_shift = (
                    shift[0] + bond.image[0],
                    shift[1] + bond.image[1],
                    shift[2] + bond.image[2],
                )
                stack.append((j, new_shift, path + (j,), shifts + (new_shift,)))
    return rings


def _ring_bond_keys(atoms: tuple[int, ...], shifts: tuple[tuple[int, int, int], ...]) -> tuple[tuple, ...]:
    keys = []
    size = len(atoms)
    for k in range(size):
        a = atoms[k]
        b = atoms[(k + 1) % size]
        image = tuple(shifts[(k + 1) % size][d] - shifts[k][d] for d in range(3))
        keys.append(bond_key(a, b, image))
    return tuple(keys)


def _ring_has_chord(
    graph: BondGraph,
    atoms: tuple[int, ...],
    shifts: tuple[tuple[int, int, int], ...],
) -> bool:
    size = len(atoms)
    for k in range(size):
        for m in range(k + 1, size):
            consecutive = (m == k + 1) or (k == 0 and m == size - 1)
            if consecutive:
                continue
            image = tuple(shifts[m][d] - shifts[k][d] for d in range(3))
            if _has_bond(graph, atoms[k], atoms[m], image):
                return True
    return False


def _ring_coordinates(graph: BondGraph, ring: Ring) -> np.ndarray:
    return np.asarray(
        [graph.cart[a] + np.asarray(s, dtype=float) @ graph.lattice for a, s in zip(ring.atoms, ring.shifts)],
        dtype=float,
    )


def classify_rings(graph: BondGraph, rings: list[Ring], *, planarity_tol: float = 0.20) -> list[Ring]:
    """Mark rings planar/aromatic in place and return the aromatic subset.

    A ring is accepted as aromatic if it is planar (max deviation from the
    best plane < ``planarity_tol``), every atom is an aromatic-capable
    element, and every ring bond is shortened (``d <= 1.50 A``), i.e. no
    saturated bond.  For imidazolate (2-methylimidazole linker) this is
    exactly the 5-membered C3N2 ring with C–N ~1.34–1.37 A and C=C ~1.35 A.
    """
    aromatic: list[Ring] = []
    for ring in rings:
        coords = _ring_coordinates(graph, ring)
        centroid = coords.mean(axis=0)
        centered = coords - centroid
        try:
            _, _, vh = np.linalg.svd(centered, full_matrices=False)
            normal = vh[-1]
        except np.linalg.LinAlgError:  # pragma: no cover - degenerate coordinates
            normal = np.array([0.0, 0.0, 1.0])
        deviations = np.abs(centered @ normal)
        ring.centroid = centroid
        ring.normal = normal / max(float(np.linalg.norm(normal)), 1e-12)
        ring.max_plane_deviation = float(deviations.max())
        ring.planar = ring.max_plane_deviation < planarity_tol

        lengths = []
        for key in ring.bond_keys:
            bonds = graph.by_key.get(key)
            if bonds:
                lengths.append(bonds[0].distance)
            else:  # pragma: no cover - ring keys are built from the graph
                lengths = []
                break
        if lengths:
            ring.max_bond_length = max(lengths)
            ring.min_bond_length = min(lengths)
        elements_ok = all(graph.symbols[a] in AROMATIC_ELEMENTS for a in ring.atoms)
        ring.aromatic = bool(
            ring.planar
            and elements_ok
            and lengths
            and ring.max_bond_length <= 1.50
            and ring.min_bond_length >= 1.20
        )
        if ring.aromatic:
            aromatic.append(ring)
    return aromatic


# ---------------------------------------------------------------------------
# Bond orders
# ---------------------------------------------------------------------------
def _set_order(graph: BondGraph, key: tuple, order: float) -> None:
    for bond in graph.by_key.get(key, ()):
        bond.order = order


def _assign_bond_orders(graph: BondGraph) -> None:
    """Assign integer-ish bond orders (1/2/3) + aromatic flags."""
    rings = find_rings(graph)
    aromatic_rings = classify_rings(graph, rings)
    graph.rings = rings
    for ring in aromatic_rings:
        for atom in ring.atoms:
            graph.aromatic_atoms.add(atom)
        for key in ring.bond_keys:
            graph.aromatic_bonds.add(key)
            for bond in graph.by_key.get(key, ()):
                bond.aromatic = True

    # 1) Multiple bonds outside aromatic rings, from bond-length ratios.
    for key, bonds in graph.by_key.items():
        bond = bonds[0]
        if key in graph.aromatic_bonds:
            continue
        if bond.metal or graph.symbols[bond.i] == "H" or graph.symbols[bond.j] == "H":
            _set_order(graph, key, 1.0)
            continue
        radius = covalent_radius(graph.symbols[bond.i]) + covalent_radius(graph.symbols[bond.j])
        ratio = bond.distance / radius if radius > 0 else 1.0
        if ratio < 0.80:
            order = 3.0
        elif ratio < 0.92:
            order = 2.0
        else:
            order = 1.0
        _set_order(graph, key, order)

    # 2) Carboxylate / carbonate groups: symmetric C–O pairs are delocalised;
    #    represent them with one C=O and one C–O so carbon keeps valence 4.
    _fix_carboxylate_orders(graph)

    # 3) Kekulé structure inside aromatic rings.
    _assign_kekule(graph, aromatic_rings)


def _fix_carboxylate_orders(graph: BondGraph) -> None:
    for atom in range(graph.n_atoms):
        if graph.symbols[atom] != "C":
            continue
        oxygen_bonds = [
            b for b in graph.adj.get(atom, ()) if graph.symbols[b.j] == "O" and not b.metal
        ]
        if len(oxygen_bonds) != 2:
            continue
        # one O already carries an H (carboxylic acid): that O is single
        h_oxygen = [b for b in oxygen_bonds if graph.h_neighbor_count(b.j) > 0]
        if len(h_oxygen) == 1:
            single = h_oxygen[0]
            double = [b for b in oxygen_bonds if b.j != single.j][0]
            _set_order(graph, bond_key(atom, single.j, single.image), 1.0)
            _set_order(graph, bond_key(atom, double.j, double.image), 2.0)
            continue
        # delocalised carboxylate: both C–O look double-ish (ratio < 0.95)
        ratios = []
        for b in oxygen_bonds:
            radius = covalent_radius("C") + covalent_radius("O")
            ratios.append(b.distance / radius if radius else 1.0)
        if max(ratios) < 0.95:
            ordered = sorted(oxygen_bonds, key=lambda b: b.distance)
            _set_order(graph, bond_key(atom, ordered[0].j, ordered[0].image), 2.0)
            _set_order(graph, bond_key(atom, ordered[1].j, ordered[1].image), 1.0)


def _assign_kekule(graph: BondGraph, aromatic_rings: list[Ring]) -> None:
    """Complete ring pi bonds so that every aromatic carbon reaches valence 4."""
    if not aromatic_rings:
        return

    edges: dict[tuple, float] = {}
    for key in graph.aromatic_bonds:
        bonds = graph.by_key.get(key)
        if bonds:
            edges[key] = bonds[0].distance

    adjacency: dict[int, list[tuple[int, tuple, float]]] = {}
    for key, distance in edges.items():
        a, b = key[0], key[1]
        adjacency.setdefault(a, []).append((b, key, distance))
        adjacency.setdefault(b, []).append((a, key, distance))

    must_cover: set[int] = set()
    for atom in sorted(graph.aromatic_atoms):
        if graph.symbols[atom] not in {"C", "B"}:
            continue
        base = graph.order_sum(atom)  # ring bonds currently order 1
        demand = VALENCE.get(graph.symbols[atom], 4) - base
        if demand >= 0.99:
            must_cover.add(atom)
        elif demand < -0.01:
            graph.warnings.append(
                f"芳香环原子 {atom}({graph.symbols[atom]}) 键级和 {base:.2f} 超过价态"
            )

    # Split the aromatic sub-graph into connected components and solve each
    # independently (fast, and failures stay local).
    components: list[set[int]] = []
    seen: set[int] = set()
    for atom in sorted(must_cover):
        if atom in seen:
            continue
        comp: set[int] = set()
        stack = [atom]
        while stack:
            cur = stack.pop()
            if cur in comp:
                continue
            comp.add(cur)
            seen.add(cur)
            for other, _key, _dist in adjacency.get(cur, ()):
                if other not in comp:
                    stack.append(other)
        components.append(comp)

    for comp in components:
        comp_must = {a for a in comp if a in must_cover}
        solution = _solve_kekule_component(graph, comp, comp_must, adjacency)
        if solution is None:
            # Fallback: represent the missing ring pi bond as a virtual pi
            # bond (bond stays order 1); RDKit placement is skipped for this
            # fragment and hydrogen booking still works.
            for atom in comp_must:
                graph.virtual_pi[atom] = graph.virtual_pi.get(atom, 0.0) + 1.0
            graph.warnings.append(
                "芳香环 Kekulé 匹配失败（组件原子 %s），按分数 π 键处理" % sorted(comp_must)
            )
            continue
        for key in solution:
            _set_order(graph, key, 2.0)


def _solve_kekule_component(
    graph: BondGraph,
    component: set[int],
    must_cover: set[int],
    adjacency: dict[int, list[tuple[int, tuple, float]]],
) -> tuple[tuple, ...] | None:
    """Minimum-cost matching covering every atom in ``must_cover``.

    Heteroatoms (N/O/S/P/Se) may be covered by a ring double bond (pyridine
    type) or left single (pyrrole type) - the choice decides whether an
    uncoordinated heteroatom receives an H later.
    """
    best: list[tuple[float, tuple]] = []
    budget = [200000]

    def rec(remaining: frozenset[int], covered: frozenset[int], chosen: tuple, cost: float) -> None:
        budget[0] -= 1
        if budget[0] < 0:
            return
        if best and cost >= best[0][0] - 1e-9:
            return
        if not remaining:
            entry = (cost, tuple(sorted(chosen)))
            if not best or entry < best[0]:
                best[:] = [entry]
            return
        # MRV: atom with the fewest usable partners first
        atom = min(
            remaining,
            key=lambda a: sum(
                1
                for other, _k, _d in adjacency.get(a, ())
                if other not in covered and (other in remaining or other not in must_cover)
            ),
        )
        rest = remaining - {atom}
        options = []
        for other, key, distance in adjacency.get(atom, ()):
            if other in covered:
                continue
            if other in must_cover:
                options.append((distance, other, key, True))
            elif other not in component:
                continue
            elif graph.symbols[other] in {"C", "B"}:
                continue  # carbon with satisfied valence must not gain a pi bond
            else:
                options.append((distance, other, key, False))
        for distance, other, key, other_is_must in sorted(options):
            new_remaining = rest - {other} if other_is_must else rest
            rec(new_remaining, covered | {other}, chosen + (key,), cost + distance)

    rec(frozenset(must_cover), frozenset(), (), 0.0)
    if not best:
        return None
    return best[0][1]


# ---------------------------------------------------------------------------
# Hydrogen demand
# ---------------------------------------------------------------------------
@dataclass
class HydrogenDemand:
    """How many H an atom still needs, and why."""

    atom: int
    symbol: str
    missing: int
    hybrid: str
    order_sum: float
    metal_bonds: int = 0
    existing_h: int = 0
    reason: str = "valence"
    detail: str = ""


def hydrogen_demand(graph: BondGraph) -> list[HydrogenDemand]:
    """Compute the hydrogen demand of every non-metal, non-H atom.

    Rules (see ``docs/REPAIR.md``):

    * C: 4 - bond order sum.
    * N: 3 - bond order sum, but a metal-coordinated N gets **no** H (the
      metal bond fills its valence: ZIF-8 imidazolate N).
    * O: 2 - bond order sum; a metal-coordinated O gets no H; a deprotonated
      carboxylate O is treated as anionic (no H) and reported.
    * S/P/B/Si/Se: same idea with their neutral valence.
    * Atoms with no bonds at all are only protonated when no metal is nearby
      (otherwise the missing bond is a missed coordination bond, not an H).
    """
    demands: list[HydrogenDemand] = []
    n = graph.n_atoms
    for atom in range(n):
        symbol = graph.symbols[atom]
        if symbol == "H" or graph.metals[atom]:
            continue
        target = VALENCE.get(symbol)
        if target is None:
            continue
        bonds = graph.adj.get(atom, ())
        if not bonds:
            demands.append(
                HydrogenDemand(
                    atom=atom,
                    symbol=symbol,
                    missing=0,
                    hybrid="sp3",
                    order_sum=0.0,
                    reason="isolated",
                    detail="孤立原子，未成键；不补 H（可能是配位键未被识别）",
                )
            )
            continue
        order_sum = graph.order_sum(atom)
        metal_bonds = graph.metal_bond_count(atom)
        existing_h = graph.h_neighbor_count(atom)
        reason = "valence"
        detail = ""
        missing = target - order_sum

        if metal_bonds and symbol in {"N", "O", "S", "Se"}:
            missing = 0.0
            reason = "metal-coordinated"
            detail = f"{symbol} 与金属配位（{metal_bonds} 个金属键），按价态不补 H"
        elif symbol == "O" and missing > 0.01 and _is_carboxylate_oxygen(graph, atom):
            missing = 0.0
            reason = "carboxylate-O"
            detail = "羧酸根 O 视为去质子化阴离子，不补 H（若确为 -COOH，需提供化学式/电荷信息）"

        if missing > 0.01 and symbol in {"C", "N", "O", "S", "P", "B", "Si", "Se"}:
            missing_int = int(round(missing))
        else:
            missing_int = 0
        if missing_int < 0:
            missing_int = 0
        if missing_int > 0 and abs(missing - missing_int) > 0.15:
            missing_int = int(np.floor(missing + 1e-6))

        if missing_int:
            # do not over-protonate: at most the remaining sigma slots
            max_extra = max(0, target - graph.h_neighbor_count(atom) - int(round(order_sum - existing_h)))
            missing_int = max(0, min(missing_int, max_extra if max_extra else missing_int))
        if missing < -0.01:
            graph.warnings.append(
                f"原子 {atom}({symbol}) 键级和 {order_sum:.2f} 超过中性价态 {target}"
            )

        demands.append(
            HydrogenDemand(
                atom=atom,
                symbol=symbol,
                missing=missing_int,
                hybrid=graph.hybridization(atom),
                order_sum=order_sum,
                metal_bonds=metal_bonds,
                existing_h=existing_h,
                reason=reason,
                detail=detail,
            )
        )
    return demands


def is_carboxylate_oxygen(graph: BondGraph, atom: int) -> bool:
    """True if ``atom`` is an O of a carboxylate/carbonate group."""
    for bond in graph.adj.get(atom, ()):
        if bond.metal:
            continue
        carbon = bond.j
        if graph.symbols[carbon] != "C":
            continue
        oxygens = [
            b for b in graph.adj.get(carbon, ()) if graph.symbols[b.j] == "O" and not b.metal
        ]
        if len(oxygens) >= 2:
            return True
    return False


# Backwards-compatible private alias (used internally above).
_is_carboxylate_oxygen = is_carboxylate_oxygen


def describe_bond_graph(graph: BondGraph) -> dict:
    """Small debug summary (used by tests / diagnostics)."""
    from collections import Counter

    return {
        "natoms": graph.n_atoms,
        "nbonds": len(graph.unique_bonds()),
        "n_metal_bonds": sum(1 for b in graph.unique_bonds() if b.metal),
        "rings": [
            {
                "atoms": list(r.atoms),
                "size": r.size,
                "planar": r.planar,
                "aromatic": r.aromatic,
                "max_bond": round(r.max_bond_length, 3),
            }
            for r in graph.rings
            if r.aromatic
        ],
        "aromatic_atoms": len(graph.aromatic_atoms),
        "bond_order_histogram": dict(Counter(round(b.order, 2) for b in graph.unique_bonds())),
        "warnings": list(graph.warnings),
    }
