"""``cifkit batch``: concurrent multi-structure pipeline runs."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC_LOCAL = "把 tests/data/zif8_cr_sod.cif 导出为 vasp"


def _run(args, timeout: int = 300):
    return subprocess.run(
        [sys.executable, "-m", "cifkit", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


@pytest.mark.skipif(not (ROOT / "tests/data/zif8_cr_sod.cif").is_file(), reason="fixture missing")
def test_batch_two_local_specs(tmp_path):
    out = tmp_path / "batch"
    proc = _run(["batch", "--spec", SPEC_LOCAL, "--spec", SPEC_LOCAL,
                 "--jobs", "2", "--outdir", str(out), "--json"])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)  # stdout must be pure JSON
    assert data["jobs"] == 2 and data["ok"] == 2 and data["concurrency"] == 2
    assert (out / "batch_manifest.json").is_file()
    for run in data["runs"]:
        assert run["ok"] is True
        assert (Path(run["outdir"]) / "manifest.json").is_file()


def test_batch_specs_file_and_failure(tmp_path):
    out = tmp_path / "batch2"
    specs = tmp_path / "specs.jsonl"
    specs.write_text(
        "\n".join([
            json.dumps({"spec": SPEC_LOCAL, "outdir": str(out / "a")}),
            json.dumps({"spec": "把 tests/data/does_not_exist.cif 导出为 vasp"}),
        ]) + "\n",
        encoding="utf-8",
    )
    proc = _run(["batch", "--specs-file", str(specs), "--jobs", "2", "--outdir", str(out), "--json"])
    assert proc.returncode == 1  # one of two jobs must fail
    data = json.loads(proc.stdout)
    assert data["jobs"] == 2 and data["ok"] == 1
    assert (Path(out / "a") / "manifest.json").is_file()


def test_batch_rejects_empty_specs(tmp_path):
    proc = _run(["batch", "--outdir", str(tmp_path / "x"), "--json"])
    assert proc.returncode == 2
    assert "spec" in (proc.stderr or "").lower()
