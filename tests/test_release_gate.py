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


def test_diagnosis_detects_a_missing_skill(check_all, tmp_path):
    """The 2026-11 catalog rename: eval still expected document-pptx after deletion."""
    sample = json.dumps({"query": "把这份材料做成 PPT",
                         "want": "make-presentation / definitely-not-a-skill",
                         "got_ids": ["office-pptx"]}, ensure_ascii=False)
    diagnosis = check_all.diagnose_agentlib_eval(sample, catalog=tmp_path)
    assert diagnosis and "missing-skill" in diagnosis
    assert "catalog" in diagnosis


def test_diagnosis_flags_a_stale_expectation_when_both_skills_exist(check_all, tmp_path):
    """Both ids exist but the new one ranks first → the expectation looks stale."""
    wanted, top = "office-pptx", "office-xlsx"
    (tmp_path / wanted).mkdir()
    (tmp_path / top).mkdir()
    sample = json.dumps({"query": "整理这个 Excel", "want": f"document-excel / {wanted}",
                         "got_ids": [top]}, ensure_ascii=False)
    diagnosis = check_all.diagnose_agentlib_eval(sample, catalog=tmp_path)
    assert diagnosis and "stale-eval" in diagnosis


def test_diagnosis_reports_router_regression_as_last_resort(check_all, tmp_path):
    wanted = "cif-workbench"
    (tmp_path / wanted).mkdir()
    sample = json.dumps({"query": "x", "want": f"some-intent / {wanted}", "got_ids": [wanted]},
                        ensure_ascii=False)
    # same id on both sides is not a stale/missing case; it must not be mislabelled
    diagnosis = check_all.diagnose_agentlib_eval(sample, catalog=tmp_path)
    assert diagnosis is None or "stale-eval" not in diagnosis


def test_external_catalog_is_opt_in_and_never_required(check_all):
    """No CIF functionality may depend on another checkout (round 58)."""
    import importlib.util
    import os

    if os.environ.get("CIFKIT_AGENTLIB"):
        pytest.skip("CIFKIT_AGENTLIB is set in this environment")
    assert check_all.AGENTLIB is None, "AGENTLIB must default to None, not a machine path"
    release = _load("release_check_module2", ROOT / "scripts" / "release_check.py")
    assert release.AGENTLIB is None
    # the skills this project owns are linted from the repository itself
    assert check_all.SKILLS_DIR == ROOT / "skills"
    assert check_all.SKILL_CHECK == ROOT / "scripts" / "check_skill.py"


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


def test_limitations_group_table_must_match_the_rows(release_check):
    """Round 57: the J group row claimed 1✅/7🟡 for weeks while J4 and J8 were
    both ✅ — the group summary table itself was never parsed.  The gate must
    reject a stale group row (by entry-ID prefix, matching the headline gate)."""
    good = """
| A1 | x | 🟡 | a | b | c |
| A2 | y | ✅ | a | b | c |
| B1 | z | 🟡 | a | b | c |

| 组 | 主题 | 条目 | ✅ | 🟡 | 🔴 |
|---|---|---|---|---|---|
| A | alpha | 2 | 1 | 1 | 0 |
| B | beta | 1 | 0 | 1 | 0 |
"""
    ok, detail = release_check.limitations_group_table_ok(good)
    assert ok, detail

    stale = good.replace("| A | alpha | 2 | 1 | 1 | 0 |", "| A | alpha | 2 | 0 | 2 | 0 |")
    ok, detail = release_check.limitations_group_table_ok(stale)
    assert not ok and "A:" in detail


def test_the_real_limitations_group_table_is_consistent(release_check):
    text = (ROOT / "docs" / "LIMITATIONS.md").read_text(encoding="utf-8")
    ok, detail = release_check.limitations_group_table_ok(text)
    assert ok, detail
