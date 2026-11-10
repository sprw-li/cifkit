"""Bundle consistency gate: write all 12 bundles and check their internal contracts.

    .venv\\Scripts\\python.exe scripts\\check_bundles.py [--json OUT]

Exit 0 only when every bundle's required files exist, its cross-file references
resolve, and everything it declares missing is really absent.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(ROOT / "runs" / "check_bundles.json"))
    ap.add_argument("--structure", default=str(ROOT / "tests" / "data" / "zif8_cr_sod.cif"))
    args = ap.parse_args()

    from pymatgen.core import Structure

    from cifkit.export import supported_bundles, write_bundle
    from cifkit.export.bundle_check import check_bundle

    structure = Structure.from_file(args.structure)
    report: dict = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "structure": args.structure, "natoms": len(structure),
                    "bundles": [], "ok": False}
    with tempfile.TemporaryDirectory() as tmp:
        for code in sorted(supported_bundles()):
            outdir = Path(tmp) / code
            info = write_bundle(structure, code, outdir)
            result = check_bundle(code, outdir, info.get("missing") or [])
            result["files"] = info.get("files")
            report["bundles"].append(result)
            mark = "ok " if result["ok"] else "FAIL"
            print(f"[{mark}] {code:10s} {len(result['checks'])} checks"
                  + ("" if result["ok"] else f"  errors={result['errors']}"))

    passed = sum(1 for item in report["bundles"] if item["ok"])
    report["passed"] = passed
    report["total"] = len(report["bundles"])
    report["ok"] = passed == report["total"]
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nbundles: {passed}/{report['total']} consistent — {out}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
