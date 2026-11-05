# 应用实例（第 5 轮）：4 个真实需求的可交付成果

> 这 4 个用例是对 CIF 工作台的**超出单条 pipeline 的能力测试**：点群教学图、布拉维点阵对称性分析、
> 纯金属批量导出+表面能输入、Fe-C 计算套件。每项都有真实数据来源、可复跑脚本、独立验证与诚实局限。

| # | 用户原话 | 交付目录 | 核心产物 | 数据来源 |
|---|---|---|---|---|
| 1 | 我需要向学生们讲解 Fd3m 点群的性质，帮我找一些典例，排成 png | [u1_fd3m](u1_fd3m/) | 6 个真实 Fd-3m 典例教学图 PNG（3740×2822）+ 讲稿 README + CSV | COD ×5 + AFLOW/ICSD ×1 |
| 2 | 对比 cF 与 tI 的关系，探究 14 种布拉维点阵的对称性等效与退化 | [u2_bravais](u2_bravais/) | Bain 路径 CSV/PNG、14 种点阵表、12 组等价实测、report.md | pymatgen + spglib 本地计算 |
| 3 | 帮我逐一导出 100 种纯金属的晶格模拟数据，以及最密面的表面能模拟需要用到的文件 | [u3_metals](u3_metals/) | 69 种金属 × bulk/slab/POSCAR/INCAR/KPOINTS + summary.csv + kit.zip | ASE 参考态 58 / AFLOW 7 / COD 4 |
| 4 | 铁碳化合物有哪些种，跟相图的关系是什么？帮我打包一个用于探究这个问题的计算套件 | [u4_fec](u4_fec/) | 7 个 Fe-C 化合物结构、0K 凸包图、相图笔记、VASP 模板、kit.zip | AFLOW LIB2 + ICSD |

## 一键自检

```powershell
$PY = 'D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe'
$env:PYTHONIOENCODING='utf-8'
Set-Location 'D:\Dev\Project5-skill-cif'
& $PY usecases\verify_usecases.py     # Lead 独立验收：4 个用例 22 项检查（spglib/CSV/zip/数值/文件完整性）
```

最近一次结果：**22/22 PASS**（u1 spglib 全部 #227；u2 Bain c/a=√2 → #225、14 种点阵 14/14；
u3 69/69 目录文件齐全、真空全部 15.0 Å；u4 Fe3C +0.0456 eV/atom、hull 仅 Fe/C 端点）。

## 各项结论速览

### 1) Fd-3m 典例（[u1_fd3m/README.md](u1_fd3m/README.md)）
- 6 个真实结构：C 金刚石、Si、MgAl₂O₄ 尖晶石、Fe₃O₄ 磁铁矿、Y₂Ti₂O₇ 烧绿石、LiTi₂O₄ 尖晶石；
  **全部经 spglib 复核为 #227 / 点群 m-3m / 192 个空间群操作**。
- 图：2×3 面板（球棍+配位多面体），每格标注化学式/空间群/点群/晶胞参数；底部信息框给 Fd-3m 性质、
  Wyckoff 位（8a/8b/16c/16d/32e/48f）、与 cF 布拉维点阵的关系。
- 讲稿 README 解释每个例子为什么典型（金刚石 sp³ 网络、尖晶石的 8a+16d 双阳离子位、烧绿石的 16c/16d/48f/8b 组合等）。

### 2) cF vs tI 与 14 种布拉维点阵（[u2_bravais/report.md](u2_bravais/report.md)）
- **Bain 路径**（fcc 出发的体心四方胞，c/a 0.90–1.70，80 个网格点）：中间全部 **tI #139 I4/mmm（4/mmm，阶 16）**；
  精确 c/a=1 → **cI #229 Im-3m**，精确 c/a=√2 → **cF #225 Fm-3m**。
- **结论**：cF 与 tI 的"等价"只是 **c/a=√2 特殊度量下的胞选择等价**，点群不同（m-3m 阶 48 vs 4/mmm 阶 16），
  不是同一点群/空间群；Bain 路径就是对称性从 m-3m 经 4/mmm 退化/恢复的过程。
- 14 种布拉维点阵 14/14 与全息对称空间群一致；12 组等价/退化实测（cF≡tI、cF≡hR(60°)、cI≡hR(109.47°)、
  oC(a=b)→tP、mP(β=90°)→oP 等）；并记录 spglib 容差窗口（0.05 Å 会把 c/a=1.41 误判 cF）。

### 3) 纯金属晶格 + 最密面表面能输入（[u3_metals/README.md](u3_metals/README.md)）
- 周期表金属共 **87 种**（pymatgen `is_metal`；用户说"100 种"是近似）→ **成功导出 69 种**，18 种如实 missing。
- 分层选基态：ASE/Kittel 参考态 58、AFLOW LIB1 客户端 SG 过滤 7、COD 4；置信度 high 58 / medium 7 / uncertain 4。
- 每个元素：`bulk.cif/bulk_POSCAR`（常规胞）+ `slab_POSCAR/slab.cif`（最密面，真空 15.0 Å）
  + `INCAR/KPOINTS` 模板；汇总 `metals_summary.csv`（40+ 字段）与 `run_report.csv`（87 行）。
- 选面：fcc(111)、bcc(110)、hcp(0001)、sc(100)、diamond(111)；复杂结构用平面原子密度算法（标注 plane_confidence）。
- **18 个 missing 的原因**（不编造）：Fr/Cm/Bk/Cf/Es（AFLOW/COD 均无）、Fm–Cn（实验晶体结构未确立）。
- 限制：不含 VASP 能量；slab 为未弛豫理想切面；E_surf=(E_slab − N·μ)/(2A)，模板 README 给了完整流程。

### 4) Fe-C 化合物 + 相图关系 + 计算套件（[u4_fec/README.md](u4_fec/README.md)）
- 7 个结构（CIF+POSCAR，均 spglib 复核）：Fe₃C Pnma oP16、Fe₅C₂(Hägg) C2/c mS28、Fe₇C₃ P6₃mc hP20、
  Fe₂C Pnnm oP6 与 P6/mmm hP3、FeC WC 型 P-6m2 hP2、Fe₂₃C₆ Fm-3m cF116。
- **0 K 凸包**（AFLOW LIB2 的 289 条 Fe-C 形成焓）：hull 上只有 **Fe(bcc) 与 C 两端点** → 0 K DFT 下无稳定 Fe-C 二元化合物；
  - Fe₃C = **+0.0456 eV/atom**，Fe₂C(正交) = **+0.0516**，FeC = **+0.3843 eV/atom**；Hägg/Fe₇C₃/Fe₂₃C₆ 等 ICSD 结构
    无 AFLOW 形成焓，未硬凑进 hull。
- 相图笔记：Fe-Fe₃C 亚稳系关键点（1147 °C 共晶 4.30 wt%C、727 °C 共析 0.76 wt%C）按 Callister/Porter-Easterling 教材值，
  未逐条在线复核的已标注；解释"0 K DFT 全亚稳 vs 相图中 Fe₃C 常见亚稳相"的差异。
- 套件 `fe_c_kit.zip`（87 文件）：结构、CSV、凸包脚本（可离线复跑/替换成自己的 VASP 能量）、VASP 输入模板、README。

## 复现（各自 README 有完整命令）

```powershell
& $PY usecases\u1_fd3m\scripts\fetch_structures.py   # 联网抓取（已缓存则跳过）
& $PY usecases\u1_fd3m\make_figure.py                # 复核 + CSV + PNG
& $PY usecases\u2_bravais\scripts\bain_path.py
& $PY usecases\u2_bravais\scripts\bravais14.py
& $PY usecases\u3_metals\scripts\export_metals.py    # 断点续跑
& $PY usecases\u3_metals\scripts\finalize_metals.py --zip
& $PY usecases\u4_fec\scripts\build_hull.py          # 离线，断言 Fe3C 数值
```

## 诚实性与局限（统一说明）

- 所有结构都记录来源（COD id / AFLOW aurl / ASE 参考态）、sha256（能算的）、spglib 复核结果；
  "未验证/近似"写在各 README，不把教科书结论伪装成本地实测。
- 教材相图温度、部分复杂金属的基态结构（Np/Pu/Am 等）标 uncertain；VASP 模板未真实运行（环境无 VASP/POTCAR）。
- 本目录脚本使用 `usecases/_common/aflow_db.py`（AFLUX 客户端）；AFLOW CIF 的 PAW 势名归一化已在
  `cifkit/sources/aflow.py::sanitize_aflow_cif` 修复（否则元素会被误解析）。

## 目录

```text
usecases/
  _common/{aflow_db.py, element_reference.py}   # 共享 helper（Lead 维护）
  verify_usecases.py                             # 独立验收（22 项）
  u1_fd3m/{README.md, make_figure.py, scripts/, data/, figures/}
  u2_bravais/{README.md, report.md, scripts/, data/, figures/}
  u3_metals/{README.md, metals_summary.csv, metals_kit.zip, elements/, surface_energy/, data/, scripts/}
  u4_fec/{README.md, fe_c_kit.zip, structures/, data/, figures/, vasp_inputs/, scripts/, docs/}
```
