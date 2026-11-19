---
name: cif-workbench
description: >-
  CIF 晶体结构工作台总入口：从 CoRE MOF/COD 下载典型 RCSR 拓扑 MOF 的 CIF，
  补氢/修无序/去近邻，做超胞、沿 (hkl) 切 slab、加真空层，导出 VASP/CIF/XYZ
  等计算化学格式，一条 `python -m cifkit pipeline` 跑通并产出可溯源的 manifest.json。
---

# cif-workbench（总入口）

一条命令跑完整条 CIF 处理链：**检索下载 → 拓扑核实 → 修复 → 标准胞 → 切面/面内重复 → 真空 → 导出 → 校验 → manifest**。
只有这一条管线能同时满足“带溯源、可复现、每步有证据”；单步任务用 `cif-fetch` / `cif-repair` / `cif-geometry` / `cif-export`。

## 何时使用

- 用户一句话里同时要：下载 CIF/MOF、补氢、超胞（Supercell）、沿 (hkl) 切表面/slab、加真空层、导出 VASP/POSCAR 等格式；
- 需要一份可复核的处理报告：来源 DOI/sha256、拓扑证据、补氢统计、超胞/面内重复倍数、真空实测值、校验结论；
- 例：`帮我下载典型的RCSR为sod的mof，需要碳上补充氢，创建一个2x2x1的超胞（Supercell），沿(111)面切出表面，并加上15Å的真空层，导出为计算化学软件使用的格式。`

**不要用**：只画二维结构式（`draw-chemistry`）、CIF 转 3D 打印网格（`cif-to-3dprint`）、只要无头渲染出图（`blender-mol-render`）。

## 依赖（已就绪，勿重复安装）

```powershell
$PY = 'D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe'   # cifkit 已 editable 安装
Set-Location 'D:\Dev\Project5-skill-cif'
$env:PYTHONIOENCODING='utf-8'                                # 中文输出必须，防 GBK 乱码
& $PY -m cifkit --version
```

- 唯一入口：`& $PY -m cifkit <子命令>`；不要 `pip install`，不要另建虚拟环境。
- 离线数据已缓存在 `D:\Dev\Project5-skill-cif\_cache\core-mof-2024\`（`CoREMOF2024DB.zip` 44 MB / 8300 CIF、`ASR_data_SI_20250204.csv`）——**不要重复联网下载大文件**。
- 网络可达：COD、Zenodo、PyPI；不可达：`rcsr.anu.edu.au`、figshare API。

## 最快路径

```powershell
# 1) 环境自检（离线，几秒）
& $PY -m cifkit selftest --verbose

# 2) 只解析不执行：确认拓扑/超胞/晶面/真空/格式都识别对
& $PY -m cifkit route "帮我下载典型的RCSR为sod的mof，需要碳上补充氢，创建一个2x2x1的超胞（Supercell），沿(111)面切出表面，并加上15Å的真空层，导出为计算化学软件使用的格式。"
# 退出码 0 = 识别到结构；退出码 2 = 没解析出 topology/structure_name/structure_id，先补参数

# 3) 一条管线跑通（务必给 --outdir）
& $PY -m cifkit pipeline "帮我下载典型的RCSR为sod的mof，需要碳上补充氢，创建一个2x2x1的超胞（Supercell），沿(111)面切出表面，并加上15Å的真空层，导出为计算化学软件使用的格式。" `
    --outdir runs\demo_sod_zif8 --format vasp,cif,xyz --json

# 4) 独立复核（不信自报，直接从产物结构验 DESIGN §1 的 9 条验收，其中 8 项自动复核）
& $PY D:\Dev\Project5-skill-cif\scripts\verify_demo.py runs\demo_sod_zif8
```

### `--spec` 用法（批量/固定参数时）

```json
{
  "query": "sod MOF 补氢+超胞+切面+真空",
  "source": "core-mof",
  "topology": "sod",
  "typical": true,
  "repair_h": true,
  "repair_disorder": true,
  "remove_close_contacts": true,
  "supercell": [2, 2, 1],
  "surface": [1, 1, 1],
  "surface_frame": "slab",
  "vacuum": 15.0,
  "slab_thickness": 15.0,
  "output_formats": ["vasp", "cif", "xyz"],
  "outdir": "runs/spec_run"
}
```

```powershell
& $PY -m cifkit pipeline --spec runs\spec.json --outdir runs\spec_run --json
```

本地 CIF 也走 spec：把 `"source": "local"`、`"structure_id": "D:\\path\\my.cif"` 填上，跳过下载。

## 批量（多结构并发）：`cifkit batch`

一条一句（`--spec` 可重复），或 `--specs-file specs.jsonl`（每行 `{"spec": "...", "outdir": "..."}`）：

```powershell
& $PY -m cifkit batch --spec "把 tests/data/zif8_cr_sod.cif 导出为 vasp" --spec "把 tests/data/zif8_cr_sod.cif 导出成 cif" --jobs 2 --outdir runs\batch --json
# 输出 runs\batch\batch_manifest.json：每条 run 的 ok/returncode/seconds/outdir/summary
```

- 每条 run 独立子进程 + 独立 `outdir`；一条失败不阻塞其它（总 exit 1 但 manifest 记录全部）。
- 3 条 demo 实测：串行 41.0 s → `--jobs 3` **14.8 s（2.8×）**；详见 `docs/PERFORMANCE.md`。
- 缓存并发安全（文件锁 + 原子写）见 `docs/ROBUSTNESS.md`；冷启动诊断用
  `python scripts/bootstrap_data.py --check`。

单独一次几何操作也有进程内缓存：`cifkit.geom.make_slab` 同参数第二次 ~150× 加速
（2.12 s → 0.014 s），`slab_cache_info()` 可查命中。

## 2x2x1 的语义（重要，别只看原子数）

管线里同时给 `supercell` 和 `surface` 时，默认 **`surface_frame="slab"`**：
先从标准化体相切出 `(hkl)` slab，再把 `2x2x1` 作为 **slab 面内 2x2 重复**（`reps[2]` 必须为 1）。
demo 的 `sod`：修复后 276 原子 → (111) 切出 **base 552** → 面内 2x2 → **2208 原子**（= 276 × 8）。
`--surface-frame cell` 才是字面“先 2x2x1 超胞再切该胞 (111)”，取向不是立方 (111)，只作对照。
只给 `supercell` 不给 `surface` 时，才是普通超胞（`2x2x1` → 原子数 ×4）。

## 数据源（五个，按需切换）

`cifkit` 内置 5 个数据源适配器，一条管线用 `--source auto` 自动选，也可显式指定：

| source | 覆盖 | 需要 key | 拓扑元数据 |
|---|---|---|---|
| `core-mof` | CoRE MOF 2024（MOF + RCSR 拓扑；NCR 原始 CIF） | 否（本地缓存） | **有**（仅 ASR） |
| `cod` | Crystallography Open Database（实验晶体，公有领域） | 否 | 无 |
| `materials-project` | Materials Project（DFT 结构，按 `mp-<id>`/化学式） | **是**（`MP_API_KEY`） | 无 |
| `aflow` | AFLOW（无机/合金，按化学式或 aurl） | 否 | 无 |
| `local` | 本地 `.cif` | 否 | 无 |

```powershell
& $PY -m cifkit sources --probe          # 数据源状态/可达性（先看这个）
& $PY -m cifkit fetch --source aflow --name ZnO --limit 3
& $PY -m cifkit fetch --source mp --id mp-149 --outdir runs\mp          # 需 MP_API_KEY
& $PY -m cifkit pipeline "..." --source cod --topology sod --outdir runs\x
```

经验：MP/AFLOW/COD **没有 RCSR 拓扑列**，请求拓扑时它们返回空列表（不是没结构）；
MOF 名称（ZIF-8）只有 core-mof/COD 能按名称检索；MP 只支持 `mp-id`/化学式，AFLOW 只支持化学式
或 aurl。详见 `catalog/cif-fetch/SKILL.md` 与 `D:\Dev\Project5-skill-cif\docs\SOURCES.md` §7d。

## 参数表

| 参数 | 说明 | 默认 |
|---|---|---|
| `"TEXT"` / `--spec` | 自然语言原话 / TaskSpec JSON，二选一 | — |
| `--outdir DIR` | **必填**，产物目录（不存在会创建） | — |
| `--format vasp,cif,xyz` | 覆盖解析出的导出格式，逗号分隔（支持：vasp/cif/xyz/lammps/qe/cp2k/xsf） | 解析结果；无格式词时 `vasp,cif,xyz` |
| `--source auto` | `auto` / `core-mof` / `cod` / `local` / `materials-project` | `auto` |
| `--topology sod` | 仅当原话没解析出拓扑时补 | 解析结果 |
| `--surface-frame slab\|cell` | 同时有 supercell+surface 时的语义（见上节） | `slab` |
| `--ingest` | 把产物登记进 `library/`（会复制文件） | 关 |
| `--json` | 输出 RunResult JSON（steps/artifacts/validation） | 人类可读 |

## 产物（`--outdir` 下）

| 文件 | 内容 / 用途 |
|---|---|
| `plan.json` | 解析出的执行计划（步骤名/参数），先看它确认理解正确 |
| `raw.cif` | 下载的原始结构（未修复），sha256 与 manifest 对得上 |
| `repaired.cif` | 修复后结构（补氢/无序/近邻） |
| `standardized.cif` | 标准胞（无 cluster 时） |
| `supercell.cif` | **仅当没有 `surface` 时**才生成（普通超胞） |
| `slab.cif` | 切出的 slab（已含 `2x2` 面内重复，demo 2208 原子） |
| `final.cif` | 最终（真空设置后）结构 |
| `structure.vasp` / `structure.cif` / `structure.xyz` | 计算化学导出（按 `--format`；实际格式以 `cifkit formats` 为准） |
| `preview.png` | 结构预览图 |
| `report.md` | 人读报告：来源、步骤、校验、产物 |
| `manifest.json` | **全链路溯源**：查询、来源 record/provenance/sha256、每步 status/耗时/数据、validation、artifacts |

## 失败处理（exit code）

| 码 | 含义 | 处理 |
|---|---|---|
| 0 | 成功，`validation.ok=true` | 照“验收证据”复核 |
| 1 | 运行时错误或校验失败 | 读 `--json` 里 `steps[].status=="failed"` 的那步 `data.traceback` |
| 2 | `route` 没识别出拓扑/结构名/id | 补 `--topology`，或改用 `--spec` |
| 3 | 引擎模块 `NotImplementedError` | 该模块还没实现，别假装跑通 |

常见原因：
- `topology mismatch` → `verify-topology` 失败，换记录或先人工核实（见 cif-fetch 的 evidence 三档）；
- `vacuum too small after adjustment` → 结构在真空方向不自洽，先 `--surface` 再 `--vacuum`；
- `no hits` → 拓扑拼写/数据源不对，先 `cif-fetch` 单独试；
- 导出报 `unsupported export format` / `KeyError` → 该格式/元素当前引擎不支持，换 vasp/cif/xyz。

失败也会写 `manifest.json`，`steps` 里能看到停在哪一步。

## 验收证据（必须贴，不许只说“完成”）

1. 命令的 **exit code = 0** 且 `--json` 里 `"ok": true`；
2. `manifest.json` 里 `source.record` 含 `record_id/formula/topology/topology_evidence/doi`，`source.provenance.sha256` 与 `raw.cif` 实测 sha256 一致；
3. `steps` 里 `verify-topology`（若请求了 sod）`data.evidence ∈ {metadata, verified, curated}` 且 `data.ok=true`；
4. `repair` 的 `data.added_h` 与 `repaired.cif` 实测 H 增量一致（ZIF-8 应为 +120，156→276 原子）；
5. 有 `supercell` 步骤时：`after == before*4`（2x2x1）；**有 surface 步骤时**看
   `surface.data.frame=="slab"`、`in_plane_reps==[2,2]`、`atoms_after_reps == base_atoms*4 == len(slab.cif)`（demo 552→2208）；
6. `surface`/`vacuum` 的 `data.measured`（或 `vacuum_measured`）≥ 目标 15 Å（实测，不是名义值）；
7. `structure.vasp` 能读回且原子数 == `final.cif`；
8. `validation.ok=true`；`report.md` 含 来源/执行步骤/校验/产物 四个小节。

```powershell
& $PY -m cifkit validate runs\demo_sod_zif8\final.cif --json   # 单看最终结构
& $PY D:\Dev\Project5-skill-cif\scripts\verify_demo.py runs\demo_sod_zif8
```

## 常见坑

- **`route` 成功 ≠ `pipeline` 成功**：先 route 看 `plan.json`，参数错在这一步最便宜。
- **2x2x1 是 slab 面内重复**：默认 `frame=slab`，demo slab 552→2208；别按“×4 超胞”或“×8 超胞”字面理解，先看 `info.slab`。
- **真空是实测的**：报告里写 `measured` 值；别拿 `c` 轴长度当真空。
- **中文字符串**：PowerShell 里给 `$env:PYTHONIOENCODING='utf-8'`，否则 `manifest` 中文可能乱码。
- **不要 `--ingest` 做实验**：会往库目录写副本；除非用户明确要入库。
- **重跑可复现**：同一查询会命中缓存，`raw.cif` 内容不变；`runs/<同名>` 会覆盖，换 `--outdir` 保留前后对照。

## 实测记录（2026-11-05，本机 .venv）

| 命令 | 结果 |
|---|---|
| `selftest --verbose` | 7/7 passed，exit 0 |
| `route "<原句>"` | topology=sod、supercell=2x2x1、surface=(1,1,1)、vacuum=15.0、formats=vasp,cif,xyz |
| `pipeline "<原句>" --outdir runs\demo_sod_zif8 --format vasp,cif,xyz --json` | exit 0（缓存热时 ~10 s，stdout 是干净 JSON，步骤日志走 stderr）；步骤见下 |
| `pipeline --spec runs\spec.json --outdir runs\spec_run` | exit 0：local CIF 138 → standardize 276 → supercell 2x2x1 **1104** → export cif,vasp → validate PASS(9)；`--spec` 支持 UTF-8/UTF-8-BOM |
| `scripts\verify_demo.py runs\demo_sod_zif8` | **8/8 PASS**（sha256/DOI/拓扑/补氢/2x2x1/真空/VASP 读回/校验/report；DESIGN §1 共 9 条，其中 8 项自动复核） |

demo 管线实测（`runs\demo_sod_zif8\manifest.json`）：

```text
resolve        core-mof:SI/NCR/both/ja204757x_si_002_ASR_pacman.cif  Zn12 C96 N48  156 atoms  DOI=10.1021/ja204757x
verify-topology evidence=verified  （与 CR/ASR 2015[Zn][sod]3 的 underlying net 签名一致）
repair         add_H=120  atoms 156 -> 276   （C 96/96 四配位，Zn CN={4:12}）
standardize    atoms=276  Zn12 H120 C96 N48
surface        hkl=(1,1,1) frame=slab reps=(2,2,1) base=552 after=2208 abc=[48.166,48.166,34.283] vacuum=15.000 (min_image_distance=15.2396)
vacuum         target=15.0  measured=15.000 Å（垂直；min_image_distance 15.240 Å 另计）
export         vasp, cif, xyz
validate       PASS checks=12
render         preview.png
manifest       runs\demo_sod_zif8\manifest.json（tool 0.1.0 / python 3.14.8）
```

产物：`raw.cif`(10 816 B)、`repaired.cif`(15 379 B)、`standardized.cif`(15 379 B)、`slab.cif`=`final.cif`(121 521 B)、
`structure.vasp`(152 719 B)、`structure.cif`(121 521 B)、`structure.xyz`(134 797 B)、`preview.png`(300 594 B)、
`report.md`(5 248 B)、`manifest.json`(74 320 B)。

