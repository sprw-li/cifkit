"""Export fidelity gate: geometry, not just atom count (round 44).

Round 44 raised ``verify_formats`` from "the reader saw 138 atoms" to "the reader
recovered the same geometry", with two comparison modes:

* periodic read-back whose lattice matches the source → ``StructureMatcher``;
* lattice-free read-back (xyz/mol/sdf/turbomole/lammps) → sorted pairwise-distance
  fingerprint, because ASE invents a meaningless bounding-box cell there.

These tests pin both modes plus the traps found while building it: a *synthetic*
cell must not trigger periodic matching, and a displaced structure must fail.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from cifkit.export.geometry_check import LOOSE_TOLERANCE, compare

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "data" / "terephthalic_acid_hfree.cif"


@pytest.fixture(scope="module")
def structure() -> Structure:
    return Structure.from_file(FIXTURE)


def test_identical_structure_passes(structure):
    verdict = compare(structure, structure.copy(), "cif")
    assert verdict.ok and verdict.periodic
    assert verdict.max_deviation < 1e-9


def test_tiny_perturbation_is_within_the_tolerance(structure):
    other = structure.copy()
    other.translate_sites(0, [1e-5, 0, 0], frac_coords=False)
    verdict = compare(structure, other, "cif")
    assert verdict.ok, verdict.detail


def test_large_displacement_fails(structure):
    other = structure.copy()
    other.translate_sites(0, [0.5, 0, 0], frac_coords=False)
    verdict = compare(structure, other, "cif")
    assert not verdict.ok


def test_wrong_lattice_fails(structure):
    other = structure.copy()
    other.lattice = Lattice.cubic(structure.lattice.a * 1.5)
    verdict = compare(structure, other, "cif")
    assert not verdict.ok


def test_wrong_species_assignment_fails(structure):
    other = structure.copy()
    symbols = [site.species_string for site in other]
    symbols[0] = "N" if symbols[0] != "N" else "C"
    other.replace(0, symbols[0])
    verdict = compare(structure, other, "cif")
    assert not verdict.ok


def test_synthetic_cell_does_not_trigger_periodic_matching(structure):
    """An ASE bounding box is not a lattice: the fingerprint path must be used."""
    import ase

    atoms = ase.Atoms(symbols=[site.species_string for site in structure],
                      positions=structure.cart_coords)
    verdict = compare(structure, atoms, "xyz")
    assert verdict.ok, verdict.detail
    assert verdict.periodic is False, "a fabricated cell must not be trusted"


def test_gromacs_tolerance_reflects_its_three_decimals():
    assert LOOSE_TOLERANCE["gromacs"] >= 1e-2
    assert LOOSE_TOLERANCE.get("cif", 1e-3) <= 1e-3


def test_report_records_the_geometry_verdict():
    import json

    path = ROOT / "runs" / "verify_formats" / "verify_formats.json"
    if not path.is_file():
        pytest.skip("verify_formats not run in this checkout")
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["n_geometry_checked"] >= 20
    assert report["geometry_failures"] == []
    assert report["worst_deviation_A"] is not None
    checked = [row for row in report["formats"] if row.get("geometry")]
    assert all(row["geometry"]["ok"] for row in checked)
    # the tight ones really are tight: most formats are exact to ~1e-9 A
    tight = [row for row in checked
             if (row["geometry"]["max_deviation_A"] or 1) < 1e-6]
    assert len(tight) >= 15, f"only {len(tight)} formats matched to 1e-6 A"

def test_lattice_free_route_also_rejects_a_substitution(structure):
    """Distances cannot see a C->N swap; the composition check must."""
    import ase

    other = structure.copy()
    symbols = [site.species_string for site in other]
    symbols[0] = "N" if symbols[0] != "N" else "C"
    other.replace(0, symbols[0])
    atoms = ase.Atoms(symbols=symbols, positions=other.cart_coords)
    verdict = compare(structure, atoms, "xyz")
    assert not verdict.ok
    assert "composition" in verdict.detail
