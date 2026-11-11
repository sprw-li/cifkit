"""Completion detection: an aborted run is not evidence (round 51).

The 60/80 Ha jobs printed energies *and* ``MPI_ABORT ... out of heap memory``, and the
batch job itself was reported as ``succeeded``.  These tests pin that the collector
refuses those numbers instead of publishing a physics-looking table.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from cifkit.export.convergence import COMPLETION_MARKERS, FAILURE_MARKERS, output_completed

ROOT = Path(__file__).resolve().parents[1]

FINISHED = """\\
Total PSPW energy     :  -0.1112953510E+03
Total times  cpu: 1020.8s     wall: 1031.8s
"""

ABORTED = """\\
Total PSPW energy     :  -0.1116695201E+03
 electron_init: out of heap memory                   0
[0] ARMCI Error: 0:electron_init: out of heap memory:
MPI_ABORT was invoked on rank 0
"""


def test_finished_run_is_accepted():
    ok, why = output_completed(FINISHED)
    assert ok and "Total times" in why


def test_aborted_run_is_rejected_even_though_it_printed_an_energy():
    ok, why = output_completed(ABORTED)
    assert not ok
    assert "MPI_ABORT" in why or "heap" in why


def test_empty_output_is_not_a_completion():
    ok, why = output_completed("")
    assert not ok and "no completion marker" in why


def test_boundary_overflow_is_rejected():
    ok, _ = output_completed("!    total energy = -76.0 Ry\n*** buffer overflow detected ***\n")
    assert not ok


@pytest.mark.parametrize("marker", COMPLETION_MARKERS)
def test_every_completion_marker_is_recognised(marker):
    ok, _ = output_completed(f"some output\n{marker}\n")
    assert ok


@pytest.mark.parametrize("marker", FAILURE_MARKERS)
def test_every_failure_marker_wins_over_completion(marker):
    ok, why = output_completed(f"{marker}\nTotal times  cpu: 1s\n")
    assert not ok, f"{marker} must invalidate a run that also printed a completion line"


def _write_run(root: Path, cutoff: int, energy: str, body: str) -> None:
    directory = root / f"conv_c{cutoff}" / f"cut_{cutoff}"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "nwchem.out").write_text(body.replace("__E__", energy), encoding="utf-8")


def test_collector_drops_aborted_runs_and_counts_them(tmp_path):
    runs = tmp_path / "runs"
    _write_run(runs, 20, "-0.1112953510E+03",
               "Total PSPW energy     :  __E__\nTotal times  cpu: 1s\n")
    _write_run(runs, 30, "-0.1116378257E+03",
               "Total PSPW energy     :  __E__\nTotal times  cpu: 1s\n")
    _write_run(runs, 60, "-0.1116899285E+03",
               "Total PSPW energy     :  __E__\nMPI_ABORT was invoked on rank 0\n")

    out = tmp_path / "report.json"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "collect_convergence.py"),
         "--root", str(runs), "--pattern", "conv_c*", "--code", "nwchem",
         "--threshold", "3.7e-5", "--per-atom", "16", "--json", str(out)],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600)
    assert proc.returncode == 0, proc.stderr[-600:]
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["n_invalid"] == 1
    by_value = {sample["value"]: sample for sample in report["samples"]}
    assert by_value[60.0]["energy"] is None, "an aborted run must not publish an energy"
    assert by_value[60.0]["ok"] is False
    assert "aborted" in by_value[60.0]["detail"]
    assert by_value[20.0]["energy"] == pytest.approx(-111.2953510)
