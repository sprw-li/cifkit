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

def test_skewed_cell_beyond_half_box_is_refused(tmp_path):
    """Round 57 adversarial F1: ASE's Prism rotates but does NOT reduce tilts
    (reduce_cell=False), so a strongly skewed cell produced |xy| > length/2 —
    a box real LAMMPS rejects — silently.  cifkit now refuses honestly; writing
    a *reduced* cell instead would change the cell shape and trip the round-57
    cellpar guard, so refusal is the only consistent behaviour."""
    import math as _math

    from pymatgen.core import Lattice, Structure

    from cifkit.export import write_structure

    # a=b, gamma=170° → xy ≈ -0.985*a, far beyond half the box length
    skewed = Structure(Lattice.from_parameters(2.0, 2.0, 2.4, 90, 90, 170),
                       ["Zn", "O"], [[0, 0, 0], [0.33, 0.66, 0.5]])
    target = tmp_path / "data.lmp"
    with pytest.raises(ValueError, match="tilt factor"):
        write_structure(skewed, target, fmt="lammps-data")
    assert not target.exists()  # no half-broken file left behind


def test_edge_tilt_exactly_half_the_box_is_allowed(tmp_path):
    """Hexagonal cells (gamma=120°) sit exactly at |xy| = length/2 — the
    historical workhorse case must keep working."""
    from pymatgen.core import Lattice, Structure

    from cifkit.export import write_structure

    structure = Structure(Lattice.hexagonal(3.25, 5.2), ["Zn", "O"],
                          [[0, 0, 0], [0.3333, 0.6667, 0.5]])
    target = tmp_path / "data.lmp"
    write_structure(structure, target, fmt="lammps-data")
    assert "xy xz yz" in target.read_text(encoding="utf-8")
