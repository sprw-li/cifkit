"""Validation layer tests (owner: geom-export).

Assertions use the measured numbers from the demo path: the (111) slab of the
276-atom conventional ZIF-8 cell has a measured vacuum >= 15 A, and the H-free
raw ZIF-8 fails the carbon/hydrogen checks when ``spec.repair_h`` is set.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from cifkit import geom
from cifkit.types import TaskSpec
from cifkit.validate import CHECK_NAMES, validate_structure

DATA = Path(__file__).resolve().parent / "data"
VALID_SEVERITIES = {"error", "warning", "info"}


@pytest.fixture(scope="module")
def zif8_prim() -> Structure:
    return Structure.from_file(str(DATA / "zif8_cr_sod.cif"))


@pytest.fixture(scope="module")
def zif8_slab(zif8_prim: Structure):
    conv = geom.standardize(zif8_prim)
    slab, info = geom.make_slab(conv, (1, 1, 1), slab_thickness=10.0, vacuum=15.0)
    return slab, info


# ---------------------------------------------------------------------------
def test_check_names_are_stable() -> None:
    assert CHECK_NAMES == (
        "natoms",
        "composition",
        "lattice",
        "finite_coordinates",
        "duplicate_atoms",
        "min_distance",
        "vacuum",
        "slab_continuity",
        "dangling_bonds",
        "hydrogen",
        "carbon_coordination",
        "charge",
    )


def test_validate_bulk_zif8(zif8_prim: Structure) -> None:
    report = validate_structure(zif8_prim)
    assert report.ok is True
    metrics = report.metrics
    assert metrics["natoms"] == 138
    assert "Zn" in metrics["formula"] and "H" in metrics["formula"]
    assert set(metrics["lattice"]) >= {"abc", "angles", "volume", "volume_per_atom"}
    assert abs(metrics["lattice"]["abc"][0] - 14.669) < 0.01
    assert 0.5 <= metrics["min_distance"] <= 3.0
    assert metrics["min_distance_pair"] is not None
    assert metrics["h_count"] == 60, "the 138-atom primitive cell has 60 H (Zn6 C48 N24 H60)"
    assert metrics["is_slab"] is False
    # 36 aromatic ring C (3 bonds) + 12 methyl C (4 bonds) in the 138-atom cell
    assert metrics["c_coordination"] == {3: 36, 4: 12}
    assert metrics["c_missing_h"] == 0

    names = [c.name for c in report.checks]
    assert {"natoms", "composition", "lattice", "finite_coordinates", "duplicate_atoms", "min_distance"} <= set(names)
    assert set(names) <= set(CHECK_NAMES)
    assert all(c.severity in VALID_SEVERITIES for c in report.checks)
    # no H-deficient carbon -> carbon check passes
    carbon = next(c for c in report.checks if c.name == "carbon_coordination")
    assert carbon.ok is True


def test_validate_slab_reports_vacuum_and_thickness(zif8_slab) -> None:
    slab, info = zif8_slab
    report = validate_structure(slab, spec=TaskSpec(vacuum=15.0, surface=(1, 1, 1)))
    assert report.ok is True, [c.__dict__ for c in report.checks if not c.ok]
    metrics = report.metrics
    assert metrics["is_slab"] is True
    # the reported vacuum is the perpendicular layer thickness -> exactly 15 A
    assert abs(metrics["vacuum_measured"] - 15.0) < 0.01
    assert metrics["vacuum_perp"] == metrics["vacuum_measured"]
    assert metrics["vacuum"] == metrics["vacuum_measured"]
    # the min periodic-image distance is a separate (safe, larger) number
    assert metrics["min_image_distance"] >= metrics["vacuum_perp"] - 1e-6
    assert metrics["slab_thickness"] > 5.0
    assert metrics["surface_atoms"] > 0
    assert metrics["dangling_bonds"] >= 0
    # make_slab and validate must agree on the measured vacuum
    assert abs(metrics["vacuum_measured"] - info["vacuum_measured"]) < 0.01
    vacuum_check = next(c for c in report.checks if c.name == "vacuum")
    assert vacuum_check.ok is True and vacuum_check.severity == "error"
    assert "真空层（垂直）" in vacuum_check.detail
    assert "最小周期像距离" in vacuum_check.detail
    # a cut MOF slab necessarily exposes under-coordinated atoms -> warning only
    dangling = next(c for c in report.checks if c.name == "dangling_bonds")
    assert dangling.severity == "warning"


def test_validate_slab_enforces_the_vacuum_target(zif8_slab) -> None:
    slab, _info = zif8_slab
    report = validate_structure(slab, spec=TaskSpec(vacuum=30.0, surface=(1, 1, 1)))
    assert report.ok is False
    vacuum = next(c for c in report.checks if c.name == "vacuum")
    assert vacuum.ok is False and vacuum.severity == "error"
    assert report.metrics["vacuum_target"] == 30.0


def test_validate_hfree_with_repair_h_fails_honestly() -> None:
    hfree = Structure.from_file(str(DATA / "zif8_raw_hfree.cif"))
    report = validate_structure(hfree, spec=TaskSpec(repair_h=True))
    assert report.ok is False
    failed = {c.name for c in report.checks if not c.ok and c.severity == "error"}
    assert "hydrogen" in failed
    assert "carbon_coordination" in failed
    assert report.metrics["h_count"] == 0
    assert report.metrics["c_missing_h"] > 0


def test_validate_hfree_without_spec_is_a_warning_not_a_failure() -> None:
    hfree = Structure.from_file(str(DATA / "zif8_raw_hfree.cif"))
    report = validate_structure(hfree)
    assert report.ok is True  # repair was not requested
    carbon = next(c for c in report.checks if c.name == "carbon_coordination")
    assert carbon.ok is False and carbon.severity == "warning"


def test_validate_duplicate_atoms() -> None:
    bad = Structure(
        Lattice.cubic(8.0),
        ["C", "C", "N"],
        [[0.0, 0.0, 0.0], [0.01, 0.0, 0.0], [0.5, 0.5, 0.5]],
    )
    report = validate_structure(bad)
    assert report.ok is False
    duplicate = next(c for c in report.checks if c.name == "duplicate_atoms")
    assert duplicate.ok is False and duplicate.severity == "error"
    min_distance = next(c for c in report.checks if c.name == "min_distance")
    assert min_distance.ok is False
    assert report.metrics["min_distance"] < 0.5
    assert report.metrics["duplicate_pairs"] >= 1


def test_validate_cluster(zif8_prim: Structure) -> None:
    cluster = geom.extract_cluster(zif8_prim, mode="sbu")
    report = validate_structure(cluster)
    assert report.ok is True
    assert report.metrics["is_cluster"] is True
    assert report.metrics["is_slab"] is False
    assert report.metrics["min_distance"] is not None


def test_validate_extra_is_merged_into_metrics(zif8_prim: Structure) -> None:
    report = validate_structure(zif8_prim, extra={"step": "surface", "frame": "slab"})
    assert report.metrics["extra"] == {"step": "surface", "frame": "slab"}


def test_validate_rejects_none() -> None:
    with pytest.raises(ValueError):
        validate_structure(None)


def test_validate_empty_structure() -> None:
    empty = Structure(Lattice.cubic(5.0), [], [], validate_proximity=False)
    report = validate_structure(empty)
    assert report.ok is False
    assert report.metrics["natoms"] == 0


def test_validate_metrics_have_the_report_keys(zif8_prim: Structure, zif8_slab) -> None:
    bulk = validate_structure(zif8_prim).metrics
    for key in ("natoms", "formula", "lattice", "min_distance"):
        assert key in bulk, key
    slab, _info = zif8_slab
    slab_metrics = validate_structure(slab).metrics
    for key in (
        "natoms",
        "formula",
        "lattice",
        "min_distance",
        "vacuum_measured",
        "vacuum_perp",
        "min_image_distance",
        "slab_thickness",
    ):
        assert key in slab_metrics, key


def test_hydrogen_check_is_noop_for_inorganic_structure() -> None:
    """Round 4: repair_h on an inorganic structure with no organic H sites is OK.

    Previously the validator failed any ``repair_h`` run whose final structure had
    zero H atoms, which wrongly failed e.g. a GaN AFLOW download (H completion is a
    legitimate no-op for inorganic/DFT structures).
    """
    gan = Structure(Lattice.cubic(4.5), ["Ga", "N"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    report = validate_structure(gan, spec=TaskSpec(repair_h=True))
    hydrogen = next(c for c in report.checks if c.name == "hydrogen")
    assert hydrogen.ok is True
    assert hydrogen.severity == "info"
    assert "no-op" in hydrogen.detail
    assert report.ok is True


def test_hydrogen_check_still_fails_under_hydrogenated_organic() -> None:
    """A carbon framework with missing H must still fail the hydrogen check."""
    # diamond-like C network where every interior C has only 2 neighbours in the
    # (small) cell -> missing H; the carbon_coordination check must flag it too.
    carbon = Structure(Lattice.cubic(2.5), ["C"], [[0, 0, 0]], validate_proximity=False)
    report = validate_structure(carbon, spec=TaskSpec(repair_h=True))
    hydrogen = next(c for c in report.checks if c.name == "hydrogen")
    assert hydrogen.ok is False
    assert hydrogen.severity == "error"
