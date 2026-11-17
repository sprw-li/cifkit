"""Regression tests for the non-finite-cell guard (P0: spglib native crash).

Before the guard, a CIF whose cell contains ``nan`` (e.g. ``_cell_angle_beta
nan``) made ``SpacegroupAnalyzer(Structure(NaN lattice))`` access-violate inside
spglib: exit ``0xC0000005`` / ``-1073741819``, **zero** stdout bytes, no Python
traceback -- one ``POST /rpc`` would kill the server process.

These tests pin the contract:

* the shared guard raises :class:`~cifkit.guards.DegenerateCellError` on every
  degenerate cell and never hands it to spglib;
* every symmetry entry point that used to crash (``features``, ``--no-rdf`` /
  ``--topology`` branches, ``geom --standardize``, ``geom --surface``) now fails
  with a typed, readable error instead of dying in native code;
* the CLI still emits **strict JSON** on stdout and a non-zero exit code;
* healthy structures are bit-for-bit unaffected.

The degenerate CIFs are **embedded below** and materialised into ``tmp_path`` at
run time, so the file is self-contained: it depends only on the delivered repo
(``tests/data/zif8_cr_sod.cif``) and never on evaluation scratch directories.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from pymatgen.core import Lattice, Structure

from cifkit.features import extract_features, features_many
from cifkit.geom.standardize import standardize
from cifkit.geom.surface import make_slab
from cifkit.guards import (
    DegenerateCellError,
    assert_finite_cell,
    cell_violations,
    guard_structure,
)

ROOT = Path(__file__).resolve().parents[1]
GOOD_CIF = ROOT / "tests" / "data" / "zif8_cr_sod.cif"

#: Windows access-violation exit codes (signed / unsigned forms of 0xC0000005)
CRASH_CODES = (-1073741819, 3221225477)

#: minimal reproduction: valid cell lengths, ``_cell_angle_beta`` is the plain
#: ASCII token ``nan`` -- pymatgen builds a lattice whose matrix contains NaN.
NAN_ANGLE_CIF = """\
# hand-written CIF with VALID cell lengths but a NaN cell angle (a plain ASCII token)
data_C
_symmetry_space_group_name_H-M   'P 1'
_cell_length_a   5.0
_cell_length_b   5.0
_cell_length_c   5.0
_cell_angle_alpha   90.0
_cell_angle_beta   nan
_cell_angle_gamma   90.0
loop_
 _atom_site_type_symbol
 _atom_site_label
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
  C  C0  0.0  0.0  0.0
"""

#: zero-volume variant: a = 0 plus NaN angles (a finite matrix with valid angles
#: and a zero axis is rejected by the CIF parser itself, as "singular matrix").
ZERO_VOLUME_CIF = """\
# generated using pymatgen
data_C
_symmetry_space_group_name_H-M   'P 1'
_cell_length_a   0.00000000
_cell_length_b   5.00000000
_cell_length_c   5.00000000
_cell_angle_alpha   90.00000000
_cell_angle_beta   nan
_cell_angle_gamma   nan
_symmetry_Int_Tables_number   1
_chemical_formula_structural   C
_chemical_formula_sum   C1
_cell_volume   0.00000000
_cell_formula_units_Z   1
loop_
 _symmetry_equiv_pos_site_id
 _symmetry_equiv_pos_as_xyz
  1  'x, y, z'
loop_
 _atom_site_type_symbol
 _atom_site_label
 _atom_site_symmetry_multiplicity
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
  C  C0  1  0.00000000  0.00000000  0.00000000  1
"""


def _strict_json(text: str):
    """``json.loads`` that rejects the non-standard NaN/Infinity constants."""

    def _reject(constant: str):
        raise ValueError(f"non-strict JSON constant: {constant}")

    return json.loads(text, parse_constant=_reject)


def _run_cli(*argv: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "cifkit", *argv],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


@pytest.fixture(scope="module")
def degenerate_cifs(tmp_path_factory) -> dict[str, Path]:
    """Write the embedded degenerate CIFs to a temporary directory."""
    directory = tmp_path_factory.mktemp("degenerate_cells")
    nan_path = directory / "nan_angle.cif"
    zero_path = directory / "zero_volume.cif"
    nan_path.write_text(NAN_ANGLE_CIF, encoding="utf-8")
    zero_path.write_text(ZERO_VOLUME_CIF, encoding="utf-8")
    return {"nan": nan_path, "zero": zero_path}


@pytest.fixture(scope="module")
def nan_structure(degenerate_cifs) -> Structure:
    return Structure.from_file(str(degenerate_cifs["nan"]))


@pytest.fixture(scope="module")
def zero_structure(degenerate_cifs) -> Structure:
    return Structure.from_file(str(degenerate_cifs["zero"]))


@pytest.fixture(scope="module")
def good_structure() -> Structure:
    return Structure.from_file(str(GOOD_CIF))


# ---------------------------------------------------------------------------
# unit level: the guard itself
# ---------------------------------------------------------------------------
def test_guard_accepts_healthy_structure(good_structure):
    assert cell_violations(good_structure) == []
    assert_finite_cell(good_structure)  # must not raise
    assert guard_structure(good_structure) is good_structure


def test_nan_cell_violations_are_reported(nan_structure):
    violations = cell_violations(nan_structure)
    assert violations, "a NaN lattice must produce at least one violation"
    joined = "; ".join(violations)
    assert "non-finite" in joined
    assert "nan" in joined


@pytest.mark.parametrize("key", ["nan", "zero"])
def test_degenerate_cif_raises_typed_error(key, nan_structure, zero_structure):
    structure = nan_structure if key == "nan" else zero_structure
    with pytest.raises(DegenerateCellError) as excinfo:
        assert_finite_cell(structure, context="unit-test")
    err = excinfo.value
    assert err.violations
    assert err.context == "unit-test"
    assert "degenerate cell" in str(err)
    # a DegenerateCellError must stay catchable as a plain ValueError
    assert isinstance(err, ValueError)


def test_finite_matrix_with_zero_determinant_is_rejected():
    # finite entries and finite, in-range angles -- only the volume is zero
    flat = Lattice.from_parameters(5.0, 5.0, 5.0, 90.0, 90.0, 0.0)
    violations = cell_violations(flat)
    assert any("det(lattice)" in v for v in violations), violations
    with pytest.raises(DegenerateCellError):
        assert_finite_cell(flat)


def test_positive_but_degenerate_axis_is_rejected():
    tiny = Lattice.from_parameters(1e-13, 5.0, 5.0, 90.0, 90.0, 90.0)
    with pytest.raises(DegenerateCellError) as excinfo:
        assert_finite_cell(tiny)
    assert any("lattice length a" in v for v in excinfo.value.violations)


def test_guard_accepts_raw_matrix_and_infinities():
    assert cell_violations(np.eye(3) * 5.0) == []
    inf_matrix = np.eye(3) * 5.0
    inf_matrix[0, 1] = math.inf
    with pytest.raises(DegenerateCellError) as excinfo:
        assert_finite_cell(inf_matrix)
    assert any("non-finite" in v for v in excinfo.value.violations)


# ---------------------------------------------------------------------------
# every symmetry entry point
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "options",
    [
        {"rdf": True},
        {"rdf": False},  # --no-rdf
        {"rdf": False, "topology": True},  # --topology
        {"rdf": False, "rings": True},  # --rings
    ],
)
def test_extract_features_guards_every_branch(nan_structure, options):
    with pytest.raises(DegenerateCellError):
        extract_features(nan_structure, **options)


def test_standardize_raises_instead_of_crashing(nan_structure):
    with pytest.raises(DegenerateCellError) as excinfo:
        standardize(nan_structure)
    assert excinfo.value.context == "standardize"


def test_make_slab_raises_instead_of_crashing(nan_structure):
    with pytest.raises(DegenerateCellError) as excinfo:
        make_slab(nan_structure, (1, 1, 1), slab_thickness=5.0, vacuum=5.0)
    assert excinfo.value.context == "make_slab"


def test_features_many_records_error_row(degenerate_cifs):
    rows = features_many([degenerate_cifs["nan"]], jobs=1, rdf=False)
    assert len(rows) == 1
    assert "DegenerateCellError" in rows[0]["error"]
    # the row must stay JSON-serialisable (it travels through the JSON API)
    _strict_json(json.dumps(rows))


def test_zero_volume_structure_is_guarded_everywhere(zero_structure):
    with pytest.raises(DegenerateCellError):
        extract_features(zero_structure, rdf=False)
    with pytest.raises(DegenerateCellError):
        standardize(zero_structure)


# ---------------------------------------------------------------------------
# subprocess level: the acceptance command must not crash
# ---------------------------------------------------------------------------
def test_cli_features_nan_json_does_not_crash_and_is_strict_json(degenerate_cifs):
    proc = _run_cli("features", str(degenerate_cifs["nan"]), "--json")
    assert proc.returncode not in CRASH_CODES, (
        f"native 0xC0000005 crash not fixed (returncode={proc.returncode})"
    )
    assert proc.returncode != 0, "a degenerate cell must fail the run (non-zero exit)"
    payload = _strict_json(proc.stdout)
    assert payload["ok"] is False
    assert payload["n_failed"] == 1
    assert "DegenerateCellError" in payload["rows"][0]["error"]


def test_cli_geom_standardize_nan_exits_nonzero_with_readable_error(degenerate_cifs, tmp_path):
    out = tmp_path / "a.cif"
    proc = _run_cli("geom", str(degenerate_cifs["nan"]), "-o", str(out), "--standardize")
    assert proc.returncode not in CRASH_CODES, (
        f"native 0xC0000005 crash not fixed (returncode={proc.returncode})"
    )
    assert proc.returncode != 0
    assert "DegenerateCellError" in proc.stderr
    assert not out.exists(), "no output may be written for a rejected cell"


def test_cli_geom_surface_nan_exits_nonzero(degenerate_cifs, tmp_path):
    out = tmp_path / "slab.cif"
    proc = _run_cli("geom", str(degenerate_cifs["nan"]), "-o", str(out), "--surface", "1", "1", "1")
    assert proc.returncode not in CRASH_CODES
    assert proc.returncode != 0
    assert "DegenerateCellError" in proc.stderr


# ---------------------------------------------------------------------------
# healthy structures stay healthy
# ---------------------------------------------------------------------------
def test_features_of_healthy_structure_unchanged(good_structure):
    row = extract_features(good_structure, rdf=False)
    assert row["natoms"] == 138
    assert row["spacegroup_number"] == 217
    assert row["spacegroup_symbol"] == "I-43m"
    # tests/data/zif8_cr_sod.cif is the rhombohedral primitive setting
    assert row["a"] == pytest.approx(14.6693, abs=0.01)


def test_cli_features_healthy_structure_still_succeeds():
    proc = _run_cli("features", str(GOOD_CIF), "--json")
    assert proc.returncode == 0, proc.stderr[-2000:]
    payload = _strict_json(proc.stdout)
    assert payload["ok"] is True
    assert payload["rows"][0]["spacegroup_number"] == 217


def test_standardize_healthy_structure_still_works(good_structure):
    out = standardize(good_structure.copy())
    assert len(out) > 0
    assert np.isfinite(out.lattice.matrix).all()
