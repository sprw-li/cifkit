"""Dataset builder: runs manifests → dataset.csv/jsonl + copied structures + manifest."""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from cifkit.dataset import build_dataset, load_runs

DATA = Path(__file__).resolve().parent / "data"
ZIF8 = DATA / "zif8_cr_sod.cif"


def _make_run(root: Path, name: str, *, topology: str = "sod", copy: bool = True) -> Path:
    run = root / name
    run.mkdir(parents=True)
    if copy:
        shutil.copyfile(ZIF8, run / "standardized.cif")
    manifest = {
        "ok": True,
        "spec": {"query": name, "outdir": str(run)},
        "artifacts": ({"standardized.cif": str(run / "standardized.cif")} if copy else {}),
        "source": {"source": "core-mof",
                   "record": {"record_id": f"core-mof:{name}", "topology": topology,
                              "topology_evidence": "verified"}},
        "steps": [],
    }
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run


def test_load_runs_finds_manifests(tmp_path):
    _make_run(tmp_path, "a")
    _make_run(tmp_path, "b", copy=False)
    runs = load_runs(tmp_path)
    assert len(runs) == 2


def test_dataset_builds_csv_jsonl_and_structures(tmp_path):
    runs = tmp_path / "runs"
    _make_run(runs, "run_a")
    _make_run(runs, "run_b", topology="pcu")
    _make_run(runs, "run_bad", copy=False)  # no structure -> recorded as failure
    out = tmp_path / "dataset"
    summary = build_dataset(runs, out, label_key="topology", rdf=False)
    assert summary["n_runs"] == 3
    assert summary["n_ok"] == 2
    assert summary["n_failed"] == 1
    assert summary["csv_sha256"]
    rows = list(csv.DictReader((out / "dataset.csv").open(encoding="utf-8-sig")))
    assert len(rows) == 2
    labels = {row["label"] for row in rows}
    assert labels == {"sod", "pcu"}
    assert all(row["formula"] and int(row["natoms"]) > 0 for row in rows)
    assert len(list((out / "structures").glob("*.cif"))) == 2
    assert (out / "dataset.jsonl").is_file()
    manifest = json.loads((out / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["n_failed"] == 1 and manifest["errors"]


def test_dataset_without_features(tmp_path):
    runs = tmp_path / "runs"
    _make_run(runs, "run_a")
    out = tmp_path / "ds"
    summary = build_dataset(runs, out, features=False, copy_structures=False)
    assert summary["n_ok"] == 1
    rows = list(csv.DictReader((out / "dataset.csv").open(encoding="utf-8-sig")))
    assert rows and rows[0]["run_id"] == "run_a"


def test_dataset_from_library_dir(tmp_path):
    lib = tmp_path / "library"
    run = lib / "run_lib"
    run.mkdir(parents=True)
    shutil.copyfile(ZIF8, run / "standardized.cif")
    (run / "manifest.json").write_text(json.dumps({
        "ok": True,
        "artifacts": {"standardized.cif": str(run / "standardized.cif")},
        "source": {"source": "local", "record": {"record_id": "local:test"}},
    }), encoding="utf-8")
    (lib / "index.jsonl").write_text(json.dumps({"run_id": "run_lib"}) + "\n", encoding="utf-8")
    out = tmp_path / "ds_lib"
    summary = build_dataset(lib, out, label_key="source", rdf=False)
    assert summary["n_ok"] == 1
    rows = list(csv.DictReader((out / "dataset.csv").open(encoding="utf-8-sig")))
    assert rows and rows[0]["source"] == "local"
