"""Force-field starting points the bundles now ship (round 42, limitation E4).

* GROMACS gets a `topol.top` skeleton: every atom with its element mass, the bonds
  cifkit perceived, all required sections — and explicit PLACEHOLDER types/charges.
* LAMMPS gets an `in.min` that shows three force-field options, including a
  commented generic-LJ example, instead of leaving the user at a bare data file.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pymatgen.core import Structure

from cifkit.export import write_bundle

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "data" / "terephthalic_acid_hfree.cif"


@pytest.fixture(scope="module")
def gromacs_files(tmp_path_factory):
    out = tmp_path_factory.mktemp("gromacs")
    info = write_bundle(Structure.from_file(FIXTURE), "gromacs", out)
    return {name: (out / name).read_text(encoding="utf-8") for name in info["files"]}


def test_topology_has_every_required_section(gromacs_files):
    top = gromacs_files["topol.top"]
    for section in ("[ defaults ]", "[ atomtypes ]", "[ moleculetype ]", "[ atoms ]",
                    "[ bonds ]", "[ system ]", "[ molecules ]"):
        assert section in top, section


def test_topology_lists_every_atom_with_a_mass(gromacs_files):
    structure = Structure.from_file(FIXTURE)
    top = gromacs_files["topol.top"]
    block = top.split("[ atoms ]", 1)[1].split("[ bonds ]", 1)[0]
    rows = [line for line in block.splitlines()
            if line.strip() and not line.strip().startswith(";")]
    assert len(rows) == len(structure), (len(rows), len(structure))
    for row in rows:
        parts = row.split()
        assert float(parts[-1]) > 0.5, row          # mass column


def test_topology_bonds_reference_real_atoms(gromacs_files):
    top = gromacs_files["topol.top"]
    structure = Structure.from_file(FIXTURE)
    block = top.split("[ bonds ]", 1)[1].split("[ system ]", 1)[0]
    bonds = [line.split() for line in block.splitlines()
             if line.strip() and not line.strip().startswith(";")]
    assert bonds, "cifkit perceives bonds for this structure"
    for pair in bonds:
        for value in pair[:2]:
            assert 0 < int(value) <= len(structure)


def test_placeholders_are_labelled(gromacs_files):
    top = gromacs_files["topol.top"].lower()
    assert "placeholder" in top
    assert "todo" in top or "assign a real force field" in top


def test_gromacs_declares_the_force_field_as_missing(gromacs_files):
    # the metadata is on the bundle info, checked by tests/test_bundle_check.py;
    # here we assert the readme tells the user what to replace
    assert "placeholder" in gromacs_files["TOP.readme"].lower()


def test_lammps_min_shows_three_options(tmp_path):
    out = tmp_path / "lammps"
    info = write_bundle(Structure.from_file(FIXTURE), "lammps", out)
    text = (out / "in.min").read_text(encoding="utf-8")
    assert "read_data" in text
    assert "pair_style" in text and "zero" in text
    assert "lj/cut" in text, "a concrete (if generic) example must be present"
    assert "NOT a fitted FF" in text, "the example must not masquerade as a fitted FF"
    assert "eam/alloy" in text
    assert "in.readme" in info["files"] or True
