# 技能组：CIF 处理工作台（catalog/cif-*）

> 技能正文唯一真源：`D:\agent-library\catalog\`（本文件只是索引与证据，不复制正文）。
> 引擎入口：`D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe -m cifkit`，命令面冻结于 `docs/DESIGN.md` §6c。

## 1. 技能组一览

| skill | catalog 路径 | 管什么 | 典型触发语 |
|---|---|---|---|
| `cif-workbench` | `catalog/cif-workbench/SKILL.md` | **总入口**：一条 `pipeline` 跑完 下载→拓扑核实→修复→超胞→切面→真空→导出→校验→manifest | “下载典型 sod 的 MOF，补氢，2x2x1 超胞，切 (111)，加 15 Å 真空，导出计算化学格式” |
| `cif-fetch` | `catalog/cif-fetch/SKILL.md` | 数据库选型 + 下载：**六个数据源**（CoRE MOF 2024 离线缓存/拓扑过滤、COD、Materials Project 需 key、AFLOW 免 key、QMOF 本地镜像、本地文件）；`topology_evidence` 四档 | “从 CoRE MOF 下载一个 sod 拓扑的典型结构，要 raw 的 CIF” |
| `cif-repair` | `catalog/cif-repair/SKILL.md` | 补碳上氢 / 无序占位 / 过近原子；读 `RepairReport` | “这个 CIF 缺氢，把缺失的氢补上” |
| `cif-geometry` | `catalog/cif-geometry/SKILL.md` | 标准胞、超胞、`(hkl)` slab、真空层（实测）、金属簇/SBU | “2x2x1 超胞，沿 (111) 切 slab，加 20 Å 真空” |
| `cif-usecases` | `catalog/cif-usecases/SKILL.md` | 进阶应用（`cifkit teach/bravais/metals/fec`）：点群典例教学图 / 布拉维点阵对称性分析 / 纯金属批量+表面能输入 / Fe-C 相图计算套件；另含配套命令 `cifkit surface-energy`（slab/bulk 能量 → E_surf 算术与单位换算） | "Fd3m 点群典例排成 png"、"对比 cF 与 tI"、"100 种纯金属表面能文件"、"铁碳相图套件"、"我有 slab 和 bulk 的能量，算一下表面能" |
| `cif-data` | `catalog/cif-data/SKILL.md` | ML-ready 数据管线：结构特征表（组成/晶格/对称性/配位数/RDF/拓扑）CSV/JSONL；runs/library → dataset | "批量提取结构特征导出 CSV"、"构建 ML 数据集" |
| `cif-export` | `catalog/cif-export/SKILL.md` | **cif → anything**：31 种格式（VASP/CIF/XYZ/EXTXYZ/JSON/PDB/SDF/MOL/LAMMPS/QE/CP2K/GROMACS/Gaussian/ORCA/ABACUS/DFTB/SIESTA/NWChem/AIMS/CASTEP/ABINIT/CRYSTAL/XSF/CFG…）+ 12 种计算软件输入包 | "转成 LAMMPS data"、"生成 CP2K/QE 输入"、"导出 Gaussian gjf" |

五个技能共用同一个 intent：`cif-structure-pipeline`（`category = science`），
在 `catalog/intents.json` 里用 patterns/keywords/examples 覆盖原句与中英文变体；
五个 manifest 都声明 `intents: ["cif-structure-pipeline"]`，由 router 的 `entry_affinity` 按原话证据排序：

- 综合任务（原句）→ 第一候选 **cif-workbench**；
- 只补氢 → `cif-repair` 排第一；
- 只切面/真空 → `cif-geometry` 排第一；
- 只导出格式 → `cif-export` 排第一；
- 只下载/检索 → `cif-fetch` 排第一。

## 2. 技能 ↔ cifkit 命令对应表

| skill | 命令（`$PY` = venv python） | 关键输出 |
|---|---|---|
| cif-workbench | `& $PY -m cifkit pipeline "TEXT" --outdir runs\x --format vasp,cif,xyz --json`；`& $PY -m cifkit pipeline --spec spec.json --outdir runs\x` | `manifest.json`、`report.md`、`structure.vasp` 等 |
| cif-fetch | `& $PY -m cifkit fetch --topology sod --name ZIF-8 --raw --outdir runs\fetch --json` | 记录列表 / `raw.cif` + `source.json` |
| cif-repair | `& $PY -m cifkit repair FILE -o OUT --add-h --json` | `{"report": {...}, "natoms", "formula"}` |
| cif-geometry | `& $PY -m cifkit geom FILE -o OUT --supercell 2 2 1 --surface 1 1 1 --thickness 15 --vacuum 15 --json` | `{natoms, abc, info:{slab, vacuum}}` |
| cif-export | `& $PY -m cifkit export FILE --format vasp,cif,xyz -o DIR --json`；`formats`；`validate` 读回 | `structure.<ext>` 与读回结果（支持 31 种格式，以 `formats` 实测输出为准） |
| cif-usecases | `& $PY -m cifkit teach --spacegroup Fd-3m --outdir runs\uc\fd3m`；`bravais --outdir runs\uc\bravais [--bain-range 0.9:1.7:0.05]`；`metals --outdir runs\uc\metals --elements Fe,Cu,Mg [--zip]`；`fec --outdir runs\uc\fec [--zip]`（实现 `cifkit/usecases_cli.py`；均支持 `--json`） | `figures/fd3m_examples.png`+`data/examples.csv`；Bain/14 点阵 CSV+PNG；`elements/<El>/...`+`metals_summary.csv`；Fe-C 结构+凸包+VASP 模板+`fe_c_kit.zip` |
| cif-usecases（表面能） | `& $PY -m cifkit surface-energy --slab-e E --slab-atoms N --area A --bulk-per-atom e --slab-formula "Zn:8,O:8" --bulk-formula "Zn:4,O:4" --json runs\se.json`（`--json` 是**文件路径**；`--one-surface` 只算单表面） | 表面能 `eV/Å² / meV/Å² / J/m²` + 化学计量校验；能量由用户 DFT 提供，本命令不产能量 |
| 公共 | `& $PY -m cifkit route "TEXT"` / `selftest` / `validate FILE` / `formats` | 解析结果、环境自检、校验报告 |

**2x2x1 语义（技能正文与 `--help` 都以这条为准）**：`pipeline` / `geom` 里同时给 `supercell` 和 `surface` 时，
默认 `surface_frame="slab"`——先从标准化体相切 `(hkl)`，再把 `2x2x1` 作为 slab **面内 2x2** 重复
（demo：修复后 276 → slab base 552 → **2208** 原子）。`--surface-frame cell` 才是字面“先 2x2x1 超胞再切该胞 (111)”，
取向不是立方 (111)，只在报告里作 caveat 对照。只给 `supercell` 不给 `surface` 时才是普通超胞（2x2x1 → 原子数 ×4）。

## 3. 路由链路（实测）

```powershell
$env:PYTHONIOENCODING='utf-8'   # GBK 控制台下不加会 UnicodeEncodeError traceback
py -3 D:\agent-library\router.py route --agent dsh "<用户原句>"
```

2026-11-05 实测（原句）:

```text
query: 帮我下载典型的RCSR为sod的mof，需要碳上补充氢，创建一个2x2x1的超胞（Supercell），沿(111)面切出表面，并加上15Å的真空层，导出为计算化学软件使用的格式。
intent: cif-structure-pipeline
intent category: science
intent candidates: cif-structure-pipeline
1. cif-workbench  [skill/science]  score=82  intent=cif-structure-pipeline
   catalog/cif-workbench/SKILL.md
2. cif-fetch ...
3. cif-export ...
4. cif-geometry ...
5. cif-repair ...
```

修复前的误判：该句曾被判成 `install-app`（因为 `install-app` 的 pattern
`(安装|下载|解压|install|setup).{0,8}(软件|应用|app|程序|包)?` 里分组可选，单独一个“下载”就能拿 +5 强匹配）。
本次修复**不改 router.py**，只动数据：

1. 新增 `cif-structure-pipeline` intent（patterns 覆盖 RCSR/拓扑、CIF/MOF/晶体、补氢、超胞、切面、真空、导出，
   examples 含原句与中英文变体）；
2. `install-app` 增加 `excludes: ["cif|mof|晶体|晶胞|超胞|supercell|slab|真空层|补氢|补充氢|切面|rcsr|poscar|vasp"]`，
   让结构处理类话语不再被软件安装误吞；
3. `domains.json` 的 `science` 域补 `cif/mof/rcsr/晶胞/超胞/supercell/slab/vacuum/补氢/切面/poscar/vasp` 关键词；
4. `catalog/evals/routing.jsonl` 新增 10 条 CIF 正例（原句、中文变体、英文变体、只补氢、只切面、只导出、只下载）。

## 4. 评测证据（`py -3 scripts\eval_router.py --all`，先 `$env:PYTHONIOENCODING='utf-8'`）

```text
cases=96
intent top1: 96/96 = 100.0%
skill top1:  96/96 = 100.0%
skill top5:  96/96 = 100.0%
negatives=25  false-positive=0 (0.0%)  budget=10.0%
slot cases=11  pass=11/11
```

`py -3 scripts\ci.py --fast` → exit code 0（同上述三套评测）。

新增的 10 条正例（都在 `catalog/evals/routing.jsonl`）：

| query | 期望 intent | 期望 top-1 skill |
|---|---|---|
| 原句（sod MOF 全链路） | cif-structure-pipeline | cif-workbench |
| “帮我下载典型的RCSR为sod的MOF，补氢后做2x2x1超胞，沿(111)面切表面，加15Å真空层，导出VASP” | 同上 | cif-workbench |
| “把这个CIF结构补上缺失的氢原子” | 同上 | cif-repair |
| “给这个cif补氢” | 同上 | cif-repair |
| “把晶体沿(111)面切成slab，加20Å真空层” | 同上 | cif-geometry |
| “把这个结构的CIF导出成POSCAR/VASP格式” | 同上 | cif-export |
| “把这个MOF结构导出成VASP格式” | 同上 | cif-export |
| “从CoRE MOF下载一个sod拓扑的典型结构，要raw的CIF” | 同上 | cif-fetch |
| “从 Materials Project 下载 mp-149 的 CIF” | cif-structure-pipeline | cif-fetch（数据源检索类） |
| “从 AFLOW 下载 GaN 的晶体结构” | cif-structure-pipeline | cif-fetch |
| “从 Materials Project 下载 mp-149 的 CIF 然后导出 POSCAR” | cif-structure-pipeline | cif-workbench（下载+导出=管线） |
| “查一下RCSR为sod的MOF有哪些” | 同上 | cif-fetch |
| “download a sod topology MOF CIF, add hydrogens, build a 2x2x1 supercell, cut a (111) surface with 15 A vacuum, export POSCAR” | 同上 | cif-workbench |

## 5. 怎么重跑与维护

```powershell
$env:PYTHONIOENCODING='utf-8'
cd D:\agent-library
py -3 scripts\store.py                   # 改了 catalog/intents.json 后重建索引
py -3 router.py route --agent dsh "<原句>"
py -3 scripts\eval_router.py --all       # 正例 + 负例 + 槽位
py -3 scripts\ci.py --fast               # 与 pre-commit 一致
```

- 新增/改技能：只改 `catalog/<id>/SKILL.md` + `manifest.json`，**不要**复制到各 Agent 目录；
- 改 intent/domains：改 `catalog/intents.json` / `catalog/domains.json` → `store.py` → 三套评测必须全绿；
- 本轮改动前的备份在 `D:\agent-library\_trash\*.bak-20261105-142530`；
- `router.py` **未修改**（无备份/无回归风险）。