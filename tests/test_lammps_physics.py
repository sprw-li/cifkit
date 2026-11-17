"""LAMMPS physics cross-check (round 57).

"Accepted by LAMMPS" and "the physics is right" are different claims.  These tests pin
the second one: an independent LJ evaluation over the **shipped data file** must
reproduce the energy LAMMPS reported for the same parameters (cloud job 060f75f5,
LAMMPS 7 Feb 2024; the numbers are the ``Energy initial`` line of the minimisation in
``runs/cloud_h3/real_physics2/realphysics_probe.json`` at the unrelaxed coordinates).

They also pin the evaluator itself against hand-computable cases, because a reference
implementation that is wrong in the same way as nothing else is worse than useless.
Those cases are small cells on purpose: only there do *self-images* (an atom's
interaction with its own periodic images) and the body-diagonal lattice shifts change
the answer at a level a hand enumeration can hold to ``rel=1e-9``.
"""
from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

import numpy as np
import pytest
from pymatgen.core import Lattice, Structure

from cifkit.lammps_data import read_data_lammps
from cifkit.lammps_reference import (compare_with_lammps, lj_cut_energy,
                                     lj_cut_energy_per_atom)

ROOT = Path(__file__).resolve().parents[1]
PARAMS = {"epsilon_ev": 0.0103, "sigma_a": 3.4, "cutoff_a": 10.0}
#: the reference reproduces the recorded LAMMPS energies to ~1e-12 relative; 1e-8 is
#: loose enough for summation-order differences and tight enough to catch a broken
#: image enumerator (the body-diagonal shift bug was 1.5e-7 on mof5, and an
#: rtol=1e-5 gate passed it).
RTOL = 1e-8


def _pair_energy(r: float, epsilon_ev: float, sigma_a: float, cutoff_a: float) -> float:
    if not 0.0 < r < cutoff_a:
        return 0.0
    x6 = (sigma_a / r) ** 6
    return 4.0 * epsilon_ev * (x6 * x6 - x6)


def _hand_lattice_sum(cart: np.ndarray, lattice: np.ndarray, **params) -> float:
    """Explicit periodic lattice sum, independent of ``cifkit.lammps_reference``.

    ``E = sum_{i<j} sum_m v(|r_i - r_j + m L|) + (n/2) sum_{m!=0} v(|m L|)``: every
    unordered pair - including an atom and its own images - is counted once.
    """
    n = len(cart)
    energy = 0.0
    for m in itertools.product(range(-2, 3), repeat=3):
        shift = np.array(m, dtype=float) @ lattice
        for i in range(n):
            for j in range(i + 1, n):
                energy += _pair_energy(float(np.linalg.norm(cart[i] - cart[j] - shift)),
                                       **params)
        if m != (0, 0, 0) and n:
            energy += 0.5 * n * _pair_energy(float(np.linalg.norm(shift)), **params)
    return energy


# ------------------------------------------------------------------ the evaluator
def test_single_pair_matches_the_lj_formula():
    """Two atoms 4 A apart in a huge box: E = 4*eps*((sigma/r)^12 - (sigma/r)^6)."""
    structure = Structure(Lattice.cubic(100.0), ["C", "C"],
                          [[0, 0, 0], [4.0, 0, 0]], coords_are_cartesian=True)
    expected = 4 * 0.0103 * ((3.4 / 4.0) ** 12 - (3.4 / 4.0) ** 6)
    assert lj_cut_energy(structure, **PARAMS) == pytest.approx(expected, rel=1e-12)


def test_pairs_beyond_the_cutoff_contribute_nothing():
    structure = Structure(Lattice.cubic(100.0), ["C", "C"],
                          [[0, 0, 0], [12.0, 0, 0]], coords_are_cartesian=True)
    assert lj_cut_energy(structure, **PARAMS) == pytest.approx(0.0, abs=1e-12)


def test_periodic_images_are_counted():
    """Images and self-images must move a 6 A cell's energy by an absolute margin.

    The 0.87 A contact dominates (5.5e5 eV), so a *relative* comparison against the
    single-pair value is meaningless: the whole periodic correction is ~2e-2 eV, i.e.
    ~4e-8 of the total.  An absolute margin is what can be falsified here - if images
    were skipped the difference would be exactly zero.  (The image terms are
    attractive at these separations, so the periodic total sits *below* the single-pair
    value; ``test_minimum_image_contact_is_hand_computed`` pins the strict ``>`` case.)
    """
    structure = Structure(Lattice.cubic(6.0), ["C", "C"],
                          [[0, 0, 0], [0.5, 0.5, 0.5]], coords_are_cartesian=True)
    energy = lj_cut_energy(structure, **PARAMS)
    assert energy > 0, "a 0.87 A separation is strongly repulsive"
    distance = math.sqrt(0.75)
    single = 4 * PARAMS["epsilon_ev"] * ((PARAMS["sigma_a"] / distance) ** 12
                                         - (PARAMS["sigma_a"] / distance) ** 6)
    assert abs(energy - single) > 1e-3, (
        "images must contribute ~2e-2 eV here; a difference of zero would mean they "
        "were skipped")


def test_minimum_image_contact_is_hand_computed():
    """6 A cube, C at x=0 and x=5.5: the nearest *image* is the 0.5 A contact.

    The direct pair (5.5 A) is mildly attractive while the minimum-image pair (0.5 A)
    is ~4e8 eV repulsive, so the periodic energy is 8+ orders of magnitude above the
    direct-pair value.  The expectation is enumerated by hand - including the
    self-images and every shift inside the cutoff - and held to ``rel=1e-9``; any
    missing image changes the answer by more than that.
    """
    lattice = np.diag([6.0, 6.0, 6.0])
    cart = np.array([[0.0, 0.0, 0.0], [5.5, 0.0, 0.0]])
    structure = Structure(Lattice(lattice), ["C", "C"], cart, coords_are_cartesian=True)
    energy = lj_cut_energy(structure, **PARAMS)
    expected = _hand_lattice_sum(cart, lattice, **PARAMS)
    direct = _pair_energy(5.5, **PARAMS)
    assert direct < 0, "the 5.5 A pair alone is attractive"
    assert expected > 1e8, f"the 0.5 A image must dominate, got {expected}"
    assert energy == pytest.approx(expected, rel=1e-9)
    assert energy > direct + 1e5, "images must dominate the direct pair"


def test_self_image_of_a_single_atom_is_counted():
    """One C in a 6 A cube: the entire energy is its interaction with its own images.

    With a 10 A cutoff only the six 6 A images and the twelve 8.49 A body diagonals
    are inside it, so E = 3*v(6.0) + 6*v(8.48528137423857) = -4.9758e-3 eV.  Dropping
    self-images (a plain ``i < j`` enumeration over all shifts) returns 0.0.
    """
    structure = Structure(Lattice.cubic(6.0), ["C"], [[0.0, 0.0, 0.0]],
                          coords_are_cartesian=True)
    energy = lj_cut_energy(structure, **PARAMS)
    expected = (3 * _pair_energy(6.0, **PARAMS)
                + 6 * _pair_energy(math.sqrt(72.0), **PARAMS))
    assert expected < -1e-3
    assert energy == pytest.approx(expected, rel=1e-12)
    assert energy == pytest.approx(_hand_lattice_sum(np.zeros((1, 3)), np.diag([6.0] * 3),
                                                     **PARAMS), rel=1e-12)


def test_energy_scales_with_epsilon():
    structure = Structure(Lattice.cubic(20.0), ["C", "C"],
                          [[0, 0, 0], [3.5, 0, 0]], coords_are_cartesian=True)
    base = lj_cut_energy(structure, **PARAMS)
    doubled = lj_cut_energy(structure, **{**PARAMS, "epsilon_ev": 2 * PARAMS["epsilon_ev"]})
    assert doubled == pytest.approx(2 * base, rel=1e-12)


def test_per_atom_helper():
    structure = Structure(Lattice.cubic(20.0), ["C", "C"],
                          [[0, 0, 0], [3.5, 0, 0]], coords_are_cartesian=True)
    assert (lj_cut_energy_per_atom(structure, **PARAMS)
            == pytest.approx(lj_cut_energy(structure, **PARAMS) / 2))


# --------------------------------------------------------------- the data parser
def test_data_lammps_parser_reads_the_shipped_file():
    path = ROOT / "cloud_lj" / "data" / "lammps__terephthalic_acid_hfree" / "data.lammps"
    if not path.is_file():
        pytest.skip("LAMMPS check bundle not present")
    lattice, positions, types = read_data_lammps(path)
    assert len(positions) == 16
    assert len(types) == 16
    assert np.linalg.det(lattice) > 0
    assert set(types) == {1, 2, 3}


# ------------------------------------------------------- the cross-code agreement
def test_shipped_files_reproduce_lammps_energies():
    """The real check: LAMMPS's own numbers vs an independent evaluation.

    All three shipped cells are larger than the 10 A cutoff, so self-images are absent;
    what this pins (at 1e-8) is the distinct-pair image enumeration, including the
    body-diagonal shifts of the cubic cells - the bug that made the old rtol=1e-5
    gate pass with mof5 off by 1.5e-7.
    """
    recorded = {
        "lammps__hkust1_hfree": 409124.98253649,
        "lammps__mof5_hfree": 173145.377770684,
        "lammps__terephthalic_acid_hfree": 178719.393379894,
    }
    checked = 0
    for case, energy in recorded.items():
        path = ROOT / "cloud_lj" / "data" / case / "data.lammps"
        if not path.is_file():
            continue
        lattice, positions, _types = read_data_lammps(path)
        structure = Structure(Lattice(lattice), ["C"] * len(positions), positions,
                              coords_are_cartesian=True)
        verdict = compare_with_lammps(structure, lammps_energy=energy, **PARAMS,
                                      rtol=RTOL)
        assert verdict["match"], verdict
        checked += 1
    if not checked:
        pytest.skip("no LAMMPS check bundle")


def test_recorded_gate_report_passes():
    path = ROOT / "runs" / "lammps_physics.json"
    if not path.is_file():
        pytest.skip("physics gate not run in this checkout")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert len(payload["cases"]) >= 3
    for row in payload["cases"]:
        assert row["relative"] <= payload["rtol"], row


def test_a_wrong_energy_is_rejected():
    """The comparison must actually fail when the numbers disagree."""
    path = ROOT / "cloud_lj" / "data" / "lammps__terephthalic_acid_hfree" / "data.lammps"
    if not path.is_file():
        pytest.skip("LAMMPS check bundle not present")
    lattice, positions, _types = read_data_lammps(path)
    structure = Structure(Lattice(lattice), ["C"] * len(positions), positions,
                          coords_are_cartesian=True)
    # 100 eV vs 1.8e5 eV: unambiguously wrong
    verdict = compare_with_lammps(structure, lammps_energy=100.0, **PARAMS, rtol=RTOL)
    assert not verdict["match"]
    assert abs(verdict["difference_eV"]) > 1.0
