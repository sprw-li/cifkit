"""Cloud acceptance evidence must be classified honestly (round 53).

The consolidated report is what a platform reads to decide "can cifkit write an input
this code accepts?".  These tests pin the mapping, including the two mistakes that
the real report exposed: duplicate rows for one code, and calling a geometry-only
LAMMPS run "verified".
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    import sys

    spec = importlib.util.spec_from_file_location(
        "check_software", ROOT / "scripts" / "check_software.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    # register before exec: the script defines dataclasses, which need __module__
    # to resolve in sys.modules
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(root: Path, name: str, payload: dict) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "acceptance_result.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_accepted_run_is_accepted_not_verified(tmp_path):
    module = _load_script()
    _write(tmp_path, "accept_lammps", {
        "code": "lammps", "status": "accepted", "exit": 0,
        "normal_marker": "Total wall time", "failure_marker": None,
        "route": "shipped-route", "binary": "/usr/bin/lmp"})
    levels = module.classify_cloud_evidence(tmp_path)
    assert levels["LAMMPS"]["level"] == "accepted", levels
    assert "no force field" in levels["LAMMPS"]["detail"]


def test_same_code_from_two_runs_is_one_row(tmp_path):
    module = _load_script()
    _write(tmp_path, "accept_lammps_a", {
        "code": "lammps", "status": "accepted", "exit": 1,
        "normal_marker": None, "failure_marker": "ERROR",
        "route": "shipped-route", "binary": "/usr/bin/lmp"})
    _write(tmp_path, "accept_lammps_b", {
        "code": "LAMMPS", "status": "accepted", "exit": 0,
        "normal_marker": "Total wall time", "failure_marker": None,
        "route": "shipped-route", "binary": "/usr/bin/lmp"})
    levels = module.classify_cloud_evidence(tmp_path)
    assert list(levels) == ["LAMMPS"], levels
    assert "Total wall time" in levels["LAMMPS"]["detail"]


def test_screen_reader_orca_is_blocked_with_the_reason(tmp_path):
    module = _load_script()
    _write(tmp_path, "accept_orca-debian-package", {
        "code": "orca-debian-package", "status": "no-normal-marker", "exit": 1,
        "normal_marker": None, "failure_marker": None,
        "route": "shipped-route", "binary": "/usr/bin/orca"})
    levels = module.classify_cloud_evidence(tmp_path)
    assert levels["ORCA (chemistry)"]["level"] == "blocked"
    assert "screen reader" in levels["ORCA (chemistry)"]["detail"]


def test_eol_abinit_is_blocked(tmp_path):
    module = _load_script()
    _write(tmp_path, "accept_abinit", {
        "code": "abinit", "status": "failed-marker", "exit": 14,
        "normal_marker": None, "failure_marker": "ERROR",
        "route": "shipped-route", "binary": "/usr/bin/abinit"})
    levels = module.classify_cloud_evidence(tmp_path)
    assert levels["ABINIT"]["level"] == "blocked"


def test_missing_directory_is_safe(tmp_path):
    module = _load_script()
    assert module.classify_cloud_evidence(tmp_path / "nope") == {}


def test_real_report_is_consistent():
    """The committed report must not claim a level its evidence does not support."""
    path = ROOT / "runs" / "check_software.json"
    if not path.is_file():
        import pytest

        pytest.skip("check_software not run in this checkout")
    report = json.loads(path.read_text(encoding="utf-8"))
    cloud = report.get("cloud") or {}
    for code, row in cloud.items():
        assert row["level"] in ("verified", "accepted", "blocked"), (code, row)
        if row["level"] == "accepted" and code == "LAMMPS":
            assert "no force field" in row["detail"], "geometry-only must be labelled"
