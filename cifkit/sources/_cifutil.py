"""Small shared CIF helpers for the source adapters (header summary + parsing).

Kept separate from ``base.py`` (Lead-owned) so adapters can share code without
touching frozen shared modules.
"""
from __future__ import annotations

import hashlib
import re
import warnings
from pathlib import Path

_FORMULA_RE = re.compile(r"_chemical_formula_sum\s+['\"]?([^'\"\n]+)")
_CELL_RE = {
    "a": re.compile(r"_cell_length_a\s+([-+0-9.]+)"),
    "b": re.compile(r"_cell_length_b\s+([-+0-9.]+)"),
    "c": re.compile(r"_cell_length_c\s+([-+0-9.]+)"),
    "alpha": re.compile(r"_cell_angle_alpha\s+([-+0-9.]+)"),
    "beta": re.compile(r"_cell_angle_beta\s+([-+0-9.]+)"),
    "gamma": re.compile(r"_cell_angle_gamma\s+([-+0-9.]+)"),
}
_ELEMENT_RE = re.compile(r"([A-Z][a-z]?)\s*(\d+(?:\.\d+)?)?")


def parse_formula(formula: str | None) -> dict[str, float]:
    """Parse an elemental formula like ``"Zn6 H60 C48 N24"`` (ignores surrounding dashes)."""
    out: dict[str, float] = {}
    if not formula:
        return out
    for match in _ELEMENT_RE.finditer(str(formula)):
        element = match.group(1)
        count = match.group(2)
        try:
            value = float(count) if count else 1.0
        except ValueError:  # pragma: no cover - defensive
            continue
        if value <= 0:
            continue
        out[element] = out.get(element, 0.0) + value
    return out


def header_meta(text: str) -> dict:
    """Cheap header summary: ``{"formula", "cell", "formula_dict"}``."""
    formula_match = _FORMULA_RE.search(text)
    formula = formula_match.group(1).strip() if formula_match else None
    cell: dict[str, float | None] = {}
    for key, regex in _CELL_RE.items():
        match = regex.search(text)
        cell[key] = float(match.group(1)) if match else None
    return {"formula": formula, "cell": cell, "formula_dict": parse_formula(formula)}


def structure_from_bytes(data: bytes, label: str = "cif"):
    """Parse CIF bytes into a pymatgen ``Structure`` (single fallback path)."""
    from pymatgen.core import Structure

    text = data.decode("utf-8", "replace")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return Structure.from_str(text, fmt="cif")
        except Exception:  # noqa: BLE001 - fall back to explicit CifParser
            from pymatgen.io.cif import CifParser

            structures = CifParser.from_str(text).parse_structures(primitive=False)
            if not structures:
                raise ValueError(f"无法从 {label} 解析出结构")
            return structures[0]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
