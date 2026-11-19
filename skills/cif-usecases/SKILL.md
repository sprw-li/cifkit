---
name: cif-usecases
description: >-
  CIF 工作台进阶应用：点群典例教学图、布拉维点阵对称性分析、纯金属批量晶格+表面能输入、Fe-C 相图计算套件；
  用 cifkit 的 teach/bravais/metals/fec 子命令一键复跑，产物写到 --outdir。
---

# cif-usecases（进阶应用：教学图 / 对称性分析 / 金属批量 / 相图套件）

> 这是 CIF 工作台扩展出来的 4 类“超出单条 pipeline”的应用工作流。每个工作流都有真实数据来源、
> 独立验收与诚实局限；已固化成 `cifkit` 的 4 个子命令（实现：`cifkit/usecases_cli.py`），
> 产物统一写到 `--outdir`，原 `usecases/` 交付目录不会被改动。
> 另有配套命令 `cifkit surface-energy`（§5）：把 `metals`/slab 工作流产出的 slab 与用户 DFT 能量
> 固定成表面能算术；它是引擎 `cifkit/cli.py` 的子命令，**不在** `usecases_cli.py` 里。

## 何时使用

- 用户要 **点群/空间群的典例教学图**（“找一些 Fd-3m 的典例，排成 png”）；
- 用户要 **布拉维点阵/对称性等效与退化**分析（“对比 cF 与 tI 的关系，探究 14 种布拉维点阵”）；
- 用户要 **批量导出纯金属晶格数据 + 最密面表面能模拟输入**（“导出 100 种纯金属…表面能文件”）；
- 用户要 **Fe-C 化合物/相图关系 + 计算套件**（“铁碳化合物有哪些种，跟相图的关系，打包套件”）；
- 用户已经算完 slab/bulk 的 DFT 能量、要 **表面能（E_surf）数值与单位换算**（“我有 slab 和 bulk 的能量，算一下表面能”）→ §5 `surface-energy`。

## 依赖

```powershell
$PY = 'D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe'
Set-Location 'D:\Dev\Project5-skill-cif'
$env:PYTHONIOENCODING='utf-8'
& $PY -m cifkit --version
```

- `teach` 默认允许网络（COD/AFLOW），**已缓存不重下**；`--offline` 只用缓存（`usecases/u1_fd3m/data/structures/`）。
- `bravais` / `fec` 完全离线（本地构胞 / 已导出的 AFLOW CSV）。
- `metals` 优先 ASE/Kittel 参考态（离线）；只有缺数据的元素才走 AFLOW/COD 缓存/网络，支持断点续跑。

## 子命令（推荐入口）

统一格式：`& $PY -m cifkit <teach|bravais|metals|fec> --outdir DIR [选项] [--json]`。
`--json` 时 stdout 是**单个 JSON**（日志走 stderr）；退出码 0=成功，1=运行失败，2=参数/请求不支持。
若本机 `cifkit/cli.py` 尚未注册这 4 个子命令，用等价入口 `& $PY -m cifkit.usecases_cli <子命令> ...`。

### 1) `cifkit teach` — Fd-3m 典例教学图（PNG + CSV）

```powershell
& $PY -m cifkit teach --spacegroup Fd-3m --outdir runs\uc\fd3m --json
& $PY -m cifkit teach --outdir runs\uc\fd3m --offline --json   # 只用缓存，不联网
```

| 参数 | 说明 | 默认 |
|---|---|---|
| `--spacegroup` | 目前仅支持 `Fd-3m`（#227）；其它值退出码 2 | `Fd-3m` |
| `--outdir` | 产物目录（必填） | — |
| `--online/--offline` | 允许/禁止联网补齐缺失 CIF | `--online` |
| `--symprec` | spglib 对称性容差（Å） | `0.05` |
| `--json` | stdout 输出单个 JSON | 关 |

产物：`<outdir>/data/structures/*.cif`、`data/examples.csv`、`data/provenance.json`、
`figures/fd3m_examples.png`（2×3 面板，标注化学式/空间群/点群/晶胞参数；spglib 全部 #227）。
诚实边界：CIF 里的反位无序/分数占位按主导元素作图，不声称样品完全有序。

### 2) `cifkit bravais` — Bain 路径 + 14 种布拉维点阵

```powershell
& $PY -m cifkit bravais --outdir runs\uc\bravais --json
& $PY -m cifkit bravais --outdir runs\uc\bravais --bain-range 0.9:1.7:0.05 --json   # 小步长更快
```

| 参数 | 说明 | 默认 |
|---|---|---|
| `--outdir` | 产物目录（必填） | — |
| `--bain-range` | 扫描范围 `START:STOP:STEP`（c/a） | `0.9:1.7:0.01` |
| `--json` | stdout 输出单个 JSON | 关 |

产物：`data/bain_path.csv`（默认 82 行）、`data/bain_tolerance.csv`、`data/bravais14.csv`、
`data/equivalences.csv`（12 组）、`data/hR_alpha_scan.csv`、`figures/{bain_symmetry,bain_cells,bravais_relations}.png`。
核心结论：cF 与 tI 只在 c/a=√2 特殊度量下胞等价，点群不同（m-3m 阶 48 vs 4/mmm 阶 16）；Bain 路径中间全是 tI #139。
注意 spglib 容差：symprec=0.05 Å 会把 c/a=1.41 误判 cF；报告给出 0.01 Å 判据与容差表。

### 3) `cifkit metals` — 纯金属批量晶格 + 最密面表面能输入

```powershell
& $PY -m cifkit metals --outdir runs\uc\metals --elements Fe,Cu,Mg --json       # 子集（推荐做冒烟）
& $PY -m cifkit metals --outdir runs\uc\metals --elements all --zip --json      # 全部 87 种金属 + kit.zip
```

| 参数 | 说明 | 默认 |
|---|---|---|
| `--outdir` | 产物目录（必填；已有 `data/records.json` 时断点续跑） | — |
| `--elements` | `all` 或逗号分隔子集（如 `Fe,Cu,Mg`）；非金属/未知元素退出码 2 | `all` |
| `--zip/--no-zip` | 是否额外打包 `metals_kit.zip` | `--no-zip` |
| `--json` | stdout 输出单个 JSON | 关 |

产物：`elements/<El>/{bulk.cif,bulk_POSCAR,slab.cif,slab_POSCAR,lattice.csv,INCAR,KPOINTS}`、
`metals_summary.csv`、`data/{records,run_report,slab_validation}.csv|json`、`surface_energy/`（E_surf 模板）、
`metals_kit.zip`（`--zip`）。
覆盖：周期表 87 种金属中 **69 种**有可靠基态结构（ASE 58 / AFLOW 7 / COD 4），18 种如实记录 missing
（Fr/Cm/Bk/Cf/Es 无公开结构；Fm–Cn 实验结构未确立）。**不要为凑数编造结构。**
最密面：fcc(111)、bcc(110)、hcp(0001)、sc(100)、diamond(111)；复杂结构用平面原子密度算法（标 plane_confidence）。
局限：不含 VASP 能量，slab 为未弛豫理想切面。

### 4) `cifkit fec` — Fe-C 结构 + 0 K 凸包 + VASP 模板（离线）

```powershell
& $PY -m cifkit fec --outdir runs\uc\fec --json
& $PY -m cifkit fec --outdir runs\uc\fec --zip --json   # 额外打包 fe_c_kit.zip
```

| 参数 | 说明 | 默认 |
|---|---|---|
| `--outdir` | 产物目录（必填；离线，只读仓库里已导出的 AFLOW CSV） | — |
| `--zip/--no-zip` | 是否额外打包 `fe_c_kit.zip` | `--no-zip` |
| `--json` | stdout 输出单个 JSON | 关 |

产物：`structures/`（7 个 Fe-C 化合物 CIF+POSCAR）、`data/{aflow_fe_c_energies,fe_c_compounds,hull_points}.csv`、
`figures/fe_c_hull.png`、`docs/phase_diagram_notes.md`、`vasp_inputs/`、`fe_c_kit.zip`（`--zip`）。
关键数字（AFLOW LIB2 的 289 条形成焓，0 K DFT）：hull 只有 Fe/C 端点；Fe3C=+0.0456、Fe2C(正交)=+0.0516、
FeC=+0.3843 eV/atom；Hägg/Fe7C3/Fe23C6 无 AFLOW 焓，未硬凑。
诚实话术：AFLOW 数据是别人算的 DFT，不是本地新算；相图温度按 Callister/Porter-Easterling 教材值，未逐条在线复核的已标注。

### 5) `cifkit surface-energy` — slab/bulk 能量 → 表面能（算术，不是 DFT）

`metals` 只给未弛豫的 slab 结构与 `surface_energy/` 模板；能量要用户自己算。这一个命令负责
“slab 结构 + 用户 DFT 能量”之间的记账与单位换算（引擎子命令，**不是** `usecases_cli.py` 里的 4 个子命令之一）：

```powershell
& $PY -m cifkit surface-energy --slab-e -100.0 --slab-atoms 32 --area 100.0 `
    --bulk-per-atom -5.0 --slab-formula "Zn:8,O:8" --bulk-formula "Zn:4,O:4" `
    --json runs\uc\se.json
```

| 参数 | 说明 | 默认 |
|---|---|---|
| `--slab-e` | slab 总能量（eV；与 bulk 用同一泛函/赝势/截断） | 必填 |
| `--slab-atoms` | slab 原子数 | 必填 |
| `--area` | 表面面积（Å²） | 必填 |
| `--bulk-per-atom` | bulk 每原子能量（eV） | 与 `--bulk-e`+`--bulk-atoms` 二选一 |
| `--bulk-e` / `--bulk-atoms` | bulk 总能 + 原子数 | 同上 |
| `--slab-formula` / `--bulk-formula` | 组成（如 `Zn:4,O:4`），用于化学计量校验 | 无 |
| `--one-surface` | 只算一个表面（默认双表面） | 关 |
| `--json FILE` | 把结果 JSON **写入该文件**（注意：这里是路径，不是开关） | 无 |

- `E_surf = (E_slab − n_slab × e_bulk) / (N_surface × A)`；输出 **eV/Å² / meV/Å² / J/m²**（1 eV/Å² = 16.02176634 J/m²）。
- **化学计量校验**：slab 组成必须是 bulk 组成的整数倍，否则报错（避免拿不同组成的相减）；两种 bulk 参考同时给且不一致也报错。
- 诚实边界：能量来自用户自己的 DFT，本命令**不产生能量、不做弛豫**；弛豫通常会降低表面能。
  与 `metals` 产出的 `surface_energy/` 模板配套使用。完整说明见 `docs/GEOM.md` "表面能：`cifkit surface-energy`"。

## 旧脚本 fallback（子命令等价，保留用于调试/单步）

```powershell
& $PY usecases\u1_fd3m\scripts\fetch_structures.py --outdir runs\uc\fd3m   # 联网抓取（已缓存跳过）
& $PY usecases\u1_fd3m\make_figure.py --outdir runs\uc\fd3m               # spglib 复核 + CSV + PNG
& $PY usecases\u2_bravais\scripts\bain_path.py --outdir runs\uc\bravais --bain-range 0.9:1.7:0.05
& $PY usecases\u2_bravais\scripts\bravais14.py --outdir runs\uc\bravais
& $PY usecases\u3_metals\scripts\export_metals.py --outdir runs\uc\metals --elements Fe,Cu,Mg
& $PY usecases\u3_metals\scripts\finalize_metals.py --outdir runs\uc\metals --zip
& $PY usecases\u4_fec\scripts\build_hull.py --out-csv runs\uc\fec\data\hull_points.csv --out-png runs\uc\fec\figures\fe_c_hull.png
& $PY usecases\u4_fec\scripts\make_vasp_inputs.py --kit runs\uc\fec
```

> 各脚本的 `main(argv=None)` 与默认输出目录保持兼容：不带 `--outdir` 时仍写回 `usecases/<case>/`。

## 验收证据

```powershell
& $PY -m pytest tests\test_usecase_cli.py -q      # 4 命令 help/参数、teach 离线、bravais 小步长、fec 离线、metals Fe/Cu/Mg、JSON 纯度、错误码
& $PY usecases\verify_usecases.py                 # 旧交付物独立验收 22 项（fallback）
```

本机实测（2026-11-05，`.venv`）：`pytest tests/test_usecase_cli.py -q` → **12 passed, 1 skipped（全量 opt-in gate）**，约 28 s；
4 个命令 `--json` 均 exit 0 且 stdout 可 `json.loads`；`teach --offline` 6/6 #227；`bravais --bain-range 0.9:1.7:0.05`
bain 18 点、14/14 点阵、12 组等价；`metals --elements Fe,Cu,Mg` 3/3 元素各 7 文件；
`fec` 7 结构 / 10 个 vasp_inputs 目录 / Fe3C E_above_hull=+0.0456、kit.zip 打包成功。

## 数据来源与坑（经验）

- COD：有实验 CIF，按 `text` 检索后需用 spglib 复核空间群（COD 没有空间群过滤 API）。
- AFLOW：CIF 的 `_atom_site_type_symbol` 含 PAW 势名，`cifkit.sources.aflow.sanitize_aflow_cif` 已修复；
  `spacegroup_relax(...)` 查询过滤不可靠，必须查全量客户端过滤；LIB1 里每元素有多种多型，**不能**用最低
  `energy_atom` 当基态（实测 Sn→diamond、Hg→bcc、Ga→bct、In→hcp、Mn→hcp 都错）。
- ASE `ase.data.reference_states` 是简单结构的可靠基态/晶格来源（fcc/bcc/hcp/sc/diamond/bct/rhombohedral）。
- 没有 Materials Project key 时不要试图“猜” MP 数据；文档里明确标注未 live 验证。
- `--outdir` 语义：所有命令只写 outdir；测试/演示用临时目录，别污染 `usecases/` 交付物。

## 不要用

- 只要单条 CIF 管线的（下载→补氢→超胞→切面→真空→导出）→ 用 `cif-workbench`，不要走这套；
- 只要查一个结构/一个相图数字的 → 用 `cif-fetch` + 文献检索，不要启动批量；
- 把 `metals`/`fec` 当成“本地 DFT 计算”——它们只生成结构与输入模板，不含 VASP 能量。
