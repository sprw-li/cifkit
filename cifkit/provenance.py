"""Run provenance: environment, sha256, manifest, and the local structure library."""
from __future__ import annotations

import datetime as _dt
import hashlib
import importlib.metadata as _md
import json
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

from cifkit.cache import project_root
from cifkit.locks import append_jsonl_locked
from cifkit.types import RunResult, StructureRecord, TaskSpec

#: packages whose *versions are recorded in every manifest*.  Only packages cifkit
#: actually imports belong here: ``openbabel-wheel`` (GPL-2.0) is listed as an
#: optional extra instead, because importing it is not required by any code path
#: (verified by ``scripts/verify_formats_no_gpl.py``).  See LICENSING.md.
_PACKAGES = ["pymatgen", "ase", "numpy", "scipy", "networkx", "matplotlib", "rdkit"]
_OPTIONAL_PACKAGES = ["openbabel-wheel"]


def now() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def environment() -> dict[str, Any]:
    versions: dict[str, str] = {}
    for name in [*_PACKAGES, *_OPTIONAL_PACKAGES]:
        try:
            versions[name] = _md.version(name)
        except Exception:  # noqa: BLE001 - optional packages
            pass
    try:
        import pymatgen  # noqa: F401

        versions.setdefault("pymatgen", "unknown")
    except Exception:  # noqa: BLE001
        pass
    return {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "platform": platform.platform(),
        "packages": versions,
        "project_root": str(project_root()),
    }


def new_manifest(spec: TaskSpec) -> dict[str, Any]:
    return {
        "schema": "cifkit/run/v1",
        "created_at": now(),
        "tool_version": _tool_version(),
        "query": spec.query,
        "spec": spec.to_dict(),
        "environment": environment(),
        "source": None,
        "steps": [],
        "artifacts": {},
        "validation": None,
        "library": None,
    }


def _tool_version() -> str:
    try:
        from cifkit import __version__

        return __version__
    except Exception:  # noqa: BLE001
        return "unknown"


def record_source(manifest: dict[str, Any], record: StructureRecord, provenance: dict[str, Any]) -> None:
    manifest["source"] = {"record": record.to_dict(), "provenance": provenance}


def add_step(manifest: dict[str, Any], step_dict: dict[str, Any]) -> None:
    manifest["steps"].append(step_dict)


def write_json(path: str | Path, data: dict[str, Any] | list[Any]) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(p)


def write_manifest(outdir: str | Path, manifest: dict[str, Any]) -> str:
    return write_json(Path(outdir) / "manifest.json", manifest)


def finish_run(result: RunResult, manifest: dict[str, Any] | None = None) -> None:
    """Persist report + manifest; both are listed in ``artifacts`` consistently.

    The report is rendered *after* seeding the report/manifest artifact entries,
    so a run's "产物" list always matches ``manifest["artifacts"]`` (this also
    holds for ``--ingest`` runs, where the library entry is appended and both
    files are rewritten).
    """
    outdir = Path(result.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    if manifest is None:
        manifest = getattr(result, "_manifest", None) or new_manifest(result.spec)
    report_path = outdir / "report.md"
    manifest_path = outdir / "manifest.json"
    result.artifacts["report"] = str(report_path)
    result.artifacts["manifest"] = str(manifest_path)
    result.manifest_path = str(manifest_path)
    manifest["artifacts"] = dict(result.artifacts)
    report = render_report(result, manifest)
    report_path.write_text(report, encoding="utf-8")
    manifest["artifacts"] = dict(result.artifacts)
    write_manifest(outdir, manifest)


def ingest(result: RunResult, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Copy final artifacts into the shared structure library (入库) and index them."""
    lib = project_root() / "library"
    lib.mkdir(parents=True, exist_ok=True)
    run_id = Path(result.outdir).name
    entry_dir = lib / run_id
    entry_dir.mkdir(parents=True, exist_ok=True)
    copied: dict[str, str] = {}
    for key, path in result.artifacts.items():
        p = Path(path)
        if p.is_file():
            dst = entry_dir / p.name
            if p.resolve() != dst.resolve():
                shutil.copy2(p, dst)
            copied[key] = str(dst)
    meta = {
        "run_id": run_id,
        "created_at": now(),
        "query": result.spec.query,
        "topology": result.spec.topology,
        "source": (manifest or {}).get("source"),
        "artifacts": copied,
        "validation_ok": result.validation.ok if result.validation else None,
    }
    write_json(entry_dir / "metadata.json", meta)
    index_path = lib / "index.jsonl"
    # Round 42 (G3): concurrent `--ingest` runs must not interleave lines.
    append_jsonl_locked(index_path, meta)
    return {"library_entry": str(entry_dir), "index": str(index_path)}


def render_report(result: RunResult, manifest: dict[str, Any]) -> str:
    spec = result.spec
    lines: list[str] = []
    lines.append(f"# CIF 处理报告：{Path(result.outdir).name}")
    lines.append("")
    lines.append(f"- 运行时间：{manifest.get('created_at')}")
    lines.append(f"- 是否成功：{'✅' if result.ok else '❌'}")
    lines.append(f"- 原始请求：{spec.query}")
    lines.append("")
    src = manifest.get("source") or {}
    if src:
        rec = src.get("record") or {}
        prov = src.get("provenance") or {}
        lines.append("## 1. 结构来源")
        lines.append(f"- 来源库：{rec.get('source')}")
        lines.append(f"- 记录 id：{rec.get('record_id')}")
        if rec.get("refcode"):
            lines.append(f"- refcode：{rec.get('refcode')}")
        if rec.get("doi"):
            lines.append(f"- DOI：https://doi.org/{rec.get('doi')}")
        if rec.get("topology"):
            lines.append(f"- 拓扑：{rec.get('topology')}（证据：{rec.get('topology_evidence')}）")
        if rec.get("formula"):
            lines.append(f"- 组成：{rec.get('formula')}")
        if prov.get("url"):
            lines.append(f"- URL：{prov.get('url')}")
        if prov.get("sha256"):
            lines.append(f"- CIF sha256：`{prov.get('sha256')}`")
        lines.append("")
    lines.append("## 2. 执行步骤")
    for s in result.steps:
        mark = {"ok": "✅", "skipped": "⏭", "failed": "❌"}.get(s.status, "?")
        lines.append(f"### {mark} {s.name}")
        if s.detail:
            lines.append(s.detail)
        lines.append("")

    lines.extend(_render_geometry_section(result))

    if result.validation:
        v = result.validation
        lines.append(f"## 4. 校验：{'通过' if v.ok else '未通过'}")
        for c in v.checks:
            mark = "✅" if c.ok else ("⚠️" if c.severity == "warning" else "❌")
            lines.append(f"- {mark} {c.name}：{c.detail}")
        if v.metrics:
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(v.metrics, ensure_ascii=False, indent=2, default=str))
            lines.append("```")
        lines.append("")
    else:
        failed = next((s.name for s in result.steps if s.status == "failed"), "?")
        lines.append(f"## 4. 校验：未运行（步骤 `{failed}` 失败）")
        lines.append("")
    lines.append("## 5. 产物")
    for key, path in result.artifacts.items():
        lines.append(f"- {key}: `{path}`")
    return "\n".join(lines) + "\n"


def _render_geometry_section(result: RunResult) -> list[str]:
    """Quote the measured geometry (slab thickness, vacuum, termination) from step data."""
    from cifkit.types import StepResult

    by_name: dict[str, StepResult] = {s.name: s for s in result.steps}
    surf = (by_name.get("surface").data if by_name.get("surface") else {}) or {}
    vac = (by_name.get("vacuum").data if by_name.get("vacuum") else {}) or {}
    last_metrics = {}
    if result.validation:
        last_metrics = dict(result.validation.metrics or {})
    surface_metrics = last_metrics or {}

    if not surf and not vac:
        return []
    lines = ["## 3. 结构几何（实测）", ""]
    if surf:
        lines.append(f"- 切面：({''.join(str(x) for x in surf.get('hkl', []))})，frame={surf.get('frame')}，reps={surf.get('reps')}")
        if surf.get("base_atoms"):
            lines.append(f"- 切面原子数：base={surf.get('base_atoms')} → 面内重复后 {surf.get('atoms_after_reps')}")
        if surf.get("slab_thickness") is not None:
            lines.append(f"- slab 厚度（原子垂直跨度）：{round(float(surf['slab_thickness']), 3)} Å")
        term = surf.get("termination")
        if isinstance(term, dict):
            bits = ", ".join(f"{k}={v}" for k, v in term.items() if k in {"shift", "dangling_bonds", "stoich_deviation", "index"})
            if bits:
                lines.append(f"- 终止面选择：{bits}")
        if surf.get("vacuum_measured") is not None:
            lines.append(f"- 生成时垂直真空：{round(float(surf['vacuum_measured']), 3)} Å")
        if surf.get("min_image_distance") is not None:
            lines.append(f"- 最小周期像距离：{round(float(surf['min_image_distance']), 3)} Å")
    if vac:
        if vac.get("measured") is not None:
            lines.append(f"- 最终垂直真空（实测）：{round(float(vac['measured']), 3)} Å")
        if vac.get("min_image_distance") is not None:
            lines.append(f"- 最终最小周期像距离：{round(float(vac['min_image_distance']), 3)} Å")
    if surface_metrics.get("natoms"):
        lines.append(f"- 最终原子数 / 组成：{surface_metrics.get('natoms')} / {surface_metrics.get('formula')}")
    if surface_metrics.get("lattice"):
        lat = surface_metrics["lattice"]
        lines.append(f"- 最终晶胞：a,b,c = {lat.get('abc')} Å；angles = {lat.get('angles')}°")
    lines.append("")
    return lines
