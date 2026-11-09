"""Live data-source health check (round 25): offline-testable parts only.

The network parts are exercised by running the script; these tests pin the logic
that must be right even when a database is down or the machine is offline.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("sources_live_check",
                                                  ROOT / "scripts" / "sources_live_check.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def live():
    return _load()


def test_local_dataset_check_works_offline(live):
    """core-mof is local: its result must not depend on the network at all."""
    result = live.check_core_mof()
    assert result["status"] in ("ok", "fail")   # 'fail' only when the cache is absent
    if result["status"] == "ok":
        assert result["n_entries"] > 0


def test_tcp_probe_reports_unreachable_without_hanging(live):
    # 127.0.0.1:1 is essentially always closed; the probe must return, not raise
    result = live.tcp_probe("127.0.0.1", 1, timeout=1.0)
    assert result["reachable"] is False
    assert "error" in result
    assert result["seconds"] < 5


def test_markdown_renderer_covers_every_source(live):
    report = {
        "sources": {
            "core-mof": {"status": "ok", "n_entries": 8300, "seconds": 0.05},
            "cod": {"status": "ok", "n_hits": 3, "first": "cod:1", "seconds": 10.4},
            "materials-project": {"status": "needs-key",
                                  "note": "set MP_API_KEY", "tcp": {"seconds": 1.3}},
            "qmof": {"status": "not-configured", "n_cif": 0, "note": "no mirror"},
            "broken": {"status": "fail", "error": "TimeoutError: boom"},
        }
    }
    md = live.render_markdown(report)
    assert md.startswith("| 数据源 | 状态 |")
    for name in report["sources"]:
        assert f"`{name}`" in md
    assert "8300 条索引" in md and "n_hits=3" in md
    assert "set MP_API_KEY" in md and "TimeoutError: boom" in md


def test_repository_report_matches_the_script_if_present(live):
    path = ROOT / "runs" / "sources_live.json"
    if not path.is_file():
        pytest.skip("live report not generated yet")
    import json

    report = json.loads(path.read_text(encoding="utf-8"))
    assert set(report["sources"]) >= {"core-mof", "cod", "aflow", "materials-project"}
    rendered = live.render_markdown(report)
    assert "materials-project" in rendered
