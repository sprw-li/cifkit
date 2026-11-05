"""Source adapters: database lookup + download, behind one registry.

Available sources: ``core-mof`` (CoRE MOF 2024, 有 RCSR 拓扑列), ``cod``
(Crystallography Open Database，公有领域、无拓扑列), ``materials-project``
(Materials Project，需 ``MP_API_KEY``，DFT 结构、无拓扑列), ``aflow``
(AFLOW，免 key、无机/合金、无拓扑列), ``qmof`` (QMOF，DFT 标注 MOF；读取本地镜像，
官方 figshare/GitHub 在本环境不可达，未 live 实测), ``local`` (本地 CIF)。

Every adapter returns ``StructureRecord`` hits from ``search`` and a
``FetchedStructure`` from ``fetch``. ``resolve(spec)`` picks adapters based on
``spec.source``. ``auto`` 规则：``mp-<digits>`` → materials-project；``aflow:``/
``AFLOWDATA/`` → aflow；7 位数字 → cod；``.cif`` → local；有 topology/name →
core-mof（MOF 拓扑库）；显式 ``--source`` 优先。

``resolve`` 的 ``prefer_raw`` 语义（task-1 硬性要求）
----------------------------------------------------
用户说"需要碳上补充氢"时 ``spec.repair_h=True``，``resolve`` 会把它翻译成
``SourceQuery(prefer_raw=True)``：优先返回**需要修复的原始 CIF**（H 缺失/占位），
并保证 ``record.h_count / h_expected / variant / topology_evidence`` 语义正确。

对 ``topology="sod"``：返回 CoRE MOF 2024 NCR 目录里 H 缺失的 ZIF-8 原始 CIF
（``SI/NCR/both/ja204757x_si_002_ASR_pacman.cif``，Zn12C96N48，156 原子，0 H，
DOI 10.1021/ja204757x），其拓扑经过 ``cifkit.topology.verify`` 结构比对后标
``verified``；而 ``prefer_raw=False`` 时返回 CoRE ASR 里 H 完整的计算就绪结构
（证据等级 ``metadata``）。

多候选处理
----------
``resolve`` 在 ``len(hits) > 1`` 时：若查询带 ``typical`` / ``prefer_raw`` /
显式 ``structure_name`` / ``structure_id``，按检索的确定性排序取第一条（并把候选
数量与选择规则写进 ``provenance["resolution"]``）；否则视为多候选冲突，抛
``ValueError`` 并列出候选，要求用户缩小条件。
"""
from __future__ import annotations

import re
from functools import lru_cache

from cifkit.types import FetchedStructure, SourceQuery, StructureRecord, TaskSpec

from cifkit.sources.aflow import AFLOWSource
from cifkit.sources.cod import CODSource
from cifkit.sources.core_mof import CoreMOFSource
from cifkit.sources.local import LocalSource
from cifkit.sources.materials_project import MaterialsProjectSource, api_key as mp_api_key, key_source as mp_key_source
from cifkit.sources.qmof import QMOFSource, qmof_available

__all__ = [
    "SourceQuery",
    "StructureRecord",
    "FetchedStructure",
    "available_sources",
    "source_status",
    "get_source",
    "pick_source",
    "resolve",
]

_SOURCE_TYPES: dict[str, type] = {
    "core-mof": CoreMOFSource,
    "cod": CODSource,
    "local": LocalSource,
    "materials-project": MaterialsProjectSource,
    "aflow": AFLOWSource,
    "qmof": QMOFSource,
}

_ALIASES = {
    "core-mof": "core-mof",
    "core_mof": "core-mof",
    "coremof": "core-mof",
    "core-mof-2024": "core-mof",
    "core-mof-2019": "core-mof",
    "coREMOF": "core-mof",
    "cod": "cod",
    "crystallography-open-database": "cod",
    "crystallographyopendatabase": "cod",
    "local": "local",
    "file": "local",
    "filesystem": "local",
    "materials-project": "materials-project",
    "materials_project": "materials-project",
    "materialsproject": "materials-project",
    "mp": "materials-project",
    "materialsproject.org": "materials-project",
    "aflow": "aflow",
    "aflowlib": "aflow",
    "aflow.org": "aflow",
    "aflowlib.duke.edu": "aflow",
    "qmof": "qmof",
    "qmof-database": "qmof",
    "qmof_database": "qmof",
    "quantum-mof-database": "qmof",
}

_MP_ID_RE = re.compile(r"^mp-\d+$")
_COD_ID_RE = re.compile(r"^\d{7}$")
_LOCAL_SUFFIXES = (".cif", ".mmcif", ".mcif")


def _canonical(name: str) -> str:
    key = str(name or "").strip()
    if not key:
        raise ValueError(f"数据源名不能为空；可用：{sorted(_SOURCE_TYPES)}")
    lowered = key.lower()
    if lowered in _SOURCE_TYPES:
        return lowered
    if lowered in _ALIASES:
        return _ALIASES[lowered]
    raise ValueError(f"未知数据源 {name!r}；可用数据源：{sorted(_SOURCE_TYPES)}")


def available_sources() -> dict[str, str]:
    """Return ``{source_name: human description}``."""
    return {name: cls.description for name, cls in _SOURCE_TYPES.items()}


def source_status() -> list[dict]:
    """Structured source list for the ``cifkit sources`` command / agent selection."""
    rows: list[dict] = []
    for name, cls in _SOURCE_TYPES.items():
        requires = bool(getattr(cls, "requires_auth", False))
        row = {
            "name": name,
            "description": cls.description,
            "requires_auth": requires,
            "auth_hint": getattr(cls, "auth_hint", ""),
            "available": True,
            "status": "ready",
        }
        if name == "materials-project":
            row["available"] = bool(mp_api_key())
            row["status"] = f"key set via {mp_key_source()}" if row["available"] else "missing MP_API_KEY"
        elif name == "qmof":
            row["available"] = bool(qmof_available())
            row["status"] = (
                "local mirror ready"
                if row["available"]
                else "local mirror missing (set CIFKIT_QMOF_DIR; figshare/GitHub unreachable here)"
            )
        elif name == "core-mof":
            try:
                from cifkit.sources.core_mof import zip_path

                row["available"] = zip_path().is_file()
                row["status"] = "cache ready" if row["available"] else "cache missing (run scripts/bootstrap_data.py)"
            except Exception:  # noqa: BLE001
                row["available"] = False
                row["status"] = "cache check failed"
        rows.append(row)
    return rows


@lru_cache(maxsize=None)
def _instance_for(canonical: str):
    return _SOURCE_TYPES[canonical]()


def get_source(name: str):
    """Return a source adapter instance by name (``core-mof``, ``cod``, ``local`` ...).

    别名（``core_mof`` / ``core-mof-2024`` / ``file`` ...）会归一化到同一个单例。
    """
    return _instance_for(_canonical(name))


def _pick_source(spec: TaskSpec) -> str:
    explicit = str(spec.source or "auto").strip()
    if explicit.lower() not in ("", "auto"):
        return _canonical(explicit)

    structure_id = str(spec.structure_id or "").strip()
    if structure_id:
        if structure_id.lower().endswith(_LOCAL_SUFFIXES):
            return "local"
        if _COD_ID_RE.match(structure_id):
            return "cod"
        if _MP_ID_RE.match(structure_id):
            return "materials-project"
        if structure_id.startswith(("aflow:", "AFLOWDATA/")) or "AFLOWDATA" in structure_id or "aflowlib" in structure_id:
            return "aflow"
    if spec.topology:
        return "core-mof"
    if spec.structure_name:
        # A plain inorganic formula (GaN / NaCl / Fe2O3) is usually an AFLOW/MP target;
        # MOF names (ZIF-8, UiO-66, HKUST-1) never parse as a Composition, so they
        # still go to core-mof.
        if _looks_like_formula(spec.structure_name):
            return "aflow"
        return "core-mof"
    raise ValueError(
        "无法确定数据源：spec 里没有 topology / structure_name / structure_id，也没有显式 source。"
        "请给出要检索的拓扑（如 sod）、结构名（如 ZIF-8 / GaN）或文件/COO/MP/AFLOW id。"
    )


def _looks_like_formula(name: str) -> bool:
    """True for a parseable chemical formula; MOF names (ZIF-8/UiO-66) return False."""
    text = str(name or "").strip().replace(" ", "")
    if not text:
        return False
    try:
        from pymatgen.core import Composition

        comp = Composition(text)
        return bool(comp.elements) and comp.reduced_formula != "None"
    except Exception:  # noqa: BLE001 - not a formula
        return False


def pick_source(spec: TaskSpec) -> str:
    """Public wrapper: decide which adapter ``spec`` should use (see module docstring)."""
    return _pick_source(spec)


def _query_for(spec: TaskSpec, source_name: str) -> SourceQuery:
    return SourceQuery(
        topology=spec.topology,
        typical=bool(spec.typical),
        # "需要碳上补充氢" => 优先拿需要修复的原始结构
        prefer_raw=bool(spec.repair_h),
        structure_name=spec.structure_name,
        structure_id=spec.structure_id,
        # resolve 只需要"确定性第一条"+ 少量候选用于消歧；原始结构每条都要做
        # topology.verify，取太多会不必要地变慢。
        limit=3,
        source=source_name,
        extra={"repair_h": bool(spec.repair_h)},
    )


def _select_hit(hits: list[StructureRecord], query: SourceQuery, source_name: str) -> tuple[StructureRecord, str]:
    if not hits:
        raise ValueError(
            f"数据源 {source_name} 无命中：topology={query.topology!r}、structure_name={query.structure_name!r}、"
            f"structure_id={query.structure_id!r}、prefer_raw={query.prefer_raw}"
        )
    if len(hits) == 1:
        return hits[0], "single candidate"
    disambiguated = bool(query.typical or query.prefer_raw or query.structure_name or query.structure_id)
    if disambiguated:
        reasons = []
        if query.typical:
            reasons.append("typical=True 取最典型候选")
        if query.prefer_raw:
            reasons.append("prefer_raw=True 优先原始（需修复）结构")
        if query.structure_name:
            reasons.append(f"structure_name={query.structure_name!r}")
        if query.structure_id:
            reasons.append(f"structure_id={query.structure_id!r}")
        return hits[0], f"{len(hits)} 个候选，按确定性排序取第一条（{'; '.join(reasons)}）"
    candidates = [hit.record_id for hit in hits[:8]]
    raise ValueError(
        f"数据源 {source_name} 命中 {len(hits)} 个候选，无法唯一确定：{candidates}。"
        "请提供更具体的 topology/structure_name/structure_id，或显式指定 source。"
    )


def resolve(spec: TaskSpec) -> FetchedStructure:
    """Search + fetch the structure requested by ``spec``; raise on ambiguity."""
    source_name = _pick_source(spec)
    source = get_source(source_name)
    query = _query_for(spec, source_name)
    hits = source.search(query)
    chosen, selection_rule = _select_hit(hits, query, source_name)
    fetched = source.fetch(chosen)
    provenance = dict(fetched.provenance or {})
    provenance["resolution"] = {
        "requested_source": spec.source,
        "resolved_source": source_name,
        "query": {
            "topology": query.topology,
            "typical": query.typical,
            "prefer_raw": query.prefer_raw,
            "structure_name": query.structure_name,
            "structure_id": query.structure_id,
            "limit": query.limit,
        },
        "n_hits": len(hits),
        "candidates": [hit.record_id for hit in hits[:10]],
        "selected": chosen.record_id,
        "selection_rule": selection_rule,
    }
    fetched.provenance = provenance
    return fetched
