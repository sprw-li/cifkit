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

Account rules (round 58): a row is ``ok`` only when the file was written **and**
read back (or strictly parsed) successfully.  A *typed* refusal — the writer
correctly declined because the format cannot represent the structure/cell
(``DisorderedStructureError`` / ``FormatLimitError`` / ``CellNotRepresentableError``,
all ``ExportRefusalError``) — is counted as ``unsupported`` with its reason, never
as ``bad``.  ``bad`` is reserved for real failures (crash, unreadable read-back,
geometry mismatch), so the report means "everything representable passed;
everything unrepresentable was refused explicitly".

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
    # Round 58 (defect A2): every row carries the *complete* key set from the
    # start, so a structure that fails to load (the first row of a batch, in the
    # reported bug) can no longer KeyError the reporter or empty the aggregation.
    result: dict = {"structure": path.name, "path": path_str, "ok": False,
                    "load_failed": False, "formats": {}, "bundles": {}, "templates": {},
                    "errors": [], "bad_formats": [], "bad_bundles": [],
                    "bad_templates": [], "unsupported_formats": {},
                    "unsupported_bundles": {}, "unsupported_templates": {},
                    "n_formats_ok": 0, "n_formats_unsupported": 0,
                    "n_bundles_ok": 0, "n_bundles_unsupported": 0,
                    "n_templates_ok": 0, "n_templates_unsupported": 0}
    try:
        import tempfile

        from pymatgen.core import Structure

        from cifkit.export import supported_bundles, supported_formats, write_bundle, write_structure
        from cifkit.export.bundle_check import check_bundle
        from cifkit.export.geometry_check import compare
        from cifkit.export.refusals import ExportRefusalError, refusal_reason
        from cifkit.export.template_check import check_template
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
                        # Round 58: actually parse the template instead of assuming
                        # "a file was written, therefore it is fine".  For dftb the
                        # coordinates live in the sibling ``geo.gen`` that the writer
                        # now produces next to the HSD; ``check_template`` refuses a
                        # missing or inconsistent companion, so the "31/31" count
                        # cannot be inflated by an unusable half-product.
                        row["reader"] = "strict-parse"
                        companion: dict[str, str] = {}
                        if fmt == "dftb":
                            gen = outdir / "geo.gen"
                            if gen.is_file():
                                companion["geo.gen"] = gen.read_text(
                                    encoding="utf-8", errors="replace")
                        report = check_template(
                            fmt, target.read_text(encoding="utf-8", errors="replace"),
                            companion)
                        row["template_natoms"] = report.natoms
                        row["ok"] = bool(report.ok)
                        if not report.ok:
                            result["errors"].append(f"{fmt} (template): {report.errors[:2]}")
                    else:
                        row["reader"] = reader or "none"
                        row["ok"] = row["bytes"] > 0
                except ExportRefusalError as exc:
                    # expected: the writer *correctly* refused because the format
                    # cannot represent this structure/cell.  Not a defect - the
                    # corpus reports it as 'unsupported', separately from real
                    # failures (round 58: previously this was a bare ValueError and
                    # landed in the 'bad' bucket).
                    row["unsupported"] = refusal_reason(exc)
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
                except ExportRefusalError as exc:
                    entry["unsupported"] = refusal_reason(exc)
                except Exception as exc:  # noqa: BLE001
                    entry["error"] = f"{type(exc).__name__}: {exc}"
                    result["errors"].append(f"bundle {code}: {entry['error']}")
                result["bundles"][code] = entry

            templates = ("cp2k", "siesta", "abacus", "orca", "dftb")

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
                except ExportRefusalError as exc:
                    # the underlying format cannot express this structure/cell
                    entry["unsupported"] = refusal_reason(exc)
                except Exception as exc:  # noqa: BLE001
                    entry["error"] = f"{type(exc).__name__}: {exc}"
                    result["errors"].append(f"template {fmt}: {entry['error']}")
                result["templates"][fmt] = entry
    except Exception as exc:  # noqa: BLE001
        # Do NOT return early: the row still has to go through the accounting
        # below with its complete key set (round 58, defect A2).
        result["errors"].append(f"load failed: {type(exc).__name__}: {exc}")
        result["load_failed"] = True

    bad_formats = [name for name, row in result["formats"].items()
                   if not row["ok"] and "unsupported" not in row]
    bad_bundles = [name for name, row in result["bundles"].items()
                   if not row["ok"] and "unsupported" not in row]
    bad_templates = [name for name, row in result["templates"].items()
                     if not row["ok"] and "unsupported" not in row]
    result["n_formats_ok"] = sum(1 for row in result["formats"].values() if row["ok"])
    result["n_formats_unsupported"] = sum(
        1 for row in result["formats"].values() if "unsupported" in row)
    result["n_bundles_ok"] = sum(1 for row in result["bundles"].values() if row["ok"])
    result["n_bundles_unsupported"] = sum(
        1 for row in result["bundles"].values() if "unsupported" in row)
    result["n_templates_ok"] = sum(1 for row in result["templates"].values() if row["ok"])
    result["n_templates_unsupported"] = sum(
        1 for row in result["templates"].values() if "unsupported" in row)
    result["unsupported_formats"] = {
        name: row["unsupported"] for name, row in result["formats"].items()
        if "unsupported" in row}
    result["unsupported_bundles"] = {
        name: row["unsupported"] for name, row in result["bundles"].items()
        if "unsupported" in row}
    result["unsupported_templates"] = {
        name: row["unsupported"] for name, row in result["templates"].items()
        if "unsupported" in row}
    result["bad_formats"] = bad_formats
    result["bad_bundles"] = bad_bundles
    result["bad_templates"] = bad_templates
    # ok == "written and verified" (or honestly refused), not "load failed"
    result["ok"] = (not result["load_failed"] and not bad_formats
                    and not bad_bundles and not bad_templates)
    return result


def _read_back(target: Path, fmt: str, reader: str):
    if reader == "pymatgen":
        from pymatgen.core import Structure

        return Structure.from_file(str(target))
    import ase.io

    from cifkit.export.verify_formats_map import ASE_READERS

    return ase.io.read(str(target), format=ASE_READERS[fmt])


def aggregate(results: list[dict]) -> dict:
    """Aggregate per-structure rows into the report's cross-structure counts.

    Round 58 (defect A2): the key set comes from the **union of every row**, never
    from ``results[0]``.  Previously a first row that failed to load had empty
    ``formats``/``bundles`` maps, which silently emptied ``by_format``/``by_bundle``
    for the whole run.  ``*_unsupported`` counts honest refusals separately so the
    headline number can never inflate them into passes.
    """
    def _names(key: str) -> list[str]:
        return sorted({name for row in results for name in (row.get(key) or {})})

    by_format = {fmt: sum(1 for row in results
                          if ((row.get("formats") or {}).get(fmt) or {}).get("ok"))
                 for fmt in _names("formats")}
    by_format_unsupported = {
        fmt: sum(1 for row in results
                 if "unsupported" in ((row.get("formats") or {}).get(fmt) or {}))
        for fmt in _names("formats")}
    by_bundle = {code: sum(1 for row in results
                           if ((row.get("bundles") or {}).get(code) or {}).get("ok"))
                 for code in _names("bundles")}
    by_bundle_unsupported = {
        code: sum(1 for row in results
                  if "unsupported" in ((row.get("bundles") or {}).get(code) or {}))
        for code in _names("bundles")}
    n_ok = sum(1 for row in results if row.get("ok"))
    return {
        "n_ok": n_ok,
        "n_load_failed": sum(1 for row in results if row.get("load_failed")),
        "n_formats_ok_total": sum(int(row.get("n_formats_ok") or 0) for row in results),
        "n_formats_unsupported_total": sum(
            int(row.get("n_formats_unsupported") or 0) for row in results),
        "n_bundles_ok_total": sum(int(row.get("n_bundles_ok") or 0) for row in results),
        "n_bundles_unsupported_total": sum(
            int(row.get("n_bundles_unsupported") or 0) for row in results),
        "by_format": by_format,
        "by_format_unsupported": by_format_unsupported,
        "by_bundle": by_bundle,
        "by_bundle_unsupported": by_bundle_unsupported,
    }


def format_row(row: dict) -> str:
    """One report line per structure (safe on a load-failed row: defect A2)."""
    mark = "ok  " if row.get("ok") else "FAIL"
    formats = row.get("formats") or {}
    unsupported = sorted(row.get("unsupported_formats") or {})
    return (f"  [{mark}] {row.get('structure', '?'):34s} natoms={row.get('natoms')} "
            f"formats={row.get('n_formats_ok', 0)}/{len(formats)} "
            f"unsupported={unsupported} "
            f"bad={(row.get('bad_formats') or [])[:3]}"
            f"{(row.get('bad_bundles') or [])[:2]}{(row.get('bad_templates') or [])[:2]}"
            + (" LOAD-FAILED" if row.get("load_failed") else ""))


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
    report.update(aggregate(results))
    report["all_ok"] = report["n_ok"] == len(results)
    report["accounting"] = (
        "ok = file written AND read back / strictly parsed; unsupported = the writer "
        "correctly refused (typed ExportRefusalError: disordered / format-limit / "
        "cell-not-representable) and is never counted as bad; bad = real failure "
        "(crash, read-back mismatch, unparseable template). all_ok therefore means "
        "'everything representable passed, everything unrepresentable was refused "
        "explicitly'.")
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    from cifkit.locks import atomic_write_json

    atomic_write_json(out, report)

    print(f"\nstructures fully passing: {report['n_ok']}/{len(results)} in {elapsed:.1f}s"
          f" (load failures: {report['n_load_failed']})")
    for row in results:
        print(format_row(row))
        for key, label in (("unsupported_bundles", "unsupported bundles"),
                           ("unsupported_templates", "unsupported templates")):
            if row.get(key):
                print(f"        {label}: "
                      + ", ".join(f"{name} [{str(reason).split(':', 1)[0]}]"
                                  for name, reason in sorted(row[key].items())))
    print(f"\nreport: {out}")
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
