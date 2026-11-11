"""Format limits and the precision model (round 56).

Both modules exist because a 320-structure corpus sweep of real CoRE MOF files found
failures that a single fixture never could:

* ``.struct`` silently truncated 2376 atoms to 237 (ASE reads the count from a
  3-character field) — the worst possible outcome, so it is now refused up front;
* ``.mol``/``.sdf`` reject >999 atoms;
* ``.pdb`` deviates up to 0.005 Å because CRYST1 carries cell **angles** with two
  decimals, which the old flat 1e-3 tolerance did not account for.
"""
from __future__ import annotations

import pytest
from pymatgen.core import Lattice, Structure

from cifkit.export.format_limits import ATOM_LIMITS, FormatLimitError, guard_atom_limit
from cifkit.export.precision_model import (ANGLE_GEOMETRIC_FACTOR, DEFAULT_TOLERANCE,
                                           format_tolerance)


def _structure(natoms: int, a: float = 20.0) -> Structure:
    return Structure(Lattice.cubic(a), ["C"] * natoms,
                     [[0.01 * i % 1, 0.02 * i % 1, 0.03 * i % 1] for i in range(natoms)])


# ------------------------------------------------------------------ format limits
def test_limits_are_declared_for_the_fixed_width_formats():
    assert ATOM_LIMITS["struct"][0] == 999
    assert ATOM_LIMITS["mol"][0] == 999
    assert ATOM_LIMITS["sdf"][0] == 999
    for fmt, (limit, why) in ATOM_LIMITS.items():
        assert limit > 0 and why, fmt


def test_under_the_limit_passes():
    guard_atom_limit("struct", _structure(999))
    guard_atom_limit("mol", _structure(999))


def test_over_the_limit_raises_with_a_useful_message():
    with pytest.raises(FormatLimitError) as info:
        guard_atom_limit("struct", _structure(1000))
    assert info.value.code == "format-limit"
    assert info.value.limit == 999 and info.value.natoms == 1000
    assert "cif, json, xyz" in str(info.value), "the message must say what to use instead"


def test_formats_without_a_limit_are_untouched():
    for fmt in ("cif", "json", "xyz", "vasp", "cp2k"):
        guard_atom_limit(fmt, _structure(5000))


def test_the_real_2376_atom_case_is_refused():
    """core_0057.cif from the corpus: .struct would have silently lost 90% of it."""
    import json
    from pathlib import Path

    corpus = Path(__file__).resolve().parents[1] / "runs" / "corpus_bulk.json"
    if not corpus.is_file():
        pytest.skip("bulk corpus not present")
    rows = json.loads(corpus.read_text(encoding="utf-8"))["results"]
    huge = [row for row in rows if (row.get("natoms") or 0) > 999]
    if not huge:
        pytest.skip("no >999-atom structure in this corpus")
    with pytest.raises(FormatLimitError):
        guard_atom_limit("struct", _structure(huge[0]["natoms"]))


# --------------------------------------------------------------- precision model
def test_angle_precision_makes_the_tolerance_cell_dependent():
    small = format_tolerance("pdb", Lattice.cubic(15.0))
    large = format_tolerance("pdb", Lattice.cubic(46.0))
    assert large > small > DEFAULT_TOLERANCE
    assert large == pytest.approx(0.0005 + ANGLE_GEOMETRIC_FACTOR
                                  * (0.005 * 3.141592653589793 / 180) * 46.0, rel=1e-6)


def test_the_measured_46_angstrom_case_is_covered():
    """Observed deviation 0.00509 A on a 46.076 A rhombohedral cell."""
    from pymatgen.core import Lattice as L

    lattice = L.from_parameters(46.076, 46.076, 46.076, 119.45, 119.45, 119.45)
    assert format_tolerance("pdb", lattice) > 0.00509


def test_formats_without_a_cell_or_without_angle_loss_keep_the_floor():
    assert format_tolerance("xyz") == DEFAULT_TOLERANCE
    assert format_tolerance("gromacs", Lattice.cubic(46.0)) >= 0.0005


def test_geometry_check_uses_the_model():
    from cifkit.export.geometry_check import default_tolerance

    loose = default_tolerance("pdb", _structure(10, a=46.0))
    tight = default_tolerance("cif", _structure(10, a=46.0))
    assert loose > tight
