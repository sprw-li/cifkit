"""Lead-owned integration tests: the pipeline end to end."""
from __future__ import annotations

from pathlib import Path

import pytest
from pymatgen.core import Structure

from cifkit.pipeline import run
from cifkit.spec import parse_request

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "data"
DEMO = (
    "帮我下载典型的RCSR为sod的mof，需要碳上补充氢，创建一个2x2x1的超胞（Supercell），"
    "沿(111)面切出表面，并加上15Å的真空层，导出为计算化学软件使用的格式。"
)


def _count(structure: Structure, el: str) -> int:
    return sum(1 for s in structure if s.species_string == el)


def test_local_hfree_pipeline(tmp_path):
    raw = FIXTURES / "zif8_raw_hfree.cif"
    spec = parse_request(f"把 {raw} 补氢，然后导出 cif", outdir=tmp_path / "local")
    spec.source = "local"
    assert spec.repair_h is True
    result = run(spec)
    assert result.ok, [s for s in result.steps if s.status == "failed"]
    repaired = Structure.from_file(Path(result.outdir) / "repaired.cif")
    assert len(repaired) == 276
    assert _count(repaired, "H") == 120
    assert _count(repaired, "C") == 96
    assert _count(repaired, "Zn") == 12
    assert (Path(result.outdir) / "structure.cif").is_file()


def test_no_h_added_on_complete_structure(tmp_path):
    raw = FIXTURES / "zif8_cr_sod.cif"
    spec = parse_request(f"把 {raw} 补氢后导出 cif", outdir=tmp_path / "noh")
    spec.source = "local"
    result = run(spec)
    assert result.ok
    repair = result.step("repair")
    assert repair is not None
    assert repair.data.get("added_h") == 0


@pytest.mark.slow
def test_demo_pipeline(tmp_path):
    """完整 demo：需要 _cache 里已有 CoRE MOF 2024 数据。"""
    spec = parse_request(DEMO, outdir=tmp_path / "demo")
    result = run(spec)
    assert result.ok, [s for s in result.steps if s.status == "failed"]
    rep = result.step("repair")
    assert rep is not None and rep.data.get("added_h") == 120
    surf = result.step("surface")
    assert surf is not None
    # 2x2x1 is applied in the slab frame: slab 552 -> 2x2 in-plane = 2208 atoms
    assert surf.data.get("reps") == (2, 2, 1)
    assert surf.data.get("atoms_after_reps") == 2208
    fin = Structure.from_file(Path(result.outdir) / "final.cif")
    assert len(fin) == 2208
    assert _count(fin, "H") == 960  # 120 H per conventional cell * 4 in-plane repeats
    assert (Path(result.outdir) / "structure.vasp").is_file()
