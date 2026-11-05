"""Bootstrap the CoRE MOF 2024 cache used by ``cifkit fetch`` / ``cifkit pipeline``.

Fresh machine::

    .venv\\Scripts\\python.exe scripts\\bootstrap_data.py

Downloads (Zenodo record 15055758, CC-BY-4.0, ~45 MB total) into
``_cache/core-mof-2024/``:

* ``CoREMOF2024DB.zip``           8300 CIFs (SI/CR + SI/NCR)
* ``ASR_data_SI_20250204.csv``    topology metadata for 1372 ASR structures
* ``NCR_ASR_SI.xlsx``             QC flags for the NCR (raw) structures

The script is idempotent: existing files are verified by size and skipped unless
``--force`` is given; downloads retry 3 times.  ``--check`` verifies the cache
without downloading (exit code 1 when anything is missing).  It also prints
sha256 so provenance can be checked later.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = "https://zenodo.org/records/15055758/files/"
FILES = {
    "CoREMOF2024DB.zip": None,  # size checked loosely; large binary
    "ASR_data_SI_20250204.csv": None,
    "NCR_ASR_SI.xlsx": None,
}
MIN_SIZES = {
    "CoREMOF2024DB.zip": 40_000_000,
    "ASR_data_SI_20250204.csv": 500_000,
    "NCR_ASR_SI.xlsx": 100_000,
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_once(url: str, tmp: Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as resp, tmp.open("wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        read = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            read += len(chunk)
            if total and read % (10 << 20) < (1 << 20):
                print(f"  {read/1e6:.1f}/{total/1e6:.1f} MB", flush=True)


def download(name: str, dest: Path, *, force: bool = False) -> dict:
    min_size = MIN_SIZES.get(name, 0)
    if dest.is_file() and dest.stat().st_size >= min_size and not force:
        return {"file": name, "status": "cached", "bytes": dest.stat().st_size, "sha256": sha256(dest)}
    url = BASE + name + "?download=1"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"downloading {name} <- {url}", flush=True)
    t0 = time.time()
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            _download_once(url, tmp)
            last_error = None
            break
        except Exception as exc:  # noqa: BLE001 - retry transient network errors
            last_error = exc
            print(f"  attempt {attempt + 1}/3 failed: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(1.5 * (attempt + 1))
    if last_error is not None:
        raise RuntimeError(f"{name} 下载失败（已重试 3 次）：{last_error}") from last_error
    if tmp.stat().st_size < min_size:
        raise RuntimeError(f"{name} 下载不完整：{tmp.stat().st_size} B < {min_size} B")
    tmp.replace(dest)
    return {
        "file": name,
        "status": "downloaded",
        "bytes": dest.stat().st_size,
        "sha256": sha256(dest),
        "url": url,
        "elapsed_s": round(time.time() - t0, 1),
    }


def check_cache(outdir: Path, *, as_json: bool = False) -> int:
    """Verify that every expected cache file exists with a plausible size."""
    rows = []
    ok = True
    for name in FILES:
        path = outdir / name
        size = path.stat().st_size if path.is_file() else 0
        good = path.is_file() and size >= MIN_SIZES.get(name, 0)
        ok = ok and good
        rows.append({"file": name, "status": "ok" if good else "MISSING", "bytes": size})
    if as_json:
        print(json.dumps({"cache": str(outdir), "ok": ok, "files": rows}, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(f"{row['status']:8s} {row['file']:<30s} {row['bytes']/1e6:8.2f} MB")
        print(f"\n{'cache OK: ' + str(outdir) if ok else 'cache MISSING files — 运行: python scripts/bootstrap_data.py'}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="只检查缓存完整性（不下载）：缺失/过小返回非 0")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    from cifkit.sources.core_mof import dataset_dir

    outdir = dataset_dir()
    if args.check:
        return check_cache(outdir, as_json=args.json)

    records = [download(name, outdir / name, force=args.force) for name in FILES]
    meta = {
        "dataset": "CoRE MOF 2024 v1.1",
        "dataset_doi": "10.5281/zenodo.15055758",
        "license": "CC-BY-4.0",
        "record_url": "https://zenodo.org/records/15055758",
        "files": records,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    (outdir / "SOURCES.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(meta, ensure_ascii=False, indent=2))
    else:
        for r in records:
            print(f"{r['status']:10s} {r['file']}  {r['bytes']/1e6:.1f} MB  sha256={r['sha256'][:16]}...")
        print(f"\ncache: {outdir}")
        print(f"下一步：.venv\\Scripts\\python.exe -m cifkit selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
