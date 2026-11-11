"""Command line interface for the CIF workbench.

Frozen command surface (skills/catalog wrappers and docs depend on it):

    python -m cifkit route "TEXT" [--json]
    python -m cifkit pipeline "TEXT" --outdir DIR [--format vasp,cif,xyz] [--source auto] [--ingest] [--json]
    python -m cifkit pipeline --spec spec.json ... --outdir DIR [--bundle vasp,qe]
    python -m cifkit batch --spec "TEXT" [--spec "TEXT2"] [--jobs N] [--outdir runs/batch] [--json]
    python -m cifkit batch --specs-file runs/specs.jsonl [--jobs N] [--json]
    python -m cifkit convert FILE --to vasp,cif,xyz --bundle vasp,qe --outdir DIR [--json]
    python -m cifkit features FILE_OR_DIR ... --out features.csv [--json] [--jobs N] [--no-rdf] [--topology]
    python -m cifkit dataset --from-runs runs/ --outdir dataset/ [--json] [--label-key topology]
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
import subprocess
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


def _read_spec_text(path: str | Path) -> str:
    """Read a JSON spec tolerating UTF-8 (with/without BOM) and UTF-16.

    Windows PowerShell 5.1 `>` / Out-File writes UTF-16LE and `Set-Content`
    may add a BOM; users should not have to debug codecs for a spec file.
    """
    raw = Path(path).read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw.decode("utf-8-sig")
    return raw.decode("utf-8")


def _load_spec(args) -> TaskSpec:
    if getattr(args, "spec", None):
        try:
            text = _read_spec_text(args.spec)
        except UnicodeDecodeError as exc:
            raise SystemExit(
                f"error: --spec 编码无法识别（{args.spec}）：{exc}。请保存为 UTF-8（无 BOM）或 UTF-16。"
            ) from exc
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"error: --spec 不是合法 JSON（{args.spec}）：{exc.msg} at line {exc.lineno} col {exc.colno}. "
                "提示：`>`/Out-File 可能写入 UTF-16 或 BOM；本工具支持 UTF-8/UTF-8-BOM/UTF-16，"
                "但仍需保证内容是合法 JSON。"
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
    bundle_info: dict = {}
    if args.json:
        # step logs must go to stderr so stdout stays a single valid JSON document
        import contextlib

        with contextlib.redirect_stdout(sys.stderr):
            result = run(spec, ingest_run=args.ingest)
        if getattr(args, "bundle", None):
            bundle_info = _write_pipeline_bundles(result, args.bundle)
        payload = result.to_dict()
        payload["bundles"] = bundle_info
        _print_json(payload)
    else:
        result = run(spec, ingest_run=args.ingest)
        if getattr(args, "bundle", None):
            bundle_info = _write_pipeline_bundles(result, args.bundle)
        print()
        print(f"ok={result.ok}  outdir={result.outdir}")
        print(f"manifest={result.manifest_path}")
        for key, path in result.artifacts.items():
            print(f"  {key}: {path}")
        for code, info in bundle_info.items():
            print(f"  bundle {code}: {info}")
    return 0 if result.ok else 1


def _write_pipeline_bundles(result, bundle_text: str) -> dict:
    """Write computation-software input bundles for a finished pipeline run."""
    from pymatgen.core import Structure

    from cifkit import export

    codes = _bundle_codes(bundle_text)
    if not codes:
        return {}
    artifact = result.artifacts.get("standardized.cif") or result.artifacts.get("raw.cif")
    if not artifact:
        return {"error": "pipeline 没有 standardized.cif/raw.cif，无法生成输入包"}
    structure = Structure.from_file(artifact)
    outdir = Path(result.outdir) / "bundles"
    written: dict = {}
    for code in codes:
        try:
            written[code] = export.write_bundle(structure, code, outdir / code, title=Path(artifact).stem)
        except Exception as exc:  # noqa: BLE001 - bundle failure must not kill the run
            written[code] = {"error": f"{type(exc).__name__}: {exc}"}
    return written


def cmd_batch(args) -> int:
    """Run several pipeline jobs concurrently (one subprocess per job)."""
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    jobs: list[dict] = []
    if args.specs_file:
        text = Path(args.specs_file).read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"specs-file 第 {lineno} 行不是合法 JSON：{exc}", file=sys.stderr)
                return 2
            if isinstance(item, str):
                item = {"spec": item}
            if not isinstance(item, dict) or not (item.get("spec") or item.get("query")):
                print(f"specs-file 第 {lineno} 行缺少 spec/query", file=sys.stderr)
                return 2
            jobs.append(item)
    for query in args.spec or []:
        jobs.append({"spec": query})
    if not jobs:
        print("batch: 至少给一个 --spec 或 --specs-file", file=sys.stderr)
        return 2

    root = Path(args.outdir)
    root.mkdir(parents=True, exist_ok=True)
    started = time.time()

    def _slug(text: str) -> str:
        keep = [ch if (ch.isalnum() or ch in "-_") else "_" for ch in str(text)]
        return "".join(keep)[:48] or "run"

    def run_one(index: int, job: dict) -> dict:
        query = str(job.get("spec") or job.get("query"))
        outdir = Path(job["outdir"]) if job.get("outdir") else root / f"{index:02d}_{_slug(query)}"
        cmd = [sys.executable, "-m", "cifkit", "pipeline", query, "--outdir", str(outdir), "--json"]
        if getattr(job, "get", None) and job.get("source"):
            cmd += ["--source", str(job["source"])]
        if args.ingest:
            cmd.append("--ingest")
        t0 = time.time()
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=args.timeout,
            )
        except subprocess.TimeoutExpired:
            return {"index": index, "spec": query, "outdir": str(outdir), "ok": False,
                    "returncode": None, "seconds": round(time.time() - t0, 2),
                    "stderr_tail": f"timeout after {args.timeout}s", "summary": {}}
        summary: dict = {}
        try:
            summary = json.loads(proc.stdout.strip() or "{}")
        except json.JSONDecodeError:
            summary = {"raw_stdout_tail": proc.stdout[-400:]}
        return {
            "index": index,
            "spec": query,
            "outdir": str(outdir),
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "seconds": round(time.time() - t0, 2),
            "stderr_tail": proc.stderr[-500:],
            "summary": summary,
        }

    results: list[dict] = []
    jobs_n = max(1, int(args.jobs))
    with ThreadPoolExecutor(max_workers=jobs_n) as pool:
        futures = {pool.submit(run_one, i, job): i for i, job in enumerate(jobs)}
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: item["index"])
    manifest = {
        "root": str(root),
        "jobs": len(results),
        "concurrency": jobs_n,
        "ok": sum(1 for item in results if item["ok"]),
        "seconds": round(time.time() - started, 2),
        "runs": results,
    }
    (root / "batch_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if args.json:
        _print_json(manifest)
    else:
        for item in results:
            flag = "ok  " if item["ok"] else "fail"
            print(f"[{flag}] {item['seconds']:6.2f}s  {item['spec'][:64]} -> {item['outdir']}")
        print(f"\n{manifest['ok']}/{len(results)} ok in {manifest['seconds']}s "
              f"(jobs={jobs_n}, manifest={root / 'batch_manifest.json'})")
    return 0 if manifest["ok"] == len(results) else 1


def _load_structure_any(path: str | Path):
    """Load a structure from any format pymatgen or ASE can read."""
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"结构文件不存在：{p}")
    from pymatgen.core import Structure

    try:
        return Structure.from_file(str(p))
    except Exception:  # noqa: BLE001 - fall back to ASE
        try:
            import ase.io
            from pymatgen.io.ase import AseAtomsAdaptor

            atoms = ase.io.read(str(p))
            if len(atoms) == 0:
                raise ValueError("ASE 读到 0 个原子")
            return AseAtomsAdaptor.get_structure(atoms)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(
                f"无法解析结构文件 {p}（pymatgen 和 ASE 都失败；支持 cif/poscar/xyz/json/xsf 等）：{exc}"
            ) from exc


def _bundle_codes(text: str | None) -> list[str]:
    if not text:
        return []
    return [code.strip().lower() for code in text.split(",") if code.strip()]


def _convert_one(
    src: Path,
    outdir: Path,
    formats: list[str],
    bundles: list[str],
    *,
    stem: str | None = None,
    title: str | None = None,
    in_subdir: bool = False,
) -> dict:
    """Convert one structure file into formats/bundles under ``outdir``.

    Args:
        stem: output base name (defaults to the input file stem).
        in_subdir: write into ``outdir/<name>/`` instead of directly into
            ``outdir``. Batch mode uses sub-directories so two inputs with the
            same file name cannot collide; single-input mode stays flat so the
            round-9 ``--stem X`` behaviour (``outdir/X.vasp``) is preserved.
    """
    from cifkit import export

    entry: dict = {"input": str(src), "ok": False, "formats": {}, "bundles": {}}
    try:
        structure = _load_structure_any(src)
    except Exception as exc:  # noqa: BLE001 - one bad input must not stop the batch
        entry["error"] = f"{type(exc).__name__}: {exc}"
        return entry
    entry["natoms"] = len(structure)
    name = stem or src.stem
    target = (outdir / name) if in_subdir else outdir
    target.mkdir(parents=True, exist_ok=True)
    for fmt in formats:
        try:
            entry["formats"][fmt] = export.write_structure(structure, target / f"{name}.{fmt}", fmt)
        except Exception as exc:  # noqa: BLE001
            entry.setdefault("errors", []).append(f"{fmt}: {type(exc).__name__}: {exc}")
    for code in bundles:
        try:
            entry["bundles"][code] = export.write_bundle(structure, code, target / code,
                                                         title=title or name)
        except Exception as exc:  # noqa: BLE001
            entry.setdefault("errors", []).append(f"bundle {code}: {type(exc).__name__}: {exc}")
    entry["ok"] = not entry.get("errors")
    written = list(entry["formats"].values())
    if isinstance(entry.get("bundles"), dict):
        for info in entry["bundles"].values():
            if isinstance(info, dict):
                written.extend(info.get("files", []))
    entry["n_files"] = len(written)
    entry["outdir"] = str(target)
    return entry


def cmd_convert(args) -> int:
    """CIF/结构文件 → 任意格式 + 任意计算软件输入包（支持目录/多输入批量 + manifest）。"""
    from cifkit import export

    formats = [f.strip().lower() for f in (args.to or "").split(",") if f.strip()]
    bundles = _bundle_codes(args.bundle)
    if not formats and not bundles:
        print("error: 至少给 --to 或 --bundle 之一（如 --to vasp,xyz 或 --bundle vasp,qe）", file=sys.stderr)
        return 2
    supported = export.supported_formats()
    unsupported = [fmt for fmt in formats if fmt not in supported]
    if unsupported:
        print(
            f"error: unsupported format(s): {', '.join(unsupported)}; supported: {', '.join(sorted(supported))}",
            file=sys.stderr,
        )
        return 2
    if bundles:
        available = export.supported_bundles()
        bad_bundles = [code for code in bundles if code not in available]
        if bad_bundles:
            print(
                f"error: unsupported bundle(s): {', '.join(bad_bundles)}; available: {', '.join(sorted(available))}",
                file=sys.stderr,
            )
            return 2

    # --- resolve inputs: files and/or directories (deduped) -----------------
    inputs = _expand_structure_inputs(args.file)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    batch_mode = len(inputs) > 1 or any(Path(item).is_dir() for item in args.file)
    if not batch_mode:
        # single file: files land directly in --outdir (round-9 behaviour, so
        # `--stem X` still produces `outdir/X.vasp`)
        result = _convert_one(inputs[0], outdir, formats, bundles, stem=args.stem,
                              title=args.title, in_subdir=False)
        result.update({"outdir": str(outdir), "n_inputs": 1})
    else:
        # batch: one sub-directory per input + a manifest of everything written.
        # Stems must be unique: d1/same.cif and d2/same.cif would otherwise write to
        # the same sub-directory and silently overwrite each other.
        counts: dict[str, int] = {}
        base_stems: list[str] = []
        for index, src in enumerate(inputs):
            base = f"{args.stem}_{index:03d}" if args.stem else src.stem
            base_stems.append(base)
            counts[base] = counts.get(base, 0) + 1
        seen: dict[str, int] = {}
        runs = []
        for src, base in zip(inputs, base_stems):
            if counts[base] > 1:
                seen[base] = seen.get(base, 0) + 1
                stem = f"{base}_{seen[base]:03d}"
            else:
                stem = base
            runs.append(_convert_one(src, outdir, formats, bundles, stem=stem,
                                     title=args.title, in_subdir=True))
        manifest = {
            "ok": all(run["ok"] for run in runs),
            "outdir": str(outdir),
            "n_inputs": len(inputs),
            "n_ok": sum(1 for run in runs if run["ok"]),
            "n_failed": sum(1 for run in runs if not run["ok"]),
            "formats": formats,
            "bundles": bundles,
            "runs": runs,
        }
        (outdir / "convert_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result = manifest

    if args.json:
        _print_json(result)
    else:
        if "runs" in result:
            for run in result["runs"]:
                flag = "ok  " if run["ok"] else "fail"
                print(f"[{flag}] {run['input']} -> {run['n_files']} files"
                      + (f"  ({run['error']})" if run.get("error") else ""))
            print(f"\n{result['n_ok']}/{result['n_inputs']} ok; manifest={outdir / 'convert_manifest.json'}")
        else:
            print(f"input: {result['input']} ({result.get('natoms')} atoms)")
            for fmt, path in result["formats"].items():
                print(f"  {fmt:10s} -> {path}")
            for code, info in result["bundles"].items():
                print(f"  bundle {code} -> {info if not isinstance(info, dict) else info.get('files', info)}")
            print(f"outdir: {outdir}")
    return 0 if result["ok"] else 1


def _write_string_csv(rows: list[dict], path: Path) -> Path:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: (json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value)
                             for key, value in row.items()})
    return path


def _expand_structure_inputs(items: list[str]) -> list[Path]:
    candidates: list[Path] = []
    for item in items:
        p = Path(item)
        if p.is_dir():
            found = sorted(p.glob("*.cif")) + sorted(p.glob("*.cif.gz"))
            if not found:
                raise ValueError(f"目录里没有 .cif：{p}")
            candidates.extend(found)
        elif p.is_file():
            candidates.append(p)
        else:
            raise ValueError(f"输入不存在：{p}")
    # Windows globbing is case-insensitive, so *.cif also matches *.CIF; dedupe by
    # resolved path while preserving the (sorted) order.
    seen: set[str] = set()
    paths: list[Path] = []
    for path in candidates:
        key = str(path.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    return paths


def cmd_features(args) -> int:
    """把 CIF/结构文件批量变成 ML-ready 特征表（CSV/JSONL）。"""
    from cifkit.features import features_many

    paths = _expand_structure_inputs(args.input)
    rows = features_many(
        [str(p) for p in paths],
        jobs=args.jobs,
        rdf=not args.no_rdf,
        rdf_bins=args.rdf_bins,
        rdf_max=args.rdf_max,
        topology=args.topology,
        rings=args.rings,
    )
    if args.out:
        out = _write_string_csv(rows, Path(args.out))
    else:
        out = None
    ok = sum(1 for row in rows if not row.get("error"))
    failed = len(rows) - ok
    result = {"ok": failed == 0, "n_inputs": len(paths), "n_ok": ok, "n_failed": failed,
              "out": str(out) if out else None, "rows": rows if args.json else None}
    if args.json:
        _print_json({k: v for k, v in result.items() if k != "rows"} | {"rows": rows})
    else:
        for row in rows:
            if row.get("error"):
                print(f"[fail] {row.get('path')}: {row['error']}", file=sys.stderr)
        print(f"{ok}/{len(paths)} structures -> {out if out else '(stdout JSON)'}")
    return 0 if failed == 0 else 1


def cmd_dataset(args) -> int:
    """从 runs/library 构建 dataset（结构 + 特征 + manifest）。"""
    from cifkit.dataset import build_dataset

    source = args.from_runs or args.from_library
    if not source:
        print("error: --from-runs DIR 或 --from-library DIR 至少给一个", file=sys.stderr)
        return 2
    outdir = Path(args.outdir)
    result = build_dataset(
        source,
        outdir,
        features=not args.no_features,
        copy_structures=not args.no_structures,
        label_key=args.label_key,
        stream=not getattr(args, "no_stream", False),
        jobs=getattr(args, "jobs", 1),
        dedupe=getattr(args, "dedupe", None),
    )
    if args.json:
        _print_json(result)
    else:
        print(f"dataset: {outdir}")
        for key in ("mode", "n_runs", "n_ok", "n_failed", "csv", "jsonl", "structures",
                    "max_rows_held", "dedupe", "n_deduped"):
            if key in result:
                print(f"  {key}: {result[key]}")
    return 0 if result.get("n_failed", 0) == 0 else 1


def cmd_fetch(args) -> int:
    from cifkit.sources import get_source, pick_source
    from cifkit.types import SourceQuery, TaskSpec

    spec = TaskSpec(
        source=args.source,
        topology=args.topology,
        structure_name=args.name,
        structure_id=args.id,
    )
    source_name = pick_source(spec) if str(args.source or "auto").lower() in ("", "auto") else args.source
    src = get_source(source_name)
    query = SourceQuery(
        topology=args.topology,
        typical=not args.no_typical,
        prefer_raw=args.raw,
        structure_name=args.name,
        structure_id=args.id,
        limit=args.limit,
        source=source_name,
    )
    if not args.json:
        print(f"source={source_name}")
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
        if args.json:
            # keep stdout a single valid JSON document (the hits array above)
            print(f"wrote {path} (sha256={raw_sha[:16]}...)", file=sys.stderr)
        else:
            print(f"wrote {path} (sha256={raw_sha[:16]}...)")
    return 0


def cmd_sources(args) -> int:
    from cifkit.sources import source_status

    rows = source_status()
    if args.probe:
        from cifkit.sources.aflow import aflow_available
        from cifkit.sources.cod import cod_available
        from cifkit.sources.materials_project import mp_available

        probes = {"cod": cod_available, "aflow": aflow_available, "materials-project": mp_available}
        for row in rows:
            probe = probes.get(row["name"])
            if probe is not None:
                try:
                    row["network"] = bool(probe())
                except Exception as exc:  # noqa: BLE001
                    row["network"] = False
                    row["network_error"] = f"{type(exc).__name__}: {exc}"
    if args.json:
        _print_json(rows)
    else:
        for row in rows:
            mark = "OK " if row.get("available") else "!! "
            auth = "需要 key" if row.get("requires_auth") else "免 key"
            net = f" network={'up' if row.get('network') else 'down'}" if "network" in row else ""
            print(f"[{mark}] {row['name']:18s} {auth:7s} {row['status']}{net}")
            print(f"        {row['description']}")
            if row.get("auth_hint") and not row.get("available"):
                print(f"        hint: {row['auth_hint']}")
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
    pl.add_argument("--bundle", default=None,
                    help="额外写出计算软件输入包（逗号分隔：vasp,qe,cp2k,lammps,gromacs,gaussian,orca,abacus,dftb,siesta,nwchem,aims）")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_pipeline)

    b = sub.add_parser("batch", help="批量并发跑多条 pipeline（每条约一个子进程）")
    b.add_argument("--spec", action="append", default=[], help="自然语言请求，可重复")
    b.add_argument("--specs-file", default=None,
                   help="JSONL 文件：每行 {\"spec\": \"...\", \"outdir\": \"...\"(可选), \"source\": \"...\"(可选)}")
    b.add_argument("--outdir", default="runs/batch", help="批处理根目录（每 run 一个子目录）")
    b.add_argument("--jobs", type=int, default=4, help="并发度（默认 4）")
    b.add_argument("--timeout", type=float, default=600.0, help="单条超时秒数")
    b.add_argument("--ingest", action="store_true")
    b.add_argument("--json", action="store_true")
    b.set_defaults(func=cmd_batch)

    cv = sub.add_parser("convert", help="CIF/结构文件 → 任意格式 + 计算软件输入包（支持目录批量）")
    cv.add_argument("file", nargs="+",
                    help="输入结构文件或目录（目录里的 *.cif 全部转换；多输入时写 convert_manifest.json）")
    cv.add_argument("--to", default="", help="逗号分隔的格式：vasp,cif,xyz,extxyz,json,pdb,sdf,...（见 cifkit formats）")
    cv.add_argument("--bundle", default="", help="逗号分隔的软件输入包：vasp,qe,cp2k,lammps,gromacs,gaussian,orca,abacus,dftb,siesta,nwchem,aims")
    cv.add_argument("--outdir", required=True)
    cv.add_argument("--stem", default=None, help="输出文件主名（默认取输入文件名）")
    cv.add_argument("--title", default=None)
    cv.add_argument("--json", action="store_true")
    cv.set_defaults(func=cmd_convert)

    ft = sub.add_parser("features", help="批量提取结构特征（组成/晶格/对称性/配位/RDF/拓扑）→ CSV/JSONL")
    ft.add_argument("input", nargs="+", help="结构文件或目录（目录里的 *.cif 全部处理）")
    ft.add_argument("--out", default=None, help="输出 CSV；省略则只在 --json 时打印")
    ft.add_argument("--jobs", type=int, default=4)
    ft.add_argument("--no-rdf", action="store_true", help="不算 RDF（大结构快很多）")
    ft.add_argument("--rdf-bins", type=int, default=50)
    ft.add_argument("--rdf-max", type=float, default=8.0)
    ft.add_argument("--topology", action="store_true", help="额外做拓扑识别（sod/pcu/fcu/...，较慢）")
    ft.add_argument("--rings", action="store_true", help="额外统计 4–8 元环（金属节点 net，较慢）")
    ft.add_argument("--json", action="store_true")
    ft.set_defaults(func=cmd_features)

    ds = sub.add_parser("dataset", help="从 runs/ 或 library/ 汇总结构+特征+标签 → ML 数据集")
    ds.add_argument("--from-runs", default=None, help="扫描 runs/**/manifest.json")
    ds.add_argument("--from-library", default=None, help="扫描 library/index.jsonl")
    ds.add_argument("--outdir", required=True)
    ds.add_argument("--label-key", default=None, help="用 manifest/provenance 里的哪个字段作 label（如 topology/doi/source）")
    ds.add_argument("--no-features", action="store_true")
    ds.add_argument("--no-structures", action="store_true")
    ds.add_argument("--jobs", type=int, default=1,
                    help="并行处理 run 数（默认 1；顺序保持、在飞窗口有界）")
    ds.add_argument("--dedupe", default=None,
                    choices=["structure_sha256", "structure_file", "formula",
                             "reduced_formula", "label"],
                    help="按该键去重（保留首次出现；失败 run 永不被去掉）")
    ds.add_argument("--json", action="store_true")
    ds.set_defaults(func=cmd_dataset)

    f = sub.add_parser("fetch", help="按拓扑/名称/id 检索结构数据库并落盘")
    f.add_argument("--source", default="auto",
                   help="auto|core-mof|cod|materials-project|aflow|local（auto 按拓扑/名称/id 推断）")
    f.add_argument("--topology", default=None)
    f.add_argument("--name", default=None, help="结构名或化学式（如 ZIF-8 / GaN）")
    f.add_argument("--id", default=None, help="结构 id：mp-149 / 7111973 / aflowlib.duke.edu:AFLOWDATA/...")
    f.add_argument("--raw", action="store_true", help="优先返回需要修复的原始 CIF（缺氢等）")
    f.add_argument("--ready", dest="raw", action="store_false")
    f.add_argument("--no-typical", action="store_true")
    f.add_argument("--limit", type=int, default=10)
    f.add_argument("--outdir", default=None)
    f.add_argument("--json", action="store_true")
    f.set_defaults(func=cmd_fetch)

    srcs = sub.add_parser("sources", help="列出可用数据源、是否需要 key、缓存/网络状态")
    srcs.add_argument("--probe", action="store_true", help="联网探测各站可达性（慢）")
    srcs.add_argument("--json", action="store_true")
    srcs.set_defaults(func=cmd_sources)

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

    # use-case subcommands (cifkit teach / bravais / metals / fec) live in a
    # separate module; registered last so they share the same parser conventions
    from cifkit.usecases_cli import register as register_usecase_commands

    register_usecase_commands(sub)

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
