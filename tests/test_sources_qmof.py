"""QMOF local-mirror adapter: search/fetch/provenance and honest missing-data errors."""
from __future__ import annotations

import csv
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from cifkit.sources import available_sources, get_source, source_status
from cifkit.sources.qmof import QMOFSource, qmof_available
from cifkit.types import SourceQuery

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "data" / "zif8_cr_sod.cif"


def _make_mirror(tmp_path: Path) -> Path:
    root = tmp_path / "qmof"
    (root / "structures").mkdir(parents=True)
    shutil.copyfile(FIXTURE, root / "structures" / "ZIF8_TEST.cif")
    with (root / "qmof.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["name", "formula", "spacegroup"])
        writer.writerow(["ZIF8_TEST", "Zn12 C96 N48", "I-43m"])
    return root


def test_qmof_registered_in_sources():
    assert "qmof" in available_sources()
    rows = {row["name"]: row for row in source_status()}
    assert rows["qmof"]["status"].startswith("local mirror")


def test_qmof_missing_mirror_raises_actionable_error(tmp_path, monkeypatch):
    monkeypatch.setenv("CIFKIT_QMOF_DIR", str(tmp_path / "nope"))
    with pytest.raises(FileNotFoundError) as excinfo:
        QMOFSource().search(SourceQuery(structure_name="ZIF8"))
    message = str(excinfo.value)
    assert "CIFKIT_QMOF_DIR" in message
    assert "figshare" in message or "10.6084" in message


def test_qmof_search_and_fetch_from_dir_mirror(tmp_path, monkeypatch):
    root = _make_mirror(tmp_path)
    monkeypatch.setenv("CIFKIT_QMOF_DIR", str(root))
    assert qmof_available() is True
    src = get_source("qmof")
    hits = src.search(SourceQuery(structure_name="ZIF8_TEST"))
    assert len(hits) == 1
    record = hits[0]
    assert record.record_id == "qmof:ZIF8_TEST"
    assert record.source == "qmof"
    assert record.topology_evidence == "unknown"  # no RCSR topology column
    fetched = src.fetch(record)
    assert fetched.structure.composition.reduced_formula == "Zn12C96N48" or len(fetched.structure) > 50
    assert fetched.provenance["source"] == "qmof"
    assert fetched.provenance["sha256"]
    assert fetched.record.natoms == len(fetched.structure)


def test_qmof_zip_mirror_without_csv(tmp_path, monkeypatch):
    root = tmp_path / "qmofzip"
    root.mkdir()
    with zipfile.ZipFile(root / "qmof_cifs.zip", "w") as zf:
        zf.write(FIXTURE, "ABAVIJ_clean.cif")
    monkeypatch.setenv("CIFKIT_QMOF_DIR", str(root))
    src = QMOFSource()
    hits = src.search(SourceQuery(structure_name="ABAVIJ"))
    assert hits and hits[0].record_id == "qmof:ABAVIJ_clean"
    fetched = src.fetch(hits[0])
    assert len(fetched.structure) > 50
    assert fetched.provenance["cif_name"].endswith(".cif")


@pytest.mark.skipif(
    not qmof_available(), reason="QMOF mirror not bootstrapped (run scripts/bootstrap_qmof.py)"
)
def test_qmof_real_mirror_search_and_fetch():
    """Real QMOF data (downloaded from the figshare article zip) must parse and fetch."""
    src = QMOFSource()
    hits = src.search(SourceQuery(limit=3))
    assert hits, "QMOF mirror exists but search returned nothing"
    fetched = src.fetch(hits[0])
    assert len(fetched.structure) > 0
    assert fetched.provenance["source"] == "qmof"
    assert fetched.provenance["sha256"]
    assert fetched.record.natoms == len(fetched.structure)
