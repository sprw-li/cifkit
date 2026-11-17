"""Independent format round-trip verification (cif → anything).

Writes one structure in every supported format and reads it back with a
**different library than the writer** where one exists (pymatgen vs ASE vs a
structural/textual check), so ``docs/EXPORT.md`` claims can be backed by an
external reader rather than the writer's own self-check.

    .venv\\Scripts\\python.exe scripts\\verify_formats.py [--json OUT] [--structure FILE]

Exit code 0 when every *representable* format writes and (where a reader exists) reads
back with the same atom count; 1 otherwise.  A typed refusal
(``ExportRefusalError``: disordered / format-limit / cell-not-representable) is
reported as ``unsupported`` and is explicitly **not** a failure — the honest refusal
is the correct behaviour.  Formats with no third-party reader are reported as
``structural-check`` rather than being called verified.

Round 58: ``dftb`` is checked as the *single-format* product it actually is — the
written ``structure.dftb`` together with its sibling ``geo.gen`` — instead of
switching to the bundle directory, which used to hide that a bare ``--to dftb``
could write the HSD without the geometry it references.  The ``dftb`` bundle is
verified separately (files + README + a real hsd/geo.gen parse).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_STRUCTURE = ROOT / "tests" / "data" / "zif8_cr_sod.cif"

#: format -> (library, reader) used for the independent read-back.
#: pymatgen is preferred for crystallographic formats, ASE for the rest.
PYMATGEN_READERS = {"cif", "json", "vasp"}
ASE_READERS = {
    "xyz": "xyz",
    "extxyz": "extxyz",
    "pdb": "proteindatabank",
    "sdf": "sdf",
    "mol": "mol",
    "cfg": "cfg",
    "gromacs": "gromacs",
    "gen": "gen",
    "aims": "aims",
    "castep": "castep-cell",
    "abinit": "abinit-in",
    "crystal": "crystal",
    "gaussian": "gaussian-in",
    "nwchem": "nwchem-in",
    "onetep": "onetep-in",
    "dmol": "dmol-arc",
    "turbomole": "turbomole",
    "res": "res",
    "struct": "struct",
    "lammps": "lammps-data",
    "qe": "espresso-in",
    "xsf": "xsf",
}
#: formats that are input templates (no reader): verified structurally instead
TEMPLATES = {"cp2k", "siesta", "abacus", "orca", "dftb"}
#: binary/derived outputs
SPECIAL = {"png"}


def _read_pymatgen(path: Path) -> int:
    return len(_read_pymatgen_structure(path))


def _read_pymatgen_structure(path: Path):
    """Read with pymatgen and return the structure itself (used for geometry checks)."""
    from pymatgen.core import Structure

    return Structure.from_file(str(path))


def _read_ase(path: Path, fmt: str) -> int:
    return len(_read_ase_object(path, fmt))


def _read_ase_object(path: Path, fmt: str):
    """Read with ASE and return the Atoms object (used for geometry checks)."""
    import ase.io

    return ase.io.read(str(path), format=fmt)


def _check_template(path: Path, fmt: str) -> tuple[bool, str, int | None]:
    """Strict in-house parse of a template export.

    Round 38: the previous check only looked for keywords, so a truncated
    coordinate block would still pass.  ``cifkit.export.template_check`` parses
    the actual structure blocks and validates the atom count / element set / cell.
    No independent reader exists for these formats (see
    ``runs/probe_template_readers.json``), so this is honest in-house verification,
    not a third-party read-back.
    """
    from cifkit.export.template_check import check_template

    companion: dict[str, str] = {}
    if fmt == "dftb":
        gen = path.parent / "geo.gen"
        if gen.is_file():
            companion["geo.gen"] = gen.read_text(encoding="utf-8", errors="replace")
    text = path.read_text(encoding="utf-8", errors="replace")
    report = check_template(fmt, text, companion)
    detail = "ok" if report.ok else "; ".join(report.errors[:3])
    return report.ok, detail, report.natoms


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--structure", default=str(DEFAULT_STRUCTURE))
    ap.add_argument("--outdir", default=str(ROOT / "runs" / "verify_formats"))
    ap.add_argument("--json", default=None, help="JSON report path (default <outdir>/verify_formats.json)")
    ap.add_argument("--only", default=None, help="逗号分隔的格式子集（测试/快速检查用）")
    args = ap.parse_args()

    from cifkit import export

    from cifkit.export.refusals import ExportRefusalError, refusal_reason

    structure_path = Path(args.structure)
    if not structure_path.is_file():
        print(f"error: structure not found: {structure_path}", file=sys.stderr)
        return 2
    from pymatgen.core import Structure

    structure = Structure.from_file(str(structure_path))
    natoms = len(structure)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    json_path = Path(args.json) if args.json else outdir / "verify_formats.json"

    rows: list[dict] = []
    formats = sorted(export.supported_formats())
    if args.only:
        wanted = [f.strip().lower() for f in args.only.split(',') if f.strip()]
        try:
            wanted = [export.normalize_format(f) for f in wanted]
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        unknown = [f for f in wanted if f not in formats]
        if unknown:
            print(f"error: unknown format(s): {unknown}", file=sys.stderr)
            return 2
        formats = wanted
    for fmt in formats:
        path = outdir / f"structure.{fmt}"
        row: dict = {"format": fmt, "natoms_expected": natoms, "ok": False}
        t0 = time.time()
        try:
            export.write_structure(structure, path, fmt, title="verify_formats")
            row["bytes"] = path.stat().st_size
        except ExportRefusalError as exc:
            # the writer *correctly* refused: this format cannot represent the
            # structure/cell.  Counted as unsupported, never as a failure (round 58).
            row["unsupported"] = refusal_reason(exc)
            row["seconds"] = round(time.time() - t0, 3)
            rows.append(row)
            continue
        except Exception as exc:  # noqa: BLE001
            row["error"] = f"write: {type(exc).__name__}: {exc}"
            row["seconds"] = round(time.time() - t0, 3)
            rows.append(row)
            continue

        if fmt == "dftb":
            # DFTB+'s input is a *pair*: dftb_in.hsd references its sibling geo.gen.
            # Round 58: the single-format writer now writes that companion itself,
            # so verify **this** product (the file we just wrote + its sibling
            # geo.gen) — never the separate bundle directory, which used to stand in
            # for it and hid the fact that bare `--to dftb` wrote an unusable
            # half-product.  The bundle keeps its own check in the bundle loop below.
            ok, detail, parsed = _check_template(path, "dftb")
            companion = path.parent / "geo.gen"
            row["parsed_natoms"] = parsed
            row["reader"] = "strict-parse (in-house, single file + sibling geo.gen)"
            row["companion"] = companion.name if companion.is_file() else None
            row["companion_bytes"] = companion.stat().st_size if companion.is_file() else 0
            row["bytes"] = path.stat().st_size
            if not ok:
                row["error"] = f"template: {detail}"
            row["natoms_readback"] = parsed if ok else None
            row["ok"] = bool(ok) and parsed == natoms and not row.get("error")
            row["seconds"] = round(time.time() - t0, 3)
            rows.append(row)
            continue

        if fmt in PYMATGEN_READERS:
            reader_lib = "pymatgen"
            try:
                back = _read_pymatgen(path)
            except Exception as exc:  # noqa: BLE001
                back = None
                row["error"] = f"read({reader_lib}): {type(exc).__name__}: {exc}"
        elif fmt in ASE_READERS:
            reader_lib = "ase"
            try:
                back = _read_ase(path, ASE_READERS[fmt])
            except Exception as exc:  # noqa: BLE001
                back = None
                row["error"] = f"read({reader_lib}): {type(exc).__name__}: {exc}"
        elif fmt in TEMPLATES:
            reader_lib = "strict-parse (in-house)"
            ok, detail, parsed = _check_template(path, fmt)
            back = parsed if ok else None
            row["parsed_natoms"] = parsed
            if not ok:
                row["error"] = f"template: {detail}"
        elif fmt in SPECIAL:
            reader_lib = "magic-bytes"
            ok = path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
            back = natoms if ok else None
            if not ok:
                row["error"] = "not a PNG"
        else:  # pragma: no cover - every format is classified above
            reader_lib = "none"
            back = None
            row["error"] = "no reader registered"

        row["reader"] = reader_lib
        row["natoms_readback"] = back
        row["ok"] = back == natoms and not row.get("error")
        row["seconds"] = round(time.time() - t0, 3)

        # round 44: a matching atom count is not enough - compare the geometry
        if row["ok"] and reader_lib in ("pymatgen", "ase"):
            from cifkit.export.geometry_check import compare

            try:
                if reader_lib == "pymatgen":
                    back_structure = _read_pymatgen_structure(path)
                else:
                    back_structure = _read_ase_object(path, ASE_READERS[fmt])
                verdict = compare(structure, back_structure, fmt)
            except Exception as exc:  # noqa: BLE001
                verdict = None
                row["geometry_error"] = f"{type(exc).__name__}: {exc}"
            if verdict is not None:
                row["geometry"] = verdict.as_dict()
                if not verdict.ok:
                    row["ok"] = False
                    row["error"] = f"geometry: {verdict.detail}"
        rows.append(row)

    bundles: list[dict] = []
    # Round 58: with --only dftb the *bundle* must still be verified too, otherwise a
    # single-format run could hide whether the bundle and the bare product agree.
    bundle_codes = (sorted(export.supported_bundles()) if not args.only
                    else (["dftb"] if "dftb" in formats else []))
    for code in bundle_codes:
        bdir = outdir / "bundles" / code
        entry: dict = {"code": code, "files": [], "all_present": False, "readme": False}
        try:
            info = export.write_bundle(structure, code, bdir, title="verify")
            files = [bdir / name for name in info["files"]]
            entry.update({
                "files": info["files"],
                "all_present": all(f.is_file() and f.stat().st_size > 0 for f in files),
                "missing_declared": info.get("missing", []),
                "readme": (bdir / "README.md").is_file(),
            })
            if code == "dftb":
                # verify the bundle's *content* as well: hsd + its sibling geo.gen
                # must parse to the same atom count (not just exist).
                ok, detail, parsed = _check_template(bdir / "dftb_in.hsd", "dftb")
                entry["template_ok"] = bool(ok)
                entry["template_natoms"] = parsed
                entry["companion"] = "geo.gen"
                if not ok:
                    entry["template_error"] = detail
        except ExportRefusalError as exc:
            entry["unsupported"] = refusal_reason(exc)
        except Exception as exc:  # noqa: BLE001
            entry["error"] = f"{type(exc).__name__}: {exc}"
        bundles.append(entry)

    def _bundle_ok(bundle: dict) -> bool:
        """A bundle is ok when its files/README are present and, for dftb, its
        hsd+geo.gen pair actually parses to the expected atom count."""
        return (bool(bundle.get("all_present")) and bool(bundle.get("readme"))
                and bundle.get("template_ok", True) is not False)

    ok_formats = [r for r in rows if r["ok"]]
    unsupported_formats = [r for r in rows if r.get("unsupported")]
    bad_formats = [r for r in rows if not r["ok"] and not r.get("unsupported")]
    third_party = [r for r in rows if r.get("reader") in ("pymatgen", "ase")]
    geometry_checked = [row for row in rows if row.get("geometry")]
    geometry_failures = [row["format"] for row in geometry_checked
                         if not row["geometry"]["ok"]]
    worst = max((row["geometry"]["max_deviation_A"] or 0.0 for row in geometry_checked),
                default=None)
    print(f"geometry checked: {len(geometry_checked)} formats, "
          f"failures={geometry_failures}, worst deviation={worst}")
    report = {
        "structure": str(structure_path),
        "natoms": natoms,
        "n_formats": len(rows),
        "n_ok": len(ok_formats),
        "n_unsupported": len(unsupported_formats),
        "n_bad": len(bad_formats),
        "unsupported_formats": [r["format"] for r in unsupported_formats],
        "bad_formats": [r["format"] for r in bad_formats],
        "all_representable_ok": not bad_formats,
        "n_third_party_readback": len(third_party),
        "n_third_party_ok": sum(1 for r in third_party if r["ok"]),
        "formats": rows,
        "bundles": bundles,
        "n_bundles": len(bundles),
        "bundles_ok": all(_bundle_ok(b) for b in bundles if "unsupported" not in b)
                      if bundles else None,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "n_geometry_checked": len(geometry_checked),
        "geometry_failures": geometry_failures,
        "worst_deviation_A": worst,
        "accounting": (
            "ok = written and verified; unsupported = the writer correctly refused a "
            "structure/cell the format cannot represent (typed ExportRefusalError), "
            "never counted as a failure; bad = a real failure. all_representable_ok "
            "is therefore the honest 'everything representable passed' claim."),
        "note": (
            "第三方回读 = 用与写出器不同的库（pymatgen/ASE）读回并比对原子数。"
            "**回读一致 ≠ 目标软件接受**：这只说明另一个库能解析出同样多的原子，"
            "不代表 VASP/QE/CP2K/... 会接受该输入。模板类格式（cp2k/siesta/abacus/orca/dftb）"
            "与 png 只用关键字/魔数检查，不算第三方回读；模板不包含 POTCAR/UPF/basis/skf/力场，"
            "也从未在真实软件中运行过。"
            "dftb 单文件产物（structure.dftb）与其同级 geo.gen 配对校验；bundles/dftb 另行校验，"
            "不再用 bundle 目录顶替裸 --to 产物。"
        ),
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    # atomic (round 57): the format-check report is named in LIMITATIONS G4 as a
    # "不会读到半个文件" file — honour that with the shared atomic writer
    from cifkit.locks import atomic_write_json

    atomic_write_json(json_path, report)

    print(f"formats: {report['n_ok']}/{report['n_formats']} ok; "
          f"third-party readback {report['n_third_party_ok']}/{report['n_third_party_readback']} ok; "
          f"unsupported={report['unsupported_formats']}; bad={report['bad_formats']}")
    for row in rows:
        flag = ("ok  " if row["ok"]
                else ("n/a " if row.get("unsupported") else "FAIL"))
        detail = row.get("error") or row.get("unsupported") or ""
        print(f"  [{flag}] {row['format']:10s} {row.get('reader','?'):16s} "
              f"{row.get('natoms_readback')}/{natoms}  {detail}")
    print(f"bundles: {report['n_bundles']} written, all files+README(+dftb parse): "
          f"{report['bundles_ok']}")
    print(f"report: {json_path}")
    bundles_ok = report["bundles_ok"] if report["bundles_ok"] is not None else True
    return 0 if report["all_representable_ok"] and bundles_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
