#!/usr/bin/env python3
"""Does the repair stage actually make a disordered structure exportable? (round 56)

The 320-structure corpus found that **147 of 320 real CoRE MOF structures carry partial
occupancies**, and 22 of the 31 formats cannot express them.  That is a product-level
question, not a cosmetic one, so this script answers it end to end:

    raw CIF  ->  standardize/repair (disorder resolution)  ->  export all formats

and reports, per structure: whether disorder was resolved, whether the resolved
structure is ordered, and how many formats then export successfully.

    .venv\\Scripts\\python.exe scripts\\disorder_pipeline_check.py --limit 40
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BULK = ROOT / "_cache" / "core-mof-2024" / "bulk"


def check_one(path_str: str) -> dict:
    from pymatgen.core import Structure

    from cifkit.export import supported_formats, write_structure
    from cifkit.export.disorder_guard import ORDERED_ONLY, structure_is_ordered
    from cifkit.export.format_limits import ATOM_LIMITS, FormatLimitError

    path = Path(path_str)
    row: dict = {"structure": path.name}
    try:
        raw = Structure.from_file(path)
    except Exception as exc:  # noqa: BLE001
        row["error"] = f"load: {type(exc).__name__}: {exc}"
        return row
    row["natoms"] = len(raw)
    row["ordered_before"] = structure_is_ordered(raw)

    # the pipeline's repair stage: what does the project itself use?
    resolved = raw
    row["repair"] = None
    try:
        from cifkit.repair import repair_all

        # the project's real repair stage: disorder -> contacts -> H -> valence
        cif_text = path.read_text(encoding="utf-8", errors="replace")
        resolved, report = repair_all(raw, resolve_disorder=True,
                                      remove_close_contacts=False,
                                      add_hydrogen=False, cif_text=cif_text)
        row["repair"] = {
            "resolved_disorder": getattr(report, "resolved_disorder", None),
            "warnings": list(getattr(report, "warnings", []) or [])[:3],
            "actions": list(getattr(report, "actions", []) or [])[:3],
        }
    except Exception as exc:  # noqa: BLE001
        row["repair_error"] = f"{type(exc).__name__}: {exc}"

    row["ordered_after"] = structure_is_ordered(resolved)
    row["natoms_after"] = len(resolved)

    exported, unsupported, failed = [], [], []
    with tempfile.TemporaryDirectory() as tmp:
        for fmt in sorted(supported_formats()):
            limit = ATOM_LIMITS.get(fmt)
            if limit and len(resolved) > limit[0]:
                unsupported.append(fmt)
                continue
            if fmt in ORDERED_ONLY and not row["ordered_after"]:
                unsupported.append(fmt)
                continue
            try:
                write_structure(resolved, Path(tmp) / f"x.{fmt}", fmt=fmt)
                exported.append(fmt)
            except FormatLimitError:
                unsupported.append(fmt)
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{fmt}:{type(exc).__name__}")
    row["n_formats_exported"] = len(exported)
    row["n_unsupported"] = len(unsupported)
    row["failed_formats"] = failed
    row["ok"] = not failed
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--only-disordered", action="store_true",
                    help="restrict to the structures the corpus flagged as disordered")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--json", default=str(ROOT / "runs" / "disorder_pipeline.json"))
    args = ap.parse_args()

    files = sorted(BULK.glob("*.cif"))
    if args.only_disordered:
        listing = ROOT / "runs" / "_disordered_list.json"
        wanted = set(json.loads(listing.read_text(encoding="utf-8"))) if listing.is_file() else set()
        files = [path for path in files if path.name in wanted]
    files = files[: args.limit]
    started = time.time()
    with mp.get_context("spawn").Pool(processes=args.jobs) as pool:
        rows = pool.map(check_one, [str(path) for path in files], chunksize=1)
    elapsed = time.time() - started

    disorder = [row for row in rows if row.get("ordered_before") is False]
    resolved = [row for row in disorder if row.get("ordered_after")]
    payload = {
        "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "n_checked": len(rows), "seconds": round(elapsed, 1),
        "n_disordered_before": len(disorder),
        "n_disordered_after_repair": len([row for row in disorder
                                          if not row.get("ordered_after")]),
        "n_resolved": len(resolved),
        "n_with_failed_formats": len([row for row in rows if row.get("failed_formats")]),
        "results": rows,
    }
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"checked {payload['n_checked']} structures in {elapsed:.1f}s")
    print(f"disordered before repair : {len(disorder)}")
    print(f"still disordered after   : {payload['n_disordered_after_repair']}")
    print(f"structures with failures : {payload['n_with_failed_formats']}")
    if disorder:
        sample = disorder[0]
        print(f"sample {sample['structure']}: natoms {sample.get('natoms')} -> "
              f"{sample.get('natoms_after')}, ordered {sample.get('ordered_before')} -> "
              f"{sample.get('ordered_after')}, exported "
              f"{sample.get('n_formats_exported')}/31, repair={str(sample.get('repair'))[:80]}")
    for row in rows:
        if row.get("failed_formats"):
            print(f"  FAIL {row['structure']}: {row['failed_formats'][:4]}")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
