"""Partially-occupied structures: a typed, actionable contract (round 55).

The corpus sweep exported a 348-atom disordered ZIF-8 and produced 22 raw library
failures plus one **silently lossy** file (CASTEP wrote the majority species as if the
site were fully occupied).  These tests pin the replacement contract:

* a disordered structure + a format that cannot express it -> the *typed* error;
* the error names the format and the fix;
* an ordered structure is unaffected;
* formats that *can* carry disorder keep working.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from cifkit.export import write_bundle, write_structure
from cifkit.export.disorder_guard import (ORDERED_ONLY, DisorderedStructureError,
                                          guard_ordered, structure_is_ordered)

ROOT = Path(__file__).resolve().parents[1]
ORDERED = ROOT / "tests" / "data" / "terephthalic_acid_hfree.cif"
DISORDERED = ROOT / "tests" / "data" / "zif8_disordered_h.cif"


@pytest.fixture(scope="module")
def ordered() -> Structure:
    return Structure.from_file(ORDERED)


@pytest.fixture(scope="module")
def disordered() -> Structure:
    return Structure.from_file(DISORDERED)


def _distinct_species() -> Structure:
    """A hand-built partially-occupied site, independent of the CIF fixtures."""
    return Structure(Lattice.cubic(5.0),
                     [{"Na": 0.5, "K": 0.5}, "Cl"],
                     [[0, 0, 0], [0.5, 0.5, 0.5]])


def test_the_fixture_is_actually_disordered(disordered):
    assert structure_is_ordered(disordered) is False
    assert structure_is_ordered(Structure.from_file(ORDERED)) is True


def test_partial_occupancy_is_detected_independently_of_the_cif():
    assert structure_is_ordered(_distinct_species()) is False


def test_ordered_structure_exports_to_every_format(ordered, tmp_path):
    for fmt in ("xyz", "vasp", "castep", "gromacs", "lammps"):
        write_structure(ordered, tmp_path / f"x.{fmt}", fmt=fmt)
        assert (tmp_path / f"x.{fmt}").is_file()


@pytest.mark.parametrize("fmt", ["xyz", "vasp", "castep", "gromacs", "lammps", "qe"])
def test_disordered_structure_raises_the_typed_error(disordered, tmp_path, fmt):
    with pytest.raises(DisorderedStructureError) as info:
        write_structure(disordered, tmp_path / f"x.{fmt}", fmt=fmt)
    assert info.value.code == "disordered"
    assert info.value.fmt == fmt
    assert fmt in str(info.value)
    assert "resolve the disorder" in str(info.value)


def test_formats_that_can_carry_disorder_still_work(disordered, tmp_path):
    """cp2k and the CIF/JSON writers are not in the ordered-only set."""
    for fmt in ("cif", "cp2k", "json"):
        assert fmt not in ORDERED_ONLY
        write_structure(disordered, tmp_path / f"x.{fmt}", fmt=fmt)
        assert (tmp_path / f"x.{fmt}").stat().st_size > 0


def test_castep_is_guarded_because_it_would_silently_drop_occupancies(disordered, tmp_path):
    """CASTEP does not raise on its own - it writes the majority species."""
    assert "castep" in ORDERED_ONLY
    with pytest.raises(DisorderedStructureError):
        write_structure(disordered, tmp_path / "x.castep", fmt="castep")


def test_bundle_export_is_guarded_too(disordered, tmp_path):
    with pytest.raises(DisorderedStructureError):
        write_bundle(disordered, "gromacs", tmp_path / "bundle")
    # a bundle whose writer tolerates disorder is unaffected
    info = write_bundle(disordered, "cp2k", tmp_path / "bundle_cp2k")
    assert info["files"]


def test_ordered_bundles_are_unaffected(ordered, tmp_path):
    info = write_bundle(ordered, "gromacs", tmp_path / "ok")
    assert "topol.top" in info["files"]


def test_guard_is_a_noop_for_ordered_structures(ordered):
    for fmt in sorted(ORDERED_ONLY):
        guard_ordered(fmt, ordered)


def test_error_is_a_valueerror_subclass_for_backwards_compatibility(disordered, tmp_path):
    """Callers that already caught ValueError keep working."""
    with pytest.raises(ValueError):
        write_structure(disordered, tmp_path / "x.xyz", fmt="xyz")
