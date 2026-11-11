"""Acceptance matrix: one row per (code, case), quantitative where possible (round 55).

The matrix is the evidence behind "our exported input is accepted by the real code".
These tests keep it honest: deduplication, atom-count agreement preferred over a bare
banner, and the two failure modes we actually hit (wrong marker, apt timeout).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "runs" / "cloud_h3" / "acceptance_matrix.json"


def _load():
    spec = importlib.util.spec_from_file_location(
        "collect_acceptance", ROOT / "scripts" / "collect_acceptance.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def collector():
    return _load()


def test_atom_counters_read_the_shipped_files(tmp_path):
    module = _load()
    gro = tmp_path / "conf.gro"
    gro.write_text("t\n    138\n atom\n", encoding="utf-8")
    assert module.gro_atoms(gro) == 138
    data = tmp_path / "data.lammps"
    data.write_text("# c\n\n132 atoms\n2 atom types\n", encoding="utf-8")
    assert module.lammps_atoms(data) == 132
    assert module.gro_atoms(tmp_path / "missing.gro") is None


def test_every_code_has_an_atom_pattern(collector):
    assert set(collector.ATOM_PATTERNS) == {"lammps", "gromacs", "nwchem"}
    for pattern in collector.ATOM_PATTERNS.values():
        assert pattern is not None


def test_committed_matrix_is_deduplicated_and_quantitative():
    if not MATRIX.is_file():
        pytest.skip("acceptance matrix not collected in this checkout")
    payload = json.loads(MATRIX.read_text(encoding="utf-8"))
    unique = payload["unique_entries"]
    keys = [(row["code"], row["case"]) for row in unique]
    assert len(keys) == len(set(keys)), "one row per (code, case)"
    assert payload["total_accepted"] == payload["total_cases"] == len(unique)
    # atom counts must have been compared, not just a banner
    checked = [row for row in unique if row["atoms_match"] is not None]
    assert len(checked) == len(unique), "every case must compare reported vs expected atoms"
    assert all(row["atoms_match"] for row in checked)
    assert payload["n_runs_seen"] >= len(unique)


def test_matrix_covers_more_than_one_structure():
    if not MATRIX.is_file():
        pytest.skip("acceptance matrix not collected in this checkout")
    payload = json.loads(MATRIX.read_text(encoding="utf-8"))
    cases = {row["case"] for row in payload["unique_entries"]}
    assert len(cases) >= 8, f"only {len(cases)} distinct cases"
    structures = {case.split("__")[-1] for case in cases}
    assert len(structures) >= 5, structures


def test_real_world_failure_modes_are_documented():
    """Both failures we actually hit must stay visible in the docs."""
    text = (ROOT / "docs" / "CLOUD-GPU.md").read_text(encoding="utf-8")
    assert "gmx editconf" in text or "editconf" in text
    assert "apt-get" in text or "超时" in text
