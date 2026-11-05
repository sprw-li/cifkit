"""Pipeline executor: resolve -> repair -> geometry -> export -> validate -> manifest."""
from __future__ import annotations

import time
import traceback
from pathlib import Path

from pymatgen.io.cif import CifWriter

from cifkit import sources
from cifkit.geom import extract_cluster, make_slab, make_supercell, set_vacuum, standardize
from cifkit.provenance import add_step, finish_run, ingest, new_manifest, record_source, write_json
from cifkit.repair import repair_all
from cifkit.types import RunResult, StepResult, TaskSpec
from cifkit.validate import validate_structure

from cifkit import export as export_mod
from cifkit import render as render_mod
from cifkit import topology as topology_mod


class _Ctx:
    def __init__(self, spec: TaskSpec) -> None:
        self.spec = spec
        self.outdir = Path(spec.outdir)
        self.outdir.mkdir(parents=True, exist_ok=True)
        self.structure = None
        self.record = None
        self.provenance: dict = {}
        self.result = RunResult(spec=spec, outdir=self.outdir)
        self.manifest = new_manifest(spec)

    # -- helpers -----------------------------------------------------------
    def save_cif(self, name: str, structure) -> str:
        path = self.outdir / name
        CifWriter(structure, symprec=None).write_file(str(path))
        self.result.artifacts[name] = str(path)
        return str(path)

    def step(self, name: str, detail: str = "", data: dict | None = None, artifacts: list[str] | None = None,
             status: str = "ok") -> StepResult:
        sr = StepResult(name=name, status=status, detail=detail, artifacts=artifacts or [], data=data or {})
        self.result.steps.append(sr)
        add_step(self.manifest, sr.to_dict())
        print(f"[{name}] {status} {detail}".rstrip(), flush=True)
        return sr


def _require_structure(ctx: _Ctx):
    if ctx.structure is None:
        raise RuntimeError("no structure loaded yet")
    return ctx.structure


def _step_resolve(ctx: _Ctx) -> None:
    t0 = time.time()
    fetched = sources.resolve(ctx.spec)
    ctx.structure = fetched.structure
    ctx.record = fetched.record
    ctx.provenance = dict(fetched.provenance or {})
    record_source(ctx.manifest, fetched.record, ctx.provenance)
    path = ctx.provenance.get("cif_path")
    if path and Path(path).is_file():
        dst = ctx.outdir / "raw.cif"
        dst.write_bytes(Path(path).read_bytes())
        ctx.result.artifacts["raw.cif"] = str(dst)
    else:
        ctx.save_cif("raw.cif", ctx.structure)
    detail = f"{fetched.record.record_id}  {fetched.record.formula or ''}  atoms={len(ctx.structure)}"
    if fetched.record.doi:
        detail += f"  DOI={fetched.record.doi}"
    ctx.step("resolve", detail, data={"record": fetched.record.to_dict(), "provenance": ctx.provenance,
                                      "elapsed_s": round(time.time() - t0, 2)})


def _step_verify_topology(ctx: _Ctx) -> None:
    expected = ctx.spec.topology
    if not expected:
        return
    t0 = time.time()
    result = topology_mod.verify(_require_structure(ctx), expected)
    ok = bool(result.get("ok"))
    detail = f"expected={expected} evidence={result.get('evidence')} {result.get('detail', '')}".strip()
    ctx.step("verify-topology", detail, data={**result, "elapsed_s": round(time.time() - t0, 2)},
             status="ok" if ok else "failed")
    if not ok:
        raise RuntimeError(f"topology mismatch: expected {expected}, got {result}")


def _step_repair(ctx: _Ctx) -> None:
    t0 = time.time()
    s = _require_structure(ctx)
    repaired, report = repair_all(
        s,
        add_hydrogen=ctx.spec.repair_h,
        resolve_disorder=ctx.spec.repair_disorder,
        remove_close_contacts=ctx.spec.remove_close_contacts,
    )
    ctx.structure = repaired
    ctx.save_cif("repaired.cif", repaired)
    detail = (f"add_H={report.added_h} removed={report.removed_atoms} "
              f"disorder={report.resolved_disorder} atoms={len(repaired)}")
    ctx.step("repair", detail, data={**report.to_dict(), "elapsed_s": round(time.time() - t0, 2)},
             artifacts=[ctx.result.artifacts.get("repaired.cif", "")])


def _step_standardize(ctx: _Ctx) -> None:
    t0 = time.time()
    s = standardize(_require_structure(ctx))
    ctx.structure = s
    ctx.save_cif("standardized.cif", s)
    info = dict(getattr(s, "_cifkit_geom_info", {}) or {})
    kept = info.get("kept")
    detail = f"atoms={len(s)} formula={s.composition.formula}" + (f" kept={kept}" if kept else "")
    ctx.step("standardize", detail,
             data={"elapsed_s": round(time.time() - t0, 2), "natoms": len(s), "geom_info": info})


def _step_cluster(ctx: _Ctx) -> None:
    t0 = time.time()
    s = extract_cluster(_require_structure(ctx), mode=ctx.spec.cluster_mode)
    ctx.structure = s
    ctx.save_cif("cluster.cif", s)
    ctx.step("cluster", f"mode={ctx.spec.cluster_mode} atoms={len(s)}",
             data={"elapsed_s": round(time.time() - t0, 2), "natoms": len(s)})


def _step_supercell(ctx: _Ctx) -> None:
    t0 = time.time()
    before = len(_require_structure(ctx))
    s = make_supercell(_require_structure(ctx), ctx.spec.supercell)
    ctx.structure = s
    ctx.save_cif("supercell.cif", s)
    reps = ctx.spec.supercell
    expected = before * reps[0] * reps[1] * reps[2]
    detail = f"{reps[0]}x{reps[1]}x{reps[2]} atoms {before}->{len(s)} (expected {expected}) abc={[round(x,3) for x in s.lattice.abc]}"
    ok = len(s) == expected
    ctx.step("supercell", detail, data={"elapsed_s": round(time.time() - t0, 2), "before": before,
                                        "after": len(s), "expected": expected, "lattice": list(s.lattice.abc)},
             status="ok" if ok else "failed")
    if not ok:
        raise RuntimeError(f"supercell atom count mismatch: {len(s)} != {expected}")


def _step_surface(ctx: _Ctx) -> None:
    t0 = time.time()
    slab, info = make_slab(
        _require_structure(ctx),
        ctx.spec.surface,
        slab_thickness=ctx.spec.slab_thickness or 15.0,
        vacuum=ctx.spec.vacuum if ctx.spec.vacuum is not None else 15.0,
        reps=ctx.spec.supercell,
        frame=ctx.spec.surface_frame,
    )
    ctx.structure = slab
    ctx.save_cif("slab.cif", slab)
    detail = (f"hkl={ctx.spec.surface} frame={info.get('frame')} reps={info.get('reps')} "
              f"atoms={len(slab)} abc={[round(x,3) for x in slab.lattice.abc]} "
              f"vacuum={info.get('vacuum_measured', info.get('vacuum'))}")
    ctx.step("surface", detail, data={**info, "elapsed_s": round(time.time() - t0, 2)})


def _step_vacuum(ctx: _Ctx) -> None:
    t0 = time.time()
    s, measured = set_vacuum(_require_structure(ctx), ctx.spec.vacuum)
    ctx.structure = s
    ctx.save_cif("final.cif", s)
    ok = measured + 1e-6 >= ctx.spec.vacuum
    detail = f"target={ctx.spec.vacuum} Å measured={measured:.3f} Å"
    ctx.step("vacuum", detail, data={"elapsed_s": round(time.time() - t0, 2), "measured": measured},
             status="ok" if ok else "failed")
    if not ok:
        raise RuntimeError(f"vacuum too small after adjustment: {measured}")


def _step_export(ctx: _Ctx) -> None:
    t0 = time.time()
    s = _require_structure(ctx)
    written: dict[str, str] = {}
    for fmt in ctx.spec.output_formats:
        path = export_mod.write_structure(s, ctx.outdir / f"structure.{_ext(fmt)}", fmt)
        written[fmt] = path
        ctx.result.artifacts[f"export.{fmt}"] = path
    ctx.step("export", "formats=" + ", ".join(written), data={"files": written,
                                                              "elapsed_s": round(time.time() - t0, 2)},
             artifacts=list(written.values()))


def _ext(fmt: str) -> str:
    return {
        "vasp": "vasp",
        "cif": "cif",
        "xyz": "xyz",
        "lammps": "lammps",
        "qe": "qe",
        "cp2k": "cp2k",
        "xsf": "xsf",
        "gaussian": "gjf",
        "orca": "orca",
        "abacus": "abacus",
    }.get(fmt, fmt)


def _step_validate(ctx: _Ctx) -> None:
    t0 = time.time()
    report = validate_structure(_require_structure(ctx), spec=ctx.spec)
    ctx.result.validation = report
    ctx.manifest["validation"] = report.to_dict()
    detail = ("PASS" if report.ok else "FAIL") + f" checks={len(report.checks)}"
    ctx.step("validate", detail, data={"elapsed_s": round(time.time() - t0, 2), "report": report.to_dict()},
             status="ok" if report.ok else "failed")


def _step_render(ctx: _Ctx) -> None:
    if render_mod is None:  # pragma: no cover - defensive
        return
    t0 = time.time()
    out = ctx.outdir / "preview.png"
    path = render_mod.render_structure(_require_structure(ctx), out, title=ctx.spec.query[:60])
    ctx.result.artifacts["preview.png"] = path
    ctx.step("render", path, data={"elapsed_s": round(time.time() - t0, 2)}, artifacts=[path])


_STEP_FUNCS = {
    "resolve": _step_resolve,
    "verify-topology": _step_verify_topology,
    "repair": _step_repair,
    "standardize": _step_standardize,
    "cluster": _step_cluster,
    "supercell": _step_supercell,
    "surface": _step_surface,
    "vacuum": _step_vacuum,
    "export": _step_export,
    "validate": _step_validate,
    "render": _step_render,
}


def run(spec: TaskSpec, *, embed: bool = False, ingest_run: bool = False) -> RunResult:
    from cifkit.plan import build_plan

    ctx = _Ctx(spec)
    ctx.result._manifest = ctx.manifest  # type: ignore[attr-defined]
    plan = build_plan(spec)
    (ctx.outdir / "plan.json").write_text(  # small, always useful for debugging
        __import__("json").dumps([s.__dict__ for s in plan], ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    failed = None
    for step in plan:
        if step.name == "manifest":
            continue  # commit step: written at the end, even for failed runs
        func = _STEP_FUNCS.get(step.name)
        if func is None:
            ctx.step(step.name, "no executor", status="skipped")
            continue
        try:
            func(ctx)
        except Exception as exc:  # noqa: BLE001 - record and stop
            tb = traceback.format_exc()
            already = (
                ctx.result.steps
                and ctx.result.steps[-1].name == step.name
                and ctx.result.steps[-1].status == "failed"
            )
            if step.optional:
                if not already:
                    ctx.step(step.name, f"optional step failed: {type(exc).__name__}: {exc}",
                             data={"traceback": tb}, status="skipped")
                continue
            if not already:  # step already recorded its own failure before raising
                ctx.step(step.name, f"{type(exc).__name__}: {exc}", data={"traceback": tb}, status="failed")
            failed = step.name
            break

    # ok is decided before the report is rendered, so report.md shows the truth
    ctx.result.ok = failed is None and bool(ctx.result.validation and ctx.result.validation.ok)
    if failed is not None:
        ctx.result.ok = False
    ctx.manifest["ok"] = ctx.result.ok
    ctx.manifest["failed_step"] = failed

    # manifest/report are written even for failed runs
    try:
        _step_commit(ctx, ingest_run=ingest_run and failed is None)
    except Exception as exc:  # noqa: BLE001
        ctx.step("manifest", f"{type(exc).__name__}: {exc}", status="failed")
        ctx.result.ok = False
    return ctx.result


def _step_commit(ctx: _Ctx, *, ingest_run: bool = False) -> None:
    ctx.manifest["ok"] = ctx.result.ok
    ctx.step("manifest", ctx.result.outdir.as_posix(), data={"ingest_requested": bool(ingest_run)})
    ctx.manifest["artifacts"] = dict(ctx.result.artifacts)
    # 1) report + manifest first (they are artifacts too)
    finish_run(ctx.result, ctx.manifest)
    # 2) ingest a complete run (manifest/report included)
    if ingest_run:
        try:
            info = ingest(ctx.result, ctx.manifest)
            ctx.manifest["library"] = info
            ctx.result.artifacts["library"] = info["library_entry"]
            ctx.manifest["artifacts"] = dict(ctx.result.artifacts)
            finish_run(ctx.result, ctx.manifest)  # rewrite report/manifest with library info
        except Exception as exc:  # noqa: BLE001 - ingest must not lose the run
            ctx.manifest["library"] = {"error": f"{type(exc).__name__}: {exc}"}
            finish_run(ctx.result, ctx.manifest)


# ---------------------------------------------------------------------------
def preview(spec: TaskSpec) -> dict:
    from cifkit.plan import build_plan

    return {
        "spec": spec.to_dict(),
        "plan": [s.__dict__ for s in build_plan(spec)],
    }
