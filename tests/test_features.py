"""Structure features (ML-ready) — composition/lattice/symmetry/coordination/RDF/topology."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from cifkit.features import FEATURE_VERSION, extract_features, features_from_cif, features_many

DATA = Path(__file__).resolve().parent / "data"
ZIF8 = DATA / "zif8_cr_sod.cif"


@pytest.fixture(scope="module")
def zif8():
    return Structure.from_file(str(ZIF8))


def test_features_basic_keys_and_json(zif8):
    row = extract_features(zif8, rdf=False)
    for key in ("formula", "reduced_formula", "natoms", "n_elements", "element_counts",
                "atomic_fractions", "metal_fraction", "h_count", "a", "b", "c",
                "volume", "density_g_cm3", "spacegroup_number", "spacegroup_symbol",
                "cn_mean", "cn_by_element", "cn_histogram"):
        assert key in row, key
    assert row["feature_version"] == FEATURE_VERSION
    assert row["natoms"] == len(zif8)
    assert row["h_count"] == 60
    json.dumps(row)  # must be JSON-serialisable


def test_features_rdf_shape(zif8):
    row = extract_features(zif8, rdf=True, rdf_bins=20, rdf_max=6.0)
    rdf_keys = [k for k in row if k.startswith("rdf_") and k not in ("rdf_bins", "rdf_max", "rdf_r")]
    assert rdf_keys, "no element-pair RDF columns"
    for key in rdf_keys:
        assert len(json.loads(row[key])) == 20


def test_features_no_metal_and_bad_input():
    sio2 = Structure(Lattice.hexagonal(5.0, 5.5), ["Si", "O", "O"], [[0, 0, 0], [1/3, 2/3, 0.3], [2/3, 1/3, 0.7]])
    row = extract_features(sio2, rdf=False)
    assert row["metal_fraction"] == 0.0
    with pytest.raises(ValueError):
        extract_features(Structure(Lattice.cubic(5), [], []), rdf=False)


def test_features_topology_identify(zif8):
    row = extract_features(zif8, rdf=False, topology=True)
    assert row["topology_net"] == "sod"
    assert row["topology_evidence"] in ("verified", "metadata", "curated", "unknown")


def test_features_many_parallel_and_errors():
    rows = features_many([ZIF8, DATA / "zif8_cr_sod.cif", DATA / "no-such-file.cif"],
                         jobs=2, rdf=False)
    assert len(rows) == 3
    assert sum(1 for r in rows if r.get("error")) == 1
    ok = [r for r in rows if not r.get("error")]
    assert len(ok) == 2 and all(r["natoms"] > 0 for r in ok)


def test_features_from_cif_path_keys(zif8):
    row = features_from_cif(ZIF8, rdf=False)
    assert row["filename"] == ZIF8.name
    assert row["path"].endswith(ZIF8.name)
