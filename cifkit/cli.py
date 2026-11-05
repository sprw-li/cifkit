"""Command line interface for the CIF workbench.

Frozen command surface (skills/catalog wrappers and docs depend on it):

    python -m cifkit route "TEXT" [--json]
    python -m cifkit pipeline "TEXT" --outdir DIR [--format vasp,cif,xyz] [--source auto] [--ingest] [--json]
    python -m cifkit pipeline --spec spec.json ... --outdir DIR
    python -m cifkit fetch --topology sod [--name ZIF-8] [--raw|--ready] [--limit N] [--outdir DIR] [--json]
    python -m cifkit repair FILE -o OUT [--add-h] [--no-disorder] [--no-contacts] [--json]
    python -m cifkit geom FILE -o OUT [--standardize] [--supercell 2 2 1] [--surface 1 1 1]
                             [--vacuum 15] [--thickness 15] [--cluster MODE] [--json]
    python -m cifkit export FILE --format vasp,cif -o OUT [--json]
    python -m cifkit validate FILE [--json]
    python -m cifkit formats
    python -m cifkit selftest
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from cifkit.types import TaskSpec


def _setup_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


def _print_json(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _load_spec(args) -> TaskSpec:
    if getattr(args, "spec", None):
        text = Path(args.spec).read_text(encoding="utf-8-sig")  # tolerate PowerShell 5.1 BOM
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"error: --spec 不是合法 JSON（{args.spec}）：{exc.msg} at line {exc.lineno} col {exc.colno}. "
                "Windows PowerShell 5.1 的 `>` / Out-File 默认写 UTF-16/BOM，请用 "
                "`Set-Content -Encoding utf8` 或本工具接受的 utf-8-sig 保存。"
            ) from exc
        if not isinstance(raw, dict):
            raise SystemExit(f"error: --spec 顶层必须是 JSON 对象，得到 {type(raw).__name__}")
        known = {f.name for f in TaskSpec.__dataclass_fields__.values()}
        spec = TaskSpec(**{k: v for k, v in raw.items() if k in known})
        spec.spec_inputs = raw  # type: ignore[attr-defined]
    else:
        from cifkit.spec import parse_request

        spec = parse_request(args.query, outdir=args.outdir)
    if getattr(args, "outdir", None):
        spec.outdir = Path(args.outdir)
    if getattr(args, "source", None):
        spec.source = args.source
    if getattr(args, "format", None):
        spec.output_formats = [f.strip() for f in args.format.split(",") if f.strip()]
    if getattr(args, "topology", None) and not spec.topology:
        spec.topology = args.topology
    if getattr(args, "surface_frame", None) and spec.surface:
        spec.surface_frame = args.surface_frame
    if getattr(args, "ingest", False):
        spec.raw_text = spec.raw_text or spec.query
    return spec


# ---------------------------------------------------------------------------
def cmd_route(args) -> int:
    from cifkit.plan import build_plan, describe_plan
    from cifkit.spec import describe_spec, parse_request

    spec = parse_request(args.query, outdir=args.outdir or "runs/preview")
    plan = build_plan(spec)
    if args.json:
        _print_json({"spec": spec.to_dict(), "plan": [s.__dict__ for s in plan]})
        return 0 if spec.topology or spec.structure_name or spec.structure_id else 2
    print(describe_spec(spec))
    print()
    print(describe_plan(plan))
    return 0 if spec.topology or spec.structure_name or spec.structure_id else 2


def cmd_pipeline(args) -> int:
    from cifkit.pipeline import run

    spec = _load_spec(args)
    if args.json:
        # step logs must go to stderr so stdout stays a single valid JSON document
        import contextlib

        with contextlib.redirect_stdout(sys.stderr):
            result = run(spec, ingest_run=args.ingest)
        _print_json(result.to_dict())
    else:
        result = run(spec, ingest_run=args.ingest)
        print()
        print(f"ok={result.ok}  outdir={result.outdir}")
        print(f"manifest={result.manifest_path}")
        for key, path in result.artifacts.items():
            print(f"  {key}: {path}")
    return 0 if result.ok else 1


def cmd_fetch(args) -> int:
    from cifkit.sources import get_source

    src = get_source(args.source)
    from cifkit.types import SourceQuery

    query = SourceQuery(
        topology=args.topology,
        typical=not args.no_typical,
        prefer_raw=args.raw,
        structure_name=args.name,
        limit=args.limit,
        source=args.source,
    )
    hits = src.search(query)
    if args.json:
        _print_json([h.to_dict() for h in hits])
    else:
        if not hits:
            print("no hits")
            return 1
        for h in hits:
            print(f"{h.record_id}\n  formula={h.formula} topology={h.topology}({h.topology_evidence}) "
                  f"atoms={h.natoms} H={h.h_count} variant={h.variant}\n  doi={h.doi} "
                  f"h_deficient={h.is_h_deficient()}")
    if args.outdir and hits:
        fetched = src.fetch(hits[0])
        out = Path(args.outdir)
        out.mkdir(parents=True, exist_ok=True)
        import hashlib

        import shutil

        path = out / "raw.cif"
        cif_path = (fetched.provenance or {}).get("cif_path")
        if cif_path and Path(cif_path).is_file():
            # byte copy so raw.cif sha256 == provenance.sha256
            shutil.copyfile(cif_path, path)
        else:
            from pymatgen.io.cif import CifWriter

            CifWriter(fetched.structure, symprec=None).write_file(str(path))
        raw_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        meta = {
            "record": fetched.record.to_dict(),
            "provenance": fetched.provenance,
            "raw_cif": str(path),
            "raw_cif_sha256": raw_sha,
            "note": (
                "raw_cif 是源 CIF 的字节拷贝，sha256 应与 provenance.sha256 一致"
                if cif_path
                else "源 CIF 不可直接拷贝，raw_cif 由 Structure 重新写出，sha256 与 provenance.sha256 可能不同"
            ),
        }
        (out / "source.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"wrote {path} (sha256={raw_sha[:16]}...)")
    return 0


def cmd_repair(args) -> int:
    from cifkit.repair import repair_all
    from pymatgen.core import Structure
    from pymatgen.io.cif import CifWriter

    s = Structure.from_file(args.file)
    out_s, report = repair_all(
        s,
        add_hydrogen=args.add_h,
        resolve_disorder=not args.no_disorder,
        remove_close_contacts=not args.no_contacts,
    )
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        CifWriter(out_s, symprec=None).write_file(args.out)
    if args.json:
        _print_json({"report": report.to_dict(), "natoms": len(out_s), "formula": out_s.composition.formula})
    else:
        print(f"atoms {len(s)} -> {len(out_s)}  added_H={report.added_h} removed={report.removed_atoms} "
              f"disorder={report.resolved_disorder}")
        for w in report.warnings:
            print(f"  warning: {w}")
    return 0


def cmd_geom(args) -> int:
    from pymatgen.core import Structure
    from pymatgen.io.cif import CifWriter
    from cifkit import geom

    s = Structure.from_file(args.file)
    info = {}
    if args.standardize:
        s = geom.standardize(s)
    if args.cluster:
        s = geom.extract_cluster(s, mode=args.cluster)
    if args.surface:
        # physical default: cleave from the (standardized) bulk, repeat in the slab frame
        s, slab_info = geom.make_slab(
            s,
            tuple(args.surface),
            slab_thickness=args.thickness or 15.0,
            vacuum=args.vacuum or 15.0,
            reps=tuple(args.supercell) if args.supercell else None,
            frame=getattr(args, "surface_frame", "slab"),
        )
        info["slab"] = slab_info
    elif args.supercell:
        s = geom.make_supercell(s, tuple(args.supercell))
    if args.vacuum is not None:
        s, measured = geom.set_vacuum(s, args.vacuum)
        info["vacuum"] = measured
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        CifWriter(s, symprec=None).write_file(args.out)
    payload = {"natoms": len(s), "formula": s.composition.formula, "abc": list(s.lattice.abc),
               "angles": list(s.lattice.angles), "info": info}
    if args.json:
        _print_json(payload)
    else:
        print(f"atoms={len(s)} formula={s.composition.formula} abc={[round(x,3) for x in s.lattice.abc]}")
        if info:
            print(json.dumps(info, ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_export(args) -> int:
    from pymatgen.core import Structure
    from cifkit import export

    supported = export.supported_formats()
    requested = [f.strip() for f in args.format.split(",") if f.strip()]
    unsupported = [f for f in requested if f not in supported]
    if unsupported:
        print(
            f"error: unsupported format(s): {', '.join(unsupported)}; "
            f"supported: {', '.join(sorted(supported))}",
            file=sys.stderr,
        )
        return 2
    s = Structure.from_file(args.file)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    written = {}
    for fmt in requested:
        written[fmt] = export.write_structure(s, outdir / f"structure.{fmt}", fmt)
    if args.json:
        _print_json(written)
    else:
        for fmt, path in written.items():
            print(f"{fmt}: {path}")
    return 0


def cmd_validate(args) -> int:
    from pymatgen.core import Structure
    from cifkit.validate import validate_structure

    s = Structure.from_file(args.file)
    report = validate_structure(s)
    if args.json:
        _print_json(report.to_dict())
    else:
        print(f"ok={report.ok}")
        for c in report.checks:
            mark = "OK " if c.ok else ("WARN" if c.severity == "warning" else "FAIL")
            print(f"  [{mark}] {c.name}: {c.detail}")
        print(json.dumps(report.metrics, ensure_ascii=False, indent=2, default=str))
    return 0 if report.ok else 1


def cmd_formats(args) -> int:
    from cifkit import export

    fmts = export.supported_formats()
    if args.json:
        _print_json(fmts)
    else:
        for name, desc in fmts.items():
            print(f"{name:12s} {desc}")
    return 0


def cmd_selftest(args) -> int:
    """Fast offline checks: imports, parser, cached data, module smoke tests."""
    failures: list[str] = []
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, fn):
        try:
            detail = fn() or ""
            checks.append((name, True, str(detail)))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            checks.append((name, False, f"{type(exc).__name__}: {exc}"))

    check("import:spec", lambda: __import__("cifkit.spec").spec.__name__)
    check("import:sources", lambda: __import__("cifkit.sources").sources.__name__)
    check("import:repair", lambda: __import__("cifkit.repair").repair.__name__)
    check("import:geom", lambda: __import__("cifkit.geom").geom.__name__)
    check("import:export", lambda: __import__("cifkit.export").export.__name__)
    check("import:validate", lambda: __import__("cifkit.validate").validate.__name__)

    def parse_demo():
        from cifkit.spec import parse_request

        s = parse_request("下载RCSR为sod的mof，补氢，2x2x1超胞，沿(111)面切表面，加15Å真空层，导出VASP")
        assert s.topology == "sod", s.topology
        assert s.supercell == (2, 2, 1), s.supercell
        assert s.surface == (1, 1, 1), s.surface
        assert s.vacuum == 15.0, s.vacuum
        assert "vasp" in s.output_formats
        return "ok"

    check("parse:demo", parse_demo)

    if args.verbose:
        for name, ok, detail in checks:
            print(f"[{'OK' if ok else 'FAIL'}] {name} {detail}")
    else:
        for f in failures:
            print(f"FAIL {f}")
    print(f"selftest: {len(checks) - len(failures)}/{len(checks)} passed")
    return 0 if not failures else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cifkit", description="CIF 处理工作台")
    p.add_argument("--version", action="version", version="cifkit 0.1.0")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("route", help="把一句话解析成 TaskSpec 和步骤计划（不执行）")
    r.add_argument("query")
    r.add_argument("--outdir", default=None)
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_route)

    pl = sub.add_parser("pipeline", help="一条管线跑通：检索下载→修复→几何→导出→校验→入库")
    pl.add_argument("query", nargs="?")
    pl.add_argument("--spec", default=None, help="TaskSpec JSON（与 query 二选一）")
    pl.add_argument("--outdir", required=True)
    pl.add_argument("--source", default=None)
    pl.add_argument("--topology", default=None)
    pl.add_argument("--format", default=None, help="逗号分隔，如 vasp,cif,xyz")
    pl.add_argument("--surface-frame", choices=["slab", "cell"], default=None,
                    help="slab=先从体相切面再面内重复（默认）；cell=先超胞再切面（字面语义）")
    pl.add_argument("--ingest", action="store_true", help="把产物登记进 library/")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_pipeline)

    f = sub.add_parser("fetch", help="按拓扑/名称检索结构数据库并落盘")
    f.add_argument("--source", default="core-mof")
    f.add_argument("--topology", default=None)
    f.add_argument("--name", default=None)
    f.add_argument("--raw", action="store_true", help="优先返回需要修复的原始 CIF（缺氢等）")
    f.add_argument("--ready", dest="raw", action="store_false")
    f.add_argument("--no-typical", action="store_true")
    f.add_argument("--limit", type=int, default=10)
    f.add_argument("--outdir", default=None)
    f.add_argument("--json", action="store_true")
    f.set_defaults(func=cmd_fetch)

    rp = sub.add_parser("repair", help="修复 CIF：补氢 / 无序占位 / 过近原子")
    rp.add_argument("file")
    rp.add_argument("-o", "--out", default=None)
    rp.add_argument("--add-h", action="store_true")
    rp.add_argument("--no-disorder", action="store_true")
    rp.add_argument("--no-contacts", action="store_true")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_repair)

    g = sub.add_parser("geom", help="几何操作：标准化 / 超胞 / 切面 / 真空 / 金属簇")
    g.add_argument("file")
    g.add_argument("-o", "--out", default=None)
    g.add_argument("--standardize", action="store_true")
    g.add_argument("--supercell", nargs=3, type=int, default=None)
    g.add_argument("--surface", nargs=3, type=int, default=None)
    g.add_argument("--surface-frame", choices=["slab", "cell"], default="slab",
                   help="slab=先从体相切面再面内重复（物理默认）；cell=先超胞再切该胞的晶面（字面语义）")
    g.add_argument("--vacuum", type=float, default=None)
    g.add_argument("--thickness", type=float, default=None)
    g.add_argument("--cluster", default=None, choices=["sbu", "metal_cluster", "core"])
    g.add_argument("--json", action="store_true")
    g.set_defaults(func=cmd_geom)

    e = sub.add_parser("export", help="导出计算化学格式")
    e.add_argument("file")
    e.add_argument("--format", required=True)
    e.add_argument("-o", "--out", required=True)
    e.add_argument("--json", action="store_true")
    e.set_defaults(func=cmd_export)

    v = sub.add_parser("validate", help="结构校验")
    v.add_argument("file")
    v.add_argument("--json", action="store_true")
    v.set_defaults(func=cmd_validate)

    fm = sub.add_parser("formats", help="列出支持的导出格式")
    fm.add_argument("--json", action="store_true")
    fm.set_defaults(func=cmd_formats)

    st = sub.add_parser("selftest", help="离线自检")
    st.add_argument("--verbose", action="store_true")
    st.set_defaults(func=cmd_selftest)

    return p


def main(argv: list[str] | None = None) -> int:
    _setup_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except NotImplementedError as exc:
        print(f"not implemented: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001
        if getattr(args, "verbose", False):
            traceback.print_exc()
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
