"""Machine-readable contract for the embedding API (no third-party validator needed).

The operator schemas here are the single source of truth and are also written to
``cifkit/schemas/*.json`` so a platform can generate clients / validate at the
edge.  ``validate_request`` is a deliberately small JSON-Schema subset checker
(type/required/enum/additionalProperties) — enough for gating, with no
``jsonschema`` dependency.

    python -m cifkit.contract --dump        # rewrite cifkit/schemas/*.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"

_PASSTHROUGH = {"type": "object", "additionalProperties": True}

#: per-operation parameter schema (validated before dispatch)
OP_SCHEMAS: dict[str, dict[str, Any]] = {
    "capabilities": {"type": "object", "additionalProperties": False, "properties": {}},
    "features": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "path": {"type": "string"},
            "cif_text": {"type": "string"},
            "structure": {"type": "object"},
            "rdf": {"type": "boolean"},
            "rdf_bins": {"type": "integer", "minimum": 1},
            "rdf_max": {"type": "number", "exclusiveMinimum": 0},
            "topology": {"type": "boolean"},
            "rings": {"type": "boolean"},
            "symprec": {"type": "number", "exclusiveMinimum": 0},
        },
    },
    "features_many": {
        "type": "object",
        "additionalProperties": False,
        "required": ["paths"],
        "properties": {
            "paths": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "jobs": {"type": "integer", "minimum": 1, "maximum": 32},
            "rdf": {"type": "boolean"},
            "rings": {"type": "boolean"},
            "topology": {"type": "boolean"},
        },
    },
    "convert": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "path": {"type": "string"},
            "cif_text": {"type": "string"},
            "structure": {"type": "object"},
            "formats": {"type": "array", "items": {"type": "string"}},
            "bundles": {"type": "array", "items": {"type": "string"}},
            "outdir": {"type": "string"},
            "title": {"type": "string"},
        },
    },
    "dataset": {
        "type": "object",
        "additionalProperties": False,
        "required": ["runs_dir", "outdir"],
        "properties": {
            "runs_dir": {"type": "string"},
            "outdir": {"type": "string"},
            "features_enabled": {"type": "boolean"},
            "copy_structures": {"type": "boolean"},
            "label_key": {"type": "string"},
            "rdf": {"type": "boolean"},
            "topology": {"type": "boolean"},
        },
    },
    "topology": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "path": {"type": "string"},
            "cif_text": {"type": "string"},
            "structure": {"type": "object"},
            "net": {"type": "string", "enum": ["sod", "pcu", "dia", "fcu", "tbo", "bcu"]},
        },
    },
    "validate": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "path": {"type": "string"},
            "cif_text": {"type": "string"},
            "structure": {"type": "object"},
            "vacuum": {"type": "number", "minimum": 0},
        },
    },
}

#: top-level RPC request
REQUEST_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "cifkit request",
    "type": "object",
    "additionalProperties": False,
    "required": ["op"],
    "properties": {
        "op": {"type": "string", "enum": sorted(OP_SCHEMAS)},
        "params": {"type": "object"},
    },
}

#: top-level RPC response
RESPONSE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "cifkit response",
    "type": "object",
    "required": ["ok", "op", "api_version"],
    "properties": {
        "ok": {"type": "boolean"},
        "op": {"type": ["string", "null"]},
        "api_version": {"type": "string"},
        "elapsed_ms": {"type": "number"},
        "data": {"type": ["object", "null"]},
        "error": {
            "type": "object",
            "required": ["code", "message"],
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "detail": {},
            },
        },
        "http_status": {"type": "integer"},
        "params_echo": {"type": "object"},
    },
}

#: feature-table row (see docs/FEATURES.md); extra keys are allowed and versioned
FEATURE_ROW_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "cifkit feature row",
    "type": "object",
    "required": ["feature_version", "formula", "natoms", "a", "b", "c", "alpha", "beta", "gamma"],
    "properties": {
        "feature_version": {"const": "cifkit-features/v1"},
        "formula": {"type": "string"},
        "reduced_formula": {"type": "string"},
        "natoms": {"type": "integer", "minimum": 1},
        "n_elements": {"type": "integer", "minimum": 1},
        "metal_fraction": {"type": "number", "minimum": 0, "maximum": 1},
        "h_count": {"type": "integer", "minimum": 0},
        "spacegroup_number": {"type": ["integer", "null"]},
        "cn_mean": {"type": ["number", "null"]},
        "ring_basis": {"type": "string", "enum": ["metal-net", "full-bond-graph"]},
    },
}


def _type_ok(value: Any, spec: dict[str, Any]) -> bool:
    expected = spec.get("type")
    if expected is None:
        return True
    options = expected if isinstance(expected, list) else [expected]
    for option in options:
        if option == "object" and isinstance(value, dict):
            return True
        if option == "array" and isinstance(value, list):
            return True
        if option == "string" and isinstance(value, str):
            return True
        if option == "boolean" and isinstance(value, bool):
            return True
        if option == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if option == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if option == "null" and value is None:
            return True
    return False


def validate_against(instance: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Validate ``instance`` against the supported JSON-Schema subset."""
    errors: list[str] = []
    if not _type_ok(instance, schema):
        return [f"{path}: expected {schema.get('type')}, got {type(instance).__name__}"]
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in {schema['enum']}")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: {instance} > maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: {instance} <= exclusiveMinimum {schema['exclusiveMinimum']}")
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required key {key!r}")
        properties = schema.get("properties") or {}
        if schema.get("additionalProperties") is False:
            extra = [k for k in instance if k not in properties]
            for key in extra:
                errors.append(f"{path}: unexpected key {key!r}")
        for key, subschema in properties.items():
            if key in instance:
                errors.extend(validate_against(instance[key], subschema, f"{path}.{key}"))
    if isinstance(instance, list):
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(instance):
                errors.extend(validate_against(item, item_schema, f"{path}[{index}]"))
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
    return errors


def validate_request(request: Any) -> list[str]:
    """Return a list of contract violations for an RPC request (empty = valid)."""
    errors = validate_against(request, REQUEST_SCHEMA)
    if errors or not isinstance(request, dict):
        return errors
    op = request.get("op")
    schema = OP_SCHEMAS.get(op)
    if schema is None:
        return [f"$.op: unknown operation {op!r}"]
    return validate_against(request.get("params") or {}, schema, "$.params")


def validate_response(response: Any) -> list[str]:
    return validate_against(response, RESPONSE_SCHEMA)


def _dump() -> list[Path]:
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, payload in (
        ("request.json", REQUEST_SCHEMA),
        ("response.json", RESPONSE_SCHEMA),
        ("feature_row.json", FEATURE_ROW_SCHEMA),
        ("ops.json", {"$schema": "https://json-schema.org/draft/2020-12/schema",
                      "title": "cifkit operation parameters",
                      "type": "object",
                      "properties": OP_SCHEMAS}),
    ):
        path = SCHEMA_DIR / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":  # pragma: no cover - CLI convenience
    import sys

    if "--dump" in sys.argv:
        for path in _dump():
            print(f"wrote {path}")
    else:
        print("usage: python -m cifkit.contract --dump")
