"""Disorder / partial-occupancy resolution for the repair layer.

pymatgen's ``CifParser`` keeps partial occupancies in the site species dict
(``{Element: occupancy}``) but drops ``_atom_site_disorder_group`` /
``_atom_site_disorder_assembly``.  This module therefore has two entry
levels:

* :func:`parse_atom_site_loop` - a small, dependency-free CIF text parser that
  returns the per-site occupancy / disorder-group / disorder-assembly records;
* :func:`resolve_disorder` - works directly on a pymatgen ``Structure`` using
  the occupancies embedded in the species dict (so it also works through
  ``cifkit repair FILE`` where the raw CIF text is not available), and uses
  the parsed records when a ``cif_text`` is supplied.

Resolution strategy
-------------------
* heavy atoms with partial occupancy: alternative positions closer than
  0.7 A form one disorder group; keep the highest-occupancy site (ties -> the
  alphabetically first label / index).  A lone partial heavy site is promoted
  to its majority element with a warning.
* hydrogen atoms with partial occupancy (the common "statistical methyl"
  model): every partial H is assigned to its parent heavy atom; the number of
  H the parent still needs is derived from the heavy-atom bond graph
  (valences / aromatic-ring perception, i.e. the same rules as hydrogen
  completion).  Of the candidate H positions the compatible subset (all
  H...H > 1.2 A) is selected - for ZIF-8 this picks one methyl orientation
  out of the two modelled ones.  Fully occupied H are always kept.
* ``_atom_site_disorder_group`` information, when available, is honoured
  first: whole groups are selected by total occupancy.
"""
from __future__ import annotations

import re
import shlex
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from pymatgen.core import Structure

from cifkit.repair.bonds import (
    is_metal,
    perceive_bonds,
    hydrogen_demand,
    site_occupancy,
    site_symbol,
)
from cifkit.repair._labels import ensure_unique_labels

_NUMBER = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
_IMAGE_OFFSETS = np.asarray(
    [[a, b, c] for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1)], dtype=float
)


# ---------------------------------------------------------------------------
# CIF text parsing
# ---------------------------------------------------------------------------
@dataclass
class AtomSiteRecord:
    """One ``_atom_site_*`` row from a CIF file."""

    label: str
    symbol: str
    frac: tuple[float, float, float]
    occupancy: float = 1.0
    disorder_group: str | None = None
    disorder_assembly: str | None = None
    multiplicity: float | None = None
    charge: float | None = None


def _parse_float(token: str) -> float | None:
    token = token.strip().strip("'\"")
    match = _NUMBER.search(token)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:  # pragma: no cover - regex guarantees a number
        return None


def parse_atom_site_loop(cif_text: str) -> list[AtomSiteRecord]:
    """Parse ``_atom_site_*`` loop(s) out of raw CIF text.

    Supports the standard columns ``_atom_site_type_symbol``,
    ``_atom_site_label``, ``_atom_site_fract_x/y/z``,
    ``_atom_site_occupancy``, ``_atom_site_disorder_group``,
    ``_atom_site_disorder_assembly``, ``_atom_site_symmetry_multiplicity`` and
    ``_atom_site_charge``.  Values with standard uncertainties (``0.123(4)``)
    and quoted strings are accepted.
    """
    lines = cif_text.splitlines()
    records: list[AtomSiteRecord] = []
    index = 0
    n_lines = len(lines)
    while index < n_lines:
        line = lines[index]
        stripped = line.strip()
        if stripped.lower() != "loop_":
            index += 1
            continue
        index += 1
        headers: list[str] = []
        while index < n_lines and lines[index].strip().startswith("_"):
            headers.append(lines[index].strip().lower())
            index += 1
        if not headers or "atom_site" not in headers[0]:
            continue
        rows: list[list[str]] = []
        while index < n_lines:
            row_line = lines[index].strip()
            if not row_line or row_line.startswith("#"):
                index += 1
                continue
            lowered = row_line.lower()
            if lowered.startswith(("loop_", "data_", "_", "stop_")):
                break
            tokens = shlex.split(row_line, posix=True)
            if tokens:
                rows.append(tokens)
            index += 1
        column = {name: position for position, name in enumerate(headers)}

        def value(tokens: list[str], name: str, default: str | None = None) -> str | None:
            position = column.get(name)
            if position is None or position >= len(tokens):
                return default
            return tokens[position]

        def clean(token: str | None) -> str | None:
            if token is None:
                return None
            token = token.strip().strip("'\"")
            if token in {"", ".", "?"}:
                return None
            return token

        for tokens in rows:
            symbol = value(tokens, "_atom_site_type_symbol")
            label = value(tokens, "_atom_site_label") or ""
            fx = _parse_float(value(tokens, "_atom_site_fract_x") or "")
            fy = _parse_float(value(tokens, "_atom_site_fract_y") or "")
            fz = _parse_float(value(tokens, "_atom_site_fract_z") or "")
            if symbol is None or fx is None or fy is None or fz is None:
                continue
            symbol = symbol.strip("'\"")
            # strip oxidation state / charge suffix such as "Zn2+" / "O2-"
            match = re.match(r"([A-Za-z]{1,2})", symbol)
            symbol = match.group(1) if match else symbol
            occupancy = _parse_float(value(tokens, "_atom_site_occupancy") or "1") or 1.0
            disorder_group = clean(value(tokens, "_atom_site_disorder_group"))
            disorder_assembly = clean(value(tokens, "_atom_site_disorder_assembly"))
            multiplicity = _parse_float(value(tokens, "_atom_site_symmetry_multiplicity") or "")
            charge = _parse_float(value(tokens, "_atom_site_charge") or "")
            records.append(
                AtomSiteRecord(
                    label=label.strip("'\""),
                    symbol=symbol,
                    frac=(fx, fy, fz),
                    occupancy=occupancy,
                    disorder_group=disorder_group,
                    disorder_assembly=disorder_assembly,
                    multiplicity=multiplicity,
                    charge=charge,
                )
            )
    return records


def read_cif_atom_sites(path: str | Path) -> list[AtomSiteRecord]:
    """Convenience wrapper: parse atom sites from a CIF file path."""
    return parse_atom_site_loop(Path(path).read_text(encoding="utf-8", errors="replace"))


# ---------------------------------------------------------------------------
# Structure helpers
# ---------------------------------------------------------------------------
def _min_image_distance(lattice: np.ndarray, frac_a: np.ndarray, frac_b: np.ndarray) -> float:
    delta = frac_a[None, :] - frac_b[None, :] + _IMAGE_OFFSETS
    return float(np.linalg.norm(delta @ lattice, axis=1).min())


def _match_records(
    structure: Structure, records: list[AtomSiteRecord]
) -> list[AtomSiteRecord | None]:
    """Match parsed CIF rows to structure sites by element + coordinates."""
    if not records:
        return [None] * len(structure)
    lattice = np.asarray(structure.lattice.matrix, dtype=float)
    by_symbol: dict[str, list[AtomSiteRecord]] = defaultdict(list)
    for record in records:
        by_symbol[record.symbol].append(record)
    matched: list[AtomSiteRecord | None] = []
    for site_index, site in enumerate(structure):
        symbol = site_symbol(site)
        frac = np.asarray(site.frac_coords, dtype=float)
        best: tuple[float, int, AtomSiteRecord] | None = None
        for record_index, record in enumerate(by_symbol.get(symbol, ())):
            record_frac = np.asarray(record.frac, dtype=float)
            distance = _min_image_distance(lattice, frac, record_frac)
            if distance < 0.10 and (best is None or distance < best[0]):
                best = (distance, id(record), record)
        matched.append(best[2] if best else None)
    return matched


def _majority_symbol(site) -> str:
    species = site.species
    if len(species) == 1:
        return next(iter(species)).symbol
    return max(species.items(), key=lambda kv: kv[1])[0].symbol


def _majority_species(site):
    species = site.species
    if len(species) == 1:
        return next(iter(species))
    return max(species.items(), key=lambda kv: kv[1])[0]


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
@dataclass
class DisorderStats:
    partial_before: int = 0
    partial_after: int = 0
    removed_sites: int = 0
    removed_h: int = 0
    removed_heavy: int = 0
    groups_resolved: int = 0
    h_groups: int = 0
    heavy_groups: int = 0
    promoted_sites: int = 0
    cif_records: int = 0
    warnings: list[str] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "partial_before": self.partial_before,
            "partial_after": self.partial_after,
            "removed_sites": self.removed_sites,
            "removed_h": self.removed_h,
            "removed_heavy": self.removed_heavy,
            "groups_resolved": self.groups_resolved,
            "h_groups": self.h_groups,
            "heavy_groups": self.heavy_groups,
            "promoted_sites": self.promoted_sites,
            "cif_records": self.cif_records,
            "warnings": self.warnings,
        }


def _compatible_subset(
    structure: Structure,
    candidate_indices: list[int],
    count: int,
    lattice: np.ndarray,
    *,
    min_hh: float = 1.20,
) -> list[int]:
    """Pick ``count`` mutually compatible H positions (largest occupancy first)."""
    import itertools

    if count >= len(candidate_indices):
        return list(candidate_indices)
    if count <= 0:
        return []
    fracs = {index: np.asarray(structure[index].frac_coords, dtype=float) for index in candidate_indices}
    occupancy = {index: site_occupancy(structure[index]) for index in candidate_indices}
    best = None
    for combination in itertools.combinations(candidate_indices, count):
        min_distance = np.inf
        for a, b in itertools.combinations(combination, 2):
            min_distance = min(
                min_distance, _min_image_distance(lattice, fracs[a], fracs[b])
            )
        compatible = min_distance >= min_hh
        occupancy_sum = sum(occupancy[index] for index in combination)
        score = (
            0 if compatible else 1,
            -occupancy_sum,
            -min_distance if np.isfinite(min_distance) else 0.0,
            tuple(combination),
        )
        if best is None or score < best[0]:
            best = (score, list(combination))
    return best[1] if best else list(candidate_indices[:count])


def resolve_disorder(
    structure: Structure,
    *,
    cif_text: str | None = None,
    h_min_distance: float = 1.20,
) -> tuple[Structure, dict]:
    """Resolve partial occupancies / statistical atoms.

    Returns ``(new_structure, stats)``; ``stats["groups_resolved"]`` is the
    number of disorder groups that were resolved and is what
    ``RepairReport.resolved_disorder`` stores.
    """
    stats = DisorderStats()
    # pymatgen 2026 ``Structure.remove_sites`` / ``replace`` mutate in place.
    structure = structure.copy()
    n = len(structure)
    if n == 0:
        return structure.copy(), stats.to_dict()

    records = parse_atom_site_loop(cif_text) if cif_text else []
    stats.cif_records = len(records)
    matched_records = _match_records(structure, records) if records else [None] * n

    symbols = [site_symbol(site) for site in structure]
    occupancy = [site_occupancy(site) for site in structure]
    partial = [index for index in range(n) if occupancy[index] < 0.999]
    stats.partial_before = len(partial)
    if not partial:
        stats.partial_after = 0
        stats.actions.append(
            {
                "action": "disorder",
                "detail": "无部分占据位点，跳过无序消解",
                "removed_sites": 0,
                "groups": 0,
            }
        )
        return structure.copy(), stats.to_dict()

    lattice = np.asarray(structure.lattice.matrix, dtype=float)
    remove: set[int] = set()

    partial_heavy = [index for index in partial if symbols[index] != "H"]
    partial_h = [index for index in partial if symbols[index] == "H"]

    # ---- heavy-atom disorder: merge alternative positions ------------------
    heavy_groups = _heavy_disorder_groups(structure, partial_heavy, lattice, symbols)
    heavy_replacements: dict[int, object] = {}
    for group in heavy_groups:
        stats.heavy_groups += 1
        group_sorted = sorted(
            group,
            key=lambda index: (
                -(occupancy[index]),
                str(matched_records[index].label) if matched_records[index] else f"{index:08d}",
            ),
        )
        keep = group_sorted[0]
        for index in group:
            if index != keep:
                remove.add(index)
        species = _majority_species(structure[keep])
        heavy_replacements[keep] = species
        if len(group) > 1:
            stats.groups_resolved += 1
    for index in partial_heavy:
        if index in remove:
            continue
        if any(index in group for group in heavy_groups):
            if occupancy[index] < 0.999:
                stats.warnings.append(
                    f"重原子位点 {index} 的部分占据未找到同组替代位点，按主元素 {symbols[index]} 处理"
                )
                heavy_replacements[index] = _majority_species(structure[index])
            continue
        stats.warnings.append(
            f"重原子位点 {index}({symbols[index]}) 占有率为 {occupancy[index]:.2f}，按主元素处理"
        )
        heavy_replacements[index] = _majority_species(structure[index])

    # ---- hydrogen disorder: select one orientation per parent -------------
    kept_indices = [index for index in range(n) if index not in remove]
    kept_set = set(kept_indices)
    heavy_indices = [index for index in kept_indices if symbols[index] != "H"]
    heavy_symbols = [_majority_symbol(structure[index]) for index in heavy_indices]
    heavy_structure = Structure(
        lattice=structure.lattice,
        species=heavy_symbols,
        coords=[structure[index].frac_coords for index in heavy_indices],
        coords_are_cartesian=False,
        validate_proximity=False,
    )
    demand_by_original: dict[int, int] = {}
    if heavy_indices:
        graph = perceive_bonds(heavy_structure)
        for demand in hydrogen_demand(graph):
            demand_by_original[heavy_indices[demand.atom]] = demand.missing

    # parent assignment for all H sites (full and partial)
    def parent_of(h_index: int) -> int | None:
        frac = np.asarray(structure[h_index].frac_coords, dtype=float)
        best = None
        for heavy_index in heavy_indices:
            distance = _min_image_distance(
                lattice, frac, np.asarray(structure[heavy_index].frac_coords, dtype=float)
            )
            if distance < 1.65 and (best is None or distance < best[0]):
                best = (distance, heavy_index)
        return None if best is None else best[1]

    full_h_by_parent: Counter = Counter()
    for index in kept_indices:
        if symbols[index] == "H" and occupancy[index] >= 0.999:
            parent = parent_of(index)
            if parent is not None:
                full_h_by_parent[parent] += 1

    partial_h_by_parent: dict[int, list[int]] = defaultdict(list)
    unassigned_h: list[int] = []
    selected_h_partial: set[int] = set()
    for index in partial_h:
        if index in remove:
            continue
        parent = parent_of(index)
        if parent is None or is_metal(symbols[parent]):
            if parent is not None and is_metal(symbols[parent]):
                stats.warnings.append(
                    f"部分占据 H 位点 {index} 配位于金属 {parent}，疑似金属氢化物，保留并跳过补氢推断"
                )
                continue
            unassigned_h.append(index)
            continue
        partial_h_by_parent[parent].append(index)

    if unassigned_h:
        stats.warnings.append(
            f"{len(unassigned_h)} 个部分占据 H 位点未找到 1.65 Å 内的母原子，保留原样"
        )

    for parent, candidates in sorted(partial_h_by_parent.items()):
        stats.h_groups += 1
        expected = demand_by_original.get(parent, 0) - full_h_by_parent.get(parent, 0)
        if expected <= 0:
            remove.update(candidates)
            stats.groups_resolved += 1
            continue
        selected = _select_group_candidates(
            structure, candidates, expected, lattice, matched_records, h_min_distance
        )
        selected_h_partial.update(selected)
        for index in candidates:
            if index not in selected:
                remove.add(index)
        if len(candidates) > 1:
            stats.groups_resolved += 1

    # ---- apply -----------------------------------------------------------
    if remove:
        new_structure = structure.copy()
        new_structure.remove_sites(sorted(remove))
        stats.removed_sites = len(remove)
        stats.removed_h = sum(1 for index in remove if symbols[index] == "H")
        stats.removed_heavy = len(remove) - stats.removed_h
    else:
        new_structure = structure.copy()

    kept_order = [index for index in range(n) if index not in remove]
    position = {original: new_index for new_index, original in enumerate(kept_order)}

    if heavy_replacements:
        # map original indices to the indices in the new structure
        for original, species in heavy_replacements.items():
            if original not in position:
                continue
            new_structure.replace(position[original], species)

    # The selected half-occupancy H sites become fully occupied: they now
    # represent the chosen orientation of the disorder model.
    promoted_originals = {
        original for original in selected_h_partial if original not in remove
    }
    remaining_partial = [
        index for index, site in enumerate(new_structure) if site_occupancy(site) < 0.999
    ]
    unresolved: list[int] = []
    for index in remaining_partial:
        site = new_structure[index]
        original = kept_order[index] if index < len(kept_order) else index
        new_structure.replace(index, _majority_species(site))
        if original not in promoted_originals:
            unresolved.append(original)
    stats.partial_after = 0
    stats.promoted_sites = len(promoted_originals)
    if unresolved:
        preview = ", ".join(str(index) for index in unresolved[:6])
        stats.warnings.append(
            f"{len(unresolved)} 个部分占据位点未参与无序消解，已按主元素升为全占据"
            f"（位点 {preview}{'…' if len(unresolved) > 6 else ''}）"
        )
    ensure_unique_labels(new_structure)

    stats.actions.append(
        {
            "action": "disorder",
            "detail": (
                f"无序/占位：{stats.partial_before} 个部分占据位点 → "
                f"删除 {stats.removed_sites} 个替代位点"
                f"（H {stats.removed_h} 个、重原子 {stats.removed_heavy} 个）；"
                f"消解 {stats.groups_resolved} 个无序组（H 组 {stats.h_groups}、重原子组 {stats.heavy_groups}）；"
                f"{stats.promoted_sites} 个选定半占据位点升为全占据；"
                f"剩余部分占据 {stats.partial_after} 个"
            ),
            "removed_sites": stats.removed_sites,
            "removed_h": stats.removed_h,
            "removed_heavy": stats.removed_heavy,
            "groups_resolved": stats.groups_resolved,
            "h_groups": stats.h_groups,
            "heavy_groups": stats.heavy_groups,
            "promoted_sites": stats.promoted_sites,
            "partial_before": stats.partial_before,
            "partial_after": stats.partial_after,
        }
    )
    return new_structure, stats.to_dict()


def _heavy_disorder_groups(
    structure: Structure,
    partial_heavy: list[int],
    lattice: np.ndarray,
    symbols: list[str],
) -> list[list[int]]:
    """Group alternative heavy-atom positions (different species nearby)."""
    groups: list[list[int]] = []
    seen: set[int] = set()
    for index in partial_heavy:
        if index in seen:
            continue
        group = [index]
        seen.add(index)
        frac = np.asarray(structure[index].frac_coords, dtype=float)
        for other in partial_heavy:
            if other in seen:
                continue
            other_frac = np.asarray(structure[other].frac_coords, dtype=float)
            if _min_image_distance(lattice, frac, other_frac) < 0.70:
                group.append(other)
                seen.add(other)
        groups.append(group)
    return groups


def _select_group_candidates(
    structure: Structure,
    candidates: list[int],
    expected: int,
    lattice: np.ndarray,
    matched_records: list[AtomSiteRecord | None],
    h_min_distance: float,
) -> list[int]:
    """Select the hydrogen positions to keep for one parent atom.

    ``_atom_site_disorder_group`` is honoured when it is present: pick the
    group with the largest total occupancy (ties -> label).  Otherwise use the
    geometric compatibility criterion (mutually > ``h_min_distance`` apart).
    """
    groups: dict[str | None, list[int]] = defaultdict(list)
    for index in candidates:
        record = matched_records[index] if index < len(matched_records) else None
        groups[record.disorder_group if record is not None else None].append(index)
    if len(groups) > 1 and None not in groups:
        ranked = []
        for group_name, indices in groups.items():
            occupancy_sum = sum(site_occupancy(structure[index]) for index in indices)
            labels = tuple(
                str(matched_records[index].label) if matched_records[index] else str(index)
                for index in indices
            )
            ranked.append((-occupancy_sum, labels, indices))
        ranked.sort()
        chosen: list[int] = []
        for _score, _labels, indices in ranked:
            if len(chosen) + len(indices) <= expected:
                chosen.extend(indices)
            if len(chosen) == expected:
                break
        if chosen:
            return chosen
    return _compatible_subset(
        structure, candidates, expected, lattice, min_hh=h_min_distance
    )
