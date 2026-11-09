"""MP live path — only runs when a real MP_API_KEY is configured (otherwise skipped)."""
from __future__ import annotations

import pytest

from cifkit.sources.materials_project import MaterialsProjectSource, api_key
from cifkit.types import SourceQuery

pytestmark = pytest.mark.skipif(
    not api_key(), reason="MP_API_KEY not set; live MP path intentionally skipped (mock tests cover parsing)"
)


def _mp_or_skip(**kwargs):
    """Live MP query: skip on transport/upstream failure (no evidence either way)."""
    from cifkit.sources import get_source
    from cifkit.types import SourceQuery

    try:
        return get_source("materials-project").search(SourceQuery(**kwargs))
    except (RuntimeError, OSError) as exc:
        pytest.skip(f"MP 查询暂时失败（网络/上游）：{exc}")


def test_mp_live_search_mp149():
    src = MaterialsProjectSource()
    hits = _mp_or_skip(structure_id="mp-149", limit=1)
    assert hits, "MP live search returned no hit for mp-149"
    assert hits[0].record_id.startswith("mp-")
    try:
        fetched = src.fetch(hits[0])
    except (RuntimeError, OSError, ValueError) as exc:
        pytest.skip(f"MP 取回暂时失败（网络/上游）：{exc}")
    assert len(fetched.structure) > 0
    assert fetched.provenance.get("source") == "materials-project"


def test_mp_live_formula_search():
    hits = _mp_or_skip(structure_name="GaN", limit=3)
    assert hits, "MP live formula search returned no hit for GaN"
