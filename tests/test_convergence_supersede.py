"""Round 54: a cutoff tried twice must yield one sample, not two (and not an average).

cutoff 60 aborted on an 8 GiB box and completed on a 32 GiB box.  Both artifact
directories remain, so the collector needs an explicit rule; these tests pin it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

FINISHED = "Total PSPW energy     :  __E__\nTotal times  cpu: 1s\n"
ABORTED = "Total PSPW energy     :  __E__\nMPI_ABORT was invoked on rank 0\n"


def _write(root: Path, job: str, cutoff: int, energy: str, body: str) -> None:
    directory = root / job / f"cut_{cutoff}"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "nwchem.out").write_text(body.replace("__E__", energy), encoding="utf-8")


def _collect(root: Path, out: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "collect_convergence.py"),
         "--root", str(root), "--pattern", "conv_c*", "--code", "nwchem",
         "--threshold", "3.7e-5", "--per-atom", "16", "--json", str(out)],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600)
    assert proc.returncode == 0, proc.stdout[-600:] + proc.stderr[-600:]
    return json.loads(out.read_text(encoding="utf-8"))


def test_failed_attempt_is_superseded_by_the_successful_retry(tmp_path):
    runs = tmp_path / "runs"
    _write(runs, "conv_c60", 60, "-0.1116899285E+03", ABORTED)
    _write(runs, "conv_c60_big", 60, "-0.1117286759E+03", FINISHED)
    _write(runs, "conv_c20", 20, "-0.1112953510E+03", FINISHED)
    report = _collect(runs, tmp_path / "r.json")

    values = [sample["value"] for sample in report["samples"]]
    assert values == [20.0, 60.0], values
    sixty = next(sample for sample in report["samples"] if sample["value"] == 60.0)
    assert sixty["ok"] is True
    assert sixty["energy"] == pytest.approx(-111.7286759), "the completed run must win"
    assert report["superseded_attempts"], "the discarded attempt must be recorded"
    assert report["superseded_attempts"][0]["value"] == 60.0
    assert report["n_invalid"] == 0


def test_only_failures_still_produce_one_invalid_sample(tmp_path):
    runs = tmp_path / "runs"
    _write(runs, "conv_c60", 60, "-0.1116899285E+03", ABORTED)
    report = _collect(runs, tmp_path / "r.json")
    assert len(report["samples"]) == 1
    assert report["samples"][0]["ok"] is False
    assert report["n_invalid"] == 1


def test_committed_report_matches_its_own_bookkeeping():
    path = ROOT / "runs" / "convergence" / "nwchem_cloud_report.json"
    if not path.is_file():
        pytest.skip("cloud convergence report not present")
    report = json.loads(path.read_text(encoding="utf-8"))
    values = [sample["value"] for sample in report["samples"]]
    assert values == sorted(values), "one row per cutoff value"
    assert len(values) == len(set(values))
    # 'complete' must agree with the sample outcomes: a sweep with a crashed point
    # must not describe itself as complete
    assert report["complete"] is (report["n_invalid"] == 0)
    if report["n_invalid"]:
        assert report["complete"] is False
    usable = [s for s in report["samples"] if s["ok"]]
    assert len(usable) >= 3, "convergence needs at least three usable points"
    # the four completed points must be monotonically *decreasing* in energy
    energies = [s["energy"] for s in usable]
    assert all(b <= a for a, b in zip(energies, energies[1:])), energies
