"""Advanced use-case subcommands for the cifkit CLI: teach / bravais / metals / fec.

These four commands wrap the reproducible workflows that already live under
``usecases/`` (u1_fd3m, u2_bravais, u3_metals, u4_fec).  They are *imported*
and called as Python functions -- never through ``subprocess`` -- so the CLI
keeps the workbench's single-process, testable behaviour while the individual
scripts stay runnable on their own (``main(argv=None)`` is kept backwards
compatible).

Registering in ``cifkit/cli.py`` (Lead adds these two lines inside
``build_parser``, just before ``return p``)::

    from cifkit.usecases_cli import register as register_usecase_commands
    register_usecase_commands(sub)

Until that registration lands, ``python -m cifkit.usecases_cli <cmd>`` is the
same entry point (this is what ``tests/test_usecase_cli.py`` exercises as a
fallback).

Output contract
---------------
* every command takes ``--outdir`` (required) and writes all deliverables below
  it; the original use-case directories are never modified;
* ``--json`` prints exactly one JSON object on stdout; all progress/log lines
  from the wrapped scripts are re-routed to stderr;
* exit codes: 0 success, 1 runtime error, 2 bad arguments/unsupported request.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import importlib
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
USECASES = ROOT / "usecases"

U1 = USECASES / "u1_fd3m"
U2 = USECASES / "u2_bravais"
U3 = USECASES / "u3_metals"
U4 = USECASES / "u4_fec"

_MODULES: dict[str, Any] = {}

#: accept the usual spellings of the only space group this use case ships.
_FD3M_ALIASES = {"fd3m", "227", "#227", "fd-3m", "f d -3 m"}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _setup_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 - best effort on exotic streams
            pass


def _require_usecases() -> None:
    if not USECASES.is_dir():
        raise FileNotFoundError(
            f"usecases/ directory not found under {ROOT}; run from the cifkit checkout"
        )


def _import_script(directory: Path, module_name: str) -> Any:
    """Import a use-case script module by name with its directory on sys.path."""
    key = f"{directory}::{module_name}"
    if key in _MODULES:
        return _MODULES[key]
    path = directory / f"{module_name}.py"
    if not path.is_file():
        raise FileNotFoundError(f"use-case script not found: {path}")
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    module = importlib.import_module(module_name)
    # guard against a same-named module from another use-case directory
    if Path(module.__file__).resolve() != path.resolve():
        raise ImportError(f"module '{module_name}' resolved to {module.__file__}, expected {path}")
    _MODULES[key] = module
    return module


def _u1_fetch() -> Any:
    return _import_script(U1 / "scripts", "fetch_structures")


def _u1_figure() -> Any:
    return _import_script(U1, "make_figure")


def _u2_bain() -> Any:
    return _import_script(U2 / "scripts", "bain_path")


def _u2_bravais() -> Any:
    return _import_script(U2 / "scripts", "bravais14")


def _u3_export() -> Any:
    return _import_script(U3 / "scripts", "export_metals")


def _u3_finalize() -> Any:
    # finalize_metals imports names from export_metals; import it after the export module.
    _u3_export()
    return _import_script(U3 / "scripts", "finalize_metals")


def _u4_hull() -> Any:
    return _import_script(U4 / "scripts", "build_hull")


def _u4_vasp() -> Any:
    return _import_script(U4 / "scripts", "make_vasp_inputs")


@contextlib.contextmanager
def _quiet(json_mode: bool) -> Iterator[None]:
    """Keep stdout a pure JSON stream in --json mode: script logs go to stderr."""
    if json_mode:
        with contextlib.redirect_stdout(sys.stderr):
            yield
    else:
        yield


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _call(main_fn, argv: list[str], json_mode: bool) -> int:
    """Call a wrapped script's ``main(argv)``; keep stdout pure JSON in --json mode."""
    with _quiet(json_mode):
        return int(main_fn(argv))


def _copy_missing(src: Path, dst: Path) -> int:
    """Copy files (recursively) that do not exist yet; never overwrite user output."""
    if not src.is_dir():
        return 0
    copied = 0
    dst.mkdir(parents=True, exist_ok=True)
    for item in sorted(src.rglob("*")):
        if not item.is_file() or "__pycache__" in item.parts or item.suffix == ".pyc":
            continue
        target = dst / item.relative_to(src)
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        copied += 1
    return copied


def _artifacts(outdir: Path, *, subdir: str | None = None) -> list[dict]:
    base = outdir / subdir if subdir else outdir
    rows: list[dict] = []
    if not base.is_dir():
        return rows
    for path in sorted(base.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        rows.append(
            {"path": path.relative_to(outdir).as_posix(), "bytes": path.stat().st_size}
        )
    return rows


def _zip_dir(outdir: Path, zip_name: str, *, exclude: set[str]) -> Path:
    """Zip the deliverable tree (excluding caches / the archive itself)."""
    zip_path = outdir / zip_name
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(outdir.rglob("*")):
            if not path.is_file() or path == zip_path:
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            rel = path.relative_to(outdir).as_posix()
            if rel in exclude:
                continue
            zf.write(path, rel)
    return zip_path


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _elapsed(t0: float) -> float:
    return round(time.time() - t0, 2)


def _normalize_spacegroup(text: str) -> str:
    return text.strip().lower().replace(" ", "")


# --------------------------------------------------------------------------- #
# teach: Fd-3m examples -> spglib verification -> CSV + PNG
# --------------------------------------------------------------------------- #
def cmd_teach(args: argparse.Namespace) -> int:
    t0 = time.time()
    if _normalize_spacegroup(str(args.spacegroup)) not in {a.replace(" ", "") for a in _FD3M_ALIASES}:
        print(
            f"error: unsupported spacegroup {args.spacegroup!r}; this use case only ships "
            "Fd-3m (#227). Use --spacegroup Fd-3m.",
            file=sys.stderr,
        )
        return 2
    _require_usecases()
    outdir = Path(args.outdir).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    struct_dir = outdir / "data" / "structures"

    cached = _copy_missing(U1 / "data" / "structures", struct_dir)
    missing = [e["key"] for e in _u1_fetch().EXAMPLES if not (struct_dir / f"{e['key']}.cif").is_file()]
    if missing and args.online:
        fetch_rc = _call(_u1_fetch().main, ["--outdir", str(outdir)], args.json)
        if fetch_rc != 0:
            return fetch_rc
        missing = [e["key"] for e in _u1_fetch().EXAMPLES if not (struct_dir / f"{e['key']}.cif").is_file()]
    if missing:
        print(
            f"error: missing {len(missing)} cached CIF(s) {missing}; run without --offline "
            "(network: COD/AFLOW) or provide usecases/u1_fd3m/data/structures",
            file=sys.stderr,
        )
        return 2

    figure_rc = _call(
        _u1_figure().main,
        ["--outdir", str(outdir), "--symprec", str(args.symprec)],
        args.json,
    )
    png = outdir / "figures" / "fd3m_examples.png"
    csv_path = outdir / "data" / "examples.csv"
    rows = _read_csv(csv_path) if csv_path.is_file() else []
    verified = sum(1 for r in rows if str(r.get("verified_227", "")).strip() in {"1", "True", "true"})
    ok = figure_rc == 0 and len(rows) == 6 and verified == 6 and png.is_file()
    payload = {
        "command": "teach",
        "ok": ok,
        "spacegroup": "Fd-3m",
        "spacegroup_number": 227,
        "online": bool(args.online),
        "cached_cifs_used": cached,
        "examples": len(rows),
        "verified_227": verified,
        "png": str(png),
        "csv": str(csv_path),
        "exit": figure_rc,
        "elapsed_s": _elapsed(t0),
        "artifacts": _artifacts(outdir),
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"teach -> {outdir}")
        print(f"  examples={len(rows)} verified_227={verified}")
        print(f"  PNG  -> {png}")
        print(f"  CSV  -> {csv_path}")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# bravais: Bain path + 14 Bravais lattices
# --------------------------------------------------------------------------- #
def _parse_bain_range(text: str) -> tuple[float, float, float]:
    parts = str(text).split(":")
    if len(parts) != 3:
        raise ValueError(f"--bain-range expects START:STOP:STEP, got {text!r}")
    rmin, rmax, step = (float(p) for p in parts)
    if not (0.3 <= rmin < rmax <= 3.0):
        raise ValueError(f"--bain-range start/stop out of range: {text!r}")
    if step <= 0 or step > (rmax - rmin):
        raise ValueError(f"--bain-range step must be > 0 and <= span: {text!r}")
    return rmin, rmax, step


def cmd_bravais(args: argparse.Namespace) -> int:
    t0 = time.time()
    _require_usecases()
    try:
        rmin, rmax, step = _parse_bain_range(args.bain_range)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    outdir = Path(args.outdir).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    bain = _u2_bain()
    bain_rc = _call(bain.main, ["--outdir", str(outdir), "--bain-range", f"{rmin}:{rmax}:{step}"], args.json)
    brav = _u2_bravais()
    brav_rc = _call(brav.main, ["--outdir", str(outdir)], args.json)

    data = outdir / "data"
    bain_rows = _read_csv(data / "bain_path.csv") if (data / "bain_path.csv").is_file() else []
    table = _read_csv(data / "bravais14.csv") if (data / "bravais14.csv").is_file() else []
    equiv = _read_csv(data / "equivalences.csv") if (data / "equivalences.csv").is_file() else []
    verified14 = sum(1 for r in table if str(r.get("verified", "")).strip() in {"1", "True", "true"})
    verified_eq = sum(1 for r in equiv if str(r.get("verified", "")).strip() in {"1", "True", "true"})
    specials = {
        row["c_over_a"]: {
            "spacegroup_number": row.get("spacegroup_number"),
            "spacegroup_symbol": row.get("spacegroup_symbol"),
        }
        for row in bain_rows
        if str(row.get("is_special", "")).strip() in {"1", "True", "true"}
    }
    pngs = [p for p in sorted((outdir / "figures").glob("*.png"))] if (outdir / "figures").is_dir() else []
    ok = (
        bain_rc == 0
        and brav_rc == 0
        and len(bain_rows) > 2
        and len(table) == 14
        and verified14 == 14
        and len(equiv) >= 4
        and len(pngs) >= 3
    )
    payload = {
        "command": "bravais",
        "ok": ok,
        "bain_range": [rmin, rmax, step],
        "bain_points": len(bain_rows),
        "bain_specials": specials,
        "bravais_lattices": len(table),
        "bravais_verified": verified14,
        "equivalences": len(equiv),
        "equivalences_verified": verified_eq,
        "figures": [str(p) for p in pngs],
        "exit": {"bain_path": bain_rc, "bravais14": brav_rc},
        "elapsed_s": _elapsed(t0),
        "artifacts": _artifacts(outdir),
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"bravais -> {outdir}")
        print(f"  bain points={len(bain_rows)}  specials={specials}")
        print(f"  14 Bravais: {verified14}/{len(table)} verified;  equivalences: {verified_eq}/{len(equiv)}")
        for p in pngs:
            print(f"  PNG -> {p}")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# metals: per-element bulk/slab/VASP templates (+ optional kit zip)
# --------------------------------------------------------------------------- #
def _seed_metals_cache(outdir: Path) -> None:
    """Bring the read-only AFLOW LIB1 candidate cache along so subset runs stay offline."""
    src = U3 / "data" / "aflow_lib1_candidates.json"
    dst = outdir / "data" / "aflow_lib1_candidates.json"
    if src.is_file() and not dst.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def cmd_metals(args: argparse.Namespace) -> int:
    t0 = time.time()
    _require_usecases()
    outdir = Path(args.outdir).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    _seed_metals_cache(outdir)

    export = _u3_export()
    elements = (args.elements or "").strip()
    export_argv = ["--outdir", str(outdir)]
    if elements and elements.lower() != "all":
        export_argv += ["--elements", elements]
    export_rc = _call(export.main, export_argv, args.json)
    if export_rc != 0:
        if args.json:
            _print_json(
                {
                    "command": "metals",
                    "ok": False,
                    "elements_requested": args.elements,
                    "exit": {"export_metals": export_rc},
                    "error": "export_metals failed (bad element names? see stderr)",
                }
            )
        return export_rc

    finalize = _u3_finalize()
    fin_argv: list[str] = ["--outdir", str(outdir)]
    if elements and elements.lower() != "all":
        fin_argv += ["--validate-elements", elements]
    if args.zip:
        fin_argv.append("--zip")
    fin_rc = _call(finalize.main, fin_argv, args.json)

    data = outdir / "data"
    records = json.loads((data / "records.json").read_text(encoding="utf-8")) if (data / "records.json").is_file() else {}
    failures = json.loads((data / "failures.json").read_text(encoding="utf-8")) if (data / "failures.json").is_file() else {}
    summary = _read_csv(outdir / "metals_summary.csv") if (outdir / "metals_summary.csv").is_file() else []
    element_dirs = sorted(p.name for p in (outdir / "elements").glob("*") if p.is_dir()) if (outdir / "elements").is_dir() else []
    zip_path = outdir / "metals_kit.zip"
    required_ok = all(
        (outdir / "elements" / el / name).is_file()
        for el in element_dirs
        for name in ("bulk.cif", "bulk_POSCAR", "slab.cif", "slab_POSCAR", "INCAR", "KPOINTS")
    )
    ok = export_rc == 0 and fin_rc == 0 and bool(element_dirs) and required_ok and len(summary) == len(element_dirs)
    payload = {
        "command": "metals",
        "ok": ok,
        "elements_requested": elements or "all",
        "elements_exported": element_dirs,
        "n_exported": len(element_dirs),
        "n_summary_rows": len(summary),
        "n_failed": len(failures),
        "zip": str(zip_path) if zip_path.is_file() else None,
        "exit": {"export_metals": export_rc, "finalize_metals": fin_rc},
        "elapsed_s": _elapsed(t0),
        "artifacts": _artifacts(outdir, subdir="elements"),
        "tables": [str(outdir / "metals_summary.csv"), str(data / "run_report.csv")],
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"metals -> {outdir}")
        print(f"  exported={len(element_dirs)} summary_rows={len(summary)} failed={len(failures)}")
        if zip_path.is_file():
            print(f"  zip -> {zip_path}")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# fec: Fe-C structures + 0 K hull + VASP inputs (+ optional kit zip)
# --------------------------------------------------------------------------- #
_FEC_KIT_README = """# Fe-C 计算套件（cifkit fec 生成）

产物：
- `structures/`：7 个 Fe-C 化合物 CIF + POSCAR（AFLOW LIB2 / ICSD_WEB，spglib 复核）
- `data/aflow_fe_c_energies.csv`：AFLOW LIB2 的 289 条形成焓（只读输入）
- `data/fe_c_compounds.csv`：结构表（空间群/Pearson/来源/焓）
- `data/hull_points.csv`：0 K 凸包点（每组成最低焓 + E_above_hull）
- `figures/fe_c_hull.png`：凸包图
- `docs/phase_diagram_notes.md`：Fe-Fe3C 亚稳相图笔记（教材值，非本地实测）
- `vasp_inputs/<name>/`：POSCAR/INCAR/INCAR.static/KPOINTS/KPOINTS.static/POTCAR.readme

组成和能量来自 AFLOW（别人算的 DFT），本套件**没有**跑 VASP；`POTCAR` 受 VASP 许可限制不随包分发。
把 `data/hull_points.csv` 换成你自己的形成焓即可离线复跑凸包。
"""


def cmd_fec(args: argparse.Namespace) -> int:
    t0 = time.time()
    _require_usecases()
    outdir = Path(args.outdir).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    data = outdir / "data"
    figures = outdir / "figures"
    data.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)

    # 1) offline structure + input table (shipped in the repo use case)
    _copy_missing(U4 / "structures", outdir / "structures")
    _copy_missing(U4 / "data", data)
    _copy_missing(U4 / "docs", outdir / "docs")
    if (U4 / "README.md").is_file() and not (outdir / "README.md").is_file():
        shutil.copy2(U4 / "README.md", outdir / "README.md")
    if not (outdir / "README.md").is_file():
        (outdir / "README.md").write_text(_FEC_KIT_README, encoding="utf-8")

    # 2) 0 K convex hull (offline: reads the AFLOW CSV copied above)
    energies = data / "aflow_fe_c_energies.csv"
    if not energies.is_file():
        print(f"error: missing {energies}; the offline kit needs the shipped AFLOW CSV", file=sys.stderr)
        return 2
    hull = _u4_hull()
    hull_rc = _call(
        hull.main,
        [
            "--energies-csv", str(energies),
            "--out-csv", str(data / "hull_points.csv"),
            "--out-png", str(figures / "fe_c_hull.png"),
        ],
        args.json,
    )
    # 3) VASP templates from the shipped structures
    vasp = _u4_vasp()
    vasp_rc = _call(vasp.main, ["--kit", str(outdir)], args.json)

    structures = sorted(p.name for p in (outdir / "structures").glob("*.cif"))
    vasp_dirs = sorted(p.name for p in (outdir / "vasp_inputs").glob("*") if p.is_dir()) if (outdir / "vasp_inputs").is_dir() else []
    hull_rows = _read_csv(data / "hull_points.csv") if (data / "hull_points.csv").is_file() else []
    fe3c = next((r for r in hull_rows if abs(float(r["x_C"]) - 0.25) < 1e-6), None)
    hull_vertices = [r for r in hull_rows if str(r.get("on_hull", "")).strip() == "yes"]
    zip_path = outdir / "fe_c_kit.zip"
    if args.zip:
        zip_path = _zip_dir(outdir, "fe_c_kit.zip", exclude={"fe_c_kit.zip"})
    ok = (
        hull_rc == 0
        and vasp_rc == 0
        and len(structures) == 7
        and len(vasp_dirs) >= 7
        and len(hull_rows) > 0
        and (figures / "fe_c_hull.png").is_file()
        and (data / "hull_points.csv").is_file()
    )
    payload = {
        "command": "fec",
        "ok": ok,
        "structures": len(structures),
        "vasp_input_dirs": len(vasp_dirs),
        "hull_points": len(hull_rows),
        "hull_vertices": len(hull_vertices),
        "fe3c": None if fe3c is None else {
            "energy_formation_eV_per_atom": fe3c.get("energy_formation_eV_per_atom"),
            "energy_above_hull_eV_per_atom": fe3c.get("energy_above_hull_eV_per_atom"),
            "status": fe3c.get("status"),
        },
        "zip": str(zip_path) if zip_path.is_file() else None,
        "exit": {"build_hull": hull_rc, "make_vasp_inputs": vasp_rc},
        "elapsed_s": _elapsed(t0),
        "artifacts": _artifacts(outdir),
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"fec -> {outdir}")
        print(f"  structures={len(structures)} vasp_inputs={len(vasp_dirs)} hull_points={len(hull_rows)}")
        if fe3c is not None:
            print(f"  Fe3C E_form={fe3c.get('energy_formation_eV_per_atom')} "
                  f"E_above_hull={fe3c.get('energy_above_hull_eV_per_atom')}")
        if zip_path.is_file():
            print(f"  zip -> {zip_path}")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# argparse wiring
# --------------------------------------------------------------------------- #
def _add_commands(sub: argparse._SubParsersAction) -> None:  # type: ignore[attr-defined]
    t = sub.add_parser("teach", help="Fd-3m 点群典例教学图：spglib 复核 → CSV + PNG")
    t.add_argument("--spacegroup", default="Fd-3m", help="目前仅支持 Fd-3m (#227)")
    t.add_argument("--outdir", required=True, help="产物目录")
    t.add_argument("--online", dest="online", action="store_true", default=True,
                   help="允许联网补齐缺失 CIF（已缓存不重下；默认开）")
    t.add_argument("--offline", dest="online", action="store_false",
                   help="只用已有缓存，不联网")
    t.add_argument("--symprec", type=float, default=0.05, help="spglib 对称性容差（Å）")
    t.add_argument("--json", action="store_true", help="stdout 输出单个 JSON")
    t.set_defaults(func=cmd_teach)

    b = sub.add_parser("bravais", help="Bain 路径 + 14 种布拉维点阵的对称性实测")
    b.add_argument("--outdir", required=True, help="产物目录")
    b.add_argument("--bain-range", default="0.9:1.7:0.01",
                   help="Bain 扫描范围 START:STOP:STEP（默认 0.9:1.7:0.01）")
    b.add_argument("--json", action="store_true", help="stdout 输出单个 JSON")
    b.set_defaults(func=cmd_bravais)

    m = sub.add_parser("metals", help="纯金属批量导出：bulk/slab/POSCAR/INCAR/KPOINTS")
    m.add_argument("--outdir", required=True, help="产物目录")
    m.add_argument("--elements", default="all", help="all 或逗号分隔子集（如 Fe,Cu,Mg）")
    m.add_argument("--zip", dest="zip", action="store_true", default=False,
                   help="额外打包 metals_kit.zip")
    m.add_argument("--no-zip", dest="zip", action="store_false", help="不打包（默认）")
    m.add_argument("--json", action="store_true", help="stdout 输出单个 JSON")
    m.set_defaults(func=cmd_metals)

    f = sub.add_parser("fec", help="Fe-C 结构 + 0 K 凸包 + VASP 模板（离线）")
    f.add_argument("--outdir", required=True, help="产物目录")
    f.add_argument("--zip", dest="zip", action="store_true", default=False,
                   help="额外打包 fe_c_kit.zip")
    f.add_argument("--no-zip", dest="zip", action="store_false", help="不打包（默认）")
    f.add_argument("--json", action="store_true", help="stdout 输出单个 JSON")
    f.set_defaults(func=cmd_fec)


def register(subparsers: argparse._SubParsersAction) -> Any:  # type: ignore[attr-defined]
    """Register the four use-case subcommands on an existing subparsers group."""
    _add_commands(subparsers)
    return subparsers


def build_parser(prog: str = "cifkit") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="cifkit 进阶应用子命令（teach / bravais / metals / fec）",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    _add_commands(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    _setup_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        if getattr(args, "json", False):
            _print_json({"ok": False, "command": getattr(args, "cmd", None),
                         "error": f"{type(exc).__name__}: {exc}"})
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
