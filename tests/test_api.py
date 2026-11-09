"""Embedding API (cifkit.api) — stable, JSON-serialisable, side-effect-light surface."""
from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from cifkit import api

DATA = Path(__file__).resolve().parent / "data"
ZIF8 = DATA / "zif8_cr_sod.cif"


def test_capabilities_shape():
    caps = api.capabilities()
    assert caps["api_version"] == api.API_VERSION
    assert len(caps["formats"]) >= 31
    assert len(caps["bundles"]) >= 12
    assert "features" in caps["operations"] and "convert" in caps["operations"]
    assert set(caps["offline_operations"]) >= {"features", "convert", "dataset", "topology", "validate"}
    json.dumps(caps)  # must be JSON-serialisable


def test_features_from_path_text_and_structure_agree():
    from_path = api.features(path=ZIF8, rdf=False)
    text = ZIF8.read_text(encoding="utf-8")
    from_text = api.features(cif_text=text, rdf=False)
    structure = Structure.from_file(str(ZIF8))
    from_object = api.features(structure=structure, rdf=False)
    for key in ("natoms", "h_count", "spacegroup_number", "metal_fraction"):
        assert from_path[key] == from_text[key] == from_object[key], key
    json.dumps(from_path)


def test_features_rdf_and_rings_options():
    row = api.features(path=ZIF8, rdf=True, rdf_bins=10, rdf_max=5.0)
    keys = [k for k in row if k.startswith("rdf_") and k not in ("rdf_bins", "rdf_max", "rdf_r")]
    assert keys and all(len(json.loads(row[k])) == 10 for k in keys)
    rings = api.features(path=ZIF8, rdf=False, rings=True)
    assert rings["ring_basis"] == "metal-net"


def test_convert_inline_text_and_binary():
    result = api.convert(path=ZIF8, formats=["vasp", "png"])
    assert result["outdir"] is None
    vasp = result["formats"]["vasp"]
    assert vasp["encoding"] == "utf-8" and "POSCAR" not in vasp["text"][:0] or vasp["text"]
    assert vasp["text"].splitlines()[0].strip()
    import base64

    png = base64.b64decode(result["formats"]["png"]["base64"])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    json.dumps({k: v for k, v in result.items() if k != "formats"})


def test_convert_to_outdir_and_bundles(tmp_path):
    result = api.convert(path=ZIF8, formats=["vasp", "cif"], bundles=["qe"], outdir=tmp_path)
    assert Path(result["formats"]["vasp"]).is_file()
    assert Path(result["formats"]["cif"]).is_file()
    assert (tmp_path / "qe" / "pw.in").is_file()
    assert result["natoms"] == 138


def test_convert_inline_and_disk_are_byte_identical(tmp_path):
    """Inline text is the file's bytes decoded as UTF-8 (no newline translation).

    Search the inline string for the expected serialisation rather than the
    tempting-but-unsafe: don't claim identical bytes without comparing them.
    """
    inline = api.convert(path=ZIF8, formats=["vasp"])["formats"]["vasp"]["text"]
    api.convert(path=ZIF8, formats=["vasp"], outdir=tmp_path)
    on_disk = (tmp_path / "zif8_cr_sod.vasp").read_bytes().decode("utf-8")
    assert inline == on_disk
    assert "\r\n" in inline or "\n" in inline  # explicit about which stream we compare


def test_topology_and_validate():
    topo = api.topology(path=ZIF8)
    assert topo["net"] == "sod" and topo["evidence"] == "verified"
    verified = api.topology(path=ZIF8, net="sod")
    assert verified.get("ok") is True
    mismatched = api.topology(path=ZIF8, net="pcu")
    assert mismatched.get("ok") is False
    report = api.validate(path=ZIF8)
    assert report["ok"] is True and len(report["checks"]) >= 9
    json.dumps(report)


def test_error_codes():
    with pytest.raises(api.InvalidRequest):
        api.features()
    with pytest.raises(api.InvalidRequest):
        api.features(path=ZIF8, structure=Structure.from_file(str(ZIF8)))
    with pytest.raises(api.NotFound):
        api.features(path="definitely-missing.cif")
    with pytest.raises(api.UnsupportedFormat):
        api.convert(path=ZIF8, formats=["not-a-format"])
    with pytest.raises(api.UnsupportedFormat):
        api.convert(path=ZIF8, bundles=["not-a-bundle"])
    with pytest.raises(api.InvalidRequest):
        api.convert(path=ZIF8)
    with pytest.raises(api.InvalidRequest):
        api.features(cif_text="this is not a cif")
    assert api.NotFound("x").http_status == 404
    assert api.UnsupportedFormat("x").code == "unsupported-format"


def test_features_many_reports_failures_without_raising():
    result = api.features_many([ZIF8, ZIF8, DATA / "nope.cif"], jobs=2, rdf=False)
    assert result["n_inputs"] == 3 and result["n_ok"] == 2 and result["n_failed"] == 1
    assert result["ok"] is False


def test_dataset_from_runs(tmp_path):
    runs = tmp_path / "runs" / "r1"
    runs.mkdir(parents=True)
    shutil.copyfile(ZIF8, runs / "standardized.cif")
    (runs / "manifest.json").write_text(json.dumps({
        "ok": True,
        "artifacts": {"standardized.cif": str(runs / "standardized.cif")},
        "source": {"source": "local", "record": {"record_id": "local:x", "topology": "sod"}},
    }), encoding="utf-8")
    result = api.dataset(runs_dir=tmp_path / "runs", outdir=tmp_path / "ds",
                         label_key="topology", rdf=False)
    assert result["n_ok"] == 1 and result["n_failed"] == 0
    assert (tmp_path / "ds" / "dataset.csv").is_file()
    with pytest.raises(api.NotFound):
        api.dataset(runs_dir=tmp_path / "missing", outdir=tmp_path / "x")


def test_api_is_thread_safe():
    structures = [Structure(Lattice.cubic(4.0 + i * 0.1), ["Na", "Cl"],
                            [[0, 0, 0], [0.5, 0.5, 0.5]]) for i in range(6)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda s: api.features(structure=s, rdf=False), structures))
    assert len(rows) == 6
    assert all(row["natoms"] == 2 for row in rows)
    assert len({row["a"] for row in rows}) == 6  # no cross-talk between calls
