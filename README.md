# CIF 处理工作台（cifkit）— Project5

把「从数据库下载下来的裸 CIF」变成「能直接喂给 VASP / QE / CP2K / LAMMPS 的结构」：
**选型下载 → 拓扑核实 → 修复（补氢 / 无序占位 / 近邻）→ 标准胞 → 超胞 → (hkl) 切面 → 真空层 → 导出 → 校验 → 入库**。

技能组在 `D:\agent-library\catalog\cif-*`（router 可命中）；本仓库是引擎、脚本与验收现场。

---

## 一条管线跑通（验收 demo）

用户原话：

> 帮我下载典型的RCSR为sod的mof，需要碳上补充氢，创建一个2x2x1的超胞（Supercell），沿(111)面切出表面，并加上15Å的真空层，导出为计算化学软件使用的格式。

```powershell
$PY = 'D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe'
$env:PYTHONIOENCODING='utf-8'
Set-Location 'D:\Dev\Project5-skill-cif'

# 首次在新机器上：准备 CoRE MOF 2024 缓存（Zenodo，~45 MB，幂等）
& $PY scripts\bootstrap_data.py

# 一条管线（缓存热时约 10 s）
& $PY -m cifkit pipeline "帮我下载典型的RCSR为sod的mof，需要碳上补充氢，创建一个2x2x1的超胞（Supercell），沿(111)面切出表面，并加上15Å的真空层，导出为计算化学软件使用的格式。" --outdir runs\demo_sod_zif8 --format vasp,cif,xyz --ingest

# 独立复核（不信自报，直接从产物结构验 8 条标准）
& $PY scripts\verify_demo.py runs\demo_sod_zif8
```

实测结果（`runs/demo_sod_zif8/`，2026-11-05 本机）：

| 步骤 | 结果 |
|---|---|
| 来源 | CoRE MOF 2024（Zenodo 15055758，CC-BY-4.0）`SI/NCR/both/ja204757x_si_002_ASR_pacman.cif`；DOI 10.1021/ja204757x；sha256 记录在 manifest |
| 拓扑 | `sod`，证据 `verified`：underlying net 签名（4-配位；配位序列 4,10,20,34,52,74,100,130；4/6/8 元环分布）与 CoRE ASR `2015[Zn][sod]3[ASR]1` 一致 |
| 补氢 | 0 H → **+120 H**（每 mIm 5 个 H；环 C–H 平面内、甲基 109.5°），156 → **276 原子**，C 96/96 四配位，无 N–H |
| 标准化 | 常规胞 I-43m，276 原子（整数倍守卫，不翻倍） |
| (111) slab | 552 原子，面内 a=b≈24.08 Å，slab 厚≈19.28 Å |
| 2x2x1 | 作为 **slab 面内 2×2** 重复 → **2208 原子**，面内 a=b≈48.17 Å |
| 真空 15 Å | c⊥ = 34.283 Å；垂直真空实测 **15.000 Å**（另有最小周期像距离 15.240 Å） |
| 导出 | `structure.vasp` 2208 原子（读回一致）、`structure.cif`、`structure.xyz` |
| 校验 | 12 项通过（`dangling_bonds` 是表面必然的 WARN） |
| 独立验收 | **8/8 PASS**（`scripts/verify_demo.py`） |
| 产物 | `raw.cif` `repaired.cif` `standardized.cif` `slab.cif` `final.cif` `structure.vasp/.cif/.xyz` `preview.png` `report.md` `manifest.json` |

`2x2x1` 的语义：默认 **`--surface-frame slab`**（物理正确：先在体相常规胞上切 (111)，再做面内 2×2、沿法向 ×1）；
`--surface-frame cell` 是字面语义（先 2x2x1 超胞再切该胞的 (111)，取向不是立方 (111)），仅作对照，见 `docs/GEOM.md`。

---

## 能力矩阵

| 子命令 | 作用 | 示例 |
|---|---|---|
| `pipeline` | 一条管线，产出 manifest/report/预览 | 见上 |
| `fetch` | 按 RCSR 拓扑 / 名称 / id 从 CoRE MOF 2024、COD、本地检索并落盘 | `fetch --topology sod --raw --limit 5` |
| `repair` | 补氢 / 无序占位 / 过近原子 / 价态检查 | `repair raw.cif -o fixed.cif --add-h --json` |
| `geom` | 标准化 / 超胞 / (hkl) slab / 真空 / 金属簇-SBU | `geom s.cif -o slab.cif --standardize --surface 1 1 1 --supercell 2 2 1 --vacuum 15` |
| `export` | VASP/CIF/XYZ/LAMMPS/QE/CP2K/XSF（7 种，写出后尽量读回校验） | `export slab.cif --format vasp,cif -o out` |
| `validate` | 结构校验（原子数、最近邻、真空、悬空键、C 配位…） | `validate final.cif --json` |
| `route` | 一句话 → TaskSpec + 计划（不执行） | `route "…"`；退出码 2 = 缺少结构信息 |
| `formats` / `selftest` | 格式列表 / 环境自检 | |

环境：`.venv`（`--system-site-packages`）内含 `pymatgen`、`ase`、`openbabel-wheel`、`pytest`，继承全局 `rdkit`/`numpy`/`scipy`/`networkx`/`matplotlib`；`cifkit` 已 editable 安装，任意目录可 `python -m cifkit`。

---

## 关键设计

- **诚实溯源**：每次运行写 `manifest.json`（查询、来源 URL/DOI/sha256、每步耗时、校验数字、工具版本），`--ingest` 额外入库到 `library/`（`index.jsonl` + 每 run 目录）。
- **拓扑证据分级**：`metadata`（数据库列）→ `verified`（结构比对：金属节点配位、2–8 层配位序列、4–8 元环分布）→ `curated`（文献样例 + 复核）→ `unknown`/`mismatch`。不把“论文标题/名字”当已验证。
- **补氢**：周期键感知 + 金属配位约束 → 每个有机片段 RDKit capping + `AddHs(addCoords=True)` → 坐标映射回晶胞；纯几何 VSEPR 兜底；补后自检 C 价态、H–H/H–重原子最小距离。局限见 `docs/REPAIR.md`。
- **切面/真空**：`SlabGenerator` 多终止面候选按「悬空键 + 化学计量偏差」打分；真空层按**垂直定义**精确设置（`c⊥ = slab厚 + target`），同时报告最小周期像距离。
- **失败也写 manifest**：任一步失败仍产出 `manifest.json`/`report.md`（`ok: false`, `failed_step`），便于复盘。
- **离线优先**：索引与 CIF 全部走 `_cache/`；`bootstrap_data.py` 负责新机器首次下载。

---

## 测试与复现

```powershell
& $PY -m pytest tests -q            # 119 passed（含 demo 端到端；需要 _cache）
& $PY -m cifkit selftest --verbose  # 离线自检 7/7
& $PY scripts\verify_demo.py runs\demo_sod_zif8   # 8/8
```

测试分布：export 20 / geom 34 / pipeline 3 / repair 12 / sources 17 / spec 6 / topology 15 / validate 12。

---

## 技能组（agent-library）

| skill | 作用 |
|---|---|
| `catalog/cif-workbench` | 总入口：一条管线 |
| `catalog/cif-fetch` | 数据库选型 + 下载 + 拓扑证据 |
| `catalog/cif-repair` | 补氢 / 无序 / 近邻 / 价态 |
| `catalog/cif-geometry` | 超胞 / 切面 / 真空 / 金属簇 |
| `catalog/cif-export` | 格式导出与读回验证 |

- 原句路由：`intent=cif-structure-pipeline`，第一候选 `cif-workbench`（修复前曾被误判为 `install-app`）。
- `eval_router --all`：正例 73/73（intent/skill top1/top5 100%），负例 0/25 误报，槽位 11/11；`ci.py --fast` 通过。

---

## 局限（先说清楚）

- 补氢针对有机配体/常规 MOF（C/N/O/S）；金属氢化物、自由基、纯无机周期体系会如实给 warning 或走几何兜底，见 `docs/REPAIR.md` §局限。
- 拓扑比对以单个金属原子为节点，未做 Zr6 等 SBU 收缩；参考取 CoRE 同拓扑 ASR 记录。
- 切面终止面是几何启发式（悬空键 + 化学计量偏差），不是表面能计算；表面有悬空键是正常现象。
- 导出 7 种格式；`gaussian/orca/abacus` 未实现，会明确报 unsupported（不会静默写错）。
- CoRE 2024 的 NCR 原始 CIF 只有 curated 样例带 DOI；其余 raw 记录 `doi=None` 并在 notes 说明。

## 文档索引

- [docs/DESIGN.md](docs/DESIGN.md) — 目标、架构、冻结接口、数据事实、验收数字
- [docs/PIPELINE.md](docs/PIPELINE.md) — 管线逐步验收
- [docs/SOURCES.md](docs/SOURCES.md) — 数据源、缓存、拓扑判定算法与证据分级
- [docs/REPAIR.md](docs/REPAIR.md) — 补氢/无序/近邻算法与局限
- [docs/GEOM.md](docs/GEOM.md) — 标准化/超胞/切面/真空/簇的实测与坑
- [docs/EXPORT.md](docs/EXPORT.md) — 导出格式、QE 赝势、读回校验
- [docs/SKILLS.md](docs/SKILLS.md) — 技能组索引、命令对应表、路由证据
- `D:\agent-library\catalog\cif-*/SKILL.md` — 技能正文（唯一真源）
