"""LAMMPS export must be readable by a real ``lmp`` binary (round 33).

Running our file in LAMMPS 2024 gave:

    reading atoms ...  16 atoms
    ERROR: Not all per-type masses are set. Type 1 is missing.

ASE's ``lammps-data`` writer omits masses and does not record the type->element
mapping, so both are now written by cifkit itself.  These tests pin that.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "data" / "terephthalic_acid_hfree.cif"


@pytest.fixture(scope="module")
def data_file(tmp_path_factory):
    from pymatgen.core import Structure

    from cifkit.export import write_structure

    target = tmp_path_factory.mktemp("lammps") / "data.lammps"
    write_structure(Structure.from_file(FIXTURE), target, fmt="lammps-data")
    return target.read_text(encoding="utf-8")


def test_masses_section_exists_for_every_type(data_file):
    header = re.search(r"(\d+)\s+atoms\s*\n\s*(\d+)\s+atom types", data_file)
    assert header, "LAMMPS header missing"
    n_types = int(header.group(2))
    assert "Masses" in data_file
    masses_block = data_file.split("Masses", 1)[1].split("Atoms", 1)[0]
    rows = [line for line in masses_block.splitlines()
            if line.strip() and not line.strip().startswith("#")]
    assert len(rows) == n_types, (len(rows), n_types, masses_block)
    for row in rows:
        parts = row.split()
        assert len(parts) >= 2
        type_id, mass = int(parts[0]), float(parts[1])
        assert 1 <= type_id <= n_types
        assert 0.5 < mass < 300.0


def test_type_to_element_mapping_is_documented(data_file):
    assert "type -> element:" in data_file
    mapping = data_file.split("type -> element:", 1)[1].splitlines()[0]
    assert re.search(r"1=[A-Z][a-z]?", mapping)


def test_force_field_gap_is_stated(data_file):
    lowered = data_file.lower()
    assert "force field" in lowered, "the file must say that pair_style/pair_coeff is missing"


def test_atom_count_matches_the_header(data_file):
    header = re.search(r"(\d+)\s+atoms", data_file)
    n_atoms = int(header.group(1))
    atoms_block = data_file.split("Atoms", 1)[1]
    rows = [line for line in atoms_block.splitlines() if line.strip() and
            not line.strip().startswith("#")]
    assert len(rows) == n_atoms
