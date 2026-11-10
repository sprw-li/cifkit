"""CI definition drift check (round 40, limitation H4).

The workflow has never run on a real runner, but it *can* be kept honest: every
script it calls must exist, every gate script must be reachable from CI, and every
script that is deliberately out of CI must be classified.  These tests pin that.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ci():
    spec = importlib.util.spec_from_file_location("check_ci", ROOT / "scripts" / "check_ci.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_every_shipped_script_is_classified(ci):
    """Each script is reachable from CI (directly or through check_all) or on-demand."""
    workflow = ci.load_workflow(ci.WORKFLOW)
    info = ci.analyse(workflow)
    assert not info["unclassified"], sorted(info["unclassified"])
    assert info["gate"], "check_all.py should reference at least one script"


def test_on_demand_catalogue_has_reasons(ci):
    assert ci.ON_DEMAND
    for name, reason in ci.ON_DEMAND.items():
        assert reason and len(reason) > 8, f"{name} needs a real reason"


def test_real_workflow_passes_the_checks(ci):
    workflow = ci.load_workflow(ci.WORKFLOW)
    results = ci.check(workflow, ci.extract_commands(workflow))
    failures = [item for item in results if not item["ok"]]
    assert not failures, failures


def test_a_missing_script_is_detected(ci, tmp_path):
    workflow = ci.load_workflow(ci.WORKFLOW)
    # inject a step that calls a script which does not exist
    workflow["jobs"]["test"]["steps"].append({"name": "bogus",
                                              "run": "python scripts/does_not_exist.py"})
    results = {item["check"]: item for item in ci.check(workflow,
                                                        ci.extract_commands(workflow))}
    assert not results["every referenced script exists"]["ok"]


def test_report_shape_if_present():
    path = ROOT / "runs" / "check_ci.json"
    if not path.is_file():
        pytest.skip("check_ci not run in this checkout")
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert len(report["checks"]) >= 8
