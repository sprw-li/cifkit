"""Materials Project (MP) 适配器：按 material_id / 化学式检索并下载结构。

与 CoRE/COD 的差异（经验，见 ``docs/SOURCES.md``）：

* MP 需要 API key（https://materialsproject.org/api 免费注册）。设置环境变量
  ``MP_API_KEY``（或旧名 ``PMG_MAPI_KEY``）；本模块不会把 key 写进缓存/日志。
* MP 的结构是 **DFT 计算结构**（通常已含 H、无部分占据、无序已被处理），
  因此不适合演示"补氢/修无序"；要那种原始 CIF 请用 CoRE MOF 的 NCR 或 COD。
* MP 没有 RCSR 拓扑元数据 → 本适配器返回的记录 ``topology_evidence="unknown"``，
  需要拓扑断言时由 ``cifkit.topology.verify`` 做结构比对。
* API 返回的是 pymatgen structure dict，不是 deposited CIF；写盘时会生成 CIF 并
  在 provenance 里注明 ``cif_generated=True`` 与 JSON 的 sha256（两者都记录）。

REST 端点（2024+ 版本）::

    GET https://api.materialsproject.org/materials/summary/?material_ids=mp-149
        &_fields=material_id,formula_pretty,structure,...
        Header: X-API-KEY: <key>
"""
from __future__ import annotations

import json
import os
from dataclasses import replace
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from cifkit.cache import cache_dir
from cifkit.sources._cifutil import file_sha256, sha256_bytes
from cifkit.sources.http import HttpClient, HttpError
from cifkit.sources.base import count_hydrogen, expected_hydrogen
from cifkit.types import FetchedStructure, SourceQuery, StructureRecord

DEFAULT_HOST = "https://api.materialsproject.org"
KEY_ENVS = ("MP_API_KEY", "PMG_MAPI_KEY")
MP_ID_RE = re.compile(r"^mp-\d+$")
_MP_HOST = "api.materialsproject.org"
_USER_AGENT = "cifkit/0.1 (CIF workbench; Materials Project adapter; python-urllib)"
_SELECT_FIELDS = "material_id,formula_pretty,chemsys,spacegroup,nsites,is_stable,is_metal"
_LICENSE_NOTE = (
    "Materials Project usage terms（https://materialsproject.org/）；"
    "再分发/发表前请自行确认许可，本工具不替用户做版权判断"
)
#: tests monkeypatch this hook instead of the network
_REQUEST_JSON = None


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def api_key() -> str | None:
    import os

    for env in KEY_ENVS:
        value = str(os.environ.get(env) or "").strip()
        if value:
            return value
    return None


def key_source() -> str | None:
    import os

    for env in KEY_ENVS:
        if str(os.environ.get(env) or "").strip():
            return env
    return None


def mp_available(timeout: float = 5.0) -> bool:
    """Cheap network probe (host reachable). Key presence is checked separately."""
    try:
        with socket.create_connection((_MP_HOST, 443), timeout=timeout):
            return True
    except OSError:
        return False


def _require_key() -> str:
    key = api_key()
    if key:
        return key
    raise ValueError(
        "Materials Project 需要 API key：请到 https://materialsproject.org/api 免费申请，然后设置环境变量 "
        f"{' 或 '.join(KEY_ENVS)}（PowerShell: $env:MP_API_KEY='...'）。"
        "不想用 key 时请改用 --source core-mof / cod / aflow。"
    )


#: shared client: exponential backoff + Retry-After + pacing (see cifkit.sources.http).
#: min_interval defaults to 0.25 s between requests to the same host so a batch
#: fetch does not hammer a public database; override with the env var (0 disables).
_HTTP = HttpClient(user_agent=_USER_AGENT, retries=2, base_backoff=1.5, max_backoff=30.0,
                   min_interval=float(os.environ.get("CIFKIT_MP_MIN_INTERVAL", "0.25")))


def _http_json(path: str, params: dict[str, Any] | None = None, *, timeout: float = 40.0,
               retries: int = 2, host: str = DEFAULT_HOST) -> dict:
    key = _require_key()
    if _REQUEST_JSON is not None:  # test hook
        return _REQUEST_JSON(path, params or {}, key)
    query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
    url = f"{host.rstrip('/')}{path}" + (f"?{query}" if query else "")
    client = _HTTP if retries == _HTTP.retries else replace(_HTTP, retries=retries)
    try:
        return client.get_json(url, headers={"X-API-KEY": key, "Accept": "application/json"},
                               timeout=timeout)
    except HttpError as exc:
        body = exc.body or ""
        if exc.status in (401, 403):
            raise ValueError(
                f"Materials Project 拒绝了请求（HTTP {exc.status}）：API key 无效或没有权限。"
                f"请在 https://materialsproject.org/api 检查 key。{(' body=' + body) if body else ''}"
            ) from exc
        if exc.status == 400:
            raise
        raise RuntimeError(
            f"Materials Project 请求失败：{url}（HTTP {exc.status}, {exc.attempts} 次尝试）"
        ) from exc


def mp_cache_dir() -> Path:
    return cache_dir("materials-project")


def _summary_rows(params: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    payload = _http_json("/materials/summary/", {**params, "_limit": limit, "_fields": _SELECT_FIELDS})
    if not isinstance(payload, dict):
        raise RuntimeError(f"Materials Project 返回结构异常（{type(payload).__name__}）")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise RuntimeError("Materials Project 返回 JSON 缺少 data 列表")
    return [row for row in rows if isinstance(row, dict)]


def _structure_dict(row: dict[str, Any]) -> dict[str, Any] | None:
    structure = row.get("structure")
    return structure if isinstance(structure, dict) else None


def _record_from_row(row: dict[str, Any], *, cache_reused: bool = False) -> StructureRecord:
    mid = str(row.get("material_id") or "").strip()
    formula = str(row.get("formula_pretty") or row.get("formula") or "").strip() or None
    nsites = row.get("nsites")
    structure = _structure_dict(row)
    natoms = int(nsites) if isinstance(nsites, int) else (len(structure.get("sites", [])) if structure else None)
    return StructureRecord(
        record_id=f"mp:{mid}",
        source="materials-project",
        formula=formula,
        topology=None,
        topology_evidence="unknown",
        refcode=mid or None,
        coreid=mid or None,
        doi=None,
        variant="computation-ready",
        natoms=natoms,
        h_count=None,
        h_expected=None,
        path=None,
        url=f"{DEFAULT_HOST}/materials/summary/?material_ids={mid}",
        sha256=None,
        notes=[
            "Materials Project 结构为 DFT 计算结构（通常已含 H、无部分占据），一般不需要补氢/修无序",
            "MP 没有 RCSR 拓扑元数据；拓扑断言需由 cifkit.topology.verify 结构比对",
            "CIF 由 API 返回的 structure dict 生成（不是 deposited CIF），provenance 会记录 JSON sha256",
        ],
        extra={
            "material_id": mid,
            "mp_url": f"https://materialsproject.org/materials/{mid}",
            "spacegroup": row.get("spacegroup"),
            "chemsys": row.get("chemsys"),
            "is_stable": row.get("is_stable"),
            "license": _LICENSE_NOTE,
            "cache_reused": cache_reused,
        },
    )


def _formula_candidates(name: str) -> list[str]:
    """Best-effort parse of a formula-ish name (``GaN``, ``Fe2 O3``) for the MP API."""
    text = str(name or "").strip().replace(" ", "")
    if not text:
        return []
    try:
        from pymatgen.core import Composition

        comp = Composition(text)
        if comp.reduced_formula and comp.reduced_formula != "None":
            return [comp.formula, comp.reduced_formula]
    except Exception:  # noqa: BLE001 - not a formula (e.g. "ZIF-8")
        return []
    return []


class MaterialsProjectSource:
    """Materials Project source adapter (needs ``MP_API_KEY``)."""

    name = "materials-project"
    description = "Materials Project（DFT 结构；需要 MP_API_KEY；无 RCSR 拓扑元数据）"
    requires_auth = True
    auth_hint = "设置环境变量 MP_API_KEY（https://materialsproject.org/api）"

    def search(self, query: SourceQuery) -> list[StructureRecord]:
        limit = max(1, int(query.limit or 10))
        identifier = str(query.structure_id or "").strip()
        if identifier:
            ids = [part.strip() for part in identifier.split(",") if part.strip()]
            bad = [mid for mid in ids if not MP_ID_RE.match(mid)]
            if bad:
                raise ValueError(f"MP 结构 id 必须形如 mp-149，收到 {bad}")
            rows = _summary_rows({"material_ids": ",".join(ids)}, limit=len(ids))
            return [_record_from_row(row) for row in rows]

        if query.topology:
            return []  # MP has no RCSR topology metadata; caller should fall back

        name = str(query.structure_name or query.extra.get("formula") or "").strip()
        if not name:
            return []
        for formula in _formula_candidates(name):
            rows = _summary_rows({"formula": formula}, limit=limit)
            if rows:
                records = [_record_from_row(row) for row in rows]
                for rec in records:
                    rec.notes.append(f"按化学式 {formula!r} 检索（从名称 {name!r} 解析）")
                return records
        return []

    def fetch(self, record: StructureRecord) -> FetchedStructure:
        mid = str(record.extra.get("material_id") or record.record_id.split(":")[-1]).strip()
        if not MP_ID_RE.match(mid):
            raise ValueError(f"MP 记录 {record.record_id!r} 缺少合法的 material_id")
        payload = _http_json(
            "/materials/summary/",
            {"material_ids": mid, "_limit": 1,
             "_fields": "material_id,formula_pretty,chemsys,spacegroup,nsites,is_stable,structure"},
        )
        rows = (payload or {}).get("data") or []
        if not rows:
            raise ValueError(f"Materials Project 没有找到 {mid}")
        row = rows[0]
        struct_dict = _structure_dict(row)
        if struct_dict is None:
            raise ValueError(
                f"Materials Project 返回的 {mid} 没有 structure 字段（可能该条目无结构）；"
                "请换一个 material_id 或改用其它数据源"
            )
        from pymatgen.core import Structure
        from pymatgen.io.cif import CifWriter

        structure = Structure.from_dict(struct_dict)
        out = mp_cache_dir()
        out.mkdir(parents=True, exist_ok=True)
        json_path = out / f"{mid}.mp.json"
        cif_path = out / f"{mid}.cif"
        json_bytes = json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")
        json_path.write_bytes(json_bytes)
        CifWriter(structure, symprec=None).write_file(str(cif_path))
        cif_sha = file_sha256(cif_path)
        record.path = str(cif_path)
        record.sha256 = cif_sha
        record.natoms = len(structure)
        record.formula = structure.composition.formula
        record.h_count = count_hydrogen(structure)
        record.h_expected = round(expected_hydrogen(dict(structure.composition.get_el_amt_dict())), 1)
        record.variant = "computation-ready"
        provenance = {
            "source": "materials-project",
            "record_id": record.record_id,
            "material_id": mid,
            "api_url": f"{DEFAULT_HOST}/materials/summary/?material_ids={mid}",
            "url": f"https://materialsproject.org/materials/{mid}",
            "license": _LICENSE_NOTE,
            "structure_json_sha256": sha256_bytes(json_bytes),
            "sha256": cif_sha,
            "cif_sha256": cif_sha,
            "cif_path": str(cif_path),
            "json_path": str(json_path),
            "cif_generated": True,
            "cif_generated_note": "CIF 由 Materials Project API 的 structure dict 生成（非 deposited CIF）",
            "fetch_mode": "api",
            "cache_reused": False,
            "fetched_at": now(),
            "topology_evidence": "unknown",
            "topology_note": "MP 无 RCSR 拓扑元数据；拓扑断言需 cifkit.topology.verify",
            "h_count": record.h_count,
        }
        return FetchedStructure(structure=structure, record=record, provenance=provenance)
