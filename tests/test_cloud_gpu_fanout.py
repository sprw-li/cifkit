"""Fan-out launcher logic that must never be wrong (round 30).

These pin the four things the parallel audit found broken: job-id extraction from
noisy CLI output, the worst-case cost plan (queue time included), the photon gate
semantics, and the fact that a submission whose output cannot be parsed must abort
instead of leaving a billed orphan.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def fanout():
    spec = importlib.util.spec_from_file_location("cloud_gpu_fanout",
                                                  ROOT / "scripts" / "cloud_gpu_fanout.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_extract_job_id_from_noisy_output(fanout):
    """The real failure: upload-progress objects followed by the payload."""
    text = ('{"phase":"start","sent_bytes":0}\n{"phase":"confirmed","sent_bytes":5463}\n'
            '{\n  "ok": true,\n  "data": {\n    "jobId": "7a8cb39189b14a158137157381d8ce40"\n  }\n}\n')
    assert fanout.extract_job_id(text, fanout.json_from(text)) == "7a8cb39189b14a158137157381d8ce40"


def test_extract_job_id_from_the_payload_alone(fanout):
    text = '{"ok": true, "data": {"jobId": "774a6dd5dcc94815812ad39df2d42319"}}'
    assert fanout.extract_job_id(text, fanout.json_from(text)) == "774a6dd5dcc94815812ad39df2d42319"


def test_extract_job_id_returns_none_when_absent(fanout):
    assert fanout.extract_job_id('{"ok": true, "data": {}}', {"ok": True, "data": {}}) is None


def test_plan_includes_queue_time(fanout):
    plan = fanout.plan(jobs=8, run_minutes=6, wait_minutes=25, price=6.0,
                       sku="4090", photon_per_rmb=95.0)
    # 8 * (6 + 25)/60 * 6 = 24.8 RMB — the old code reported 9.6
    assert plan["worst_case_with_queue_rmb"] == pytest.approx(24.8)
    assert plan["max_wait_time_minutes"] == 25
    assert plan["worst_case_photons"] == pytest.approx(24.8 * 95.0, rel=1e-3)


def test_plan_run_only_excludes_queue(fanout):
    plan = fanout.plan(8, 6, 25, 6.0, "4090", 95.0)
    assert plan["worst_case_run_only_rmb"] == pytest.approx(4.8)


def test_a_six_photon_balance_cannot_afford_even_one_gpu_job(fanout):
    """Documented reality of round 30: the session's own billing consumed the photons.

    The gate must therefore refuse, not submit: the projection is what is compared.
    """
    small = fanout.plan(1, 2, 5, 6.0, "4090", 95.0)
    large = fanout.plan(8, 6, 25, 6.0, "4090", 95.0)
    assert small["worst_case_photons"] > 6, small
    assert large["worst_case_photons"] > small["worst_case_photons"] * 8


def test_launcher_has_the_hard_gates(fanout):
    source = (ROOT / "scripts" / "cloud_gpu_fanout.py").read_text(encoding="utf-8")
    for marker in ("refusing: photon balance unknown",
                   "projected worst case",
                   "ABORT:",
                   "batchjob\", \"kill",
                   "submissions_",          # ledger is namespaced per run id
                   "--run-id",
                   "--resume"):
        assert marker in source, marker


def test_upload_allowlist_excludes_compiled_caches(fanout):
    submit = (ROOT / "scripts" / "cloud_h3_submit.py").read_text(encoding="utf-8")
    assert "__pycache__" in submit and "UPLOAD_EXCLUDES" in submit
    spec = importlib.util.spec_from_file_location("cloud_h3_submit",
                                                  ROOT / "scripts" / "cloud_h3_submit.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bundle = ROOT / "cloud_h3"
    files = module.bundle_files(bundle)
    assert files, "about to upload nothing?"
    assert not [f for f in files if f.suffix == ".pyc" or "__pycache__" in str(f)]
