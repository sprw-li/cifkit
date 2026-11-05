"""Close contacts / duplicate atoms for the repair layer.

The default criterion is the one frozen in ``docs/DESIGN.md`` and task-2:
``d < 0.85 * (r_cov_i + r_cov_j)`` (``r`` from the covalent-radius table used
by :mod:`cifkit.repair.bonds`).  For hydrogen the overlap thresholds are
separate and configurable because H...H distances of a normal methyl group
(1.78 A) are much larger than the covalent-radius sum:

* H...H   < ``h_h_min``      (default 1.0 A) - one of the two H is removed
* H...X   < ``h_heavy_min``  (default 0.9 A) - the H is removed

Removal keeps the atom that appears first (lowest site index); for H/metal
pairs the H is removed.  Atoms closer than a full bond are *not* removed
silently when the pair is a legitimate chemical bond, so the radius-based
factor is kept well below 1.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pymatgen.core import Structure

from cifkit.repair.bonds import covalent_radius, is_metal, site_symbol


@dataclass
class CloseContact:
    """A pair of atoms that overlap under the chosen criterion."""

    i: int
    j: int
    distance: float
    image: tuple[int, int, int]
    kind: str  # "duplicate" | "h-h" | "h-heavy" | "self-image"
    kept: int | None = None
    removed: int | None = None

    def to_dict(self) -> dict:
        return {
            "i": self.i,
            "j": self.j,
            "distance": round(self.distance, 4),
            "image": list(self.image),
            "kind": self.kind,
            "kept": self.kept,
            "removed": self.removed,
        }


def _search_radius(symbols: list[str], factor: float, h_h_min: float, h_heavy_min: float) -> float:
    if not symbols:
        return 1.0
    radius = max(covalent_radius(symbol) for symbol in symbols)
    return float(max(factor * 2.0 * radius, h_h_min, h_heavy_min, 0.6) + 0.05)


def find_close_contacts(
    structure: Structure,
    *,
    factor: float = 0.85,
    h_h_min: float = 1.0,
    h_heavy_min: float = 0.9,
) -> list[CloseContact]:
    """Return all overlapping atom pairs (including periodic images)."""
    symbols = [site_symbol(site) for site in structure]
    n = len(symbols)
    if n < 2:
        return []
    search = _search_radius(symbols, factor, h_h_min, h_heavy_min)
    center, point, offsets, distances = structure.get_neighbor_list(search)
    # Nearest heavy-atom distance of every H (its own X–H bond).  X-ray
    # structures routinely refine N–H/C–H bonds to 0.85–0.96 A, which is
    # *shorter than the overlap threshold*: those pairs are bonds, not clashes,
    # so they must not be deleted.
    nearest_heavy: dict[int, float] = {}
    for ci, pi, dist in zip(center, point, distances):
        a, b = int(ci), int(pi)
        if a == b:
            continue
        if symbols[a] == "H" and symbols[b] != "H":
            nearest_heavy[a] = min(nearest_heavy.get(a, np.inf), float(dist))
        elif symbols[b] == "H" and symbols[a] != "H":
            nearest_heavy[b] = min(nearest_heavy.get(b, np.inf), float(dist))
    contacts: list[CloseContact] = []
    seen: set[tuple] = set()
    for ci, pi, off, dist in zip(center, point, offsets, distances):
        a, b = int(ci), int(pi)
        image = tuple(int(x) for x in off)
        if a == b:
            if image == (0, 0, 0):
                continue
            if float(dist) < factor * 2.0 * covalent_radius(symbols[a]):
                tag = ("self", a, image)
                if tag in seen:
                    continue
                seen.add(tag)
                contacts.append(CloseContact(a, a, float(dist), image, "self-image"))
            continue
        if a > b:
            continue  # each pair once (the neighbor list has both directions)
        tag = ("pair", a, b, image)
        if tag in seen:  # pragma: no cover - a>b filter already dedupes
            continue
        seen.add(tag)
        symbol_a, symbol_b = symbols[a], symbols[b]
        metal_a, metal_b = is_metal(symbol_a), is_metal(symbol_b)
        if symbol_a == "H" and symbol_b == "H":
            if float(dist) < h_h_min:
                contacts.append(CloseContact(a, b, float(dist), image, "h-h"))
            continue
        if symbol_a == "H" or symbol_b == "H":
            h_index, other_index = (a, b) if symbol_a == "H" else (b, a)
            distance = float(dist)
            if abs(distance - nearest_heavy.get(h_index, np.inf)) < 0.02:
                continue  # this is the H's own X–H bond (possibly X-ray short)
            if distance < h_heavy_min:
                contacts.append(
                    CloseContact(h_index, other_index, distance, image, "h-heavy")
                )
            continue
        threshold = factor * (covalent_radius(symbol_a) + covalent_radius(symbol_b))
        if float(dist) < threshold:
            contacts.append(CloseContact(a, b, float(dist), image, "duplicate"))
    contacts.sort(key=lambda c: (c.i, c.j, c.image, c.distance))
    return contacts


def remove_close_contacts(
    structure: Structure,
    *,
    factor: float = 0.85,
    h_h_min: float = 1.0,
    h_heavy_min: float = 0.9,
) -> tuple[Structure, int, dict]:
    """Remove overlapping atoms.

    Returns ``(new_structure, removed_count, details)``.  Details contain the
    list of detected contacts (with kept/removed indices) plus warnings for
    contacts that cannot be fixed by deletion (e.g. an atom overlapping its
    own periodic image, which indicates a broken cell).
    """
    contacts = find_close_contacts(
        structure, factor=factor, h_h_min=h_h_min, h_heavy_min=h_heavy_min
    )
    warnings: list[str] = []
    removed: set[int] = set()
    occupancy = [float(sum(site.species.values())) for site in structure]
    for contact in contacts:
        if contact.kind == "self-image":
            warnings.append(
                f"原子 {contact.i} 与其周期像距离仅 {contact.distance:.2f} Å："
                "晶胞/周期性异常，无法通过删除原子修复"
            )
            continue
        if contact.i in removed or contact.j in removed:
            continue
        if contact.kind == "h-heavy":
            h_index = contact.i
            contact.kept, contact.removed = contact.j, h_index
            removed.add(h_index)
            continue
        if contact.kind in {"h-h", "duplicate"}:
            keep, drop = contact.i, contact.j
            if occupancy[drop] > occupancy[keep]:
                keep, drop = drop, keep
            contact.kept, contact.removed = keep, drop
            removed.add(drop)
            continue

    new_structure = structure
    if removed:
        # pymatgen 2026 ``remove_sites`` mutates in place: work on a copy.
        new_structure = structure.copy()
        new_structure.remove_sites(sorted(removed))
    details = {
        "removed": len(removed),
        "contacts": [contact.to_dict() for contact in contacts],
        "warnings": warnings,
    }
    return new_structure, len(removed), details
