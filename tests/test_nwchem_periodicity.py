"""NWChem export must match the structure's periodicity (round 28).

Real NWChem 7.2.2 in a cloud container rejected our file with:

    dft_rdinput: detected periodicity = 3
    There is an error in the input file        (exit 3)

The geometry was fine; the *task* was wrong (molecular DFT cannot do PBC).  These
tests pin the corrected behaviour and the portability fix found in the same run.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ZIF8 = ROOT / "tests" / "data" / "zif8_cr_sod.cif"


@pytest.fixture(scope="module")
def nwchem_text(tmp_path_factory):
    from pymatgen.core import Structure

    from cifkit.export import write_structure

    tmp = tmp_path_factory.mktemp("nwchem")
    target = tmp / "mol.nw"
    write_structure(Structure.from_file(ZIF8), target, fmt="nwchem")
    return target.read_text(encoding="utf-8")


def _directives(text: str) -> list[str]:
    """Non-comment, non-blank lines (the comment block quotes the rejected tasks)."""
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def test_periodic_input_uses_the_verified_plane_wave_task(nwchem_text):
    """The pattern that finished in real NWChem 7.2.2, not a guess."""
    assert "system crystal" in nwchem_text, "the fixture is periodic"
    directives = _directives(nwchem_text)
    assert "task pspw energy" in directives
    assert "task dft energy" not in directives, "molecular DFT rejects periodicity=3"
    assert "task nwpw energy" not in directives, "unknown theory in real NWChem"
    assert "nwpw" in directives
    assert "cutoff 20" in [line.strip() for line in directives]
    assert "ecut" not in " ".join(directives), "'ecut' is rejected by nwpw_input"
    assert not [line for line in directives if line.startswith("basis")], "Gaussian basis"


def test_the_evidence_for_the_pattern_is_recorded(nwchem_text):
    """The file must explain *why* this task, and cite the failed attempts."""
    lowered = nwchem_text.lower()
    assert "periodicity = 3" in lowered
    assert "cutoff" in lowered and "pseudopotential" in lowered
    assert "libraryps" in lowered


def test_no_host_paths_and_relative_dirs(nwchem_text):
    assert "permanent_dir ." in nwchem_text
    assert str(ROOT) not in nwchem_text
    assert "D:\\" not in nwchem_text


def test_the_export_path_is_periodic_only(tmp_path):
    """ASE declares ``system crystal`` for any pymatgen ``Structure``.

    So every file from this writer takes the periodic path above — including a
    molecule placed in a box.  A true cluster would need a different export path,
    and this API says so by rejecting a ``Molecule``.
    """
    from pymatgen.core import Lattice, Molecule, Structure

    from cifkit.export import write_structure

    boxed = Structure(Lattice.cubic(15.0),
                      ["H", "H", "O"],
                      [[0, 0, 0], [0.757, 0.586, 0], [-0.757, 0.586, 0]])
    target = tmp_path / "boxed.nw"
    write_structure(boxed, target, fmt="nwchem")
    text = target.read_text(encoding="utf-8")
    assert "system crystal" in text, "periodicity is declared even for a molecule in a box"
    assert "task pspw energy" in _directives(text), "the periodic path applies here too"

    with pytest.raises(Exception):
        write_structure(Molecule(["H", "H"], [[0, 0, 0], [0, 0, 0.74]]),
                        tmp_path / "cluster.nw", fmt="nwchem")
