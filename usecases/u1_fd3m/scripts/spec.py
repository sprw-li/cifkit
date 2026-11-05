"""Fd-3m 典例：数据源规格（COD 为主，AFLOW 补 1 条）。

每个条目记录：教学用的理想化学式、来源、检索方式、用作图规则的近邻截断。
实际空间群一律由 ``make_figure.py`` 用 spglib 复核，不信任数据库的 ``sg`` 字段。

``bonds``：3D 显示用的 (元素A, 元素B, 截断 Å) 规则，仅用于画键，不参与对称性判定。
``polyhedra``：画半透明配位多面体的中心元素 / 配位元素 / 截断（Å）。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # usecases/u1_fd3m
DATA = ROOT / "data"
STRUCT_DIR = DATA / "structures"
FIG_DIR = ROOT / "figures"
PROVENANCE_JSON = DATA / "provenance.json"
EXAMPLES_CSV = DATA / "examples.csv"
FIGURE_PNG = FIG_DIR / "fd3m_examples.png"

#: 全部条目都要求 spglib(number=227, pointgroup=m-3m)。
EXAMPLES = [
    dict(
        key="diamond_C",
        formula="C",
        name="金刚石 diamond",
        source="COD",
        cod_id="9008564",
        search="text=diamond → 过滤 formula=C 且 sg 含 'F d -3 m'",
        url="https://www.crystallography.net/cod/9008564.cif",
        why="Fd-3m 的原型：C 全占 8a，两套 fcc 沿体对角线错开 1/4，构成四面体 sp3 网络",
        bonds=[("C", "C", 1.90)],
        polyhedra=dict(center="C", ligand="C", cut=1.90, max_poly=2),
        reps=2,
        view=(22, 35),
    ),
    dict(
        key="silicon",
        formula="Si",
        name="硅 silicon",
        source="COD",
        cod_id="9008565",
        search="text=silicon → 过滤 formula=Si 且 sg 含 'F d -3 m'",
        url="https://www.crystallography.net/cod/9008565.cif",
        why="同金刚石型、键长与晶格更大：同一 Wyckoff 位在不同尺度下的同一对称性",
        bonds=[("Si", "Si", 2.55)],
        polyhedra=dict(center="Si", ligand="Si", cut=2.55, max_poly=2),
        reps=2,
        view=(22, 35),
    ),
    dict(
        key="spinel_MgAl2O4",
        formula="MgAl2O4",
        name="尖晶石 spinel",
        source="COD",
        cod_id="9001364",
        search="text=MgAl2O4 → 过滤 formula=Al2 Mg O4 且 sg 含 'F d -3 m'",
        url="https://www.crystallography.net/cod/9001364.cif",
        why="正尖晶石：Mg 占 8a 四面体、Al 占 16d 八面体、O 占 32e —— Fd-3m 最经典的三位点组合",
        bonds=[("Mg", "O", 2.25), ("Al", "O", 2.15)],
        polyhedra=dict(center=["Mg", "Al"], ligand="O", cut=2.25, max_poly=24),
        reps=1,
        view=(24, 40),
    ),
    dict(
        key="magnetite_Fe3O4",
        formula="Fe3O4",
        name="磁铁矿 magnetite",
        source="COD",
        cod_id="9005813",
        search="text=Fe3O4 / magnetite → 过滤 formula=Fe3 O4 且 sg 含 'F d -3 m'",
        url="https://www.crystallography.net/cod/9005813.cif",
        why="反尖晶石：同一元素 Fe 同时占 8a(四面体) 与 16d(八面体)，展示 Fd-3m 的两种阳离子位",
        bonds=[("Fe", "O", 2.30)],
        polyhedra=dict(center="Fe", ligand="O", cut=2.30, max_poly=24),
        reps=1,
        view=(24, 40),
    ),
    dict(
        key="pyrochlore_Y2Ti2O7",
        formula="Y2Ti2O7",
        name="烧绿石 pyrochlore",
        source="COD",
        cod_id="1559965",
        search="text=Y2Ti2O7 → 唯一命中，sg 含 'F d -3 m'",
        url="https://www.crystallography.net/cod/1559965.cif",
        why="A2B2O7 烧绿石：Y 16d、Ti 16c、O 48f、O' 8b —— 与尖晶石不同的 Fd-3m 占位组合",
        bonds=[("Y", "O", 2.65), ("Ti", "O", 2.20)],
        polyhedra=dict(center="Ti", ligand="O", cut=2.20, max_poly=16),
        reps=1,
        view=(20, 35),
    ),
    dict(
        key="LiTi2O4",
        formula="LiTi2O4",
        name="锂钛尖晶石（超导）",
        source="AFLOW",
        aurl="aflowlib.duke.edu:AFLOWDATA/ICSD_WEB/FCC/Li1O4Ti2_ICSD_81329",
        search="AFLUX: species(Li,Ti,O),nspecies(3),spacegroup_relax(227*)",
        url="https://aflowlib.duke.edu/AFLOWDATA/ICSD_WEB/FCC/Li1O4Ti2_ICSD_81329/Li1O4Ti2_ICSD_81329.cif",
        why="尖晶石型氧化物超导体：Li 8a 四面体 + Ti 16d 八面体；原始 CIF 是 α=60° 菱方原胞",
        bonds=[("Li", "O", 2.25), ("Ti", "O", 2.15)],
        polyhedra=dict(center=["Li", "Ti"], ligand="O", cut=2.25, max_poly=24),
        reps=1,
        view=(24, 40),
    ),
]

#: 需要的元素显示颜色（CPK 风格，浅色背景下清晰）。
ELEMENT_COLORS = {
    "C": "#3b3b3b",
    "Si": "#c8a26a",
    "Mg": "#3fbf5f",
    "Al": "#7f9ac9",
    "O": "#e03a3a",
    "Fe": "#d97b2b",
    "Y": "#2fb3a3",
    "Ti": "#8a8fd8",
    "Li": "#b45fd0",
}

ELEMENT_RADII = {  # 显示半径（Å），仅用于绘图，非物理量
    "C": 0.30,
    "Si": 0.37,
    "Mg": 0.42,
    "Al": 0.37,
    "O": 0.26,
    "Fe": 0.40,
    "Y": 0.48,
    "Ti": 0.40,
    "Li": 0.42,
}
