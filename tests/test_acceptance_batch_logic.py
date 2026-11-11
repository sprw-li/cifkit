"""Quantitative acceptance evidence (round 55).

"Accepted" must mean more than "a banner appeared": the batch runner now extracts the
*atom count the code reported reading* and compares it with the count in the file we
shipped.  These tests cover that helper and the ordering bug it exposed (the helper
was appended after the ``__main__`` block, so the container hit a ``NameError`` — the
job failed twice before the log was read).
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "run_acceptance_batch", ROOT / "cloud_h3" / "run_acceptance_batch.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def batch():
    return _load()


# ------------------------------------------------------------------ the helper
def test_gro_atom_count_comes_from_line_two(batch, tmp_path):
    path = tmp_path / "conf.gro"
    path.write_text("title\n   16\n    1MOL  H1 1 0.1 0.2 0.3\n", encoding="utf-8")
    assert batch._input_atom_count(path) == 16


def test_lammps_atom_count_comes_from_the_header(batch, tmp_path):
    path = tmp_path / "data.lammps"
    path.write_text("# comment\n\n132 atoms\n2 atom types\n", encoding="utf-8")
    assert batch._input_atom_count(path) == 132


def test_unknown_input_returns_none(batch, tmp_path):
    path = tmp_path / "mystery.xyz"
    path.write_text("2\n\nH 0 0 0\nH 0 0 1\n", encoding="utf-8")
    assert batch._input_atom_count(path) is None


def test_missing_file_returns_none(batch, tmp_path):
    assert batch._input_atom_count(tmp_path / "nope.gro") is None


# ------------------------------------------------------------------ the markers
def test_gromacs_evidence_regex_reads_the_reported_count(batch):
    """`gmx editconf` prints 'Read 16 atoms'; that is the quantity we check."""
    pattern = batch.CASES["gromacs"]["evidence"]
    found = re.search(pattern, "Read 16 atoms\nVolume: 3.375 nm^3\n")
    assert found and int(found.group(1)) == 16


def test_lammps_evidence_regex_reads_nlocal(batch):
    pattern = batch.CASES["lammps"]["evidence"]
    blob = "  Nlocal:             16 ave          16 max          16 min\n"
    found = re.search(pattern, blob)
    assert found and int(found.group(1)) == 16


def test_gromacs_normal_markers_match_the_real_banner(batch):
    """The old markers ('GROMACS version') never appear in `gmx editconf` output."""
    real = ("         :-) GROMACS - gmx editconf, 2023.3-Ubuntu (-: \n"
            'GROMACS reminds you: "Nada e organico" (Pitty)\n')
    markers = batch.CASES["gromacs"]["normal"]
    assert any(marker in real for marker in markers), markers


# ------------------------------------------------------------------ the ordering bug
def test_helper_is_defined_before_main_runs(batch):
    source = (ROOT / "cloud_h3" / "run_acceptance_batch.py").read_text(encoding="utf-8")
    assert source.index("def _input_atom_count") < source.index("def main() -> int:")
    assert source.count("def _input_atom_count") == 1
    assert callable(batch._input_atom_count)


def test_every_case_has_the_fields_the_runner_uses(batch):
    for code, spec in batch.CASES.items():
        for field in ("packages", "binary", "input", "run", "normal", "failure"):
            assert field in spec, (code, field)
        assert spec["packages"] and spec["binary"] and spec["run"]
