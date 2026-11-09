"""Release-gate helpers (round 22): external-failure diagnosis + doc consistency."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def check_all():
    return _load("check_all_module", ROOT / "scripts" / "check_all.py")


@pytest.fixture(scope="module")
def release_check():
    return _load("release_check_module", ROOT / "scripts" / "release_check.py")


def test_diagnosis_is_none_when_the_eval_passed(check_all):
    assert check_all.diagnose_agentlib_eval("skill top1: 97/97 = 100.0%") is None
    assert check_all.diagnose_agentlib_eval("") is None


def test_diagnosis_detects_a_missing_skill(check_all):
    """The 2026-11 catalog rename: eval still expected document-pptx after deletion."""
    sample = json.dumps({"query": "把这份材料做成 PPT",
                         "want": "make-presentation / definitely-not-a-skill",
                         "got_ids": ["office-pptx"]}, ensure_ascii=False)
    diagnosis = check_all.diagnose_agentlib_eval(sample)
    assert diagnosis and "missing-skill" in diagnosis
    assert "agent-library" in diagnosis


def test_diagnosis_flags_a_stale_expectation_when_both_skills_exist(check_all):
    """Both ids exist but the new one ranks first → the expectation looks stale."""
    catalog = check_all.AGENTLIB / "catalog"
    wanted, top = "office-pptx", "office-xlsx"
    if not (catalog / wanted).is_dir() or not (catalog / top).is_dir():
        pytest.skip("catalog no longer has both skills")
    sample = json.dumps({"query": "整理这个 Excel", "want": f"document-excel / {wanted}",
                         "got_ids": [top]}, ensure_ascii=False)
    diagnosis = check_all.diagnose_agentlib_eval(sample)
    assert diagnosis and "stale-eval" in diagnosis


def test_diagnosis_reports_router_regression_as_last_resort(check_all):
    catalog = check_all.AGENTLIB / "catalog"
    wanted = top = next((d.name for d in catalog.glob("cif-*") if d.is_dir()), None)
    if not wanted:
        pytest.skip("no cif-* skills in the catalog")
    sample = json.dumps({"query": "x", "want": f"some-intent / {wanted}", "got_ids": [top]},
                        ensure_ascii=False)
    # same id on both sides is not a stale/missing case; it must not be mislabelled
    diagnosis = check_all.diagnose_agentlib_eval(sample)
    assert diagnosis is None or "stale-eval" not in diagnosis


def test_limitations_summary_must_match_the_rows(release_check):
    good = """
| A1 | x | 🟡 | a | b | c |
| A2 | y | 🔴 | a | b | c |
**共 2 条局限 = 0 ✅（已修/已覆盖） / 1 🟡（可绕过/已知边界） / 1 🔴（未解决/未验证）**
"""
    ok, detail = release_check.limitations_summary_ok(good)
    assert ok, detail

    stale = good.replace("共 2 条局限 = 0 ✅", "共 3 条局限 = 0 ✅")
    ok, detail = release_check.limitations_summary_ok(stale)
    assert not ok and "stated 3" in detail


def test_the_real_limitations_file_is_consistent(release_check):
    text = (ROOT / "docs" / "LIMITATIONS.md").read_text(encoding="utf-8")
    ok, detail = release_check.limitations_summary_ok(text)
    assert ok, detail
