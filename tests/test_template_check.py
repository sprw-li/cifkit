"""Strict template parsers (round 38, limitation E2).

No third-party reader in our dependency set can parse the 5 template formats
(``runs/probe_template_readers.json``), so the in-house parser must be strict
enough to catch a damaged export.  These tests pin that.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pymatgen.core import Structure

from cifkit.export import write_bundle, write_structure
from cifkit.export.template_check import check_template

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "data" / "terephthalic_acid_hfree.cif"


@pytest.fixture(scope="module")
def structure() -> Structure:
    return Structure.from_file(FIXTURE)


@pytest.mark.parametrize("fmt", ["cp2k", "siesta", "abacus", "orca"])
def test_real_export_parses_with_the_right_atom_count(tmp_path, structure, fmt):
    target = tmp_path / f"artifact.{fmt}"
    write_structure(structure, target, fmt=fmt)
    report = check_template(fmt, target.read_text(encoding="utf-8"))
    assert report.ok, report.errors
    assert report.natoms == len(structure)
    expected = sorted({site.species_string for site in structure})
    if fmt != "siesta":  # SIESTA uses numeric species indices in this template
        assert report.elements == expected, (report.elements, expected)


def test_dftb_bundle_parses_with_geo_gen(tmp_path, structure):
    info = write_bundle(structure, "dftb", tmp_path / "dftb")
    files = {name: (tmp_path / "dftb" / name) for name in info["files"]}
    hsd = files["dftb_in.hsd"].read_text(encoding="utf-8")
    gen = files["geo.gen"].read_text(encoding="utf-8")
    report = check_template("dftb", hsd, {"geo.gen": gen})
    assert report.ok, report.errors
    assert report.natoms == len(structure)


def test_truncated_coordinates_are_rejected(tmp_path, structure):
    target = tmp_path / "artifact.cp2k"
    write_structure(structure, target, fmt="cp2k")
    text = target.read_text(encoding="utf-8")
    # drop every coordinate row inside &COORD — a keyword-only check would pass
    dam = re.sub(r"(?m)^\s+[A-Z][a-z]?\s+-?\d[^\n]*$", "", text)
    report = check_template("cp2k", dam)
    assert not report.ok
    assert (report.natoms or 0) != len(structure)


def test_siesta_ships_a_real_species_label(tmp_path, structure):
    """Our SIESTA export writes a ChemicalSpeciesLabel block (index mass element)."""
    target = tmp_path / "artifact.siesta"
    write_structure(structure, target, fmt="siesta")
    text = target.read_text(encoding="utf-8")
    assert "%block ChemicalSpeciesLabel" in text
    report = check_template("siesta", text)
    assert report.ok, report.errors
    assert report.natoms == len(structure)


def test_siesta_without_the_label_block_is_rejected(tmp_path, structure):
    target = tmp_path / "artifact.siesta"
    write_structure(structure, target, fmt="siesta")
    text = target.read_text(encoding="utf-8")
    damaged = re.sub(r"%block ChemicalSpeciesLabel.*?%endblock", "", text, flags=re.S)
    report = check_template("siesta", damaged)
    assert any("no ChemicalSpeciesLabel" in error for error in report.errors)


def test_unknown_format_raises():
    with pytest.raises(ValueError):
        check_template("vasp", "")
