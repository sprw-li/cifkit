"""QMOF (Quantum MOF Database) adapter — local mirror / drop-in data source.

QMOF is a DFT-labelled subset of CoRE/CSD MOFs (Rosen et al.).  Its public
distribution lives on figshare (DOI 10.6084/m9.figshare.13147324) and a GitHub
mirror; both were **unreachable from this environment** (HTTP 403 / timeout), so
this adapter reads a **local mirror** and says so explicitly instead of faking a
live download:

    $CIFKIT_QMOF_DIR=/path/to/qmof
    # or: <cache>/qmof/

Expected layout (either form works)::

    qmof/
      qmof.csv              # metadata: name/refcode, formula, ... (optional but searched)
      structures/*.cif      # one CIF per entry, file stem == name
      # or qmof_cifs.zip / qmof_database.zip containing *.cif entries

If the dataset is absent the adapter reports a clear, actionable error (where to
get the data and which env var to point at); it never silently returns fake
results.  When ``qmof.csv`` is absent the source still works structurally: it
indexes CIF file names and parses formulas on fetch.
"""
from __future__ import annotations

import csv
import json
import os
import zipfile
from pathlib import Path
from typing import Any

from cifkit.cache import cache_dir
from cifkit.sources._cifutil import structure_from_bytes
from cifkit.sources.base import count_hydrogen, sha256_bytes
from cifkit.types import FetchedStructure, SourceQuery, StructureRecord

#: figshare record for the QMOF database (documented, but blocked from this network)
QMOF_DOI = "10.6084/m9.figshare.13147324"
QMOF_URL = "https://figshare.com/articles/dataset/QMOF_Database/13147324"
QMOF_GITHUB = "https://github.com/Andrew-S-Rosen/QMOF"

#: accepted metadata / archive names inside the mirror directory
META_NAMES = ("qmof.csv", "qmof_database.csv", "qmof_metadata.csv")
ZIP_NAMES = ("qmof_cifs.zip", "qmof_database.zip", "qmof.zip")
STRUCT_DIR_NAMES = ("structures", "cifs", "qmof_cifs")


def qmof_dir() -> Path:
    env = os.environ.get("CIFKIT_QMOF_DIR")
    if env:
        return Path(env).expanduser()
    return cache_dir("qmof")


def _meta_file() -> Path | None:
    root = qmof_dir()
    for name in META_NAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def _structure_dir() -> Path | None:
    root = qmof_dir()
    for name in STRUCT_DIR_NAMES:
        candidate = root / name
        if candidate.is_dir():
            return candidate
    return None


def _zip_file() -> Path | None:
    root = qmof_dir()
    for name in ZIP_NAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def qmof_available() -> bool:
    return _meta_file() is not None or _structure_dir() is not None or _zip_file() is not None


def _read_metadata(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _index_from_files() -> list[dict[str, Any]]:
    """Fallback index built from CIF file names / zip entries (no metadata CSV)."""
    entries: list[dict[str, Any]] = []
    structs = _structure_dir()
    if structs is not None:
        for cif in sorted(structs.glob("*.cif")):
            entries.append({"name": cif.stem, "cif": cif.name, "path": str(cif), "kind": "dir"})
    archive = _zip_file()
    if archive is not None:
        with zipfile.ZipFile(archive) as handle:
            for member in handle.namelist():
                if member.endswith(".cif"):
                    entries.append({"name": Path(member).stem, "cif": Path(member).name,
                                    "path": member, "kind": "zip"})
    return entries


def _read_cif(entry: dict[str, Any]) -> bytes:
    if entry.get("kind") == "dir":
        return Path(entry["path"]).read_bytes()
    archive = _zip_file()
    if archive is None:
        raise FileNotFoundError("QMOF zip 不在镜像目录里")
    member = entry.get("path") or entry.get("cif")
    with zipfile.ZipFile(archive) as handle:
        return handle.read(member)


class QMOFSource:
    name = "qmof"
    description = "QMOF 数据库（DFT 标注 MOF；本适配器读取本地镜像，需要用户提供 QMOF 数据）"
    requires_auth = False
    auth_hint = (
        "把 QMOF 数据放到 $CIFKIT_QMOF_DIR（或 _cache/qmof/）：qmof.csv + structures/*.cif "
        f"（官方 figshare DOI {QMOF_DOI}；本环境网络不可达，未实测在线下载）"
    )

    def _ensure(self) -> None:
        if not qmof_available():
            raise FileNotFoundError(
                f"QMOF 本地镜像未找到：{qmof_dir()}。\n"
                f"请从 {QMOF_URL}（DOI {QMOF_DOI}）或 {QMOF_GITHUB} 下载并解压到该目录，"
                "或用环境变量 CIFKIT_QMOF_DIR 指向已有镜像。\n"
                "注意：本适配器只读本地镜像；本环境到 figshare/GitHub 的下载不可达，"
                "因此未做 live 下载实测（不伪造）。"
            )

    def search(self, query: SourceQuery) -> list[StructureRecord]:
        self._ensure()
        meta = _meta_file()
        rows: list[dict[str, Any]]
        if meta is not None:
            rows = [dict(row) for row in _read_metadata(meta)]
            for row in rows:
                row.setdefault("name", row.get("refcode") or row.get("qmof_id") or "")
        else:
            rows = _index_from_files()

        wanted = str(query.structure_name or query.structure_id or "").strip().lower()
        hits: list[StructureRecord] = []
        for row in rows:
            name = str(row.get("name") or row.get("refcode") or "").strip()
            if not name:
                continue
            hay = " ".join(str(v) for v in row.values() if v is not None).lower()
            if wanted and wanted not in hay and wanted not in name.lower():
                continue
            formula = str(row.get("formula") or row.get("formula_pretty") or "") or None
            hits.append(
                StructureRecord(
                    record_id=f"qmof:{name}",
                    source="qmof",
                    formula=formula,
                    topology=None,
                    topology_evidence="unknown",  # QMOF carries no RCSR topology column
                    refcode=name,
                    variant="computation-ready",
                    path=str(row.get("path") or row.get("cif") or ""),
                    notes=[
                        "QMOF 本地镜像（figshare/ QMOF GitHub 在本环境不可达，未 live 验证下载）",
                        f"metadata: {row.get('path') or row.get('cif') or 'filesystem'}",
                    ],
                    extra={"row": row, "kind": row.get("kind")},
                )
            )
            if len(hits) >= query.limit:
                break
        return hits

    def fetch(self, record: StructureRecord) -> FetchedStructure:
        self._ensure()
        row = record.extra.get("row") or {}
        entry = {
            "name": row.get("name") or record.refcode,
            "path": row.get("path") or row.get("cif"),
            "kind": row.get("kind") or ("zip" if _zip_file() is not None else "dir"),
        }
        if not entry.get("kind") or not entry.get("path"):
            # reconstruct from record_id
            name = str(record.refcode or record.record_id.split(":", 1)[-1])
            structs = _structure_dir()
            if structs is not None and (structs / f"{name}.cif").is_file():
                entry = {"name": name, "path": str(structs / f"{name}.cif"), "kind": "dir"}
            elif _zip_file() is not None:
                entry = {"name": name, "path": f"{name}.cif", "kind": "zip"}
            else:
                raise FileNotFoundError(f"QMOF 镜像里找不到 {name}.cif")
        data = _read_cif(entry)
        structure = structure_from_bytes(data, label=f"QMOF {record.refcode}")
        digest = sha256_bytes(data)
        record.natoms = len(structure)
        record.formula = structure.composition.formula
        record.h_count = count_hydrogen(structure)
        record.sha256 = digest
        provenance = {
            "source": "qmof",
            "record_id": record.record_id,
            "mirror_dir": str(qmof_dir()),
            "cif_name": entry.get("path"),
            "sha256": digest,
            "cif_sha256": digest,
            "license": "QMOF 数据集的许可与 CoRE/CSD 来源相关；再分发前请核对官方说明",
            "note": (
                "读取本地 QMOF 镜像；不是在线下载。QMOF 是 CoRE/CSD 的 DFT 标注子集，"
                "本适配器不提供 RCSR 拓扑列（topology_evidence=unknown）。"
            ),
        }
        return FetchedStructure(structure=structure, record=record, provenance=provenance)
