# Fe–C 计算套件（u4_fec）：铁碳化合物清单 + 0 K 凸包 + 相图关系

> 回答的问题：**"铁碳化合物有哪些种，跟相图的关系是什么？"**
>
> 本套件把三样东西打包在一起：
> 1. **7 个 Fe–C 碳化物结构**（CIF + POSCAR，spglib 复核空间群，带来源与 sha256）；
> 2. **0 K 凸包**：用 AFLOW LIB2 的形成焓算出的 Fe–C 二元 convex hull（CSV + 图）；
> 3. **相图笔记 + VASP 输入模板**：把 hull 的结果和 Fe–Fe₃C 亚稳相图对起来，
>    并给出"自己重算"所需的 VASP 模板与流程。

**重要声明：本套件里的能量数据（`data/aflow_fe_c_energies.csv`）是 AFLOW 数据库
（LIB2）中别人已经算好的 PBE DFT 结果，不是本次在本地新算的。**
本套件没有跑任何 DFT；`vasp_inputs/` 只是让你可以自己算的模板。

---

## 1. 五条结论（都能在 `data/*.csv` 里复现）

1. **0 K DFT 下 Fe–C 没有稳定的二元化合物。** 凸包就是 Fe（0 at%C）到 C
   （100 at%C）之间的零线；所有碳化物都在 hull 之上（亚稳）。
2. **Fe₃C（渗碳体，Pnma #62, oP16）只高出 hull +0.0456 eV/atom**
   ——AFLOW LIB2 中 25 at%C 处最低的条目（C4Fe12, prototype 180）。
   与文献常见的 ~+0.05 eV/atom 量级一致。
3. **正交 Fe₂C（Pnnm #58, oP6）几乎与渗碳体简并：+0.0516 eV/atom**
   （LIB2 C2Fe4, prototype 257；与 ICSD 162104 实验结构同型，
   StructureMatcher 拟合 rms ≈ 0.009）。
4. **FeC 在 0 K 下离 hull 很远：+0.38–0.40 eV/atom**（LIB2 最低为 C3Fe3, hP6,
   +0.3843；WC 型 FeC 为 +0.3957），与"常压没有 1:1 Fe–C 稳定化合物"一致。
5. **相图 vs 凸包不是一回事**：Fe–Fe₃C 亚稳相图是有限温度 Gibbs 能
   （727 °C 共析 0.76 wt%C、1147 °C 共晶 4.30 wt%C），Fe₃C 靠**动力学**长期存在
   （石墨形核难），而 0 K hull 显示它相对 Fe+石墨是亚稳的。详见
   [`docs/phase_diagram_notes.md`](docs/phase_diagram_notes.md)。

`data/hull_points.csv` 关键行（`E_above_hull == E_form`，因为 hull 是零线）：

| 相 | at%C | E_form / E_above_hull (eV/atom) | on hull |
|---|---|---|---|
| Fe (bcc, 端点) | 0 | 0 | yes |
| **Fe₃C 渗碳体** (Pnma, oP16) | 25 | **+0.0456** | no (metastable) |
| **Fe₂C 正交** (Pnnm, oP6) | 33.33 | **+0.0516** | no (metastable) |
| **FeC** (50 at%C 最低, hP6) | 50 | **+0.3843** | no (metastable) |
| C (端点) | 100 | 0 | yes |

未进 hull 的相：**Hägg Fe₅C₂**（C2/c, mS28）、**Fe₇C₃**（P6₃mc, hP20）、
**Fe₂C 六方**（P6/mmm, hP3）、**Fe₂₃C₆**（Fm-3m, cF116）——它们在 AFLOW 里是
ICSD 结构条目，`enthalpy_formation_atom = null`，没有可比较的形成焓。
本套件不拿文献值硬凑，见 `docs/phase_diagram_notes.md` §4。

---

## 2. 目录结构

```
usecases/u4_fec/
├── README.md                      <- 本文件
├── fe_c_kit.zip                   <- 整个套件（不含缓存）的打包
├── data/
│   ├── aflow_fe_c_energies.csv    <- AFLOW LIB2 原始行：289 条 Fe-C 二元 DFT 条目（29 个 at%C）
│   ├── fe_c_compounds.csv         <- 7 个化合物的结构清单（空间群/Pearson/natoms/来源/sha256）
│   └── hull_points.csv            <- 凸包输出（每个成分：E_form、hull 能量、E_above_hull、on_hull）
├── structures/
│   ├── <name>.cif                 <- 原始 AFLOW CIF（逐字节保存，可追溯）
│   └── <name>.POSCAR              <- 常规胞（conventional cell, pymatgen SGA, symprec=0.01）
├── figures/
│   └── fe_c_hull.png              <- 0 K 凸包图（左：全部条目；右：成分最低点+标注）
├── docs/
│   └── phase_diagram_notes.md     <- Fe–Fe₃C 相图关键点、碳化物、hull 与相图的关系
├── scripts/
│   ├── fetch_aflow_data.py        <- 网络：重新导出 data/aflow_fe_c_energies.csv
│   ├── fetch_structures.py        <- 网络：下载 CIF、spglib 复核、写 compounds CSV
│   ├── build_hull.py              <- 离线：构建 hull + 出图（可离线复跑，支持 --energies 覆盖）
│   ├── plot_hull.py               <- 离线：单独重画图
│   ├── make_vasp_inputs.py        <- 离线：重新生成 vasp_inputs/ 模板
│   ├── run_vasp_template.ps1      <- Windows 下跑 VASP 的示例驱动
│   └── run_vasp_template.sh       <- Linux/macOS 版本
└── vasp_inputs/
    ├── <name>/POSCAR              <- 结构副本（canonical 在 structures/）
    ├── <name>/INCAR               <- 弛豫模板（ISIF=3, ISPIN=2, ISMEAR=1）
    ├── <name>/INCAR.static        <- 单点模板（NSW=0, ISMEAR=-5）
    ├── <name>/KPOINTS             <- 弛豫 k 网格（pymatgen automatic_density）
    ├── <name>/KPOINTS.static      <- 更密 k 网格（单点用）
    ├── <name>/POTCAR.readme       <- 用哪个 PAW、怎么算 E_form、坑
    ├── ref_fe_bcc/                <- 参考态：铁磁 bcc Fe
    ├── ref_c_graphite/            <- 参考态：石墨
    └── ref_c_diamond/             <- 参考态：金刚石（AFLOW 的 C 参考态是类金刚石结构）
```

`<name>` 共 7 个：`fe3c_cementite`、`fe5c2_hagg`、`fe7c3_hex`、`fe2c_ortho`、
`fe2c_hex`、`fec_wc_type`、`fe23c6`。

---

## 3. 快速开始（离线，无需网络）

```powershell
# 仓库根目录 <repo>
.venv\Scripts\python.exe usecases\u4_fec\scripts\build_hull.py     # -> data/hull_points.csv + figures/fe_c_hull.png
.venv\Scripts\python.exe usecases\u4_fec\scripts\plot_hull.py      # 只重画图
```

`build_hull.py` 会打印 hull 顶点与关键数字，并自检 Fe₃C 的 E_form 与
`data/aflow_fe_c_energies.csv` 中 C4Fe12 的最低值完全一致。

网络步骤（只在需要重新抓数据时跑）：

```powershell
.venv\Scripts\python.exe usecases\u4_fec\scripts\fetch_aflow_data.py    # 289 条 LIB2 条目
.venv\Scripts\python.exe usecases\u4_fec\scripts\fetch_structures.py    # 7 个结构 + sha256
.venv\Scripts\python.exe usecases\u4_fec\scripts\make_vasp_inputs.py    # VASP 模板
```

---

## 4. 数据字典

### `data/aflow_fe_c_energies.csv`（289 行）
`compound, auid, aurl, catalog, spacegroup_relax, pearson_symbol_relax, prototype,
enthalpy_formation_atom, n_Fe, n_C, natoms, x_C, at_percent_C`

* `enthalpy_formation_atom` 单位 **eV/atom**，是 AFLOW 的形成焓
  （相对元素基态，见 §5），**不是**总能；
* 同一个化学式（如 C2Fe4）会有多个条目（不同原型/不同晶胞），hull 只用每个成分的最低值。

### `data/fe_c_compounds.csv`（7 行）
`name, formula, at_percent_C, x_C, spacegroup_number, spacegroup_symbol, pearson_symbol,
prototype, natoms_conventional, natoms_primitive, wyckoff_groups, source_kind, aurl,
cif_url, aflow_cif_sha256, file_sha256_cif, file_sha256_poscar,
aflow_enthalpy_formation_eV_atom, dft_counterpart, note`

* `spacegroup_number`/`spacegroup_symbol` 是 **spglib**（symprec=0.01）对下载结构实测；
* `file_sha256_cif` / `file_sha256_poscar` 是 `structures/` 下两个文件的 sha256，
  本 CSV 与结构文件一起构成可追溯清单；
* `aflow_enthalpy_formation_eV_atom` 为空 = AFLOW 没给焓（ICSD 条目），不进 hull。

### `data/hull_points.csv`
`x_C, at_percent_C, compound, aurl, spacegroup, pearson_symbol, prototype,
energy_formation_eV_per_atom, hull_energy_eV_per_atom, energy_above_hull_eV_per_atom,
on_hull, status, n_entries_at_composition, energy_source`

---

## 5. E_form 的定义与"替换成你自己的 DFT 能量"

AFLOW 的 `enthalpy_formation_atom` 早已是相对元素参考态的形成焓：

```
E_form(Fe_x C_y) = [E_tot(Fe_x C_y) − x·E(Fe_ref) − y·E(C_ref)] / (x + y)   [eV/atom]
```

元素端点因此按定义为 0，0 K hull 就是这些点的下凸包。
若你自己跑 VASP：用 `vasp_inputs/ref_fe_bcc`（铁磁 bcc Fe）和
`vasp_inputs/ref_c_graphite`（石墨）算参考能量（同 POTCAR/ENCUT/k 网格），
再把各碳化物算出的总能按上式换成 `E_form`，写成 CSV：

```csv
x_C,energy_formation_eV_per_atom,comment
0.000000,0.000000,Fe bcc FM (my VASP)
0.250000,0.048000,Fe3C my VASP PBE
0.333333,0.052000,Fe2C Pnnm my VASP PBE
1.000000,0.000000,graphite (my VASP)
```

然后覆盖重算 hull：

```powershell
.venv\Scripts\python.exe usecases\u4_fec\scripts\build_hull.py `
    --energies my_energies.csv --out-png figures\my_hull.png
```

注意：

* **参考态要统一**：AFLOW 的 C 参考是类金刚石 cF8（`ref_c_diamond`）；
  如果你用石墨做参考，E_form 会整体平移约几十 meV/atom，这属于参考态差异，
  不是谁"算错了"。比较 AFLOW 值时请用 diamond 参考，比较实验热力学时用石墨；
* 同一批比较里 ENCUT / POTCAR / 泛函 / 磁性设置必须一致；
* Fe–C 碳化物是铁磁的，非磁性或不同磁序会带来 0.1 eV/atom 量级的误差。

---

## 6. 数据来源、许可与"不是我算的"

* **能量**：AFLOW LIB2（`aflowlib.duke.edu:AFLOWDATA/LIB2_WEB/CFe_pv/...`），
  通过 `https://aflow.org/API/aflux/` 查询，2026-11 抓取。AFLOW 是公开数据库，
  引用请遵循 <https://aflow.org/> 的使用条款；**这些是 AFLOW 作者的 DFT 结果，
  本套件只是下载/整理/可视化，没有重算**。
* **结构**：
  * DFT 条目（Fe₃C、WC 型 FeC）来自 AFLOW LIB2；
  * 实验结构（Fe₅C₂、Fe₇C₃、两种 Fe₂C、Fe₂₃C₆）来自 AFLOW 的 ICSD_WEB 镜像，
    原始数据属于 ICSD（FIZ Karlsruhe），URL 见 `data/fe_c_compounds.csv` 的 `cif_url`；
  * `structures/*.cif` 是抓到的原始 CIF（逐字节），sha256 已记录。
* **参考态结构**（`vasp_inputs/ref_*`）是本套件用标准原型 + 常见实验点阵常数
  本地生成的**弛豫起点**，不是数据库条目。

---

## 7. 局限与未验证项（请一并阅读）

1. **AFLOW 形成焓不是本地计算**，泛函/参数（PBE、Fe_pv 类 PAW）由 AFLOW 决定；
   与你的计算可能有 10–50 meV/atom 的系统差。
2. **Hägg Fe₅C₂、Fe₇C₃、两种实验 Fe₂C、Fe₂₃C₆ 没有 AFLOW 形成焓**，
   本套件只提供结构，**没有**把它们放到 hull 上；它们的相对稳定性未在本套件中量化。
3. **0 K、无熵、只含化学计量相**：hull 不能预测共晶/共析温度，也不能描述 γ/α
   固溶体，所以"没有稳定二元化合物"不等于"相图里没有碳化物"。
4. **AFLOW 元素参考态未核实**：LIB1 中 C 的最低条目是类金刚石 cF8（比 hP4 石墨低
   ~2.5 meV/atom），但 LIB2 形成焓具体用哪条参考无法从接口确认；影响 ≪ 1 meV/atom
   （25 at%C 处），不改变结论。
5. **相图数字**：727 °C/0.76 wt%、1147 °C/4.30 wt%、1493 °C/0.16 wt%、
   2.14/0.022 wt%、770/912/1394/1538 °C 是标准教材值（Callister 9e Ch.9;
   Porter–Easterling Ch.1），本环境无法访问 Wikipedia/NIST PDF 逐条核对；
   Fe₃C 熔点、Fe–石墨稳定系共晶/共析、回火碳化物析出温度区间标为**未核实**，
   详见 `docs/phase_diagram_notes.md`。
6. **VASP 模板未经真实 VASP 运行验证**（构建环境无 VASP、无 POTCAR）；
   ENCUT=520、SIGMA=0.2、k 网格密度只是合理起点，发表前请做收敛测试。
   `run_vasp_template.ps1/.sh` 只是流程示例。
7. **Fe₂C 的 ε/η 命名**在不同文献中不统一；本套件以空间群 + Pearson 符号为准。

---

## 8. 复现清单

| 命令 | 需要网络 | 产物 |
|---|---|---|
| `fetch_aflow_data.py` | 是 | `data/aflow_fe_c_energies.csv` |
| `fetch_structures.py` | 是 | `structures/*`、`data/fe_c_compounds.csv` |
| `build_hull.py` | 否 | `data/hull_points.csv`、`figures/fe_c_hull.png` |
| `plot_hull.py` | 否 | `figures/fe_c_hull.png` |
| `make_vasp_inputs.py` | 否 | `vasp_inputs/**` |

本套件与 `fe_c_kit.zip` 的构建环境：Python 3.14、pymatgen 2026.10、spglib 2.8.0、
matplotlib 3.11.2（Windows）。
