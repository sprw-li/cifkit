"""把 6 个 Fd-3m 典例的原始 CIF 抓取/留档到 ``data/structures/``（需要网络）。

用法（在仓库根目录）::

    .venv\\Scripts\\python.exe usecases\\u1_fd3m\\scripts\\fetch_structures.py

COD 记录走 ``cifkit.sources.cod.CODSource``（自带重试与 ``_cache/cod`` 缓存）；
AFLOW 记录走共享 helper ``usecases._common.aflow_db.fetch_structure``。
下载后**不在这里**断言空间群——空间群一律由 ``make_figure.py`` 用 spglib 复核。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                         # usecases/u1_fd3m
REPO = HERE.parents[2]                     # 仓库根
sys.path.insert(0, str(HERE))              # 同目录 spec.py
sys.path.insert(0, str(REPO))              # usecases._common / cifkit

from spec import (  # noqa: E402  (同目录模块)
    EXAMPLES,
    PROVENANCE_JSON,
    STRUCT_DIR,
)

UA_NOTE = "COD data are in the public domain; AFLOW usage terms apply (see aflow.org)."

#: base directory used to store relative paths in provenance (CLI may retarget it)
REL_BASE = ROOT


def retarget(outdir: Path) -> None:
    """Write structures/provenance under ``<outdir>/data/`` instead of the use case dir.

    Kept as a separate helper so ``cifkit/usecases_cli.py`` can import this module and
    call ``main(["--outdir", ...])`` without touching the repo copy of u1_fd3m.
    """
    global STRUCT_DIR, PROVENANCE_JSON, REL_BASE
    out = Path(outdir).expanduser().resolve()
    STRUCT_DIR = out / "data" / "structures"
    PROVENANCE_JSON = out / "data" / "provenance.json"
    REL_BASE = out


def _relative(path: Path) -> str:
    """Relative path when it is under the current base, absolute otherwise."""
    try:
        return str(path.relative_to(REL_BASE))
    except ValueError:
        return str(path)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_cod(entry: dict) -> dict:
    from cifkit.sources.cod import CODSource
    from cifkit.types import SourceQuery

    src = CODSource()
    hits = src.search(SourceQuery(structure_id=entry["cod_id"]))
    if not hits:
        raise RuntimeError(f"COD {entry['cod_id']} 检索无命中")
    fetched = src.fetch(hits[0])
    cif_path = Path(fetched.record.path)
    data = cif_path.read_bytes()
    out = STRUCT_DIR / f"{entry['key']}.cif"
    out.write_bytes(data)
    return {
        "key": entry["key"],
        "source": "COD",
        "record_id": fetched.record.record_id,
        "cod_id": entry["cod_id"],
        "url": entry["url"],
        "search": entry["search"],
        "sha256": sha256_bytes(data),
        "bytes": len(data),
        "cache_path": str(cif_path),
        "cache_reused": bool(fetched.provenance.get("cache_reused")),
        "license": "COD public domain (https://www.crystallography.net/cod/)",
        "local_cif": _relative(out),
        "fetched_at": fetched.provenance.get("fetched_at"),
    }


def fetch_aflow(entry: dict) -> dict:
    from usecases._common import aflow_db as db

    structure, prov, record = db.fetch_structure(entry["aurl"])
    cif_path = Path(prov["cif_path"])
    data = cif_path.read_bytes()
    out = STRUCT_DIR / f"{entry['key']}.cif"
    out.write_bytes(data)
    return {
        "key": entry["key"],
        "source": "AFLOW",
        "record_id": record.record_id,
        "aurl": entry["aurl"],
        "url": entry["url"],
        "search": entry["search"],
        "sha256": sha256_bytes(data),
        "bytes": len(data),
        "cache_path": str(cif_path),
        "cache_reused": bool(prov.get("cache_reused")),
        "license": "AFLOW usage terms (https://aflow.org/)",
        "local_cif": _relative(out),
        "fetched_at": prov.get("fetched_at"),
        "composition_aflow": structure.composition.reduced_formula,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="已有本地 CIF 也重新抓取")
    ap.add_argument("--outdir", type=Path, default=None,
                    help="输出根目录（默认 usecases/u1_fd3m；给出时写到 <outdir>/data/）")
    args = ap.parse_args(argv)
    if args.outdir:
        retarget(args.outdir)

    STRUCT_DIR.mkdir(parents=True, exist_ok=True)
    PROVENANCE_JSON.parent.mkdir(parents=True, exist_ok=True)
    old_entries: dict[str, dict] = {}
    if PROVENANCE_JSON.is_file():
        try:
            old_entries = {row.get("key"): row for row in
                           json.loads(PROVENANCE_JSON.read_text(encoding="utf-8")).get("entries", [])}
        except Exception:  # noqa: BLE001 - 旧文件损坏不影响重新抓取
            old_entries = {}
    rows = []
    t_all = time.time()
    for entry in EXAMPLES:
        out = STRUCT_DIR / f"{entry['key']}.cif"
        if out.is_file() and not args.force:
            data = out.read_bytes()
            if entry["key"] in old_entries:
                # 保留上一次真实抓取的 provenance，只更新本地文件哈希
                row = dict(old_entries[entry["key"]])
                row["sha256"] = sha256_bytes(data)
                row["bytes"] = len(data)
                row["local_cif"] = _relative(out)
                row["note"] = "本次 --force 未启用，沿用已有本地 CIF 与上次抓取的 provenance"
            else:
                row = {
                    "key": entry["key"], "source": entry["source"],
                    "record_id": entry.get("cod_id") or entry.get("aurl"),
                    "url": entry["url"], "search": entry["search"],
                    "sha256": sha256_bytes(data), "bytes": len(data),
                    "cache_path": "(local, fetched earlier)", "cache_reused": True,
                    "license": UA_NOTE, "local_cif": _relative(out),
                    "fetched_at": "earlier run",
                    "note": "本次 --force 未启用，沿用已有本地 CIF（无上次 provenance 记录）",
                }
            rows.append(row)
            print(f"[skip] {entry['key']:22s} 已有 {out.name}")
            continue
        t = time.time()
        try:
            row = fetch_cod(entry) if entry["source"] == "COD" else fetch_aflow(entry)
        except Exception as exc:  # noqa: BLE001 - 网络失败要明确报出来，不静默
            print(f"[FAIL] {entry['key']:22s} {type(exc).__name__}: {exc}")
            continue
        rows.append(row)
        print(f"[ok]   {entry['key']:22s} {row['source']:5s} sha256={row['sha256'][:12]}… "
              f"{row['bytes']:6d} B  {time.time() - t:4.1f}s")
    PROVENANCE_JSON.write_text(
        json.dumps({"note": UA_NOTE, "entries": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nprovenance → {PROVENANCE_JSON}")
    print(f"共 {len(rows)}/{len(EXAMPLES)} 条；总耗时 {time.time() - t_all:.1f}s")
    return 0 if len(rows) == len(EXAMPLES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
