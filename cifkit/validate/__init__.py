"""结构校验：组成、近邻距离、配位/悬空键、真空层、电荷等。

Owner: geom teammate. Public API:

    validate_structure(structure, *, spec=None, extra=None) -> ValidationReport
"""
from __future__ import annotations

from cifkit.types import ValidationReport


def validate_structure(structure, *, spec=None, extra: dict | None = None) -> ValidationReport:
    raise NotImplementedError("validate.validate_structure not implemented yet")
