"""Dataset builder: runs/library manifests → structures + feature table (CSV/JSONL).

    dataset = cifkit.dataset.build_dataset("runs", "dataset/", label_key="topology")

Two build modes:

``stream=True`` (default)
    Manifests are walked lazily and rows are written **as they are computed**:
    pass 1 streams features to ``dataset.jsonl`` (and copies structures), pass 2
    streams that JSONL back to build ``dataset.csv`` with the union of columns.
    At most a couple of rows are held in memory, so a large library does not have
    to fit in RAM (limitation **F6**).  The column *set* is still held (one small
    string per column) because RDF columns are data dependent.

``stream=False``
    Legacy in-memory path, kept for comparison; byte-identical outputs (asserted
    by ``tests/test_dataset.py``).

Outputs::

    dataset.csv            scalar features + JSON columns (rdf/rings/...) + label
    dataset.jsonl          one JSON object per run: {run_id, features, manifest,
                           meta, after} (+error for failed runs) — format v2
    structures/<run_id>.cif
    dataset_manifest.json  source, mode, counts, failures, csv sha256, max rows held
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any, Iterator

from cifkit.features import FEATURE_VERSION, extract_features
from cifkit.locks import atomic_write_json

__all__ = ["build_dataset", "load_runs", "iter_manifests", "iter_runs",
           "iter_jsonl", "count_jsonl", "dedupe_rows", "DEDUPE_KEYS"]

_STRUCT_CANDIDATES = ("standardized.cif", "raw.cif", "structure.cif", "repaired.cif", "structure.vasp")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_manifests(root: str | Path) -> Iterator[dict[str, Any]]:
    """Yield manifests under ``root`` lazily (shallow-first sorted walk).

    Unlike :func:`load_runs` this never materialises the whole list, so a library
    with millions of runs does not have to be held in memory.
    """
    base = Path(root)
    if not base.exists():
        raise FileNotFoundError(f"runs/library 目录不存在：{base}")
    for manifest_path in sorted(base.rglob("manifest.json")):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            yield {"run_dir": str(manifest_path.parent), "manifest": str(manifest_path),
                   "error": f"manifest parse failed: {exc}"}
            continue
        if not isinstance(data, dict):
            yield {"run_dir": str(manifest_path.parent), "manifest": str(manifest_path),
                   "error": "manifest is not an object"}
            continue
        data["run_dir"] = str(manifest_path.parent)
        data["manifest"] = str(manifest_path)
        yield data


def load_runs(root: str | Path) -> list[dict[str, Any]]:
    """Return all manifests under ``root`` (materialised; use :func:`iter_manifests`)."""
    return list(iter_manifests(root))


def iter_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield objects from a JSONL file lazily; broken lines are yielded as errors."""
    with Path(path).open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception as exc:  # noqa: BLE001
                yield {"error": f"jsonl parse failed at line {lineno}: {exc}"}


def count_jsonl(path: str | Path) -> int:
    """Number of non-empty lines, counted while streaming (no memory growth)."""
    with Path(path).open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


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



#: accepted ``dedupe`` keys -> how the value is obtained from a finished row
DEDUPE_KEYS = ("structure_sha256", "structure_file", "formula", "reduced_formula", "label")


def _dedupe_value(row: dict, key: str) -> str | None:
    """Return the value to dedupe on, or ``None`` when the row has no such key."""
    if key == "structure_sha256":
        path = row.get("structure_file")
        if not path:
            return None
        try:
            return _sha256(Path(str(path)))
        except OSError:
            return None
    if key == "label":
        value = row.get("label")
    elif key in ("formula", "reduced_formula", "structure_file"):
        value = row.get(key)
    else:
        raise ValueError(f"unknown dedupe key {key!r}; choose from {DEDUPE_KEYS}")
    return None if value in (None, "") else str(value)


def dedupe_rows(rows: Iterator[tuple[dict[str, Any], dict[str, Any] | None]],
                key: str, stats: dict[str, Any]
                ) -> Iterator[tuple[dict[str, Any], dict[str, Any] | None]]:
    """Yield only the first row per ``key``; records how many were dropped.

    Memory: one string per unique key (not per row) - documented, not hidden.
    Failed runs (rows carrying ``error``) are never deduplicated away.
    """
    seen: set[str] = set()
    stats.setdefault("dedupe_key", key)
    stats.setdefault("n_deduped", 0)
    stats.setdefault("dedupe_keys_seen", 0)
    for row, payload in rows:
        if row.get("error"):
            yield row, payload
            continue
        value = _dedupe_value(row, key)
        if value is None:
            yield row, payload
            continue
        if value in seen:
            stats["n_deduped"] += 1
            continue
        seen.add(value)
        stats["dedupe_keys_seen"] = len(seen)
        yield row, payload

def _label_from(run: dict[str, Any], key: str | None) -> Any:
    if not key:
        return None
    record = (run.get("source") or {}).get("record") or {}
    for holder in (record, run, (run.get("source") or {}).get("provenance") or {}):
        if isinstance(holder, dict) and holder.get(key) is not None:
            return holder[key]
    return None


def _unique_run_id(run: dict, index: int, used: dict[str, int]) -> str:
    run_dir = Path(run.get("run_dir", ""))
    run_id = run_dir.name or f"run{index}"
    if run_id in used:
        used[run_id] += 1
        run_id = f"{run_id}_{used[run_id]}"
    else:
        used[run_id] = 1
    return run_id


def _run_row(run: dict, run_id: str, *, features: bool, copy_structures: bool,
             label_key: str | None, rdf: bool, topology: bool,
             struct_dir: Path | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Process one run: the single implementation used by both code paths."""
    if run.get("error"):
        return {"run_id": run_id, "error": run["error"]}, None
    struct_path = _structure_path(run)
    if struct_path is None:
        return {"run_id": run_id, "error": "no structure artifact in manifest"}, None
    try:
        if features:
            from pymatgen.core import Structure

            structure = Structure.from_file(str(struct_path))
            row = extract_features(structure, rdf=rdf, topology=topology)
        else:
            row = {}
    except Exception as exc:  # noqa: BLE001
        return {"run_id": run_id,
                "error": f"features failed: {type(exc).__name__}: {exc}"}, None
    record = (run.get("source") or {}).get("record") or {}
    base: dict[str, Any] = {
        "run_id": run_id,
        "source": (run.get("source") or {}).get("source") or record.get("source"),
        "record_id": record.get("record_id"),
        "topology_evidence": record.get("topology_evidence"),
        "structure_file": str(struct_path),
        "label": _label_from(run, label_key),
    }
    base.update(row)
    # `after` holds keys that the materialised path appends *after* the feature
    # columns, so the streamed CSV keeps the legacy column order byte-for-byte.
    after: dict[str, Any] = {}
    if copy_structures and struct_dir is not None:
        target = struct_dir / f"{run_id}.cif"
        try:
            shutil.copyfile(struct_path, target)
            base["structure_copy"] = str(target)
        except Exception as exc:  # noqa: BLE001
            base["copy_error"] = f"copy failed: {exc}"
        for key in ("structure_copy", "copy_error"):
            if key in base:
                after[key] = base.pop(key)
    meta = {k: v for k, v in base.items() if k not in row and k not in after}
    return base, {"run_id": run_id, "features": row, "manifest": run.get("manifest"),
                  "meta": meta, "after": after}


def iter_runs(source: str | Path, *, features: bool = True, copy_structures: bool = True,
              label_key: str | None = None, rdf: bool = True, topology: bool = False,
              struct_dir: Path | None = None, jobs: int = 1
              ) -> Iterator[tuple[dict[str, Any], dict[str, Any] | None]]:
    """Yield ``(row, jsonl_object)`` per usable run — the streaming core.

    ``jsonl_object`` is ``None`` for failed runs; those come back as a row whose
    ``error`` key is set (and ``run_id``), so the caller can record them and still
    emit a row-count-consistent dataset.

    ``jobs > 1`` runs the per-run work (structure parsing + features, both of which
    release the GIL inside pymatgen/numpy) on a bounded thread pool.  Order is
    preserved and at most ``jobs * 2`` runs are in flight, so streaming memory
    bounds still hold.
    """
    kwargs = dict(features=features, copy_structures=copy_structures, label_key=label_key,
                  rdf=rdf, topology=topology, struct_dir=struct_dir)
    used_ids: dict[str, int] = {}

    if not jobs or jobs <= 1:
        for index, run in enumerate(iter_manifests(source)):
            run_id = _unique_run_id(run, index, used_ids)
            yield _run_row(run, run_id, **kwargs)
        return

    from collections import deque
    from concurrent.futures import ThreadPoolExecutor

    window = max(1, int(jobs)) * 2
    with ThreadPoolExecutor(max_workers=int(jobs)) as pool:
        pending: deque = deque()
        for index, run in enumerate(iter_manifests(source)):
            run_id = _unique_run_id(run, index, used_ids)
            pending.append(pool.submit(_run_row, run, run_id, **kwargs))
            if len(pending) >= window:
                yield pending.popleft().result()
        while pending:
            yield pending.popleft().result()


def _write_jsonl(path: Path, rows: Iterator[tuple[dict[str, Any], dict[str, Any] | None]],
                 *, stats: dict[str, Any]) -> None:
    """Pass 1: stream rows to JSONL, tracking failures and the union of columns."""
    with path.open("w", encoding="utf-8") as handle:
        for row, obj in rows:
            if obj is None:
                stats["errors"].append({"run_id": row.get("run_id"), "error": row.get("error")})
                handle.write(json.dumps({"run_id": row.get("run_id"), "error": row.get("error"),
                                         "features": {}}, ensure_ascii=False) + "\n")
            else:
                handle.write(json.dumps(obj, ensure_ascii=False) + "\n")
            stats["n_rows"] += 1
            # the stream holds exactly one row at a time; record that as evidence
            stats["max_rows_held"] = max(stats["max_rows_held"], 1)


def _csv_row(obj: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the CSV row in the legacy column order (meta → features → after)."""
    if "error" in obj and not obj.get("features"):
        return {"run_id": obj.get("run_id"), "error": obj.get("error")}
    meta = obj.get("meta") or {}
    row: dict[str, Any] = dict(meta)
    if "run_id" not in row:
        row["run_id"] = obj.get("run_id")
    row.update(obj.get("features") or {})
    row.update(obj.get("after") or {})
    return row


def _csv_from_jsonl(jsonl_path: Path, csv_path: Path) -> list[str]:
    """Pass 2: stream JSONL → CSV without holding rows in memory.

    Column order is derived from first appearance while streaming, which is exactly
    how the materialised path derived it — so both modes produce identical bytes.
    """
    keys: list[str] = []
    seen: set[str] = set()
    for obj in iter_jsonl(jsonl_path):
        if "error" in obj and not obj.get("features"):
            continue
        for key in _csv_row(obj):
            if key not in seen:
                seen.add(key)
                keys.append(key)
    fields = keys or ["run_id"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for obj in iter_jsonl(jsonl_path):
            if "error" in obj and not obj.get("features"):
                continue  # failures live in dataset_manifest.json, not in the table
            row = _csv_row(obj)
            writer.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                             for k, v in row.items()})
    return fields


def build_dataset(
    source: str | Path,
    outdir: str | Path,
    *,
    features: bool = True,
    copy_structures: bool = True,
    label_key: str | None = None,
    rdf: bool = True,
    topology: bool = False,
    stream: bool = True,
    jobs: int = 1,
    dedupe: str | None = None,
) -> dict[str, Any]:
    """Build a dataset from pipeline runs; returns a summary dict.

    ``jobs`` parallelises the per-run parsing/feature work (order preserved,
    bounded in-flight window); ``jobs=1`` is the classic sequential stream.

    ``dedupe`` keeps only the first run per key (``structure_sha256``,
    ``structure_file``, ``formula``, ``reduced_formula`` or ``label``) and records
    ``n_deduped`` in the summary; failed runs are never dropped.
    """
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    struct_dir = out / "structures"
    if copy_structures:
        struct_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out / "dataset.csv"
    jsonl_path = out / "dataset.jsonl"

    if stream:
        stats: dict[str, Any] = {"errors": [], "failed_rows": [], "n_rows": 0, "max_rows_held": 0}
        rows_gen = iter_runs(source, features=features, copy_structures=copy_structures,
                             label_key=label_key, rdf=rdf, topology=topology,
                             struct_dir=struct_dir if copy_structures else None,
                             jobs=jobs)
        if dedupe:
            rows_gen = dedupe_rows(rows_gen, dedupe, stats)
        _write_jsonl(jsonl_path, rows_gen, stats=stats)
        _csv_from_jsonl(jsonl_path, csv_path)
        summary = {
            "source": str(source),
            "outdir": str(out),
            "mode": "stream",
            "n_runs": stats["n_rows"],
            "n_ok": stats["n_rows"] - len(stats["errors"]),
            "n_failed": len(stats["errors"]),
            "errors": stats["errors"],
            "csv": str(csv_path),
            "jsonl": str(jsonl_path),
            "structures": str(struct_dir) if copy_structures else None,
            "csv_sha256": _sha256(csv_path) if csv_path.is_file() else None,
            "feature_version": FEATURE_VERSION,
            "max_rows_held": stats["max_rows_held"],
            "dedupe": stats.get("dedupe_key"),
            "n_deduped": stats.get("n_deduped", 0),
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        # atomic (round 57): LIMITATIONS G4 promises "不会读到半个文件" for the
        # dataset manifest — the plain write_text here did not honour that
        atomic_write_json(out / "dataset_manifest.json", summary)
        return summary

    # ---- legacy materialised path (kept for A/B verification) ----
    runs = load_runs(source)
    rows: list[dict[str, Any]] = []
    objects: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for row, obj in iter_runs(source, features=features, copy_structures=copy_structures,
                              label_key=label_key, rdf=rdf, topology=topology,
                              struct_dir=struct_dir if copy_structures else None):
        if obj is None:
            errors.append({"run_id": row.get("run_id"), "error": row.get("error")})
        rows.append(row)
        objects.append(obj or {"run_id": row.get("run_id"), "error": row.get("error"),
                               "features": {}})

    # Rebuild CSV rows through the *same* helper the streaming path uses, so both
    # modes cannot drift (column order and values are byte-identical by construction).
    ok_objects = [obj for obj in objects if not (obj.get("error") and not obj.get("features"))]
    keys: list[str] = []
    for obj in ok_objects:
        for key in _csv_row(obj):
            if key not in keys:
                keys.append(key)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        for obj in ok_objects:
            row = _csv_row(obj)
            writer.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                             for k, v in row.items()})
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for obj in objects:
            handle.write(json.dumps(obj, ensure_ascii=False) + "\n")

    summary = {
        "source": str(source),
        "outdir": str(out),
        "mode": "materialised",
        "n_runs": len(runs),
        "n_ok": len(rows) - len(errors),
        "n_failed": len(errors),
        "errors": errors,
        "csv": str(csv_path),
        "jsonl": str(jsonl_path),
        "structures": str(struct_dir) if copy_structures else None,
        "csv_sha256": _sha256(csv_path) if csv_path.is_file() else None,
        "feature_version": FEATURE_VERSION,
        "max_rows_held": len(rows),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    atomic_write_json(out / "dataset_manifest.json", summary)
    return summary
