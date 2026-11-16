# 结构特征表与数据集（cifkit.features / cifkit.dataset）

`cifkit features` 把结构变成 ML-ready 特征表；`cifkit dataset` 把 `runs/` 或 `library/`
里的多次 pipeline 结果汇总成数据集（结构 + 特征 + 标签 + manifest）。两者都不联网、不改结构。

## 1. `cifkit features`

```powershell
$PY = 'D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe'
& $PY -m cifkit features runs\demo_sod_zif8\standardized.cif --out runs\features.csv --json
& $PY -m cifkit features runs\export_demo --out runs\features_all.csv --no-rdf --jobs 4 --json
& $PY -m cifkit features runs\export_demo --out runs\features_topo.csv --topology --no-rdf
& $PY -m cifkit features runs\export_demo --out runs\features_rings.csv --rings --no-rdf
```

特征字典（v1；标量列扁平，字典/列表列为 JSON 字符串）：

| 列 | 类型 | 含义 / 计算方式 |
|---|---|---|
| `path`, `filename`, `feature_version` | str | 来源文件与特征版本 |
| `formula`, `reduced_formula` | str | pymatgen 组成 |
| `natoms`, `n_elements` | int | 原子数 / 元素数 |
| `element_counts`, `atomic_fractions` | JSON dict | 元素计数/占比 |
| `metal_fraction` | float | `is_metal` 元素占比 |
| `h_count`, `has_c`, `has_organic_chemistry` | int(0/1) | H 数、是否含 C、是否含 C/N/O/S |
| `a,b,c,alpha,beta,gamma` | float | 晶格参数（Å/°） |
| `volume`, `density_g_cm3`, `volume_per_atom` | float | 体积/密度/每原子体积 |
| `spacegroup_number/symbol`, `point_group`, `n_symops`, `crystal_system` | mixed | spglib/pymatgen 对称性（失败为 null） |
| `cn_mean`, `cn_by_element`(JSON), `cn_histogram`(JSON) | mixed | 几何配位数统计 |
| `rdf_<ElA>_<ElB>` | JSON list | 元素对 g(r)，长度 = `rdf_bins`；`rdf_r` 是 r 网格。**对称定义**（round 57）：每列是 A≤B 的无序对，中心与邻居两个方向都计入同一根直方图；归一化 `g_AB = hist/((N_A·ρ_B + N_B·ρ_A)·壳层体积)`（A=B 时为 `N_A·ρ_A·壳层体积`），理想随机混合 → 1。round 57 修复三处缺陷（此前所有列恒 0 或量级错）：邻居物种解析用错 Site 助手、壳层体积少减内球、归一化用总原子数 |
| `topology_net`, `topology_evidence` | str | `--topology` 时调用 `cifkit.topology.identify`（6 个落盘 net；未知→unknown） |
| `ring_basis`, `ring_sizes`, `rings_per_node` | JSON/list | `--rings` 时的 4–8 元环。金属框架走 SBU 收缩的 underlying net（`ring_basis=metal-net`，另给 `n_metal_nodes`/`n_linkers`）；**无金属的共价/有机框架走完整键图**（`ring_basis=full-bond-graph`，另给 `rings_per_cell`/`rings_truncated`） |
| `error` | str | 失败行标记（其它行仍输出，命令 exit 1） |

耗时：138 原子 ZIF-8 无 RDF ~0.1 s；RDF(50×8 Å) ~1–2 s；`--topology` +2–5 s；大结构建议 `--no-rdf`。

## 2. `cifkit dataset`

```powershell
& $PY -m cifkit dataset --from-runs runs --outdir runs\dataset --label-key topology --json
& $PY -m cifkit dataset --from-library library --outdir runs\dataset_lib --label-key source --json
```

- 扫描 `<source>/**/manifest.json`；每个 run 取 `standardized.cif` > `raw.cif` > `repaired.cif` > `structure.vasp`。
- 输出：`dataset.csv`（run 级：run_id/source/record_id/topology_evidence/structure_file/label + 全部特征）、
  `dataset.jsonl`（完整特征对象）、`structures/<run_id>.cif`、`dataset_manifest.json`
  （n_runs/n_ok/n_failed/errors/csv_sha256/时间/feature_version）。
- `label` 从 `--label-key` 在 manifest 的 `source.record` 或 `provenance` 里取（如 `topology`、`source`、`doi`）；
  取不到则为空。
- 失败不中断：无结构/解析失败进 `errors`，其余照常输出；`n_failed>0` 时命令 exit 1（但文件已写好）。

## 3. 与其它命令的关系

- 上游：`cifkit pipeline`（下载/补氢/超胞/切面/真空）→ `manifest.json` → `cifkit dataset`。
- 侧车：`cifkit batch` 批量生成 runs → 再 dataset 汇总。
- 下游：CSV 直接给 pandas/sklearn；`dataset.jsonl` 保留嵌套 RDF 等供自定义特征用。

## 4. 已知限制

- RDF 是有限网格近似（默认 50 bins × 8 Å），元素对多时列多、文件大；超大结构可关掉。
- 配位数/对称性基于几何与 spglib，不读化学价/自旋。
- dataset 只汇总 manifest 中已有结构，不重新下载；不计算 DFT 能量/带隙等标签。
- 特征版本 `cifkit-features/v1`；改列名会升级版本号并更新本文件。
