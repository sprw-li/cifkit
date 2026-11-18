"""拓扑判定测试：underlying net 签名 + verify 的证据等级（结构比对，不硬编码）。

全部离线（tests/data fixtures + _cache 里的 CoRE 参考结构）；CoRE 缓存缺失时
相关用例自动 skip，但核心用例只依赖 ``tests/data/zif8_cr_sod.cif`` 作为显式参考。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from cifkit import topology
from cifkit.cache import cache_dir
from cifkit.types import StructureRecord

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"
# gate on the *effective* cache ($CIFKIT_CACHE first) — see tests/test_sources.py
CACHE_ZIP = cache_dir("core-mof-2024") / "CoREMOF2024DB.zip"

needs_core = pytest.mark.skipif(
    not CACHE_ZIP.is_file(),
    reason="CoRE MOF 2024 cache 缺失（跑 scripts/bootstrap_data.py，或设置 CIFKIT_CACHE）")

# sod 参考签名（由 underlying net 结构比对得到，不是数据库标签）
SOD_COORDINATION_SEQUENCE = [4.0, 10.0, 20.0, 34.0, 52.0, 74.0, 100.0, 130.0]


@pytest.fixture(scope="module")
def cr_sod():
    return Structure.from_file(DATA / "zif8_cr_sod.cif")


@pytest.fixture(scope="module")
def raw_hfree():
    return Structure.from_file(DATA / "zif8_raw_hfree.cif")


@pytest.fixture(scope="module")
def cr_reference_path():
    return str(DATA / "zif8_cr_sod.cif")


@pytest.fixture(scope="module")
def verified_raw(raw_hfree, cr_reference_path):
    topology.clear_cache()
    return topology.verify(raw_hfree, "sod", reference=cr_reference_path)


# ---------------------------------------------------------------------------
# underlying net / 签名
# ---------------------------------------------------------------------------
def test_underlying_net_primitive_cell(cr_sod):
    net = topology.underlying_net(cr_sod)
    assert net["n_nodes"] == 6
    assert net["n_edges"] == 12
    assert net["n_linkers"] == 12
    assert net["warnings"] == []
    # 每个 Zn 节点 4 配位（sod 是 4-c net）
    coordination = {}
    for edge in net["edges"]:
        coordination[edge["i"]] = coordination.get(edge["i"], 0) + 1
    assert sorted(coordination.values()) == [4] * 6
    assert {node["element"] for node in net["nodes"]} == {"Zn"}


def test_underlying_net_conventional_cell(raw_hfree):
    net = topology.underlying_net(raw_hfree)
    assert net["n_nodes"] == 12
    assert net["n_edges"] == 24
    assert net["n_linkers"] == 24


def test_signature_is_cell_independent(cr_sod, raw_hfree):
    sig_cr = topology.describe(cr_sod)["signature"]
    sig_raw = topology.describe(raw_hfree)["signature"]
    assert sig_cr is not None and sig_raw is not None
    # 原胞 vs 常规胞：节点数不同，但归一化不变量必须一致
    assert sig_cr["n_metal_nodes"] == 6
    assert sig_raw["n_metal_nodes"] == 12
    assert sig_cr["coordination_numbers"] == {"4": 1.0}
    assert sig_raw["coordination_numbers"] == {"4": 1.0}
    assert sig_cr["coordination_sequence"] == SOD_COORDINATION_SEQUENCE
    assert sig_raw["coordination_sequence"] == SOD_COORDINATION_SEQUENCE
    assert sig_cr["linkers_per_metal"] == sig_raw["linkers_per_metal"] == 2.0
    for size in ("4", "6", "8"):
        assert sig_cr["rings_per_node"][size]["per_node"] == pytest.approx(
            sig_raw["rings_per_node"][size]["per_node"], abs=1e-6
        )
    # sod 有 4/6/8 元环，没有 5/7 元环（作为 sanity check，不是硬编码结论）
    assert sig_cr["rings_per_node"]["4"]["per_node"] > 0
    assert sig_cr["rings_per_node"]["6"]["per_node"] > 0
    assert sig_cr["rings_per_node"]["5"]["per_node"] == 0
    assert sig_cr["rings_per_node"]["7"]["per_node"] == 0
    assert sig_cr["rings_truncated"] is False
    assert sig_cr["coordination_sequence_truncated"] is False


def test_describe_shape(cr_sod):
    info = topology.describe(cr_sod)
    assert info["natoms"] == 138
    assert info["metals"] == ["Zn"]
    assert info["net"] == {"n_nodes": 6, "n_edges": 12, "n_linkers": 12}
    assert isinstance(info["signature"], dict)


# ---------------------------------------------------------------------------
# verify：结构比对 → verified（demo 硬性要求）
# ---------------------------------------------------------------------------
def test_verify_hfree_zif8_is_verified(verified_raw, cr_reference_path):
    result = verified_raw
    assert result["ok"] is True
    assert result["evidence"] == "verified"
    assert "underlying net 签名一致" in result["detail"]
    # detail 必须写清比较了什么 + 数值（不许空泛"已验证"）
    assert "配位数" in result["detail"]
    assert "配位序列" in result["detail"]
    assert "环分布" in result["detail"]
    assert "4.0" in result["detail"] or "4," in result["detail"]

    signature = result["signature"]
    assert signature["coordination_numbers"] == {"4": 1.0}
    assert signature["coordination_sequence"] == SOD_COORDINATION_SEQUENCE
    assert signature["rings_per_node"]["4"]["per_node"] > 0

    reference = result["reference"]
    assert reference is not None
    assert reference["record_id"] == cr_reference_path


def test_repeated_verify_is_stable(raw_hfree, cr_reference_path):
    first = topology.verify(raw_hfree, "sod", reference=cr_reference_path)
    second = topology.verify(raw_hfree, "sod", reference=cr_reference_path)
    assert first["ok"] == second["ok"] is True
    assert first["evidence"] == second["evidence"] == "verified"
    assert first["signature"] == second["signature"]


@needs_core
def test_verify_uses_core_reference_by_default(raw_hfree):
    result = topology.verify(raw_hfree, "sod")
    assert result["ok"] is True
    assert result["evidence"] == "verified"
    reference = result["reference"]
    assert reference["record_id"].endswith("SI/CR/ASR/2015[Zn][sod]3[ASR]1.cif")
    assert reference["topology_evidence"] == "metadata"


@needs_core
def test_verify_ready_structure_is_metadata_not_verified(cr_sod):
    # 结构本身 == CoRE ASR labeled 记录时，证据等级是 metadata（不是结构比对）
    result = topology.verify(cr_sod, "sod")
    assert result["ok"] is True
    assert result["evidence"] == "metadata"
    assert "CoRE MOF 2024 ASR" in result["detail"]


def test_verify_record_metadata_argument(cr_sod):
    record = StructureRecord(
        record_id="test:sod-record",
        source="test",
        topology="sod",
        topology_evidence="metadata",
    )
    result = topology.verify(cr_sod, "sod", record=record)
    assert result["ok"] is True
    assert result["evidence"] == "metadata"


# ---------------------------------------------------------------------------
# verify：明显不同的结构 → mismatch / unknown（优雅降级）
# ---------------------------------------------------------------------------
def test_verify_cscl_net_mismatch(cr_reference_path):
    # 简单立方 CsCl 型：Cs 节点配位数与 sod 完全不同 → 必须 mismatch
    structure = Structure(Lattice.cubic(3.0), ["Cs", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    result = topology.verify(structure, "sod", reference=cr_reference_path)
    assert result["ok"] is False
    assert result["evidence"] == "mismatch"
    assert "配位数" in result["detail"]


def test_verify_main_group_structure_is_unknown(cr_reference_path):
    # 纯主族体系（Si/O，无金属节点）→ unknown，不抛异常、不硬编造拓扑
    structure = Structure(
        Lattice.cubic(5.0), ["Si", "O", "O"], [[0, 0, 0], [0.25, 0.25, 0.25], [0.75, 0.75, 0.75]]
    )
    result = topology.verify(structure, "sod", reference=cr_reference_path)
    assert result["ok"] is False
    assert result["evidence"] == "unknown"
    assert "金属节点" in result["detail"]


def test_verify_unknown_topology_without_reference_is_unknown(raw_hfree):
    result = topology.verify(raw_hfree, "zzz")
    assert result["ok"] is False
    assert result["evidence"] == "unknown"
    assert "参考" in result["detail"]


def test_verify_empty_expected_is_unknown(raw_hfree):
    result = topology.verify(raw_hfree, "")
    assert result["ok"] is False
    assert result["evidence"] == "unknown"


@needs_core
def test_verify_real_pcu_structure_is_mismatch(cr_reference_path):
    from cifkit.sources import core_mof

    candidate = core_mof.reference_candidates("pcu")[0]
    structure = core_mof.load_structure(candidate["zip_path"])
    result = topology.verify(structure, "sod", reference=cr_reference_path)
    assert result["ok"] is False
    assert result["evidence"] == "mismatch"


def test_evidence_values_are_documented_enum(verified_raw):
    assert verified_raw["evidence"] in {"metadata", "verified", "curated", "mismatch", "unknown"}
    # 只有 ok=True 才允许 metadata/verified；ok=False 时不能是 verified
    if verified_raw["ok"]:
        assert verified_raw["evidence"] in {"metadata", "verified"}
