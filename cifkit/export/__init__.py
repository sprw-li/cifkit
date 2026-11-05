"""导出层：计算化学软件格式写出。

Owner: geom teammate. Public API (DESIGN.md §6):

    write_structure(structure, path, fmt, *, title=None) -> str
    supported_formats() -> dict[str, str]
"""
from __future__ import annotations

from cifkit.export.writers import FORMAT_INFO, normalize_format, supported_formats, write_structure

__all__ = ["write_structure", "supported_formats", "normalize_format", "FORMAT_INFO"]
