"""Dataset parallel `--jobs` (round 36, limitation F7).

The pool must change *speed* only — never the dataset itself.  These tests pin:

* ``jobs=1`` and ``jobs=4`` produce byte-identical JSONL/CSV (order preserved);
* streaming still holds (``max_rows_held`` stays 1);
* a failing run still produces an error row in both modes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "data" / "zif8_cr_sod.cif"


def _make_runs(root: Path, count: int) -> Path:
    runs = root / "runs"
    sample = FIXTURE.read_text(encoding="utf-8")
    for index in range(count):
        run = runs / f"run{index:03d}"
        run.mkdir(parents=True)
        (run / "standardized.cif").write_text(sample, encoding="utf-8")
        (run / "manifest.json").write_text(json.dumps({
            "ok": True,
            "artifacts": {"standardized.cif": str(run / "standardized.cif")},
            "source": {"source": "local", "record": {"record_id": f"local:{index}"}},
        }), encoding="utf-8")
    return runs


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    return _make_runs(tmp_path_factory.mktemp("ds"), 6)


def test_parallel_matches_sequential(tmp_path, corpus):
    from cifkit.dataset import build_dataset

    sequential = build_dataset(corpus, tmp_path / "seq", rdf=False, jobs=1)
    parallel = build_dataset(corpus, tmp_path / "par", rdf=False, jobs=4)
    assert sequential["n_runs"] == parallel["n_runs"] == 6

    outs = (str(tmp_path / "seq"), str(tmp_path / "par"))

    def norm(value):
        """The outdir is part of structure_file/structure_copy by design."""
        if isinstance(value, dict):
            return {key: norm(item) for key, item in value.items()}
        if isinstance(value, list):
            return [norm(item) for item in value]
        if isinstance(value, str):
            for out in outs:
                value = value.replace(out, "<OUT>")
            return value
        return value

    def rows(path: Path) -> list:
        return [norm(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()]

    seq_rows = rows(tmp_path / "seq" / "dataset.jsonl")
    par_rows = rows(tmp_path / "par" / "dataset.jsonl")
    assert len(seq_rows) == len(par_rows) == 6
    assert seq_rows == par_rows, "order/contents must be identical with a thread pool"

    def csv_text(path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        for out in outs:
            text = text.replace(out, "<OUT>")
        return text

    assert csv_text(tmp_path / "seq" / "dataset.csv") == csv_text(tmp_path / "par" / "dataset.csv")


def test_streaming_bound_holds_with_parallel(tmp_path, corpus):
    from cifkit.dataset import build_dataset

    summary = build_dataset(corpus, tmp_path / "stream", rdf=False, jobs=4)
    assert summary["mode"] == "stream"
    assert summary["max_rows_held"] == 1, "a bounded window must not materialise rows"


def test_failing_run_is_reported_in_both_modes(tmp_path, corpus):
    from cifkit.dataset import build_dataset

    broken = corpus / "run_broken"
    broken.mkdir()
    (broken / "manifest.json").write_text(json.dumps({"ok": False, "error": "boom"}),
                                          encoding="utf-8")
    sequential = build_dataset(corpus, tmp_path / "s2", rdf=False, jobs=1)
    parallel = build_dataset(corpus, tmp_path / "p2", rdf=False, jobs=4)
    assert parallel["n_runs"] == sequential["n_runs"] == 7
    assert parallel["n_failed"] == sequential["n_failed"] == 1


def test_jobs_of_one_is_the_default():
    import inspect

    from cifkit.dataset import build_dataset, iter_runs

    assert inspect.signature(build_dataset).parameters["jobs"].default == 1
    assert inspect.signature(iter_runs).parameters["jobs"].default == 1
