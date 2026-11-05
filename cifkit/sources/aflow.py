"""AFLOW 适配器：AFLUX 检索 + 直接从 aflowlib 目录取 CIF（无需 API key）。

AFLOW 与 CoRE/COD 的差异（经验，见 ``docs/SOURCES.md``）：

* 免 key；覆盖大量 **无机/金属/合金** 计算结构（ICSD_WEB + LIB1/2/3），MOF 极少。
* 没有 RCSR 拓扑元数据 → 记录一律 ``topology_evidence="unknown"``，需要拓扑断言时
  用 ``cifkit.topology.verify`` 做结构比对。
* 检索走 AFLUX：``https://aflow.org/API/aflux/?species(Zn,O),nspecies(2),paging(0,N)``
  （``paging`` 时返回 ``{"1 of 289": {...}}`` 形式的字典，本适配器兼容 dict/list）。
* 下载走 aflowlib 文件 API：``{aurl}/?files`` 列文件，CIF 文件名形如
  ``<system>.<entry>.cif``；文件名里的 ``:`` 必须 URL-encode（``%3A``）才能下载。
* ``aurl`` 形如 ``aflowlib.duke.edu:AFLOWDATA/LIB1_WEB/Zn:PAW_PBE:06Sep2000/A9``；
  也接受完整 ``https://aflowlib.duke.edu/...`` URL。
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from cifkit.cache import cache_dir
from cifkit.sources._cifutil import file_sha256, header_meta, sha256_bytes, structure_from_bytes
from cifkit.sources.base import count_hydrogen, expected_hydrogen, expected_hydrogen as _eh
from cifkit.types import FetchedStructure, SourceQuery, StructureRecord

AFLUX_URL = "https://aflow.org/API/aflux/"
AFLOW_HOST = "aflowlib.duke.edu"
AFLOUDATA_BASE = "https://aflowlib.duke.edu"
_USER_AGENT = "cifkit/0.1 (CIF workbench; AFLOW adapter; python-urllib)"
_LICENSE_NOTE = "AFLOW usage terms（https://aflow.org/）；再分发/发表前请自行确认许可，本工具不替用户做版权判断"
_REQUEST_TEXT = None  # test hook: callable(url) -> bytes


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def aflow_available(timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection((AFLOW_HOST, 443), timeout=timeout):
            return True
    except OSError:
        return False


def _http_get(url: str, *, timeout: float = 60.0, retries: int = 2) -> bytes:
    if _REQUEST_TEXT is not None:  # test hook
        return _REQUEST_TEXT(url)
    last: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "*/*"})
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed AFLOW hosts
                return response.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (400, 403, 404):
                raise
            time.sleep(2.0 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"AFLOW 请求失败：{url}（{type(last).__name__}: {last}）") from last


def aflow_cache_dir() -> Path:
    return cache_dir("aflow")


# ---------------------------------------------------------------------------
# aurl / AFLUX helpers
# ---------------------------------------------------------------------------
def normalize_aurl(value: str) -> str:
    """Return a fetchable base URL for an AFLOW aurl / URL / ``aflowlib.duke.edu:...``."""
    text = str(value or "").strip().rstrip("/")
    if not text:
        raise ValueError("AFLOW aurl 不能为空")
    if text.startswith(("http://", "https://")):
        return text
    if text.startswith(AFLOW_HOST + ":"):
        return AFLOUDATA_BASE + "/" + text[len(AFLOW_HOST) + 1:]
    if text.startswith("AFLOWDATA/"):
        return AFLOUDATA_BASE + "/" + text
    raise ValueError(
        f"无法识别的 AFLOW aurl：{value!r}。支持：完整 URL、'{AFLOW_HOST}:AFLOWDATA/...'，"
        "或先用 --name <化学式> 检索列表。"
    )


def _formula_query(name: str) -> str | None:
    """Turn a chemical formula (``GaN``, ``Fe2O3``) into an AFLUX species query."""
    text = str(name or "").strip().replace(" ", "")
    if not text:
        return None
    try:
        from pymatgen.core import Composition

        comp = Composition(text)
    except Exception:  # noqa: BLE001 - not a formula (e.g. ZIF-8)
        return None
    elements = sorted(el.symbol for el in comp.elements)
    if not elements:
        return None
    return f"species({','.join(elements)}),nspecies({len(elements)})"


def _parse_aflux(payload: bytes) -> list[dict[str, Any]]:
    try:
        data = json.loads(payload.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("AFLUX 返回的不是 JSON（检查查询语法）") from exc
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        # paging(0,N) returns {"1 of 289": {...}, "2 of 289": {...}}
        rows = list(data.values())
    else:
        raise RuntimeError(f"AFLUX 返回结构异常（{type(data).__name__}）")
    return [row for row in rows if isinstance(row, dict)]


def _record_from_row(row: dict[str, Any], *, limit: int = 10) -> StructureRecord:
    aurl = str(row.get("aurl") or "").strip()
    auid = str(row.get("auid") or "").strip()
    compound = str(row.get("compound") or "").strip() or None
    from cifkit.sources._cifutil import parse_formula

    formula_dict = parse_formula(compound) if compound else {}
    natoms = int(round(sum(formula_dict.values()))) if formula_dict else None
    if auid:
        record_id = auid if auid.startswith("aflow:") else f"aflow:{auid}"
    else:
        record_id = f"aflow:{_aurl_slug(aurl)}"
    return StructureRecord(
        record_id=record_id,
        source="aflow",
        formula=compound,
        topology=None,
        topology_evidence="unknown",
        refcode=auid or None,
        coreid=None,
        doi=None,
        variant="computation-ready",
        natoms=natoms,
        h_count=int(round(formula_dict.get("H", 0.0))) if formula_dict else None,
        h_expected=None,  # inorganic/DFT structures: the organic H-budget heuristic does not apply
        path=None,
        url=normalize_aurl(aurl) if aurl else None,
        sha256=None,
        notes=[
            "AFLOW 覆盖无机/金属/合金计算结构（MOF 很少），没有 RCSR 拓扑元数据；"
            "拓扑断言需 cifkit.topology.verify 结构比对",
            "AFLOW 结构是 DFT 弛豫结果（通常不含 H/无序），一般不需要补氢/修无序",
            f"文件来源 aurl={aurl or '?'}",
        ],
        extra={
            "aurl": aurl,
            "auid": auid,
            "aflow_compound": compound,
            "spacegroup_relax": row.get("spacegroup_relax"),
            "Pearson_symbol_relax": row.get("Pearson_symbol_relax"),
            "species": row.get("species"),
            "license": _LICENSE_NOTE,
            "cache_reused": False,
        },
    )


def _aurl_slug(aurl: str) -> str:
    text = str(aurl or "").strip().rstrip("/")
    for prefix in (AFLOUDATA_BASE + "/", "https://aflowlib.duke.edu/", "http://aflowlib.duke.edu/"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.replace(":", "-").replace("/", "_") or "unknown"


def _pick_cif_name(files: list[str], aurl: str) -> str | None:
    """Choose the primary (non-symmetrized) CIF from an AFLOW entry file list."""
    cifs = [str(name) for name in files if str(name).lower().endswith(".cif")]
    if not cifs:
        return None
    path = urllib.parse.urlparse(aurl if "://" in aurl else "https://" + aurl).path
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2:
        expected = f"{parts[-2]}.{parts[-1]}.cif"
        for name in cifs:
            if name == expected:
                return name
    preferred = [name for name in cifs if not any(tag in name for tag in ("_sprim", "_sconv", "_corner"))]
    pool = preferred or cifs
    return sorted(pool, key=len)[0]


class AFLOWSource:
    """AFLOW source adapter (no API key needed)."""

    name = "aflow"
    description = "AFLOW（无机/合金计算结构，免 key；无 RCSR 拓扑元数据）"
    requires_auth = False
    auth_hint = "无需 key"

    def search(self, query: SourceQuery) -> list[StructureRecord]:
        limit = max(1, int(query.limit or 10))
        identifier = str(query.structure_id or "").strip()
        if identifier:
            if identifier.startswith("aflow:") or identifier.lower().startswith(("aflowlib.duke.edu:", "aflowdata/")):
                if identifier.startswith("aflow:") and "AFLOWDATA" not in identifier:
                    raise ValueError(
                        f"AFLOW 的 auid（{identifier}）不能直接检索；请改传 aurl/URL"
                        "（形如 'aflowlib.duke.edu:AFLOWDATA/.../A9'），或用 --name <化学式> 检索。"
                    )
                aurl = identifier
                record = _record_from_row({"aurl": aurl})
                record.notes.append("直接按 aurl 指定条目（未走 AFLUX 元数据检索）")
                return [record]
            # full URL to an AFLOW entry directory
            if identifier.startswith(("http://", "https://")) and "AFLOWDATA" in identifier:
                record = _record_from_row({"aurl": identifier})
                record.notes.append("直接按 URL 指定条目（未走 AFLUX 元数据检索）")
                return [record]
            raise ValueError(
                f"AFLOW 结构 id 需为 aurl/URL（形如 'aflowlib.duke.edu:AFLOWDATA/.../A9'），"
                f"收到 {identifier!r}"
            )

        if query.topology:
            return []  # AFLOW has no RCSR topology metadata

        name = str(query.structure_name or query.extra.get("formula") or "").strip()
        if not name:
            return []
        aflux = _formula_query(name)
        if not aflux:
            return []
        url = f"{AFLUX_URL}?{aflux},paging(0,{limit})"
        rows = _parse_aflux(_http_get(url))
        records = [_record_from_row(row) for row in rows[:limit]]
        for rec in records:
            rec.notes.append(f"按 AFLUX 查询 {aflux!r} 检索（从名称 {name!r} 解析）")
        return records

    def fetch(self, record: StructureRecord) -> FetchedStructure:
        aurl = str(record.extra.get("aurl") or "").strip()
        if not aurl:
            raise ValueError(f"AFLOW 记录 {record.record_id!r} 缺少 aurl")
        base = normalize_aurl(aurl)
        files_payload = _http_get(base + "/?files")
        try:
            files = json.loads(files_payload.decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"AFLOW 文件列表不是 JSON：{base}/?files") from exc
        if not isinstance(files, list):
            raise RuntimeError(f"AFLOW 文件列表格式异常（{type(files).__name__}）：{base}")
        cif_name = _pick_cif_name([str(x) for x in files], base)
        if not cif_name:
            raise ValueError(f"AFLOW 条目 {base} 没有 CIF 文件；可用文件：{files[:20]}")
        # ':' in the file name must be percent-encoded or the server 404s
        cif_url = f"{base}/{urllib.parse.quote(cif_name, safe='')}"
        data = _http_get(cif_url)
        if b"data_" not in data[:4096] and b"_cell_length_a" not in data[:8192]:
            raise ValueError(f"AFLOW 返回的内容不是 CIF：{cif_url}（{len(data)} bytes）")
        structure = structure_from_bytes(data, label=f"AFLOW {cif_name}")
        out = aflow_cache_dir()
        out.mkdir(parents=True, exist_ok=True)
        slug = _aurl_slug(base)
        cif_path = out / f"{slug}.cif"
        cif_path.write_bytes(data)
        digest = sha256_bytes(data)
        record.path = str(cif_path)
        record.sha256 = digest
        record.natoms = len(structure)
        record.formula = structure.composition.formula
        record.h_count = count_hydrogen(structure)
        record.h_expected = None  # inorganic/DFT; not an organic H-deficiency judgement
        record.variant = "computation-ready"
        provenance = {
            "source": "aflow",
            "record_id": record.record_id,
            "aurl": base,
            "auid": record.extra.get("auid"),
            "cif_file": cif_name,
            "url": cif_url,
            "license": _LICENSE_NOTE,
            "sha256": digest,
            "cif_sha256": digest,
            "cif_path": str(cif_path),
            "cache_reused": False,
            "fetched_at": now(),
            "topology_evidence": "unknown",
            "topology_note": "AFLOW 无 RCSR 拓扑元数据；拓扑断言需 cifkit.topology.verify",
            "h_count": record.h_count,
        }
        return FetchedStructure(structure=structure, record=record, provenance=provenance)
