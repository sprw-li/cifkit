"""导出层：计算化学格式写出 + 计算软件输入包（cif → anything）。

Public API (DESIGN.md §6):

    write_structure(structure, path, fmt, *, title=None) -> str
    supported_formats() -> dict[str, str]
    write_bundle(structure, code, outdir, *, title=None) -> dict
    supported_bundles() -> dict[str, str]
"""
from __future__ import annotations

from cifkit.export.bundles import BUNDLE_INFO, supported_bundles, write_bundle
from cifkit.export.writers import FORMAT_INFO, normalize_format, supported_formats, write_structure

__all__ = [
    "write_structure",
    "supported_formats",
    "normalize_format",
    "FORMAT_INFO",
    "write_bundle",
    "supported_bundles",
    "BUNDLE_INFO",
]
