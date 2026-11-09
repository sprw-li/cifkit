"""Independent format round-trip verification (cif → anything).

Writes one structure in every supported format and reads it back with a
**different library than the writer** where one exists (pymatgen vs ASE vs a
structural/textual check), so ``docs/EXPORT.md`` claims can be backed by an
external reader rather than the writer's own self-check.

    .venv\\Scripts\\python.exe scripts\\verify_formats.py [--json OUT] [--structure FILE]

Exit code 0 when every format writes and (where a reader exists) reads back with
the same atom count; 1 otherwise.  Formats with no third-party reader are
reported as ``structural-check`` rather than being called verified.
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
    from pymatgen.core import Structure

    return len(Structure.from_file(str(path)))


def _read_ase(path: Path, fmt: str) -> int:
    import ase.io

    return len(ase.io.read(str(path), format=fmt))


def _check_template(path: Path, fmt: str) -> tuple[bool, str]:
    """Structural check for template inputs: required keywords present."""
    text = path.read_text(encoding="utf-8", errors="replace")
    required = {
        "cp2k": ("&CELL", "&COORD"),
        "siesta": ("LatticeVectors", "AtomicCoordinates"),
        "abacus": ("ATOMIC_SPECIES", "ATOMIC_POSITIONS"),
        "orca": ("* xyz", "!"),
        "dftb": ("Geometry",),
    }[fmt]
    missing = [kw for kw in required if kw not in text]
    return (not missing), ("ok" if not missing else f"missing {missing}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--structure", default=str(DEFAULT_STRUCTURE))
    ap.add_argument("--outdir", default=str(ROOT / "runs" / "verify_formats"))
    ap.add_argument("--json", default=None, help="JSON report path (default <outdir>/verify_formats.json)")
    ap.add_argument("--only", default=None, help="逗号分隔的格式子集（测试/快速检查用）")
    args = ap.parse_args()

    from cifkit import export

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
        except Exception as exc:  # noqa: BLE001
            row["error"] = f"write: {type(exc).__name__}: {exc}"
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
            reader_lib = "structural-check"
            ok, detail = _check_template(path, fmt)
            back = natoms if ok else None
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
        rows.append(row)

    bundles: list[dict] = []
    for code in ([] if args.only else sorted(export.supported_bundles())):
        info = export.write_bundle(structure, code, outdir / "bundles" / code, title="verify")
        files = [outdir / "bundles" / code / name for name in info["files"]]
        bundles.append({
            "code": code,
            "files": info["files"],
            "all_present": all(f.is_file() and f.stat().st_size > 0 for f in files),
            "missing_declared": info.get("missing", []),
            "readme": (outdir / "bundles" / code / "README.md").is_file(),
        })

    ok_formats = [r for r in rows if r["ok"]]
    third_party = [r for r in rows if r["reader"] in ("pymatgen", "ase")]
    report = {
        "structure": str(structure_path),
        "natoms": natoms,
        "n_formats": len(rows),
        "n_ok": len(ok_formats),
        "n_third_party_readback": len(third_party),
        "n_third_party_ok": sum(1 for r in third_party if r["ok"]),
        "formats": rows,
        "bundles": bundles,
        "n_bundles": len(bundles),
        "bundles_ok": all(b["all_present"] and b["readme"] for b in bundles) if bundles else None,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "note": (
            "第三方回读 = 用与写出器不同的库（pymatgen/ASE）读回并比对原子数。"
            "**回读一致 ≠ 目标软件接受**：这只说明另一个库能解析出同样多的原子，"
            "不代表 VASP/QE/CP2K/... 会接受该输入。模板类格式（cp2k/siesta/abacus/orca/dftb）"
            "与 png 只用关键字/魔数检查，不算第三方回读；模板不包含 POTCAR/UPF/basis/skf/力场，"
            "也从未在真实软件中运行过。"
        ),
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"formats: {report['n_ok']}/{report['n_formats']} ok; "
          f"third-party readback {report['n_third_party_ok']}/{report['n_third_party_readback']} ok")
    for row in rows:
        flag = "ok  " if row["ok"] else "FAIL"
        print(f"  [{flag}] {row['format']:10s} {row.get('reader','?'):16s} "
              f"{row.get('natoms_readback')}/{natoms}  {row.get('error','')}")
    print(f"bundles: {report['n_bundles']} written, all files+README: {report['bundles_ok']}")
    print(f"report: {json_path}")
    bundles_ok = report["bundles_ok"] if report["bundles_ok"] is not None else True
    return 0 if report["n_ok"] == report["n_formats"] and bundles_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
