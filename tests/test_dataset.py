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


@pytest.fixture()
def make_runs():
    """Factory: build a small runs tree (3 ok + 1 failing) and return its root."""

    def _factory(root: Path) -> Path:
        _make_run(root, "run_a", topology="sod")
        _make_run(root, "run_b", topology="pcu")
        _make_run(root, "run_c", topology="sod")
        _make_run(root, "run_bad", copy=False)
        return root

    return _factory


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


def test_stream_and_materialised_modes_agree(tmp_path, make_runs):
    """F6: streaming must not change the outputs, only the memory profile."""
    source = make_runs(tmp_path / "runs")
    stream_dir = tmp_path / "stream"
    materialised_dir = tmp_path / "materialised"
    stream = build_dataset(source, stream_dir, label_key="topology", rdf=False)
    material = build_dataset(source, materialised_dir, label_key="topology", rdf=False,
                             stream=False)

    assert stream["mode"] == "stream" and material["mode"] == "materialised"
    assert stream["n_runs"] == material["n_runs"]
    assert stream["n_ok"] == material["n_ok"] and stream["n_failed"] == material["n_failed"]

    # `structure_copy`/`structure_file` record absolute paths, so the two outdirs
    # can never be byte-identical; normalise those prefixes and compare the rest.
    def normalise(path: Path, outdir: Path) -> str:
        text = path.read_text(encoding="utf-8-sig")
        # JSON escapes backslashes, so replace both the raw and the escaped prefix
        return text.replace(json.dumps(str(outdir))[1:-1], "<OUT>").replace(str(outdir), "<OUT>")

    assert normalise(stream_dir / "dataset.csv", stream_dir) == \
        normalise(materialised_dir / "dataset.csv", materialised_dir), "CSV differs between modes"
    assert normalise(stream_dir / "dataset.jsonl", stream_dir) == \
        normalise(materialised_dir / "dataset.jsonl", materialised_dir), "JSONL differs between modes"
    # n_ok must equal the number of data rows (CSV holds successes only)
    csv_lines = (stream_dir / "dataset.csv").read_text(encoding="utf-8-sig").splitlines()
    assert len(csv_lines) - 1 == stream["n_ok"]
    assert csv_lines[0].split(",")[:6] == ["run_id", "source", "record_id", "topology_evidence",
                                           "structure_file", "label"]


def test_streaming_holds_one_row(tmp_path, make_runs):
    """The evidence for the streaming claim: max_rows_held stays constant."""
    source = make_runs(tmp_path / "runs")
    stream = build_dataset(source, tmp_path / "s", rdf=False)
    material = build_dataset(source, tmp_path / "m", rdf=False, stream=False)
    assert stream["max_rows_held"] == 1
    assert material["max_rows_held"] == material["n_runs"] >= 2


def test_iter_manifests_is_lazy(tmp_path, make_runs):
    """iter_manifests yields without reading everything into a list."""
    import types

    from cifkit.dataset import iter_manifests

    source = make_runs(tmp_path / "runs")
    gen = iter_manifests(source)
    assert isinstance(gen, types.GeneratorType)
    first = next(gen)
    assert "run_dir" in first


def test_count_jsonl_and_iter_jsonl_stream(tmp_path, make_runs):
    from cifkit.dataset import build_dataset as build, count_jsonl, iter_jsonl

    source = make_runs(tmp_path / "runs")
    build(source, tmp_path / "ds", rdf=False)
    jsonl = tmp_path / "ds" / "dataset.jsonl"
    assert count_jsonl(jsonl) == sum(1 for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip())
    objects = list(iter_jsonl(jsonl))
    assert all("run_id" in obj for obj in objects)
