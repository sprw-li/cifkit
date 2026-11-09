"""Pagination (J4) and streaming dataset (F6) behaviour at the API/service layer."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from cifkit import api, contract
from cifkit.service import handle

DATA = Path(__file__).resolve().parent / "data"
ZIF8 = DATA / "zif8_cr_sod.cif"


@pytest.fixture()
def built_dataset(tmp_path):
    runs = tmp_path / "runs"
    for index in range(5):
        run = runs / f"run{index}"
        run.mkdir(parents=True)
        shutil.copyfile(ZIF8, run / "standardized.cif")
        (run / "manifest.json").write_text(json.dumps({
            "ok": True,
            "artifacts": {"standardized.cif": str(run / "standardized.cif")},
            "source": {"source": "local", "record": {"record_id": f"local:{index}",
                                                     "topology": "sod",
                                                     "topology_evidence": "verified"}},
        }), encoding="utf-8")
    summary = api.dataset(runs_dir=runs, outdir=tmp_path / "ds", label_key="topology", rdf=False)
    return tmp_path / "ds", summary


def test_dataset_defaults_to_streaming(built_dataset):
    _ds, summary = built_dataset
    assert summary["mode"] == "stream"
    assert summary["max_rows_held"] == 1
    assert summary["n_ok"] == 5


def test_dataset_rows_pages_without_loading_everything(built_dataset):
    ds, _summary = built_dataset
    first = api.dataset_rows(dataset_dir=ds, offset=0, limit=2)
    second = api.dataset_rows(dataset_dir=ds, offset=2, limit=2)
    third = api.dataset_rows(dataset_dir=ds, offset=4, limit=2)
    assert first["total"] == 5 and first["has_more"] is True
    assert [r["run_id"] for r in first["rows"]] == ["run0", "run1"]
    assert [r["run_id"] for r in second["rows"]] == ["run2", "run3"]
    assert [r["run_id"] for r in third["rows"]] == ["run4"]
    assert third["has_more"] is False
    # pages must not overlap and must cover everything exactly once
    seen = [r["run_id"] for page in (first, second, third) for r in page["rows"]]
    assert seen == ["run0", "run1", "run2", "run3", "run4"]


def test_dataset_rows_column_projection_and_features(built_dataset):
    ds, _summary = built_dataset
    slim = api.dataset_rows(dataset_dir=ds, limit=2, columns=["label"])
    assert all(set(row) <= {"run_id", "label"} for row in slim["rows"])
    full = api.dataset_rows(dataset_dir=ds, limit=1, with_features=True)
    assert full["rows"][0]["natoms"] == 138
    with_manifest = api.dataset_rows(dataset_dir=ds, limit=1, include_manifest=True)
    assert with_manifest["rows"][0]["manifest"].endswith("manifest.json")


def test_dataset_rows_errors(built_dataset):
    ds, _summary = built_dataset
    with pytest.raises(api.InvalidRequest):
        api.dataset_rows(dataset_dir=ds, offset=-1)
    with pytest.raises(api.InvalidRequest):
        api.dataset_rows(dataset_dir=ds, limit=0)
    with pytest.raises(api.NotFound):
        api.dataset_rows(dataset_dir=ds / "nope")
    # a direct path to the jsonl file also works
    assert api.dataset_rows(dataset_dir=ds / "dataset.jsonl", limit=1)["rows"]


def test_features_many_pagination(built_dataset):
    paths = [ZIF8] * 4
    page = api.features_many(paths, jobs=2, rdf=False, offset=1, limit=2)
    assert page["total"] == 4 and page["n_inputs"] == 4
    assert len(page["rows"]) == 2 and page["has_more"] is True
    last = api.features_many(paths, jobs=2, rdf=False, offset=3, limit=2)
    assert len(last["rows"]) == 1 and last["has_more"] is False
    with pytest.raises(api.InvalidRequest):
        api.features_many(paths, offset=-1)
    with pytest.raises(api.InvalidRequest):
        api.features_many(paths, limit=0)


def test_dataset_rows_service_op(built_dataset):
    ds, _summary = built_dataset
    response = handle({"op": "dataset_rows", "params": {"dataset_dir": str(ds), "limit": 2}})
    assert response["ok"] is True and response["data"]["total"] == 5
    assert contract.validate_response(response) == []
    bad = handle({"op": "dataset_rows", "params": {"dataset_dir": str(ds), "limit": 0}})
    assert bad["ok"] is False and bad["error"]["code"] == "invalid-request"
    assert any("limit" in v for v in bad["error"]["detail"]["violations"])


def test_dataset_op_accepts_stream_flag(built_dataset, tmp_path):
    runs = tmp_path / "runs"
    summary = api.dataset(runs_dir=runs, outdir=tmp_path / "ds2", rdf=False, stream=False)
    assert summary["mode"] == "materialised"
    # both modes must still agree on the numbers
    streamed = api.dataset(runs_dir=runs, outdir=tmp_path / "ds3", rdf=False, stream=True)
    assert streamed["n_ok"] == summary["n_ok"] == 5
    assert streamed["n_failed"] == summary["n_failed"] == 0


def test_platform_sandboxes_dataset_dir(tmp_path):
    from cifkit.platform import ForbiddenPath, Policy, check_params

    policy = Policy(read_roots=[str(tmp_path / "allowed")])
    (tmp_path / "allowed").mkdir()
    with pytest.raises(ForbiddenPath):
        check_params("dataset_rows", {"dataset_dir": str(tmp_path / "elsewhere")}, policy)
    ok = check_params("dataset_rows", {"dataset_dir": str(tmp_path / "allowed")}, policy)
    assert Path(ok["dataset_dir"]).is_absolute()
