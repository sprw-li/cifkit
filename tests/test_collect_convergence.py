"""Integration test for the per-cutoff collector (round 48).

The collector is the piece that turned three successful-but-unparsed jobs into a
real convergence table, so it gets its own test: build a fake job tree, run the
script, and check the report.  This also pins the directory-name parsing bug that
made the first attempt return "no outputs matched" while the files were present.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = """\
 iter.           Energy         DeltaE       DeltaRho
    1    -0.1076404459E+03
Total PSPW energy     :  -0.1076404459E+03
    2    -0.1112953510E+03
Total PSPW energy     :  -0.1112953510E+03
Total times  cpu: 1020.8s     wall: 1031.8s
"""


@pytest.fixture
def fake_jobs(tmp_path):
    for cutoff, energy in ((20, "-0.1112953510E+03"), (30, "-0.1116378257E+03"),
                           (40, "-0.1116688537E+03")):
        directory = tmp_path / "runs" / f"conv_c{cutoff}" / f"cut_{cutoff}"
        directory.mkdir(parents=True)
        (directory / "nwchem.out").write_text(
            OUTPUT.replace("-0.1112953510E+03", energy), encoding="utf-8")
    return tmp_path / "runs"


def test_collector_builds_a_report(fake_jobs, tmp_path):
    out = tmp_path / "report.json"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "collect_convergence.py"),
         "--root", str(fake_jobs), "--pattern", "conv_c*", "--code", "nwchem",
         "--threshold", "3.7e-5", "--per-atom", "16", "--json", str(out)],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600)
    assert proc.returncode == 0, proc.stdout[-800:] + proc.stderr[-800:]
    report = json.loads(out.read_text(encoding="utf-8"))
    assert [sample["value"] for sample in report["samples"]] == [20.0, 30.0, 40.0]
    assert report["samples"][0]["energy"] == pytest.approx(-111.2953510)
    assert report["samples"][2]["energy"] == pytest.approx(-111.6688537)
    # per-atom threshold of ~1 meV: this sweep must NOT be called converged
    assert report["converged_at"] is None
    assert report["complete"] is True
    assert len(report["sources"]) == 3


def test_collector_uses_the_last_energy_of_each_output(fake_jobs, tmp_path):
    """The first PSPW line in a file is an early iteration, not the run's energy."""
    import importlib.util

    from cifkit.export.convergence import parse_energy

    spec = importlib.util.spec_from_file_location(
        "collector", ROOT / "scripts" / "collect_convergence.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    text = (fake_jobs / "conv_c20" / "cut_20" / "nwchem.out").read_text(encoding="utf-8")
    assert parse_energy(text) == pytest.approx(-111.2953510)


def test_collector_reports_nothing_when_there_is_no_match(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "collect_convergence.py"),
         "--root", str(tmp_path), "--pattern", "nope*", "--json", str(tmp_path / "r.json")],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600)
    assert proc.returncode == 1
    assert "no outputs matched" in proc.stdout
