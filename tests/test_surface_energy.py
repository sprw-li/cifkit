"""Surface-energy arithmetic (round 49, limitation D3).

Getting the convention right is the whole point, so the tests check the formula
against hand-computed values and — more importantly — that the *inconsistent* inputs
people actually supply are rejected instead of silently producing a number.
"""
from __future__ import annotations

import pytest

from cifkit.surface_energy import (EV_PER_ANGSTROM2_TO_J_PER_M2, render_markdown,
                                   surface_energy)


def test_formula_matches_hand_computation():
    # excess = -100 - 32*(-5) = 60 eV over 2*100 A^2 -> 0.30 eV/A^2
    result = surface_energy(e_slab=-100.0, n_slab=32, area_a2=100.0, e_bulk_per_atom=-5.0)
    assert result.excess_ev == pytest.approx(60.0)
    assert result.e_surf_ev_per_a2 == pytest.approx(0.30)
    assert result.e_surf_mev_per_a2 == pytest.approx(300.0)
    assert result.e_surf_j_per_m2 == pytest.approx(0.30 * EV_PER_ANGSTROM2_TO_J_PER_M2)


def test_unit_constant_is_the_codata_value():
    assert EV_PER_ANGSTROM2_TO_J_PER_M2 == pytest.approx(16.02176634, rel=1e-9)


def test_bulk_total_plus_atom_count_is_accepted():
    a = surface_energy(e_slab=-100.0, n_slab=32, area_a2=100.0, e_bulk_per_atom=-5.0)
    b = surface_energy(e_slab=-100.0, n_slab=32, area_a2=100.0, e_bulk_total=-80.0, n_bulk=16)
    assert a.e_surf_ev_per_a2 == pytest.approx(b.e_surf_ev_per_a2)


def test_disagreeing_bulk_references_are_rejected():
    with pytest.raises(ValueError, match="disagrees"):
        surface_energy(e_slab=-100.0, n_slab=32, area_a2=100.0,
                       e_bulk_per_atom=-5.0, e_bulk_total=-100.0, n_bulk=16)


def test_asymmetric_slab_counts_one_surface():
    one = surface_energy(e_slab=-100.0, n_slab=32, area_a2=100.0,
                         e_bulk_per_atom=-5.0, surfaces=1)
    two = surface_energy(e_slab=-100.0, n_slab=32, area_a2=100.0,
                         e_bulk_per_atom=-5.0, surfaces=2)
    assert one.e_surf_ev_per_a2 == pytest.approx(2 * two.e_surf_ev_per_a2)


def test_stoichiometry_mismatch_is_rejected():
    """Subtracting a bulk reference of a different composition is the classic error."""
    with pytest.raises(ValueError, match="integer multiple"):
        surface_energy(e_slab=-100.0, n_slab=32, area_a2=100.0, e_bulk_per_atom=-5.0,
                       slab_formula={"Zn": 4, "O": 4, "C": 8},
                       bulk_formula={"Zn": 4, "O": 4})


def test_matching_stoichiometry_is_accepted():
    result = surface_energy(e_slab=-100.0, n_slab=32, area_a2=100.0, e_bulk_per_atom=-5.0,
                            slab_formula={"ZnO": 2}, bulk_formula={"ZnO": 1})
    assert result.e_surf_ev_per_a2 == pytest.approx(0.30)


@pytest.mark.parametrize("kwargs", [
    {"e_slab": 1.0, "n_slab": 0, "area_a2": 10.0, "e_bulk_per_atom": -1.0},
    {"e_slab": 1.0, "n_slab": 10, "area_a2": 0.0, "e_bulk_per_atom": -1.0},
    {"e_slab": 1.0, "n_slab": 10, "area_a2": 10.0, "e_bulk_per_atom": -1.0, "surfaces": 3},
])
def test_invalid_inputs_raise(kwargs):
    with pytest.raises(ValueError):
        surface_energy(**kwargs)


def test_missing_bulk_reference_raises():
    with pytest.raises(ValueError, match="give either"):
        surface_energy(e_slab=1.0, n_slab=10, area_a2=10.0)


def test_negative_surface_energy_is_reported_not_hidden():
    """A bulk reference that is too *shallow* makes E_surf negative: a warning sign."""
    # excess = -100 - 32*(-3) = -4 eV -> -0.02 eV/A^2
    result = surface_energy(e_slab=-100.0, n_slab=32, area_a2=100.0, e_bulk_per_atom=-3.0)
    assert result.excess_ev == pytest.approx(-4.0)
    assert result.e_surf_ev_per_a2 < 0
    assert "converged" in result.note


def test_markdown_states_both_units_and_the_caveat():
    result = surface_energy(e_slab=-100.0, n_slab=32, area_a2=100.0, e_bulk_per_atom=-5.0)
    text = render_markdown(result, title="ZnO(0001)")
    assert "ZnO(0001)" in text
    assert "J/m²" in text and "meV/Å²" in text
    assert "converged" in text
