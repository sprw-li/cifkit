"""Structure features for data pipelines / ML (composition, lattice, symmetry, coordination, RDF...).

The output of :func:`extract_features` is a flat ``dict`` that is JSON-serialisable
and CSV-friendly: scalar values stay scalar, while per-element / per-pair / list
data are stored as compact JSON strings (column names are stable).

This module deliberately has no I/O side effects; :func:`features_from_cif` and
:func:`features_many` are thin wrappers used by ``cifkit features``.
"""
from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from pymatgen.core import Structure

from cifkit.geom._common import coordination_numbers, element_symbol

__all__ = ["extract_features", "features_from_cif", "features_many", "FEATURE_VERSION"]

FEATURE_VERSION = "cifkit-features/v1"


def _round(value: float, ndigits: int = 6) -> float:
    try:
        return round(float(value), ndigits)
    except Exception:  # noqa: BLE001
        return float("nan")


def _element_counts(structure: Structure) -> dict[str, int]:
    counts: dict[str, int] = {}
    for site in structure:
        el = element_symbol(site)
        counts[el] = counts.get(el, 0) + 1
    return counts


def _symmetry(structure: Structure, symprec: float) -> dict[str, Any]:
    try:
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

        sga = SpacegroupAnalyzer(structure, symprec=symprec)
        symbol = sga.get_space_group_symbol()
        number = sga.get_space_group_number()
        point_group = sga.get_point_group_symbol()
        ops = len(sga.get_symmetry_operations())
        crystal_system = sga.get_crystal_system()
    except Exception:  # noqa: BLE001 - symmetry analysis is best-effort
        return {"spacegroup_number": None, "spacegroup_symbol": None, "point_group": None,
                "n_symops": None, "crystal_system": None}
    return {"spacegroup_number": int(number), "spacegroup_symbol": symbol,
            "point_group": point_group, "n_symops": int(ops), "crystal_system": crystal_system}


def _coordination(structure: Structure) -> dict[str, Any]:
    try:
        cns = np.asarray(coordination_numbers(structure), dtype=float).ravel().tolist()
    except Exception:  # noqa: BLE001
        return {"cn_mean": None, "cn_by_element": None, "cn_histogram": None}
    if not cns:
        return {"cn_mean": None, "cn_by_element": None, "cn_histogram": None}
    hist: dict[str, int] = {}
    for cn in cns:
        hist[str(int(cn))] = hist.get(str(int(cn)), 0) + 1
    by_el: dict[str, list[int]] = {}
    for site, cn in zip(structure, cns):
        by_el.setdefault(element_symbol(site), []).append(int(cn))
    per_el = {el: _round(float(np.mean(vals)), 3) for el, vals in by_el.items()}
    return {
        "cn_mean": _round(float(np.mean(cns)), 3),
        "cn_by_element": json.dumps(per_el, ensure_ascii=False, sort_keys=True),
        "cn_histogram": json.dumps(dict(sorted(hist.items(), key=lambda kv: int(kv[0]))), ensure_ascii=False),
    }


def _rdf(structure: Structure, *, bins: int, max_r: float) -> dict[str, Any]:
    """Element-pair radial distribution functions g(r) on a shared r grid."""
    elements = sorted({element_symbol(site) for site in structure})
    r_grid = np.linspace(0.0, float(max_r), int(bins) + 1)
    centers = 0.5 * (r_grid[:-1] + r_grid[1:])
    hist = {(a, b): np.zeros(int(bins), dtype=float) for i, a in enumerate(elements) for b in elements[i:]}
    counts = {a: 0 for a in elements}
    for site in structure:
        counts[element_symbol(site)] += 1
    volume = float(structure.volume)
    density = {el: (counts[el] / volume if volume > 0 else 0.0) for el in elements}
    for site in structure:
        el_i = element_symbol(site)
        try:
            neighbors = structure.get_neighbors(site, r=float(max_r))
        except Exception:  # noqa: BLE001
            continue
        for nb in neighbors:
            el_j = element_symbol(nb.specie) if hasattr(nb.specie, "symbol") else str(nb.specie)
            if el_j not in elements or el_i not in elements:
                continue
            r = float(nb.nn_distance)
            idx = int(np.searchsorted(r_grid, r, side="right") - 1)
            if 0 <= idx < int(bins):
                key = (el_i, el_j) if (el_i, el_j) in hist else (el_j, el_i)
                hist[key][idx] += 1.0
    result: dict[str, Any] = {"rdf_bins": int(bins), "rdf_max": float(max_r)}
    shell_vol = (4.0 / 3.0) * math.pi * (np.diff(r_grid) ** 3)
    for (a, b), raw in hist.items():
        norm = len(structure) * density[b] * shell_vol if density[b] > 0 else np.zeros_like(raw)
        g = np.divide(raw, norm, out=np.zeros_like(raw), where=norm > 0)
        result[f"rdf_{a}_{b}"] = json.dumps([_round(v, 4) for v in g])
    result["rdf_r"] = json.dumps([_round(v, 4) for v in centers])
    return result


def _topology(structure: Structure) -> dict[str, Any]:
    try:
        from cifkit.topology import identify

        info = identify(structure)
        return {
            "topology_net": info.get("net") or info.get("best_net") or "unknown",
            "topology_evidence": info.get("evidence", "unknown"),
        }
    except Exception:  # noqa: BLE001 - never fail a feature row because of topology
        return {"topology_net": "unknown", "topology_evidence": "unknown"}


def extract_features(
    structure: Structure,
    *,
    rdf: bool = True,
    rdf_bins: int = 50,
    rdf_max: float = 8.0,
    topology: bool = False,
    symprec: float = 0.1,
) -> dict[str, Any]:
    """Return a flat, JSON-serialisable feature dict for one structure."""
    if not isinstance(structure, Structure):
        raise ValueError(f"expected pymatgen Structure, got {type(structure).__name__}")
    if len(structure) == 0:
        raise ValueError("empty structure")
    counts = _element_counts(structure)
    natoms = len(structure)
    lat = structure.lattice
    elements = sorted(counts)
    from pymatgen.core import Element

    metal_atoms = sum(counts[el] for el in elements if Element(el).is_metal)
    features: dict[str, Any] = {
        "feature_version": FEATURE_VERSION,
        "formula": structure.composition.formula.replace(" ", ""),
        "reduced_formula": structure.composition.reduced_formula,
        "natoms": natoms,
        "n_elements": len(elements),
        "element_counts": json.dumps(counts, ensure_ascii=False, sort_keys=True),
        "atomic_fractions": json.dumps({el: _round(c / natoms, 6) for el, c in counts.items()},
                                       ensure_ascii=False, sort_keys=True),
        "metal_fraction": _round(metal_atoms / natoms, 6),
        "h_count": int(counts.get("H", 0)),
        "has_c": int("C" in counts),
        "has_organic_chemistry": int(any(el in counts for el in ("C", "N", "O", "S"))),
        "a": _round(lat.a), "b": _round(lat.b), "c": _round(lat.c),
        "alpha": _round(lat.alpha), "beta": _round(lat.beta), "gamma": _round(lat.gamma),
        "volume": _round(structure.volume), "density_g_cm3": _round(structure.density),
        "volume_per_atom": _round(structure.volume / natoms),
        "n_sites": natoms,
    }
    features.update(_symmetry(structure, symprec))
    features.update(_coordination(structure))
    if topology:
        features.update(_topology(structure))
    if rdf:
        try:
            features.update(_rdf(structure, bins=int(rdf_bins), max_r=float(rdf_max)))
        except Exception:  # noqa: BLE001 - RDF is optional
            features["rdf_error"] = "failed"
    return features


def features_from_cif(path: str | Path, **kwargs: Any) -> dict[str, Any]:
    """Load a structure file and return its feature dict (adds ``path``)."""
    p = Path(path)
    structure = Structure.from_file(str(p))
    row = extract_features(structure, **kwargs)
    row["path"] = str(p)
    row["filename"] = p.name
    return row


def features_many(
    paths: Iterable[str | Path],
    *,
    jobs: int = 4,
    rdf: bool = True,
    rdf_bins: int = 50,
    rdf_max: float = 8.0,
    topology: bool = False,
    symprec: float = 0.1,
) -> list[dict[str, Any]]:
    """Feature rows for many files; a bad file becomes ``{"path", "error"}`` (no exception)."""
    path_list = [Path(p) for p in paths]

    def _one(p: Path) -> dict[str, Any]:
        try:
            return features_from_cif(p, rdf=rdf, rdf_bins=rdf_bins, rdf_max=rdf_max,
                                     topology=topology, symprec=symprec)
        except Exception as exc:  # noqa: BLE001
            return {"path": str(p), "filename": p.name, "error": f"{type(exc).__name__}: {exc}"}

    if int(jobs) <= 1 or len(path_list) <= 1:
        return [_one(p) for p in path_list]
    with ThreadPoolExecutor(max_workers=max(1, int(jobs))) as pool:
        return list(pool.map(_one, path_list))
