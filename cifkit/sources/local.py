"""本地 ``.cif`` 文件适配器：用户已有结构 / 测试 fixture 走这里。

本地文件没有数据库元数据，所以 ``topology_evidence`` 永远是 ``unknown``；
拓扑只能由 ``cifkit.topology.verify`` 做结构比对。缺氢判断只用于提示
（``variant="raw"``），真正的补氢由 ``cifkit.repair`` 依据局部价态完成。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from cifkit.sources._cifutil import (
    file_sha256,
    header_meta,
    sha256_bytes,
    structure_from_bytes,
)
from cifkit.sources.base import count_hydrogen, expected_hydrogen
from cifkit.types import FetchedStructure, SourceQuery, StructureRecord

#: 视为 CIF 的扩展名
CIF_SUFFIXES = {".cif", ".mmcif", ".mcif"}


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _coerce_path(raw: str | None) -> Path | None:
    if not raw:
        return None
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        candidate = Path.cwd() / path
        if candidate.is_file():
            path = candidate
    return path


class LocalSource:
    """Local filesystem CIF source adapter."""

    name = "local"
    description = "本地 .cif 文件（用户已有结构；无数据库元数据，拓扑需结构比对）"

    def search(self, query: SourceQuery) -> list[StructureRecord]:
        raw = query.structure_id or query.extra.get("path")
        path = _coerce_path(raw)
        if path is None:
            return []
        if not path.is_file():
            raise ValueError(f"本地 CIF 不存在：{raw}")
        if path.suffix.lower() not in CIF_SUFFIXES:
            raise ValueError(f"本地文件不是 CIF（扩展名 {path.suffix!r}）：{path}")
        text = path.read_bytes()[:8192].decode("utf-8", "replace")
        meta = header_meta(text)
        formula = meta["formula_dict"]
        h_count = int(round(formula.get("H", 0.0))) if formula else None
        natoms = int(round(sum(formula.values()))) if formula else None
        h_expected = round(expected_hydrogen(formula), 1) if formula else None
        deficient = h_count is not None and h_expected is not None and h_count + 0.5 < h_expected
        notes = [
            "本地 CIF 没有数据库拓扑元数据；拓扑必须由 cifkit.topology.verify 结构比对核实",
            "h_expected 为 sources/base.expected_hydrogen 的经验估计（非实测），仅用于标记是否可能缺氢",
        ]
        if h_count == 0:
            notes.append("头部化学式里没有 H：很可能是需要补氢的原始结构（variant=raw）")
        return [
            StructureRecord(
                record_id=f"local:{path}",
                source="local",
                formula=meta["formula"],
                topology=query.topology,
                topology_evidence="unknown",
                refcode=path.stem,
                coreid=None,
                doi=None,
                variant="raw" if deficient or h_count == 0 else "unknown",
                natoms=natoms,
                h_count=h_count,
                h_expected=h_expected,
                path=str(path),
                url=path.as_uri(),
                sha256=file_sha256(path),
                notes=notes,
                extra={
                    "local_path": str(path),
                    "abc": [meta["cell"].get(key) for key in ("a", "b", "c")],
                    "h_deficient_estimate": bool(deficient),
                },
            )
        ]

    def fetch(self, record: StructureRecord) -> FetchedStructure:
        raw_path = record.extra.get("local_path") or record.path
        path = _coerce_path(raw_path)
        if path is None or not path.is_file():
            raise ValueError(f"本地 CIF 不存在：{raw_path}")
        data = path.read_bytes()
        digest = sha256_bytes(data)
        structure = structure_from_bytes(data, label=str(path))
        record.path = str(path)
        record.sha256 = digest
        record.h_count = count_hydrogen(structure)
        record.natoms = len(structure)
        record.formula = structure.composition.formula
        provenance = {
            "source": "local",
            "record_id": record.record_id,
            "url": path.as_uri(),
            "local_path": str(path),
            "sha256": digest,
            "cif_path": str(path),
            "fetched_at": now(),
            "topology_evidence": "unknown",
            "topology_note": "本地文件无拓扑元数据；拓扑需 cifkit.topology.verify 结构比对，本记录未做拓扑断言",
        }
        return FetchedStructure(structure=structure, record=record, provenance=provenance)
