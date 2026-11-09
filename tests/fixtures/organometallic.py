"""Organometallic fixtures with chemically correct geometry (C3).

* ferrocene: D5d, Fe–C = 2.04, C–C = 1.41, C–H = 1.09 (H in the ring plane)
* dimethylzinc: linear C–Zn–C, Zn–C = 1.95, tetrahedral CH3 (C–H = 1.09)
* carboxylate control: Zr···C through-space at 3.2 A must NOT be a bond
"""
from __future__ import annotations

import numpy as np
from pymatgen.core import Lattice, Structure

BOX = 22.0


def _unit(vec) -> np.ndarray:
    vec = np.asarray(vec, dtype=float)
    return vec / np.linalg.norm(vec)


def _basis(axis) -> tuple[np.ndarray, np.ndarray]:
    axis = _unit(axis)
    helper = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = _unit(np.cross(axis, helper))
    e2 = np.cross(axis, e1)
    return e1, e2


def cp_ring(center, axis, *, radius=1.195, ch=1.09, stagger=0.0):
    """Cyclopentadienyl ring: 5 C + 5 H, hydrogens in the ring plane."""
    axis = _unit(axis)
    e1, e2 = _basis(axis)
    coords, species = [], []
    for k in range(5):
        angle = 2 * np.pi * k / 5 + stagger
        radial = np.cos(angle) * e1 + np.sin(angle) * e2
        carbon = np.asarray(center, float) + radius * radial
        coords.append(carbon); species.append("C")
        coords.append(carbon + ch * radial); species.append("H")
    return coords, species


def ferrocene(*, centroid=1.65, ring_radius=1.195) -> Structure:
    """Idealised D5d ferrocene: ring centroid 1.65 A from Fe → Fe–C ~ 2.04 A."""
    coords, species = [[0.0, 0.0, 0.0]], ["Fe"]
    for sign in (1, -1):
        ring, ring_species = cp_ring((0, 0, sign * centroid), (0, 0, 1),
                                     radius=ring_radius,
                                     stagger=0.0 if sign > 0 else np.pi / 5)
        coords += ring
        species += ring_species
    return Structure(Lattice.cubic(BOX), species, coords, coords_are_cartesian=True)


def dimethylzinc(*, zn_c=1.95, ch=1.09) -> Structure:
    coords, species = [[0.0, 0.0, 0.0]], ["Zn"]
    for sign in (1, -1):
        axis = np.array([sign, 0.0, 0.0])
        carbon = np.asarray([sign * zn_c, 0.0, 0.0])
        coords.append(carbon); species.append("C")
        e1, e2 = _basis(axis)
        # three H at the tetrahedral angle from the Zn–C axis
        theta = np.deg2rad(109.47)
        for k in range(3):
            angle = 2 * np.pi * k / 3
            direction = (np.cos(theta) * _unit(axis)
                         + np.sin(theta) * (np.cos(angle) * e1 + np.sin(angle) * e2))
            coords.append(carbon + ch * direction); species.append("H")
    return Structure(Lattice.cubic(BOX), species, coords, coords_are_cartesian=True)


def carboxylate_like(*, zr_c=3.20) -> Structure:
    """Zr next to an acetate group (RCOO⁻) at a chosen Zr...C distance.

    The carboxylate carbon carries its full complement (C–O, C=O, C–CH3), i.e.
    valence 4, which is exactly why a short Zr...C contact there must **not** be
    read as a carbon sigma bond (see the valence guard in ``perceive_bonds``).
    """
    coords = [[0.0, 0.0, 0.0],              # Zr
              [zr_c, 0.0, 0.0],             # carboxylate C
              [zr_c + 1.25, 0.10, 0.0],     # O (single)
              [zr_c - 0.20, 1.15, 0.0],     # O (double)
              [zr_c, -1.50, 0.0]]           # methyl C (the R group)
    species = ["Zr", "C", "O", "O", "C"]
    return Structure(Lattice.cubic(BOX), species, coords, coords_are_cartesian=True)


def _report(name: str, structure: Structure) -> None:
    from cifkit.repair.bonds import hydrogen_demand, perceive_bonds

    graph = perceive_bonds(structure)
    unique = graph.unique_bonds()
    metal_c = [b for b in unique if b.organometallic]
    h_added = sum(max(0, d.missing) for d in hydrogen_demand(graph))
    print(f"== {name}: atoms={graph.n_atoms} M–C bonds={len(metal_c)} "
          f"H that would be added={h_added:g}")
    for b in metal_c[:4]:
        print(f"     {graph.symbols[b.i]}–{graph.symbols[b.j]} {b.distance:.3f} A")
    for atom, symbol in enumerate(graph.symbols):
        if symbol == "C":
            print(f"     C{atom}: order_sum={graph.order_sum(atom):g} "
                  f"H={graph.h_neighbor_count(atom)}")
    for warning in graph.warnings[:2]:
        print("     warn:", warning)


if __name__ == "__main__":
    fe = ferrocene()
    fe_c = sorted(float(((s.coords - fe[0].coords) ** 2).sum() ** 0.5)
                  for s in fe if s.species_string == "C")
    print(f"   (fixture check: Fe–C = {fe_c[0]:.3f}-{fe_c[-1]:.3f} A, expect ~2.04)")
    _report("ferrocene", fe)
    _report("dimethylzinc", dimethylzinc())
    _report("carboxylate-control (Zr...C 3.20 A)", carboxylate_like())
    _report("carboxylate-control (Zr...C 2.55 A, still > window)",
            carboxylate_like(zr_c=2.55))
