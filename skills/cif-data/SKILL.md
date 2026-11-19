---
name: cif-data
description: >-
  把 CIF / 批量 run 变成 ML-ready 数据：`cifkit features` 提取结构特征表（组成、晶格、对称性、
  配位数、RDF、可选拓扑 net）并写 CSV/JSONL；`cifkit dataset` 从 runs/ 或 library/ 汇总成 dataset
  （dataset.csv/jsonl + structures + manifest 溯源）。
---

# cif-data（结构特征表 / ML 数据集）

只读加工层：**不改结构、不跑计算**，把 CIF 或已完成的 run 汇总成可训练/可统计的特征表与数据集。
若目标是“把结构转成某个软件格式”，用 `cif-export`；若目标是“下载→补氢→超胞→切面→导出”的流水线，用 `cif-workbench`。

## 何时使用

- “导出这个 CIF 的结构特征 CSV / 提取 RDF / 配位数 / 密度 / 空间群”；
- “把一批 CIF 做成机器学习特征表（CSV；要 JSONL 用 `cifkit dataset` 的 `dataset.jsonl`）”；
- “从 runs/ 或 library/ 构建 dataset（含结构副本 + manifest）”；
- 需要可复现的特征列定义与数据溯源（工具版本、sha256、跳过/失败列表）。

**不要用**：要改结构（补氢/超胞/切面/真空）→ `cif-workbench`；只要格式转换/计算软件输入包 → `cif-export`；
只要单条 CIF 的校验/报告 → `cifkit validate` / `pipeline`；要做 DFT 计算本身 → 本工具不提交/不计算能量。

## 依赖

```powershell
$PY = 'D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe'
Set-Location 'D:\Dev\Project5-skill-cif'
$env:PYTHONIOENCODING='utf-8'
& $PY -m cifkit --version
```

- 离线可用（读本地 CIF / runs / library）；不需要网络。
- 大结构注意：RDF 是 O(N²) 邻接统计，>500 原子建议 `--no-rdf`；拓扑识别更慢，按需 `--topology`。
- 环统计：`--rings` 在金属框架上走 SBU 收缩的 underlying net（`ring_basis=metal-net`），在无金属的共价/有机框架上回退到**完整键图**（`ring_basis=full-bond-graph`，给 `rings_per_cell`）；节点数 >600 时跳过并标 `rings_truncated`。

## 命令

```powershell
# 1) 单个 CIF → 特征表（CSV）
& $PY -m cifkit features tests\data\zif8_cr_sod.cif --out runs\data\zif8_features.csv --json

# 2) 一批 CIF/目录 → CSV（并行；坏文件记 error 不中断）
& $PY -m cifkit features tests\data --out runs\data\features.csv --jobs 4 --json

# 3) 只要结构与组成/对称性（关闭 RDF，大结构更快）
& $PY -m cifkit features runs\demo_sod_zif8\final.cif --out runs\data\final_features.csv --no-rdf --json

# 4) 加拓扑 net（pcu/sod/fcu…，额外耗时；失败返回 unknown 不崩）
& $PY -m cifkit features tests\data\zif8_cr_sod.cif --out runs\data\topo.csv --topology --json

# 4) 环统计（4–8 元环；金属框架与共价框架都支持）
& $PY -m cifkit features tests\data\zif8_cr_sod.cif --out runs\data\rings.csv --rings --no-rdf --json

# 5) 从 runs/ 构建数据集（dataset.csv/jsonl + 结构副本 + manifest）
& $PY -m cifkit dataset --from-runs runs\demo_sod_zif8 --outdir runs\dataset_demo --json

# 6) 从 library/（pipeline --ingest 的产物）构建数据集
& $PY -m cifkit dataset --from-runs library --outdir runs\dataset_library --json
```

> 命令面以 `& $PY -m cifkit features --help` / `dataset --help` 的运行时输出为准（本技能按 Lead 冻结的目标命令编写）。
> 若 `features`/`dataset` 尚未出现在 `cifkit --help`，说明 CLI 还没接线，先不要声称已跑通。

## 参数表（目标命令面）

### `cifkit features`

| 参数 | 说明 | 默认 |
|---|---|---|
| `INPUT...` | 一个或多个 CIF 文件 / 目录（递归找 `*.cif`） | — |
| `--out FILE` | 特征表 CSV（必填） | — |
| `--jobs N` | 并行进程/线程数 | 1（或实现默认） |
| `--no-rdf` | 不计算 RDF（大结构提速） | RDF 开 |
| `--rdf-bins N` / `--rdf-max Å` | RDF 分箱数与截断 | 50 / 8.0 Å |
| `--topology` | 额外跑 `topology.identify()` 记 net/evidence（慢） | 关 |
| `--rings` | 额外统计 4–8 元环（金属 net 或完整键图；慢） | 关 |
| `--json` | stdout 输出单个 JSON 摘要（路径、行数、列名、errors） | 人要读的文本 |

> `features` **没有 JSONL 输出参数**（实测照 CLI 不存在的写法会 `unrecognized arguments`，exit 2）：
> 它只有 `--out` 写 CSV 与 `--json` 在 stdout 打摘要。需要 JSONL 时用 `--out` 得到 CSV 后自行转换，
> 或改用 `cifkit dataset`（其产物含 `dataset.jsonl`）。

### `cifkit dataset`

| 参数 | 说明 | 默认 |
|---|---|---|
| `--from-runs DIR` | 扫描含 `manifest.json` 的 run 目录（或 library 根） | — |
| `--outdir DIR` | 数据集输出目录（必填） | — |
| `--label-key FIELD` | 从 manifest/provenance 取一个字段作 `label` 列（如 `topology`/`doi`/`source`） | 无 |
| `--no-structures` | 不复制结构文件（只要特征表） | 复制 |
| `--json` | stdout 输出单个 JSON 摘要 | — |

## 输入 / 输出 schema（目标；以运行时表头为准）

**features CSV 列（标量扁平，复杂结构用 JSON 字符串列）**：

| 组 | 列 |
|---|---|
| 身份 | `path`（或 `run_id`）、`formula`、`reduced_formula`、`natoms` |
| 组成 | `element_counts`(JSON)、`atomic_fractions`(JSON)、`n_elements`、`metal_fraction`、`h_count`、`has_CNO`(有机框架判定) |
| 晶格 | `a,b,c,alpha,beta,gamma`、`volume`、`density_g_cm3`、`V_per_atom`、`lattice_type` |
| 对称性 | `spacegroup_number`、`spacegroup_symbol`、`point_group`、`n_symops`、`centering` |
| 配位 | `mean_CN`、`cn_by_element`(JSON)、`cn_histogram`(JSON) |
| RDF | `rdf`(JSON：`{pair: {"r": [...], "g": [...]}}` 或全原子 g(r))；`--no-rdf` 时为空/缺列 |
| 环统计（`--rings`） | `ring_basis`（`metal-net`/`full-bond-graph`）、`ring_sizes`、`rings_per_node`；金属框架另给 `n_metal_nodes`/`n_linkers`，无金属框架另给 `rings_per_cell`/`rings_truncated` |
| 拓扑（可选） | `net`、`net_evidence`（`metadata/verified/curated/unknown/mismatch`） |

**dataset 输出**：

```text
<outdir>/
  dataset.csv            # 每行一个 run/结构：run_id + 身份列 + 全部特征列（+ 可选 label）
  dataset.jsonl          # 原始特征对象（每行一个 JSON）
  structures/<id>.cif    # 复制结构副本（--no-structures 可关）
  dataset_manifest.json  # 来源扫描范围、工具版本、时间、行数、sha256(dataset.csv)、skipped/errors
```

## 与其它技能的边界

| 需求 | 用 |
|---|---|
| 下载/补氢/超胞/切面/真空/导出流水线 | `cif-workbench`（产物 `runs/<run>/manifest.json`） |
| 单条结构转计算软件格式/输入包 | `cif-export`（`cifkit convert` / `cifkit export`） |
| 从 CIF/run 提取特征、汇总 dataset | **本技能**（只读；不修改上游产物） |
| 单个结构的完整性/真空/价态校验 | `cifkit validate`，或 `cif-workbench` 的 validation |

典型串联：`cif-workbench` 产出 `runs/*/manifest.json` + `standardized.cif` → `cifkit dataset --from-runs runs/`；
或 `cifkit features <cif>` 得到 CSV 后直接喂给 pandas/sklearn。

## 局限（必须如实写进报告）

- **RDF 是几何统计**，不是实验/DFT 结果；bin 宽、截断、归一化方法要在报告里写明（默认 50 bins, 8 Å）。
- **大结构慢**：RDF 用邻接/距离统计，原子数上千时明显变慢；>500 原子先 `--no-rdf`。
- **拓扑识别**：只有已建参考的 net（如 sod/pcu/dia/fcu/tbo/bcu）能 verified；其它返回 unknown，**不许**当 verified。
- **dataset 只汇总已有产物**：不下载、不补算、不保证 run 的物理正确性；标签来自 manifest 字段，可能缺失。
- **对称性判定依赖 symprec**：默认 0.1 Å；容差不同可能改变 spacegroup/lattice_type，报告要写容差。
- **不是训练管线**：不做 train/test 划分、不做特征标准化；这些由下游 ML 自己负责。

## 验收证据

1. `features --json` 的摘要里 `rows > 0`、`columns` 含身份/晶格/对称性列；`errors` 为空或逐条解释；
2. CSV 用 pandas 读回：行数 == 输入 CIF 数；`natoms`/`spacegroup_number`/`a` 与源 CIF 抽查一致；
3. `--no-rdf` 与默认 RDF 的耗时对比记录（大结构）；
4. dataset：`dataset.csv` 行数 == 扫描到的 run 数；`dataset_manifest.json` 有 sha256 与 skipped/errors；结构副本存在；
5. 抽查 1 个 run 的 `dataset.csv` 行与 `manifest.json` 的 record/formula 对齐。

```powershell
& $PY -m cifkit features tests\data\zif8_cr_sod.cif --out runs\data\zif8_features.csv --json
& $PY -c "import pandas as pd; d=pd.read_csv(r'runs\data\zif8_features.csv'); print(d.shape); print(d.iloc[0].to_dict())"
& $PY -m cifkit dataset --from-runs runs --outdir runs\dataset_demo --json
```
