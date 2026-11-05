"""Bootstrap the CoRE MOF 2024 cache used by ``cifkit fetch`` / ``cifkit pipeline``.

Fresh machine::

    .venv\\Scripts\\python.exe scripts\\bootstrap_data.py

Downloads (Zenodo record 15055758, CC-BY-4.0, ~45 MB total) into
``_cache/core-mof-2024/``:

* ``CoREMOF2024DB.zip``           8300 CIFs (SI/CR + SI/NCR)
* ``ASR_data_SI_20250204.csv``    topology metadata for 1372 ASR structures
* ``NCR_ASR_SI.xlsx``             QC flags for the NCR (raw) structures

The script is idempotent: existing files are verified by size and skipped unless
``--force`` is given. It also prints sha256 so provenance can be checked later.
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


def download(name: str, dest: Path, *, force: bool = False) -> dict:
    min_size = MIN_SIZES.get(name, 0)
    if dest.is_file() and dest.stat().st_size >= min_size and not force:
        return {"file": name, "status": "cached", "bytes": dest.stat().st_size, "sha256": sha256(dest)}
    url = BASE + name + "?download=1"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"downloading {name} <- {url}", flush=True)
    t0 = time.time()
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    from cifkit.sources.core_mof import dataset_dir

    outdir = dataset_dir()
    records = [download(name, outdir / name, force=args.force) for name in FILES]
    meta = {
        "dataset": "CoRE MOF 2024 v1.1",
        "dataset_doi": "10.5281/zenodo.15055758",
        "license": "CC-BY-4.0",
        "record_url": "https://zenodo.org/records/15055758",
        "files": records,
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
