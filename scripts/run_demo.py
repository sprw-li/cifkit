"""Demo：用户原话一条管线跑通 + 独立验收。

用法：
    .venv\Scripts\python.exe scripts\run_demo.py [--outdir runs/demo_sod_zif8] [--fresh]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEMO = (
    "帮我下载典型的RCSR为sod的mof，需要碳上补充氢，创建一个2x2x1的超胞（Supercell），"
    "沿(111)面切出表面，并加上15Å的真空层，导出为计算化学软件使用的格式。"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="runs/demo_sod_zif8")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--skip-verify", action="store_true")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    if args.fresh and outdir.exists():
        shutil.rmtree(outdir)

    from cifkit.pipeline import run
    from cifkit.spec import describe_spec, parse_request

    spec = parse_request(DEMO, outdir=outdir)
    print(describe_spec(spec))
    t0 = time.time()
    result = run(spec, ingest_run=True)
    print(f"\n管线结束 ok={result.ok} 用时 {time.time() - t0:.1f}s -> {outdir}")
    if not args.skip_verify:
        rc = subprocess.call([sys.executable, str(ROOT / "scripts" / "verify_demo.py"), str(outdir)])
        return 0 if result.ok and rc == 0 else 1
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
