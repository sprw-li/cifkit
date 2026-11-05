"""Dataset builder: runs/library manifests → structures + feature table (CSV/JSONL).

    dataset = cifkit.dataset.build_dataset("runs", "dataset/", label_key="topology")

The builder scans ``<runs>/**/manifest.json`` (written by ``cifkit pipeline``),
picks a final structure per run (``standardized.cif`` preferred, then any CIF/VASP
artifact), computes features with :mod:`cifkit.features`, optionally copies the
structures, and writes:

    dataset.csv            scalar features + JSON columns (rdf/rings/...) + label
    dataset.jsonl          one JSON object per run (full feature dict)
    structures/<run_id>.cif
    dataset_manifest.json  source, tool version, counts, failures, csv sha256
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any

from cifkit.features import extract_features

__all__ = ["build_dataset", "load_runs"]

_STRUCT_CANDIDATES = ("standardized.cif", "raw.cif", "structure.cif", "repaired.cif", "structure.vasp")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_runs(root: str | Path) -> list[dict[str, Any]]:
    """Return manifests under ``root`` (walk for ``manifest.json``), shallow-first."""
    base = Path(root)
    if not base.exists():
        raise FileNotFoundError(f"runs/library 目录不存在：{base}")
    manifests = sorted(base.rglob("manifest.json"))
    runs: list[dict[str, Any]] = []
    for manifest_path in manifests:
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            runs.append({"run_dir": str(manifest_path.parent), "manifest": str(manifest_path),
                         "error": f"manifest parse failed: {exc}"})
            continue
        data["run_dir"] = str(manifest_path.parent)
        data["manifest"] = str(manifest_path)
        runs.append(data)
    return runs


def _structure_path(run: dict[str, Any]) -> Path | None:
    run_dir = Path(run.get("run_dir", ""))
    artifacts = run.get("artifacts") or {}
    for key in _STRUCT_CANDIDATES:
        value = artifacts.get(key)
        if value and Path(value).is_file():
            return Path(value)
    for key, value in artifacts.items():
        if isinstance(value, str) and value.lower().endswith((".cif", ".vasp")) and Path(value).is_file():
            return Path(value)
    for name in _STRUCT_CANDIDATES:
        candidate = run_dir / name
        if candidate.is_file():
            return candidate
    return None


def _label_from(run: dict[str, Any], key: str | None) -> Any:
    if not key:
        return None
    record = (run.get("source") or {}).get("record") or {}
    for holder in (record, run, (run.get("source") or {}).get("provenance") or {}):
        if isinstance(holder, dict) and holder.get(key) is not None:
            return holder[key]
    return None


def build_dataset(
    source: str | Path,
    outdir: str | Path,
    *,
    features: bool = True,
    copy_structures: bool = True,
    label_key: str | None = None,
    rdf: bool = True,
    topology: bool = False,
) -> dict[str, Any]:
    """Build a dataset from pipeline runs; returns a summary dict."""
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    struct_dir = out / "structures"
    if copy_structures:
        struct_dir.mkdir(parents=True, exist_ok=True)

    runs = load_runs(source)
    rows: list[dict[str, Any]] = []
    objects: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    used_ids: dict[str, int] = {}

    for index, run in enumerate(runs):
        run_dir = Path(run.get("run_dir", ""))
        run_id = run_dir.name or f"run{index}"
        if run_id in used_ids:
            used_ids[run_id] += 1
            run_id = f"{run_id}_{used_ids[run_id]}"
        else:
            used_ids[run_id] = 1
        if run.get("error"):
            errors.append({"run_id": run_id, "error": run["error"]})
            continue
        struct_path = _structure_path(run)
        if struct_path is None:
            errors.append({"run_id": run_id, "error": "no structure artifact in manifest"})
            continue
        try:
            if features:
                from pymatgen.core import Structure

                structure = Structure.from_file(str(struct_path))
                row = extract_features(structure, rdf=rdf, topology=topology)
            else:
                row = {}
        except Exception as exc:  # noqa: BLE001
            errors.append({"run_id": run_id, "error": f"features failed: {type(exc).__name__}: {exc}"})
            continue
        record = (run.get("source") or {}).get("record") or {}
        base = {
            "run_id": run_id,
            "source": (run.get("source") or {}).get("source") or record.get("source"),
            "record_id": record.get("record_id"),
            "topology_evidence": record.get("topology_evidence"),
            "structure_file": str(struct_path),
            "label": _label_from(run, label_key),
        }
        base.update(row)
        rows.append(base)
        objects.append({"run_id": run_id, "features": row, "manifest": run.get("manifest")})
        if copy_structures:
            target = struct_dir / f"{run_id}.cif"
            try:
                shutil.copyfile(struct_path, target)
                base["structure_copy"] = str(target)
            except Exception as exc:  # noqa: BLE001
                errors.append({"run_id": run_id, "error": f"copy failed: {exc}"})

    # CSV: union of keys, JSON-encode nested values
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    csv_path = out / "dataset.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = __import__("csv").DictWriter(handle, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                             for k, v in row.items()})
    jsonl_path = out / "dataset.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for obj in objects:
            handle.write(json.dumps(obj, ensure_ascii=False) + "\n")

    summary = {
        "source": str(source),
        "outdir": str(out),
        "n_runs": len(runs),
        "n_ok": len(rows),
        "n_failed": len(errors),
        "errors": errors,
        "csv": str(csv_path),
        "jsonl": str(jsonl_path),
        "structures": str(struct_dir) if copy_structures else None,
        "csv_sha256": _sha256(csv_path) if csv_path.is_file() else None,
        "feature_version": "cifkit-features/v1",
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    (out / "dataset_manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
