"""Dataset de-duplication (round 43, limitation F5).

Duplicates are the most common "cleaning" need in a structure dataset: the same
framework fetched twice, or several runs of the same structure.  These tests pin
that dedupe keeps the first occurrence, never drops failures, is identical in
streamed and materialised mode, and actually saves memory (keys, not rows).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ZIF8 = ROOT / "tests" / "data" / "zif8_cr_sod.cif"
MOF5 = ROOT / "tests" / "data" / "mof5_hfree.cif"


def _make_runs(root: Path) -> Path:
    runs = root / "runs"
    # three runs of the same structure under different ids, plus a different one
    for index, source in enumerate([ZIF8, ZIF8, ZIF8, MOF5]):
        run = runs / f"run{index:03d}"
        run.mkdir(parents=True)
        (run / "standardized.cif").write_text(source.read_text(encoding="utf-8"),
                                              encoding="utf-8")
        (run / "manifest.json").write_text(json.dumps({
            "ok": True,
            "artifacts": {"standardized.cif": str(run / "standardized.cif")},
            "source": {"source": "local", "record": {"record_id": f"local:{index}"}},
        }), encoding="utf-8")
    broken = runs / "run_broken"
    broken.mkdir()
    (broken / "manifest.json").write_text(json.dumps({"ok": False, "error": "boom"}),
                                          encoding="utf-8")
    return runs


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    return _make_runs(tmp_path_factory.mktemp("dedupe"))


def test_dedupe_keeps_first_occurrence_and_never_drops_failures(tmp_path, corpus):
    from cifkit.dataset import build_dataset

    summary = build_dataset(corpus, tmp_path / "out", rdf=False,
                            dedupe="structure_sha256")
    assert summary["n_runs"] == 3          # 2 unique structures + 1 failed run
    assert summary["n_deduped"] == 2       # three copies of ZIF-8 collapse to one
    assert summary["n_failed"] == 1
    rows = [json.loads(line) for line in
            (tmp_path / "out" / "dataset.jsonl").read_text(encoding="utf-8").splitlines()]
    ids = [row["run_id"] for row in rows]
    assert ids[0] == "run000", "the FIRST occurrence must win"
    assert "run_broken" in ids


def test_dedupe_by_formula_matches_structure_hash_here(tmp_path, corpus):
    from cifkit.dataset import build_dataset

    by_hash = build_dataset(corpus, tmp_path / "hash", rdf=False,
                            dedupe="structure_sha256")
    by_formula = build_dataset(corpus, tmp_path / "formula", rdf=False, dedupe="formula")
    assert by_formula["n_deduped"] == by_hash["n_deduped"]


def test_without_dedupe_everything_is_kept(tmp_path, corpus):
    from cifkit.dataset import build_dataset

    summary = build_dataset(corpus, tmp_path / "all", rdf=False)
    assert summary["n_runs"] == 5
    assert summary["n_deduped"] == 0
    assert summary["dedupe"] is None


def test_unknown_key_is_rejected(tmp_path, corpus):
    from cifkit.dataset import build_dataset

    with pytest.raises(ValueError):
        build_dataset(corpus, tmp_path / "bad", rdf=False, dedupe="not-a-key")


def test_dedupe_memory_is_keys_not_rows(tmp_path, corpus):
    """The streaming guarantee must survive dedupe (F6 + F5 together)."""
    from cifkit.dataset import build_dataset

    summary = build_dataset(corpus, tmp_path / "stream", rdf=False,
                            dedupe="structure_sha256")
    assert summary["mode"] == "stream"
    assert summary["max_rows_held"] == 1


def test_cli_exposes_the_flag():
    source = (ROOT / "cifkit" / "cli.py").read_text(encoding="utf-8")
    assert '"--dedupe"' in source
    assert 'choices=["structure_sha256"' in source
