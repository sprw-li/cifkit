"""CIF → anything CLI: convert / features / dataset (and pipeline --bundle)."""
from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ZIF8 = ROOT / "tests" / "data" / "zif8_cr_sod.cif"


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


@pytest.mark.skipif(not ZIF8.is_file(), reason="fixture missing")
def test_convert_core_formats_and_json_purity(tmp_path):
    out = tmp_path / "conv"
    proc = _run(["convert", str(ZIF8), "--to", "vasp,cif,xyz", "--outdir", str(out), "--json"])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)  # stdout must be pure JSON
    assert data["ok"] is True and data["natoms"] > 50
    for path in data["formats"].values():
        assert Path(path).is_file()
    from pymatgen.core import Structure

    s_vasp = Structure.from_file(data["formats"]["vasp"])
    s_cif = Structure.from_file(data["formats"]["cif"])
    assert len(s_vasp) == len(s_cif) == data["natoms"]


def test_convert_requires_a_target(tmp_path):
    proc = _run(["convert", str(ZIF8), "--outdir", str(tmp_path / "x"), "--json"])
    assert proc.returncode == 2
    assert "to" in (proc.stderr or "") or "bundle" in (proc.stderr or "")


def test_convert_unknown_format_errors(tmp_path):
    proc = _run(["convert", str(ZIF8), "--to", "not-a-format", "--outdir", str(tmp_path / "y"), "--json"])
    assert proc.returncode == 2
    assert "unsupported" in (proc.stderr or "").lower()


def _has_bundles() -> bool:
    try:
        from cifkit import export

        return hasattr(export, "write_bundle") and bool(export.supported_bundles())
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _has_bundles(), reason="export bundles not available yet")
def test_convert_bundle_vasp_and_qe(tmp_path):
    out = tmp_path / "bundles"
    proc = _run(["convert", str(ZIF8), "--bundle", "vasp,qe", "--outdir", str(out), "--json"])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    for code in ("vasp", "qe"):
        info = data["bundles"][code]
        files = info.get("files", info) if isinstance(info, dict) else info
        assert files, f"bundle {code} produced no files"
    assert any((out / "vasp").iterdir())


def test_features_cli(tmp_path):
    pytest.importorskip("cifkit.features")
    out = tmp_path / "features.csv"
    proc = _run(["features", str(ZIF8), "--out", str(out), "--no-rdf", "--json", "--jobs", "1"])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["n_ok"] == 1 and data["n_failed"] == 0
    rows = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    assert len(rows) == 1
    assert rows[0]["formula"] and rows[0]["spacegroup_number"]


def test_dataset_cli(tmp_path):
    pytest.importorskip("cifkit.dataset")
    runs = tmp_path / "runs" / "run1"
    runs.mkdir(parents=True)
    shutil.copyfile(ZIF8, runs / "standardized.cif")
    manifest = {
        "ok": True,
        "spec": {"query": "test", "outdir": str(runs)},
        "artifacts": {"standardized.cif": str(runs / "standardized.cif")},
        "source": {"record": {"record_id": "core-mof:test", "topology": "sod", "topology_evidence": "verified"}},
        "steps": [],
    }
    (runs / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    out = tmp_path / "dataset"
    proc = _run(["dataset", "--from-runs", str(tmp_path / "runs"), "--outdir", str(out),
                 "--label-key", "topology", "--json"])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data.get("n_failed", 0) == 0
    assert (out / "dataset.csv").is_file()
    rows = list(csv.DictReader((out / "dataset.csv").open(encoding="utf-8-sig")))
    assert rows and rows[0].get("label") == "sod"


def test_features_dir_dedupes_case_insensitive_glob(tmp_path):
    """P1 (Round 8): *.cif and *.CIF both match on Windows; directory inputs must be deduped."""
    pytest.importorskip("cifkit.features")
    src = tmp_path / "cifs"
    src.mkdir()
    for name in ("a.cif", "b.CIF", "c.cif"):
        shutil.copyfile(ZIF8, src / name)
    out = tmp_path / "f.csv"
    proc = _run(["features", str(src), "--out", str(out), "--no-rdf", "--json", "--jobs", "1"])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["n_inputs"] == 3 and data["n_ok"] == 3, data
    rows = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    assert len(rows) == 3
