"""Lead-owned CLI contract tests (Round-2 review findings: JSON purity, --spec BOM, failed-run report)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "data"
H_FREE = FIXTURES / "zif8_raw_hfree.cif"


def _run(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "cifkit", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=300,
    )


def test_pipeline_json_stdout_is_pure_json(tmp_path):
    """P1-1: --json stdout must parse as JSON; step logs go to stderr."""
    out = tmp_path / "run"
    proc = _run([
        "pipeline",
        f"把 {H_FREE} 补氢后导出 cif",
        "--outdir", str(out),
        "--format", "cif",
        "--json",
    ])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)  # must not raise
    assert data["ok"] is True
    names = [s["name"] for s in data["steps"]]
    assert "manifest" in names
    assert "resolve" in names


def test_manifest_artifacts_include_manifest_and_report(tmp_path):
    """P2-4: manifest.json must list itself and report.md among artifacts."""
    out = tmp_path / "run"
    proc = _run(["pipeline", f"把 {H_FREE} 补氢后导出 cif", "--outdir", str(out), "--format", "cif"])
    assert proc.returncode == 0, proc.stderr
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["ok"] is True
    assert set(manifest["artifacts"]) >= {"manifest", "report", "raw.cif", "repaired.cif"}


def test_spec_with_utf8_bom(tmp_path):
    """P2-1: --spec must tolerate UTF-8 BOM (Windows PowerShell 5.1 default)."""
    spec = {
        "query": "bom spec",
        "source": "local",
        "structure_id": str(H_FREE),
        "repair_h": True,
        "output_formats": ["cif"],
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text("\ufeff" + json.dumps(spec), encoding="utf-8")
    out = tmp_path / "run"
    proc = _run(["pipeline", "--spec", str(spec_path), "--outdir", str(out), "--json"])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["ok"] is True


def test_spec_with_utf16_encoding(tmp_path):
    """--spec must tolerate UTF-16 (PowerShell 5.1 `>` default) as well."""
    spec = {
        "query": "utf16 spec",
        "source": "local",
        "structure_id": str(H_FREE),
        "repair_h": True,
        "output_formats": ["cif"],
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-16")
    out = tmp_path / "run"
    proc = _run(["pipeline", "--spec", str(spec_path), "--outdir", str(out), "--json"])
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["ok"] is True


def test_failed_run_writes_report_without_duplicate_steps(tmp_path):
    """P2-2: a failed run still writes manifest/report, one failed step, and section 4."""
    out = tmp_path / "run"
    proc = _run([
        "pipeline",
        f"把 {H_FREE} 补氢后导出 cif",
        "--outdir", str(out),
        "--topology", "pcu",  # deliberately wrong topology for a ZIF-8 CIF
        "--format", "cif",
    ])
    assert proc.returncode == 1
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["ok"] is False
    assert manifest["failed_step"] == "verify-topology"
    failed = [s for s in manifest["steps"] if s["status"] == "failed"]
    assert len(failed) == 1, failed
    report = (out / "report.md").read_text(encoding="utf-8")
    assert report.count("❌ verify-topology") == 1
    assert "校验：未运行" in report


def test_unsupported_export_format_exits_2(tmp_path):
    """P1: unsupported formats must fail loudly (no silent wrong file)."""
    proc = _run(["export", str(H_FREE), "--format", "bogus-format", "-o", str(tmp_path / "x")])
    assert proc.returncode == 2
    assert "unsupported" in (proc.stderr + proc.stdout).lower()


def test_route_without_structure_info_exits_2():
    proc = _run(["route", "帮我处理一下这个结构，加氢"])
    assert proc.returncode == 2
    assert "没有识别到拓扑" in proc.stdout or "没有识别到" in proc.stdout


def test_repair_creates_output_parent_dir(tmp_path):
    """P2: repair -o must create missing parent directories."""
    out = tmp_path / "a" / "b" / "repaired.cif"
    proc = _run(["repair", str(H_FREE), "-o", str(out), "--add-h", "--json"])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["natoms"] == 276
    assert out.is_file()


def test_fetch_json_with_outdir_stdout_is_pure_json(tmp_path):
    """P1 (Round 4): `fetch --json --outdir` stdout must stay a single JSON array.

    The "wrote ..." status line belongs on stderr; docs/SKILL use this combo.
    """
    out = tmp_path / "fetch"
    proc = _run([
        "fetch", "--source", "local", "--id", str(H_FREE),
        "--outdir", str(out), "--json",
    ])
    assert proc.returncode == 0, proc.stderr
    hits = json.loads(proc.stdout)  # must not raise
    assert isinstance(hits, list) and hits
    assert (out / "raw.cif").is_file()
    assert "wrote" in proc.stderr


def test_sources_command_lists_databases():
    """`cifkit sources --json` must list every adapter with auth metadata."""
    proc = _run(["sources", "--json"])
    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    by_name = {row["name"]: row for row in rows}
    assert {"core-mof", "cod", "local", "materials-project", "aflow"} <= set(by_name)
    assert by_name["materials-project"]["requires_auth"] is True
    assert by_name["aflow"]["requires_auth"] is False
    assert "description" in by_name["cod"]


def test_fetch_mp_without_key_fails_clearly(monkeypatch):
    """MP without a key must fail with an actionable message, not a traceback."""
    env = {"PYTHONIOENCODING": "utf-8"}
    import os

    base_env = dict(os.environ)
    base_env.pop("MP_API_KEY", None)
    base_env.pop("PMG_MAPI_KEY", None)
    base_env.update(env)
    proc = __import__("subprocess").run(
        [sys.executable, "-m", "cifkit", "fetch", "--source", "mp", "--id", "mp-149"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=base_env, timeout=120,
    )
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "MP_API_KEY" in combined
