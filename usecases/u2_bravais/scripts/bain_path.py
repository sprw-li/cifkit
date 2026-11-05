"""Bain 路径：fcc(cF) — bct(tI) — bcc(cI) 的对称性退化与恢复（spglib 实测）。

构造：bct 胞（2 原子基元 (0,0,0)+(1/2,1/2,1/2)），a=b=a_t 固定为 fcc Cu 的
a_t = a_c/√2 = 2.5562 Å，c = (c/a)·a_t 从 0.90 扫到 1.70（步长 0.01），
并额外插入精确的 c/a = 1（bcc）与 c/a = √2（fcc）两个特殊点。

输出：
* ``data/bain_path.csv``      —— 每个 c/a 点的 spglib 空间群/点群/Bravais/体积/近邻距
* ``data/bain_tolerance.csv`` —— 同一批 c/a 在 symprec=0.01 与 0.05 Å 下的判定差异
* ``figures/bain_symmetry.png`` —— 对称性 vs c/a（点群阶 / 常规胞操作数）
* ``figures/bain_cells.png``   —— cF / tI / cI 三种胞的几何示意

用法（仓库根目录）::

    .venv\\Scripts\\python.exe usecases\\u2_bravais\\scripts\\bain_path.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    DATA,
    FIG,
    bct,
    conventional_bcc,
    conventional_fcc,
    min_distance,
    setup_matplotlib,
    spg_info,
    volume_per_atom,
    write_csv,
)

A_C = 3.6150                     # fcc Cu 常规胞（教学用标准值）
A_T = A_C / math.sqrt(2)        # Bain 关系：a_t = a_c/√2 = 2.5562 Å
C_OVER_A_MIN, C_OVER_A_MAX, C_OVER_A_STEP = 0.90, 1.70, 0.01
SYMPREC = 0.01                   # 严格：只有精确特殊度量才判为立方
SYMPREC_LOOSE = 0.05             # 默认容差，用于展示"容差窗口"


def scan_one(r: float, symprec: float) -> dict:
    s = bct(r, a_t=A_T)
    info = spg_info(s, symprec=symprec)
    params = s.lattice
    std = np.array(info["std_lattice"], dtype=float)
    return {
        "c_over_a": round(r, 6),
        "a_t": round(params.a, 6),
        "c_t": round(params.c, 6),
        "delta_to_fcc_metric": round(abs(params.c - math.sqrt(2) * params.a), 6),
        "spacegroup_number": info["sg_number"],
        "spacegroup_symbol": info["sg_symbol"],
        "point_group": info["point_group"],
        "pointgroup_order": info["pointgroup_order"],
        "n_symops_conv": info["n_symops_conv"],
        "n_symops_input": info["n_symops_input"],
        "bravais": info["bravais"],
        "centering": info["centering"],
        "std_a": round(float(np.linalg.norm(std[0])), 6),
        "std_b": round(float(np.linalg.norm(std[1])), 6),
        "std_c": round(float(np.linalg.norm(std[2])), 6),
        "volume_per_atom": round(volume_per_atom(s), 5),
        "nn_distance": round(min_distance(s), 5),
        "is_special": int(abs(r - 1.0) < 1e-9 or abs(r - math.sqrt(2)) < 1e-9),
    }


def make_bain_data() -> list[dict]:
    grid = np.round(np.arange(C_OVER_A_MIN, C_OVER_A_MAX + 1e-9, C_OVER_A_STEP), 2)
    points = sorted({float(r) for r in grid} | {1.0, math.sqrt(2)})
    return [scan_one(r, SYMPREC) for r in points]


def make_tolerance_table(points=(0.99, 1.0, 1.01, 1.40, 1.41, 1.42, 1.43)) -> list[dict]:
    rows = []
    for r in points:
        row = {"c_over_a": round(float(r), 6)}
        for label, symprec in (("tight_0.01", SYMPREC), ("loose_0.05", SYMPREC_LOOSE)):
            info = spg_info(bct(float(r), a_t=A_T), symprec=symprec)
            row[f"sg_{label}"] = info["sg_number"]
            row[f"symbol_{label}"] = info["sg_symbol"]
            row[f"bravais_{label}"] = info["bravais"]
        row["delta_to_special_metric"] = round(
            min(abs(float(r) - 1.0), abs(float(r) - math.sqrt(2))) * A_T, 6)
        rows.append(row)
    return rows


# ---------------------------------------------------------------- 图 1
def plot_symmetry(rows: list[dict]):
    plt = setup_matplotlib()
    r = np.array([row["c_over_a"] for row in rows])
    pg_order = np.array([row["pointgroup_order"] for row in rows])
    ops = np.array([row["n_symops_conv"] for row in rows])
    bravais = [row["bravais"] for row in rows]
    colors = {"tI": "#c94f4f", "cI": "#2e6fba", "cF": "#2e9e5b"}

    fig, axes = plt.subplots(1, 2, figsize=(17, 7.2), gridspec_kw={"width_ratios": [1.05, 1]})
    fig.patch.set_facecolor("white")

    for ax, y, ylabel, title in [
        (axes[0], pg_order, "点群阶（m-3m = 48；4/mmm = 16）", "点群：只有特殊度量才升到 m-3m"),
        (axes[1], ops, "常规胞对称操作数（cF=192，cI=96，tI=32）", "空间群操作数：cF / cI / tI"),
    ]:
        ax.axvspan(C_OVER_A_MIN, C_OVER_A_MAX, color="#f3f5f8", zorder=0)
        for b, c in colors.items():
            mask = np.array([bb == b for bb in bravais])
            ax.scatter(r[mask], y[mask], s=42, c=c, label={"tI": "tI (I4/mmm)", "cI": "cI (Im-3m)",
                                                             "cF": "cF (Fm-3m)"}[b], zorder=3,
                       edgecolors="white", linewidths=0.4)
        for x0, lab, cc in [(1.0, "c/a = 1\ncI (Im-3m)", "#2e6fba"),
                            (math.sqrt(2), "c/a = √2\ncF (Fm-3m)", "#2e9e5b")]:
            ax.axvline(x0, color=cc, linestyle="--", linewidth=1.5, zorder=2)
            ax.annotate(lab, xy=(x0, max(y)), xytext=(x0 + (0.015 if x0 < 1.3 else -0.02), max(y)),
                        textcoords="data", fontsize=11.5, color=cc, ha="left" if x0 < 1.3 else "right",
                        va="top", fontweight="bold")
        ax.set_xlim(C_OVER_A_MIN - 0.01, C_OVER_A_MAX + 0.01)
        ax.set_xlabel("c / a（bct 胞，a = a$_t$ = a$_c$/√2 = %.4f Å）" % A_T, fontsize=12)
        ax.set_ylabel(ylabel, fontsize=12)
        ax.set_title(title, fontsize=14, fontweight="bold")
        ax.grid(alpha=0.25)
        ax.legend(fontsize=10.5, loc="center right", framealpha=0.95)

    fig.suptitle("Bain 路径：单轴应变下的 bct 对称性 —— cF 与 tI 只在 c/a = √2 这一特殊度量下等价",
                 fontsize=16.5, fontweight="bold", y=0.975)
    fig.text(0.5, 0.925,
             f"spglib symprec = {SYMPREC} Å；a$_t$ = {A_T:.4f} Å 固定，c = (c/a)·a$_t$ 扫描 "
             f"{C_OVER_A_MIN}–{C_OVER_A_MAX}（步长 {C_OVER_A_STEP}）+ 精确 c/a=1、√2 两点；数据见 data/bain_path.csv",
             ha="center", fontsize=11, color="#555555")
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    FIG.mkdir(parents=True, exist_ok=True)
    out = FIG / "bain_symmetry.png"
    fig.savefig(out, dpi=170)
    plt.close(fig)
    return out


# ---------------------------------------------------------------- 图 2（3D 胞示意）
def _draw_cell(ax, structure, color, title, subtitle, atom_colors=None, cell_color="#3366aa"):
    """画一个胞：原子 + 三个晶格矢量箭头 + 虚线盒。"""
    lat = np.array(structure.lattice.matrix)
    frac = np.array([site.frac_coords for site in structure])
    cart = frac @ lat
    for vec, label in zip(lat, ["a", "b", "c"]):
        ax.quiver(0, 0, 0, *vec, color=cell_color, linewidth=2.2, arrow_length_ratio=0.12)
        ax.text(*(vec * 1.06), label, fontsize=14, color=cell_color, fontweight="bold")
    # 虚线盒
    corners = np.array([[i, j, k] for i in (0, 1) for j in (0, 1) for k in (0, 1)])
    corners_cart = corners @ lat
    for i in range(8):
        for j in range(i + 1, 8):
            if np.sum(np.abs(corners[i] - corners[j]) < 1e-9) == 2:
                ax.plot(*zip(corners_cart[i], corners_cart[j]), color="#bbbbbb", lw=0.9, ls="--")
    symbols = [site.species.elements[0].symbol for site in structure]
    colors = atom_colors or {"Cu": "#c97b3a"}
    ax.scatter(cart[:, 0], cart[:, 1], cart[:, 2], s=260,
               c=[colors.get(s, "#888888") for s in symbols], edgecolors="#333333", linewidths=0.6)
    ax.set_box_aspect((lat[0, 0], lat[1, 1], lat[2, 2]))
    m = lat.sum(axis=0) / 2
    ax.set_xlim(0, m[0] * 2.1)
    ax.set_ylim(0, m[1] * 2.1)
    ax.set_zlim(0, m[2] * 2.1)
    ax.set_axis_off()
    ax.set_title(title + "\n" + subtitle, fontsize=13, fontweight="bold", linespacing=1.35)
    ax.view_init(elev=20, azim=32)


def plot_cells():
    plt = setup_matplotlib()
    fig = plt.figure(figsize=(18, 7.2))
    fig.patch.set_facecolor("white")
    # 1) fcc 常规胞 + 2×2×2 轮廓说明
    ax1 = fig.add_subplot(1, 3, 1, projection="3d")
    fcc = conventional_fcc(A_C)
    _draw_cell(ax1, fcc, "#2e9e5b", "cF（Fm-3m）· fcc 常规胞",
               f"a$_c$ = {A_C:.4f} Å，4 原子/胞")
    # 2) bct 胞（一般 c/a=1.2 → tI）
    ax2 = fig.add_subplot(1, 3, 2, projection="3d")
    r_show = 1.2
    bct_cell = bct(r_show, a_t=A_T)
    _draw_cell(ax2, bct_cell, "#c94f4f", f"tI（I4/mmm）· bct 胞，c/a = {r_show}",
               f"a$_t$ = {A_T:.4f} Å，c$_t$ = {r_show * A_T:.4f} Å，2 原子/胞")
    # 3) bcc 常规胞
    ax3 = fig.add_subplot(1, 3, 3, projection="3d")
    bcc = conventional_bcc(A_T)
    _draw_cell(ax3, bcc, "#2e6fba", "cI（Im-3m）· bcc 常规胞",
               f"a$_{{bcc}}$ = a$_t$ = {A_T:.4f} Å，2 原子/胞")
    fig.suptitle("Bain 路径的几何：fcc 常规胞 → bct 胞（a$_t$ = a$_c$/√2, c$_t$ 可变）→ bcc",
                 fontsize=16.5, fontweight="bold", y=0.98)
    fig.text(0.5, 0.925,
             "c/a = √2：bct 胞恰为 fcc；c/a = 1：bct 胞恰为 bcc。中间为 tI（I4/mmm）。"
             "三个胞都含 2 个基元位点（bct/bcc）或 4 个（fcc 常规胞），体积/原子一致。",
             ha="center", fontsize=11.5, color="#555555")
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    FIG.mkdir(parents=True, exist_ok=True)
    out = FIG / "bain_cells.png"
    fig.savefig(out, dpi=170)
    plt.close(fig)
    return out


def main() -> int:
    rows = make_bain_data()
    path = write_csv(rows, DATA / "bain_path.csv")
    tol = write_csv(make_tolerance_table(), DATA / "bain_tolerance.csv")
    f1 = plot_symmetry(rows)
    f2 = plot_cells()

    specials = {row["c_over_a"]: row for row in rows if row["is_special"]}
    grid = [row for row in rows if not row["is_special"]]
    print(f"CSV → {path}（{len(rows)} 行）")
    print(f"CSV → {tol}")
    print(f"PNG → {f1}\nPNG → {f2}")
    for r, row in specials.items():
        print(f"c/a = {r:.6f}: sg={row['spacegroup_number']} {row['spacegroup_symbol']} "
              f"pg={row['point_group']} bravais={row['bravais']} ops={row['n_symops_conv']}")
    generic = [row for row in grid if row["spacegroup_number"] != 139]
    print(f"网格点中非 tI 的点：{[(x['c_over_a'], x['spacegroup_symbol']) for x in generic]}")
    print(f"tI 区间：{min(x['c_over_a'] for x in grid if x['spacegroup_number'] == 139):.2f}"
          f"–{max(x['c_over_a'] for x in grid if x['spacegroup_number'] == 139):.2f} 共 "
          f"{sum(1 for x in grid if x['spacegroup_number'] == 139)} 点")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
