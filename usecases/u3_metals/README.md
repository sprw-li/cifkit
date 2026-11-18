# 纯金属晶格数据 + 最密面表面能输入文件（`usecases/u3_metals/`）

用户需求：“逐一导出 100 种纯金属的晶格模拟数据，以及最密面的表面能模拟需要用到的文件”。

周期表中 pymatgen 判定为金属的元素共 **87 种**（“100 种”是近似说法）。本交付：

| 指标 | 数值 |
|---|---|
| 周期表金属总数（`pymatgen.core.Element.is_metal`） | **87** |
| 成功导出（bulk + 最密面 slab + 输入模板） | **69** |
| 未导出（missing，附原因，**未编造**） | **18** |
| 数据来源：ASE 内置 Kittel 表 / AFLOW（客户端 SG 过滤）/ COD | 58 / 7 / 4 |
| 结构置信度：high / medium / uncertain | 58 / 7 / 4 |
| 最密面判定：教科书原型规则 / 平面原子密度算法（其中低置信度 flag） | 58 / 11（1） |
| 抽查 slab 数目 / 失败数 | **19 / 0** |

> 类金属 B、Si、Ge、As、Sb、Te、Po 不属于金属，**不在 87 种内**，本交付不打包（避免把类金属混称纯金属）。

---

## 1. 目录结构

```
usecases/u3_metals/
├── README.md                     本文件
├── metals_summary.csv            汇总表：晶格 + 最密面 + slab 全部字段（69 行）
├── lattice.csv                   晶格表（69 行，任务要求的字段在前）
├── metals_kit.zip                完整工具包（bulk/slab/POSCAR/INCAR/KPOINTS/CSV/README）
├── elements/<El>/                每个元素一个目录（共 **69** 个）
│   ├── bulk.cif                  常规胞（conventional）CIF
│   ├── bulk_POSCAR               常规胞 VASP POSCAR（VASP5，含元素行）
│   ├── slab.cif                  最密面 slab + 15 Å 真空 CIF
│   ├── slab_POSCAR               同上，VASP POSCAR
│   ├── lattice.csv               该元素一行的晶格表
│   ├── INCAR                     该 slab 的静态计算模板（已填 N_slab、A、面指数）
│   └── KPOINTS                    该 slab 的 Γ-centered k 网格（kz=1）
├── surface_energy/
│   ├── INCAR                     全局静态计算模板（注释说明参数与用途）
│   ├── KPOINTS                   通用模板（各元素目录里有更合适的）
│   └── README.md                 E_surf 公式、工作流、注意事项
├── data/
│   ├── run_report.csv            全部 **87** 个元素的 ok/failed + 原因
│   ├── slab_validation.csv       19 个 slab 的独立复验结果
│   ├── records.json              每个元素的完整记录（断点续跑用）
│   ├── failures.json             18 个失败元素及原因
│   ├── summary_stats.json        README 中数字的机器可读版本
│   ├── aflow_lib1_candidates.json  缓存的 AFLUX LIB1 全量候选（探测脚本产物）
│   └── cod_cache/                COD CIF 缓存（不入 zip）
└── scripts/
    ├── groundstates.py           87 元素基态结构解析（ASE → AFLOW → COD 三层）
    ├── surface_planes.py         最密面判定（原型规则 + 平面原子密度算法）
    ├── export_metals.py          主脚本（逐元素导出，可断点续跑）
    ├── finalize_metals.py        汇总 CSV / 复验 / 模板 / 打包
    ├── verify_deliverables.py    验收自检脚本
    └── probe_aflow_lib1.py       AFLUX LIB1 候选缓存生成（可选）
```

---

## 2. 数据来源与结构选型（为什么不用 “AFLOW 最低 energy_atom”）

最初方案是取 AFLOW LIB1 中 `energy_atom` 最低的条目，但实测它**不能可靠给出元素基态**
（Sn 被选成金刚石 cF8、Hg 被选成 bcc、Ga 选成 tI2、In 选成 hP3、Mn 选成 hP2、Sm 选成 hP2…，
因为 LIB1 混用多种 PAW 势，SCAN/LDA 的绝对能量不可比）。最终采用**分层策略**：

**Tier 1 — ASE 内置 Kittel 参考表（58 个元素，`structure_confidence = high`）**

`ase.data.reference_states` + `ase.build.bulk` 构建 bcc / fcc / hcp / bct / rhombohedral 原胞，
再取 pymatgen 常规胞并用 spglib 复核空间群与常规胞原子数，全部通过：

| 原型 | 元素 | SG |
|---|---|---|
| bcc (A2) | Li Na K V Cr Fe Rb Nb Mo Cs Ba Eu Ta W | 229 |
| fcc (A1) | Al Ca Ni Cu Sr Rh Pd Ag Ce Yb Ir Pt Au Pb Ac Th | 225 |
| hcp (A3) | Be Mg Sc Ti Co Zn Y Zr Tc Ru Cd La Pr Nd Gd Tb Dy Ho Er Tm Lu Hf Re Os Tl | 194 |
| bct In (A6) | In（tI2） | 139 |
| bct β-Sn (A5) | Sn（tI4，含 2 原子基元） | 141 |
| 菱方 α-Hg (A10) | Hg（hR1 菱方原胞 / hR3 六方常规胞） | 166 |

晶格常数取 ASE/Kittel 实验值（如 Fe a=2.87、Cu a=3.61、Mg a=3.21 c/a=1.624、In a=3.2456 c/a=1.5217、Sn a=5.82 c/a=0.546）。

**Tier 2 — AFLOW LIB1 客户端过滤（7 个元素，`medium`/`uncertain`）**

AFLUX 会**静默忽略** `spacegroup_relax(...)` 过滤（实测），因此改为：查全量 LIB1 →
客户端按**期望空间群**过滤 → 优先匹配期望 Pearson → 再取能量最低 → spglib 复核。
AFLOW CIF 里的 `_atom_site_type_symbol` 是 PAW 势名（如 `potpaw_PBE.54/Fe_sv`），
cifkit 已修复解析；脚本另外做独立的纯元素校验。

| 元素 | 期望 | 结果 |
|---|---|---|
| Mn | α-Mn cI58 (#217) | ✓ cI58 |
| Ga | α-Ga oS8 (#64) | ✓ oS8 |
| Sm | Sm-type hR9 (#166) | ✓ hR9 |
| Bi | α-Bi A7 hR2 primitive (#166) | ✓ hR2 primitive / hR6 hex cell |
| Pa | α-Pa tI2 (#139) | ✓（LIB1 无 → ICSD） |
| U | α-U oC4 (#63) | ✓（LIB1 无 → ICSD） |
| Pm | 预测 hcp hP2 (#194) | ✓ hP2，`medium`（无 ASE 条目，AFLOW 结构） |

**Tier 3 — COD 实验结构（4 个元素，`uncertain`）**

AFLOW LIB1/ICSD 都没有的，最后到 Crystallography Open Database 查纯元素条目，
按期望空间群 + 纯元素 + spglib 复核后使用：

| 元素 | 期望 | COD 条目 |
|---|---|---|
| Ra | bcc cI2 (#229) | 1509139 (1968) |
| Np | α-Np oP8 Pnma (#62) | 9008585 |
| Pu | α-Pu mP16 P2₁/m (#11) | 1525989 (2001) |
| Am | dhcp hP4 (#194) | 9008524 (1963) |

---

## 3. 缺失元素（18 个，missing，未编造）

| 元素 | 原因 |
|---|---|
| Cm, Bk, Cf, Es | 无 ASE 参考；AFLOW LIB1/LIB2/LIB3/ICSD 实测均无条目；COD 无纯元素条目 |
| Fr | 无 ASE 参考；AFLOW 各目录无条目；COD 无条目 |
| Fm, Md, No, Lr, Rf, Db, Sg, Bh, Hs, Mt, Ds, Rg, Cn | 无 ASE 参考；实验晶体结构未确立（部分元素仅有极少量原子被合成），任何数据库都没有可靠结构 → 判为 missing |

复现的失败原因逐条写在 `data/run_report.csv` 与 `data/failures.json`。

---

## 4. 最密面判定规则

优先用原型常识（`plane_method = prototype_rule`，`plane_confidence = textbook`）：

| SG | 原型 | 最密面 |
|---|---|---|
| 225 | fcc (A1) | **(111)** |
| 229 | bcc (A2) | **(110)** |
| 194 | hcp (A3) / dhcp (hP4) | **(0001)** |
| 221 | sc | (100) |
| 227 | diamond | (111) |

其余结构（Mn/Ga/U/Np/Pu/Sm/Bi/Hg/In/Sn/Pa 等，`plane_method = planar_density`，
`plane_confidence = computed`）用**低指数面的平面原子密度**自动选：

对每个约化后的 (hkl)（|h|,|k|,|l| ≤ 2，含 (0001)）：法向 **n**、面间距 d、
平面内最短两个独立格矢 b₁,b₂（A₂D = |b₁×b₂|）；按 `(r·n) mod d`（容差 0.30 Å）
把原子分成“原子面”，每面上把投影坐标约化到 (b₁,b₂) 胞内去重，得每个 2D 胞的原子数 Nₖ；
取 `ρ(hkl) = maxₖ Nₖ / A₂D`，取 ρ 最大的面。该算法在已知原型上复现了
fcc(111)、bcc(110)、hcp(0001) 的教科书结果（见 `data/slab_validation.csv` 与 §6）。
若 ρ 超过单原子面密排上限 `2/(√3·d_NN²)`，说明该面强起伏、原子面无法分辨，标 `plane_confidence = low`。

六方晶胞的面指数用 4 指数 Miller-Bravais 记法（如 `(0001)`、`(10-1-2)`）。

**已核验**（任务要求）：

| 元素 | 期望 | 实测 `densest_plane` | slab 原子数 | 真空 |
|---|---|---|---|---|
| Fe | (110) | **(110)** | 12 | 15.0 Å |
| Cu | (111) | **(111)** | 24 | 15.0 Å |
| Mg | (0001) | **(0001)** | 6 | 15.0 Å |
| Al | (111) | **(111)** | 24 | 15.0 Å |
| W | (110) | **(110)** | 12 | 15.0 Å |

---

## 5. CSV 字段

### `lattice.csv` / `elements/<El>/lattice.csv`
`element, Z, prototype, spacegroup_number, spacegroup_symbol, a, b, c, alpha, beta, gamma,
V_per_atom, source_aurl, source_energy_atom, natoms, structure_type, lattice_source,
structure_confidence, sg_check, pearson_primitive`

* `Z` / `natoms` — 常规胞原子数（纯元素中二者相同）
* `prototype` — 由 spglib 实测 SG + 常规胞原子数计算的 Pearson 符号（`oS` = 单面心，如 α-Ga oS8）
* `sg_check` — spglib 实测空间群号（与期望一致的复核结果）
* `source_aurl` / `source_energy_atom` — AFLOW 条目的 URL 与弛豫 energy_atom；ASE/COD 行留空（不臆造能量）
* `pearson_primitive` — 原胞 Pearson；菱方结构参见 Hg：`hR1`(primitive) / `hR3`(hex 常规胞)
* `lattice_source` — `ASE reference_states (Kittel)` / `AFLOW ... filtered client-side` / `COD ...`
* `structure_confidence` — high / medium / uncertain

### `metals_summary.csv`
`lattice.csv` 全部字段 + `densest_plane, plane_hkl, plane_method, plane_confidence, plane_rho,
interplanar_d, layer_spacing, surface_atoms, slab_atoms, slab_thickness, vacuum_measured,
surface_area, n_atomic_layers, atoms_per_layer, interlayer_spacing, near_neighbor_bulk,
validate_ok, validate_min_distance, validate_duplicate_pairs, status`

### `data/run_report.csv`
`element, status, reason, structure_type, structure_confidence, sg_check, lattice_source,
densest_plane, slab_atoms, vacuum_measured, source_aurl, elapsed_s` — **87 行**，每个元素一条。

---

## 6. 验收 / 自检结果

* `elements/<El>/` 目录数 = `metals_summary.csv` 行数 = `lattice.csv` 行数 = **69**
* `data/run_report.csv` = **87** 行（69 ok + 18 failed，失败均带原因）
* 全部 69 个 slab 的 `vacuum_measured` = **15.0 Å**（`cifkit.geom.make_slab` 精确设真空）
* 抽查 **19** 个 slab（Fe/Cu/Mg/Al/W/Ti/Nb/Ni/Zn/Co/In/Sn/Hg/Sm/Bi/Mn/Ga/U/Pa）：
  从磁盘重新读取 `slab.cif` → `cifkit.validate.validate_structure(spec=TaskSpec(vacuum=15))`：
  **19/19 通过**，真空 ≥ 15 Å、无重合原子（`duplicate_pairs = 0`）、最小原子间距合理；
  明细见 `data/slab_validation.csv`
* `metals_kit.zip` 可解压（`zipfile.testzip()` 校验），含 69 个元素目录 + 表格 + 模板 + 脚本
* 所有 `bulk_POSCAR` / `slab_POSCAR` 用 `pymatgen.Poscar.from_file` 重新解析通过

复验命令：

```powershell
cd <repo>
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe usecases\u3_metals\scripts\verify_deliverables.py
```

---

## 7. 表面能工作流（E_surf）

```
E_surf = (E_slab − N_slab · μ) / (2A),      μ = E_bulk_cell / Z
```

* `E_slab` — `elements/<El>/slab_POSCAR` 的 VASP 总能（eV）
* `E_bulk_cell` — `elements/<El>/bulk_POSCAR` 的 VASP 总能（eV），`Z` = 该常规胞原子数（`lattice.csv`）
* `N_slab` — slab 原子数（`metals_summary.csv` 的 `slab_atoms`）
* `A` — slab 表面积 `|a×b|`（Å²，`surface_area` 列）
* 分母 `2A`：slab 上下两个表面**等价**（对称构造），不要重复计数

流程：

1. **bulk 参考**：对 `bulk_POSCAR` 做静态计算（与 slab 用同一 POTCAR / ENCUT / smearing），
   得到 `E_bulk_cell`，`μ = E_bulk_cell / Z`。
2. **slab**：对 `slab_POSCAR` 做静态计算（`KPOINTS` 的 kz=1；真空 15 Å）。
   若需弛豫，按 `INCAR` 注释把 `NSW/IBRION` 打开，并在 `slab_POSCAR` 用 Selective dynamics
   **固定底部至少两层**（`F F F`）。
3. 代入公式，用 `metals_summary.csv` 的 `slab_atoms` 与 `surface_area`。

`surface_energy/INCAR` 与每个 `elements/<El>/INCAR` 是静态计算模板（注释说明每个参数为什么这么设）；
`surface_energy/README.md` 是同一份工作流的独立说明。

---

## 8. 已知限制 / 未验证项（诚实声明）

1. **没有包含任何 VASP 能量**：本交付是结构 + 输入模板，`E_surf` 数值需要用户自己跑 VASP 得到；
   `bulk.cif` 来自实验晶格常数（ASE/Kittel）或 AFLOW/COD 弛豫/实验结构，**不是**本项目的 DFT 结果。
2. **slab 未弛豫**：`slab_POSCAR` 是理想晶体学切面（`make_slab` 会做终止面打分，纯元素只有一种化学终止），
   真实表面能需要弛豫 + 收敛测试（ENCUT、k 网格、slab 厚度、真空）。
3. **`source_energy_atom` 仅作溯源**：AFLOW 行的弛豫 `energy_atom` 只用于同一空间群/同一 Pearson
   内部排序，**不用于挑基态**；ASE/COD 行该字段为空（不臆造能量）。本交付不含任何 VASP 能量。
4. **最密面算法的不确定项**：非教科书原型用低指数面平面原子密度选面（`plane_method = planar_density`）。
   `plane_confidence = computed` 的元素：Ga (100)、In (01-1)、Sn (010)、Sm (0001)、Hg (01-1-1)、
   Bi (10-1-2)、Pa (110)、U (001)、Np (1-1-2)、Pu (2-1-1)；
   `plane_confidence = low` 的只有 **α-Mn (012)**：其密度 0.3559 atoms/Å² 高于单原子面密排上限
   `2/(√3·d_NN²) = 0.254`（d_NN = 2.135 Å），说明该面强起伏、原子面无法分辨。
   这些面**未必是文献最常研究的表面**（如 Bi 常研究 (0001) 基面、α-Mn/α-Pu 常用低指数面）；
   `metals_summary.csv` 的 `plane_rule` 列保留了前 3 名候选面的密度，便于用户自行覆盖。
   强起伏面的 `atoms_per_layer`（如 Mn 20/29/58/29/96）是“按面间距等分”的近似值，见 `layer_detection` 列。
5. **薄 slab 例外**：Bi (10-1-2) slab 厚度 9.95 Å（< 10 Å）但含 **4 个原子层**，满足“≥3 层”；
   其余 slab 厚度见 `metals_summary.csv`。
6. **大 slab**：α-Mn (012) 232 原子、α-Pu (2-1-1) 192 原子（低对称面 + 12 Å 厚度导致面内胞很大），
   VASP 计算量偏大；如需小胞可自行减少层数或改用更简单的面。
7. **`ISPIN = 2` 对所有元素**：非磁性金属自旋矩会收敛到 0（无害但略慢）。
8. **Hg 的 Pearson 记法**：菱方原胞 1 原子 = `hR1`，六方常规胞 3 原子 = `hR3`；表中 `prototype`
   按“常规胞”约定给 `hR3`，`pearson_primitive` 给 `hR1`；`structure_type` 同时写明两者。
   同理 Sm-type 为 `hR9`（六方常规胞），Bi A7 为 `hR6` / 原胞 `hR2`。
9. **AFLOW/COD 数据是 DFT 弛豫/历史实验值**：U、Pa、Np、Pu、Am、Ra 的 `structure_confidence = uncertain`
   （COD 为 1960–2001 年实验数据；α-Pu 为低温相），用于表面能前建议先做晶格弛豫确认。
10. **未做**：ZPE、van der Waals、偶极修正、表面弛豫能、Wulff 构造、温度/压力相图。

---

## 9. 复现 / 断点续跑

```powershell
cd <repo>
$env:PYTHONIOENCODING='utf-8'

# 全部 87 个元素（已有结果自动跳过；失败元素会重试）
.venv\Scripts\python.exe usecases\u3_metals\scripts\export_metals.py

# 只跑指定元素；--force 强制重算
.venv\Scripts\python.exe usecases\u3_metals\scripts\export_metals.py --elements Fe,Cu,Mg,Al,W
.venv\Scripts\python.exe usecases\u3_metals\scripts\export_metals.py --elements Fe --force

# 汇总 CSV + 19 个 slab 复验 + 模板 + zip
.venv\Scripts\python.exe usecases\u3_metals\scripts\finalize_metals.py --zip

# 验收自检（目录/CSV/zip/关键面指数/真空/复验）
.venv\Scripts\python.exe usecases\u3_metals\scripts\verify_deliverables.py
```

断点机制：`data/records.json` 记录每个元素的完整结果；重跑时若 `elements/<El>/` 的 7 个必需文件
都在就跳过（输出 `ok_cached`）。AFLOW CIF 由 cifkit 缓存（`_cache/aflow`），COD CIF 缓存在
`data/cod_cache/`，AFLUX 结果缓存在 `data/aflow_lib1_candidates.json`。

---

## 10. 数据来源与许可

* **ASE reference_states**（Kittel《Introduction to Solid State Physics》晶体学表）— ASE LGPL
* **AFLOW** — https://aflow.org/ ，AFLOW usage terms；再分发/发表前请自行确认许可
* **COD** — https://www.crystallography.net/cod/ ，COD 为开放数据（各条目许可不同）
* 计算/解析：pymatgen 2026.10、spglib 2.8、ASE 3.29、cifkit（本项目）

本目录只写 `usecases/u3_metals/`，未修改 `cifkit/` 或其它 usecase，未做 git commit。
