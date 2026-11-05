"""预览图：把周期结构/表面画成 PNG（matplotlib 3D，不依赖 GPU）。

Owner: geom teammate. Public API:

    render_structure(structure, path, *, view="auto", title=None, repeat=(1,1,1)) -> str
"""
from __future__ import annotations


def render_structure(structure, path, *, view: str = "auto", title: str | None = None, repeat=(1, 1, 1)) -> str:
    raise NotImplementedError("render.render_structure not implemented yet")
