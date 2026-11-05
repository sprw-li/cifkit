"""Missing-hydrogen completion ("补氢") for periodic structures.

Pipeline
--------
1. :func:`cifkit.repair.bonds.perceive_bonds` builds the periodic bond graph
   (covalent-radius bond search with minimum images, metal bonds flagged,
   5/6-membered aromatic rings detected, Kekulé bond orders assigned).
2. :func:`~cifkit.repair.bonds.hydrogen_demand` decides *how many* H every
   atom still needs, from its bond-order sum, with explicit chemical rules
   for metal-coordinated N/O/S (no N–H on a Zn-bound imidazolate nitrogen)
   and for deprotonated carboxylate oxygen.
3. **RDKit route (preferred)**: every finite organic fragment left after
   cutting the metal–ligand bonds is capped at the removed coordination
   bonds (H placeholder), the heavy-atom graph with its Kekulé bond orders is
   handed to RDKit, and ``Chem.AddHs(mol, addCoords=True)`` produces the
   hydrogen coordinates in the fragment's own 3-D conformer; coordinates are
   mapped back into the periodic cell.  Implicit-H counts are cross-checked
   against step 2 and a mismatch rejects the fragment.
4. **Pure-geometry fallback**: VSEPR/tetrahedral construction from the
   existing bond directions (sp3 109.47°, sp2 120° in the ring plane, sp
   180°), with candidate rotation/flip enumeration.  This is also used when
   RDKit is unavailable or a fragment is periodic / unsanitizable.
5. **Conflict minimisation**: every candidate is checked against all atoms
   over all periodic images; H···H must stay > 1.4 Å (hard reject < 1.2 Å),
   H···heavy > 1.5 Å (hard reject < 0.9 Å), H···metal > 2.0 Å (hard reject
   < 1.5 Å).  The best candidate set (largest distance margin) wins.
6. Post-placement valence verification: every C must end at bond order sum 4,
   no overlapping hydrogens.  Any deviation is reported as a warning.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
from pymatgen.core import Structure

from cifkit.repair.bonds import (
    H_BOND_LENGTH,
    VALENCE,
    BondGraph,
    HydrogenDemand,
    covalent_radius,
    hydrogen_demand,
    perceive_bonds,
)
from cifkit.repair._labels import ensure_unique_labels

try:  # RDKit is optional: it is present in the project venv but not required.
    from rdkit import Chem, RDLogger
    from rdkit.Chem import rdmolops
    from rdkit.Geometry import Point3D

    RDLogger.DisableLog("rdApp.warning")
    _RDKIT_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only without rdkit
    Chem = None  # type: ignore[assignment]
    Point3D = None  # type: ignore[assignment]
    _RDKIT_AVAILABLE = False


# Conflict thresholds in Angstrom: (hard reject, preferred target).
_HARD_MIN = {"H": 1.20, "metal": 1.50, "heavy": 0.90}
_PREFERRED_MIN = {"H": 1.40, "metal": 2.00, "heavy": 1.50}

_IMAGE_OFFSETS = np.asarray(
    [[a, b, c] for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1)], dtype=float
)


# ---------------------------------------------------------------------------
# Small geometric helpers
# ---------------------------------------------------------------------------
def _normalize(vec: np.ndarray) -> np.ndarray | None:
    norm = float(np.linalg.norm(vec))
    if norm < 1e-9:
        return None
    return vec / norm


def _perpendicular_basis(axis: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Two orthonormal unit vectors perpendicular to ``axis``."""
    helper = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    b1 = _normalize(np.cross(axis, helper))
    if b1 is None:  # pragma: no cover - axis guaranteed to be a unit vector
        b1 = np.array([0.0, 1.0, 0.0])
    b2 = _normalize(np.cross(axis, b1))
    return b1, b2 if b2 is not None else np.array([0.0, 0.0, 1.0])


def _tetrahedral_angle() -> float:
    return float(np.arccos(-1.0 / 3.0))


def _fibonacci_sphere(count: int) -> np.ndarray:
    idx = np.arange(count, dtype=float) + 0.5
    phi = np.arccos(1.0 - 2.0 * idx / count)
    theta = np.pi * (1.0 + 5.0 ** 0.5) * idx
    return np.column_stack(
        [np.cos(theta) * np.sin(phi), np.sin(theta) * np.sin(phi), np.cos(phi)]
    )


# ---------------------------------------------------------------------------
# Candidate hydrogen directions (pure geometry)
# ---------------------------------------------------------------------------
def _geometric_candidate_sets(
    graph: BondGraph,
    demand: HydrogenDemand,
    *,
    max_sets: int = 200,
) -> list[list[np.ndarray]]:
    """Unit direction vectors for the missing H atoms of one atom.

    Returns a list of *candidate sets*; each set contains exactly
    ``demand.missing`` unit vectors (directions from the atom).
    """
    missing = demand.missing
    if missing <= 0:
        return []
    symbol = demand.symbol
    hybrid = demand.hybrid
    dirs = [direction for _neighbour, direction in graph.unit_directions(demand.atom)]
    candidates: list[list[np.ndarray]] = []
    tetra = _tetrahedral_angle()
    cos_tetra, sin_tetra = np.cos(tetra), np.sin(tetra)

    if not dirs:
        # Isolated atom: pick `missing` well-separated directions.
        sphere = _fibonacci_sphere(64)
        chosen: list[np.ndarray] = []
        for _ in range(min(missing, 4)):
            best = None
            for point in sphere:
                separation = min((float(np.dot(point, other)) for other in chosen), default=-1.0)
                if best is None or separation < best[0]:
                    best = (separation, point)
            chosen.append(best[1])
        return [chosen]

    if len(dirs) == 1:
        axis = dirs[0]
        b1, b2 = _perpendicular_basis(axis)
        if hybrid == "sp" and missing == 1:
            return [[-axis]]
        if hybrid == "sp2":
            if missing == 1:
                for phi in np.linspace(0.0, 2.0 * np.pi, 12, endpoint=False):
                    direction = (
                        np.cos(np.radians(120.0)) * axis
                        + np.sin(np.radians(120.0)) * (np.cos(phi) * b1 + np.sin(phi) * b2)
                    )
                    candidates.append([direction])
                return candidates
            if missing == 2:
                # =CH2: both H in a plane through the double bond; use the
                # neighbour's local plane to orient that plane.
                normal = _local_plane_normal(graph, demand.atom)
                p = _normalize(np.cross(normal, axis)) if normal is not None else b1
                if p is None:  # pragma: no cover
                    p = b1
                h1 = np.cos(np.radians(120.0)) * axis + np.sin(np.radians(120.0)) * p
                h2 = np.cos(np.radians(120.0)) * axis - np.sin(np.radians(120.0)) * p
                return [[h1, h2]]
        if hybrid == "sp3":
            if missing == 3:
                for phi in np.linspace(0.0, 2.0 * np.pi, 24, endpoint=False):
                    trip = []
                    for k in range(3):
                        angle = phi + k * 2.0 * np.pi / 3.0
                        trip.append(
                            cos_tetra * axis
                            + sin_tetra * (np.cos(angle) * b1 + np.sin(angle) * b2)
                        )
                    candidates.append(trip)
                return candidates[:max_sets]
            if missing == 1:
                for phi in np.linspace(0.0, 2.0 * np.pi, 24, endpoint=False):
                    candidates.append(
                        [cos_tetra * axis + sin_tetra * (np.cos(phi) * b1 + np.sin(phi) * b2)]
                    )
                return candidates
        # Anything else: fall back to sampling below.

    if len(dirs) == 2:
        u1, u2 = dirs
        cos_alpha = float(np.clip(np.dot(u1, u2), -1.0, 1.0))
        alpha = float(np.arccos(cos_alpha))
        if hybrid == "sp2" and missing == 1:
            bisector = _normalize(-(u1 + u2))
            if bisector is not None:
                return [[bisector]]
        if hybrid == "sp3":
            bisector = _normalize(u1 + u2)
            normal = _normalize(np.cross(u1, u2))
            if bisector is not None and normal is not None and alpha > 1e-3:
                half = alpha / 2.0
                cos_half = np.cos(half)
                if abs(cos_half) > 1e-3:
                    a = -1.0 / (3.0 * cos_half)
                    if abs(a) <= 1.0:
                        b = float(np.sqrt(max(0.0, 1.0 - a * a)))
                        if missing == 1:
                            return [
                                [a * bisector + b * normal],
                                [a * bisector - b * normal],
                            ]
                        if missing == 2:
                            return [[a * bisector + b * normal, a * bisector - b * normal]]
        if hybrid == "sp2" and missing == 2:  # pragma: no cover - rare
            pass

    if len(dirs) == 3 and missing == 1:
        complement = _normalize(-(dirs[0] + dirs[1] + dirs[2]))
        if complement is not None:
            return [[complement]]

    # General fallback: greedy sampling on a sphere with the ideal angle.
    ideal = {"sp3": tetra, "sp2": np.radians(120.0), "sp": np.pi}.get(hybrid, tetra)
    cos_ideal = float(np.cos(ideal))
    sphere = _fibonacci_sphere(400)
    chosen: list[np.ndarray] = []
    for _ in range(missing):
        best = None
        for point in sphere:
            if any(abs(float(np.dot(point, other))) > 0.999 for other in chosen):
                continue
            cost = sum((float(np.dot(point, d)) - cos_ideal) ** 2 for d in dirs)
            cost += sum((float(np.dot(point, other)) - cos_ideal) ** 2 for other in chosen)
            if best is None or cost < best[0]:
                best = (cost, point)
        chosen.append(best[1])
    return [chosen]


def _local_plane_normal(graph: BondGraph, atom: int) -> np.ndarray | None:
    """Best estimate of the local sp2 plane normal around ``atom``.

    Uses the aromatic ring plane when the atom is part of one, otherwise the
    plane spanned by the neighbours of the atom's bonded neighbours.
    """
    for ring in graph.rings:
        if ring.aromatic and atom in ring.atoms and ring.normal is not None:
            return np.asarray(ring.normal, dtype=float)
    candidate_vectors: list[np.ndarray] = []
    for _neighbour, direction in graph.unit_directions(atom):
        candidate_vectors.append(direction)
    # Vectors to the neighbours of the neighbours (excluding the atom itself).
    for neighbour, _direction in graph.unit_directions(atom):
        base = graph.cart[neighbour]
        for bond in graph.adj.get(neighbour, ()):
            if bond.j == atom:
                continue
            vec = graph.cart[bond.j] + np.asarray(bond.image, dtype=float) @ graph.lattice - base
            unit = _normalize(vec)
            if unit is not None:
                candidate_vectors.append(unit)
    for i in range(len(candidate_vectors)):
        for j in range(i + 1, len(candidate_vectors)):
            normal = _normalize(np.cross(candidate_vectors[i], candidate_vectors[j]))
            if normal is not None:
                return normal
    return None


# ---------------------------------------------------------------------------
# RDKit capped-fragment route
# ---------------------------------------------------------------------------
@dataclass
class _RdkitResult:
    positions: dict[int, list[np.ndarray]] = field(default_factory=dict)
    fragments_total: int = 0
    fragments_ok: int = 0
    fragments_failed: int = 0
    failures: list[str] = field(default_factory=list)


def _connected_components(graph: BondGraph, atoms: Iterable[int]) -> list[list[int]]:
    """Components of the non-metal bond graph (H atoms included)."""
    remaining = set(atoms)
    components: list[list[int]] = []
    while remaining:
        start = remaining.pop()
        component = [start]
        stack = [start]
        while stack:
            current = stack.pop()
            for bond in graph.adj.get(current, ()):
                if bond.metal:
                    continue
                neighbour = bond.j
                if neighbour in remaining:
                    remaining.discard(neighbour)
                    component.append(neighbour)
                    stack.append(neighbour)
        components.append(component)
    return components


def _unwrap_component(
    graph: BondGraph, component: list[int]
) -> dict[int, tuple[int, int, int]] | None:
    """Translation that makes a finite fragment contiguous, or None if periodic."""
    root = component[0]
    shifts: dict[int, tuple[int, int, int]] = {root: (0, 0, 0)}
    stack = [root]
    while stack:
        current = stack.pop()
        for bond in graph.adj.get(current, ()):
            if bond.metal:
                continue
            neighbour = bond.j
            expected = tuple(shifts[current][d] + bond.image[d] for d in range(3))
            if neighbour in shifts:
                if shifts[neighbour] != expected:
                    return None
                continue
            shifts[neighbour] = expected
            stack.append(neighbour)
    if len(shifts) != len(component):
        return None
    return shifts


def _cap_positions(
    graph: BondGraph, atom: int, count: int, existing_dirs: list[np.ndarray]
) -> list[np.ndarray]:
    """Directions for placeholder H atoms capping removed metal bonds."""
    directions: list[np.ndarray] = []
    for bond in graph.adj.get(atom, ()):
        if not bond.metal:
            continue
        vec = graph.cart[bond.j] + np.asarray(bond.image, dtype=float) @ graph.lattice
        unit = _normalize(vec - graph.cart[atom])
        if unit is not None:
            directions.append(unit)
    if not existing_dirs and not directions:  # pragma: no cover - isolated capped atom
        return [np.array([1.0, 0.0, 0.0]) for _ in range(count)]
    axis = directions[0] if directions else existing_dirs[0]
    b1, b2 = _perpendicular_basis(axis)
    while len(directions) < count:
        used = directions + list(existing_dirs)
        best = None
        for phi in np.linspace(0.0, 2.0 * np.pi, 24, endpoint=False):
            point = (
                np.cos(np.radians(109.47)) * axis
                + np.sin(np.radians(109.47)) * (np.cos(phi) * b1 + np.sin(phi) * b2)
            )
            separation = min((float(np.dot(point, other)) for other in used), default=-1.0)
            if best is None or separation < best[0]:
                best = (separation, point)
        directions.append(best[1])
    return directions[:count]


def _rdkit_positions(
    graph: BondGraph,
    demands: dict[int, HydrogenDemand],
) -> _RdkitResult:
    """Hydrogen positions from RDKit ``AddHs(addCoords=True)`` per fragment."""
    result = _RdkitResult()
    if not _RDKIT_AVAILABLE or not demands:
        return result
    targets = set(demands)
    components = _connected_components(graph, range(graph.n_atoms))
    for component in components:
        targets_here = [atom for atom in component if atom in targets]
        if not targets_here:
            continue
        if any(graph.metals[atom] for atom in component):
            continue  # non-metal bonds never link metals; defensive
        if len(component) == 1 and not any(
            not bond.metal for bond in graph.adj.get(component[0], ())
        ):
            # isolated atom (e.g. a mu3-O cluster oxygen left after cutting all
            # metal bonds): no molecular conformer to build, place it with the
            # VSEPR geometry fallback instead of a degenerate one-atom mol.
            continue
        result.fragments_total += 1
        try:
            positions = _rdkit_positions_for_fragment(graph, component, demands)
        except Exception as exc:  # noqa: BLE001 - fragment-level fallback
            result.fragments_failed += 1
            result.failures.append(
                f"片段 {sorted(component)[:6]}… RDKit 失败: {type(exc).__name__}: {exc}"
            )
            continue
        if positions is None:
            result.fragments_failed += 1
            result.failures.append(f"片段 {sorted(component)[:6]}… 周期性/价态校验不通过，改用几何法")
            continue
        result.fragments_ok += 1
        for atom, coords in positions.items():
            result.positions.setdefault(atom, []).extend(coords)
    return result


def _rdkit_positions_for_fragment(
    graph: BondGraph,
    component: list[int],
    demands: dict[int, HydrogenDemand],
) -> dict[int, list[np.ndarray]] | None:
    """Build a capped RDKit molecule for one fragment and harvest H coords."""
    assert Chem is not None and Point3D is not None
    shifts = _unwrap_component(graph, component)
    if shifts is None:
        return None
    component_set = set(component)
    index_of: dict[int, int] = {}
    mol = Chem.RWMol()
    for atom in component:
        mol.AddAtom(Chem.Atom(graph.symbols[atom]))
        index_of[atom] = mol.GetNumAtoms() - 1

    seen_bonds: set[tuple] = set()
    for atom in component:
        for bond in graph.adj.get(atom, ()):
            if bond.metal:
                continue
            if bond.j not in component_set:
                continue
            if bond.i > bond.j:
                continue
            bond_key = (bond.i, bond.j, tuple(bond.image))
            if bond_key in seen_bonds:
                continue
            seen_bonds.add(bond_key)
            order = float(bond.order)
            if order >= 2.5:
                bond_type = Chem.BondType.TRIPLE
            elif order >= 1.5:
                bond_type = Chem.BondType.DOUBLE
            else:
                bond_type = Chem.BondType.SINGLE
            mol.AddBond(index_of[bond.i], index_of[bond.j], bond_type)

    # Placeholder H atoms that cap the removed coordination bonds / anionic
    # heteroatoms, so that the fragment is a sane closed-shell molecule.
    caps: dict[int, int] = {}
    for atom in component:
        symbol = graph.symbols[atom]
        target = VALENCE.get(symbol)
        if symbol == "H" or target is None:
            continue
        base = float(sum(b.order for b in graph.adj.get(atom, ()) if not b.metal))
        demand = demands.get(atom)
        missing = demand.missing if demand is not None else 0
        if missing > 0:
            continue
        cap = int(round(max(0.0, target - base)))
        if cap > 0:
            caps[atom] = cap
    cap_mol_indices: list[tuple[int, int]] = []
    for atom, count in caps.items():
        for _ in range(count):
            mol.AddAtom(Chem.Atom("H"))
            cap_index = mol.GetNumAtoms() - 1
            mol.AddBond(index_of[atom], cap_index, Chem.BondType.SINGLE)
            cap_mol_indices.append((atom, cap_index))

    # Formal charges (only positive over-valence can occur after capping).
    for atom in component:
        symbol = graph.symbols[atom]
        target = VALENCE.get(symbol)
        if symbol == "H" or target is None:
            continue
        base = float(sum(b.order for b in graph.adj.get(atom, ()) if not b.metal))
        demand = demands.get(atom)
        missing = demand.missing if demand is not None else 0
        total = base + caps.get(atom, 0) + missing
        charge = int(round(total - target))
        if charge:
            mol.GetAtomWithIdx(index_of[atom]).SetFormalCharge(charge)

    molecule = mol.GetMol()
    conformer = Chem.Conformer(molecule.GetNumAtoms())
    conformer.Set3D(True)
    unwrapped: dict[int, np.ndarray] = {}
    for atom in component:
        cart = graph.cart[atom] + np.asarray(shifts[atom], dtype=float) @ graph.lattice
        unwrapped[atom] = cart
        conformer.SetAtomPosition(index_of[atom], Point3D(*[float(x) for x in cart]))
    for atom, cap_index in cap_mol_indices:
        count_already = sum(1 for a, _i in cap_mol_indices[: cap_mol_indices.index((atom, cap_index))] if a == atom)
        existing_dirs = [direction for _n, direction in graph.unit_directions(atom)]
        direction = _cap_positions(graph, atom, caps[atom], existing_dirs)[count_already]
        conformer.SetAtomPosition(
            cap_index, Point3D(*[float(x) for x in unwrapped[atom] + direction])
        )
    molecule.AddConformer(conformer)
    try:
        Chem.SanitizeMol(molecule)
    except Exception:  # noqa: BLE001 - fallback to geometry
        return None

    # Cross-check: RDKit's implicit H count must match the bond-order plan.
    for atom in component:
        demand = demands.get(atom)
        expected = demand.missing if demand is not None else 0
        got = int(molecule.GetAtomWithIdx(index_of[atom]).GetNumImplicitHs())
        if got != expected:
            return None

    with_h = Chem.AddHs(molecule, addCoords=True)
    conformer_with_h = with_h.GetConformer()
    inverse_lattice = np.linalg.inv(graph.lattice)
    positions: dict[int, list[np.ndarray]] = {}
    n_before = molecule.GetNumAtoms()
    for atom in with_h.GetAtoms():
        if atom.GetIdx() < n_before or atom.GetSymbol() != "H":
            continue
        neighbours = list(atom.GetNeighbors())
        if len(neighbours) != 1:
            return None
        parent = neighbours[0].GetIdx()
        parent_struct = next((a for a, idx in index_of.items() if idx == parent), None)
        if parent_struct is None or parent_struct not in demands:
            return None
        point = conformer_with_h.GetAtomPosition(atom.GetIdx())
        cart_unwrapped = np.array([point.x, point.y, point.z], dtype=float)
        cart_cell = cart_unwrapped - np.asarray(shifts[parent_struct], dtype=float) @ graph.lattice
        frac = cart_cell @ inverse_lattice
        positions.setdefault(parent_struct, []).append(np.mod(frac, 1.0))
    expected_total = sum(demands[a].missing for a in component if a in demands)
    if sum(len(v) for v in positions.values()) != expected_total:
        return None
    return positions


# ---------------------------------------------------------------------------
# Conflict evaluation
# ---------------------------------------------------------------------------
@dataclass
class _AtomCloud:
    """Fractional coordinates + chemistry labels of every atom in the cell."""

    frac: np.ndarray
    symbols: list[str]
    metals: list[bool]
    lattice: np.ndarray

    @classmethod
    def from_structure(cls, structure: Structure) -> "_AtomCloud":
        from cifkit.repair.bonds import is_metal, site_symbol

        return cls(
            frac=np.asarray(structure.frac_coords, dtype=float),
            symbols=[site_symbol(site) for site in structure],
            metals=[is_metal(site_symbol(site)) for site in structure],
            lattice=np.asarray(structure.lattice.matrix, dtype=float),
        )

    def append(self, frac: np.ndarray) -> int:
        self.frac = np.vstack([self.frac, np.asarray(frac, dtype=float).reshape(1, 3)])
        self.symbols.append("H")
        self.metals.append(False)
        return len(self.symbols) - 1


def _minimum_distances(cloud: _AtomCloud, positions: np.ndarray, skip_index: int) -> np.ndarray:
    """Minimum-image distance from each position to every atom in the cloud.

    Returns an array of shape ``(len(positions), len(cloud.frac))``; the column
    of ``skip_index`` (the H parent) is set to +inf.
    """
    if len(cloud.frac) == 0:
        return np.full((len(positions), 0), np.inf)
    offsets = _IMAGE_OFFSETS
    out = np.empty((len(positions), len(cloud.frac)), dtype=float)
    for i, position in enumerate(positions):
        delta = cloud.frac[None, :, :] - position[None, None, :] + offsets[:, None, :]
        carts = delta @ cloud.lattice
        distances = np.linalg.norm(carts, axis=2)
        out[i] = distances.min(axis=0)
    if skip_index is not None and 0 <= skip_index < out.shape[1]:
        out[:, skip_index] = np.inf
    return out


def _pair_category(symbol: str, metal: bool) -> str:
    if symbol == "H":
        return "H"
    if metal:
        return "metal"
    return "heavy"


def _evaluate_set(
    cloud: _AtomCloud,
    positions: np.ndarray,
    skip_index: int,
) -> tuple[bool, float, dict]:
    """Check one candidate hydrogen set; return (ok, margin_ratio, detail)."""
    okay = True
    margin = np.inf
    detail = {"min_hh": np.inf, "min_h_heavy": np.inf, "min_h_metal": np.inf, "violations": []}
    distances = _minimum_distances(cloud, positions, skip_index)
    for i in range(len(positions)):
        for j, symbol in enumerate(cloud.symbols):
            category = _pair_category(symbol, cloud.metals[j])
            distance = float(distances[i, j])
            if not np.isfinite(distance):
                continue
            key = {"H": "min_hh", "heavy": "min_h_heavy", "metal": "min_h_metal"}[category]
            detail[key] = min(detail[key], distance)
            margin = min(margin, distance / _PREFERRED_MIN[category])
            if distance < _HARD_MIN[category]:
                okay = False
                detail["violations"].append(
                    f"H{tuple(np.round(positions[i], 3))}–{symbol}{j} {distance:.2f} Å"
                )
    # pairwise between H atoms of the same set
    for i in range(len(positions)):
        for j in range(i + 1, len(positions)):
            delta = positions[i] - positions[j]
            delta -= np.round(delta)
            distance = float(np.linalg.norm(delta @ cloud.lattice))
            detail["min_hh"] = min(detail["min_hh"], distance)
            margin = min(margin, distance / _PREFERRED_MIN["H"])
            if distance < _HARD_MIN["H"]:
                okay = False
                detail["violations"].append(f"H–H {distance:.2f} Å")
    return okay, float(margin), detail


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def add_hydrogens(structure: Structure) -> tuple[Structure, dict]:
    """Complete missing hydrogens on a periodic structure.

    Returns ``(new_structure, stats)`` where ``stats`` contains counts,
    the route used, and any verification warnings.  The input structure is
    never modified.
    """
    graph = perceive_bonds(structure)
    demands_list = hydrogen_demand(graph)
    demands = {d.atom: d for d in demands_list if d.missing > 0}
    warnings: list[str] = list(graph.warnings)

    if not demands:
        stats = {
            "added_h": 0,
            "route": "none",
            "detail": "没有需要补的氢：所有原子价态已满足（no-op）",
            "by_parent_element": {},
            "h_types": {},
            "per_ligand_h": {},
            "rdkit": {"available": _RDKIT_AVAILABLE, "fragments_total": 0, "fragments_ok": 0, "fragments_failed": 0},
            "geometric": 0,
            "min_hh": None,
            "min_h_heavy": None,
            "min_h_metal": None,
            "c_valence_ok": True,
            "warnings": warnings,
        }
        return structure.copy(), stats

    rdkit_result = _rdkit_positions(graph, demands)
    warnings.extend(rdkit_result.failures)

    cloud = _AtomCloud.from_structure(structure)
    placed: list[tuple[int, np.ndarray]] = []  # (parent atom, frac coords)
    route_counter = Counter()
    min_distances = {"H": np.inf, "heavy": np.inf, "metal": np.inf}

    for atom in sorted(demands):
        demand = demands[atom]
        candidate_sets: list[tuple[str, list[np.ndarray], list[np.ndarray]]] = []
        rdkit_fracs = rdkit_result.positions.get(atom, [])
        if len(rdkit_fracs) == demand.missing:
            # RDKit works in cartesian space; candidates are cell fractional.
            candidate_sets.append(("rdkit", list(rdkit_fracs), []))
        for directions in _geometric_candidate_sets(graph, demand):
            fracs = []
            for direction in directions:
                cart = graph.cart[atom] + demand_h_bond_length(demand.symbol) * direction
                frac = cart @ np.linalg.inv(graph.lattice)
                fracs.append(np.mod(frac, 1.0))
            candidate_sets.append(("geometric", fracs, directions))

        best = None
        for route, fracs, _directions in candidate_sets:
            positions = np.asarray(fracs, dtype=float)
            okay, margin, detail = _evaluate_set(cloud, positions, atom)
            score = (0 if okay else 1, -margin)
            if best is None or score < best[0]:
                best = (score, route, positions, detail, okay)
        if best is None:  # pragma: no cover - defensive
            continue
        _score, route, positions, detail, okay = best
        if not okay:
            warnings.append(
                f"原子 {atom}({demand.symbol}) 补 H 未能完全避开冲突: "
                + "; ".join(detail["violations"][:3])
            )
        route_counter[route] += 1
        for key, label in (("min_hh", "H"), ("min_h_heavy", "heavy"), ("min_h_metal", "metal")):
            if np.isfinite(detail[key]):
                min_distances[label] = min(min_distances[label], detail[key])
        for frac in positions:
            cloud.append(frac)
            placed.append((atom, frac))

    # ----- build the new structure --------------------------------------
    new_structure = structure.copy()
    for _parent, frac in placed:
        new_structure.append("H", frac, coords_are_cartesian=False, validate_proximity=False)
    ensure_unique_labels(new_structure)

    # ----- verification --------------------------------------------------
    by_parent_element: Counter = Counter(graph.symbols[atom] for atom in demands)
    h_types: Counter = Counter()
    for atom, demand in demands.items():
        suffix = f"H{demand.missing}" if demand.missing > 1 else "H"
        h_types[f"{demand.hybrid} {demand.symbol}-{suffix}"] += demand.missing
    per_ligand: Counter = Counter()
    components = _connected_components(graph, range(graph.n_atoms))
    for component in components:
        if any(graph.metals[atom] for atom in component):
            continue
        count = sum(1 for parent, _f in placed if parent in component)
        if count:
            per_ligand[count] += 1
    valence_errors = []
    for atom in range(graph.n_atoms):
        symbol = graph.symbols[atom]
        if symbol != "C":
            continue
        expected = VALENCE["C"]
        final_sum = graph.order_sum(atom) + sum(1 for parent, _f in placed if parent == atom)
        if abs(final_sum - expected) > 0.01:
            valence_errors.append(f"C{atom} 键级和 {final_sum:.2f} != {expected}")
    c_valence_ok = not valence_errors
    if valence_errors:
        warnings.extend(valence_errors[:8])

    # Mean C–H bond length sanity (only for H placed on carbon).
    ch_lengths = []
    lattice = np.asarray(new_structure.lattice.matrix, dtype=float)
    for parent, frac in placed:
        if graph.symbols[parent] != "C":
            continue
        delta = frac - new_structure[parent].frac_coords
        delta -= np.round(delta)
        ch_lengths.append(float(np.linalg.norm(delta @ lattice)))

    routes = {route for route, count in route_counter.items() if count}
    if routes == {"rdkit"}:
        route = "rdkit-capped"
    elif routes == {"geometric"}:
        route = "geometric-vsepr"
    else:
        route = "mixed (rdkit-capped + geometric-vsepr)"
    detail = (
        f"补氢：新增 {len(placed)} 个 H "
        f"（{dict(h_types)}；路线 {route}；"
        f"RDKit 片段 {rdkit_result.fragments_ok}/{rdkit_result.fragments_total} 成功；"
        f"每个有机片段补 H 数量分布 {dict(sorted(per_ligand.items()))}）"
    )
    if ch_lengths:
        detail += f"；C–H 键长 {min(ch_lengths):.3f}–{max(ch_lengths):.3f} Å"
    if np.isfinite(min_distances["H"]):
        detail += f"；最小 H···H {min_distances['H']:.2f} Å"
    if np.isfinite(min_distances["heavy"]):
        detail += f"；最小 H···重原子 {min_distances['heavy']:.2f} Å"
    if np.isfinite(min_distances["metal"]):
        detail += f"；最小 H···金属 {min_distances['metal']:.2f} Å"

    stats = {
        "added_h": len(placed),
        "route": route,
        "detail": detail,
        "by_parent_element": {symbol: int(count) for symbol, count in by_parent_element.items()},
        "h_types": {label: int(count) for label, count in h_types.items()},
        "per_ligand_h": {int(count): int(fragments) for count, fragments in per_ligand.items()},
        "rdkit": {
            "available": _RDKIT_AVAILABLE,
            "fragments_total": rdkit_result.fragments_total,
            "fragments_ok": rdkit_result.fragments_ok,
            "fragments_failed": rdkit_result.fragments_failed,
        },
        "geometric": int(route_counter.get("geometric", 0)),
        "min_hh": _finite_or_none(min_distances["H"]),
        "min_h_heavy": _finite_or_none(min_distances["heavy"]),
        "min_h_metal": _finite_or_none(min_distances["metal"]),
        "c_valence_ok": c_valence_ok,
        "warnings": warnings,
    }
    return new_structure, stats


def demand_h_bond_length(symbol: str) -> float:
    """X–H bond length used for placement."""
    return H_BOND_LENGTH.get(symbol, 1.09)


def _finite_or_none(value: float):
    return float(value) if np.isfinite(value) else None
