"""MP live path — only runs when a real MP_API_KEY is configured (otherwise skipped)."""
from __future__ import annotations

import pytest

from cifkit.sources.materials_project import MaterialsProjectSource, api_key
from cifkit.types import SourceQuery

pytestmark = pytest.mark.skipif(
    not api_key(), reason="MP_API_KEY not set; live MP path intentionally skipped (mock tests cover parsing)"
)


def test_mp_live_search_mp149():
    src = MaterialsProjectSource()
    hits = src.search(SourceQuery(structure_id="mp-149", limit=1))
    assert hits, "MP live search returned no hit for mp-149"
    assert hits[0].record_id.startswith("mp-")
    fetched = src.fetch(hits[0])
    assert len(fetched.structure) > 0
    assert fetched.provenance.get("source") == "materials-project"


def test_mp_live_formula_search():
    src = MaterialsProjectSource()
    hits = src.search(SourceQuery(structure_name="GaN", limit=3))
    assert hits, "MP live formula search returned no hit for GaN"
