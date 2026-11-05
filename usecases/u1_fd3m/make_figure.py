"""Fd-3m (#227) 点群 m-3m 典例教学图：数据核验 → CSV → PNG（离线可重跑）。

流程：
1. 读 ``data/structures/*.cif``（由 ``scripts/fetch_structures.py`` 抓取留档）；
2. 每个结构用 **spglib** 复核：空间群号、国际记号、点群、对称操作数、点群阶、
   是否含反演、F 心多重度、Wyckoff 字母/位点对称性（origin choice 2, Hall 526）；
3. 写 ``data/examples.csv``；
4. 画 2×3 的 3D 球棍 + 多面体面板，底部信息框，输出 ``figures/fd3m_examples.png``。

用法（仓库根目录）::

    .venv\\Scripts\\python.exe usecases\\u1_fd3m\\make_figure.py
    .venv\\Scripts\\python.exe usecases\\u1_fd3m\\make_figure.py --symprec 0.05

依赖：pymatgen / spglib / numpy / scipy / matplotlib（Agg，无显示环境可跑）。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sys
import textwrap
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "scripts"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Line3DCollection, Poly3DCollection  # noqa: E402
from scipy.spatial import ConvexHull  # noqa: E402

import spglib  # noqa: E402
from pymatgen.core import Element, Structure  # noqa: E402

from spec import (  # noqa: E402
    DATA,
    ELEMENT_COLORS,
    ELEMENT_RADII,
    EXAMPLES,
    EXAMPLES_CSV,
    FIGURE_PNG,
    FIG_DIR,
    STRUCT_DIR,
)

warnings.filterwarnings("ignore", message=".*Incorrect stoichiometry.*")
warnings.filterwarnings("ignore", message=".*dict interface is deprecated.*")

HALL_CHOICE2 = 526          # Fd-3m origin choice 2（尖晶石/烧绿石教科书 setting）


def retarget(outdir) -> None:
    """Write data/CSV/PNG under ``<outdir>/`` instead of the use case directory."""
    from pathlib import Path as _Path

    global STRUCT_DIR, EXAMPLES_CSV, FIG_DIR, FIGURE_PNG
    out = _Path(outdir).expanduser().resolve()
    STRUCT_DIR = out / "data" / "structures"
    EXAMPLES_CSV = out / "data" / "examples.csv"
    FIG_DIR = out / "figures"
    FIGURE_PNG = FIG_DIR / "fd3m_examples.png"


# ---------------------------------------------------------------- 基础工具
def sym(site) -> str:
    """占位度最高的元素符号（严格 CIF 无混占时即为唯一元素）。"""
    return max(site.species.items(), key=lambda kv: kv[1])[0].symbol


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def spg_cell(structure: Structure):
    """spglib 的 (lattice, positions, numbers) 三元组。"""
    return (
        np.array(structure.lattice.matrix, dtype=float),
        np.array([site.frac_coords for site in structure], dtype=float),
        np.array([Element(sym(site)).Z for site in structure], dtype=int),
    )


def spglib_dataset(structure: Structure, symprec: float, hall_number: int = 0):
    return spglib.get_symmetry_dataset(spg_cell(structure), symprec=symprec, hall_number=hall_number)


def conventional_cell(structure: Structure, symprec: float):
    """用 spglib 标准胞把任意 setting（含菱方原胞）统一成常规胞。"""
    ds = spglib_dataset(structure, symprec)
    lattice = np.array(ds.std_lattice, dtype=float)
    coords = np.array(ds.std_positions, dtype=float)
    symbols = [Element.from_Z(int(z)).symbol for z in ds.std_types]
    conv = Structure(lattice, symbols, coords, coords_are_cartesian=False)
    # 再核验一次：统一后的常规胞仍必须是 #227
    ds2 = spglib_dataset(conv, symprec)
    if int(ds2.number) != 227:
        raise RuntimeError(f"标准化后空间群不是 227，而是 {ds2.number} {ds2.international}")
    return conv, ds2


def wyckoff_summary(structure: Structure, conv: Structure, ds_choice2, ds_conv, symprec: float):
    """返回 (按 origin choice 2 的 Wyckoff 摘要, 备注)。

    5 个 CIF 本身已是常规胞（F d -3 m :2 setting），直接对原 CIF 用 Hall 526 取字母；
    LiTi2O4 的 AFLOW CIF 是菱方**原胞**（a=6.068 Å, α=60°），字母多重度会写成 2/4/8，
    对常规胞用 spglib 默认 setting 取字母后按实测映射（a↔b, c↔d）换到 origin choice 2。
    """
    rows = defaultdict(lambda: {"count": 0, "site_sym": "?", "symbols": set()})
    note = "input CIF = conventional cell; letters from spglib Hall 526 (origin choice 2)"
    if len(structure) == len(conv):
        for site, letter, ssym in zip(structure, ds_choice2.wyckoffs, ds_choice2.site_symmetry_symbols):
            key = (sym(site), letter)
            rows[key]["count"] += 1
            rows[key]["site_sym"] = ssym
            rows[key]["symbols"].add(Element(sym(site)).long_name)
    else:
        mapping = {"a": "b", "b": "a", "c": "d", "d": "c"}
        note = ("primitive-rhombohedral input cell; letters mapped to origin choice 2 via "
                "spglib Hall 525→526 correspondence (a↔b, c↔d) measured on the isotypic spinels")
        for site, letter, ssym in zip(conv, ds_conv.wyckoffs, ds_conv.site_symmetry_symbols):
            letter2 = mapping.get(letter, letter)
            key = (sym(site), letter2)
            rows[key]["count"] += 1
            rows[key]["site_sym"] = ssym
            rows[key]["symbols"].add(Element(sym(site)).long_name)
    parts = []
    for (el, letter), info in sorted(rows.items(), key=lambda kv: (kv[1]["count"], kv[0][1], kv[0][0])):
        parts.append(f"{el}:{info['count']}{letter}({info['site_sym']})")
    return "; ".join(parts), rows, note


def analyze(entry: dict, symprec: float) -> dict:
    cif = STRUCT_DIR / f"{entry['key']}.cif"
    st = Structure.from_file(str(cif))
    conv, ds_conv = conventional_cell(st, symprec)
    ds_in = spglib_dataset(st, symprec)
    try:
        ds2 = spglib_dataset(st, symprec, hall_number=HALL_CHOICE2)
    except Exception:  # noqa: BLE001 - 个别 setting 可能不被接受，退回默认
        ds2 = ds_in
    wyckoff, rows, note = wyckoff_summary(st, conv, ds2, ds_conv, symprec)

    # 点群阶 = 去重后的旋转矩阵数（F 心常规胞里共有 192 个空间操作）
    rotations = np.array(ds_conv.rotations, dtype=int)
    point_ops = {tuple(r.ravel()) for r in rotations}
    inv = any(np.array_equal(r, -np.eye(3, dtype=int)) for r in rotations)

    v_std = abs(np.linalg.det(np.array(ds_conv.std_lattice, dtype=float)))
    v_prim = abs(np.linalg.det(np.array(ds_conv.primitive_lattice, dtype=float)))
    centering_mult = int(round(v_std / v_prim))

    lat = conv.lattice
    return {
        "entry": entry,
        "cif_path": cif,
        "structure": st,
        "conv": conv,
        "formula_ideal": entry["formula"],
        "formula_cif": st.composition.reduced_formula,
        "sg_number": int(ds_conv.number),
        "sg_symbol": str(ds_conv.international),
        "point_group": str(ds_conv.pointgroup),
        "schoenflies": str(spglib.get_spacegroup_type(int(ds_conv.hall_number)).schoenflies),
        "hall_number": int(ds_conv.hall_number),
        "choice": str(spglib.get_spacegroup_type(int(ds_conv.hall_number)).choice),
        "n_symops": len(rotations),
        "pointgroup_order": len(point_ops),
        "inversion": bool(inv),
        "centering_mult": centering_mult,
        "bravais": "c" + ("F" if centering_mult == 4 else "?"),
        "a": lat.a, "b": lat.b, "c": lat.c,
        "alpha": lat.alpha, "beta": lat.beta, "gamma": lat.gamma,
        "natoms_cif": len(st),
        "natoms_conv": len(conv),
        "wyckoff": wyckoff,
        "wyckoff_rows": rows,
        "wyckoff_note": note,
        "sha256": sha256_file(cif),
    }


# ---------------------------------------------------------------- 3D 显示簇
def neighbor_pairs(cart: np.ndarray, symbols: list[str], rules: list[tuple[str, str, float]]) -> list[tuple[int, int]]:
    """按 (元素A, 元素B, 截断) 规则找近邻对（同元素对只算一次）。"""
    from scipy.spatial import cKDTree

    tree = cKDTree(cart)
    pairs: set[tuple[int, int]] = set()
    for el_a, el_b, cut in rules:
        idx_a = [i for i, s in enumerate(symbols) if s == el_a]
        for i in idx_a:
            for j in tree.query_ball_point(cart[i], cut):
                if i == j or symbols[j] != el_b:
                    continue
                if el_a == el_b and j < i:
                    continue
                pairs.add((min(i, j), max(i, j)))
    return sorted(pairs)


def polyhedra(client: dict, entry: dict) -> list[tuple[np.ndarray, np.ndarray, str]]:
    """中心原子 → 配位多面体（ConvexHull 面片），最多 ``max_poly`` 个以免糊成一团。"""
    poly = entry.get("polyhedra")
    if not poly:
        return []
    centers = poly["center"]
    centers = [centers] if isinstance(centers, str) else list(centers)
    ligand = poly["ligand"]
    cut = float(poly["cut"])
    max_poly = int(poly.get("max_poly", 24))
    cart = client["cart"]
    symbols = client["symbols"]
    mask = client["mask"]
    from scipy.spatial import cKDTree

    tree = cKDTree(cart)
    out = []
    for i in np.where(mask)[0]:
        if symbols[i] not in centers:
            continue
        verts = [j for j in tree.query_ball_point(cart[i], cut) if j != i and symbols[j] == ligand]
        if len(verts) < 4:
            continue
        pts = cart[verts]
        try:
            hull = ConvexHull(pts)
        except Exception:  # noqa: BLE001 - 退化/共面时跳过
            continue
        color = ELEMENT_COLORS.get(symbols[i], "#888888")
        out.append((pts, hull.simplices, color))
    if len(out) > max_poly:
        step = len(out) / max_poly
        out = [out[int(k * step)] for k in range(max_poly)]
    return out


def make_client(structure: Structure, reps: int, bonds: list[tuple[str, str, float]], entry: dict):
    """构造用于 3D 显示的原子簇（中心区域 + 周期像补齐）。"""
    R = 2 * reps + 1
    big = structure.copy()
    big = big.make_supercell([R, R, R])
    lat = np.array(big.lattice.matrix, dtype=float)
    shift = lat.sum(axis=0) / 2.0
    cart = np.array(big.cart_coords, dtype=float) - shift
    symbols = [sym(site) for site in big]
    a_cell = np.array(structure.lattice.matrix, dtype=float)
    half = reps * np.array([a_cell[0, 0], a_cell[1, 1], a_cell[2, 2]]) / 2.0
    mask = np.all(np.abs(cart) <= half + 1e-6, axis=1)

    keep = np.where(mask)[0]
    idx_of = {int(i): k for k, i in enumerate(keep)}
    pairs = neighbor_pairs(cart, symbols, bonds)
    segments = []
    for i, j in pairs:
        if i in idx_of and j in idx_of:
            segments.append([cart[i], cart[j]])

    client = {
        "cart": cart,
        "symbols": symbols,
        "mask": mask,
        "half": half,
        "bond_segments": segments,
        "atoms_xyz": cart[keep],
        "atoms_symbols": [symbols[i] for i in keep],
        "entry": entry,
    }
    client["polyhedra"] = polyhedra(client, entry)
    return client


# ---------------------------------------------------------------- 画图
def draw_panel(ax, ana: dict, client: dict):
    entry = ana["entry"]
    half = client["half"]
    # 显示盒边界（即 reps 倍常规胞的盒子）
    corners = np.array([[sx * half[0], sy * half[1], sz * half[2]]
                        for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)])
    edges = []
    for i in range(8):
        for j in range(i + 1, 8):
            if np.sum(np.abs(corners[i] - corners[j]) < 1e-9) == 2:  # 只差一个坐标 → 棱
                edges.append([corners[i], corners[j]])
    ax.add_collection3d(Line3DCollection(edges, colors="#c9c9c9", linewidths=1.2, linestyles="--", zorder=1))

    for verts, faces, color in client["polyhedra"]:
        pc = Poly3DCollection(
            [verts[f] for f in faces], alpha=0.13,
            facecolor=color, edgecolor=color, linewidths=0.4, zorder=2,
        )
        ax.add_collection3d(pc)

    if client["bond_segments"]:
        ax.add_collection3d(Line3DCollection(client["bond_segments"], colors="#767676", linewidths=1.4, zorder=3))

    xyz = client["atoms_xyz"]
    colors = [ELEMENT_COLORS.get(s, "#888888") for s in client["atoms_symbols"]]
    radii = np.array([ELEMENT_RADII.get(s, 0.4) for s in client["atoms_symbols"]])

    box_size = float(np.max(2 * half))
    # 面板约 6.4 in 宽 → 点/Å，球径与晶胞尺度成比例
    pt_per_ang = 6.4 * 72 / box_size
    sizes = np.pi * (radii * pt_per_ang) ** 2
    ax.scatter(xyz[:, 0], xyz[:, 1], xyz[:, 2], s=sizes, c=colors,
               edgecolors="#202020", linewidths=0.35, depthshade=False, zorder=4)

    ax.set_xlim(-half[0], half[0])
    ax.set_ylim(-half[1], half[1])
    ax.set_zlim(-half[2], half[2])
    ax.set_box_aspect((2 * half[0], 2 * half[1], 2 * half[2]))
    ax.view_init(elev=entry["view"][0], azim=entry["view"][1])
    ax.set_axis_off()
    ax.set_title(
        f"{ana['formula_ideal']}  ·  {entry['name']}\n"
        f"Fd-3m (#227)  ·  点群 m-3m  ·  a = b = c = {ana['a']:.4f} Å",
        fontsize=14, fontweight="bold", pad=2, linespacing=1.3,
    )
    ax.text2D(0.5, 0.012, textwrap.fill(entry["why"], 46), transform=ax.transAxes,
              fontsize=8.6, color="#333333", va="bottom", ha="center", linespacing=1.2,
              bbox=dict(boxstyle="round,pad=0.25", facecolor="white", alpha=0.78, edgecolor="none"))


def info_box(fig, analyses: list[dict], symprec: float):
    ax = fig.add_axes([0.012, 0.008, 0.976, 0.178])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.add_patch(plt.Rectangle((0.0, 0.0), 1.0, 1.0, facecolor="#f4f6fa", edgecolor="#8fa3c8",
                               linewidth=1.6, zorder=0, transform=ax.transAxes))

    seen = sorted({(el, v["count"], letter) for a in analyses for (el, letter), v in a["wyckoff_rows"].items()},
                  key=lambda t: (t[1], t[2], t[0]))
    seen_txt = "、".join(f"{el}-{cnt}{letter}" for el, cnt, letter in seen)
    natoms = " / ".join(f"{a['formula_ideal']} {a['natoms_conv']}" for a in analyses)
    lines = [
        ("Fd-3m 点群速览（数字均为本图脚本 spglib 实测，逐项见 data/examples.csv）", 18, "bold", "#1c3d6e"),
        ("点群 m-3m（O_h，阶 48）· 中心对称（含反演）· 空间群操作 192 = 48 × 4（F 心，V_conv / V_prim = 4）· "
         "符号中的 d = 金刚石滑移面 diamond glide", 13.2, "normal", "#222222"),
        ("与布拉维点阵的关系：Fd-3m 的平移子群就是面心立方点阵 cF；点阵的全息对称（holohedry）为 m-3m，"
         "但空间群因 d 滑移而低于 Fm-3m (#225)", 13.2, "normal", "#222222"),
        ("Wyckoff 位（origin choice 2）：8a (-43m)、8b (-43m)、16c (-3m)、16d (-3m)、32e (.3m)、48f (2.mm)；"
         "一般位 192i（多重度 192 = 48 × 4）", 13.2, "normal", "#222222"),
        ("本组示例实测占据（元素-多重度字母）：" + seen_txt + "。常规胞原子数：" + natoms,
         13.2, "normal", "#222222"),
        (f"数据：COD（5 条实验 CIF）+ AFLOW（1 条 ICSD 条目）；sha256 与 spglib 复核结果见 data/examples.csv"
         f"（symprec = {symprec} Å）。图：usecases/u1_fd3m/make_figure.py（matplotlib Agg）",
         11.8, "normal", "#555555"),
    ]
    y = 0.955
    for text, size, weight, color in lines:
        ax.text(0.010, y, text, transform=ax.transAxes, fontsize=size, fontweight=weight,
                color=color, va="top", ha="left")
        y -= size * 1.62 / 244.0

    legend_x = 0.983
    for el in ["C", "Si", "Mg", "Al", "O", "Fe", "Y", "Ti", "Li"]:
        ax.text(legend_x, 0.955, el, transform=ax.transAxes, fontsize=10, color="white", ha="center",
                va="center", fontweight="bold",
                bbox=dict(boxstyle="circle,pad=0.24", facecolor=ELEMENT_COLORS.get(el, "#888"),
                          edgecolor="#333333", linewidth=0.6))
        legend_x -= 0.030
    ax.text(legend_x + 0.004, 0.955, "元素色标", transform=ax.transAxes, fontsize=10.5,
            color="#555555", ha="right", va="center")


def write_csv(analyses: list[dict], symprec: float) -> Path:
    EXAMPLES_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "formula", "name", "source", "id", "url", "search",
        "sg_number", "sg_symbol", "point_group", "pointgroup_order", "n_symops",
        "inversion", "centering_mult", "bravais",
        "a", "b", "c", "alpha", "beta", "gamma",
        "natoms", "natoms_conv", "wyckoff_choice2", "wyckoff_note",
        "spglib_symprec", "verified_227", "sha256",
    ]
    rows = []
    for a in analyses:
        entry = a["entry"]
        rows.append({
            "formula": a["formula_ideal"],
            "name": entry["name"],
            "source": entry["source"],
            "id": entry.get("cod_id") or entry.get("aurl"),
            "url": entry["url"],
            "search": entry["search"],
            "sg_number": a["sg_number"],
            "sg_symbol": a["sg_symbol"],
            "point_group": a["point_group"],
            "pointgroup_order": a["pointgroup_order"],
            "n_symops": a["n_symops"],
            "inversion": int(a["inversion"]),
            "centering_mult": a["centering_mult"],
            "bravais": a["bravais"],
            "a": f"{a['a']:.6f}", "b": f"{a['b']:.6f}", "c": f"{a['c']:.6f}",
            "alpha": f"{a['alpha']:.4f}", "beta": f"{a['beta']:.4f}", "gamma": f"{a['gamma']:.4f}",
            "natoms": a["natoms_cif"],
            "natoms_conv": a["natoms_conv"],
            "wyckoff_choice2": a["wyckoff"],
            "wyckoff_note": a["wyckoff_note"],
            "spglib_symprec": symprec,
            "verified_227": int(a["sg_number"] == 227 and a["point_group"] == "m-3m"),
            "sha256": a["sha256"],
        })
    with EXAMPLES_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return EXAMPLES_CSV


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symprec", type=float, default=0.05, help="spglib 对称性容差（Å，默认 0.05）")
    ap.add_argument("--outdir", type=Path, default=None,
                    help="输出根目录（默认 usecases/u1_fd3m；给出时写到 <outdir>/data 与 <outdir>/figures）")
    args = ap.parse_args(argv)
    if args.outdir:
        retarget(args.outdir)

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    missing = [e["key"] for e in EXAMPLES if not (STRUCT_DIR / f"{e['key']}.cif").is_file()]
    if missing:
        print(f"缺少 CIF：{missing}\n先运行：.venv\\Scripts\\python.exe usecases\\u1_fd3m\\scripts\\fetch_structures.py")
        return 2

    analyses = [analyze(entry, args.symprec) for entry in EXAMPLES]
    bad = [a for a in analyses if a["sg_number"] != 227 or a["point_group"] != "m-3m"]
    for a in analyses:
        print(f"{a['formula_ideal']:10s} {a['formula_cif']:12s} sg={a['sg_number']} {a['sg_symbol']:7s} "
              f"pg={a['point_group']:5s} order={a['pointgroup_order']:2d} symops={a['n_symops']:3d} "
              f"F={a['centering_mult']} a={a['a']:.4f} n_conv={a['natoms_conv']:3d}  {a['wyckoff']}")
    csv_path = write_csv(analyses, args.symprec)
    print(f"\nCSV → {csv_path}")

    clients = []
    for a in analyses:
        entry = a["entry"]
        # 默认可见的键对（近邻规则，显式给出截断，便于复核）
        clients.append(make_client(a["conv"], entry["reps"], entry["bonds"], entry))

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(22.0, 16.6), facecolor="white")
    gs = fig.add_gridspec(2, 3, left=0.015, right=0.985, top=0.905, bottom=0.215,
                          wspace=0.02, hspace=0.16)
    for k, (a, client) in enumerate(zip(analyses, clients)):
        ax = fig.add_subplot(gs[k // 3, k % 3], projection="3d")
        draw_panel(ax, a, client)

    fig.suptitle("Fd-3m (#227) · 点群 m-3m (O$_h$) 的六个真实结构典例",
                 fontsize=27, fontweight="bold", y=0.985, color="#14325c")
    fig.text(0.5, 0.945,
             "每个结构都由 spglib 独立复核为 #227 Fd-3m · 点群 m-3m · 来源 COD / AFLOW（见 data/examples.csv）",
             ha="center", fontsize=14.5, color="#555555")
    info_box(fig, analyses, args.symprec)
    fig.savefig(FIGURE_PNG, dpi=170, facecolor="white")
    plt.close(fig)
    print(f"PNG → {FIGURE_PNG}")

    if bad:
        print("\n[FAIL] 以下结构未通过 #227 / m-3m 复核：")
        for a in bad:
            print("  ", a["formula_ideal"], a["sg_number"], a["point_group"])
        return 1
    print(f"\n全部 {len(analyses)} 个结构复核通过：number=227, pointgroup=m-3m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
