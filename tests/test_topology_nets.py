"""Round2 拓扑库扩容测试：落盘参考签名（pcu/dia/fcu/tbo/bcu/sod）+ verify/identify。

**完全离线**：只读包内 ``cifkit/data/nets/<net>.json`` 与 ``<net>-reference.cif``；
不访问网络、不依赖 ``_cache/core-mof-2024/`` 的 CoRE zip（有专门的断网模拟用例）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from cifkit import topology

NETS_DIR = Path(topology.__file__).resolve().parent / "data" / "nets"
BUNDLED_NETS = ["bcu", "dia", "fcu", "pcu", "sod", "tbo"]
TASK_NETS = ["pcu", "dia", "fcu", "tbo", "bcu"]

#: 每个 net 参考结构的核心不变量（数值签名）；用于防止参考文件被悄悄改坏
EXPECTED_SIGNATURES = {
    "pcu": {"coordination_numbers": {"6": 1.0}, "cs_prefix": [6.0, 18.0, 38.0, 66.0]},
    "dia": {"coordination_numbers": {"4": 1.0}, "cs_prefix": [4.0, 12.0, 24.0, 42.0]},
    "fcu": {"coordination_numbers": {"12": 1.0}, "cs_prefix": [12.0, 42.0, 92.0, 162.0]},
    "tbo": {"coordination_numbers": {"8": 1.0}, "cs_prefix": [8.0, 30.0, 68.0, 126.0]},
    "bcu": {"coordination_numbers": {"8": 1.0}, "cs_prefix": [8.0, 26.0, 56.0, 98.0]},
    "sod": {"coordination_numbers": {"4": 1.0}, "cs_prefix": [4.0, 10.0, 20.0, 34.0]},
}


@pytest.fixture(scope="module")
def bundled() -> dict[str, dict]:
    """net -> 落盘参考 dict（load_reference 结果）。"""
    refs = {}
    for net in BUNDLED_NETS:
        reference = topology.load_reference(net)
        assert reference is not None, f"{net} 参考签名缺失"
        refs[net] = reference
    return refs


@pytest.fixture(scope="module")
def ref_structures() -> dict[str, Structure]:
    """net -> 从落盘参考 CIF 解析出的结构（离线）。"""
    structures = {}
    for net in BUNDLED_NETS:
        reference = topology.load_reference(net)
        cif_path = Path(reference["cif_path"])
        assert cif_path.is_file(), f"{net} 参考 CIF 缺失：{cif_path}"
        structures[net] = Structure.from_file(cif_path)
    return structures


# ---------------------------------------------------------------------------
# 落盘参考文件本身的可审计性
# ---------------------------------------------------------------------------
def test_reference_files_exist_and_are_consistent(bundled):
    assert topology.available_reference_nets() == BUNDLED_NETS
    for net in BUNDLED_NETS:
        json_path = NETS_DIR / f"{net}.json"
        assert json_path.is_file()
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["schema"] == topology.REFERENCE_SCHEMA
        assert payload["net"] == net
        # 来源可溯源：record_id / DOI / 参考 CIF + sha256
        source = payload["source"]
        assert source["record_id"].startswith("core-mof:")
        assert source["natoms"] and source["natoms"] > 0
        assert source["formula"]
        assert source["doi"], f"{net} 缺 DOI"
        cif_path = NETS_DIR / payload["cif"]
        assert cif_path.is_file()
        assert hashlib.sha256(cif_path.read_bytes()).hexdigest() == payload["cif_sha256"]
        # 生成方式可复现
        assert payload["generated_at"]
        assert payload["generated_by"]["command"]
        assert payload["selection_reason"]
        # 数值签名
        signature = payload["signature"]
        assert signature["coordination_numbers"]
        assert len(signature["coordination_sequence"]) == 8
        assert "rings_per_node" in signature


@pytest.mark.parametrize("net", BUNDLED_NETS)
def test_reference_signature_values(net):
    reference = topology.load_reference(net)
    signature = reference["signature"]
    expected = EXPECTED_SIGNATURES[net]
    assert signature["coordination_numbers"] == expected["coordination_numbers"]
    assert signature["coordination_sequence"][:4] == expected["cs_prefix"]
    # 参考结构自身签名不完整就不能当 verified 依据；配位序列必须完整
    assert signature["coordination_sequence_truncated"] is False
    assert signature["linkers_per_metal"] > 0


# ---------------------------------------------------------------------------
# verify：每个 net 的参考结构自身必须通过（结构比对路径，不靠 metadata 短路）
# ---------------------------------------------------------------------------
@pytest.fixture
def structural_only(monkeypatch):
    """关闭 CoRE 元数据指纹，强制走 underlying net 结构比对路径。

    同时清空进程内 verify/reference 缓存：同一进程里其它测试可能已缓存过
    "metadata 证据"的 verify 结果（缓存键只看结构+expected，不看环境），
    这里必须从干净状态开始测结构比对路径。
    """
    topology.clear_cache()
    monkeypatch.setattr(topology, "_core_metadata_fingerprint", lambda structure: None)


@pytest.mark.parametrize("net", TASK_NETS + ["sod"])
def test_verify_reference_structure_against_own_net(net, ref_structures, structural_only):
    result = topology.verify(ref_structures[net], net)
    assert result["ok"] is True
    assert result["evidence"] == "verified"
    assert result["reference"]["bundled"] is True
    assert result["reference"]["topology"] == net
    verified_on = result.get("verified_on") or []
    assert "coordination_numbers" in verified_on
    assert "coordination_sequence" in verified_on
    assert "linkers_per_metal" in verified_on
    # 配位序列必须在 detail / signature 里可查
    assert result["signature"]["coordination_sequence"][:4] == EXPECTED_SIGNATURES[net]["cs_prefix"]


@pytest.mark.parametrize("net", BUNDLED_NETS)
def test_verify_reference_returns_dict_contract(net, ref_structures, structural_only):
    result = topology.verify(ref_structures[net], net)
    # 向后兼容：verify 返回字段不变（ok/evidence/detail/signature/reference），可加字段
    for key in ("ok", "evidence", "detail", "signature", "reference"):
        assert key in result
    assert result["evidence"] in {"metadata", "verified", "curated", "mismatch", "unknown"}


# ---------------------------------------------------------------------------
# 交叉错配：不同 net 的参考结构必须 mismatch（不能把任何结构都说成目标 net）
# ---------------------------------------------------------------------------
def test_pcu_structure_is_not_sod(ref_structures, structural_only):
    result = topology.verify(ref_structures["pcu"], "sod")
    assert result["ok"] is False
    assert result["evidence"] == "mismatch"
    assert "配位数" in result["detail"]


def test_fcu_structure_is_not_pcu(ref_structures, structural_only):
    result = topology.verify(ref_structures["fcu"], "pcu")
    assert result["ok"] is False
    assert result["evidence"] == "mismatch"
    assert "配位数" in result["detail"]


def test_tbo_structure_is_not_bcu(ref_structures, structural_only):
    # tbo 与 bcu 都是 8 配位，靠配位序列区分 → 这条用例专门防止"只看配位数"的假阳性
    result = topology.verify(ref_structures["tbo"], "bcu")
    assert result["ok"] is False
    assert result["evidence"] == "mismatch"


def test_sod_structure_is_not_dia(ref_structures, structural_only):
    # sod 与 dia 都是 4 配位，靠配位序列/环分布区分
    result = topology.verify(ref_structures["sod"], "dia")
    assert result["ok"] is False
    assert result["evidence"] == "mismatch"


# ---------------------------------------------------------------------------
# identify：最佳 net + unknown 语义
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("net", BUNDLED_NETS)
def test_identify_bundled_reference_structures(net, ref_structures):
    result = topology.identify(ref_structures[net])
    assert result["ok"] is True
    assert result["net"] == net
    assert result["best_net"] == net
    assert result["evidence"] == "verified"
    assert result["reference"]["bundled"] is True
    assert result["signature"] is not None
    assert any(candidate["net"] == net and candidate["base_ok"] for candidate in result["candidates"])


def test_identify_zif8_raw_hfree_is_sod():
    structure = Structure.from_file(Path(__file__).parent / "data" / "zif8_raw_hfree.cif")
    result = topology.identify(structure)
    assert result["ok"] is True
    assert result["net"] == "sod"
    assert result["evidence"] == "verified"


def test_identify_nets_subset_argument(ref_structures):
    result = topology.identify(ref_structures["fcu"], nets=["pcu", "fcu"])
    assert result["ok"] is True
    assert result["net"] == "fcu"
    # 限制候选集后不应看到别的 net
    assert {candidate["net"] for candidate in result["candidates"]} <= {"pcu", "fcu"}


def test_identify_no_metal_structure_is_unknown():
    # 纯主族 Si/O 体系：无金属节点 → unknown，不抛异常
    structure = Structure(
        Lattice.cubic(5.0), ["Si", "O", "O"], [[0, 0, 0], [0.25, 0.25, 0.25], [0.75, 0.75, 0.75]]
    )
    result = topology.identify(structure)
    assert result["ok"] is False
    assert result["net"] is None
    assert result["evidence"] == "unknown"
    assert "金属节点" in result["detail"]


def test_identify_ionic_structure_is_unknown_or_mismatch():
    # CsCl 型无机离子体系：无有机 linker → net 不可用；允许 unknown，但绝不能硬判成某个 net
    structure = Structure(Lattice.cubic(3.0), ["Cs", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    result = topology.identify(structure)
    assert result["ok"] is False
    assert result["net"] is None
    assert result["evidence"] in {"unknown", "mismatch"}


# ---------------------------------------------------------------------------
# 离线：没有 CoRE zip / 不联网时，落盘参考仍然可用
# ---------------------------------------------------------------------------
def test_offline_without_core_mof_cache(tmp_path, monkeypatch, ref_structures):
    import cifkit.sources.core_mof as core_mof

    # 1) 空缓存目录（没有 CoRE zip）；2) 清掉进程内索引缓存
    monkeypatch.setenv("CIFKIT_CACHE", str(tmp_path))
    monkeypatch.setattr(core_mof, "_INDEX_CACHE", None, raising=False)
    monkeypatch.setattr(core_mof, "_META_CACHE", None, raising=False)
    topology.clear_cache()

    # verify：元数据指纹因无 zip 而不可用，必须仍能靠落盘参考给出 verified
    result = topology.verify(ref_structures["fcu"], "fcu")
    assert result["ok"] is True
    assert result["evidence"] == "verified"
    assert result["reference"]["bundled"] is True

    # identify：同样只用落盘签名
    identified = topology.identify(ref_structures["pcu"])
    assert identified["ok"] is True
    assert identified["net"] == "pcu"

    # 未知拓扑 / 无金属仍然诚实 unknown（不会因为离线就乱猜）
    assert topology.verify(ref_structures["pcu"], "zzz")["evidence"] == "unknown"
