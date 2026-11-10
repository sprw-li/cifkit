"""ABACUS export must put each species' atoms in its own block (round 38).

Real defect caught by the strict template parser: the exporter wrote **every**
atom under **every** species (48 rows for a 16-atom cell), so ABACUS would read
duplicated atoms.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pymatgen.core import Structure

from cifkit.export import write_structure

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "data" / "terephthalic_acid_hfree.cif"


@pytest.fixture(scope="module")
def abacus_text(tmp_path_factory):
    target = tmp_path_factory.mktemp("abacus") / "STRU"
    write_structure(Structure.from_file(FIXTURE), target, fmt="abacus")
    return target.read_text(encoding="utf-8")


def test_total_coordinate_rows_equal_atom_count(abacus_text):
    structure = Structure.from_file(FIXTURE)
    body = abacus_text.split("ATOMIC_POSITIONS", 1)[1]
    rows = [line for line in body.splitlines()
            if len(line.split()) >= 4 and re.match(r"\s*-?\d", line)]
    assert len(rows) == len(structure), (len(rows), len(structure))


def test_each_species_block_has_the_declared_count(abacus_text):
    structure = Structure.from_file(FIXTURE)
    body = abacus_text.split("ATOMIC_POSITIONS", 1)[1]
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    index = 1  # skip the "Cartesian" line
    seen: dict[str, int] = {}
    while index < len(lines):
        symbol = lines[index]
        if not re.fullmatch(r"[A-Z][a-z]?", symbol):
            index += 1
            continue
        declared = int(float(lines[index + 2]))
        coords = 0
        cursor = index + 3
        while cursor < len(lines) and len(lines[cursor].split()) >= 4:
            coords += 1
            cursor += 1
        seen[symbol] = seen.get(symbol, 0) + coords
        assert declared == coords, f"{symbol}: declared {declared}, wrote {coords}"
        index = cursor
    expected = {site.species_string: 0 for site in structure}
    for site in structure:
        expected[site.species_string] += 1
    assert seen == expected, (seen, expected)
