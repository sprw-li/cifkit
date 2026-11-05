"""Bootstrap the QMOF local mirror used by ``cifkit fetch --source qmof``.

Why a separate script: the QMOF data lives on figshare.  figshare's *file-level*
downloader is blocked from this network (HTTP 403), but the **article-level
version zip** works:

    https://ndownloader.figshare.com/articles/13147324/versions/1   (HTTP 200, ~121 MB)

This script downloads that zip once, extracts the CSV metadata and CIFs into the
layout expected by ``cifkit.sources.qmof``::

    _cache/qmof/
      qmof.csv                 # metadata (name/formula/...)
      structures/*.cif         # one CIF per entry

Usage::

    python scripts/bootstrap_qmof.py --check     # verify mirror without network
    python scripts/bootstrap_qmof.py             # download + extract (idempotent)
    python scripts/bootstrap_qmof.py --force     # re-download

Honesty: the data is a **real download** from the figshare article archive
(sha256 recorded); extraction is local.  If figshare is unreachable, the script
fails with an actionable message instead of silently producing a fake mirror.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ARTICLE_URL = "https://ndownloader.figshare.com/articles/13147324/versions/1"
CACHE_NAME = "qmof"
ARCHIVE_NAME = "qmof_article_v1.zip"
MIN_ARCHIVE_BYTES = 50_000_000  # ~121 MB expected; guard against error pages


def qmof_dir() -> Path:
    from cifkit.sources.qmof import qmof_dir as _dir

    return _dir()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(dest: Path, *, force: bool = False) -> dict:
    if dest.is_file() and dest.stat().st_size >= MIN_ARCHIVE_BYTES and not force:
        return {"status": "cached", "bytes": dest.stat().st_size}
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    print(f"downloading QMOF article zip <- {ARTICLE_URL}", flush=True)
    t0 = time.time()
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(ARTICLE_URL, timeout=300) as resp, tmp.open("wb") as fh:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
            last = None
            break
        except Exception as exc:  # noqa: BLE001 - retry transient network errors
            last = exc
            print(f"  attempt {attempt + 1}/3 failed: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(2.0 * (attempt + 1))
    if last is not None:
        raise RuntimeError(f"QMOF 下载失败（已重试 3 次）：{last}") from last
    if tmp.stat().st_size < MIN_ARCHIVE_BYTES:
        raise RuntimeError(f"QMOF 归档太小（{tmp.stat().st_size} B），可能不是数据包")
    tmp.replace(dest)
    return {"status": "downloaded", "bytes": dest.stat().st_size, "elapsed_s": round(time.time() - t0, 1)}


def _find_members(names: list[str]) -> tuple[str | None, list[str]]:
    """Locate the metadata CSV and the CIF members inside the archive."""
    csv_name = None
    for candidate in ("qmof.csv", "qmof_database.csv", "qmof_metadata.csv"):
        for name in names:
            if name.endswith("/" + candidate) or name == candidate:
                csv_name = name
                break
        if csv_name:
            break
    cifs = [name for name in names if name.lower().endswith(".cif")]
    return csv_name, cifs


def extract(archive: Path, target: Path) -> dict:
    target.mkdir(parents=True, exist_ok=True)
    structures = target / "structures"
    structures.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        csv_name, cifs = _find_members(names)
        if csv_name is None and not cifs:
            raise RuntimeError("QMOF 归档里既没有 CSV 也没有 CIF，无法建立镜像")
        n_csv = 0
        if csv_name:
            (target / "qmof.csv").write_bytes(zf.read(csv_name))
            n_csv = 1
        n_cif = 0
        for name in cifs:
            out = structures / Path(name).name
            out.write_bytes(zf.read(name))
            n_cif += 1
    return {"csv": n_csv, "cifs": n_cif, "structures": str(structures)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查镜像完整性（不下载）")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    target = qmof_dir()
    archive = target / "download" / ARCHIVE_NAME
    if args.check:
        ok = (target / "qmof.csv").is_file() and (target / "structures").is_dir()
        cifs = list((target / "structures").glob("*.cif")) if (target / "structures").is_dir() else []
        info = {"mirror": str(target), "ok": bool(ok and cifs), "cifs": len(cifs),
                "archive": archive.is_file(), "archive_bytes": archive.stat().st_size if archive.is_file() else 0}
        if args.json:
            print(json.dumps(info, ensure_ascii=False, indent=2))
        else:
            print(f"mirror: {target}")
            print(f"csv:    {(target / 'qmof.csv').is_file()}")
            print(f"cifs:   {len(cifs)}")
            print(f"archive:{archive} ({info['archive_bytes']/1e6:.1f} MB)")
            print("OK" if info["ok"] else "MISSING — 运行 python scripts/bootstrap_qmof.py")
        return 0 if info["ok"] else 1

    download = _download(archive, force=args.force)
    extracted = extract(archive, target)
    meta = {
        "dataset": "QMOF Database (figshare article 13147324, version 1)",
        "doi": "10.6084/m9.figshare.13147324",
        "article_url": ARTICLE_URL,
        "archive": str(archive),
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": sha256(archive),
        "download": download,
        "extracted": extracted,
        "note": (
            "figshare 的 file-level 下载在本网络 403，但 article-level versions zip 可用；"
            "本脚本记录归档 sha256，提取 CSV + CIF 到 qmof.csv / structures/。"
        ),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    (target / "SOURCES.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(meta, ensure_ascii=False, indent=2))
    else:
        print(f"downloaded {download['status']}: {archive.stat().st_size/1e6:.1f} MB sha256={meta['archive_sha256'][:16]}...")
        print(f"extracted: csv={extracted['csv']} cifs={extracted['cifs']} -> {extracted['structures']}")
        print(f"mirror: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
