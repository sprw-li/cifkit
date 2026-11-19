"""预览图：把周期结构/表面画成 PNG（matplotlib 3D，不依赖 GPU）。

Owner: geom teammate. Public API (DESIGN.md §6):

    render_structure(structure, path, *, view="auto", title=None, repeat=(1,1,1)) -> str

* ``view="auto"`` renders a slab from the side (looking along an in-plane
  direction, so the vacuum is visible) and everything else as a 3D perspective.
* Elements have a fixed colour map (:data:`ELEMENT_COLORS`), atom sizes follow
  covalent radii, the cell box is drawn.
* The rendering backend is forced to ``Agg``; output is a 1200x900 PNG.
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import numpy as np
from pymatgen.core import Structure

from cifkit.geom._common import (
    along_normal,
    axis_geometry,
    gaps_all_axes,
    site_symbols,
    vacuum_metrics,
)

#: fixed element colours (Jmol-like), fallback colours are assigned from tab10
ELEMENT_COLORS: dict[str, str] = {
    "H": "#FFFFFF",
    "He": "#D9FFFF",
    "Li": "#CC80FF",
    "B": "#FFB5B5",
    "C": "#2B2B2B",
    "N": "#3050F8",
    "O": "#FF0D0D",
    "F": "#90E050",
    "Na": "#AB5CF2",
    "Mg": "#8AFF00",
    "Al": "#BFA6A6",
    "Si": "#F0C8A0",
    "P": "#FF8000",
    "S": "#FFFF30",
    "Cl": "#1FF01F",
    "K": "#8F40D4",
    "Ca": "#3DFF00",
    "Ti": "#BFC2C7",
    "V": "#A6A6AB",
    "Cr": "#8A99C7",
    "Mn": "#9C7AC7",
    "Fe": "#E06633",
    "Co": "#F090A0",
    "Ni": "#50D050",
    "Cu": "#C88033",
    "Zn": "#7D80B0",
    "Ga": "#C28F8F",
    "Ge": "#668F8F",
    "Br": "#A62929",
    "Zr": "#94E0E0",
    "Mo": "#54B5B5",
    "Ru": "#248F8F",
    "Rh": "#0A7D8C",
    "Pd": "#006985",
    "Ag": "#C0C0C0",
    "Cd": "#FFD98F",
    "In": "#A67573",
    "Sn": "#668080",
    "I": "#940094",
    "Ba": "#00C900",
    "La": "#70D4FF",
    "Ce": "#FFFFC7",
    "Hf": "#4DC2FF",
    "W": "#2194D2",
    "Pt": "#D0D0E0",
    "Au": "#FFD123",
    "Pb": "#575961",
    "Bi": "#9E4FB5",
}

#: output size (pixels) and dpi
FIGSIZE = (12.0, 9.0)
DPI = 100
#: above this many atoms the preview is rendered with smaller markers
_BUSY_ATOMS = 4000

#: CJK-capable fonts tried first so Chinese titles (pipeline passes the raw query
#: as title) are not rendered as "tofu" boxes with matplotlib's default DejaVu Sans
_FONT_CANDIDATES = (
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "WenQuanYi Zen Hei",
    "DejaVu Sans",
)


def _configure_fonts() -> bool:
    """Install a CJK-capable font when one is available.

    Returns ``True`` when a CJK font was found (Chinese titles can then be drawn
    as-is), ``False`` when only latin fonts exist (titles with non-ASCII
    characters are then replaced by an ASCII fallback so the PNG does not end up
    full of "tofu" boxes).
    """
    try:
        from matplotlib import font_manager, rcParams

        available = {f.name for f in font_manager.fontManager.ttflist}
        cjk = [name for name in _FONT_CANDIDATES if name != "DejaVu Sans" and name in available]
        chosen = cjk or [name for name in _FONT_CANDIDATES if name in available] or ["DejaVu Sans"]
        existing = list(rcParams.get("font.sans-serif", []))
        rcParams["font.sans-serif"] = chosen + [name for name in existing if name not in chosen]
        rcParams["axes.unicode_minus"] = False
        return bool(cjk)
    except Exception:  # noqa: BLE001 - rendering must never fail because of fonts
        return False


def _is_ascii(text: str) -> bool:
    return all(ord(ch) < 128 for ch in text)


def _safe_title(title: str | None, structure: Structure, has_cjk: bool) -> str | None:
    """Return a drawable title: keep it when safe, otherwise fall back to ASCII."""
    if title is None:
        return None
    text = " ".join(str(title).split())
    if not text:
        return None
    if _is_ascii(text) or has_cjk:
        return text
    try:
        formula = structure.composition.reduced_formula
    except Exception:  # noqa: BLE001
        formula = "structure"
    return f"structure overview - {formula} - {len(structure)} atoms"


def _covalent_radius(symbol: str) -> float:
    try:
        from ase.data import atomic_numbers, covalent_radii

        r = float(covalent_radii[atomic_numbers[symbol]])
        return r if r > 0 else 0.8
    except Exception:  # noqa: BLE001
        return 0.8


def _color_map(elements: list[str]) -> dict[str, Any]:
    try:
        import matplotlib

        cmap = matplotlib.colormaps["tab10"]
    except Exception:  # noqa: BLE001 # pragma: no cover
        cmap = None
    colours: dict[str, Any] = {}
    unknown = 0
    for el in sorted(elements):
        if el in ELEMENT_COLORS:
            colours[el] = ELEMENT_COLORS[el]
        else:
            if cmap is not None:
                colours[el] = cmap(unknown % 10)
            else:  # pragma: no cover
                colours[el] = "#808080"
            unknown += 1
    return colours


def _marker_sizes(symbols: list[str]) -> np.ndarray:
    base = np.array([_covalent_radius(s) for s in symbols], dtype=float)
    scale = 0.55 if len(symbols) > _BUSY_ATOMS else 1.0
    return np.clip((base * 26.0) ** 2, 12.0, 1200.0) * scale


def _cell_edges(lattice) -> np.ndarray:
    """12 cell edges as ``(12, 2, 3)`` cartesian segments."""
    matrix = np.asarray(lattice.matrix, dtype=float)
    corners = np.array([[i, j, k] for i in (0, 1) for j in (0, 1) for k in (0, 1)], dtype=float) @ matrix
    edges = []
    for i in range(8):
        for j in range(i + 1, 8):
            if bin(i ^ j).count("1") == 1:
                edges.append([corners[i], corners[j]])
    return np.asarray(edges, dtype=float)


def _is_slab_like(structure: Structure) -> bool:
    try:
        return float(gaps_all_axes(structure)[2]) > 6.0 and not all(g > 6.0 for g in gaps_all_axes(structure))
    except Exception:  # noqa: BLE001
        return False


def _display_structure(structure: Structure, repeat) -> Structure:
    try:
        reps = tuple(int(r) for r in repeat)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"render_structure: repeat must be three integers, got {repeat!r}") from exc
    if len(reps) != 3:
        raise ValueError(f"render_structure: repeat must have three entries, got {repeat!r}")
    if any(r < 1 for r in reps):
        raise ValueError(f"render_structure: repeat entries must be >= 1, got {reps}")
    if reps == (1, 1, 1):
        return structure
    slab = _is_slab_like(structure)
    if slab and reps[2] != 1:
        reps = (reps[0], reps[1], 1)  # never repeat a slab across the vacuum
    if len(structure) * reps[0] * reps[1] * reps[2] > 20000:
        raise ValueError("render_structure: refusing to render more than 20000 atoms")
    return structure * reps


def _legend(ax, colours: dict[str, Any], counts: dict[str, int]) -> None:
    from matplotlib.lines import Line2D

    handles = [
        Line2D(
            [],
            [],
            linestyle="",
            marker="o",
            markersize=7,
            markerfacecolor=colours[el],
            markeredgecolor="black" if el in ("H", "C") else colours[el],
            markeredgewidth=0.4,
            label=f"{el} ({counts[el]})",
        )
        for el in sorted(colours)
        if counts.get(el, 0) > 0
    ]
    if handles:
        ax.legend(
            handles=handles,
            loc="upper right",
            fontsize=9,
            frameon=True,
            framealpha=0.85,
            ncol=1 if len(handles) <= 8 else 2,
        )


def _pyplot():
    """Import pyplot with the non-interactive ``Agg`` backend forced.

    This module only ever writes PNG files, but matplotlib's *automatic* backend
    selection can pick a GUI backend (TkAgg and friends) and then fail where Tcl/Tk
    is unusable: CI's windows/py3.13 runner died with
    ``_tkinter.TclError: Can't find a usable init.tcl`` while writing ``preview.png``
    (round 58).  ``force=True`` also overrides an inherited ``MPLBACKEND``, which a
    caller may well have set for their own plotting — that choice must not decide
    whether `cifkit export --to png` works.
    """
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    return plt


def _render_3d(structure: Structure, path: Path, title: str | None, colours, counts) -> None:
    plt = _pyplot()
    from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

    cart = np.asarray(structure.cart_coords, dtype=float)
    symbols = site_symbols(structure)
    fig = plt.figure(figsize=FIGSIZE, dpi=DPI)
    ax = fig.add_subplot(111, projection="3d")
    for el in sorted(colours):
        mask = np.array([s == el for s in symbols], dtype=bool)
        if not mask.any():
            continue
        ax.scatter(
            cart[mask, 0],
            cart[mask, 1],
            cart[mask, 2],
            s=_marker_sizes(symbols)[mask],
            c=colours[el],
            edgecolors="black" if el in ("H", "C") else colours[el],
            linewidths=0.25,
            alpha=0.95,
            depthshade=True,
        )
    if not _is_cluster(structure):
        for a, b in _cell_edges(structure.lattice):
            ax.plot([a[0], b[0]], [a[1], b[1]], [a[2], b[2]], color="#555555", lw=0.8, alpha=0.55)
    centre = (cart.max(axis=0) + cart.min(axis=0)) / 2.0
    radius = max(float((cart.max(axis=0) - cart.min(axis=0)).max()), 1.0) * 0.62
    ax.set_xlim(centre[0] - radius, centre[0] + radius)
    ax.set_ylim(centre[1] - radius, centre[1] + radius)
    ax.set_zlim(centre[2] - radius, centre[2] + radius)
    ax.set_box_aspect((1, 1, 1))
    ax.set_axis_off()
    ax.view_init(elev=18, azim=28)
    formula = structure.composition.formula
    ax.set_title(title or f"{formula} — {len(structure)} atoms", fontsize=13)
    _legend(ax, colours, counts)
    fig.tight_layout()
    fig.savefig(str(path), dpi=DPI, facecolor="white")
    plt.close(fig)


def _render_2d(structure: Structure, path: Path, title: str | None, colours, counts, *, mode: str) -> None:
    plt = _pyplot()
    from matplotlib.patches import Polygon

    cart = np.asarray(structure.cart_coords, dtype=float)
    symbols = site_symbols(structure)
    normal, _d_perp, _height = along_normal(structure, axis=2)
    a_vec = np.asarray(structure.lattice.matrix[0], dtype=float)
    u = a_vec - np.dot(a_vec, normal) * normal
    norm_u = float(np.linalg.norm(u))
    u = u / norm_u if norm_u > 1e-9 else np.array([1.0, 0.0, 0.0])
    if mode == "top":
        v = np.cross(normal, u)
        x = cart @ u
        y = cart @ v
        subtitle = "top view (looking down the surface normal)"
    else:
        x = cart @ u
        y = cart @ normal
        subtitle = "side view (surface normal vertical)"

    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=DPI)
    sizes = _marker_sizes(symbols)
    for el in sorted(colours):
        mask = np.array([s == el for s in symbols], dtype=bool)
        if not mask.any():
            continue
        ax.scatter(
            x[mask],
            y[mask],
            s=sizes[mask],
            c=colours[el],
            edgecolors="black" if el in ("H", "C") else colours[el],
            linewidths=0.25,
            alpha=0.95,
            zorder=3,
        )

    # projected cell box
    matrix = np.asarray(structure.lattice.matrix, dtype=float)
    corners_frac = np.array([[i, j, k] for i in (0, 1) for j in (0, 1) for k in (0, 1)], dtype=float)
    corners = corners_frac @ matrix
    cx = corners @ u
    cy = corners @ (normal if mode != "top" else np.cross(normal, u))
    edges = []
    for i in range(8):
        for j in range(i + 1, 8):
            if bin(i ^ j).count("1") == 1:
                edges.append(((cx[i], cy[i]), (cx[j], cy[j])))
    for (x0, y0), (x1, y1) in edges:
        ax.plot([x0, x1], [y0, y1], color="#888888", lw=0.9, alpha=0.7, zorder=1)

    # shade the vacuum region (side view only)
    x0, x1 = float(cx.min()), float(cx.max())
    y0, y1 = float(cy.min()), float(cy.max())
    if mode != "top":
        try:
            height = along_normal(structure, axis=2)[2]
            d_perp = float(axis_geometry(structure.lattice, axis=2)[1])
            lo = float(height.min())
            hi = float(height.max())
            # light blue blocks = empty (vacuum) space between periodic images
            ax.fill_between([x0, x1], 0.0, lo, color="#dbe9f6", alpha=0.6, zorder=0)
            ax.fill_between([x0, x1], hi, d_perp, color="#dbe9f6", alpha=0.6, zorder=0)
            try:
                metrics = vacuum_metrics(structure, axis=2)
                gap = float(metrics["vacuum_perp"])
                min_image = float(metrics["min_image_distance"])
            except Exception:  # noqa: BLE001
                gap = max(d_perp - (hi - lo), 0.0)
                min_image = gap
            ax.text(
                0.012,
                0.02,
                f"slab thickness ≈ {hi - lo:.2f} Å\n"
                f"vacuum (perpendicular) ≈ {gap:.2f} Å\n"
                f"min periodic-image distance ≈ {min_image:.2f} Å\n"
                f"c = {d_perp:.2f} Å",
                transform=ax.transAxes,
                fontsize=10,
                va="bottom",
                bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "#999999"},
            )
            y1 = max(y1, d_perp)
            y0 = min(y0, 0.0)
        except Exception:  # noqa: BLE001
            pass
    span = max(x1 - x0, y1 - y0, 1.0)
    pad = 0.03 * span
    ax.set_xlim(x0 - pad, x1 + pad)
    ax.set_ylim(y0 - pad, y1 + pad)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("in-plane (Å)")
    ax.set_ylabel("surface normal (Å)" if mode != "top" else "in-plane (Å)")
    if mode == "top":
        ax.set_ylabel("in-plane (Å)")
    formula = structure.composition.formula
    header = title or f"{formula} — {len(structure)} atoms"
    ax.set_title(f"{header}\n{subtitle}", fontsize=13)
    _legend(ax, colours, counts)
    fig.tight_layout()
    fig.savefig(str(path), dpi=DPI, facecolor="white")
    plt.close(fig)


def _is_cluster(structure: Structure) -> bool:
    try:
        gaps = gaps_all_axes(structure)
        return all(g > 6.0 for g in gaps)
    except Exception:  # noqa: BLE001
        return False


def render_structure(structure: Structure, path, *, view: str = "auto", title: str | None = None, repeat=(1, 1, 1)) -> str:
    """Render a structure preview PNG.

    Args:
        structure: structure to draw (bulk, slab or cluster-in-a-box).
        path: destination ``.png`` path (parent directories are created).
        view: ``"auto"`` (slab -> side view, else 3D), ``"side"``, ``"top"``
            (2D projections of a slab) or ``"3d"``.
        title: optional title text.
        repeat: optional repeat for visualisation only; for slabs the third
            (surface-normal) entry is forced to 1.

    Returns:
        The written path as ``str``.

    Raises:
        ValueError: empty structure, unknown view or bad repeat.
    """
    if structure is None or len(structure) == 0:
        raise ValueError("render_structure: empty structure")
    key = str(view or "auto").strip().lower()
    if key in ("side", "sideview", "side_view", "slab"):
        key = "side"
    elif key in ("3d", "perspective", "persp"):
        key = "3d"
    elif key in ("top", "surface"):
        key = "top"
    elif key != "auto":
        raise ValueError(
            f"render_structure: view must be 'auto', 'side', 'top' or '3d', got {view!r}"
        )

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    has_cjk = _configure_fonts()
    shown = _display_structure(structure, repeat)
    safe_title = _safe_title(title, shown, has_cjk)
    symbols = site_symbols(shown)
    counts: dict[str, int] = {}
    for el in symbols:
        counts[el] = counts.get(el, 0) + 1
    colours = _color_map(list(counts))

    if key == "auto":
        key = "side" if _is_slab_like(shown) else "3d"
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=r"Glyph .* missing from font")
        warnings.filterwarnings("ignore", message=r".*missing from font\(s\)")
        if key == "3d":
            _render_3d(shown, out, safe_title, colours, counts)
        else:
            _render_2d(shown, out, safe_title, colours, counts, mode=key)
    return str(out)
