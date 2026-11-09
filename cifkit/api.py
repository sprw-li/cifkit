"""Embedding API: a stable, side-effect-free surface for commercial platforms.

The CLI (``python -m cifkit ...``) is for humans and agents; **platforms should
import this module instead**.  Design rules:

* every public function takes plain Python values and returns a
  **JSON-serialisable dict** (no pymatgen objects, no Paths in the result);
* no global mutable configuration: cache/behaviour is controlled by arguments or
  environment variables (``CIFKIT_CACHE``, ``CIFKIT_QMOF_DIR``, ``MP_API_KEY``);
* errors are typed exceptions with a stable ``code`` for HTTP mapping;
* functions are safe to call from threads (no shared mutable state).

Versioning: :data:`API_VERSION` follows the schema contract in ``docs/API.md``;
breaking changes bump the major number and are listed in ``docs/API.md``.

    from cifkit import api
    api.capabilities()                      # discovery
    api.features(path="a.cif", rdf=False)   # feature dict
    api.convert(path="a.cif", formats=["vasp"], bundles=["qe"], outdir="out")
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any, Iterable

#: contract version of this module's request/response shapes
API_VERSION = "1.0"
#: version of the feature table schema produced by :func:`features`
FEATURE_SCHEMA_VERSION = "cifkit-features/v1"

#: text formats can be returned as ``str``; everything else is base64
BINARY_FORMATS = {"png", "zip"}


class CifkitError(Exception):
    """Base class for API errors; ``code`` is stable for HTTP/JSON mapping."""

    code = "cifkit-error"
    http_status = 500

    def __init__(self, message: str, *, detail: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail is not None:
            payload["detail"] = self.detail
        return payload


class InvalidRequest(CifkitError):
    code = "invalid-request"
    http_status = 400


class UnsupportedFormat(CifkitError):
    code = "unsupported-format"
    http_status = 400


class NotFound(CifkitError):
    code = "not-found"
    http_status = 404


class UpstreamUnavailable(CifkitError):
    code = "upstream-unavailable"
    http_status = 502


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _load_structure(*, path: str | Path | None = None, structure: Any = None,
                    cif_text: str | None = None, cif_bytes: bytes | None = None):
    """Resolve the ``path``/``structure``/``cif_text`` arguments to a Structure."""
    from pymatgen.core import Structure

    given = [name for name, value in (("path", path), ("cif_text", cif_text),
                                      ("cif_bytes", cif_bytes), ("structure", structure))
             if value is not None]
    if len(given) > 1:
        raise InvalidRequest(f"give exactly one of path / cif_text / cif_bytes / structure, got {given}")
    if structure is not None:
        if not isinstance(structure, Structure):
            raise InvalidRequest(f"structure must be a pymatgen Structure, got {type(structure).__name__}")
        if len(structure) == 0:
            raise InvalidRequest("structure is empty")
        return structure
    if sum(x is not None for x in (path, cif_text, cif_bytes)) != 1:
        raise InvalidRequest("give exactly one of path / cif_text / cif_bytes / structure")
    if path is not None:
        p = Path(path)
        if not p.is_file():
            raise NotFound(f"structure file not found: {p}")
        try:
            from cifkit.cli import _load_structure_any

            return _load_structure_any(p)
        except Exception as exc:  # noqa: BLE001
            raise InvalidRequest(f"cannot parse {p}: {type(exc).__name__}: {exc}") from exc
    data = cif_bytes if cif_bytes is not None else str(cif_text).encode("utf-8")
    try:
        return Structure.from_str(data.decode("utf-8"), fmt="cif")
    except Exception as exc:  # noqa: BLE001
        raise InvalidRequest(f"cannot parse CIF text: {type(exc).__name__}: {exc}") from exc


def _version_of(name: str) -> str | None:
    import importlib.metadata as md

    try:
        return md.version(name)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------
def capabilities() -> dict[str, Any]:
    """Describe what this deployment can do (for platform feature discovery)."""
    from cifkit import export
    from cifkit.features import FEATURE_VERSION
    from cifkit.sources import available_sources, source_status

    return {
        "api_version": API_VERSION,
        "feature_schema_version": FEATURE_VERSION,
        "operations": sorted(OPS),
        "formats": export.supported_formats(),
        "bundles": export.supported_bundles(),
        "sources": source_status(),
        "sources_available": sorted(available_sources()),
        "requires_key": [row["name"] for row in source_status() if row.get("requires_auth")],
        "offline_operations": ["capabilities", "features", "convert", "dataset", "topology", "validate"],
        "versions": {name: _version_of(name) for name in
                     ("cifkit", "pymatgen", "ase", "spglib", "numpy", "rdkit")},
        "limits": {
            "max_atoms_features_no_rdf": 20000,
            "ring_stats_atom_cap": 600,
            "bundle_files_require_licences": True,
        },
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


# ---------------------------------------------------------------------------
# fetch (network)
# ---------------------------------------------------------------------------
#: provenance keys that contain local filesystem paths (hidden from hosts by default)
_LOCAL_PATH_KEYS = ("cif_path", "json_path", "path", "mirror_dir", "archive")


def _sanitize_provenance(prov: dict[str, Any], *, include_paths: bool) -> dict[str, Any]:
    out = dict(prov or {})
    if not include_paths:
        for key in _LOCAL_PATH_KEYS:
            out.pop(key, None)
        out["paths_hidden"] = True
    return out


def fetch(*, source: str = "auto", topology: str | None = None, name: str | None = None,
          structure_id: str | None = None, raw: bool = True, limit: int = 5,
          include_structure: bool = True, include_paths: bool = False) -> dict[str, Any]:
    """Resolve one structure from a data source and return it **inline**.

    Platforms should prefer this over shelling out to ``cifkit fetch``: the result
    is a plain dict (record + provenance + CIF text), local paths are hidden by
    default, and no API key ever appears in the payload (keys are read from the
    environment by the source adapters and never copied into provenance).
    """
    from cifkit.sources import pick_source, resolve
    from cifkit.types import TaskSpec

    spec = TaskSpec(source=source or "auto", topology=topology, structure_name=name,
                    structure_id=structure_id)
    if str(source or "auto").lower() in ("", "auto"):
        try:
            spec.source = pick_source(spec)
        except Exception:  # noqa: BLE001 - keep 'auto' and let resolve decide
            spec.source = "auto"
    if limit is not None and int(limit) <= 0:
        raise InvalidRequest("limit must be positive")
    try:
        fetched = resolve(spec)
    except FileNotFoundError as exc:
        raise NotFound(str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        lowered = message.lower()
        if any(token in lowered for token in ("不存在", "not found", "no such file", "no hits")):
            raise NotFound(message) from exc
        raise InvalidRequest(message) from exc
    except Exception as exc:  # noqa: BLE001 - network/upstream problems
        message = str(exc)
        code_hint = message.lower()
        if any(word in code_hint for word in ("http", "url", "timeout", "network", "connection",
                                              "502", "503", "resolve", "temporar")):
            raise UpstreamUnavailable(f"{type(exc).__name__}: {message}") from exc
        raise UpstreamUnavailable(f"{type(exc).__name__}: {message}") from exc

    record = fetched.record
    result: dict[str, Any] = {
        "source": record.source,
        "record": record.to_dict(),
        "provenance": _sanitize_provenance(fetched.provenance or {}, include_paths=include_paths),
        "natoms": len(fetched.structure),
        "formula": fetched.structure.composition.formula.replace(" ", ""),
        "topology_evidence": record.topology_evidence,
        "api_version": API_VERSION,
    }
    if include_structure:
        try:
            from pymatgen.io.cif import CifWriter

            result["cif_text"] = str(CifWriter(fetched.structure, symprec=None))
        except Exception as exc:  # noqa: BLE001 - inline text is best-effort
            result["cif_text_error"] = f"{type(exc).__name__}: {exc}"
    return result


# ---------------------------------------------------------------------------
# features
# ---------------------------------------------------------------------------
def features(*, path: str | Path | None = None, structure: Any = None, cif_text: str | None = None,
             rdf: bool = True, rdf_bins: int = 50, rdf_max: float = 8.0,
             topology: bool = False, rings: bool = False, symprec: float = 0.1) -> dict[str, Any]:
    """Return the feature dict for one structure (``FEATURE_SCHEMA_VERSION``)."""
    from cifkit.features import extract_features

    obj = _load_structure(path=path, structure=structure, cif_text=cif_text)
    if int(rdf_bins) <= 0 or float(rdf_max) <= 0:
        raise InvalidRequest("rdf_bins and rdf_max must be positive")
    row = extract_features(obj, rdf=rdf, rdf_bins=int(rdf_bins), rdf_max=float(rdf_max),
                           topology=topology, rings=rings, symprec=float(symprec))
    if path is not None:
        row["path"] = str(path)
        row["filename"] = Path(path).name
    return row


def features_many(paths: Iterable[str | Path], *, jobs: int = 4, rdf: bool = True,
                  rings: bool = False, topology: bool = False) -> dict[str, Any]:
    """Batch features; bad inputs are reported per item instead of raising."""
    from cifkit.features import features_many as _many

    items = [str(p) for p in paths]
    if not items:
        raise InvalidRequest("paths is empty")
    rows = _many(items, jobs=int(jobs), rdf=rdf, rings=rings, topology=topology)
    ok = sum(1 for r in rows if not r.get("error"))
    return {"ok": ok == len(rows), "n_inputs": len(rows), "n_ok": ok,
            "n_failed": len(rows) - ok, "rows": rows}


# ---------------------------------------------------------------------------
# conversion
# ---------------------------------------------------------------------------
def convert(*, path: str | Path | None = None, structure: Any = None, cif_text: str | None = None,
            formats: Iterable[str] | None = None, bundles: Iterable[str] | None = None,
            outdir: str | Path | None = None, title: str | None = None) -> dict[str, Any]:
    """Write formats/bundles for one structure.

    With ``outdir`` the files are written to disk and paths are returned; without
    it the content is returned inline (``{"text": ...}`` for text formats,
    ``{"base64": ...}`` for binary) so a platform never needs a scratch volume.
    """
    from cifkit import export

    obj = _load_structure(path=path, structure=structure, cif_text=cif_text)
    fmt_list = [str(f).strip().lower() for f in (formats or []) if str(f).strip()]
    bundle_list = [str(b).strip().lower() for b in (bundles or []) if str(b).strip()]
    if not fmt_list and not bundle_list:
        raise InvalidRequest("give at least one of formats / bundles")
    try:
        fmt_list = [export.normalize_format(f) for f in fmt_list]
    except ValueError as exc:
        raise UnsupportedFormat(str(exc)) from exc
    available_bundles = export.supported_bundles()
    bad = [b for b in bundle_list if b not in available_bundles]
    if bad:
        raise UnsupportedFormat(f"unsupported bundle(s): {bad}; available: {sorted(available_bundles)}")

    name = title or (Path(path).stem if path is not None else "structure")

    if outdir is None:
        result: dict[str, Any] = {"outdir": None, "formats": {}, "bundles": {}, "name": name,
                                  "natoms": len(obj)}
        for fmt in fmt_list:
            try:
                text = export.render_structure_text(obj, fmt, title=title)
            except AttributeError:  # pragma: no cover - older export layer
                raise UnsupportedFormat(f"inline rendering not available for {fmt}") from None
            except Exception as exc:  # noqa: BLE001
                raise InvalidRequest(f"cannot render {fmt}: {type(exc).__name__}: {exc}") from exc
            if isinstance(text, bytes):
                result["formats"][fmt] = {"base64": base64.b64encode(text).decode("ascii"),
                                          "encoding": "base64"}
            else:
                result["formats"][fmt] = {"text": text, "encoding": "utf-8"}
        return result

    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for fmt in fmt_list:
        try:
            written[fmt] = export.write_structure(obj, out / f"{name}.{fmt}", fmt, title=title)
        except Exception as exc:  # noqa: BLE001
            raise InvalidRequest(f"cannot write {fmt}: {type(exc).__name__}: {exc}") from exc
    bundle_written: dict[str, Any] = {}
    for code in bundle_list:
        try:
            bundle_written[code] = export.write_bundle(obj, code, out / code, title=title)
        except Exception as exc:  # noqa: BLE001
            raise InvalidRequest(f"cannot write bundle {code}: {type(exc).__name__}: {exc}") from exc
    return {"outdir": str(out), "formats": written, "bundles": bundle_written,
            "name": name, "natoms": len(obj)}


# ---------------------------------------------------------------------------
# dataset / topology / validate
# ---------------------------------------------------------------------------
def dataset(*, runs_dir: str | Path, outdir: str | Path, features_enabled: bool = True,
            copy_structures: bool = True, label_key: str | None = None,
            rdf: bool = True, topology: bool = False) -> dict[str, Any]:
    """Build a dataset from pipeline runs; returns the dataset summary."""
    from cifkit.dataset import build_dataset

    src = Path(runs_dir)
    if not src.exists():
        raise NotFound(f"runs dir not found: {src}")
    return build_dataset(src, Path(outdir), features=features_enabled,
                         copy_structures=copy_structures, label_key=label_key,
                         rdf=rdf, topology=topology)


def topology(*, path: str | Path | None = None, structure: Any = None, cif_text: str | None = None,
             net: str | None = None) -> dict[str, Any]:
    """Identify the underlying net, or verify against ``net`` when given."""
    from cifkit.topology import identify, verify

    obj = _load_structure(path=path, structure=structure, cif_text=cif_text)
    if net:
        result = verify(obj, str(net).lower())
    else:
        result = identify(obj)
    result = dict(result)
    result["api_version"] = API_VERSION
    return result


def validate(*, path: str | Path | None = None, structure: Any = None, cif_text: str | None = None,
             vacuum: float | None = None) -> dict[str, Any]:
    """Structural validation report (checks + metrics), JSON-serialisable."""
    from cifkit.types import TaskSpec
    from cifkit.validate import validate_structure

    obj = _load_structure(path=path, structure=structure, cif_text=cif_text)
    spec = TaskSpec(vacuum=float(vacuum)) if vacuum is not None else None
    report = validate_structure(obj, spec=spec)
    return {
        "ok": bool(report.ok),
        "checks": [{"name": c.name, "ok": bool(c.ok), "severity": c.severity, "detail": c.detail}
                   for c in report.checks],
        "metrics": report.metrics,
        "api_version": API_VERSION,
    }


#: operations exposed through :mod:`cifkit.service` (name -> callable)
OPS: dict[str, Any] = {
    "capabilities": capabilities,
    "fetch": fetch,
    "features": features,
    "features_many": features_many,
    "convert": convert,
    "dataset": dataset,
    "topology": topology,
    "validate": validate,
}

__all__ = [
    "API_VERSION",
    "FEATURE_SCHEMA_VERSION",
    "CifkitError",
    "InvalidRequest",
    "UnsupportedFormat",
    "NotFound",
    "UpstreamUnavailable",
    "capabilities",
    "fetch",
    "features",
    "features_many",
    "convert",
    "dataset",
    "topology",
    "validate",
    "OPS",
]
