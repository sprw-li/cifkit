"""Small shared helpers for the repair layer."""
from __future__ import annotations

from pymatgen.core import Structure


def ensure_unique_labels(structure: Structure) -> Structure:
    """Make every CIF site label unique (in place), preserving explicit labels.

    pymatgen 2026 tracks CIF site labels (``site.label``); freshly appended or
    replaced sites fall back to the bare element symbol.  ``CifWriter`` treats
    such bare labels as "no label" and auto-generates ``<Element><count>``,
    which can collide with other labels and trigger the CIF duplicate-label
    warning.  This helper assigns explicit, unique ``<Element><n>`` labels to
    those sites and renames duplicated explicit labels.
    """
    taken: set[str] = set()
    for site in structure:
        taken.add(site.label)

    used: set[str] = set()
    counters: dict[str, int] = {}
    for site in structure:
        label = site.label
        if label != site.species_string and label not in used:
            used.add(label)
            continue
        base = site.species_string
        number = counters.get(base, 0)
        candidate = f"{base}{number}"
        while candidate in taken or candidate in used:
            number += 1
            candidate = f"{base}{number}"
        counters[base] = number + 1
        site.label = candidate
        used.add(candidate)
        taken.add(candidate)
    return structure
