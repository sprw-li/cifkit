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
from cifkit.types import RunResult, StructureRecord, TaskSpec

_PACKAGES = ["pymatgen", "ase", "numpy", "scipy", "networkx", "matplotlib", "rdkit", "openbabel-wheel"]


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
    for name in _PACKAGES:
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


def finish_run(result: RunResult) -> None:
    """Persist manifest + a human report; called by pipeline."""
    outdir = Path(result.outdir)
    manifest = new_manifest(result.spec)
    from cifkit.pipeline import _pipeline_state  # noqa: F401  (state attached by pipeline)

    # pipeline attaches the manifest dict to the RunResult via _manifest attribute
    manifest = getattr(result, "_manifest", manifest)  # type: ignore[attr-defined]
    result.manifest_path = write_manifest(outdir, manifest)
    result.artifacts["manifest"] = result.manifest_path
    report = render_report(result, manifest)
    report_path = outdir / "report.md"
    report_path.write_text(report, encoding="utf-8")
    result.artifacts["report"] = str(report_path)


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
    with index_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(meta, ensure_ascii=False) + "\n")
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
    if result.validation:
        v = result.validation
        lines.append(f"## 3. 校验：{'通过' if v.ok else '未通过'}")
        for c in v.checks:
            mark = "✅" if c.ok else ("⚠️" if c.severity == "warning" else "❌")
            lines.append(f"- {mark} {c.name}：{c.detail}")
        if v.metrics:
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(v.metrics, ensure_ascii=False, indent=2, default=str))
            lines.append("```")
        lines.append("")
    lines.append("## 4. 产物")
    for key, path in result.artifacts.items():
        lines.append(f"- {key}: `{path}`")
    return "\n".join(lines) + "\n"
