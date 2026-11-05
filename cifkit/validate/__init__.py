"""结构校验：组成、近邻距离、配位/悬空键、真空层、电荷等。

Owner: geom teammate. Public API (DESIGN.md §6):

    validate_structure(structure, *, spec=None, extra=None) -> ValidationReport
"""
from __future__ import annotations

from cifkit.validate.checks import CHECK_NAMES, validate_structure

__all__ = ["validate_structure", "CHECK_NAMES"]
