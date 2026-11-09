"""Organometallic metal–carbon bonds (limitation C3).

The repair layer used to ignore *all* metal–carbon contacts to avoid the
carboxylate through-space artefacts, which meant a Cp or methyl carbon looked
under-coordinated and got capped with bogus hydrogens.  These tests pin the new
behaviour: tight-distance M–C sigma bonds are perceived (and counted in the carbon
valence), through-space contacts are still rejected.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from pymatgen.core import Lattice, Structure

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from organometallic import carboxylate_like, dimethylzinc, ferrocene  # noqa: E402

from cifkit.repair.bonds import (  # noqa: E402
    ORGANOMETALLIC_MAX_DISTANCE,
    VALENCE,
    hydrogen_demand,
    organometallic_limit,
    perceive_bonds,
)

DATA = Path(__file__).resolve().parent / "data"
ZIF8 = DATA / "zif8_cr_sod.cif"


def _metal_c_bonds(graph):
    return [b for b in graph.unique_bonds() if b.organometallic]


def test_ferrocene_metal_carbon_bonds_are_perceived():
    graph = perceive_bonds(ferrocene())
    bonds = _metal_c_bonds(graph)
    assert len(bonds) == 10, "one Fe–C bond per ring carbon"
    assert graph.organometallic_bonds == 10
    assert all(1.9 < b.distance < 2.2 for b in bonds)
    assert any("有机金属" in w for w in graph.warnings)


def test_ferrocene_gets_no_bogus_hydrogen():
    """The regression that motivated C3: previously 8 H were added to ferrocene."""
    graph = perceive_bonds(ferrocene())
    assert sum(max(0, d.missing) for d in hydrogen_demand(graph)) == 0
    for atom, symbol in enumerate(graph.symbols):
        if symbol == "C":
            assert graph.order_sum(atom) == pytest.approx(4.0), atom
            assert graph.h_neighbor_count(atom) == 1


def test_dimethylzinc_methyl_is_not_hydrogenated():
    graph = perceive_bonds(dimethylzinc())
    assert len(_metal_c_bonds(graph)) == 2
    carbons = [a for a, s in enumerate(graph.symbols) if s == "C"]
    assert all(graph.order_sum(a) == pytest.approx(4.0) for a in carbons)
    assert sum(max(0, d.missing) for d in hydrogen_demand(graph)) == 0


@pytest.mark.parametrize("distance", [2.80, 3.20])
def test_carboxylate_through_space_contact_is_not_a_bond(distance):
    graph = perceive_bonds(carboxylate_like(zr_c=distance))
    assert _metal_c_bonds(graph) == []
    assert graph.organometallic_bonds == 0


def test_organometallic_window_is_tight_but_covers_real_bonds():
    assert ORGANOMETALLIC_MAX_DISTANCE == pytest.approx(2.65)
    # real sigma bonds (Cp/alkyl/carbonyl/Grignard) must be inside the window
    for metal, expected in (("Fe", 2.04), ("Zn", 1.95), ("Cr", 1.92), ("Mg", 2.15)):
        assert expected < organometallic_limit(metal), metal
    # a carboxylate contact must be outside it
    assert organometallic_limit("Zr") < 2.80


def test_window_boundary_is_enforced():
    """Just inside the window is a bond; just outside it is not.

    The window is ``min(max(1.02*(r_M+r_C), 2.30), 2.65)`` so this uses the
    computed limit rather than a hard-coded number.
    """
    limit = organometallic_limit("Zr")
    assert limit <= ORGANOMETALLIC_MAX_DISTANCE

    def pair(distance: float):
        return Structure(Lattice.cubic(22.0), ["Zr", "C"],
                         [[0, 0, 0], [distance, 0, 0]], coords_are_cartesian=True)

    assert len(_metal_c_bonds(perceive_bonds(pair(limit - 0.02)))) == 1
    assert _metal_c_bonds(perceive_bonds(pair(limit + 0.02))) == []
    # and well beyond the window (real carboxylate distance) there is never a bond
    assert _metal_c_bonds(perceive_bonds(pair(3.20))) == []


def test_saturated_carbon_is_not_bonded_even_inside_the_window():
    """Valence guard: a CO2-like carbon already has valence 4 → no Zr–C bond."""
    structure = carboxylate_like(zr_c=2.50)   # inside the distance window
    graph = perceive_bonds(structure)
    assert _metal_c_bonds(graph) == []
    assert any("饱和" in w or "σ" in w for w in graph.warnings)


def test_zif8_has_no_false_positive_metal_carbon_bonds():
    """A real Zn–N MOF must not gain any Zn–C bond."""
    structure = Structure.from_file(str(ZIF8))
    graph = perceive_bonds(structure)
    assert graph.organometallic_bonds == 0
    assert _metal_c_bonds(graph) == []
    # and the previously verified chemistry is unchanged: no atom exceeds its
    # valence, except a metal-coordinated heteroatom which may be written as X+
    for atom in range(graph.n_atoms):
        allowance = VALENCE.get(graph.symbols[atom], 4)
        if graph.metal_bond_count(atom):
            allowance += 1.0
        assert graph.order_sum(atom) <= allowance + 1e-6, (atom, graph.symbols[atom],
                                                           graph.order_sum(atom))


def test_odd_ring_kekule_never_exceeds_valence():
    """A bare cyclopentadienyl ring (odd cycle, no metal): the post-condition holds.

    Every carbon needs one ring pi bond, which is impossible in a 5-cycle; the
    code must either keep valence <= 4 or fall back to a fractional pi bond, and it
    must say what it did instead of silently over-filling a carbon.
    """
    from organometallic import cp_ring  # noqa: PLC0415

    coords, species = cp_ring((0, 0, 0), (0, 0, 1))
    structure = Structure(Lattice.cubic(22.0), species, coords, coords_are_cartesian=True)
    graph = perceive_bonds(structure)
    for atom in range(graph.n_atoms):
        assert graph.order_sum(atom) <= 4.0 + 1e-6, (atom, graph.order_sum(atom))
    assert any("Kekulé" in w or "π" in w for w in graph.warnings), graph.warnings


def test_metal_coordinated_heteroatom_may_carry_the_ring_pi_bond():
    """ZIF-8 regression: Zn–N imidazolate is written as Zn–N+=C, with no warning."""
    structure = Structure.from_file(str(ZIF8))
    graph = perceive_bonds(structure)
    assert graph.warnings == [], graph.warnings
    nitrogens = [a for a, s in enumerate(graph.symbols) if s == "N"]
    assert any(graph.order_sum(a) == pytest.approx(4.0) for a in nitrogens), \
        "at least one Zn–N must carry the ring pi bond"


def test_arene_chromium_contact_still_saturates_carbon():
    """eta6 benzene on Cr: C already has 3 bonds, the Cr contact supplies the 4th."""
    from organometallic import _basis  # noqa: PLC0415

    e1, e2 = _basis((0, 0, 1))
    coords, species = [[0.0, 0.0, 0.0]], ["Cr"]
    for k in range(6):
        angle = 2 * np.pi * k / 6
        radial = np.cos(angle) * e1 + np.sin(angle) * e2
        carbon = np.array([1.42 * radial[0], 1.42 * radial[1], 1.70])
        coords.append(carbon); species.append("C")
        coords.append(carbon + 1.09 * radial); species.append("H")
    structure = Structure(Lattice.cubic(22.0), species, coords, coords_are_cartesian=True)
    graph = perceive_bonds(structure)
    assert graph.organometallic_bonds >= 6
    assert sum(max(0, d.missing) for d in hydrogen_demand(graph)) == 0


def test_repair_end_to_end_adds_no_hydrogen():
    """The real repair entry point must leave organometallics alone."""
    from cifkit.repair import repair_all

    for structure in (ferrocene(), dimethylzinc()):
        before = len(structure)
        repaired, report = repair_all(structure, add_hydrogen=True)
        assert len(repaired) == before, "no atoms may be added"
        assert report.added_h == 0, report.added_h
