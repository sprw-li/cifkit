"""Streaming rows: generator + NDJSON HTTP route (round 52, limitation J4).

Two properties matter and are both tested against real data:

* the generator stays bounded — it must not read the whole JSONL to serve a page;
* the HTTP route streams and **still enforces the policy** (a streaming endpoint that
  skipped the sandbox would be a hole).
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"


@pytest.fixture(scope="module")
def dataset_dir(tmp_path_factory):
    """A real dataset built from a handful of runs."""
    from pymatgen.core import Structure

    from cifkit.dataset import build_dataset

    base = tmp_path_factory.mktemp("stream")
    runs = base / "runs"
    source = (DATA / "terephthalic_acid_hfree.cif").read_text(encoding="utf-8")
    for index in range(7):
        run = runs / f"run{index:03d}"
        run.mkdir(parents=True)
        (run / "standardized.cif").write_text(source, encoding="utf-8")
        (run / "manifest.json").write_text(json.dumps({
            "ok": True,
            "artifacts": {"standardized.cif": str(run / "standardized.cif")},
            "source": {"source": "local", "record": {"record_id": f"local:{index}"}},
        }), encoding="utf-8")
    build_dataset(runs, base / "ds", rdf=False)
    return base / "ds"


# ------------------------------------------------------------------ the generator
def test_generator_yields_every_row(dataset_dir):
    from cifkit.api import iter_dataset_rows

    rows = list(iter_dataset_rows(dataset_dir=dataset_dir))
    assert len(rows) == 7
    assert all("run_id" in row for row in rows)


def test_dataset_rows_and_the_generator_agree(dataset_dir):
    from cifkit.api import dataset_rows, iter_dataset_rows

    paged = dataset_rows(dataset_dir=dataset_dir, offset=2, limit=3)
    lazy = list(iter_dataset_rows(dataset_dir=dataset_dir, offset=2, limit=3))
    assert [row["run_id"] for row in paged["rows"]] == [row["run_id"] for row in lazy]
    assert paged["total"] == 7
    assert paged["has_more"] is True
    tail = dataset_rows(dataset_dir=dataset_dir, offset=5, limit=10)
    assert tail["has_more"] is False


def test_generator_does_not_read_the_whole_file(dataset_dir, monkeypatch):
    """Serving a 2-row page must not walk the entire dataset."""
    from cifkit import dataset as dataset_module
    from cifkit.api import iter_dataset_rows

    consumed = {"n": 0}
    real_iter = dataset_module.iter_jsonl

    def counting_iter(path):
        for obj in real_iter(path):
            consumed["n"] += 1
            yield obj

    monkeypatch.setattr(dataset_module, "iter_jsonl", counting_iter)
    rows = list(iter_dataset_rows(dataset_dir=dataset_dir, offset=0, limit=2))
    assert len(rows) == 2
    # one extra line may be pulled to detect the end of the page; the whole file must not
    assert consumed["n"] <= 3, f"read {consumed['n']} lines for a 2-row page"
    assert consumed["n"] < 7


def test_generator_streams_one_json_object_per_line(dataset_dir):
    from cifkit.api import stream_dataset_rows_ndjson

    lines = list(stream_dataset_rows_ndjson(dataset_dir=dataset_dir, limit=3))
    assert len(lines) == 3
    for line in lines:
        assert line.endswith("\n")
        assert json.loads(line)["run_id"].startswith("run")


def test_missing_dataset_raises_not_found(tmp_path):
    from cifkit.api import NotFound, iter_dataset_rows

    with pytest.raises(NotFound):
        list(iter_dataset_rows(dataset_dir=tmp_path / "nope"))


def test_invalid_paging_is_rejected(dataset_dir):
    from cifkit.api import InvalidRequest, iter_dataset_rows

    with pytest.raises(InvalidRequest):
        list(iter_dataset_rows(dataset_dir=dataset_dir, offset=-1))
    with pytest.raises(InvalidRequest):
        list(iter_dataset_rows(dataset_dir=dataset_dir, limit=0))


# ----------------------------------------------------------------- the HTTP route
@pytest.fixture()
def live_service(dataset_dir):
    from cifkit.platform import Policy
    from cifkit.service import serve

    policy = Policy(allow_network=False, read_roots=(str(dataset_dir),))
    server, thread = serve(host="127.0.0.1", port=0, background=True, policy=policy)
    port = server.server_address[1]
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=10)


def test_stream_route_returns_chunked_ndjson(live_service, dataset_dir):
    url = f"{live_service}/stream/dataset_rows?dir={dataset_dir}&limit=4"
    request = urllib.request.Request(url, headers={"Accept": "application/x-ndjson"})
    with urllib.request.urlopen(request, timeout=30) as response:
        assert response.status == 200
        assert "ndjson" in response.headers.get("Content-Type", "")
        body = response.read().decode("utf-8")
    lines = [line for line in body.splitlines() if line.strip()]
    assert len(lines) == 4
    assert all(json.loads(line)["run_id"].startswith("run") for line in lines)


def test_stream_route_honours_offset_and_limit(live_service, dataset_dir):
    first = urllib.request.urlopen(
        f"{live_service}/stream/dataset_rows?dir={dataset_dir}&limit=2", timeout=30)
    page1 = [json.loads(line) for line in first.read().decode().splitlines() if line.strip()]
    second = urllib.request.urlopen(
        f"{live_service}/stream/dataset_rows?dir={dataset_dir}&offset=2&limit=2", timeout=30)
    page2 = [json.loads(line) for line in second.read().decode().splitlines() if line.strip()]
    assert [row["run_id"] for row in page1] == ["run000", "run001"]
    assert [row["run_id"] for row in page2] == ["run002", "run003"]


def test_stream_route_requires_a_directory(live_service):
    try:
        urllib.request.urlopen(f"{live_service}/stream/dataset_rows", timeout=30)
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
        payload = json.loads(exc.read().decode())
        assert payload["error"]["code"] == "invalid-request"
    else:  # pragma: no cover
        pytest.fail("missing dir must be rejected")


def test_stream_route_respects_the_path_sandbox(live_service, tmp_path):
    """A streaming route must not be a sandbox bypass."""
    outside = tmp_path.parent / "outside_dataset"
    outside.mkdir(exist_ok=True)
    (outside / "dataset.jsonl").write_text('{"run_id": "leak"}\n', encoding="utf-8")
    try:
        urllib.request.urlopen(
            f"{live_service}/stream/dataset_rows?dir={outside}", timeout=30)
    except urllib.error.HTTPError as exc:
        assert exc.code == 403, exc.code
        payload = json.loads(exc.read().decode())
        assert payload["error"]["code"] in ("forbidden-path", "forbidden")
    else:  # pragma: no cover
        pytest.fail("a path outside the policy roots must be rejected")
