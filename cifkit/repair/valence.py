"""Post-repair valence / coordination checks for the repair layer.

The checks are intentionally cheap (one periodic bond perception) and are
used by :func:`cifkit.repair.repair_all` to fill ``RepairReport.warnings``:

* carbon must end with bond-order sum 4 (this is the "每个 C 四键" acceptance
  criterion for ZIF-8);
* N is allowed 3 or 4 (4 when metal-coordinated or cationic), O 2, S 2-6,
  B/P/Si their normal valences - under- or over-coordination is a warning;
* every H must be bonded to exactly one heavy atom (0 = hydride / isolated H,
  >1 = bridging hydrogen);
* metal coordination numbers are reported, and isolated / over-coordinated
  metals produce warnings;
* abnormal distances: any pair < 0.5 A, H...H < 1.2 A, H...heavy < 0.9 A,
  H...metal < 1.5 A.

A structure that passes all checks returns ``ok=True`` with an empty warning
list; the metrics dict always carries the numbers used in reports.
"""
from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np
from pymatgen.core import Structure

from cifkit.repair.bonds import (
    VALENCE,
    BondGraph,
    is_carboxylate_oxygen,
    is_metal,
    perceive_bonds,
    site_symbol,
)

# Accepted bond-order sums for neutral/organic chemistry.  The first value is
# the "normal" valence, the rest are tolerated (no warning).
_EXPECTED = {
    "C": (4,),
    "N": (3, 4),
    "O": (2,),
    "S": (2, 4, 6),
    "B": (3,),
    "P": (3, 5),
    "Si": (4,),
    "Se": (2, 4, 6),
}
_H_TOLERANCE = 1.5  # H...metal warning threshold in Angstrom


def _minimum_distances(structure: Structure, search: float) -> dict[str, float]:
    """Minimum interatomic distances by pair category (periodic images)."""
    symbols = [site_symbol(site) for site in structure]
    metals = [is_metal(symbol) for symbol in symbols]
    center, point, _offsets, distances = structure.get_neighbor_list(search)
    out = {
        "min_distance": np.inf,
        "min_hh": np.inf,
        "min_h_heavy": np.inf,
        "min_h_metal": np.inf,
    }
    # Nearest heavy atom of every H = its own X-H bond.  X-ray structures can
    # refine N-H to ~0.86 A, i.e. below the "clash" thresholds; those are
    # bonds, not overlaps, so they are excluded from the H...heavy metrics.
    nearest_heavy: dict[int, float] = {}
    for ci, pi, dist in zip(center, point, distances):
        a, b = int(ci), int(pi)
        if a == b:
            continue
        dist = float(dist)
        if symbols[a] == "H" and symbols[b] != "H":
            nearest_heavy[a] = min(nearest_heavy.get(a, np.inf), dist)
        elif symbols[b] == "H" and symbols[a] != "H":
            nearest_heavy[b] = min(nearest_heavy.get(b, np.inf), dist)
    for ci, pi, dist in zip(center, point, distances):
        a, b = int(ci), int(pi)
        if a == b:
            continue
        dist = float(dist)
        out["min_distance"] = min(out["min_distance"], dist)
        if symbols[a] == "H" and symbols[b] == "H":
            out["min_hh"] = min(out["min_hh"], dist)
        elif symbols[a] == "H" or symbols[b] == "H":
            h_index = a if symbols[a] == "H" else b
            other = b if h_index == a else a
            if abs(dist - nearest_heavy.get(h_index, np.inf)) < 0.02:
                continue  # the H's own bond
            if metals[other]:
                out["min_h_metal"] = min(out["min_h_metal"], dist)
            else:
                out["min_h_heavy"] = min(out["min_h_heavy"], dist)
    return out


def check_structure(
    structure: Structure,
    *,
    graph: BondGraph | None = None,
    min_distance_warn: float = 0.5,
    hh_warn: float = 1.2,
    h_heavy_warn: float = 0.9,
    h_metal_warn: float = _H_TOLERANCE,
) -> dict:
    """Run valence / coordination / distance checks.

    Returns a dict with ``ok``, ``warnings``, ``detail`` and ``metrics``.
    The structure is not modified.
    """
    graph = graph if graph is not None else perceive_bonds(structure)
    warnings: list[str] = list(graph.warnings)
    n = len(structure)

    bad_c: list[dict] = []
    bad_hetero: list[dict] = []
    bad_h: list[dict] = []
    metal_coordination: dict[int, int] = {}
    valence_by_element: dict[str, Counter] = defaultdict(Counter)
    for atom in range(n):
        symbol = graph.symbols[atom]
        if symbol == "H":
            bonds = graph.adj.get(atom, ())
            if len(bonds) != 1:
                bad_h.append({"atom": atom, "bonds": len(bonds)})
            continue
        if graph.metals[atom]:
            coordination = graph.metal_bond_count(atom)
            metal_coordination[atom] = coordination
            continue
        order_sum = graph.order_sum(atom)
        valence_by_element[symbol][round(order_sum * 2) / 2] += 1
        if symbol == "C":
            if abs(order_sum - 4.0) > 0.01:
                bad_c.append({"atom": atom, "order_sum": round(order_sum, 2)})
            continue
        expected = _EXPECTED.get(symbol)
        if expected is None:
            continue
        if symbol == "N" and graph.metal_bond_count(atom) and order_sum == 4.0:
            continue  # metal-coordinated aromatic N (imine-like) is fine
        if symbol == "O":
            # Carboxylate/carbonate oxygen: a deprotonated, uncoordinated O
            # legitimately has bond sum 1; a metal-coordinated O with one
            # short C-O can reach 3 (the dative metal bond is counted as 1).
            if graph.metal_bond_count(atom) and abs(order_sum - 3.0) < 0.01:
                continue
            if abs(order_sum - 1.0) < 0.01 and is_carboxylate_oxygen(graph, atom):
                continue
        if any(abs(order_sum - value) < 0.01 for value in expected):
            continue
        bad_hetero.append(
            {
                "atom": atom,
                "symbol": symbol,
                "order_sum": round(order_sum, 2),
                "expected": list(expected),
            }
        )

    # ---- warnings --------------------------------------------------------
    for entry in bad_c:
        warnings.append(f"C{entry['atom']} 键级和 {entry['order_sum']:.2f} != 4（非四价碳）")
    for entry in bad_hetero:
        warnings.append(
            f"原子 {entry['atom']}({entry['symbol']}) 键级和 {entry['order_sum']:.2f} "
            f"不在允许价态 {entry['expected']}"
        )
    for entry in bad_h:
        if entry["bonds"] == 0:
            warnings.append(f"H{entry['atom']} 未与任何重原子成键（游离 H/氢化物？）")
        else:
            warnings.append(f"H{entry['atom']} 与 {entry['bonds']} 个重原子成键（桥氢/异常氢）")
    if metal_coordination:
        for atom, coordination in metal_coordination.items():
            if coordination == 0:
                warnings.append(
                    f"金属 {atom}({graph.symbols[atom]}) 未探测到配位键（孤立金属，可能缺配体）"
                )
            elif coordination > 9:
                warnings.append(
                    f"金属 {atom}({graph.symbols[atom]}) 配位数 {coordination} 异常偏高"
                )

    distances = _minimum_distances(structure, search=3.0)
    if np.isfinite(distances["min_distance"]) and distances["min_distance"] < min_distance_warn:
        warnings.append(f"存在异常近距原子对：{distances['min_distance']:.2f} Å")
    if np.isfinite(distances["min_hh"]) and distances["min_hh"] < hh_warn:
        warnings.append(f"H···H 距离过近：{distances['min_hh']:.2f} Å < {hh_warn} Å")
    if np.isfinite(distances["min_h_heavy"]) and distances["min_h_heavy"] < h_heavy_warn:
        warnings.append(
            f"H···重原子 距离过近：{distances['min_h_heavy']:.2f} Å < {h_heavy_warn} Å"
        )
    if np.isfinite(distances["min_h_metal"]) and distances["min_h_metal"] < h_metal_warn:
        warnings.append(
            f"H···金属 距离过近：{distances['min_h_metal']:.2f} Å < {h_metal_warn} Å"
        )

    # ---- metrics / detail -----------------------------------------------
    h_count = sum(1 for symbol in graph.symbols if symbol == "H")
    metal_cn_counts: dict[str, dict[int, int]] = defaultdict(Counter)
    for atom, coordination in metal_coordination.items():
        metal_cn_counts[graph.symbols[atom]][coordination] += 1
    c_total = sum(1 for symbol in graph.symbols if symbol == "C")
    metrics = {
        "natoms": n,
        "formula": structure.composition.formula,
        "h_count": h_count,
        "c_count": c_total,
        "c_four_coordinate": c_total - len(bad_c),
        "c_bad": bad_c,
        "hetero_bad": bad_hetero,
        "h_bad": bad_h,
        "metal_coordination": {
            symbol: dict(sorted(counts.items())) for symbol, counts in metal_cn_counts.items()
        },
        "metal_bond_count": len([atom for atom in metal_coordination]),
        "valence_histogram": {
            symbol: {str(key): int(value) for key, value in counts.items()}
            for symbol, counts in valence_by_element.items()
        },
        "min_distance": _finite(distances["min_distance"]),
        "min_hh": _finite(distances["min_hh"]),
        "min_h_heavy": _finite(distances["min_h_heavy"]),
        "min_h_metal": _finite(distances["min_h_metal"]),
    }

    parts = [f"价态检查：C {metrics['c_four_coordinate']}/{c_total} 四配位"]
    if metal_cn_counts:
        cn_text = "; ".join(
            f"{symbol} CN={dict(sorted(counts.items()))}" for symbol, counts in metal_cn_counts.items()
        )
        parts.append(f"金属配位 {cn_text}")
    parts.append(f"H {h_count} 个")
    if np.isfinite(distances["min_distance"]):
        parts.append(f"最小原子间距 {distances['min_distance']:.2f} Å")
    parts.append("通过" if not warnings else f"{len(warnings)} 条警告")
    return {
        "ok": not warnings,
        "warnings": warnings,
        "metrics": metrics,
        "detail": "；".join(parts),
    }


def _finite(value: float) -> float | None:
    return round(float(value), 4) if np.isfinite(value) else None
