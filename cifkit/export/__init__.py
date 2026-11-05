"""导出层：计算化学软件格式写出。

Owner: geom teammate. Public API:

    write_structure(structure, path, fmt, *, title=None) -> str
    supported_formats() -> dict[str, str]
"""
from __future__ import annotations


def write_structure(structure, path, fmt: str, *, title: str | None = None) -> str:
    raise NotImplementedError("export.write_structure not implemented yet")


def supported_formats() -> dict[str, str]:
    raise NotImplementedError("export.supported_formats not implemented yet")
