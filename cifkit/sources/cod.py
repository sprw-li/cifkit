"""Crystallography Open Database (COD) 适配器：检索 / 下载 / 缓存。

COD 的 REST 检索接口::

    https://www.crystallography.net/cod/result?text=<query>&format=json
    https://www.crystallography.net/cod/<id>.cif

用途：核心库（CoRE）没有名字/拓扑元数据时的兜底；COD **没有拓扑列**，所以由这里返回
的记录一律 ``topology_evidence="unknown"``，拓扑必须再由 ``cifkit.topology.verify``
做结构比对。

网络行为：默认 30 s 超时、3 次重试；下载的 CIF 缓存在 ``_cache/cod/<id>.cif``，
重复请求直接命中缓存（``cache_reused=True``，hash 可复核）。COD 数据为公有领域，
详见 https://www.crystallography.net/cod/ 使用条款。
"""
from __future__ import annotations

import json
import os
from dataclasses import replace
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from cifkit.cache import cache_dir
from cifkit.sources._cifutil import (
    file_sha256,
    header_meta,
    parse_formula,
    sha256_bytes,
    structure_from_bytes,
)
from cifkit.sources.http import HttpClient, HttpError
from cifkit.sources.base import count_hydrogen, expected_hydrogen
from cifkit.types import FetchedStructure, SourceQuery, StructureRecord

BASE_URL = "https://www.crystallography.net/cod"
RESULT_URL = BASE_URL + "/result"
CIF_URL = BASE_URL + "/{cod_id}.cif"
COD_LICENSE = "COD data are in the public domain (see https://www.crystallography.net/cod/ terms)"
COD_HOST = "www.crystallography.net"
_USER_AGENT = "cifkit/0.1 (CIF workbench; structure retrieval; python-urllib)"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def cod_available(timeout: float = 5.0) -> bool:
    """Cheap network probe used by tests / callers to decide whether to try COD."""
    try:
        with socket.create_connection((COD_HOST, 443), timeout=timeout):
            return True
    except OSError:
        return False


#: shared client: exponential backoff + Retry-After + pacing (see cifkit.sources.http).
#: min_interval defaults to 0.25 s between requests to the same host so a batch
#: fetch does not hammer a public database; override with the env var (0 disables).
_HTTP = HttpClient(user_agent=_USER_AGENT, retries=3, base_backoff=1.5, max_backoff=30.0,
                   min_interval=float(os.environ.get("CIFKIT_COD_MIN_INTERVAL", "0.25")))


def _http_get(url: str, *, timeout: float = 30.0, retries: int = 3) -> bytes:
    """GET with retries; pacing/backoff/Retry-After live in :class:`HttpClient`."""
    client = _HTTP if retries == _HTTP.retries else replace(_HTTP, retries=retries)
    try:
        return client.get(url, timeout=timeout)
    except HttpError as exc:
        raise RuntimeError(f"COD 请求失败：{url}（HTTP {exc.status}）") from exc


def cod_cache_dir() -> Path:
    return cache_dir("cod")


def cod_cache_path(cod_id: str) -> Path:
    return cod_cache_dir() / f"{cod_id}.cif"


def _ensure_cif(cod_id: str, *, refresh: bool = False) -> tuple[Path, bool]:
    """Download (or reuse cache) the COD CIF; return ``(path, cache_reused)``."""
    path = cod_cache_path(cod_id)
    if path.is_file() and not refresh:
        return path, True
    url = CIF_URL.format(cod_id=cod_id)
    try:
        data = _http_get(url)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"COD 记录 {cod_id} 不存在或不可下载（HTTP {exc.code}）：{url}") from exc
    if b"data_" not in data[:2048] and b"_cell_length_a" not in data[:8192]:
        raise ValueError(f"COD 返回的内容不是 CIF（{url}，{len(data)} bytes）")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path, False


def _record_from_header(cod_id: str, path: Path, *, cache_reused: bool, url: str | None = None) -> StructureRecord:
    text = path.read_bytes()[:8192].decode("utf-8", "replace")
    meta = header_meta(text)
    formula = meta["formula_dict"]
    h_count = int(round(formula.get("H", 0.0))) if formula else None
    natoms = int(round(sum(formula.values()))) if formula else None
    h_expected = round(expected_hydrogen(formula), 1) if formula else None
    deficient = h_count is not None and h_expected is not None and h_count + 0.5 < h_expected
    # 只有"确实没有任何 H"才标 raw；经验估计偏保守，不足以断言 COD 记录需要补氢
    variant = "raw" if h_count == 0 else "unknown"
    return StructureRecord(
        record_id=f"cod:{cod_id}",
        source="cod",
        formula=meta["formula"],
        topology=None,
        topology_evidence="unknown",
        refcode=cod_id,
        coreid=None,
        doi=None,
        variant=variant,
        natoms=natoms,
        h_count=h_count,
        h_expected=h_expected,
        path=str(path),
        url=url or CIF_URL.format(cod_id=cod_id),
        sha256=file_sha256(path),
        notes=[
            "COD 记录没有拓扑元数据；拓扑必须由 cifkit.topology.verify 结构比对核实（evidence 不会标 metadata）",
            "COD 数据为公有领域（public domain），见 COD 使用条款",
            f"h_count={h_count} 为头部 _chemical_formula_sum 的计数；H 期望值 {h_expected} 仅为经验估计（base.expected_hydrogen），非实测",
        ],
        extra={
            "cod_id": cod_id,
            "cod_url": CIF_URL.format(cod_id=cod_id),
            "license": COD_LICENSE,
            "cache_reused": cache_reused,
            "h_deficient_estimate": bool(deficient),
        },
    )


def _clean_formula(formula: str | None) -> str | None:
    if not formula:
        return None
    text = str(formula).strip().strip("-").strip()
    return text or None


def _search_json(text: str, limit: int) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"text": text, "format": "json"})
    url = f"{RESULT_URL}?{params}"
    try:
        payload = _http_get(url)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"COD 检索失败（HTTP {exc.code}）：{url}") from exc
    try:
        data = json.loads(payload.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"COD 检索返回的不是 JSON：{url}") from exc
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise RuntimeError(f"COD 检索返回结构异常（{type(data).__name__}）：{url}")
    return [row for row in data[: max(limit * 3, limit)] if isinstance(row, dict)]


class CODSource:
    """Crystallography Open Database source adapter."""

    name = "cod"
    description = "Crystallography Open Database（下载 CIF；无拓扑元数据，拓扑需结构比对）"

    def search(self, query: SourceQuery) -> list[StructureRecord]:
        limit = max(1, int(query.limit or 10))
        identifier = str(query.structure_id or "").strip()
        if identifier:
            records: list[StructureRecord] = []
            for cod_id in identifier.split(","):
                cod_id = cod_id.strip()
                if not cod_id:
                    continue
                if not cod_id.isdigit():
                    raise ValueError(f"COD 结构 id 必须是数字（形如 7111973），收到 {cod_id!r}")
                path, reused = _ensure_cif(cod_id)
                records.append(_record_from_header(cod_id, path, cache_reused=reused))
                if len(records) >= limit:
                    break
            return records

        text = str(query.structure_name or query.extra.get("text") or "").strip()
        if not text:
            if query.topology:
                # COD 没有拓扑元数据，无法按拓扑检索
                return []
            return []
        rows = _search_json(text, limit)
        records = []
        for row in rows:
            cod_id = str(row.get("file") or row.get("id") or "").strip()
            if not cod_id.isdigit():
                continue
            formula = _clean_formula(row.get("formula") or row.get("calcformula") or row.get("cellformula"))
            formula_dict = parse_formula(formula)
            h_count = int(round(formula_dict.get("H", 0.0))) if formula_dict else None
            natoms = int(round(sum(formula_dict.values()))) if formula_dict else None
            h_expected = round(expected_hydrogen(formula_dict), 1) if formula_dict else None
            deficient = h_count is not None and h_expected is not None and h_count + 0.5 < h_expected
            notes = [
                "COD 记录没有拓扑元数据；拓扑必须由 cifkit.topology.verify 结构比对核实",
                "COD 数据为公有领域（public domain）",
            ]
            title = str(row.get("title") or "").strip()
            if title and title != "?":
                notes.append(f"COD 标题：{title[:160]}")
            records.append(
                StructureRecord(
                    record_id=f"cod:{cod_id}",
                    source="cod",
                    formula=formula,
                    topology=None,
                    topology_evidence="unknown",
                    refcode=cod_id,
                    doi=str(row.get("doi") or "").strip() or None,
                    # 只有"确实没有任何 H"才标 raw；经验估计不足以断言需要补氢
                    variant="raw" if h_count == 0 else "unknown",
                    natoms=natoms,
                    h_count=h_count,
                    h_expected=h_expected,
                    path=None,
                    url=CIF_URL.format(cod_id=cod_id),
                    sha256=None,
                    notes=notes,
                    extra={
                        "cod_id": cod_id,
                        "cod_url": CIF_URL.format(cod_id=cod_id),
                        "cod_meta": {
                            key: row.get(key)
                            for key in ("commonname", "chemname", "authors", "year", "journal", "doi", "sg", "vol")
                            if row.get(key)
                        },
                        "license": COD_LICENSE,
                        "cache_reused": False,
                        "h_deficient_estimate": bool(deficient),
                    },
                )
            )
            if len(records) >= limit:
                break
        return records

    def fetch(self, record: StructureRecord) -> FetchedStructure:
        cod_id = str(record.extra.get("cod_id") or record.record_id.split(":")[-1]).strip()
        if not cod_id.isdigit():
            raise ValueError(f"COD 记录 {record.record_id!r} 缺少合法的 cod_id")
        path, reused = _ensure_cif(cod_id)
        data = path.read_bytes()
        digest = sha256_bytes(data)
        structure = structure_from_bytes(data, label=f"COD {cod_id}")
        record.path = str(path)
        record.sha256 = digest
        record.h_count = count_hydrogen(structure)
        record.natoms = len(structure)
        record.formula = structure.composition.formula
        provenance = {
            "source": "cod",
            "record_id": record.record_id,
            "cod_id": cod_id,
            "cod_url": CIF_URL.format(cod_id=cod_id),
            "url": CIF_URL.format(cod_id=cod_id),
            "lifecycle_url": RESULT_URL,
            "license": COD_LICENSE,
            "sha256": digest,
            "cif_path": str(path),
            "cache_reused": bool(reused),
            "fetched_at": now(),
            "topology_evidence": "unknown",
            "topology_note": "COD 无拓扑元数据；拓扑需 cifkit.topology.verify 结构比对，本记录未做拓扑断言",
        }
        return FetchedStructure(structure=structure, record=record, provenance=provenance)
