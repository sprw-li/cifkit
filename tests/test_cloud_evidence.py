"""Cloud evidence classification (round 34).

``scripts/check_software.py`` now reads the real-run artifacts under
``runs/cloud_h3``.  The classification must stay honest:

* ``verified`` only for a *completed* run with a success marker;
* ``accepted`` for parse-level acceptance (no force field -> no calculation);
* ``blocked`` when the code itself is unusable (proven with a canonical input).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def report_module():
    spec = importlib.util.spec_from_file_location("check_software",
                                                  ROOT / "scripts" / "check_software.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    # dataclasses resolves ``sys.modules[cls.__module__]`` at class creation, so the
    # module must be registered before exec_module (it uses @dataclass).
    import sys

    sys.modules["check_software"] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_verified_requires_a_completed_run(report_module, tmp_path):
    _write(tmp_path / "artifacts_a" / "acceptance_result.json",
           {"codes": [{"code": "NWChem", "status": "verified", "binary": "/usr/bin/nwchem",
                       "exit": 0}]})
    _write(tmp_path / "artifacts_b" / "parse_accept.json",
           {"cases": [{"code": "LAMMPS", "input": "data.lammps", "exit": 0,
                       "accepted": True, "calculation_completed": False}]})
    cloud = report_module.classify_cloud_evidence(tmp_path)
    assert cloud["NWChem"]["level"] == "verified"
    assert cloud["LAMMPS"]["level"] == "accepted"


def test_parse_with_calculation_completed_is_verified(report_module, tmp_path):
    _write(tmp_path / "artifacts_p" / "parse_accept.json",
           {"cases": [{"code": "GROMACS", "input": "conf.gro", "exit": 0,
                       "accepted": True, "calculation_completed": True}]})
    cloud = report_module.classify_cloud_evidence(tmp_path)
    assert cloud["GROMACS"]["level"] == "verified"


def test_canonical_abort_marks_the_code_blocked(report_module, tmp_path):
    _write(tmp_path / "artifacts_q" / "qe_minimal.json",
           {"cases": [{"case": "canonical", "abort": True, "job_done": False},
                      {"case": "exported", "abort": True, "job_done": False}]})
    cloud = report_module.classify_cloud_evidence(tmp_path)
    assert cloud["Quantum ESPRESSO"]["level"] == "blocked"
    assert "canonical" in cloud["Quantum ESPRESSO"]["detail"]


def test_missing_package_marks_cp2k_blocked(report_module, tmp_path):
    _write(tmp_path / "artifacts_apt" / "apt_packages.json",
           {"policy": {"cp2k": "cp2k:\n  Installed: (none)\n  Candidate: (none)"}})
    cloud = report_module.classify_cloud_evidence(tmp_path)
    assert cloud["CP2K"]["level"] == "blocked"


def test_missing_or_broken_artifacts_are_skipped(report_module, tmp_path):
    assert report_module.classify_cloud_evidence(tmp_path) == {}
    (tmp_path / "artifacts_x").mkdir()
    (tmp_path / "artifacts_x" / "acceptance_result.json").write_text("{not json", encoding="utf-8")
    assert report_module.classify_cloud_evidence(tmp_path) == {}


def test_real_repository_evidence_is_consistent(report_module):
    cloud = report_module.classify_cloud_evidence(ROOT / "runs" / "cloud_h3")
    if not cloud:
        pytest.skip("no cloud evidence in this checkout")
    assert cloud.get("NWChem", {}).get("level") == "verified"
    assert cloud.get("NWChem (cifkit template)", {}).get("level") == "verified"
    assert cloud.get("LAMMPS", {}).get("level") in ("accepted", "verified")
