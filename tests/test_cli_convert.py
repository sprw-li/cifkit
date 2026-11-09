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


def test_pipeline_bundle_writes_deck(tmp_path):
    pytest.importorskip("cifkit.export")
    out = tmp_path / "pipe"
    proc = _run(["pipeline", "把 tests/data/zif8_cr_sod.cif 导出为 vasp", "--outdir", str(out),
                 "--bundle", "vasp", "--json"])
    assert proc.returncode == 0, proc.stderr
    # stdout may contain step logs from the pipeline in this process; just check artifacts
    bundle_dir = out / "bundles" / "vasp"
    assert (bundle_dir / "POSCAR").is_file()
    assert (bundle_dir / "INCAR").is_file()
    assert (bundle_dir / "POTCAR.readme").is_file()
    assert not (bundle_dir / "POTCAR").exists()


def test_features_rings_cli(tmp_path):
    pytest.importorskip("cifkit.features")
    out = tmp_path / "f.csv"
    proc = _run(["features", str(ZIF8), "--out", str(out), "--no-rdf", "--rings", "--json", "--jobs", "1"])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["n_ok"] == 1
    rows = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    assert rows and rows[0]["ring_sizes"]


def test_convert_directory_batch_manifest(tmp_path):
    """Directory input → one manifest + flat outputs; case-insensitive dupes deduped."""
    src = tmp_path / "cifs"
    src.mkdir()
    for name in ("a.cif", "b.CIF", "c.cif"):
        shutil.copyfile(ZIF8, src / name)
    out = tmp_path / "out"
    proc = _run(["convert", str(src), "--to", "vasp,xyz", "--outdir", str(out), "--json"])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["n_inputs"] == 3 and data["n_ok"] == 3 and data["n_failed"] == 0
    assert (out / "convert_manifest.json").is_file()
    for stem in ("a", "b", "c"):
        assert (out / stem / f"{stem}.vasp").is_file()
        assert (out / stem / f"{stem}.xyz").is_file()
    assert all(run["outdir"].endswith(run["input"].split("\\")[-1].rsplit(".", 1)[0])
               for run in data["runs"])


def test_convert_batch_records_bad_input(tmp_path):
    src = tmp_path / "mixed"
    src.mkdir()
    shutil.copyfile(ZIF8, src / "good.cif")
    (src / "bad.cif").write_text("this is not a CIF at all\n", encoding="utf-8")
    out = tmp_path / "out2"
    proc = _run(["convert", str(src), "--to", "vasp", "--outdir", str(out), "--json"])
    assert proc.returncode == 1  # one bad input → exit 1, but the good one still converted
    data = json.loads(proc.stdout)
    assert data["n_ok"] == 1 and data["n_failed"] == 1
    assert (out / "good" / "good.vasp").is_file()
    bad = [run for run in data["runs"] if not run["ok"]]
    assert bad and "error" in bad[0]


def test_convert_rejects_unknown_bundle(tmp_path):
    proc = _run(["convert", str(ZIF8), "--bundle", "nope", "--outdir", str(tmp_path / "z"), "--json"])
    assert proc.returncode == 2
    assert "bundle" in (proc.stderr or "").lower()


def test_convert_batch_disambiguates_duplicate_stems(tmp_path):
    """P1 (round 10 self-check): identical file names from different dirs must not clobber."""
    d1 = tmp_path / "d1"
    d2 = tmp_path / "d2"
    d1.mkdir()
    d2.mkdir()
    shutil.copyfile(ZIF8, d1 / "same.cif")
    shutil.copyfile(ZIF8, d2 / "same.cif")
    out = tmp_path / "out"
    proc = _run(["convert", str(d1 / "same.cif"), str(d2 / "same.cif"),
                 "--to", "vasp", "--outdir", str(out), "--json"])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["n_ok"] == 2
    outputs = sorted(p.name for p in out.glob("*/same*.vasp"))
    assert len(outputs) == 2, outputs
    outdirs = {Path(run["outdir"]).name for run in data["runs"]}
    assert len(outdirs) == 2, outdirs


def test_convert_single_with_stem_stays_flat(tmp_path):
    """Round-9 behaviour kept: single input + --stem X → outdir/X.vasp (no subdir)."""
    out = tmp_path / "flat"
    proc = _run(["convert", str(ZIF8), "--to", "vasp", "--stem", "myslab",
                 "--outdir", str(out), "--json"])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert (out / "myslab.vasp").is_file()
    assert not (out / "myslab").exists()
    assert data["formats"]["vasp"].endswith("myslab.vasp")


def test_convert_single_cif_directory_is_batch(tmp_path):
    """A *directory* argument always means batch: subdir + convert_manifest.json."""
    src = tmp_path / "one"
    src.mkdir()
    shutil.copyfile(ZIF8, src / "only.cif")
    out = tmp_path / "out"
    proc = _run(["convert", str(src), "--to", "vasp", "--outdir", str(out), "--json"])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["n_inputs"] == 1 and "runs" in data
    assert (out / "convert_manifest.json").is_file()
    assert (out / "only" / "only.vasp").is_file()
