"""数据源适配层测试：CoRE MOF 2024 / COD / local + ``resolve`` 语义。

离线优先：核心用例只依赖 ``_cache/core-mof-2024/`` 的本地缓存（已就绪）；
COD 联网用例用 ``skipif`` 检测网络（``cod_available()``）。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from cifkit.cache import cache_dir
from cifkit.sources import available_sources, get_source, resolve
from cifkit.sources import core_mof
from cifkit.sources.cod import cod_available
from cifkit.spec import parse_request
from cifkit.types import SourceQuery, TaskSpec

ROOT = Path(__file__).resolve().parents[1]
# The gate must ask the *effective* cache (i.e. ``$CIFKIT_CACHE`` first), otherwise a
# machine with a populated ``<repo>/_cache`` but an empty ``CIFKIT_CACHE`` runs tests
# that are guaranteed to fail — CI found this the hard way (round 58).
CACHE = cache_dir("core-mof-2024")
ZIP = CACHE / "CoREMOF2024DB.zip"
DATA = ROOT / "tests" / "data"

DEMO_QUERY = (
    "帮我下载典型的 RCSR 为 sod 的 MOF，需要碳上补充氢，创建一个 2x2x1 的超胞（Supercell），"
    "沿 (111) 面切出表面，并加上 15Å 的真空层，导出为计算化学软件使用的格式。"
)

needs_core = pytest.mark.skipif(not ZIP.is_file(), reason="CoRE MOF 2024 缓存缺失（_cache/core-mof-2024）")
needs_network = pytest.mark.skipif(not cod_available(), reason="COD 不可达（离线环境）")

RAW_ZIF8 = "SI/NCR/both/ja204757x_si_002_ASR_pacman.cif"
CR_ZIF8_SOD = "SI/CR/ASR/2015[Zn][sod]3[ASR]1.cif"


@pytest.fixture(scope="module")
def core_source():
    return core_mof.CoreMOFSource()


# ---------------------------------------------------------------------------
# registry / 基础接口
# ---------------------------------------------------------------------------
def test_available_sources():
    sources = available_sources()
    assert set(sources) >= {"core-mof", "cod", "local", "materials-project", "aflow"}
    assert all(isinstance(desc, str) and desc for desc in sources.values())


def test_get_source_aliases_and_singleton():
    assert get_source("core-mof") is get_source("core_mof") is get_source("core-mof-2024")
    assert get_source("cod").name == "cod"
    assert get_source("file").name == "local"
    with pytest.raises(ValueError):
        get_source("does-not-exist")


# ---------------------------------------------------------------------------
# 索引（离线）
# ---------------------------------------------------------------------------
@needs_core
def test_index_is_complete_and_summarised():
    index = core_mof.load_index()
    assert index["schema"] == core_mof.SCHEMA
    assert index["n_entries"] >= 8000
    assert index["n_computation_ready"] >= 2000
    assert index["n_raw"] >= 5000
    assert index["dataset"]["doi"] == "10.5281/zenodo.15055758"
    assert index["dataset"]["license"] == "CC-BY-4.0"
    assert index["zip"]["sha256"]

    raw = index["entries"][RAW_ZIF8]
    assert raw["h_count"] == 0
    assert raw["natoms"] == 156
    assert raw["variant"] == "raw"
    assert raw["abc"] == [17.0293, 17.0293, 17.0293]

    ready = index["entries"][CR_ZIF8_SOD]
    assert ready["topology_allnodes"] == "sod"
    assert ready["h_count"] == 60
    assert ready["refcode"] == "ic5028256_si_002_ASR_pacman"
    assert ready["doi"] == "10.1021/ic5028256"


@needs_core
def test_reference_candidates_sorted_typical_first():
    candidates = core_mof.reference_candidates("sod")
    assert len(candidates) == 7  # DESIGN §4：ASR topology(AllNodes)==sod 共 7 条
    assert candidates[0]["zip_path"] == CR_ZIF8_SOD
    assert candidates[0]["topology"] == "sod"


# ---------------------------------------------------------------------------
# search：计算就绪 vs 原始（prefer_raw）
# ---------------------------------------------------------------------------
@needs_core
def test_search_sod_ready_returns_computation_ready_metadata(core_source):
    hits = core_source.search(SourceQuery(topology="sod"))
    assert len(hits) == 7
    assert len({hit.record_id for hit in hits}) == 7
    assert all(hit.topology == "sod" for hit in hits)
    assert all(hit.topology_evidence == "metadata" for hit in hits)
    assert all(hit.variant == "computation-ready" for hit in hits)
    assert all(hit.is_h_deficient() is False for hit in hits)
    assert hits[0].record_id == f"core-mof:{CR_ZIF8_SOD}"
    assert hits[0].h_count == 60
    assert hits[0].doi == "10.1021/ic5028256"


@needs_core
def test_search_sod_raw_first_is_hfree_zif8_verified(core_source):
    hits = core_source.search(SourceQuery(topology="sod", prefer_raw=True, limit=3))
    assert hits, "sod 原始候选应至少有一条"
    assert len(hits) <= 3
    first = hits[0]
    assert first.record_id == f"core-mof:{RAW_ZIF8}"
    assert first.refcode == "ja204757x_si_002_ASR_pacman"
    assert first.variant == "raw"
    assert first.h_count == 0
    assert first.h_expected is not None and 100 <= first.h_expected <= 140
    assert first.is_h_deficient() is True
    assert first.doi == "10.1021/ja204757x"
    # 拓扑证据必须来自结构比对（不是硬编码），且带数值签名
    assert first.topology_evidence == "verified"
    verification = first.extra["topology_verification"]
    assert verification["ok"] is True
    assert verification["evidence"] == "verified"
    signature = verification["signature"]
    assert signature["coordination_numbers"] == {"4": 1.0}
    assert signature["coordination_sequence"][:3] == [4.0, 10.0, 20.0]
    assert signature["rings_per_node"]["4"]["per_node"] > 0
    assert signature["rings_per_node"]["6"]["per_node"] > 0
    # notes 里要能解释候选发现方式 + 估计值来源（不能 silent hardcode）
    joined = " ".join(first.notes)
    assert "curated" in joined
    assert "非实测" in joined

    # 同一条查询必须稳定复现（确定性排序）
    again = core_source.search(SourceQuery(topology="sod", prefer_raw=True, limit=3))
    assert [hit.record_id for hit in again] == [hit.record_id for hit in hits]


# ---------------------------------------------------------------------------
# fetch：zip 提取 + sha256 + provenance
# ---------------------------------------------------------------------------
@needs_core
def test_fetch_raw_hfree_zif8(core_source):
    hits = core_source.search(SourceQuery(topology="sod", prefer_raw=True, limit=1))
    record = hits[0]
    fetched = core_source.fetch(record)

    assert len(fetched.structure) == 156
    assert fetched.structure.composition["Zn"] == 12
    assert fetched.structure.composition["C"] == 96
    assert fetched.structure.composition["N"] == 48
    assert fetched.structure.composition["H"] == 0
    assert fetched.record.h_count == 0
    assert fetched.record.natoms == 156

    provenance = fetched.provenance
    cif_path = Path(provenance["cif_path"])
    assert cif_path.is_file()
    data = cif_path.read_bytes()
    assert provenance["sha256"] == hashlib.sha256(data).hexdigest()
    assert provenance["cif_sha256"] == provenance["sha256"]
    assert provenance["zip_path"] == RAW_ZIF8
    assert provenance["zip_sha256"]
    assert provenance["dataset_doi"] == "10.5281/zenodo.15055758"
    assert provenance["license"] == "CC-BY-4.0"
    assert provenance["url"].startswith("https://zenodo.org/")
    assert provenance["doi"] == "10.1021/ja204757x"
    assert provenance["topology_evidence"] == "verified"

    # 再取一次：sha256 稳定、缓存复用
    again = core_source.fetch(record)
    assert again.provenance["sha256"] == provenance["sha256"]
    assert again.provenance["cache_reused"] is True


@needs_core
def test_fetch_ready_structure(core_source):
    hits = core_source.search(SourceQuery(topology="sod", limit=1))
    fetched = core_source.fetch(hits[0])
    assert len(fetched.structure) == 138
    assert fetched.record.h_count == 60
    assert fetched.record.h_expected is None
    assert fetched.record.is_h_deficient() is False
    assert Path(fetched.provenance["cif_path"]).is_file()


# ---------------------------------------------------------------------------
# resolve：语义（demo 硬性要求）
# ---------------------------------------------------------------------------
@needs_core
def test_resolve_demo_returns_hfree_zif8():
    spec = parse_request(DEMO_QUERY)
    assert spec.topology == "sod"
    assert spec.repair_h is True
    fetched = resolve(spec)

    record = fetched.record
    assert record.record_id == f"core-mof:{RAW_ZIF8}"
    assert record.variant == "raw"
    assert record.topology_evidence == "verified"
    assert record.h_count == 0
    assert record.h_expected is not None and record.h_expected >= 100
    assert record.is_h_deficient() is True
    assert record.doi == "10.1021/ja204757x"
    assert len(fetched.structure) == 156
    # 缺氢：结构里确实没有 H 原子
    assert sum(1 for site in fetched.structure if site.species_string == "H") == 0

    resolution = fetched.provenance["resolution"]
    assert resolution["resolved_source"] == "core-mof"
    assert resolution["n_hits"] >= 1
    assert resolution["selected"] == record.record_id


@needs_core
def test_resolve_without_repair_returns_ready_structure():
    spec = parse_request("下载 RCSR 为 sod 的 MOF")
    assert spec.repair_h is False
    fetched = resolve(spec)
    assert fetched.record.variant == "computation-ready"
    assert fetched.record.topology_evidence == "metadata"
    assert fetched.record.h_count == 60
    assert len(fetched.structure) == 138


@needs_core
def test_resolve_name_only_query_honours_repair_h():
    spec = parse_request("下载 ZIF-8 结构，需要补氢")
    assert spec.structure_name == "ZIF-8"
    assert spec.topology is None
    fetched = resolve(spec)
    assert fetched.record.variant == "raw"
    assert fetched.record.h_count == 0
    assert "ja204757x_si_002" in fetched.record.record_id
    assert fetched.record.topology_evidence == "verified"


def test_resolve_local_file():
    path = DATA / "zif8_raw_hfree.cif"
    spec = TaskSpec(query="本地文件", source="local", structure_id=str(path))
    fetched = resolve(spec)
    assert len(fetched.structure) == 156
    assert fetched.record.source == "local"
    assert fetched.record.variant == "raw"
    assert fetched.record.h_count == 0
    assert fetched.provenance["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert Path(fetched.provenance["cif_path"]) == path


def test_resolve_without_target_raises():
    with pytest.raises(ValueError, match="无法确定数据源"):
        resolve(TaskSpec(query="你好"))


@needs_core
def test_resolve_unknown_topology_raises():
    with pytest.raises(ValueError, match="无命中"):
        resolve(TaskSpec(query="x", topology="zzz"))


# ---------------------------------------------------------------------------
# COD（联网；离线自动 skip）
# ---------------------------------------------------------------------------
@needs_network
def live_cod_search(**kwargs):
    """Run a live COD query, skipping on transport failure.

    ``needs_network`` only proves a TCP connection at *collection* time; the API can
    still fail later (round 27: a transient connection error failed the suite).
    A transport error means "no evidence either way" → skip.  A contract problem
    (a response that cannot be parsed) is different: that still raises.
    """
    try:
        return get_source("cod").search(SourceQuery(**kwargs))
    except RuntimeError as exc:
        pytest.skip(f"COD 查询暂时失败（网络/上游，非代码问题）：{exc}")


def test_cod_search_and_fetch_by_id():
    source = get_source("cod")
    hits = live_cod_search(structure_id="7111973", limit=1)
    assert hits and hits[0].record_id == "cod:7111973"
    assert hits[0].topology is None
    assert hits[0].topology_evidence == "unknown"

    try:
        fetched = source.fetch(hits[0])
    except (RuntimeError, ValueError) as exc:
        pytest.skip(f"COD 取回暂时失败（网络/上游）：{exc}")
    assert len(fetched.structure) > 0
    assert fetched.provenance["source"] == "cod"
    assert fetched.provenance["cod_id"] == "7111973"
    assert fetched.provenance["url"].endswith("/cod/7111973.cif")
    assert len(fetched.provenance["sha256"]) == 64
    assert Path(fetched.provenance["cif_path"]).is_file()


@needs_network
def test_cod_search_by_name():
    hits = live_cod_search(structure_name="ZIF-8", limit=3)
    assert hits, "COD 对 ZIF-8 应有命中"
    assert all(hit.source == "cod" for hit in hits)
    assert all(hit.record_id.startswith("cod:") for hit in hits)


@needs_network
def test_cod_rejects_non_numeric_id():
    with pytest.raises(ValueError):
        get_source("cod").search(SourceQuery(structure_id="ZIF-8"))


def test_cod_search_accepts_prefixed_record_id(monkeypatch):
    """search() returns record_id="cod:<id>"; resolving by that id must work."""
    from cifkit.sources import cod as cod_module
    from cifkit.types import SourceQuery

    calls: list[str] = []

    def fake_ensure(cod_id, *, refresh=False):
        calls.append(cod_id)
        path = cod_module.cod_cache_path(cod_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "data_1\n_cell_length_a 5\n_cell_length_b 5\n_cell_length_c 5\n"
            "_cell_angle_alpha 90\n_cell_angle_beta 90\n_cell_angle_gamma 90\n"
            "loop_\n_atom_site_label\n_atom_site_type_symbol\n_atom_site_fract_x\n"
            "_atom_site_fract_y\n_atom_site_fract_z\nSi1 Si 0 0 0\n",
            encoding="utf-8")
        return path, True

    monkeypatch.setattr(cod_module, "_ensure_cif", fake_ensure)
    source = cod_module.CODSource()
    records = source.search(SourceQuery(structure_id="cod:7111973", source="cod", limit=1))
    assert calls == ["7111973"], calls
    assert records and records[0].record_id.endswith("7111973")
