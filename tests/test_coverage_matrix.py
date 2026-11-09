"""Bundled topology references + dataset coverage matrix (round 23)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NETS = ROOT / "cifkit" / "data" / "nets"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def coverage():
    return _load("coverage_matrix_module", ROOT / "scripts" / "coverage_matrix.py")


def test_topology_counts_is_pure_and_counts_both_columns(coverage):
    entries = {
        "a": {"topology_allnodes": "pcu", "topology_singlenodes": "pcu"},
        "b": {"topology_allnodes": "sod", "topology_singlenodes": "sod"},
        "c": {"topology_allnodes": None, "topology_singlenodes": "pcu"},
        "d": {},
    }
    counts = coverage.topology_counts(entries)
    assert counts["allnodes"]["pcu"] == 1
    assert counts["allnodes"]["-"] == 2          # None and missing both normalise to "-"
    assert counts["singlenodes"]["pcu"] == 2


def test_every_bundled_reference_net_verifies_against_its_own_reference():
    """The bundled references must be self-consistent (json signature vs cif)."""
    from pymatgen.core import Structure

    from cifkit.topology import verify

    references = sorted(NETS.glob("*-reference.cif"))
    assert references, "no bundled topology references found"
    for reference in references:
        net = reference.stem.replace("-reference", "")
        structure = Structure.from_file(str(reference))
        result = verify(structure, net)
        assert result.get("ok") is True, f"{net}: {result}"


def test_every_bundled_net_has_metadata(coverage):
    for net in coverage.bundled_nets(NETS):
        payload = json.loads((NETS / f"{net}.json").read_text(encoding="utf-8"))
        assert payload.get("cif_sha256"), f"{net}.json has no cif_sha256"
        assert (NETS / f"{net}-reference.cif").is_file()


def test_interesting_list_covers_all_bundled_nets(coverage):
    bundled = set(coverage.bundled_nets(NETS))
    assert bundled <= set(coverage.INTERESTING), (
        f"bundled nets missing from the report list: {bundled - set(coverage.INTERESTING)}")
