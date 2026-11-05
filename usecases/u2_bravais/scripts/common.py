"""u2_bravais 共用工具：spglib 判定、Bravais 类型映射、CSV 写出、matplotlib 中文字体。"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import spglib
from pymatgen.core import Lattice, Structure

ROOT = Path(__file__).resolve().parents[1]      # usecases/u2_bravais
DATA = ROOT / "data"
FIG = ROOT / "figures"

SYSTEM_BY_NUMBER = [
    (1, 2, "a"), (3, 15, "m"), (16, 74, "o"),
    (75, 142, "t"), (143, 167, "h"), (168, 194, "h"), (195, 230, "c"),
]
SYSTEM_CN = {
    "a": "三斜 triclinic", "m": "单斜 monoclinic", "o": "正交 orthorhombic",
    "t": "四方 tetragonal", "h": "三方/六方 trigonal-hexagonal", "c": "立方 cubic",
}
CENTER_CN = {"P": "简单 P", "C": "C 心", "I": "体心 I", "F": "面心 F", "R": "菱方 R"}


def system_letter(number: int) -> str:
    for lo, hi, letter in SYSTEM_BY_NUMBER:
        if lo <= number <= hi:
            return letter
    raise ValueError(f"非法空间群号 {number}")


def bravais_type(ds) -> str:
    """从 spglib dataset 推 Bravais 类型（aP/mP/mC/oP/oC/oI/oF/tP/tI/hP/hR/cP/cI/cF）。"""
    letter = system_letter(int(ds.number))
    symbol = str(ds.international).replace(" ", "")
    centering = symbol[0] if symbol and symbol[0] in "PABCIFR" else "P"
    if letter == "h" and centering == "R":
        return "hR"
    return letter + centering


def spg_dataset(structure: Structure, symprec: float = 0.05):
    cell = (
        np.array(structure.lattice.matrix, dtype=float),
        np.array([site.frac_coords for site in structure], dtype=float),
        np.array([site.species.elements[0].Z for site in structure], dtype=int),
    )
    ds = spglib.get_symmetry_dataset(cell, symprec=symprec)
    if ds is None:
        raise RuntimeError(f"spglib 在 symprec={symprec} Å 下无法判定对称性（结构对容差过于敏感）")
    return ds


def spg_info(structure: Structure, symprec: float = 0.05) -> dict:
    ds = spg_dataset(structure, symprec)
    # 常规/标准胞里的对称操作数（来自 spglib 数据库，便于跨 setting 比较）：
    # 例如 #139 → 32，Im-3m #229 → 96，Fm-3m #225 → 192。
    std_sym = spglib.get_symmetry_from_database(int(ds.hall_number))
    std_rots = np.array(std_sym["rotations"], dtype=int)
    pg_order = len({tuple(r.ravel()) for r in std_rots})
    return {
        "sg_number": int(ds.number),
        "sg_symbol": str(ds.international),
        "point_group": str(ds.pointgroup),
        "pointgroup_order": pg_order,
        "n_symops_conv": len(std_rots),
        "n_symops_input": len(ds.rotations),
        "hall_number": int(ds.hall_number),
        "bravais": bravais_type(ds),
        "centering": str(ds.international).replace(" ", "")[0],
        "wyckoff": list(ds.wyckoffs),
        "transformation_matrix": np.round(np.array(ds.transformation_matrix, dtype=float), 5).tolist(),
        "std_lattice": np.round(np.array(ds.std_lattice, dtype=float), 5).tolist(),
        "primitive_lattice": np.round(np.array(ds.primitive_lattice, dtype=float), 5).tolist(),
        "ds": ds,
    }


def volume_per_atom(structure: Structure) -> float:
    return structure.volume / len(structure)


def min_distance(structure: Structure) -> float:
    """最小原子间距（含周期像）。"""
    dm = structure.distance_matrix
    np.fill_diagonal(dm, np.inf)
    return float(np.min(dm))


def lattice_params(structure: Structure) -> dict:
    lat = structure.lattice
    return {"a": lat.a, "b": lat.b, "c": lat.c,
            "alpha": lat.alpha, "beta": lat.beta, "gamma": lat.gamma}


# ---------------------------------------------------------------- 构造
def bct(r: float, a_t: float = 2.556, species: str = "Cu") -> Structure:
    """Bain 路径的 bct 胞：2 原子基元 (0,0,0)+(1/2,1/2,1/2)，a=b=a_t, c=r*a_t。

    r=1.0 → bcc（cI）；r=√2 → fcc（cF）；其它 → tI（I4/mmm）。
    """
    lat = Lattice.tetragonal(a_t, r * a_t)
    return Structure(lat, [species, species], [[0, 0, 0], [0.5, 0.5, 0.5]])


def rhombohedral(alpha_deg: float, a: float = 3.0, species: str = "Cu") -> Structure:
    """菱方原胞（a=b=c, α=β=γ）；α=60°→fcc，α=90°→sc，α=109.4712°→bcc。"""
    lat = Lattice.rhombohedral(a, alpha_deg)
    return Structure(lat, [species], [[0, 0, 0]])


def conventional_fcc(a_c: float = 3.615, species: str = "Cu") -> Structure:
    lat = Lattice.cubic(a_c)
    return Structure(lat, [species] * 4,
                     [[0, 0, 0], [0, .5, .5], [.5, 0, .5], [.5, .5, 0]])


def conventional_bcc(a_c: float = 2.556, species: str = "Cu") -> Structure:
    lat = Lattice.cubic(a_c)
    return Structure(lat, [species] * 2, [[0, 0, 0], [.5, .5, .5]])


# ---------------------------------------------------------------- I/O
def write_csv(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def setup_matplotlib():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    return plt
