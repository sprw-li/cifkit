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


def test_batch_manifest_written_when_subprocess_spawn_fails(tmp_path, monkeypatch):
    """P1 (round 57): a spawn-level failure (OSError from subprocess.run) must be
    recorded in batch_manifest.json instead of losing the whole batch record —
    PERFORMANCE.md promises "任一失败 exit 1 但其余 run 仍完成并进入 manifest"."""
    import cifkit.cli as cli_module

    def boom(*args, **kwargs):
        raise OSError("injected spawn failure")

    monkeypatch.setattr(cli_module.subprocess, "run", boom)
    out = tmp_path / "batch"
    code = cli_module.main(["batch", "--spec", SPEC_LOCAL, "--spec", SPEC_LOCAL,
                            "--jobs", "2", "--outdir", str(out), "--json"])
    assert code == 1
    manifest = json.loads((out / "batch_manifest.json").read_text(encoding="utf-8"))
    assert manifest["jobs"] == 2 and manifest["ok"] == 0
    for run in manifest["runs"]:
        assert run["ok"] is False
        assert "spawn failed" in run["stderr_tail"]
        assert run["returncode"] is None


def test_batch_timeout_records_returncode_none(tmp_path):
    """The timeout path must be recorded (returncode=None) and still write the
    batch manifest; previously only exit!=0 subprocesses were covered."""
    out = tmp_path / "batch_to"
    proc = _run(["batch", "--spec", SPEC_LOCAL, "--jobs", "1", "--timeout", "1",
                 "--outdir", str(out), "--json"])
    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert data["ok"] == 0 and data["jobs"] == 1
    run = data["runs"][0]
    assert run["returncode"] is None and "timeout" in run["stderr_tail"]
    assert (out / "batch_manifest.json").is_file()
