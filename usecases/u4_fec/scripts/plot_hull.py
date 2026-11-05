#!/usr/bin/env python
"""Plot the 0 K Fe-C convex hull (and the spread of AFLOW LIB2 DFT prototypes).

Can be used either as a module (``plot_hull(...)`` is called by
``build_hull.py``) or standalone, reading the CSVs that are shipped in the kit::

    .venv\\Scripts\\python.exe usecases\\u4_fec\\scripts\\plot_hull.py
    .venv\\Scripts\\python.exe usecases\\u4_fec\\scripts\\plot_hull.py --out figures\\my.png

Figure content
--------------
* left panel : every AFLOW LIB2 Fe-C entry (light grey) + the lowest-enthalpy
  entry at each composition (blue) + the lower convex hull (black line);
* right panel: zoom on the composition minima with the key carbides labelled,
  plus vertical guides for the ICSD-only phases Fe5C2 / Fe7C3 which have no
  AFLOW formation enthalpy and therefore cannot enter the hull.

Axis: x = at%C (0 = pure Fe, 100 = pure C), y = formation enthalpy in eV/atom.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
KIT = HERE.parent

# compositions (at%C) of phases that are missing an AFLOW enthalpy
MISSING_ENTHALPY = [(2.0 / 7.0 * 100.0, "Fe5C2"), (3.0 / 10.0 * 100.0, "Fe7C3")]


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _row_at(hull_rows: list[dict], at_percent_c: float, tol: float = 5e-3) -> dict | None:
    return next((r for r in hull_rows
                 if abs(float(r["at_percent_C"]) - at_percent_c) < tol), None)


def plot_hull(energy_rows: list[dict], hull_rows: list[dict], out_png: Path,
              title_suffix: str = "") -> Path:
    """Draw the two-panel hull figure. Returns the written path."""
    cloud = [
        (100.0 * float(r["x_C"]), float(r["enthalpy_formation_atom"]))
        for r in energy_rows
        if r.get("enthalpy_formation_atom") not in (None, "", "None")
    ]
    minima = [
        (float(r["at_percent_C"]), float(r["energy_formation_eV_per_atom"]))
        for r in hull_rows
        if r.get("compound") not in ("Fe", "C")
    ]
    hull = sorted(
        (float(r["at_percent_C"]), float(r["hull_energy_eV_per_atom"]))
        for r in hull_rows if r["on_hull"] == "yes"
    )

    fig, (ax_full, ax_zoom) = plt.subplots(
        1, 2, figsize=(13.5, 5.6), gridspec_kw={"width_ratios": [1.12, 1.0]}
    )

    for ax, title in ((ax_full, "(a) every AFLOW LIB2 Fe-C entry"),
                      (ax_zoom, "(b) composition minima + 0 K hull")):
        ax.scatter(*zip(*cloud), s=12, c="#b8b8b8", alpha=0.55, zorder=2,
                   linewidths=0,
                   label="AFLOW LIB2 entry" if ax is ax_full else None)
        ax.plot(*zip(*hull), color="black", lw=2.2, zorder=4,
                label="0 K convex hull (lower envelope)")
        ax.scatter(*zip(*minima), s=44, facecolors="none", edgecolors="#1f4e9c",
                   linewidths=1.4, zorder=5,
                   label="lowest entry per composition")
        ax.set_xlabel("carbon content  (at.% C)")
        ax.set_ylabel(r"formation enthalpy  $E_\mathrm{form}$  (eV/atom)")
        ax.set_title(title, fontsize=11)
        ax.grid(True, ls=":", lw=0.6, alpha=0.6)
        ax.axhline(0.0, color="0.55", lw=0.8, ls="--")
        ax.set_xlim(-3, 103)
        ax.xaxis.set_major_locator(matplotlib.ticker.MultipleLocator(20))

    # guides for the ICSD-only phases (no AFLOW enthalpy)
    label_y = {"Fe5C2": 0.46, "Fe7C3": 0.30}
    for x_at, label in MISSING_ENTHALPY:
        for ax in (ax_full, ax_zoom):
            ax.axvline(x_at, color="#7d3c98", lw=1.0, ls="--", alpha=0.65)
        ax_zoom.text(x_at - 0.9, label_y.get(label, 0.47), label, rotation=90,
                     fontsize=7.5, color="#7d3c98", ha="right", va="top")
    ax_zoom.text(2.0, 0.53,
                 "Fe5C2 (Hägg) & Fe7C3:\nICSD structures only,\n"
                 "no AFLOW E$_{form}$ → not on hull",
                 fontsize=7.6, color="#7d3c98", va="top",
                 bbox=dict(boxstyle="round,pad=0.28", fc="white",
                           ec="#7d3c98", alpha=0.85, lw=0.7))

    # ---------- Fe3C: the headline number ----------------------------------
    fe3c = _row_at(hull_rows, 25.0)
    if fe3c is not None:
        x = float(fe3c["at_percent_C"])
        y = float(fe3c["energy_formation_eV_per_atom"])
        above = float(fe3c["energy_above_hull_eV_per_atom"])
        ax_zoom.annotate(
            f"Fe$_3$C cementite (Pnma)\nE$_{{form}}$ = {y:+.4f} eV/atom\n"
            f"+{above:.4f} eV/atom above hull",
            xy=(x, y), xytext=(41, 0.235),
            arrowprops=dict(arrowstyle="->", color="#c0392b", lw=1.1,
                            shrinkB=2),
            fontsize=8.8, color="#7b241c",
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#c0392b", alpha=0.92),
        )
        ax_full.annotate("Fe$_3$C", xy=(x, y), xytext=(x + 1.5, 0.10),
                         fontsize=8.5, color="#c0392b",
                         arrowprops=dict(arrowstyle="->", color="#c0392b", lw=0.9))

    # ---------- other labelled minima --------------------------------------
    for at_percent_c, label, dx, dy, color in (
        (100.0 / 3.0, "Fe$_2$C (oP6, Pnnm)", 5.0, 0.10, "#1f4e9c"),
        (50.0, "FeC (hP6)", 6.0, 0.055, "#1f4e9c"),
    ):
        row = _row_at(hull_rows, at_percent_c)
        if row is None:
            continue
        x = float(row["at_percent_C"])
        y = float(row["energy_formation_eV_per_atom"])
        ax_zoom.annotate(f"{label}\n{y:+.3f} eV/atom", xy=(x, y),
                         xytext=(x + dx, y + dy), fontsize=8.2, color=color,
                         arrowprops=dict(arrowstyle="-", color=color, lw=0.7))

    # element endpoints
    ax_full.text(2.0, 3.0, "Fe (bcc)\nE = 0", fontsize=8, color="0.35")
    ax_full.text(98.0, 3.0, "C (reference)\nE = 0", fontsize=8, color="0.35",
                 ha="right")

    # limits
    ymax = max(y for _, y in cloud) if cloud else 1.0
    ax_full.set_ylim(-0.08, ymax * 1.10)
    ax_zoom.set_ylim(-0.02, 0.62)

    ax_full.legend(loc="upper right", fontsize=8, framealpha=0.92)
    fig.suptitle("Fe-C 0 K convex hull from AFLOW LIB2 formation enthalpies"
                 + title_suffix, fontsize=12)
    fig.text(
        0.5, 0.008,
        "Only phases with an AFLOW formation enthalpy enter the hull; Fe5C2 (Hägg) "
        "and Fe7C3 are ICSD structures without an AFLOW enthalpy and are guides only. "
        "Grey cloud = every DFT prototype AFLOW tried — not a phase diagram.",
        ha="center", fontsize=7.5, color="0.35",
    )
    fig.subplots_adjust(left=0.065, right=0.985, top=0.90, bottom=0.11, wspace=0.20)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=180)
    plt.close(fig)
    return out_png


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="plot the Fe-C 0 K hull")
    ap.add_argument("--energies-csv", type=Path,
                    default=KIT / "data" / "aflow_fe_c_energies.csv")
    ap.add_argument("--hull-csv", type=Path, default=KIT / "data" / "hull_points.csv")
    ap.add_argument("--out", type=Path, default=KIT / "figures" / "fe_c_hull.png")
    args = ap.parse_args(argv)
    plot_hull(_read_csv(args.energies_csv), _read_csv(args.hull_csv), args.out)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
