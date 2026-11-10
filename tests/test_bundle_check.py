"""Bundle internal consistency (round 39).

A bundle is only usable if its files agree with each other.  These tests check the
contracts *and* prove the checker catches a broken bundle (otherwise it would just
be decoration).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pymatgen.core import Structure

from cifkit.export import supported_bundles, write_bundle
from cifkit.export.bundle_check import check_bundle

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "data" / "terephthalic_acid_hfree.cif"


@pytest.fixture(scope="module")
def structure() -> Structure:
    return Structure.from_file(FIXTURE)


@pytest.mark.parametrize("code", sorted(supported_bundles()))
def test_every_bundle_is_internally_consistent(tmp_path, structure, code):
    info = write_bundle(structure, code, tmp_path / code)
    result = check_bundle(code, tmp_path / code, info.get("missing") or [])
    assert result["ok"], result["errors"]
    assert result["checks"], "a bundle must be checked, not just assumed"


def test_missing_file_is_detected(tmp_path, structure):
    info = write_bundle(structure, "lammps", tmp_path / "lammps")
    (tmp_path / "lammps" / "in.min").unlink()
    result = check_bundle("lammps", tmp_path / "lammps", info.get("missing") or [])
    assert not result["ok"]
    assert any("in.min" in error for error in result["errors"])


def test_broken_reference_is_detected(tmp_path, structure):
    info = write_bundle(structure, "dftb", tmp_path / "dftb")
    (tmp_path / "dftb" / "geo.gen").unlink()
    result = check_bundle("dftb", tmp_path / "dftb", info.get("missing") or [])
    assert not result["ok"]
    assert any("geo.gen" in error for error in result["errors"])


def test_wrong_reference_target_is_detected(tmp_path, structure):
    info = write_bundle(structure, "lammps", tmp_path / "lammps")
    (tmp_path / "lammps" / "data.lammps").rename(tmp_path / "lammps" / "other.lammps")
    result = check_bundle("lammps", tmp_path / "lammps", info.get("missing") or [])
    assert not result["ok"]


def test_declared_missing_must_match_reality(tmp_path, structure):
    """If a bundle ships the thing it calls missing, the docs are lying."""
    info = write_bundle(structure, "vasp", tmp_path / "vasp")
    (tmp_path / "vasp" / "POTCAR").write_text("fake", encoding="utf-8")
    result = check_bundle("vasp", tmp_path / "vasp", info.get("missing") or [])
    assert not result["ok"]
    assert any("POTCAR" in error for error in result["errors"])


def test_unknown_bundle_is_rejected(tmp_path):
    result = check_bundle("not-a-code", tmp_path, [])
    assert not result["ok"]
