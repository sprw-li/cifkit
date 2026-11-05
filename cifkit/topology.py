"""拓扑判定：数据库元数据标签 + 结构比对（underlying net 签名）。

Owner: sources teammate. Public API:

    verify(structure, expected: str) -> dict
        -> {"ok": bool, "evidence": "metadata"|"verified"|"curated"|"mismatch",
            "detail": str, "signature": {...}, "reference": {...}}

    describe(structure) -> dict
    underlying_net(structure) -> dict     # 节点/边/平移，供签名与调试
"""
from __future__ import annotations


def verify(structure, expected: str) -> dict:
    raise NotImplementedError("topology.verify not implemented yet")


def describe(structure) -> dict:
    raise NotImplementedError("topology.describe not implemented yet")


def underlying_net(structure) -> dict:
    raise NotImplementedError("topology.underlying_net not implemented yet")
