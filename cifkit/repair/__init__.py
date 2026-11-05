"""修复层：补氢 / 无序占位 / 过近原子 / 价态检查。

Owner: repair teammate. Public API (do not change without Lead):

    repair_all(structure, *, add_hydrogen=False, resolve_disorder=True,
               remove_close_contacts=True) -> tuple[Structure, RepairReport]
"""
from __future__ import annotations

from cifkit.types import RepairReport


def repair_all(
    structure,
    *,
    add_hydrogen: bool = False,
    resolve_disorder: bool = True,
    remove_close_contacts: bool = True,
) -> tuple[object, RepairReport]:
    raise NotImplementedError("repair.repair_all not implemented yet")
