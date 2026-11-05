"""New database adapters: Materials Project (mocked; needs key) and AFLOW (live+mocked)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from cifkit.sources.aflow import (
    AFLOWSource,
    _formula_query,
    _pick_cif_name,
    aflow_available,
    normalize_aurl,
)
from cifkit.sources import materials_project as mp_mod
from cifkit.sources.materials_project import MaterialsProjectSource
from cifkit.types import SourceQuery

DATA = Path(__file__).resolve().parent / "data"


# ---------------------------------------------------------------------------
# Materials Project
# ---------------------------------------------------------------------------
@pytest.fixture()
def no_mp_key(monkeypatch):
    for env in mp_mod.KEY_ENVS:
        monkeypatch.delenv(env, raising=False)


def test_mp_requires_api_key(no_mp_key):
    with pytest.raises(ValueError) as exc:
        MaterialsProjectSource().search(SourceQuery(structure_id="mp-149"))
    assert "MP_API_KEY" in str(exc.value)
    assert "materialsproject.org/api" in str(exc.value)


def _fake_mp_row() -> dict:
    structure = Structure(Lattice.cubic(5.64), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    return {
        "material_id": "mp-22862",
        "formula_pretty": "NaCl",
        "chemsys": "Cl-Na",
        "spacegroup": {"symbol": "Fm-3m", "number": 225},
        "nsites": 2,
        "is_stable": True,
        "structure": structure.as_dict(),
    }


def test_mp_search_and_fetch_mocked(monkeypatch, tmp_path):
    monkeypatch.setenv("MP_API_KEY", "fake-key-for-test")
    monkeypatch.setenv("CIFKIT_CACHE", str(tmp_path / "cache"))
    calls: list[tuple[str, dict]] = []
    row = _fake_mp_row()

    def fake_request(path, params, key):
        calls.append((path, dict(params)))
        assert key == "fake-key-for-test"
        return {"data": [row]}

    monkeypatch.setattr(mp_mod, "_REQUEST_JSON", fake_request)
    src = MaterialsProjectSource()
    hits = src.search(SourceQuery(structure_id="mp-22862"))
    assert len(hits) == 1
    rec = hits[0]
    assert rec.record_id == "mp:mp-22862"
    assert rec.formula == "NaCl"
    assert rec.topology_evidence == "unknown"  # MP has no RCSR labels
    assert rec.extra["mp_url"].endswith("mp-22862")

    fetched = src.fetch(rec)
    assert len(fetched.structure) == 2
    assert fetched.record.h_count == 0
    assert Path(fetched.provenance["cif_path"]).is_file()
    assert fetched.provenance["cif_generated"] is True
    assert fetched.provenance["structure_json_sha256"]
    assert fetched.provenance["sha256"] == fetched.provenance["cif_sha256"]
    assert calls and calls[0][0] == "/materials/summary/"


def test_mp_rejects_bad_id(monkeypatch):
    monkeypatch.setenv("MP_API_KEY", "fake")
    with pytest.raises(ValueError):
        MaterialsProjectSource().search(SourceQuery(structure_id="fe2o3"))


def test_mp_topology_query_returns_empty(monkeypatch):
    monkeypatch.setenv("MP_API_KEY", "fake")
    assert MaterialsProjectSource().search(SourceQuery(topology="sod")) == []


# ---------------------------------------------------------------------------
# AFLOW
# ---------------------------------------------------------------------------
def test_normalize_aurl_variants():
    assert normalize_aurl("aflowlib.duke.edu:AFLOWDATA/LIB1_WEB/Zn:PAW_PBE:06Sep2000/A9") == (
        "https://aflowlib.duke.edu/AFLOWDATA/LIB1_WEB/Zn:PAW_PBE:06Sep2000/A9"
    )
    assert normalize_aurl("https://aflowlib.duke.edu/AFLOWDATA/X/Y").startswith("https://")
    with pytest.raises(ValueError):
        normalize_aurl("aflow:00b8960c80015660")


def test_aflow_formula_query():
    assert _formula_query("ZnO") == "species(O,Zn),nspecies(2)"
    assert _formula_query("GaN") == "species(Ga,N),nspecies(2)"
    assert _formula_query("ZIF-8") is None  # not a chemical formula


def test_aflow_pick_cif_prefers_primary():
    aurl = "https://aflowlib.duke.edu/AFLOWDATA/LIB1_WEB/Zn:PAW_PBE:06Sep2000/A9"
    files = [
        "Zn:PAW_PBE:06Sep2000.A9_sprim.cif",
        "Zn:PAW_PBE:06Sep2000.A9.cif",
        "Zn:PAW_PBE:06Sep2000.A9_sconv.cif",
        "CONTCAR.relax",
    ]
    assert _pick_cif_name(files, aurl) == "Zn:PAW_PBE:06Sep2000.A9.cif"


TINY_CIF = """data_test
_cell_length_a 4.0
_cell_length_b 4.0
_cell_length_c 4.0
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_chemical_formula_sum 'Zn1'
_symmetry_space_group_name_H-M 'P 1'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Zn1 Zn 0.0 0.0 0.0
"""


def test_aflow_fetch_mocked(monkeypatch, tmp_path):
    monkeypatch.setenv("CIFKIT_CACHE", str(tmp_path / "cache"))
    base = "https://aflowlib.duke.edu/AFLOWDATA/LIB1_WEB/Zn:PAW_PBE:06Sep2000/A9"
    files = ["Zn:PAW_PBE:06Sep2000.A9.cif", "CONTCAR.relax"]

    def fake_get(url: str) -> bytes:
        if url.endswith("/?files"):
            assert url == base + "/?files"
            return json.dumps(files).encode()
        if url == base + "/" + "Zn%3APAW_PBE%3A06Sep2000.A9.cif":
            return TINY_CIF.encode()
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr("cifkit.sources.aflow._REQUEST_TEXT", fake_get)
    src = AFLOWSource()
    hits = src.search(SourceQuery(structure_id="aflowlib.duke.edu:AFLOWDATA/LIB1_WEB/Zn:PAW_PBE:06Sep2000/A9"))
    assert len(hits) == 1
    fetched = src.fetch(hits[0])
    assert len(fetched.structure) == 1
    assert fetched.structure.composition.reduced_formula == "Zn"
    assert Path(fetched.provenance["cif_path"]).is_file()
    assert fetched.provenance["cif_file"] == "Zn:PAW_PBE:06Sep2000.A9.cif"
    assert fetched.provenance["license"]


def test_aflow_topology_query_returns_empty():
    assert AFLOWSource().search(SourceQuery(topology="sod")) == []


@pytest.mark.skipif(not aflow_available(), reason="AFLOW 不可达（离线环境）")
def test_aflow_live_search_and_fetch(tmp_path, monkeypatch):
    monkeypatch.setenv("CIFKIT_CACHE", str(tmp_path / "cache"))
    src = AFLOWSource()
    hits = src.search(SourceQuery(structure_name="ZnO", limit=2))
    assert hits, "AFLOW ZnO 检索应至少命中一条"
    assert hits[0].record_id.startswith("aflow:")
    fetched = src.fetch(hits[0])
    assert len(fetched.structure) > 0
    assert fetched.provenance["aurl"].startswith("https://aflowlib.duke.edu/")
    assert Path(fetched.provenance["cif_path"]).is_file()

# ---------------------------------------------------------------------------
# auto source selection (formula -> aflow, MOF name -> core-mof)
# ---------------------------------------------------------------------------
def test_pick_source_formula_vs_mof_name():
    from cifkit.sources import pick_source
    from cifkit.types import TaskSpec

    assert pick_source(TaskSpec(structure_name="GaN")) == "aflow"
    assert pick_source(TaskSpec(structure_name="NaCl")) == "aflow"
    assert pick_source(TaskSpec(structure_name="ZIF-8")) == "core-mof"
    assert pick_source(TaskSpec(structure_name="UiO-66")) == "core-mof"
    assert pick_source(TaskSpec(structure_name="GaN", topology="sod")) == "core-mof"
    assert pick_source(TaskSpec(structure_id="mp-149")) == "materials-project"
    assert pick_source(TaskSpec(structure_id="7111973")) == "cod"
    assert pick_source(TaskSpec(structure_id="aflowlib.duke.edu:AFLOWDATA/LIB1_WEB/Zn:PAW_PBE:06Sep2000/A9")) == "aflow"


def test_aflow_type_symbol_sanitizer():
    """AFLOW writes PAW potential names in _atom_site_type_symbol (Fe -> P/Po bug)."""
    from cifkit.sources.aflow import sanitize_aflow_cif

    text = b"""data_test
_cell_length_a 2.45
loop_
 _atom_site_label
 _atom_site_occupancy
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_B_iso_or_equiv
 _atom_site_type_symbol
potpaw_PBE.54/Fe_sv1 1.0 0.0 0.0 0.0 1.0 potpaw_PBE.54/Fe_sv
"""
    out, changed = sanitize_aflow_cif(text)
    assert changed is True
    decoded = out.decode()
    assert "potpaw_PBE.54/Fe_sv1 1.0 0.0 0.0 0.0 1.0 Fe" in decoded
    # a normal CIF must be left byte-identical
    plain = b"data_x\nloop_\n _atom_site_label\n _atom_site_type_symbol\nZn1 Zn\n"
    out2, changed2 = sanitize_aflow_cif(plain)
    assert changed2 is False and out2 == plain

