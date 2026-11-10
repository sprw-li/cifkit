"""Rate-limit probe (round 37, limitation A6).

The probe talks to real endpoints, so the tests only pin the *policy* and the
report shape: it must stay a small, polite probe (never a load test) and must
record the fields the documentation quotes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "probe_source_limits.py"


def test_probe_is_bounded():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'ap.add_argument("--paced", type=int, default=5)' in source
    assert 'ap.add_argument("--burst", type=int, default=5)' in source
    assert "not a load test" in source.lower()


def test_probe_records_the_documented_fields():
    source = SCRIPT.read_text(encoding="utf-8")
    for field in ("paced_latency_median_s", "server_pushback", "rate_limited_statuses",
                  "retry_after_seen", "paced_stats"):
        assert field in source, field


def test_report_is_consistent_if_present():
    path = ROOT / "runs" / "source_limits.json"
    if not path.is_file():
        pytest.skip("probe not run in this checkout")
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["policy"]["paced_requests"] <= 10
    assert report["policy"]["unpaced_burst"] <= 10
    for host in report["hosts"].values():
        assert len(host["paced"]) <= report["policy"]["paced_requests"]
        assert len(host["burst"]) <= report["policy"]["unpaced_burst"]
        assert "paced_latency_median_s" in host
