"""Lead-owned tests: NL parser + plan + CLI plumbing."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from cifkit.plan import build_plan
from cifkit.spec import parse_request

ROOT = Path(__file__).resolve().parents[1]
DEMO = (
    "帮我下载典型的RCSR为sod的mof，需要碳上补充氢，创建一个2x2x1的超胞（Supercell），"
    "沿(111)面切出表面，并加上15Å的真空层，导出为计算化学软件使用的格式。"
)


def test_demo_sentence_slots():
    spec = parse_request(DEMO)
    assert spec.topology == "sod"
    assert spec.repair_h is True
    assert spec.supercell == (2, 2, 1)
    assert spec.surface == (1, 1, 1)
    assert spec.vacuum == 15.0
    assert "vasp" in spec.output_formats


def test_demo_plan_order():
    spec = parse_request(DEMO)
    names = [s.name for s in build_plan(spec)]
    # 2x2x1 is folded into the surface step (slab-frame repeats), so there is no
    # separate supercell step for the demo request.
    order = ["resolve", "verify-topology", "repair", "standardize", "surface", "vacuum", "export", "validate"]
    idx = [names.index(n) for n in order]
    assert idx == sorted(idx)
    assert "supercell" not in names


def test_english_variant():
    spec = parse_request(
        "Download a typical RCSR sod MOF, add hydrogen, make a 2x2x1 supercell, "
        "cleave the (111) surface with 15 A vacuum, export VASP POSCAR."
    )
    assert spec.topology == "sod"
    assert spec.supercell == (2, 2, 1)
    assert spec.surface == (1, 1, 1)
    assert spec.vacuum == 15.0
    assert "vasp" in spec.output_formats
    assert spec.repair_h is True


def test_local_path_detected():
    spec = parse_request(r"把 D:\data\mof.cif 补氢后导出 cif")
    assert spec.source == "local"
    assert spec.structure_id and spec.structure_id.endswith("mof.cif")
    assert spec.repair_h is True


def test_missing_structure_is_reported():
    spec = parse_request("帮我处理一下这个结构，补氢")
    assert spec.topology is None
    assert any("没有识别到拓扑" in n for n in spec.notes)


def test_route_cli_json():
    out = subprocess.run(
        [sys.executable, "-m", "cifkit", "route", DEMO, "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert out.returncode == 0, out.stderr
    data = json.loads(out.stdout)
    assert data["spec"]["topology"] == "sod"
    assert [p["name"] for p in data["plan"]][:3] == ["resolve", "verify-topology", "repair"]
