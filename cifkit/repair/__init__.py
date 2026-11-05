"""修复层：补氢 / 无序占位 / 过近原子 / 价态检查。

Owner: repair teammate. Public API (frozen in ``docs/DESIGN.md`` §6):

    repair_all(structure, *, add_hydrogen=False, resolve_disorder=True,
               remove_close_contacts=True) -> tuple[Structure, RepairReport]

The individual steps are also usable on their own:

    from cifkit.repair import add_hydrogens, resolve_disorder_sites, \
        find_close_contacts, remove_close_contacts_atoms, check_structure
"""
from __future__ import annotations

from cifkit.types import RepairReport

from cifkit.repair.bonds import (
    METAL_COORDINATING_ELEMENTS,
    BondGraph,
    HydrogenDemand,
    classify_cluster_oxygen,
    hydrogen_demand,
    is_carboxylate_oxygen,
    perceive_bonds,
)
from cifkit.repair.contacts import (
    CloseContact,
    find_close_contacts,
    remove_close_contacts as remove_close_contacts_atoms,
)
from cifkit.repair.disorder import (
    AtomSiteRecord,
    parse_atom_site_loop,
    read_cif_atom_sites,
    resolve_disorder as resolve_disorder_sites,
)
from cifkit.repair.hydrogen import add_hydrogens
from cifkit.repair.valence import check_structure
from cifkit.repair._labels import ensure_unique_labels

__all__ = [
    "repair_all",
    "add_hydrogens",
    "resolve_disorder_sites",
    "find_close_contacts",
    "remove_close_contacts_atoms",
    "check_structure",
    "perceive_bonds",
    "hydrogen_demand",
    "classify_cluster_oxygen",
    "is_carboxylate_oxygen",
    "METAL_COORDINATING_ELEMENTS",
    "parse_atom_site_loop",
    "read_cif_atom_sites",
    "BondGraph",
    "HydrogenDemand",
    "AtomSiteRecord",
    "CloseContact",
]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def repair_all(
    structure,
    *,
    add_hydrogen: bool = False,
    resolve_disorder: bool = True,
    remove_close_contacts: bool = True,
    cif_text: str | None = None,
) -> tuple[object, RepairReport]:
    """Run the repair pipeline: disorder -> contacts -> hydrogen -> valence.

    Parameters
    ----------
    structure:
        Input pymatgen ``Structure``.  It is never modified.
    add_hydrogen:
        Complete missing hydrogens (the core of "碳上补氢").
    resolve_disorder:
        Resolve partial occupancies / statistical atoms (ZIF-8 methyl H).
    remove_close_contacts:
        Delete duplicate / overlapping atoms.
    cif_text:
        Optional raw CIF text.  When given, ``_atom_site_occupancy`` and
        ``_atom_site_disorder_group`` are read directly for the disorder
        resolution (extra robustness for CIFs where pymatgen already lost
        part of that information).

    Returns
    -------
    (structure, report)
        ``report.actions`` is a list of structured dicts (``action`` /
        ``detail`` / per-step numbers) that can be quoted directly in a
        report; ``report.warnings`` lists every valence/geometry problem the
        repair layer found *after* repairing.
    """
    report = RepairReport()
    # Defensive copy: pymatgen 2026 mutates in place for remove_sites/replace,
    # and the caller's Structure must never be modified.
    current = structure.copy()

    # 1) disorder / partial occupancies
    if resolve_disorder:
        current, disorder_stats = resolve_disorder_sites(current, cif_text=cif_text)
        report.resolved_disorder = int(disorder_stats.get("groups_resolved", 0))
        report.actions.extend(disorder_stats.get("actions", []))
        report.warnings.extend(disorder_stats.get("warnings", []))
    else:
        report.actions.append(
            {
                "action": "disorder",
                "detail": "跳过无序/占位消解（resolve_disorder=False）",
                "removed_sites": 0,
                "groups": 0,
            }
        )

    # 2) close contacts / duplicate atoms
    if remove_close_contacts:
        current, removed, contact_details = remove_close_contacts_atoms(current)
        report.removed_atoms += removed
        report.actions.append(
            {
                "action": "contacts",
                "detail": (
                    f"过近原子检查（阈值 0.85*(r_i+r_j)、H···H < 1.0 Å、H···重原子 < 0.9 Å）："
                    f"删除 {removed} 个重叠/重复原子"
                ),
                "removed_atoms": removed,
                "contacts": contact_details["contacts"],
            }
        )
        report.warnings.extend(contact_details.get("warnings", []))
    else:
        report.actions.append(
            {
                "action": "contacts",
                "detail": "跳过过近原子检查（remove_close_contacts=False）",
                "removed_atoms": 0,
            }
        )

    # 3) missing hydrogens (core)
    if add_hydrogen:
        current, hydrogen_stats = add_hydrogens(current)
        report.added_h += int(hydrogen_stats["added_h"])
        report.actions.append(
            {
                "action": "hydrogen",
                "detail": hydrogen_stats["detail"],
                "route": hydrogen_stats["route"],
                "added_h": int(hydrogen_stats["added_h"]),
                "h_types": hydrogen_stats.get("h_types", {}),
                "per_ligand_h": hydrogen_stats.get("per_ligand_h", {}),
                "rdkit": hydrogen_stats.get("rdkit", {}),
                "geometric_placements": hydrogen_stats.get("geometric", 0),
                "min_hh": hydrogen_stats.get("min_hh"),
                "min_h_heavy": hydrogen_stats.get("min_h_heavy"),
                "min_h_metal": hydrogen_stats.get("min_h_metal"),
                "c_valence_ok": hydrogen_stats.get("c_valence_ok"),
            }
        )
        report.warnings.extend(hydrogen_stats.get("warnings", []))
    else:
        report.actions.append(
            {
                "action": "hydrogen",
                "detail": "跳过补氢（add_hydrogen=False）",
                "added_h": 0,
            }
        )

    # 4) post-repair valence / coordination validation
    valence = check_structure(current)
    report.actions.append(
        {
            "action": "valence",
            "detail": valence["detail"],
            "ok": valence["ok"],
            "metrics": valence["metrics"],
        }
    )
    report.warnings.extend(valence.get("warnings", []))
    report.warnings = _dedupe(report.warnings)
    ensure_unique_labels(current)  # CIF writer needs unique _atom_site_label
    return current, report
