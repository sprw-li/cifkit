"""CoRE MOF 2024 数据源适配器：索引 + 拓扑过滤 + CIF 提取 + 缓存。

数据缓存目录（已就绪，不重复下载）::

    _cache/core-mof-2024/
        CoREMOF2024DB.zip          # 8300 个 CIF：SI/CR/{ASR,FSR,Ion}/, SI/NCR/{both,Chen_Manz,mofchecker,occupancy}/
        ASR_data_SI_20250204.csv   # 1372 行 ASR 元数据（含 topology(SingleNodes)/topology(AllNodes)/DOI/natoms）
        NCR_ASR_SI.xlsx            # NCR 质检标记（Chen_Manz / mofchecker 两个 sheet）
        index.json                 # 本模块生成的索引（缓存）

索引只读每个 CIF 的**头部 6 KB**（化学式、晶胞参数），不解析全部结构；8300 个文件约
1–2 s 建好，之后 search 全部走 JSON。``--rebuild`` 语义由 ``build_index(rebuild=True)``
提供（CLI 面冻结，不能加参数）::

    python -c "from cifkit.sources.core_mof import build_index; i=build_index(rebuild=True); print(i['n_entries'])"

证据等级（与 DESIGN §5 一致）：

* ``computation-ready``（CR/ASR）：拓扑直接来自数据集元数据列 → ``topology_evidence="metadata"``。
* ``raw``（NCR 原始 CIF）：NCR 没有拓扑列，候选先按"重原子组成与某个 sod CR 记录一致"
  或 curated 文献样例发现，**必须**经 ``cifkit.topology.verify`` 结构比对后才标记
  ``verified``；参考不可用时降级为 ``curated`` 并写清依据，绝不硬编码 topology。
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import time
import warnings
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from cifkit.cache import cache_dir
from cifkit.locks import atomic_write_text, file_lock
from cifkit.sources.base import count_hydrogen, expected_hydrogen, sha256_bytes
from cifkit.types import FetchedStructure, SourceQuery, StructureRecord

#: CoRE MOF 2024 v1.1 数据集（Zenodo record 15055758，CC-BY-4.0；由 DataCite 元数据核实）
DATASET_DOI = "10.5281/zenodo.15055758"
DATASET_URL = "https://zenodo.org/records/15055758"
DATASET_FILE_URL = "https://zenodo.org/records/15055758/files/CoREMOF2024DB.zip?download=1"
DATASET_LICENSE = "CC-BY-4.0"
DATASET_VERSION = "1.1 (2025-03)"

CACHE_NAME = "core-mof-2024"
ZIP_NAME = "CoREMOF2024DB.zip"
CSV_NAMES = ("ASR_data_SI_20250204.csv", "ASR_data.csv")
XLSX_NAME = "NCR_ASR_SI.xlsx"
INDEX_NAME = "index.json"
SCHEMA = "cifkit/core-mof-index/v1"

_HEADER_BYTES = 6144
_METAL_BLOCKS = frozenset({"d", "f"})
_METAL_EXTRA = frozenset({"Li", "Na", "K", "Rb", "Cs", "Be", "Mg", "Ca", "Sr", "Ba"})

#: curated 的"文献已知原始样例"表：只给出候选与 DOI/匹配依据，拓扑仍须 topology.verify 核实。
#: 这些条目来自已核对过的文献事实（见 docs/DESIGN.md §4），不是拓扑答案本身。
RAW_EXEMPLARS: dict[str, list[dict[str, str]]] = {
    "sod": [
        {
            "zip_path": "SI/NCR/both/ja204757x_si_002_ASR_pacman.cif",
            "doi": "10.1021/ja204757x",
            "structure_name": "ZIF-8",
            "basis": (
                "JACS 2011 ZIF-8（sod 拓扑）碘吸附工作的原始 CIF：CoRE 2024 NCR 目录、"
                "组成 Zn12 C96 N48、无 H、cubic a=17.029 Å；拓扑归属为文献关联（curated），"
                "返回前必须经 topology.verify 与 CoRE ASR sod 参考结构比对核实"
            ),
        }
    ],
}

#: 名称 →（拓扑, 金属）的 curated 别名表。CoRE 元数据没有通用"常用名"列（1372 行里只有
#: 1 行有 name），所以常用名只能按文献共识映射；名称只用于**筛候选**，拓扑证据仍来自
#: 数据集拓扑列或结构比对，不会因为名字叫 ZIF-8 就直接标 verified。
NAME_HINTS: dict[str, dict[str, Any]] = {
    "zif8": {
        "topology": "sod",
        "metals": ["Zn"],
        "note": "ZIF-8 = Zn(2-甲基咪唑)2，RCSR sod（文献/数据库共识）",
    },
    "zif67": {
        "topology": "sod",
        "metals": ["Co"],
        "note": "ZIF-67 = Co(2-甲基咪唑)2（sod）；CoRE ASR 无 sod 的 Co 记录，会回退到该拓扑典型结构",
    },
    "zif4": {"topology": "cag", "metals": ["Zn"], "note": "ZIF-4 = Zn(咪唑)2，RCSR cag"},
    "mof5": {"topology": "pcu", "metals": ["Zn"], "note": "MOF-5 = Zn4O(BDC)3，RCSR pcu"},
    "hkust1": {"topology": "tbo", "metals": ["Cu"], "note": "HKUST-1 = Cu3(BTC)2，RCSR tbo"},
    "uio66": {"topology": "fcu", "metals": ["Zr"], "note": "UiO-66 = Zr6O4(OH)4(BDC)6，RCSR fcu"},
    "mof801": {
        "topology": "fcu",
        "metals": ["Zr"],
        "refcodes": {"2014[Zr][fcu]3[ASR]1"},
        "note": "CoRE ASR 的 name 列自带 MOF-801（2014[Zr][fcu]3[ASR]1）",
    },
}

_FORMULA_RE = re.compile(r"_chemical_formula_sum\s+['\"]?([^'\"\n]+)")
_CELL_RE = {
    "a": re.compile(r"_cell_length_a\s+([-+0-9.]+)"),
    "b": re.compile(r"_cell_length_b\s+([-+0-9.]+)"),
    "c": re.compile(r"_cell_length_c\s+([-+0-9.]+)"),
    "alpha": re.compile(r"_cell_angle_alpha\s+([-+0-9.]+)"),
    "beta": re.compile(r"_cell_angle_beta\s+([-+0-9.]+)"),
    "gamma": re.compile(r"_cell_angle_gamma\s+([-+0-9.]+)"),
}
_ELEMENT_RE = re.compile(r"([A-Z][a-z]?)\s*(\d+(?:\.\d+)?)?")

_ZERO_H_TOPOLOGY_LABELS = {"", "nan", "none", "unnamed", "unstable", "null", "?"}

_INDEX_CACHE: dict[str, Any] | None = None
_META_CACHE: list[dict[str, Any]] | None = None


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
def dataset_dir() -> Path:
    return cache_dir(CACHE_NAME)


def zip_path() -> Path:
    return dataset_dir() / ZIP_NAME


def csv_path() -> Path:
    for name in CSV_NAMES:
        candidate = dataset_dir() / name
        if candidate.is_file():
            return candidate
    return dataset_dir() / CSV_NAMES[0]


def xlsx_path() -> Path:
    return dataset_dir() / XLSX_NAME


def index_path() -> Path:
    return dataset_dir() / INDEX_NAME


def extracted_dir() -> Path:
    d = dataset_dir() / "extracted"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# 化学式 / 元素小工具
# ---------------------------------------------------------------------------
def is_metal_symbol(sym: str) -> bool:
    try:
        from pymatgen.core import Element

        el = Element(str(sym).strip())
    except Exception:  # noqa: BLE001
        return False
    return el.block in _METAL_BLOCKS or el.symbol in _METAL_EXTRA


def parse_formula(formula: str | None) -> dict[str, float]:
    """Parse ``_chemical_formula_sum`` like ``"Zn6 H60 C48 N24"``."""
    out: dict[str, float] = {}
    if not formula:
        return out
    for match in _ELEMENT_RE.finditer(str(formula)):
        element = match.group(1)
        count = match.group(2)
        try:
            value = float(count) if count else 1.0
        except ValueError:  # pragma: no cover - defensive
            continue
        if value <= 0:
            continue
        out[element] = out.get(element, 0.0) + value
    return out


def _metal_count(formula: dict[str, float]) -> float:
    return float(sum(value for element, value in formula.items() if is_metal_symbol(element)))


def heavy_key(formula: dict[str, float]) -> str | None:
    """与晶胞大小/原胞选择无关的"重原子组成指纹"，如 ``C:8|N:4|Zn:1``。

    以金属原子总数为分母归一化；H 被移除；无金属组成返回 None。
    """
    heavy = {element: count for element, count in formula.items() if element != "H" and count > 0}
    if not heavy:
        return None
    denominator = _metal_count(heavy)
    if denominator <= 0:
        return None
    parts: list[str] = []
    for element in sorted(heavy, key=lambda el: (not is_metal_symbol(el), el)):
        ratio = round(float(heavy[element]) / denominator, 4)
        parts.append(f"{element}:{ratio:g}")
    return "|".join(parts)


def _int_or_none(value) -> int | None:
    try:
        if value is None or str(value).strip() in ("", "-", "nan", "None"):
            return None
        number = float(value)
        if number != number:  # NaN
            return None
        return int(round(number))
    except (TypeError, ValueError):
        return None


def _clean(value) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.lower() not in ("nan", "none", "null") else None


# ---------------------------------------------------------------------------
# 索引构建
# ---------------------------------------------------------------------------
def _read_csv_rows(path: Path) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            coreid = _clean(row.get("coreid"))
            if coreid:
                rows[coreid] = row
    return rows


def _read_ncr_flags(path: Path) -> dict[str, dict[str, dict[str, Any]]]:
    """Read NCR quality-control flags (Chen_Manz / mofchecker sheets) keyed by refcode."""
    flags: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    if not path.is_file():
        return {}
    try:
        import openpyxl
    except Exception:  # noqa: BLE001 - optional at index-build time
        return {}
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for sheet in workbook.worksheets:
            rows = sheet.iter_rows(values_only=True)
            try:
                header = [str(h).strip() if h is not None else "" for h in next(rows)]
            except StopIteration:
                continue
            for row in rows:
                values = dict(zip(header, row))
                refcode = _clean(values.get("refcode"))
                if not refcode:
                    continue
                flags[refcode][sheet.title] = {
                    key: value for key, value in values.items() if key and value is not None
                }
        workbook.close()
    except Exception:  # noqa: BLE001 - QC flags are a bonus, never block the index
        return {}
    return dict(flags)


def _parse_header(head: str) -> dict[str, Any]:
    formula_match = _FORMULA_RE.search(head)
    formula = formula_match.group(1).strip() if formula_match else None
    cell: dict[str, float | None] = {}
    for key, regex in _CELL_RE.items():
        match = regex.search(head)
        cell[key] = float(match.group(1)) if match else None
    return {"formula": formula, "cell": cell}


def _entry_from_cif(zip_name: str, head: str, csv_rows: dict[str, dict[str, str]],
                    ncr_flags: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    parts = zip_name.split("/")
    section = parts[1] if len(parts) > 2 else ""
    subset = parts[2] if len(parts) > 3 else ""
    stem = Path(zip_name).stem
    variant = "computation-ready" if section == "CR" else "raw"
    parsed = _parse_header(head)
    formula_text = parsed["formula"]
    formula = parse_formula(formula_text)
    entry: dict[str, Any] = {
        "variant": variant,
        "section": section,
        "subset": subset,
    }
    if formula:
        entry["formula"] = formula_text
        entry["h_count"] = int(round(formula.get("H", 0.0)))
        entry["natoms"] = int(round(sum(formula.values())))
        hk = heavy_key(formula)
        if hk:
            entry["heavy_key"] = hk
        metals = sorted(el for el in formula if is_metal_symbol(el))
        if metals:
            entry["metal_types"] = ", ".join(metals)
    cell = parsed["cell"]
    if all(cell.get(k) is not None for k in ("a", "b", "c")):
        entry["abc"] = [cell["a"], cell["b"], cell["c"]]
    if all(cell.get(k) is not None for k in ("alpha", "beta", "gamma")):
        entry["angles"] = [cell["alpha"], cell["beta"], cell["gamma"]]

    row = None
    if variant == "computation-ready" and subset == "ASR":
        row = csv_rows.get(stem)
        if row is not None:
            entry["coreid"] = stem
            for key, column in (
                ("refcode", "refcode"),
                ("name", "name"),
                ("doi", "DOI"),
                ("metal_types", "Metal Types"),
                ("topology_allnodes", "topology(AllNodes)"),
                ("topology_singlenodes", "topology(SingleNodes)"),
                ("topology_allnodes_zeo", "topology(AllNodes)-zeo"),
            ):
                value = _clean(row.get(column))
                if value is not None:
                    entry[key] = value
            number = _int_or_none(row.get("number"))
            if number is not None:
                entry["number"] = number
            year = _int_or_none(row.get("Year"))
            if year is not None:
                entry["year"] = year
            csv_natoms = _int_or_none(row.get("natoms"))
            if csv_natoms is not None:
                entry["natoms"] = csv_natoms
    if "refcode" not in entry:
        entry["refcode"] = stem
    if "coreid" not in entry and variant == "computation-ready":
        entry["coreid"] = stem

    if variant == "raw":
        refcode = str(entry.get("refcode") or "")
        if refcode in ncr_flags:
            entry["ncr_flags"] = ncr_flags[refcode]
    return entry


def _file_fingerprint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False}
    stat = path.stat()
    return {"path": str(path), "exists": True, "size": stat.st_size, "mtime": round(stat.st_mtime, 3)}


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_cached_index(idx_file: Path, archive: Path, csv_file: Path) -> dict[str, Any] | None:
    """Return a valid cached index, or ``None`` (missing/corrupt/stale)."""
    if not idx_file.is_file():
        return None
    try:
        with idx_file.open("r", encoding="utf-8") as handle:
            cached = json.load(handle)
    except Exception:  # noqa: BLE001 - corrupt cache -> rebuild
        return None
    if cached.get("schema") == SCHEMA and _index_fresh(cached, archive, csv_file):
        return cached
    return None


def build_index(*, rebuild: bool = False) -> dict[str, Any]:
    """Build/load the JSON index of the CoRE MOF 2024 zip.

    Reads only the first ``_HEADER_BYTES`` of each CIF (formula + cell), so ~8300
    files cost 1-2 s; the result is cached in ``_cache/core-mof-2024/index.json``.

    Concurrency: parallel processes may build the index simultaneously; writers
    take an advisory lock (``index.json.lock``) and replace the file atomically,
    so a reader never sees a partially written JSON.
    """
    global _INDEX_CACHE, _META_CACHE
    archive = zip_path()
    if not archive.is_file():
        raise FileNotFoundError(
            f"CoRE MOF 2024 zip 不在缓存：{archive}。"
            f"请把 CoREMOF2024DB.zip 放到 {dataset_dir()}（本工具不重复下载大文件）。"
        )
    csv_file = csv_path()
    idx_file = index_path()
    if not rebuild:
        cached = _load_cached_index(idx_file, archive, csv_file)
        if cached is not None:
            _INDEX_CACHE = cached
            _META_CACHE = None
            return cached

    with file_lock(idx_file.with_name(idx_file.name + ".lock"), timeout=120.0):
        # double-checked locking: another process may have finished while we waited
        if not rebuild:
            cached = _load_cached_index(idx_file, archive, csv_file)
            if cached is not None:
                _INDEX_CACHE = cached
                _META_CACHE = None
                return cached

        started = time.time()
        csv_rows = _read_csv_rows(csv_file)
        ncr_flags = _read_ncr_flags(xlsx_path())
        entries: dict[str, dict[str, Any]] = {}
        with zipfile.ZipFile(archive) as archive_handle:
            for member in archive_handle.namelist():
                if not member.endswith(".cif"):
                    continue
                with archive_handle.open(member) as handle:
                    head = handle.read(_HEADER_BYTES).decode("utf-8", "replace")
                entries[member] = _entry_from_cif(member, head, csv_rows, ncr_flags)

        variants = Counter(entry.get("variant") for entry in entries.values())
        index = {
            "schema": SCHEMA,
            "built_at": now(),
            "build_seconds": round(time.time() - started, 2),
            "dataset": {
                "name": "CoRE MOF 2024",
                "version": DATASET_VERSION,
                "doi": DATASET_DOI,
                "url": DATASET_URL,
                "file_url": DATASET_FILE_URL,
                "license": DATASET_LICENSE,
            },
            "zip": {**_file_fingerprint(archive), "sha256": _sha256_file(archive)},
            "csv": {**_file_fingerprint(csv_file), "sha256": _sha256_file(csv_file)},
            "xlsx": _file_fingerprint(xlsx_path()),
            "n_entries": len(entries),
            "n_computation_ready": int(variants.get("computation-ready", 0)),
            "n_raw": int(variants.get("raw", 0)),
            "topology_columns_note": (
                "拓扑列只覆盖 SI/CR/ASR（ASR_data_SI_*.csv，1372 行）；SI/NCR/* 原始 CIF 没有拓扑元数据，"
                "其拓扑必须用 cifkit.topology.verify 结构比对核实"
            ),
            "entries": entries,
        }
        atomic_write_text(idx_file, json.dumps(index, ensure_ascii=False, separators=(",", ":")))
        _INDEX_CACHE = index
        _META_CACHE = None
        return index


def _index_fresh(index: dict[str, Any], archive: Path, csv_file: Path) -> bool:
    if not index.get("entries"):
        return False
    zip_info = index.get("zip") or {}
    if not zip_info.get("exists", True):
        return False
    if archive.is_file():
        stat = archive.stat()
        if zip_info.get("size") != stat.st_size:
            return False
        if abs(float(zip_info.get("mtime", 0)) - round(stat.st_mtime, 3)) > 1e-3:
            return False
    csv_info = index.get("csv") or {}
    if csv_file.is_file():
        stat = csv_file.stat()
        if csv_info.get("size") is not None and csv_info.get("size") != stat.st_size:
            return False
    return True


def load_index(*, rebuild: bool = False) -> dict[str, Any]:
    global _INDEX_CACHE
    if rebuild:
        _INDEX_CACHE = None
    if _INDEX_CACHE is not None:
        return _INDEX_CACHE
    return build_index(rebuild=False)


def reset_cache() -> None:
    """Drop in-memory caches (tests: force re-read of index/metadata)."""
    global _INDEX_CACHE, _META_CACHE
    _INDEX_CACHE = None
    _META_CACHE = None


# ---------------------------------------------------------------------------
# 元数据查询（供 topology.verify 使用）
# ---------------------------------------------------------------------------
def _entry_topology(entry: dict[str, Any]) -> str | None:
    for key in ("topology_allnodes", "topology_singlenodes"):
        value = str(entry.get(key) or "").strip().lower()
        if value not in _ZERO_H_TOPOLOGY_LABELS:
            return value
    return None


def entries_with_topology(topo: str) -> list[dict[str, Any]]:
    topo = str(topo or "").strip().lower()
    index = load_index()
    hits: list[dict[str, Any]] = []
    for member, entry in index["entries"].items():
        if str(entry.get("variant")) != "computation-ready":
            continue
        labels = {
            str(entry.get("topology_allnodes") or "").strip().lower(),
            str(entry.get("topology_singlenodes") or "").strip().lower(),
        }
        if topo in labels:
            hits.append(dict(entry, zip_path=member))
    return hits


def _ready_sort_key(entry: dict[str, Any], *, typical: bool = True):
    metals = str(entry.get("metal_types") or "")
    natoms = entry.get("natoms") or 10**9
    number = entry.get("number") or 10**9
    if typical:
        return (0 if "Zn" in metals else 1, natoms, number, entry.get("zip_path", ""))
    return (number, natoms, entry.get("zip_path", ""))


def reference_candidates(topo: str) -> list[dict[str, Any]]:
    """同拓扑的 CoRE ASR 计算就绪结构，按"典型"排序（Zn 优先、原子数小优先）。"""
    hits = sorted(entries_with_topology(topo), key=lambda entry: _ready_sort_key(entry, typical=True))
    return [
        {
            "zip_path": entry["zip_path"],
            "record_id": f"core-mof:{entry['zip_path']}",
            "coreid": entry.get("coreid"),
            "refcode": entry.get("refcode"),
            "doi": entry.get("doi"),
            "natoms": entry.get("natoms"),
            "metal_types": entry.get("metal_types"),
            "topology": _entry_topology(entry),
        }
        for entry in hits
    ]


def metadata_entries() -> list[dict[str, Any]]:
    """CoRE ASR labeled 记录的紧凑列表（供拓扑元数据指纹匹配，模块内缓存）。"""
    global _META_CACHE
    if _META_CACHE is not None:
        return _META_CACHE
    out: list[dict[str, Any]] = []
    index = load_index()
    for member, entry in index["entries"].items():
        if str(entry.get("variant")) != "computation-ready":
            continue
        topo = _entry_topology(entry)
        if topo is None:
            continue
        formula = parse_formula(entry.get("formula"))
        if not formula:
            continue
        out.append(
            {
                "zip_path": member,
                "record_id": f"core-mof:{member}",
                "coreid": entry.get("coreid"),
                "doi": entry.get("doi"),
                "topology": topo,
                "formula": {element: float(count) for element, count in formula.items()},
                "natoms": entry.get("natoms"),
                "abc": entry.get("abc"),
                "angles": entry.get("angles"),
            }
        )
    _META_CACHE = out
    return out


def find_metadata_record(structure, rel_tol: float = 5e-3, angle_tol: float = 0.5) -> dict[str, Any] | None:
    """Match a structure against CoRE ASR labeled records by formula/natoms/cell.

    Returns ``{"topology", "records", "match_count"}`` only when every matching
    record agrees on the topology label; ambiguous/conflicting matches return None.
    """
    try:
        composition = structure.composition.as_dict()
    except Exception:  # noqa: BLE001
        return None
    comp = {str(element): round(float(amount), 6) for element, amount in composition.items() if amount}
    natoms = len(structure)
    abc = [float(x) for x in structure.lattice.abc]
    angles = [float(x) for x in structure.lattice.angles]
    matches: list[dict[str, Any]] = []
    for entry in metadata_entries():
        if entry.get("natoms") != natoms:
            continue
        formula = entry["formula"]
        if set(formula) != set(comp):
            continue
        if any(abs(formula[element] - comp[element]) > 1e-3 for element in comp):
            continue
        entry_abc = entry.get("abc")
        if not entry_abc or any(abs(abc[i] / entry_abc[i] - 1.0) > rel_tol for i in range(3)):
            continue
        entry_angles = entry.get("angles")
        if not entry_angles or any(abs(angles[i] - entry_angles[i]) > angle_tol for i in range(3)):
            continue
        matches.append(entry)
    if not matches:
        return None
    topologies = {match["topology"] for match in matches}
    if len(topologies) != 1:
        return None
    return {
        "topology": topologies.pop(),
        "records": [match["record_id"] for match in matches[:5]],
        "match_count": len(matches),
    }


# ---------------------------------------------------------------------------
# CIF 读取 / 结构解析
# ---------------------------------------------------------------------------
def read_cif_bytes(member: str) -> bytes:
    """Read one CIF member out of the cached zip."""
    archive = zip_path()
    if not archive.is_file():
        raise FileNotFoundError(
            f"CoRE MOF 2024 zip 不在缓存：{archive}（请放到 {dataset_dir()}，不要重复下载）"
        )
    with zipfile.ZipFile(archive) as handle:
        try:
            return handle.read(member)
        except KeyError as exc:
            raise KeyError(f"CoRE zip 中没有成员 {member!r}") from exc


def structure_from_cif_bytes(data: bytes, label: str = "cif") -> Any:
    from pymatgen.core import Structure

    text = data.decode("utf-8", "replace")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return Structure.from_str(text, fmt="cif")
        except Exception:  # noqa: BLE001 - fall back to explicit CifParser
            from pymatgen.io.cif import CifParser

            structures = CifParser.from_str(text).parse_structures(primitive=False)
            if not structures:
                raise ValueError(f"无法从 {label} 解析出结构")
            return structures[0]


def load_structure(member: str) -> Any:
    return structure_from_cif_bytes(read_cif_bytes(member), label=member)


# ---------------------------------------------------------------------------
# 记录构造
# ---------------------------------------------------------------------------
def _safe_stem(member: str) -> str:
    stem = Path(member).stem
    return re.sub(r'[<>:"/\\|?*\[\]]+', "_", stem)


def _ready_record(entry: dict[str, Any], topo: str, name_info: dict[str, Any] | None = None) -> StructureRecord:
    notes = [
        "CoRE MOF 2024 ASR 计算就绪结构；拓扑来自数据集元数据列 topology(AllNodes)=%s（证据等级 metadata，未做结构比对）"
        % topo,
        "computation-ready 结构 H 已由数据库清理完整，不按估算判缺氢",
    ]
    if name_info is not None:
        hint = name_info.get("hint") or {}
        if hint.get("note"):
            notes.append(f"名称筛选：{hint['note']}（curated 别名，仅用于选候选）")
        if name_info.get("metal_fallback"):
            notes.append(
                f"名称别名指定的金属 {hint.get('metals')} 在 CoRE ASR 该拓扑下没有记录，已回退到该拓扑典型结构"
            )
    return StructureRecord(
        record_id=f"core-mof:{entry['zip_path']}",
        source="core-mof",
        formula=entry.get("formula"),
        topology=topo,
        topology_evidence="metadata",
        refcode=entry.get("refcode"),
        coreid=entry.get("coreid"),
        doi=entry.get("doi"),
        variant="computation-ready",
        natoms=entry.get("natoms"),
        h_count=entry.get("h_count"),
        h_expected=None,
        path=None,
        url=DATASET_URL,
        sha256=None,
        notes=notes,
        extra={
            "zip_path": entry["zip_path"],
            "section": entry.get("section"),
            "subset": entry.get("subset"),
            "variant": entry.get("variant"),
            "topology_allnodes": entry.get("topology_allnodes"),
            "topology_singlenodes": entry.get("topology_singlenodes"),
            "metal_types": entry.get("metal_types"),
            "dataset_doi": DATASET_DOI,
        },
    )


def _h_expected_estimate(
    raw_entry: dict[str, Any], ready_entry: dict[str, Any] | None
) -> tuple[float | None, str]:
    raw_formula = parse_formula(raw_entry.get("formula"))
    if ready_entry is not None:
        ready_formula = parse_formula(ready_entry.get("formula"))
        reference_h = float(ready_entry.get("h_count") or 0.0)
        reference_metal = _metal_count(ready_formula)
        raw_metal = _metal_count(raw_formula)
        if reference_metal > 0 and raw_metal > 0 and reference_h > 0:
            return (
                round(reference_h / reference_metal * raw_metal, 1),
                f"按 H 完整的同组成 CoRE ASR 参考 {ready_entry.get('coreid')} "
                f"（{ready_entry.get('formula')}）的 H/金属比缩放估计，非实测",
            )
    from cifkit.sources.base import expected_hydrogen

    estimate = expected_hydrogen(raw_formula) if raw_formula else None
    if estimate:
        return (round(estimate, 1), "按 sources/base.expected_hydrogen 的有机骨架经验公式粗估，非实测")
    return (None, "无法估计")


def _raw_record(
    raw_entry: dict[str, Any],
    topo: str,
    ready_entry: dict[str, Any] | None,
    exemplar: dict[str, str] | None,
) -> StructureRecord:
    h_expected, h_method = _h_expected_estimate(raw_entry, ready_entry)
    notes: list[str] = [
        "原始（NCR）CIF：未经计算就绪清理，可能缺氢/有占位原子，需 repair 层处理",
        f"记录自带 H 数={raw_entry.get('h_count')}，期望约 {h_expected}（估计值：{h_method}）",
    ]
    if ready_entry is not None:
        notes.append(
            f"候选发现：重原子组成指纹 {raw_entry.get('heavy_key')} 与 CoRE ASR sod 记录 "
            f"{ready_entry.get('coreid')} 一致（{ready_entry.get('formula')}）"
        )
    if exemplar is not None:
        notes.append("curated 候选（文献关联，非拓扑答案）：" + exemplar.get("basis", ""))
        if exemplar.get("structure_name"):
            notes.append(f"文献常用名：{exemplar['structure_name']}（curated 名称关联）")
    flags = raw_entry.get("ncr_flags") or {}
    if flags:
        if "mofchecker" in flags:
            problems = [
                key
                for key, value in flags["mofchecker"].items()
                if key.startswith("has_") and value is True
            ]
            if problems:
                notes.append("CoRE NCR 质检标记（mofchecker）：" + ", ".join(problems))
        if "Chen_Manz" in flags:
            problems = [key for key, value in flags["Chen_Manz"].items() if value is True]
            if problems:
                notes.append("CoRE NCR 质检标记（Chen_Manz）：" + ", ".join(problems))
    doi = (exemplar or {}).get("doi") or raw_entry.get("doi")
    return StructureRecord(
        record_id=f"core-mof:{raw_entry['zip_path']}",
        source="core-mof",
        formula=raw_entry.get("formula"),
        topology=topo,
        # 原始 CIF 没有数据库拓扑列；先标 curated/unknown，检索时经结构比对升级
        topology_evidence="curated" if exemplar is not None else "unknown",
        refcode=raw_entry.get("refcode"),
        coreid=raw_entry.get("coreid"),
        doi=doi,
        variant="raw",
        natoms=raw_entry.get("natoms"),
        h_count=raw_entry.get("h_count"),
        h_expected=h_expected,
        path=None,
        url=DATASET_URL,
        sha256=None,
        notes=notes,
        extra={
            "zip_path": raw_entry["zip_path"],
            "section": raw_entry.get("section"),
            "subset": raw_entry.get("subset"),
            "variant": "raw",
            "heavy_key": raw_entry.get("heavy_key"),
            "h_expected_method": h_method,
            "curated_exemplar": bool(exemplar),
            "matched_ready_record": ready_entry.get("coreid") if ready_entry else None,
            "matched_ready_doi": ready_entry.get("doi") if ready_entry else None,
            "dataset_doi": DATASET_DOI,
            "ncr_flags": raw_entry.get("ncr_flags"),
        },
    )


# ---------------------------------------------------------------------------
# 名称 → 候选筛选
# ---------------------------------------------------------------------------
def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def _name_info(name: str, entries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    key = _normalize_name(name)
    hint = NAME_HINTS.get(key)
    direct: list[dict[str, Any]] = []
    substr: list[dict[str, Any]] = []
    for member, entry in entries.items():
        entry_name = entry.get("name")
        if entry_name and _normalize_name(entry_name) == key:
            direct.append(dict(entry, zip_path=member))
            continue
        refcode = _normalize_name(str(entry.get("refcode") or ""))
        coreid = _normalize_name(str(entry.get("coreid") or ""))
        if key and (key in refcode or key in coreid):
            substr.append(dict(entry, zip_path=member))
    if hint is None and not direct and not substr:
        known = ", ".join(sorted(NAME_HINTS)) or "（空）"
        raise ValueError(
            f"未知结构名 {name!r}：CoRE 2024 索引里没有该名称/refcode，也没有 curated 别名。已知别名：{known}"
        )
    return {"key": key, "hint": hint, "direct": direct, "substr": substr[:20], "metal_fallback": False}


def _filter_by_name(
    hits: list[dict[str, Any]], name_info: dict[str, Any]
) -> list[dict[str, Any]]:
    hint = name_info.get("hint") or {}
    refcodes = {str(r) for r in (hint.get("refcodes") or set())}
    direct_coreids = {entry.get("coreid") for entry in name_info.get("direct") or []}
    filtered = hits
    if refcodes:
        by_refcode = [entry for entry in hits if str(entry.get("refcode")) in refcodes]
        if by_refcode:
            filtered = by_refcode
        else:
            filtered = [entry for entry in hits if entry.get("coreid") in direct_coreids] or hits
    elif direct_coreids:
        filtered = [entry for entry in hits if entry.get("coreid") in direct_coreids] or hits
    metals = hint.get("metals") or []
    if metals:
        by_metal = [entry for entry in filtered if any(m in str(entry.get("metal_types") or "") for m in metals)]
        if by_metal:
            filtered = by_metal
        else:
            name_info["metal_fallback"] = True
    return filtered


# ---------------------------------------------------------------------------
# 原始结构（NCR）候选发现 + 结构比对核实
# ---------------------------------------------------------------------------
def _raw_candidates(
    entries: dict[str, dict[str, Any]], topo: str
) -> list[tuple[dict[str, Any], dict[str, Any] | None, dict[str, str] | None]]:
    ready = entries_with_topology(topo)
    ready_by_heavy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in ready:
        key = entry.get("heavy_key")
        if key:
            ready_by_heavy[key].append(entry)

    found: dict[str, tuple[dict[str, Any], dict[str, Any] | None, dict[str, str] | None]] = {}
    for member, entry in entries.items():
        if str(entry.get("variant")) != "raw":
            continue
        key = entry.get("heavy_key")
        if key and key in ready_by_heavy:
            best_ready = sorted(ready_by_heavy[key], key=lambda item: _ready_sort_key(item, typical=True))[0]
            found[member] = (dict(entry, zip_path=member), best_ready, None)
    for exemplar in RAW_EXEMPLARS.get(topo, []):
        member = exemplar["zip_path"]
        if member not in entries:
            continue
        entry = dict(entries[member], zip_path=member)
        key = entry.get("heavy_key")
        best_ready = (
            sorted(ready_by_heavy[key], key=lambda item: _ready_sort_key(item, typical=True))[0]
            if key and key in ready_by_heavy
            else None
        )
        found[member] = (entry, best_ready, exemplar)

    def sort_key(item):
        entry, _ready, exemplar = item
        return (
            _int_or_none(entry.get("h_count")) if entry.get("h_count") is not None else 10**9,
            0 if str(entry.get("subset")) == "ASR" else 1 if str(entry.get("subset")) == "FSR" else 2,
            0 if exemplar is not None else 1,
            entry["zip_path"],
        )

    ordered = sorted(found.values(), key=sort_key)
    # 同一原始结构的 ASR/FSR 采样去重：优先保留 ASR（左侧排序已保证）
    deduped: list[tuple[dict[str, Any], dict[str, Any] | None, dict[str, str] | None]] = []
    seen_bases: set[str] = set()
    for item in ordered:
        entry = item[0]
        base = re.sub(r"_(ASR|FSR)_pacman$", "", Path(entry["zip_path"]).stem)
        base = re.sub(r"_(ASR|FSR)_", "_", base)
        if base in seen_bases:
            continue
        seen_bases.add(base)
        deduped.append(item)
    return deduped


class CoreMOFSource:
    """CoRE MOF 2024 source adapter (computation-ready ASR + raw NCR CIFs)."""

    name = "core-mof"
    description = "CoRE MOF 2024（1372 ASR 计算就绪 + 5636 NCR 原始 CIF，zip 本地缓存，按拓扑/名称检索）"

    # -- search ---------------------------------------------------------
    def search(self, query: SourceQuery) -> list[StructureRecord]:
        index = load_index()
        entries: dict[str, dict[str, Any]] = index["entries"]
        limit = max(1, int(query.limit or 10))
        topo = str(query.topology or "").strip().lower() or None
        name = str(query.structure_name or "").strip() or None
        name_info = _name_info(name, entries) if name else None
        if topo is None and name_info is not None:
            hint = name_info.get("hint") or {}
            topo = str(hint.get("topology") or "").strip().lower() or None

        if topo:
            ready_entries = entries_with_topology(topo)
            if name_info is not None:
                ready_entries = _filter_by_name(ready_entries, name_info)
            ready_records = [
                _ready_record(entry, topo, name_info)
                for entry in sorted(ready_entries, key=lambda entry: _ready_sort_key(entry, typical=bool(query.typical)))
            ]
            if query.prefer_raw:
                raw_records = self._raw_hits(entries, topo, limit=limit, name_info=name_info)
                if raw_records:
                    return (raw_records + ready_records)[:limit]
                for record in ready_records:
                    record.notes.append(
                        f"prefer_raw=True 但拓扑 {topo} 没有可核实（topology.verify 通过）的原始 NCR 结构，"
                        "退回 CoRE ASR 计算就绪结构"
                    )
                return ready_records[:limit]
            return ready_records[:limit]

        if name_info is not None:
            candidates = list(name_info.get("direct") or [])
            known = {entry.get("zip_path") for entry in candidates}
            candidates += [entry for entry in name_info.get("substr") or [] if entry.get("zip_path") not in known]
            records: list[StructureRecord] = []
            for entry in candidates:
                entry_topo = _entry_topology(entry)
                if entry_topo is None:
                    continue
                records.append(_ready_record(entry, entry_topo, name_info))
            if records:
                return sorted(records, key=lambda record: _ready_sort_key(record.extra, typical=bool(query.typical)))[:limit]
            raise ValueError(f"名称 {name!r} 命中了索引条目，但没有一条带可用的拓扑元数据（ASR）：无法作为 CIF 记录返回")

        return []

    def _raw_hits(
        self,
        entries: dict[str, dict[str, Any]],
        topo: str,
        *,
        limit: int,
        name_info: dict[str, Any] | None,
    ) -> list[StructureRecord]:
        from cifkit.topology import verify as verify_topology

        candidates = _raw_candidates(entries, topo)
        if name_info is not None:
            hint = name_info.get("hint") or {}
            metals = hint.get("metals") or []
            preferred = [
                item
                for item in candidates
                if not metals or any(m in str(item[0].get("metal_types") or "") for m in metals)
            ]
            if preferred:
                candidates = preferred
        records: list[StructureRecord] = []
        # 原始结构每条都要解析 + topology.verify（结构比对），为控制检索耗时最多核实 6 条；
        # 排序已保证"最需要补氢的典型原始结构"在最前面。
        max_verify = min(len(candidates), max(min(limit, 6), 3))
        for raw_entry, ready_entry, exemplar in candidates[:max_verify]:
            try:
                structure = load_structure(raw_entry["zip_path"])
            except Exception:  # noqa: BLE001 - skip unparsable candidate
                continue
            result = verify_topology(structure, topo)
            record = _raw_record(raw_entry, topo, ready_entry, exemplar)
            # 用真实解析结果覆盖索引里的头部摘要（H 数、原子数、组成）
            record.h_count = count_hydrogen(structure)
            record.natoms = len(structure)
            record.formula = structure.composition.formula
            if result.get("ok") and result.get("evidence") in ("verified", "metadata"):
                record.topology_evidence = "verified"
                record.notes.append(
                    "拓扑证据：topology.verify 结构比对通过（verify evidence=%s）。%s"
                    % (result.get("evidence"), str(result.get("detail") or "")[:400])
                )
                record.extra["topology_verification"] = {
                    "ok": True,
                    "evidence": result.get("evidence"),
                    "detail": result.get("detail"),
                    "signature": result.get("signature"),
                    "reference": result.get("reference"),
                }
            elif result.get("evidence") == "unknown" and exemplar is not None:
                record.topology_evidence = "curated"
                record.notes.append(
                    "拓扑证据：结构比对不可用（%s），按 curated 文献关联返回；未升级为 verified"
                    % str(result.get("detail") or "")[:300]
                )
                record.extra["topology_verification"] = {
                    "ok": False,
                    "evidence": result.get("evidence"),
                    "detail": result.get("detail"),
                }
            else:
                record.extra["topology_verification_failed"] = {
                    "ok": result.get("ok"),
                    "evidence": result.get("evidence"),
                    "detail": result.get("detail"),
                }
                continue
            records.append(record)
            if len(records) >= limit:
                break
        return records

    # -- fetch ----------------------------------------------------------
    def fetch(self, record: StructureRecord) -> FetchedStructure:
        member = str(record.extra.get("zip_path") or "").strip()
        if not member:
            raise ValueError(
                f"core-mof 记录 {record.record_id!r} 缺少 extra['zip_path']；"
                "请先用 CoreMOFSource.search() 得到记录再 fetch"
            )
        data = read_cif_bytes(member)
        digest = sha256_bytes(data)
        target = extracted_dir() / f"{_safe_stem(member)}-{digest[:12]}.cif"
        reused = target.is_file() and target.stat().st_size == len(data)
        if not reused:
            target.write_bytes(data)
        structure = structure_from_cif_bytes(data, label=member)

        record.path = str(target)
        record.sha256 = digest
        record.h_count = count_hydrogen(structure)
        record.natoms = len(structure)
        record.formula = structure.composition.formula

        index = load_index()
        provenance = {
            "source": "core-mof",
            "record_id": record.record_id,
            "record_refcode": record.refcode,
            "record_coreid": record.coreid,
            "variant": record.variant,
            "zip_path": member,
            "zip_sha256": (index.get("zip") or {}).get("sha256"),
            "zip_size": (index.get("zip") or {}).get("size"),
            "dataset": "CoRE MOF 2024",
            "dataset_version": DATASET_VERSION,
            "dataset_doi": DATASET_DOI,
            "dataset_url": DATASET_URL,
            "url": DATASET_URL,
            "file_url": DATASET_FILE_URL,
            "license": DATASET_LICENSE,
            "doi": record.doi,
            "doi_note": (
                "DOI 来自 CoRE ASR 元数据"
                if (record.extra or {}).get("matched_ready_doi") is None
                else "DOI 来自 curated 文献关联（NCR 无元数据列）"
            ),
            "cif_sha256": digest,
            "sha256": digest,
            "cif_path": str(target),
            "cache_reused": bool(reused),
            "fetched_at": now(),
            "topology": record.topology,
            "topology_evidence": record.topology_evidence,
            "h_count": record.h_count,
            "h_expected": record.h_expected,
        }
        return FetchedStructure(structure=structure, record=record, provenance=provenance)
