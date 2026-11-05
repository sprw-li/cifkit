"""14 种布拉维点阵：标准胞构造 + spglib 复核 + 特殊度量下的等价/退化实测。

产出：
* ``data/bravais14.csv``      —— 14 种布拉维点阵的标准胞、spglib 空间群/点群/全息对称
* ``data/hR_alpha_scan.csv``  —— 菱方（hR）胞 α 扫描：α=60°→cF，90°→cP，109.4712°→cI
* ``data/equivalences.csv``   —— ≥4 组（实际 11 组）特殊度量等价/退化关系的实测证据
* ``figures/bravais_relations.png`` —— 14 种点阵表 + 关系图 + 两组扫描/证据

用法（仓库根目录）::

    .venv\\Scripts\\python.exe usecases\\u2_bravais\\scripts\\bravais14.py
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
    SYSTEM_CN,
    bct,
    bravais_type,
    conventional_bcc,
    conventional_fcc,
    lattice_params,
    min_distance,
    setup_matplotlib,
    spg_info,
    volume_per_atom,
    write_csv,
)
from pymatgen.core import Lattice, Structure  # noqa: E402

SYMPREC = 0.05

#: 14 种布拉维点阵的构造 + 期望的"全息对称"（holohedry）空间群号。
#: 单原子/最小基元 + 不同心化方式，spglib 应还原出该点阵的最大对称空间群。
BRAVAIS_SPECS = [
    dict(bravais="aP", cn="简单三斜", system="a", expected_sg=2,
         build=lambda: Structure(Lattice.from_parameters(4.0, 4.7, 5.5, 78, 95, 103),
                                 ["Cu"], [[0, 0, 0]]),
         how="单原子 + P 三斜胞（a≠b≠c，α≠β≠γ≠90°）"),
    dict(bravais="mP", cn="简单单斜", system="m", expected_sg=10,
         build=lambda: Structure(Lattice.monoclinic(4.0, 5.0, 6.0, 105),
                                 ["Cu"], [[0, 0, 0]]),
         how="单原子 + P 单斜胞（β=105°）"),
    dict(bravais="mC", cn="C 心单斜", system="m", expected_sg=12,
         build=lambda: Structure(Lattice.monoclinic(4.0, 5.0, 6.0, 105),
                                 ["Cu", "Cu"], [[0, 0, 0], [0.5, 0.5, 0]]),
         how="C 心基元 (0,0,0)+(1/2,1/2,0) + 单斜胞"),
    dict(bravais="oP", cn="简单正交", system="o", expected_sg=47,
         build=lambda: Structure(Lattice.orthorhombic(3.7, 4.3, 5.1),
                                 ["Cu"], [[0, 0, 0]]),
         how="单原子 + P 正交胞（a≠b≠c）"),
    dict(bravais="oC", cn="C 心正交", system="o", expected_sg=65,
         build=lambda: Structure(Lattice.orthorhombic(3.7, 4.3, 5.1),
                                 ["Cu", "Cu"], [[0, 0, 0], [0.5, 0.5, 0]]),
         how="C 心基元 + 正交胞"),
    dict(bravais="oI", cn="体心正交", system="o", expected_sg=71,
         build=lambda: Structure(Lattice.orthorhombic(3.7, 4.3, 5.1),
                                 ["Cu", "Cu"], [[0, 0, 0], [0.5, 0.5, 0.5]]),
         how="I 心基元 + 正交胞"),
    dict(bravais="oF", cn="面心正交", system="o", expected_sg=69,
         build=lambda: Structure(Lattice.orthorhombic(3.7, 4.3, 5.1),
                                 ["Cu"] * 4,
                                 [[0, 0, 0], [0, .5, .5], [.5, 0, .5], [.5, .5, 0]]),
         how="F 心基元 + 正交胞"),
    dict(bravais="tP", cn="简单四方", system="t", expected_sg=123,
         build=lambda: Structure(Lattice.tetragonal(4.0, 5.0), ["Cu"], [[0, 0, 0]]),
         how="单原子 + P 四方胞（a=b≠c）"),
    dict(bravais="tI", cn="体心四方", system="t", expected_sg=139,
         build=lambda: Structure(Lattice.tetragonal(4.0, 5.0),
                                 ["Cu", "Cu"], [[0, 0, 0], [0.5, 0.5, 0.5]]),
         how="I 心基元 + 四方胞"),
    dict(bravais="hP", cn="六方", system="h", expected_sg=191,
         build=lambda: Structure(Lattice.hexagonal(3.0, 5.0), ["Cu"], [[0, 0, 0]]),
         how="单原子 + 六方胞（a=b，γ=120°）"),
    dict(bravais="hR", cn="菱方", system="h", expected_sg=166,
         build=lambda: Structure(Lattice.rhombohedral(4.0, 75.0), ["Cu"], [[0, 0, 0]]),
         how="单原子 + 菱方胞（α=75°，非特殊角）"),
    dict(bravais="cP", cn="简单立方", system="c", expected_sg=221,
         build=lambda: Structure(Lattice.cubic(4.0), ["Cu"], [[0, 0, 0]]),
         how="单原子 + 立方胞"),
    dict(bravais="cI", cn="体心立方", system="c", expected_sg=229,
         build=lambda: Structure(Lattice.cubic(4.0),
                                 ["Cu", "Cu"], [[0, 0, 0], [0.5, 0.5, 0.5]]),
         how="I 心基元 + 立方胞"),
    dict(bravais="cF", cn="面心立方", system="c", expected_sg=225,
         build=lambda: Structure(Lattice.cubic(4.0), ["Cu"] * 4,
                                 [[0, 0, 0], [0, .5, .5], [.5, 0, .5], [.5, .5, 0]]),
         how="F 心基元 + 立方胞"),
]

HOLOHEDRY = {
    "aP": "-1", "mP": "2/m", "mC": "2/m",
    "oP": "mmm", "oC": "mmm", "oI": "mmm", "oF": "mmm",
    "tP": "4/mmm", "tI": "4/mmm",
    "hP": "6/mmm", "hR": "-3m",
    "cP": "m-3m", "cI": "m-3m", "cF": "m-3m",
}
HOLOHEDRY_CN = {
    "-1": "三斜全息（-1）", "2/m": "单斜全息（2/m）", "mmm": "正交全息（mmm）",
    "4/mmm": "四方全息（4/mmm）", "6/mmm": "六方全息（6/mmm）",
    "-3m": "三方全息（-3m）", "m-3m": "立方全息（m-3m）",
}


def build_table() -> list[dict]:
    rows = []
    for spec in BRAVAIS_SPECS:
        s = spec["build"]()
        info = spg_info(s, symprec=SYMPREC)
        params = lattice_params(s)
        rows.append({
            "bravais": spec["bravais"],
            "name_cn": spec["cn"],
            "crystal_system": SYSTEM_CN[spec["system"]],
            "centering": info["centering"],
            "construction": spec["how"],
            "a": round(params["a"], 4), "b": round(params["b"], 4), "c": round(params["c"], 4),
            "alpha": round(params["alpha"], 4), "beta": round(params["beta"], 4),
            "gamma": round(params["gamma"], 4),
            "natoms_cell": len(s),
            "volume_per_atom": round(volume_per_atom(s), 5),
            "sg_number": info["sg_number"],
            "sg_symbol": info["sg_symbol"],
            "point_group": info["point_group"],
            "pointgroup_order": info["pointgroup_order"],
            "n_symops_conv": info["n_symops_conv"],
            "holohedry_point_group": HOLOHEDRY[spec["bravais"]],
            "holohedry_cn": HOLOHEDRY_CN[HOLOHEDRY[spec["bravais"]]],
            "expected_sg_number": spec["expected_sg"],
            "bravais_measured": info["bravais"],
            "verified": int(info["sg_number"] == spec["expected_sg"]
                            and info["bravais"] == spec["bravais"]),
        })
    return rows


# ---------------------------------------------------------------- 等价/退化
def equivalence_cases() -> list[dict]:
    """(id, 基准, 特殊度量, 构造, 期望 Bravais/空间群)。"""
    return [
        dict(id="E00", base="bct（偏离特殊度量）", metric="c/a = 1.20", expected="tI/139",
             build=lambda: bct(1.20, a_t=2.5562),
             note="对照组：一般 bct 是 tI（I4/mmm），点群 4/mmm，不是立方"),
        dict(id="E01", base="bct（Bain 路径）", metric="c/a = 1（精确）", expected="cI/229",
             build=lambda: bct(1.0, a_t=2.5562),
             note="bct 两端之一：c/a=1 时 bct 胞 = bcc 常规胞（cI, Im-3m）"),
        dict(id="E02", base="bct（Bain 路径）", metric="c/a = √2（精确）", expected="cF/225",
             build=lambda: bct(math.sqrt(2), a_t=2.5562),
             note="bct 另一端：c/a=√2 时 bct 胞 = fcc（cF, Fm-3m）；与 E00 对照可见点群 4/mmm → m-3m"),
        dict(id="E03", base="菱方 hR", metric="α = 60°（精确）", expected="cF/225",
             build=lambda: Structure(Lattice.rhombohedral(3.0, 60.0), ["Cu"], [[0, 0, 0]]),
             note="α=60° 的菱方原胞 = fcc 原胞（a_R = a_c/√2）"),
        dict(id="E04", base="菱方 hR", metric="α = 90°（精确）", expected="cP/221",
             build=lambda: Structure(Lattice.rhombohedral(3.0, 90.0), ["Cu"], [[0, 0, 0]]),
             note="α=90° 的菱方胞 = 简单立方胞（cP, Pm-3m）"),
        dict(id="E05", base="菱方 hR", metric="α = 109.4712°（精确）", expected="cI/229",
             build=lambda: Structure(Lattice.rhombohedral(3.0, math.degrees(math.acos(-1 / 3))),
                                     ["Cu"], [[0, 0, 0]]),
             note="α=arccos(-1/3)=109.4712° 的菱方原胞 = bcc 原胞（a_R = √3 a_c/2）"),
        dict(id="E06", base="C 心正交 oC", metric="a = b", expected="tP/123",
             build=lambda: Structure(Lattice.orthorhombic(4.0, 4.0, 5.1),
                                     ["Cu", "Cu"], [[0, 0, 0], [0.5, 0.5, 0]]),
             note="C 心正交胞在 a=b 时退化为 tP（C 心 + a=b ↔ P 四方，a_t = a/√2）"),
        dict(id="E07", base="简单正交 oP", metric="a = b", expected="tP/123",
             build=lambda: Structure(Lattice.orthorhombic(4.0, 4.0, 5.1), ["Cu"], [[0, 0, 0]]),
             note="oP 在 a=b 时退化为 tP（对称性升高，点群 mmm → 4/mmm）"),
        dict(id="E08", base="简单正交 oP", metric="a = b = c", expected="cP/221",
             build=lambda: Structure(Lattice.cubic(4.0), ["Cu"], [[0, 0, 0]]),
             note="oP 在 a=b=c 时退化为 cP"),
        dict(id="E09", base="简单单斜 mP", metric="β = 90°", expected="oP/47",
             build=lambda: Structure(Lattice.monoclinic(4.0, 5.0, 6.0, 90.0), ["Cu"], [[0, 0, 0]]),
             note="mP 在 β=90° 时退化为 oP（点群 2/m → mmm）"),
        dict(id="E10", base="C 心单斜 mC", metric="β = 90°", expected="oC/65",
             build=lambda: Structure(Lattice.monoclinic(4.0, 5.0, 6.0, 90.0),
                                     ["Cu", "Cu"], [[0, 0, 0], [0.5, 0.5, 0]]),
             note="mC 在 β=90° 时退化为 oC"),
        dict(id="E11", base="简单四方 tP", metric="c = a", expected="cP/221",
             build=lambda: Structure(Lattice.tetragonal(4.0, 4.0), ["Cu"], [[0, 0, 0]]),
             note="tP 在 c=a 时退化为 cP（点群 4/mmm → m-3m）"),
    ]


def build_equivalences() -> list[dict]:
    rows = []
    for case in equivalence_cases():
        s = case["build"]()
        info = spg_info(s, symprec=SYMPREC)
        params = lattice_params(s)
        std = np.array(info["std_lattice"], dtype=float)
        exp_bravais, exp_sg = case["expected"].split("/")
        rows.append({
            "id": case["id"],
            "base_lattice": case["base"],
            "special_metric": case["metric"],
            "construction": case["note"],
            "a": round(params["a"], 4), "b": round(params["b"], 4), "c": round(params["c"], 4),
            "alpha": round(params["alpha"], 4), "beta": round(params["beta"], 4),
            "gamma": round(params["gamma"], 4),
            "sg_number": info["sg_number"],
            "sg_symbol": info["sg_symbol"],
            "point_group": info["point_group"],
            "pointgroup_order": info["pointgroup_order"],
            "n_symops_conv": info["n_symops_conv"],
            "bravais_measured": info["bravais"],
            "expected_bravais": exp_bravais,
            "expected_sg_number": int(exp_sg),
            "std_a": round(float(np.linalg.norm(std[0])), 5),
            "std_b": round(float(np.linalg.norm(std[1])), 5),
            "std_c": round(float(np.linalg.norm(std[2])), 5),
            "volume_per_atom": round(volume_per_atom(s), 5),
            "nn_distance": round(min_distance(s), 5),
            "verified": int(info["bravais"] == exp_bravais and info["sg_number"] == int(exp_sg)),
        })
    return rows


def alpha_scan() -> list[dict]:
    alphas = sorted({float(a) for a in range(50, 116)} | {60.0, 90.0, 109.4712})
    rows = []
    for alpha in alphas:
        s = Structure(Lattice.rhombohedral(3.0, alpha), ["Cu"], [[0, 0, 0]])
        try:
            info = spg_info(s, symprec=0.01)
        except RuntimeError as exc:
            rows.append({"alpha_deg": round(alpha, 4), "note": str(exc), "sg_number": "",
                         "sg_symbol": "", "point_group": "", "bravais_measured": ""})
            continue
        rows.append({
            "alpha_deg": round(alpha, 4),
            "sg_number": info["sg_number"],
            "sg_symbol": info["sg_symbol"],
            "point_group": info["point_group"],
            "pointgroup_order": info["pointgroup_order"],
            "n_symops_conv": info["n_symops_conv"],
            "bravais_measured": info["bravais"],
            "is_special": int(any(abs(alpha - t) < 1e-3 for t in (60.0, 90.0, 109.4712))),
        })
    return rows


# ---------------------------------------------------------------- 图
def plot_relations(table: list[dict], equiv: list[dict], scan: list[dict]):
    plt = setup_matplotlib()
    from matplotlib.patches import Circle, FancyBboxPatch, Rectangle

    fig = plt.figure(figsize=(22, 16))
    fig.patch.set_facecolor("white")
    gs = fig.add_gridspec(2, 2, left=0.045, right=0.985, top=0.90, bottom=0.055,
                          wspace=0.30, hspace=0.26)

    sys_color = {"a": "#8c6bb1", "m": "#2c7fb8", "o": "#41ab5d", "t": "#e07b39",
                 "h": "#c51b8a", "c": "#d62728"}
    # ---------------- (a) 14 种点阵网格
    ax = fig.add_subplot(gs[0, 0])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_title("14 种布拉维点阵 = 7 晶系 × 允许的心化方式（每格：类型 / 全息对称空间群）",
                 fontsize=13.5, fontweight="bold")
    rows_spec = [("aP", ["aP"]), ("mP · mC", ["mP", "mC"]), ("oP · oC · oI · oF", ["oP", "oC", "oI", "oF"]),
                 ("tP · tI", ["tP", "tI"]), ("hP · hR", ["hP", "hR"]), ("cP · cI · cF", ["cP", "cI", "cF"])]
    row_y = np.linspace(0.86, 0.12, len(rows_spec))
    info_by = {row["bravais"]: row for row in table}
    system_cn = {"a": "三斜", "m": "单斜", "o": "正交", "t": "四方", "h": "三方/六方", "c": "立方"}
    for y, (label, names) in zip(row_y, rows_spec):
        ax.text(0.0, y, f"{system_cn[names[0][0]]}：{label}", fontsize=10.5,
                color="#333333", va="center", ha="left")
        for k, name in enumerate(names):
            row = info_by[name]
            x = 0.36 + k * 0.155
            color = sys_color[name[0]]
            ax.add_patch(FancyBboxPatch((x, y - 0.045), 0.145, 0.09,
                                        boxstyle="round,pad=0.004", facecolor=color,
                                        edgecolor="white", linewidth=1.2, alpha=0.16))
            ax.text(x + 0.0725, y + 0.012, f"{name}  #{row['sg_number']}", ha="center", va="center",
                    fontsize=11, fontweight="bold", color=color)
            ax.text(x + 0.0725, y - 0.023, row["sg_symbol"], ha="center", va="center",
                    fontsize=8.5, color="#555555")
    ax.text(0.05, 0.945, "同一行内从左到右为允许的心化方式（P/C/I/F/R，盒内已标注）",
            fontsize=9.5, color="#666666", ha="left")

    # ---------------- (b) 关系图
    ax = fig.add_subplot(gs[0, 1])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_title("特殊度量下的等价 / 退化关系（边上的标注为触发条件，均为 spglib 实测）",
                 fontsize=13.5, fontweight="bold")
    pos = {"hR": (0.50, 0.93), "cF": (0.88, 0.72), "cP": (0.50, 0.68), "cI": (0.12, 0.72),
           "tI": (0.50, 0.45), "tP": (0.22, 0.22), "oC": (0.72, 0.26), "oP": (0.52, 0.11),
           "mP": (0.92, 0.42)}
    edges = [
        ("hR", "cF", "α=60°"), ("hR", "cI", "α=109.47°"), ("hR", "cP", "α=90°"),
        ("tI", "cF", "c/a=√2"), ("tI", "cI", "c/a=1"),
        ("tP", "cP", "c=a"), ("oC", "tP", "a=b"), ("oP", "tP", "a=b"),
        ("oP", "cP", "a=b=c"), ("mP", "oP", "β=90°"), ("mP", "oC", "β=90°（C 心）"),
    ]
    for a, b, label in edges:
        (x1, y1), (x2, y2) = pos[a], pos[b]
        ax.plot([x1, x2], [y1, y2], color="#999999", lw=1.5, zorder=1)
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.018, label, fontsize=9.2, color="#b03a2e",
                ha="center", va="bottom", zorder=3,
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85))
    colors = {"cF": "#2e9e5b", "cI": "#2e6fba", "cP": "#2e9e5b", "tI": "#c94f4f",
              "hR": "#c51b8a", "tP": "#e07b39", "oC": "#41ab5d", "oP": "#41ab5d", "mP": "#2c7fb8"}
    for name, (x, y) in pos.items():
        ax.add_patch(Circle((x, y), 0.055, facecolor=colors[name], alpha=0.9, ec="white", lw=1.5, zorder=4))
        ax.text(x, y + 0.085, name, fontsize=12, fontweight="bold", ha="center", color=colors[name], zorder=5)
    ax.text(0.02, -0.055, "cF ≡ tI 只是 c/a=√2 这一特殊度量下的等价：tI 的点群是 4/mmm（阶 16），"
                          "cF 的点群是 m-3m（阶 48），两者不是同一个点群。",
            fontsize=10.2, color="#333333", ha="left", va="bottom", clip_on=False,
            bbox=dict(boxstyle="round,pad=0.3", fc="#fff8e7", ec="#d9b44a"))

    # ---------------- (c) 菱方 α 扫描
    ax = fig.add_subplot(gs[1, 0])
    alphas = np.array([row["alpha_deg"] for row in scan if row.get("sg_number") != ""])
    orders = np.array([row["pointgroup_order"] for row in scan if row.get("sg_number") != ""])
    brav = [row["bravais_measured"] for row in scan if row.get("sg_number") != ""]
    cc = {"hR": "#c51b8a", "cF": "#2e9e5b", "cP": "#2e9e5b", "cI": "#2e6fba"}
    for b, col in cc.items():
        m = np.array([bb == b for bb in brav])
        if m.any():
            ax.scatter(alphas[m], orders[m], s=34, color=col, label=b, zorder=3,
                       edgecolors="white", linewidths=0.4)
    for x0, lab, col in [(60.0, "α=60°\ncF", "#2e9e5b"), (90.0, "α=90°\ncP", "#2e9e5b"),
                         (109.4712, "α=109.47°\ncI", "#2e6fba")]:
        ax.axvline(x0, color=col, ls="--", lw=1.4, zorder=2)
        ax.annotate(lab, xy=(x0, 48), xytext=(x0 - 2.2, 44), fontsize=10.5, color=col,
                    fontweight="bold", ha="right")
    ax.set_xlim(49, 116)
    ax.set_ylim(0, 55)
    ax.set_xlabel("菱方胞 α（°，a=b=c=3.0 Å 固定）", fontsize=11.5)
    ax.set_ylabel("点群阶", fontsize=11.5)
    ax.set_title("菱方 hR 胞：α 在 60° / 90° / 109.47° 处退化为 cF / cP / cI", fontsize=13.5,
                 fontweight="bold")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=10, loc="lower left", framealpha=0.95)

    # ---------------- (d) 等价关系证据
    ax = fig.add_subplot(gs[1, 1])
    ids = [row["id"] for row in equiv]
    ops = [row["n_symops_conv"] for row in equiv]
    labels = [f"{row['id']}  {row['bravais_measured']} #{row['sg_number']}" for row in equiv]
    cols = ["#c94f4f" if row["bravais_measured"] in ("tI", "hR") else "#2e9e5b"
            for row in equiv]
    y = np.arange(len(ids))
    bars = ax.barh(y, ops, color=cols, alpha=0.85, edgecolor="white")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9.6)
    ax.invert_yaxis()
    for bar, row in zip(bars, equiv):
        ax.text(bar.get_width() + 3, bar.get_y() + bar.get_height() / 2,
                f"{row['n_symops_conv']} ops · {row['point_group']} · {row['special_metric']}",
                va="center", fontsize=8.8, color="#333333")
    ax.set_xlim(0, 360)
    ax.set_xlabel("常规胞对称操作数（cP=48, tI=32, cI=96, cF=192）", fontsize=11.5)
    ax.set_title("12 组等价/退化关系的 spglib 实测（E00 为对照：一般 bct = tI）",
                 fontsize=13.5, fontweight="bold")
    ax.grid(axis="x", alpha=0.25)

    fig.suptitle("14 种布拉维点阵的对称性等效与退化 —— spglib 实测（symprec = 0.05 Å）",
                 fontsize=18, fontweight="bold", y=0.975)
    FIG.mkdir(parents=True, exist_ok=True)
    out = FIG / "bravais_relations.png"
    fig.savefig(out, dpi=160, facecolor="white")
    plt.close(fig)
    return out


def main() -> int:
    table = build_table()
    equiv = build_equivalences()
    scan = alpha_scan()
    p1 = write_csv(table, DATA / "bravais14.csv")
    p2 = write_csv(equiv, DATA / "equivalences.csv")
    p3 = write_csv(scan, DATA / "hR_alpha_scan.csv")
    png = plot_relations(table, equiv, scan)

    print(f"CSV → {p1}（{len(table)} 行）")
    print(f"CSV → {p2}（{len(equiv)} 行）")
    print(f"CSV → {p3}（{len(scan)} 行）")
    print(f"PNG → {png}\n")
    for row in table:
        flag = "OK " if row["verified"] else "FAIL"
        print(f"{flag} {row['bravais']:3s} {row['sg_number']:3d} {row['sg_symbol']:8s} "
              f"pg={row['point_group']:6s} holohedry={row['holohedry_point_group']:7s} "
              f"ops={row['n_symops_conv']:3d}")
    print()
    for row in equiv:
        flag = "OK " if row["verified"] else "FAIL"
        print(f"{flag} {row['id']}: {row['base_lattice']} @ {row['special_metric']} → "
              f"{row['bravais_measured']} #{row['sg_number']} {row['sg_symbol']} "
              f"pg={row['point_group']} ops={row['n_symops_conv']}")
    n_ok = sum(row["verified"] for row in table)
    m_ok = sum(row["verified"] for row in equiv)
    print(f"\n14 种点阵验证：{n_ok}/14；等价/退化关系验证：{m_ok}/{len(equiv)}")
    return 0 if n_ok == 14 and m_ok == len(equiv) else 1


if __name__ == "__main__":
    raise SystemExit(main())
