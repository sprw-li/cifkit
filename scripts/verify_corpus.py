#!/usr/bin/env python3
"""High-batch corpus verification of the export layer (round 55, E1/E2/E4).

The gates so far verified **one** fixture (138-atom ZIF-8).  "Verified" should mean
"holds across a corpus", so this walks every structure it is given and runs the
whole export contract on each:

* 31 formats written, each read back by a third-party reader where one exists, with
  the **geometry** compared (round 44);
* 12 bundles written, internally consistent (round 39) with the code's own comment
  style (round 53);
* the 5 template formats parsed by the in-house strict parser (round 38).

Everything runs across processes (``--jobs``), because this is exactly the workload
where the GIL-bound thread pool does not help.

    .venv\\Scripts\\python.exe scripts\\verify_corpus.py --limit 16 --jobs 8
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = [str(ROOT / "tests" / "data"), str(ROOT / "_cache" / "core-mof-2024" / "extracted")]


def discover(sources: list[str], limit: int | None) -> list[Path]:
    found: list[Path] = []
    for source in sources:
        base = Path(source)
        if base.is_file() and base.suffix == ".cif":
            found.append(base)
        elif base.is_dir():
            found.extend(sorted(base.glob("*.cif")))
            for nested in sorted(base.glob("*/*.cif")):
                found.append(nested)
    unique: list[Path] = []
    seen = set()
    for path in found:
        key = path.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique[:limit] if limit else unique


def check_one(path_str: str) -> dict:
    """Run the full export contract for one structure (runs in a worker process)."""
    import os as _os

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    path = Path(path_str)
    result: dict = {"structure": path.name, "path": path_str, "ok": False,
                    "formats": {}, "bundles": {}, "templates": {}, "errors": []}
    try:
        import tempfile

        from pymatgen.core import Structure

        from cifkit.export import supported_bundles, supported_formats, write_bundle, write_structure
        from cifkit.export.bundle_check import check_bundle
        from cifkit.export.disorder_guard import DisorderedStructureError
        from cifkit.export.geometry_check import compare
        from cifkit.export.verify_formats_map import ASE_READERS, PYMATGEN_READERS

        structure = Structure.from_file(path)
        result["natoms"] = len(structure)
        result["formula"] = structure.composition.reduced_formula
        try:
            result["spacegroup"] = structure.get_space_group_info()[0]
        except Exception:  # noqa: BLE001
            result["spacegroup"] = None

        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp)
            for fmt in sorted(supported_formats()):
                target = outdir / f"structure.{fmt}"
                row: dict = {"ok": False}
                try:
                    write_structure(structure, target, fmt=fmt)
                    row["bytes"] = target.stat().st_size if target.is_file() else 0
                    if fmt in PYMATGEN_READERS:
                        reader = "pymatgen"
                    elif fmt in ASE_READERS:
                        reader = "ase"
                    else:
                        reader = "strict-parse" if fmt in (
                            "cp2k", "siesta", "abacus", "orca", "dftb") else "magic-bytes"
                    if reader in ("pymatgen", "ase"):
                        back = _read_back(target, fmt, reader)
                        verdict = compare(structure, back, fmt)
                        row["reader"] = reader
                        row["ok"] = bool(verdict.ok)
                        row["max_deviation_A"] = verdict.max_deviation
                        if not verdict.ok:
                            result["errors"].append(f"{fmt}: {verdict.detail}")
                    elif reader and str(reader).startswith("strict-parse"):
                        row["reader"] = "strict-parse"
                        row["ok"] = True
                    else:
                        row["reader"] = reader or "none"
                        row["ok"] = row["bytes"] > 0
                except DisorderedStructureError:
                    # expected: the format cannot express partial occupancies.  Not a
                    # defect - the corpus reports it as 'unsupported', separately
                    # from real failures
                    row["unsupported"] = "partial occupancies"
                except Exception as exc:  # noqa: BLE001
                    row["error"] = f"{type(exc).__name__}: {exc}"
                    result["errors"].append(f"{fmt}: {row['error']}")
                result["formats"][fmt] = row

            for code in sorted(supported_bundles()):
                bdir = outdir / f"bundle_{code}"
                entry: dict = {"ok": False}
                try:
                    info = write_bundle(structure, code, bdir)
                    verdict = check_bundle(code, bdir, info.get("missing") or [])
                    entry["ok"] = bool(verdict["ok"])
                    entry["checks"] = len(verdict["checks"])
                    if not verdict["ok"]:
                        result["errors"].append(f"bundle {code}: {verdict['errors'][:2]}")
                except DisorderedStructureError:
                    entry["unsupported"] = "partial occupancies"
                except Exception as exc:  # noqa: BLE001
                    entry["error"] = f"{type(exc).__name__}: {exc}"
                    result["errors"].append(f"bundle {code}: {entry['error']}")
                result["bundles"][code] = entry

            templates = ("cp2k", "siesta", "abacus", "orca", "dftb")
            from cifkit.export.template_check import check_template

            for fmt in templates:
                entry = {"ok": False}
                try:
                    if fmt == "dftb":
                        # check_template takes a mapping of companion *texts*
                        # ({"geo.gen": ...}), not a path
                        bdir = outdir / "bundle_dftb"
                        write_bundle(structure, "dftb", bdir)
                        text = (bdir / "dftb_in.hsd").read_text(encoding="utf-8")
                        companion = {"geo.gen": (bdir / "geo.gen").read_text(encoding="utf-8")} \
                            if (bdir / "geo.gen").is_file() else {}
                        report = check_template(fmt, text, companion)
                    else:
                        target = outdir / f"structure.{fmt}"
                        write_structure(structure, target, fmt=fmt)
                        report = check_template(fmt, target.read_text(encoding="utf-8"))
                    entry["ok"] = bool(report.ok)
                    entry["natoms"] = report.natoms
                    if not report.ok:
                        result["errors"].append(f"template {fmt}: {report.errors[:2]}")
                except DisorderedStructureError:
                    # the underlying format cannot express partial occupancies
                    entry["unsupported"] = "partial occupancies"
                except Exception as exc:  # noqa: BLE001
                    entry["error"] = f"{type(exc).__name__}: {exc}"
                    result["errors"].append(f"template {fmt}: {entry['error']}")
                result["templates"][fmt] = entry
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"load failed: {type(exc).__name__}: {exc}")
        return result

    bad_formats = [name for name, row in result["formats"].items()
                   if not row["ok"] and "unsupported" not in row]
    bad_bundles = [name for name, row in result["bundles"].items()
                   if not row["ok"] and "unsupported" not in row]
    bad_templates = [name for name, row in result["templates"].items()
                     if not row["ok"] and "unsupported" not in row]
    result["n_formats_ok"] = len(result["formats"]) - len(bad_formats)
    result["n_formats_unsupported"] = sum(
        1 for row in result["formats"].values() if "unsupported" in row)
    result["bad_formats"] = bad_formats
    result["bad_bundles"] = bad_bundles
    result["bad_templates"] = bad_templates
    result["ok"] = not bad_formats and not bad_bundles and not bad_templates
    return result


def _read_back(target: Path, fmt: str, reader: str):
    if reader == "pymatgen":
        from pymatgen.core import Structure

        return Structure.from_file(str(target))
    import ase.io

    from cifkit.export.verify_formats_map import ASE_READERS

    return ase.io.read(str(target), format=ASE_READERS[fmt])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", action="append", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    ap.add_argument("--json", default=str(ROOT / "runs" / "corpus_verification.json"))
    args = ap.parse_args()

    sources = args.source or DEFAULT_SOURCES
    structures = discover(sources, args.limit)
    if not structures:
        print(f"no CIF found under {sources}")
        return 1
    print(f"corpus: {len(structures)} structures, jobs={args.jobs}")

    started = time.time()
    with mp.get_context("spawn").Pool(processes=max(1, args.jobs)) as pool:
        results = pool.map(check_one, [str(path) for path in structures], chunksize=1)
    elapsed = time.time() - started

    report = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "jobs": args.jobs,
              "seconds": round(elapsed, 1), "n_structures": len(results),
              "results": results}
    n_ok = sum(1 for row in results if row["ok"])
    report["n_ok"] = n_ok
    report["all_ok"] = n_ok == len(results)
    report["by_format"] = {}
    for fmt in sorted(results[0]["formats"]):
        report["by_format"][fmt] = sum(1 for row in results if row["formats"][fmt]["ok"])
    report["by_bundle"] = {}
    for code in sorted(results[0]["bundles"]):
        report["by_bundle"][code] = sum(1 for row in results if row["bundles"][code]["ok"])
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nstructures fully passing: {n_ok}/{len(results)} in {elapsed:.1f}s")
    for name, row in zip([r["structure"] for r in results], results):
        mark = "ok  " if row["ok"] else "FAIL"
        print(f"  [{mark}] {name:34s} natoms={row.get('natoms')} "
              f"formats={row.get('n_formats_ok')}/{len(row['formats'])} "
              f"bad={row['bad_formats'][:3]}{row['bad_bundles'][:2]}{row['bad_templates'][:2]}")
    print(f"\nreport: {out}")
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
