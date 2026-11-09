"""check_all's --json report must capture enough to diagnose a failure (round 21).

Motivation: a run printed "9/10 groups passed" and there was no way to tell which
group failed or why.  The report now stores per-group status plus the full stdout
and stderr tails, so a flake is always diagnosable after the fact.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_fast_report_has_every_group_and_outputs(tmp_path):
    out = tmp_path / "report.json"
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_all.py"),
                           "--fast", "--skip-agentlib", "--json", str(out)],
                          cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=1800)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["total"] == report["passed"] >= 3
    assert {"name", "ok", "detail"} <= set(report["groups"][0])
    assert len(report["outputs"]) >= 3
    for output in report["outputs"]:
        assert {"name", "command", "exit_code", "stdout_tail", "stderr_tail"} <= set(output)
    print("groups:", [(g["name"], g["ok"]) for g in report["groups"]])


def test_report_records_a_failing_group(tmp_path):
    """A non-zero group must appear with ok=False and its stderr preserved."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_all", ROOT / "scripts" / "check_all.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    module.DETAIL.clear()
    ok, detail = module.run("intentional-failure", [sys.executable, "-c",
                                                   "import sys; sys.stderr.write('boom\\n'); sys.exit(7)"])
    assert ok is False and "exit 7" in detail
    assert module.DETAIL and module.DETAIL[-1]["exit_code"] == 7
    assert "boom" in module.DETAIL[-1]["stderr_tail"]
