# 管线逐步验收（PIPELINE）

> 目标：把 `docs/DESIGN.md` §1 的验收标准逐条落到“能看到什么、用什么命令验、失败长什么样”。
> 入口：`D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe -m cifkit`（命令面冻结于 DESIGN §6c）。
> 对应技能：`catalog/cif-workbench`（总入口），单步能力见 `catalog/cif-{fetch,repair,geometry,export}`。

## 0. 环境与自检

```powershell
$PY = 'D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe'
Set-Location 'D:\Dev\Project5-skill-cif'
$env:PYTHONIOENCODING='utf-8'

& $PY -m cifkit --version         # cifkit 0.1.0
& $PY -m cifkit selftest --verbose  # 7/7 passed 才算环境 OK（imports/parse demo）
```

离线缓存必须存在（否则 resolve 会尝试联网）：`_cache\core-mof-2024\CoREMOF2024DB.zip`、`ASR_data_SI_20250204.csv`。

## 1. 一条命令跑通

```powershell
$DEMO = "帮我下载典型的RCSR为sod的mof，需要碳上补充氢，创建一个2x2x1的超胞（Supercell），沿(111)面切出表面，并加上15Å的真空层，导出为计算化学软件使用的格式。"
& $PY -m cifkit route $DEMO      # 先看解析：拓扑 sod / 超胞 2x2x1 / (111) / 15 Å / vasp,cif,xyz
& $PY -m cifkit pipeline $DEMO --outdir runs\demo_sod_zif8 --format vasp,cif,xyz --json
& $PY scripts\verify_demo.py runs\demo_sod_zif8
```

`run_demo.py` 是等价封装：`& $PY scripts\run_demo.py --outdir runs\demo_sod_zif8 --fresh`（跑完自动 `verify_demo`）。

## 2. 步骤与每步的“证据点”

`pipeline` 的执行计划（`runs\<dir>\plan.json` 可复看）：

| # | 步骤 | 做什么 | 证据（`manifest.json` → `steps[]` / 产物） |
|---|---|---|---|
| 1 | `resolve` | `sources.resolve(spec)` 检索并取回结构（缓存命中不重复下载） | `source.record`（record_id/formula/topology/evidence/doi）、`source.provenance.sha256/url`；`raw.cif` |
| 2 | `verify-topology` | 用元数据或结构比对核实 `sod` | `data.ok=true`、`data.evidence ∈ {metadata, verified, curated}`、`data.detail` |
| 3 | `repair` | 补碳上 H / 解析无序 / 清近邻 | `data.added_h`、`data.removed_atoms`、`data.resolved_disorder`、`warnings[]`；`repaired.cif` |
| 4 | `standardize` | 原胞/常规胞、去重复（无 cluster 时） | `data.natoms`；`standardized.cif` |
| 5 | `surface` | 沿 `(111)` 切 slab（层厚 15 Å），并把 `supercell=2x2x1` 作为 **slab 面内 2x2 重复**（`frame=slab`） | `data.frame=="slab"`、`data.in_plane_reps==[2,2]`、`data.base_atoms`、`data.atoms_after_reps`、`data.vacuum_measured`、`data.termination`；`slab.cif` |
| 5b | `supercell` | **仅当没有 `surface` 时**：普通超胞（原子数 = 输入 × `nx*ny*nz`；2x2x1 → ×4） | `data.before/after/expected`；`supercell.cif` |
| 6 | `vacuum` | 精确设置真空并**实测** | `data.measured` 必须 ≥ `spec.vacuum`（15.0）；`final.cif` |
| 7 | `export` | 按格式写出（VASP/CIF/XYZ…） | `data.files`；`structure.vasp`、`structure.cif`、`structure.xyz` |
| 8 | `validate` | 组成/原子数/近邻/悬空键/真空校验 | `validation.checks[]` 全 ok（error 级）；`validation.metrics` |
| 9 | `render` | 预览 PNG（可选步骤，失败不阻断） | `preview.png` |
| 10 | `manifest` | 写 `manifest.json` + `report.md` | 全链路 `artifacts{}`、`environment`（工具版本） |

执行顺序固定：`resolve → verify-topology → repair → standardize → surface → vacuum → export → validate → render → manifest`。
`surface` 与 `supercell` 互斥：给了 `surface` 时不会再单独跑 `supercell`，`2x2x1` 以 `reps` 传给 `make_slab`。
任一步失败即停，但 `manifest.json` 仍会写出，`steps[].status=="failed"` + `data.traceback` 指出原因。

### 2.1 demo 的已知实测数字（DESIGN §7.1）

| 步骤 | 结果 |
|---|---|
| 原始 CIF | `SI/NCR/both/ja204757x_si_002_ASR_pacman.cif`，Zn12 C96 N48，**156** 原子，0 H，a=17.029 Å |
| 补氢 | +120 H → **276** 原子（Zn12 C96 H120 N48），每个 C 四键 |
| 标准化 | 常规胞 I-43m，a≈16.94 Å，**276** 原子 |
| (111) slab 基胞 | **552** 原子（276 的 (111) 面切两次得到） |
| slab 面内 2x2（`surface.reps=2x2x1`） | **2208** 原子（= 276 × 8） |
| 真空 15 Å | 实测 gap ≥ 15.0 Å（`vacuum_measured`） |
| 导出 | `structure.vasp` 2208 原子，可被 pymatgen 读回 |

`frame=cell` 的字面语义对照：先 2x2x1 超胞 1104 原子 → 切该胞 (111)；取向不是立方 (111)，只作 caveat。

## 3. 八条验收标准（DESIGN §1 → 怎么验）

| # | 标准 | 命令 / 检查点 | 通过判据 |
|---|---|---|---|
| 1 | 真实下载/缓存 SOD 拓扑 MOF（ZIF-8），带来源/DOI/sha256 | `manifest.source.record`、`manifest.source.provenance` | `record.topology=="sod"`、`topology_evidence ∈ {metadata,verified,curated}`、有 `doi`、`sha256(raw.cif)==provenance.sha256` |
| 2 | 补氢前后对照（缺多少 H → 补多少，逐碳价态） | `steps[repair].data.added_h`；`verify_demo.py` 的“3 碳上补氢正确” | H `0 → 120`、`added_h==120`、每个 C 共价邻接数为 4 |
| 3 | 2x2x1 超胞/面内重复（原子数 = 原胞 × 8） | `steps[surface].data`（`base_atoms/atoms_after_reps/in_plane_reps`）/ `verify_demo` “4 2x2x1 重复原子数” | `atoms_after_reps == base_atoms × 4` 且 `== len(slab.cif)`；demo 276→552→2208 = 276×8 |
| 4 | (111) slab（表面周期、层厚、终止面依据） | `steps[surface].data`、`slab.cif` | `hkl==[1,1,1]`、层厚/终止面记录在 `data`，`slab.cif` 可读 |
| 5 | 真空层 ≥ 15 Å（实测，不是名义值） | `steps[vacuum].data.measured`、`verify_demo` “5 slab+真空层” | 实测 min-distance ≥ 15.0 Å（容差 1e-3） |
| 6 | 计算化学格式导出（至少 VASP POSCAR + CIF/XYZ） | `structure.vasp/.cif/.xyz`、`export --json` | 文件非空；`structure.vasp` 读回原子数 == `final.cif` |
| 7 | 结构校验报告 + 预览图 | `validation`、`report.md`、`preview.png` | `validation.ok==true`、无 error 级 check；`preview.png` 存在 |
| 8 | `manifest.json` 全链路溯源 + 可复现 | `manifest.json`（查询/来源/下载/每步耗时/校验/工具版本） | 字段齐全；同查询重跑命中缓存、`raw.cif` sha256 不变 |

### 独立复核（不信自报）

```powershell
& $PY scripts\verify_demo.py runs\demo_sod_zif8
# 期望：8/8 通过；若某项 FAIL，先看它下面那行 detail
```

`verify_demo.py` 直接从产物结构重新计算：sha256、H 数、C 键数、超胞原子数、真空 gap、导出读回、manifest 完整性。

## 4. 产物清单（`runs\demo_sod_zif8\`）

```text
plan.json              # 解析出的步骤计划
raw.cif                # 下载的原始 CIF（未修复）
repaired.cif           # 补氢/修复后
standardized.cif       # 标准胞（pipeline 默认步骤）
slab.cif               # (111) slab，已含 2x2 面内重复（demo 2208 原子）
                       # 注：有 surface 步骤时不会生成 supercell.cif
final.cif              # 真空设置后的最终结构
structure.vasp         # VASP POSCAR
structure.cif
structure.xyz
preview.png            # 结构预览
report.md              # 人读报告（来源/执行步骤/校验/产物）
manifest.json          # 全链路溯源
```

## 5. 失败排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `route` 退出码 2 | 原话没解析出 topology/name/id | 补 `--topology sod`，或用 `--spec` |
| `no hits` | 拓扑码/数据源不对 | 先 `& $PY -m cifkit fetch --topology sod --json` 单独验 |
| `topology mismatch` | 取到的记录不是该拓扑 | 换记录；确认 `topology_evidence`，不要手改结论 |
| `vacuum too small after adjustment` | 真空方向/结构不自洽 | 先 `geom --surface` 再 `--vacuum`，或检查 slab 厚度 |
| `supercell atom count mismatch` | 超胞实现或输入异常 | 看 `data.before/after/expected`，重跑最小复现 |
| exit code 3 / `not implemented` | 引擎模块未实现 | 该步不可用，不要声称跑通；等对应模块合入 |
| 中文乱码 | 终端编码 | `$env:PYTHONIOENCODING='utf-8'` |

## 6. 单步最小复现（出问题时缩小范围）

```powershell
# 只补氢
& $PY -m cifkit repair "D:\Dev\Project5-skill-cif\tests\data\zif8_raw_hfree.cif" -o runs\mini\repaired.cif --add-h --json
# 只超胞
& $PY -m cifkit geom "D:\Dev\Project5-skill-cif\tests\data\zif8_cr_sod.cif" -o runs\mini\supercell.cif --supercell 2 2 1 --json
# 只导出 + 读回
& $PY -m cifkit export runs\demo_sod_zif8\final.cif --format vasp,cif,xyz -o runs\mini\export --json
& $PY -m cifkit validate runs\mini\export\structure.vasp --json
```

## 7. 实测记录

环境：`cifkit 0.1.0`，`.venv` Python 3.14.8，demo `manifest.json` `created_at = 2026-11-05T15:11:11+08:00`；
所有命令在 `D:\Dev\Project5-skill-cif` 下、`$env:PYTHONIOENCODING='utf-8'` 执行。

### 7.1 命令与 exit code

| 命令 | exit | 结果 |
|---|---|---|
| `selftest --verbose` | 0 | 7/7 passed（imports/parse demo） |
| `route "<原句>"` | 0 | topology=sod、supercell=2x2x1、surface=(1,1,1)、vacuum=15.0、formats=vasp,cif,xyz |
| `pipeline "<原句>" --outdir runs\demo_sod_zif8 --format vasp,cif,xyz --json` | 0 | 缓存热时约 **9–15 s**；全部步骤 ok |
| `pipeline --spec runs\spec.json --outdir runs\spec_run` | 0 | local CIF 138 → 276 → supercell 2x2x1 1104 → export cif,vasp → validate PASS(9)；`--spec` 支持 UTF-8 / UTF-8-BOM / UTF-16 |
| `scripts\verify_demo.py runs\demo_sod_zif8` | 0 | **8/8 PASS**（约 6–10 s） |

### 7.2 每步实测数字

| 步骤 | 实测 |
|---|---|
| `resolve` | `core-mof:SI/NCR/both/ja204757x_si_002_ASR_pacman.cif`，Zn12 C96 N48，156 atoms，0 H，DOI `10.1021/ja204757x`，sha256 `c6939cf7…` 与 `raw.cif` 一致（cache 命中，未重复下载） |
| `verify-topology` | `evidence=verified`：与 `core-mof:SI/CR/ASR/2015[Zn][sod]3[ASR]1.cif` 的 underlying net 签名一致（配位序列 4,10,20,34,52,74,100,130；环分布 4/6/8 元环） |
| `repair` | `add_H=120`、156 → **276** 原子、`route=rdkit-capped`、C 96/96 四配位、Zn `CN={4:12}`、`warnings=[]` |
| `standardize` | **276** 原子（I-43m，a≈17.03 Å）——注意：早期 build 曾把补氢后的 276 翻倍成 552，已加 primitive-multiple guard 修复（14:53 前后） |
| `surface` | frame=`slab`、reps `(2,2,1)`、in_plane_reps `[2,2]`、base **552** → after **2208**；abc `[48.166, 48.166, 34.283]`；`vacuum_measured=15.000`（垂直）、`min_image_distance=15.2396`；elapsed 2–4 s（随机器负载） |
| `vacuum` | target 15.0 → 垂直真空 measured **15.000 Å**（`min_image_distance` 15.240 Å 另计） |
| `export` | vasp/cif/xyz 全部写出；`structure.vasp` 152 719 B，读回 2208 原子 == `final.cif` |
| `validate` | PASS，**12 checks**，error 为空（`dangling_bonds` 仅 warning） |
| `render` | `preview.png` 生成（300 594 B） |

> `--surface-frame cell` 对照实测：input 276 → cut_cell 1104 → base/after 2208，abc `[37.876, 37.876, 42.485]`、
> beta 101.54° —— 取向不是立方 (111)，证实默认 `slab` 语义才是 demo 想要的表面。

### 7.3 独立验收 `verify_demo.py`（不信自报，从产物结构重算）

```text
[PASS] 1 来源追溯（sha256/record/DOI）    sha256 matches=True record=core-mof:SI/NCR/both/ja204757x_si_002_ASR_pacman.cif doi=10.1021/ja204757x fmt=True consistent=True note_ok=True
[PASS] 2 拓扑 sod 已核实                  evidence=verified detail=与参考 core-mof:SI/CR/ASR/2015[Zn][sod]3[ASR]1.cif 的 underlying net 签名一致
[PASS] 3 碳上补氢正确                     H 0->120 (added=120) C_env_ok=True n_bad_C=0 H/Zn=120/12 C=96
[PASS] 4 2x2x1 重复原子数                 frame=slab reps=(2, 2, 1) slab_base=552 after_reps=2208
[PASS] 5 (111) slab + 真空层              slab_atoms=2208 final_atoms=2208 measured_vacuum=15.000Å target=15.0 reported=14.999999999999993
[PASS] 6 计算化学格式导出                 structure.vasp atoms=2208 final_atoms=2208 match=True
[PASS] 7 结构校验通过                     checks=12 errors=[]
[PASS] 8 report.md / manifest 完整        report=True steps=10 artifacts=12
结果：8/8 通过
```

> `verify_demo.py --online` 还会把 DOI 送 Crossref 解析（`status=200 title='Capture of Volatile Iodine, ...'`）；离线模式只做格式/一致性/curated 标注检查，并在 detail 里注明"existence 未联网核验"。

> `artifacts=12` = raw/repaired/standardized/slab/final + 3 个导出的 structure.* + preview + report + manifest + library 目录（`--ingest`）。

### 7.4 产物（当前 `runs\demo_sod_zif8\`）

```text
raw.cif 10 816 B       repaired.cif 15 379 B     standardized.cif 15 379 B
slab.cif 121 521 B     final.cif 121 521 B       structure.cif 121 521 B
structure.vasp 152 719 B   structure.xyz 134 797 B   preview.png 300 594 B
report.md 5 248 B      manifest.json 74 320 B
```

`manifest.json` 里具备：`query/spec`、`environment`（python/pymatgen/ase 版本、可执行路径）、`source.record+provenance`
（record_id/DOI/sha256/dataset/doi/license/cache_reused）、每个 step 的 `status/detail/data.elapsed_s`、`validation`、
`artifacts`；同一查询重跑 `cache_reused=true`、`raw.cif` sha256 不变。

---

## 8. Round 2：评审后的改进（2026-11-05）

Round 1 独立评审（[REVIEW-ROUND1.md](REVIEW-ROUND1.md)，结论 PASS、无 P0）提出 4 个 P1 与 7 个 P2，已全部处理：

| ID | 问题 | 修复 | 回归测试 |
|---|---|---|---|
| P1-1 | `pipeline --json` 的 stdout 被 `[step] ok …` 日志污染，不是合法 JSON | JSON 模式下步骤日志重定向到 stderr，stdout 只有一份 JSON | `tests/test_cli.py::test_pipeline_json_stdout_is_pure_json` |
| P1-2 | PIPELINE / SKILL 把 `min_image_distance` 写成 `vacuum_measured`（15.2396/15.240） | 统一改为垂直真空 **15.000**，`min_image_distance=15.2396` 单独列出 | 文档 grep + 本节表格 |
| P1-3 | §7.3 粘贴的 `artifacts=10` 与实测不符 | 实测 `artifacts=12`（含 manifest/report/library） | 本节 §7.3 |
| P1-4 | 4 个产物字节数过期 | §7.4 / SKILL.md 已按当前 build 更新 | 本节 §7.4 |
| P2-1 | `--spec` 遇到 UTF-8 BOM / UTF-16 报原始 JSONDecodeError | CLI 自动识别 UTF-8 / UTF-8-BOM / UTF-16 并给出可读错误 | `test_spec_with_utf8_bom` / `test_spec_with_utf16_encoding` |
| P2-2 | 失败 run 的 `report.md` 重复记录 failed 步骤、缺第 4 节 | 步骤失败只记录一次；失败 run 的校验节写“未运行（步骤 X 失败）”；失败 run 也写 manifest/report | `test_failed_run_writes_report_without_duplicate_steps` |
| P2-3 | `report.md` 不含 slab 厚度/终止面依据 | 新增「3. 结构几何（实测）」：切面/frame/reps/厚度/终止面/垂直真空/最小像距离/最终晶胞 | 手工检查 report |
| P2-4 | `manifest.artifacts` 不含 manifest/report 自身 | 两者互相登记（Round 4 起改为先登记再渲染 report，见 §8.1；`--ingest` 写完后再入库） | `test_manifest_artifacts_include_manifest_and_report` |
| P2-5 | `verify_demo` 检查名含 DOI 但未校验 DOI | 校验 DOI 正则、record/provenance 一致性、curated 标注；`--online` 时送 Crossref 解析（实测 `status=200 title='Capture of Volatile Iodine, …'`）；伪造/删标注均能 FAIL | 手工构造 tamper 用例 |
| P2-6 | DESIGN §1 是 9 条、文档说 8 条 | 统一表述为“9 条验收，其中 8 项由 verify_demo 自动复核” | README / SKILL.md |
| P2-7 | standardize 的整数倍守卫依据未落盘 | pipeline 的 `standardize` 步骤 data 写入 `geom_info.kept/reason` | 手工检查 manifest |

### 8.1 Round 3 复核后的收尾（Round 4）

Round 2 二次复核（[REVIEW-ROUND2.md](REVIEW-ROUND2.md)，PASS；4/4 P1 FIXED，无新 P0/P1，无回归）剩 2 个 PARTIAL + 6 个新 P2，处理如下：

| ID | 问题 | 修复 |
|---|---|---|
| P2-5 PARTIAL | 伪造 DOI / 删除 `doi_note` 仍能通过 | `verify_demo` 增加 DOI 正则、`record.doi == provenance.doi` 一致性、curated 标注必需项；新增 `--online` 走 Crossref 解析（离线时 detail 明确写"existence 未联网核验"）。伪造 record.doi、删 doi_note 均实测 FAIL |
| P2-6 PARTIAL | README 仍写"7 条 CLI / 126" | README 改为 8 条 / **127**；PIPELINE §8 同步 |
| 新 P2-3/4/5 | §7.3 非逐字、§7.1 未写 UTF-16、§7.2 耗时漂移 | §7.1 写 UTF-8/BOM/UTF-16，§7.2 耗时改 2–4 s，§7.3 贴当前实测（含 `reported=`、完整检查字段） |
| 新 P2-6 | 非 `--ingest` 的 report 产物清单不含 report/manifest 自身 | `finish_run` 先把 report/manifest 登记进 artifacts 再渲染 report，两种 run 的"产物"清单与 `manifest.artifacts` 一致 |
| 新 P2-2 | 工作树未提交、`check_all.py` 未跟踪 | 最终 commit 一并提交 |
| 新增 | 一键体检 | `scripts/check_all.py`：selftest → pytest（或 --fast）→ verify_demo → router route/eval/ci |

附加：`tests/test_cli.py` 增加 UTF-16 spec 用例（8 条），应用层支持 UTF-16BE。

附带的健壮性增强：`repair/geom -o` 自动创建父目录；`export` 对不支持的格式返回 exit 2 并列出可用格式。
测试总数 119 → **127**（新增 `tests/test_cli.py` 8 条 CLI 合同测试；cif→anything 扩展后全量为 **297**（默认 293 passed + 4 条 opt-in/skipped））。

### 8.2 数据源扩展（CoRE MOF / COD / Materials Project / AFLOW）

原先只有 CoRE MOF 2024 + COD + local；本轮补齐 **Materials Project** 与 **AFLOW**，
并加 `cifkit sources` 让 agent 先看数据源状态再选型。

| source | 实现 | 需要的条件 | 实测 |
|---|---|---|---|
| `materials-project` | `sources/materials_project.py` | `MP_API_KEY`（免费申请） | 无 key 时失败信息可读、联网 401 被转成 ValueError；**mock 测试**覆盖 search/fetch（CIF 由 structure dict 生成、JSON/CIF 双 sha256）；本机无 key 故未做 live 检索 |
| `aflow` | `sources/aflow.py` | 免 key | **live 实测**：AFLUX 检索 ZnO（3 hits）、按 aurl 下载 Zn A9 CIF、跑完 pipeline（7 artifacts、exit 0）；CIF 文件名含冒号需 percent-encode（`%3A`） |
| `cod` | 已有 | 免 key | live 实测 id 7111973 下载与落盘 |
| `core-mof` | 已有 | 本地缓存 | demo 主路径不变 |

- 选型/经验表见 `docs/SOURCES.md` 第 7d 节；技能正文 `catalog/cif-fetch/SKILL.md`。
- 自然语言：`spec.parse_request` 现在能识别无机化学式（GaN/Fe2O3）与 `mp-149`/AFLOW aurl；
  `auto` 数据源规则：化学式 → aflow，MOF 名称 → core-mof；显式 id 时清空误识别的 formula token。
- 校验：`validate` 的 hydrogen 检查区分「有机缺氢」与「无机/计算就绪 no-op」——
  前者（有 interior C 缺键）仍是 error，后者（GaN 这类 0 H 无机结构）记为 info，不再误判失败。
- 路由：intent `cif-structure-pipeline` 增加数据源关键词与 examples；评测 79 条全过、
  负例 0/25；`ci.py --fast` exit 0。
- 测试：新增 `tests/test_sources_mp_aflow.py`（11 条，MP mock + AFLOW mock/live + auto 选源）、
  `tests/test_cli.py` 中 `sources`/MP 无 key 2 条、`test_spec`/`test_validate` 各若干；全套 **297** 条（默认 293 passed + 4 条 opt-in/skipped）。

### 8.3 进阶应用套件（第 5 轮 4 个测试实例）

`usecases/` 下新增 4 个可复跑工作流，对应技能 `catalog/cif-usecases/SKILL.md`。Round 2 起，
它们已固化成 `cifkit` 的 4 个子命令（实现：`cifkit/usecases_cli.py`，内部 **import 原脚本函数**，
不拼 subprocess；`--json` 时 stdout 纯 JSON、脚本日志走 stderr；产物只写 `--outdir`）：

```powershell
& $PY -m cifkit teach   --spacegroup Fd-3m --outdir runs\uc\fd3m [--offline] [--json]
& $PY -m cifkit bravais --outdir runs\uc\bravais [--bain-range 0.9:1.7:0.01] [--json]
& $PY -m cifkit metals  --outdir runs\uc\metals [--elements all|Fe,Cu,Mg] [--zip] [--json]
& $PY -m cifkit fec     --outdir runs\uc\fec [--zip] [--json]
```

注册方式（`cifkit/cli.py` 由 Lead 加两行，本模块不改 cli.py）：

```python
from cifkit.usecases_cli import register as register_usecase_commands
register_usecase_commands(sub)      # build_parser() 末尾，return p 之前
```

注册前等价入口：`python -m cifkit.usecases_cli <cmd> ...`（测试自动检测两者）。

| 需求 | 子命令 | 目录（旧脚本 fallback） | 关键产物 | 自检 |
|---|---|---|---|---|
| Fd-3m 点群典例教学图 | `teach` | `usecases/u1_fd3m/` | `data/structures/`+`data/examples.csv`+`figures/fd3m_examples.png`（spglib 全部 #227） | `pytest tests/test_usecase_cli.py` |
| cF vs tI / 14 种布拉维 | `bravais` | `usecases/u2_bravais/` | `data/{bain_path,bain_tolerance,bravais14,equivalences,hR_alpha_scan}.csv` + 3 张 PNG | 同上 |
| 纯金属晶格+表面能输入 | `metals` | `usecases/u3_metals/` | `elements/<El>/{bulk,slab,POSCAR,INCAR,KPOINTS}`、`metals_summary.csv`、`metals_kit.zip` | 同上 |
| Fe-C 化合物/相图套件 | `fec` | `usecases/u4_fec/` | 7 结构、`data/hull_points.csv`、`figures/fe_c_hull.png`、`vasp_inputs/`、`fe_c_kit.zip` | 同上（断言 Fe3C=+0.0456） |

实测（2026-11-05，`.venv`）：`teach --offline` → 6/6 #227（约 6 s）；`bravais --bain-range 0.9:1.7:0.05`
→ bain 18 点、14/14 点阵、12 组等价、3 PNG（约 6 s）；`metals --elements Fe,Cu,Mg` → 3/3 元素、
每元素 7 个文件、真空 15.0 Å（约 5 s）；`fec --zip` → 7 结构、10 个 vasp_inputs 目录、
Fe3C E_above_hull=+0.0456、`fe_c_kit.zip`（约 6 s）。`pytest tests/test_usecase_cli.py -q` → 12 passed + 1 skipped（全量 opt-in），约 28 s。
四命令 `--json` 均 stdout 可 `json.loads`；`teach --spacegroup Pnma` / `bravais --bain-range 1.7:0.9` /
`metals --elements Xx` 均非 0 退出且报错清晰。

旧交付物独立验收仍可用：`python usecases/verify_usecases.py` → 22/22 PASS。
路由：intent `cif-advanced-usecases` + 4 条评测（`cif-usecases` 技能不变）。
数据源经验：AFLOW CIF 的 PAW 势名归一化（已修在 `sources/aflow.py`）；AFLUX 的 `spacegroup_relax` 过滤不可靠，
必须客户端过滤；LIB1 不能按最低 energy_atom 选元素基态；无 MP key 时不伪造 MP 结果。

### 8.4 round 2 的工程化改进（并发/性能/数据源）

- `cifkit batch`：多结构并发（独立子进程 + batch_manifest.json）；3 条 demo 串行 41.0 s → 并发 14.8 s。
- `make_slab` 进程内缓存：同参数第二次 2.12 s → 0.014 s；键含结构 hash + 全部几何参数。
- CoRE 索引构建：`cifkit/locks.py` 文件锁 + 原子写，3 进程并发冷建 8300 条无损坏；
  `scripts/bootstrap_data.py --check` 可诊断冷启动缓存。
- 数据源：`qmof` 本地镜像适配器（官方 figshare/GitHub 本环境不可达 → 未 live 实测，诚实标注；
  缺失时报可操作错误）。
- 细节：[docs/PERFORMANCE.md](PERFORMANCE.md)、[docs/ROBUSTNESS.md](ROBUSTNESS.md)。

### 8.5 cif → anything（round 3：格式/输入包/特征/数据集）

- **格式**：`cifkit convert FILE --to <fmt1,fmt2,...> --outdir DIR` —— 31 种格式（含 EXTXYZ/JSON/PDB/SDF/
  MOL/CFG/GROMACS/GEN/AIMS/CASTEP/ABINIT/CRYSTAL/Gaussian/NWChem/ONETEP/DMol3/Turbomole/SHELX…），
  每个格式写出后回读校验；模板类明确标 `template`。
- **输入包**：`--bundle vasp,qe,cp2k,lammps,gromacs,gaussian,orca,abacus,dftb,siesta,nwchem,aims`（12 种），
  结构 + 输入模板 + README + `missing`（POTCAR/UPF/basis/skf/力场等）。`pipeline --bundle` 可在流水线末尾顺手生成。
- **特征表**：`cifkit features FILE_OR_DIR --out features.csv [--json] [--jobs] [--no-rdf] [--topology]`
  —— 组成/晶格/对称性/配位数/RDF/拓扑/H/金属分数；坏文件单独记 error，不中断。
- **数据集**：`cifkit dataset --from-runs runs/ --outdir dataset/ [--label-key topology]`
  —— `dataset.csv/jsonl` + `structures/` + `dataset_manifest.json`（n_ok/n_failed/errors/sha256）。
- 文档：`docs/EXPORT.md` §6（能力矩阵）、`docs/FEATURES.md`（特征字典 + dataset schema）。

### 8.6 自检工具（round 10）

| 工具 | 作用 | 命令 |
|---|---|---|
| `scripts/check_all.py` | 一键健康检查（7 组：selftest / pytest / verify_demo / router / eval / ci / **check_skill cif-***） | `python scripts\check_all.py --fast` |
| `scripts/check_all.py --adversarial` | 追加对抗性自检（convert 边界 / 格式验证器可被欺骗 / 环计数语义 / check_skill 真跑） | `python scripts\check_all.py --adversarial` |
| `scripts/verify_formats.py` | 31 格式 + 12 输入包的独立回读验证（第三方库） | `python scripts\verify_formats.py [--only vasp,cif]` |
| `scripts/adversarial_check.py` | 上面那张表的实现（18 项破坏性检查，写 `runs/lead_verify_r11/adversarial_check.json`） | `python scripts\adversarial_check.py` |

### 8.7 嵌入接口与商用合规（round 13）

- **库接口** `cifkit/api.py`：`capabilities/features/features_many/convert/dataset/topology/validate`，
  纯 dict 返回、无全局状态、线程安全；`convert` 支持**内存返回**（text / base64）不落盘。
- **服务接口** `cifkit/service.py`：`handle(request) -> response`，错误码稳定（400/404/502/500），
  secret 参数打码，自带 stdlib HTTP 服务器用于联调；可挂 FastAPI/Flask/Lambda。
- **契约** `cifkit/contract.py` + `cifkit/schemas/*.json`：request/response/ops/feature_row；
  派发前校验，`detail.violations` 给出 JSON 路径；`python -m cifkit.contract --dump` 重新生成。
- **许可**：`LICENSE`(MIT) + `LICENSING.md`（代码/数据分离、依赖分类、商用清单）；
  `scripts/license_audit.py` 审计依赖（**7 宽松 / 1 弱 copyleft ASE / 1 强 copyleft openbabel**），
  `scripts/verify_formats_no_gpl.py` 证明**核心不需要 GPL 的 Open Babel**。
- 测试：`tests/test_api.py`(11) + `tests/test_service.py`(8) + `tests/test_contract.py`(8)。
- 局限：见 `docs/LIMITATIONS.md` §J（接口/平台）与 §L（许可/商用）。

### 8.8 托管策略与许可扫描（round 14）

- `cifkit/platform.py`：`Policy`（read/write roots、allow_network、max_bytes/atoms/inputs、
  timeout_s、max_concurrency/queue_size）+ `GuardedService`（沙箱 → 403、体积 → 413、背压 → 503、
  超时 → 504、`authorizer=` 租户钩子、`stats_snapshot()`）。
- `api.fetch`：联网 op 的**内联**版本（记录 + provenance + CIF 文本，默认隐藏本机路径、绝不带 key）；
  受 `allow_network` 策略控制。
- `scripts/sca_scan.py`：SCA-lite，按"代码 / 注释 / docstring"分类标记；`--strict` 作为 check_all 第 8 组
  （当前源码级 copyleft = 0，mention-only = 2）。
- 局限表：J1/J2/J5/J8 与 L7 由 🔴 降为 🟡/✅（剩余 🔴 为 A6/C2/C3/F6/H3/H4，均需外部条件）。

### 8.9 流式数据集与分页（round 15）

- `cifkit.dataset`：`iter_manifests`（惰性遍历）、`iter_runs`（流式算特征）、
  `build_dataset(stream=True)`（默认；JSONL 先行，再流式回读生成 CSV，全程只持 1 行）、
  `iter_jsonl`/`count_jsonl`；`stream=False` 保留为对照实现，两者输出一致（测试保证）。
- `api.dataset_rows`：只读 `offset+limit` 行做分页（含 `total`/`has_more`/`columns` 投影）；
  `api.features_many` 支持 `offset/limit/total`。
- `features_many(executor=...)`：线程/进程可选；**实测 `jobs>1` 无加速**（GIL + 小工作量），
  默认线程，`--jobs` 不作为提速承诺。
- 基准：`scripts/bench_api.py`（吞吐/并行/内存/并发曲线 + 纯 Python 对照实验）→
  `runs/bench_api.json`；解读见 `docs/PERFORMANCE.md` §10。

### 8.10 统一 HTTP 客户端与限流（round 16）

- `cifkit/sources/http.py::HttpClient`：可重试状态（408/425/429/5xx）、不可重试（4xx）、
  指数退避+25% 抖动、`Retry-After`（秒/HTTP-date，受 `max_backoff` 限制）、
  同 host 最小间隔 pacing（默认 0.25s，env 可覆盖）、可注入 `sleeper`/`opener`。
- COD / AFLOW / MP 三个适配器改用该客户端（行为兼容：错误类型、401/403→ValueError 映射不变）。
- 验证方式：**本地 mock 服务器**（`tests/test_http_client.py` 10 条、`tests/test_sources_http.py` 6 条），
  包括"服务器允许 5 req/s 时 30 次批量抓取违规 0 次"与"被限流后退避重试最终成功"。
- 诚实边界：公网真实配额未知；长时间高并发抓取未测（`docs/LIMITATIONS.md` A6）。

### 8.11 故障注入与跨平台 CI（round 18）

- **故障注入** `tests/test_failure_injection.py`（11 条）：磁盘满（`os.replace` 抛 ENOSPC）、
  写入失败（`Path.write_text` 抛 EACCES）、只读目录（POSIX）、坏 `index.json`（截断）、
  坏 `manifest.json`（构建继续并记录）、锁持有者崩溃。断言重点不是"抛异常"，
  而是**旧文件完好 + 无 `.tmp` 残留 + 报错说明原因**。
- **字节级完整性** `scripts/check_eol.py`：6 个拓扑参考 CIF 的 sha256 与记录值比对 + 全库
  关键文本文件零 CRLF + `.gitattributes` 必须含 `eol=lf`；已接入 `check_all` 第 8 组。
- **跨平台 CI** `.github/workflows/ci.yml`：ubuntu/macos/windows × py3.11/3.13，强制
  `core.autocrlf=false`，依次跑 check_eol → sca_scan --strict → verify_formats →
  adversarial → pytest → check_all --skip-agentlib，另加 wheel 构建 job。
  **诚实标注**：本机只有 Windows，该 workflow **尚未真正执行过**（局限 H4）。

### 8.12 流式千级实测 + 软件验收框架（round 19）

- `scripts/bench_stream_scale.py`：合成微型语料（默认 2000 run，`--rdf` 变体），
  含预热地对比流式/传统构建的 tracemalloc 峰值、墙钟、`max_rows_held` 与 CSV 哈希；
  实测峰值内存 **3.55×（无 RDF）/ 4.34×（含 RDF）更低**，墙钟代价 0.85–1.14×（固定开销）。
- `scripts/check_software.py`：12 种计算软件的探测 → 外部数据就绪检查 → 最小自洽算例 →
  成功标记核对；`--run` 才真正执行。本机无任何软件（`verified=0/12`），
  因此 H3 保持 🔴，但"缺少的证据"现在是可机械补齐的（H3 的处置方式已写进 docs/LIMITATIONS.md）。
- `tests/test_check_software.py`：用 stub 可执行文件验证框架自身（verified / ran-no-marker /
  failed / timeout / 数据缺失跳过 / 报告诚实性）。

### 8.13 数据覆盖审计与超大结构实测（round 20）

局限 C2 的处置方式可以复用：**先查证，再决定**。

- `scripts/audit_dataset_coverage.py`：在本地 CoRE 索引上按 **name / CSD refcode / DOI**
  子串、**元素指纹**（`--formula "Cr>=3,F>=1,C>=20"`）、**最大晶胞**（`--largest Cr`）检索。
  实测：8300 条里 **0 条** MIL-101/OCUNAC（只有 1372 条有 name 字段），
  Cr≥3+F≥1+C≥20 只命中一个 `Cr816H1632C4896O3536F272`（11152 原子）。
- `scripts/bench_large_structure.py`：对指定条目逐阶段计时（解析/建键/缺氢/特征/环/校验），
  **默认不建超胞**，只报告投影原子数（2×2×1 = 44608）。
  实测 11152 原子：解析 16.8s、建键 0.71s、缺氢 0.03s、特征 1.5s、环 2.1s、校验 2.4s，全部 ok。
- COD 侧：`search(structure_id="7111973")` 与 `"cod:7111973"` 现在都接受
  （此前 search 返回的 `record_id` 回查会被拒，属真实可用性缺陷，已修 + 回归测试）。

### 8.14 check_all 的外部依赖与失败诊断（round 21）

`check_all` 的 10 组里有 4 组（`agentlib: router route` / `eval_router --all` / `ci --fast` /
`check_skill cif-*`）跑的是 **`D:\agent-library`**，即技能目录本身。这意味着：

* 那个仓库被并发修改时（例如别人正在注册新的 `office-*` 技能、但评测期望值还没同步），
  这 4 组会失败，而**与本工作台无关**；
* 因此组名加了 `agentlib:` 前缀，失败时还会打印提示，明确指向外部仓库；
* 诊断入口：`python scripts\check_all.py --json runs\check_all_full.json`，
  报告里 `groups[].ok` 指出哪组失败，`outputs[]` 保留该组的完整 stdout/stderr 尾巴
  （此前只打印最后 4 行，"9/10" 无法定位，现已修复）。

**约定**：本工作台的自测完整性以"非 agentlib 组全绿 + agentlib 组的状态另行核对"为准；
若要发布，请在**两边仓库都干净**时再跑一次完整 `check_all`。

### 8.15 发布门禁 `scripts/release_check.py`（round 22）

把"能不能发"变成一张可复跑的清单，而不是感觉：

| 门 | 判据 |
|---|---|
| 两个仓库干净 | 本仓与 `D:\agent-library` 的 `git status --porcelain` 为空（`--allow-dirty` 降级为 WARN） |
| 格式全绿 | **现场重跑** `verify_formats.py`：31/31 写出、25/25 第三方回读、12 bundle |
| 健康检查全绿 | `check_all --adversarial`（或 `--quick` 用 `--fast`）**每一组**通过，含 agentlib 组 |
| 字节完整性 | `runs/check_eol.json` 无 failures（LF + 钉住 sha256） |
| 许可 | `runs/sca_scan.json` 源码级 copyleft = 0 |
| 对抗性 | `runs/lead_verify_r11/adversarial_check.json` 全 ok |
| 文档一致性 | `docs/LIMITATIONS.md` 顶部统计与表格行数**逐项相符**（写歪了就不算发布） |
| 软件验收 | `runs/check_software.json` 存在（信息项：`verified` 数反映 H3 现状，不作为通过条件） |

用法：`.venv\Scripts\python.exe scripts\release_check.py [--quick] [--allow-dirty]`；
输出 `runs/release_check.json`（含两个仓库的 HEAD、每个门的判据与耗时），退出码 0 = 可发布。

**agentlib 组失败时自解释**：`check_all` 会解析 `eval_router` 的失败行，给出
`stale-eval?`（期望的 id 仍存在但被更专门的新 id 取代）/ `missing-skill?`（期望的 id 已被删除）/
`router-regression?` 三分类，并指出该改哪一侧——因为技能目录在**另一个仓库**里，
经常被并发修改（2026-11 的 `document-pptx → office-pptx` 改名就是这么发现的）。

### 8.16 覆盖矩阵（round 23，`docs/COVERAGE.md`）

`scripts/coverage_matrix.py` 把"本地到底有什么"变成一张可复现的表：

- 统计每个拓扑在索引里的条目数（allnodes/singlenodes）；
- 标记哪些拓扑**本地有参考网络**（只有 `cifkit/data/nets` 里那 6 个可离线验证）；
- 对每个捆绑 net **从 CoRE 压缩包取一条真实条目跑 `topology.verify`** 并记录结果。

实测：sod/pcu/dia/fcu/tbo/bcu **6/6 全部 verified**；`mtn` 条目数 **0**（再次证实 MIL-101
不在数据集内，与 C2 互证）；`sql` 176 条、`hcb` 43 条等**存在但本地无法离线验证**。
发布门禁新增一条：**捆绑参考网络必须在真实数据上验证通过**。

### 8.17 云端验收作业（H3 的补证路径，round 24）

H3（"输入模板从未在真实计算软件里跑过"）本机无法验证；已按 skill
`catalog/cloud-gpu-bohrium` 的**省钱顺序**（probe → dry-run → 极小探测作业 → 目标作业）
把证据链准备好：

| 产物 | 作用 |
|---|---|
| `cloud_h3/run_acceptance.py` | 容器内运行：探测 9 种计算软件 → 跑最小自洽算例 → 核对成功标记 → 写 `acceptance_result.json`（纯标准库） |
| `cloud_h3/cases/*` | CP2K H2O 单点（用 CP2K 自带 data）、QE pw.x scf、ORCA/NWChem H2（STO-3G 内置，无外部数据） |
| `scripts/cloud_h3_submit.py` | 门禁包装：**无凭据 = 不提交**（exit 1，不发请求）；**无 `--go` = 只 dry-run**；`--go` 才 probe→submit；支持 `--image`（自带 CP2K/QE 的镜像，省掉每次 apt 装包）、`--job-id` 轮询/取回 |
| `runs/cloud_h3/RUNBOOK.md` | 运行手册：成本敞口、命令序列、诚实边界 |

实测（本机）：`--check` exit 1（三个变量全未设置）；`--dry-run` exit 0、`network_requests = 0`、
payload sha256 可核对；`--go` 在缺凭据时 **exit 1 且不产生 probe/submit 日志**（真的没发请求）。
默认 4090 目录价 5.5 RMB/h：5 分钟探测作业 **run-only ≤ 0.4583 RMB**、含排队暴露 ≤ 3.2083 RMB；
装 CP2K 路线（60 min）≤ 5.5 / 11.0 RMB。

**H3 在此期间仍是 🔴**：没有真实运行就没有证据，dry-run 的 payload 不得当作 GPU 结果。

**round 28 实测（真正的管线）**：本机桌面端装有有效凭据（`bohr doctor` → `auth_validity: pass`），
官方 `bohr batchjob` 才是本机可用入口；现金余额 -0.09 CNY 不足，**必须用 `--payment-source photon`**
（光子余额 25 067）。已实测：`c2_m4_cpu`（0.16 RMB/h）+ PyTorch 镜像，5 分钟上限，
作业 `7972cc62…` **成功调度并运行**（spendTime 6 s、photonCost 0），产物
`acceptance_result.json` 已取回 → **镜像里没有任何计算化学软件**（预期结论）。
细节与命令见 `runs/cloud_h3/PIPELINE-FOUND.md`；`scripts/cloud_h3_submit.py --bohr-status` 可复现只读检查。

**round 29：这条链路闭环**。做法不再是「猜语法」，而是读程序自己的证据：

1. 容器里 `dpkg -L nwchem` + 搜 `/usr/share/nwchem/**` → 伪势库在 `libraryps/TM/<元素>/`（含 Zn），候选指令 token 是 **`cutoff`**（不是 `ecut`）；
2. 一个作业跑 4 个变体 → 唯一能跑完的是 `nwpw` + `cutoff 20` + `xc pbe` + `end` + **`task pspw energy`**（exit 0、打印 `Total times`）；
3. 把该模式固化进导出器（带证据注释），并把 **`memory` 指令** 放在输入顶部（Debian 的 NWChem 不认 `-memory`；且要求 `total = stack + heap + global`）；
4. 复验：cifkit 自己导出的 NWChem 文件在作业 `774a6dd5…` 里完整跑完——**`Total times cpu 1020.8 s`**、exit 0、succeeded（17.7 min / 4 光子）。

138 原子 ZIF-8 的同一模板输入解析全通过，但在 8 GiB / 32 GiB 机器上 `cutoff 20` 内存不足——这是资源约束，已如实记在局限 H3c。

### 8.18 数据源实时可用性检查（round 25）

`scripts/sources_live_check.py`：对每个数据源做 **TCP 可达性 + 一次真实小查询**，记录
状态/耗时/首个结果，并生成 `runs/sources_live.json` 与 `runs/sources_live.md`。
`release_check` 把它当**信息项**（数据库抖动不阻塞发布），`docs/SOURCES.md` 嵌入表格。

2026-11-09 快照：`core-mof` ok（8300 条）、`cod` ok（by_id + 文本查询都有结果）、
`aflow` ok（ZnO 3 条）、`local` ok（16 CIF）、`materials-project` **needs-key**、
`qmof` **not-configured**（无本地镜像）。

### 8.19 性能回归门禁（round 26，`scripts/perf_gate.py`）

`--record` 存基线、`--check` 与基线比较（**每项指标取多次运行的中位数，且先做 warm-up**，
否则首次调用的惰性导入会污染基线）。默认容差很宽：时间允许慢到 **0.5×**、内存允许涨到 **2.0×**
——因为本机是共享且高负载的（对照实验里 4 线程只有 0.78×，机器自己就会变慢），
这道门抓的是**数量级回归**，不是噪声。

实测基线（2026-11-09，中位数）：`features`（无 RDF）0.026 s、`features`（RDF）0.167 s、
`convert`（vasp+xyz）0.051 s、`features_many`（6×jobs=1）0.148 s、
流式数据集（60 run）2.13 s / 峰值 **1.16 MiB**。

用法：`scripts/perf_gate.py --record|--check [--quick]`；`release_check --perf` 会把它接成一道门
（**opt-in**，默认不跑）。基线是**本机的**，换机器/换 Python 要重录。

**负载感知（round 27 的教训）**：基线里同时记录一个**纯 Python 控制循环**（`control_loop_s`，
与库代码无关）。若本次控制循环比基线慢 >2×，说明机器处于高负载，此时**时间类指标一律记为
`inconclusive` 而不是 `REGRESSION`**；内存类指标不受负载影响，照常判定。
起因：一次发布门禁在极端负载下跑了 30 分钟（正常 2 分钟），把 2 个指标误报成性能回归，
同时还有一个 1.3 秒的命令撞上 900 秒子进程超时。现在：① 误报被降级为 `inconclusive`；
② 对抗性脚本打印控制循环并报告负载；③ CLI 子进程预算 900→1800 s、对抗性组预算 2400→5400 s。

### 8.20 产物可移植性门禁（round 28）

云端跑出来的一个副作用：**我们自己导出的 NWChem 输入里写着本机的绝对路径**
（`permanent_dir D:\Dev\Project5-skill-cif\nwchem`）——因为 ASE 的 `nwchem-in` writer 对默认
label 调了 `os.path.abspath`。这种文件在容器/集群上直接不可用。

- 修复：写完后把 `permanent_dir`/`scratch_dir` 改写成 `.`（自包含）；
- 门禁 `scripts/check_portability.py`：**把 31 个格式全部生成一遍**，扫描
  工作区根路径 / Windows 盘符路径 / `~` 家目录 / `/home|/Users` 形态；二进制（PNG，含 NUL）跳过；
- 测试 `tests/test_portability.py`：NWChem 头两行必须是相对路径，且 ≥20 个文本格式全部干净。

这类缺陷是"本地测试永远发现不了、一上云就炸"的典型，因此单列一道门。

### 8.21 云端 GPU 并发（round 30）

`scripts/cloud_gpu_fanout.py` + `cloud_gpu/gpu_bench.py`：N 台 GPU 同时提交/轮询/取回/汇总，
带**成本硬门禁**（无 `--go` 不提交；最坏情况光子数超 `--max-photons` 或余额未知一律拒绝）、
持久台账（重跑不重复扣费）、截止取消、陈旧产物隔离。
载荷做了审计级修正：预热 + 预分配输出 + CUDA event 计时（旧版无预热/循环内 cudaMalloc，
会系统性低估 GFLOPS）、显式关闭 TF32/降精度归约并记录、用 fp64 参考做真实正确性校验。

**实测边界**：光子是**共享预算**——本会话的模型网关计费同样消耗光子（账本条目
`Bohrium 模型网关按量结算`，单次 48-68 光子），余额从 25 067 降到 **6**；
按实测 0.157 光子/秒（4090），8×4090×6 min 约需 ~1 400 光子，因此**当前余额下大并发被门禁拒绝**。
详见 [docs/CLOUD-GPU.md](CLOUD-GPU.md)（含 10 条并行审计发现与修复）。

### 8.22 验收报告吸收云端证据（round 34）

`scripts/check_software.py` 以前只报告"本机装了什么"。现在它还会读取 `runs/cloud_h3/` 下
真实容器的运行记录，按三级分类：

| 级别 | 含义 | 当前证据 |
|---|---|---|
| `verified` | 真实二进制跑到成功标记 | `NWChem`（最小算例 exit 0）、`NWChem (cifkit template)`（`Total times` 1032.3 s） |
| `accepted` | 真实二进制**接受**了我们的文件，但没有完整计算 | `LAMMPS`（`read_data` + `run 0` exit 0）、`GROMACS`（`editconf` exit 0） |
| `blocked` | 该镜像里的软件本身不可用（有 canonical 对照） | `QE 6.7`（canonical H2O 也 SIGABRT）、`CP2K`（镜像无此包） |

实现要点（都是踩过的坑）：
- 同一代码多次尝试时**按 mtime 取最新**（否则修复后的 exit 0 会被旧记录覆盖）；
- `parse_accept` 类证据默认 `accepted`，只有探针显式声明 `calculation_completed` 才算 `verified`
  —— LAMMPS/GROMACS 没有力场，不能冒充"算过"；
- 产物缺失或损坏时**跳过**而不是让报告崩掉。

`runs/check_software.json` 因此同时包含 `counts`（本机）与 `cloud_counts`（云端），
`cloud` 段每条都带证据路径。

### 8.23 打包验证（round 35，`scripts/check_package.py`）

以前"打包"只存在于 CI 定义里，本机从没构建过。现在一条命令走完闭环：

```
pip wheel . --no-deps --no-build-isolation -w runs/dist
pip install --no-deps --no-index --target runs/dist_target runs/dist/cifkit-0.1.0-*.whl
# 换一个工作目录、PYTHONPATH 指向 dist_target，再从"安装副本"导入
```

**首次运行就抓到一个真问题**：`pyproject.toml` 的 `package-data` 只声明了 `data/**/*`，
**漏了 `cifkit/schemas/*.json`** —— 安装后 `cifkit.contract` 与 `--dump` 会因找不到 schema 失败。
补上后复验：

| 检查 | 结果 |
|---|---|
| wheel | 70 文件 / 237 KB，含 4 个 schema + 6 个拓扑参考 |
| 导入副本 | `loaded_from=runs/dist_target/cifkit`、`is_target_copy=true`、`API_VERSION=1.0` |
| 服务 | `service.handle({"op":"capabilities"})` → ok |
| CLI | `python -m cifkit formats` 正常 |
| 拓扑数据 | 6 个参考网络**全部 verify 通过**（证明 package-data 真的进了包） |

门禁：`release_check --package`（opt-in）+ `tests/test_packaging.py`（5 条，含
"schema 必须声明为 package-data"的回归测试）。

### 8.24 并发实测：batch 与 dataset（round 36）

**batch（`cifkit batch --jobs N`）**——8 个真实 pipeline 作业，两次独立运行：

| jobs | 用时 | 加速 | 效率 |
|---|---|---|---|
| 1 | 147-149 s | 1.00× | 1.00 |
| 2 | 90 s | 1.66× | 0.83 |
| 4 | 51-72 s | 2.05-2.93× | 0.51-0.73 |
| 8 | 39-48 s | **3.11-3.85×** | 0.39-0.48 |
| 16 | 53 s | 2.78× | 0.17 |

**结论**：扩展是真的但次线性；**16 反而比 8 慢**（过订阅）。推荐 `--jobs 4`（效率高）或 8（吞吐最高）。

**dataset（新增 `--jobs`）**——40 run 语料、`rdf=True`：jobs=1/2/4/8 → 13.7/14.9/13.8/12.9 s
（**0.92-1.06×，无加速**）。原因是 GIL：pymatgen 解析 + 纯 Python 特征都在同一解释器里。
`--jobs` 保留的价值是**语义正确**（顺序保持、在飞窗口 jobs×2、`max_rows_held=1`、
与串行输出逐字节一致，有测试保证），吞吐要靠**语料分片跑多进程/多机**。

> 所有数字都在共享机器上测得，属于数量级证据，不是承诺；`scripts/bench_batch_scale.py`
> 与 `.probe/bench_dataset_jobs.py` 可随时复测。

### 8.25 12 个计算软件包的内部一致性（round 39）

`scripts/check_bundles.py` 把每个 bundle 的**跨文件契约**写成规则并逐个校验：

| 检查类型 | 例子 |
|---|---|
| 必需文件存在且非空 | VASP 必须给 `POSCAR/INCAR/KPOINTS`；DFTB+ 必须给 `dftb_in.hsd + geo.gen` |
| **交叉引用可解析** | `dftb_in.hsd` 里的 `<<< "geo.gen"` 必须真有这个文件；`in.min` 的 `read_data data.lammps` 必须指向实际文件 |
| **声明缺失必须真缺失** | 若 bundle 说"缺 POTCAR"，那目录里就不能出现 POTCAR（数据文件；`*.readme` 不算） |

实测：**12/12 一致**，共 43 条检查。首轮就抓到两个规则/文档不一致的地方
（gromacs 的缺失文案用 "force-field .top/.itp"、vasp 的 `POTCAR.readme` 被误判为 POTCAR），
已修正并把"有规则的检查"变成发布门禁的一环（`release_check` 第 13 道门）。
测试用**故意破坏的 bundle** 验证检查器真的会失败（删 `in.min`、删 `geo.gen`、改名目标文件、伪造 POTCAR），
避免"检查器永远通过"。

### 8.26 CI 定义漂移检查（round 40）

CI 没在真实 runner 上跑过，但**定义可以保持诚实**。`scripts/check_ci.py` 解析
`.github/workflows/ci.yml`，校验：

1. 有 `test` 与 `build` 两个 job；
2. matrix 是 **3 OS × 2 Python**，且声明的最低版本 3.11 在列；
3. workflow 里固定了 `core.autocrlf false`（否则 Windows 的 EOL 证据是假的）；
4. **引用的每个脚本都存在**；
5. **每个 gate 脚本都能从 CI 到达**（直接调用，或经 `check_all` 间接）；
6. **每个非 CI 脚本都有明确的 on-demand 归类 + 理由**（新增脚本不会被静默忽略）；
7. import 冒烟指向真实模块。

实现过程中修掉两个自身缺陷：注释里提到 `scripts/check_ci.py` 一度被当成"gate 脚本"；
"可达"的定义在检查器与测试间不一致。现在两者共用同一个 `analyse()`。

顺带把 `check_bundles` 与 `check_portability` 接进 `check_all`（**7 组**），
于是 CI 通过 `check_all` 自动覆盖它们；`release_check` 也新增此门。

> round 41：`check_all` 现在 **8 组**（新增 `check_ci`，让 CI 定义漂移检查也进入日常健康检查）；
> 同一轮还修正了一处**我自己制造的**许可扫描告警：在 `check_ci.py` 的 on-demand 理由字符串里写了受限许可关键词，
> `sca_scan --strict` 正确地把「源码里出现该词」判为 copyleft 提及 —— 改成中性措辞后恢复 0 actionable。
> 门禁抓到作者本人，正是它该有的行为。

### 8.27 并发写入与力场骨架（round 42）

**跨进程追加锁**（G3）：`library/index.jsonl` 以前裸 `open("a")`，两个并发 `--ingest` 可能交错。
现在统一走 `cifkit/locks.py::append_jsonl_locked()`：持 `file_lock` 写入 + `fsync`，
**崩溃不留半行**；测试**真起 4 个进程**各追加 25 条，断言 100 行、行行可解析、无半行、锁已释放。

**力场骨架**（E4）：CIF 推不出力场，但**能推出拓扑**——
- GROMACS `topol.top`：每个原子（含元素质量）+ `[ bonds ]`（来自 cifkit 的键感知）+ 全部必需 section，
  而 `[ atomtypes ]`/`[ atoms ]` 的电荷与 LJ 参数是**明确标注的占位值**；配套 `TOP.readme` 说明要替换什么。
- LAMMPS `in.min`：给出三条路（`zero` 几何检查 / 通用 LJ 占位并标注"**不是拟合力场**" / 真实 FF 示例），
  `data.lammps` 带完整 `Masses`。
- bundle 门禁规则同步更新（gromacs 现要求 `topol.top` 存在，且"缺失"文案必须提到 atom types）。

### 8.28 崩溃恢复与去重（round 43）

**崩溃恢复（G5）**——用真进程强杀验证文件契约：

| 场景 | 断言 |
|---|---|
| SIGKILL 追加者（持锁中） | 索引只剩**完整行**（逐行 JSON 可解析、结尾有换行） |
| SIGKILL 原子写者 | 目标是完整的旧/新一代（**绝不截断**），且不留 `.tmp*` |
| 崩溃后重跑 | 幂等：读者按 `run_id` 去重，不产生重复语义条目 |

这次测试**又抓到一个真 bug**：被 SIGKILL 的持锁者留下**mtime 很新**的锁文件，
原来的"按年龄判过期"要等满 `stale`（默认 180 s）——期间所有写者全部阻塞。
修复：`file_lock` 现在做**所有权探活**（锁文件里记了 pid），所有者已死则立即回收；
且探活是**保守**的：只有明确的"进程不存在"才算死（Windows 上 `ERROR_INVALID_PARAMETER`），
权限不足/无法判定一律当作**活着**——偷走活锁会让两个写者同时写，比等待更糟。
（第一版实现就是"OpenProcess 失败即视为死"，在并发测试里立刻暴露为互相偷锁 + 超时。）

**去重（F5）**：`build_dataset(dedupe=...)` / `cifkit dataset --dedupe KEY` —— 保留首次出现、
失败 run 永不去掉、流式/物化一致、内存只占键集合；summary 增 `dedupe` 与 `n_deduped`。
### 8.29 导出保真度：从「原子数」到「几何」（round 44）

以前 25 个第三方回读只断言 `len(readback) == len(structure)`——**晶胞错了、坐标错了、元素换错了都能通过**。
现在 `scripts/verify_formats.py` 对每个能读回的格式做**几何比对**（`cifkit/export/geometry_check.py`）：

| 情形 | 判据 |
|---|---|
| 回读出的晶胞**与源晶胞一致** | `StructureMatcher.get_rms_dist` 的 max displacement ≤ 容差（顺序无关） |
| 回读**没有晶胞**（xyz/mol/sdf/turbomole/lammps：ASE 会造包围盒） | **排序配对距离指纹**逐项比较（晶胞无关的几何签名） |

实测（138 原子 ZIF-8）：**25/25 通过**，其中 20 个精确到 **≤1e-6 Å**；
最松的是 `gromacs` **3.2e-3 Å**（对应 .gro 的 3 位小数）与 `pdb` 3.5e-4 Å。

实现中修掉两个自身错误（都由更严格的判据暴露）：
① 误用 `StructureMatcher.get_mappings`（`int + None` 崩溃）→ 改用 `get_rms_dist`；
② 一度以「有晶胞」决定是否做周期比对，于是 ASE 造的**假晶胞**让 xyz/mol/sdf/turbomole/lammps 全部误报失败
——现在只有**与源晶胞匹配**才走周期路径，否则退回距离指纹。

测试 `tests/test_export_fidelity.py`（8 条）刻意验证**反向情形**：位移 0.5 Å、换晶胞、换元素都必须判失败，
合成的假晶胞不得触发周期匹配。

### 8.30 收敛性研究机械 + 一把被捶过的锁（round 45）

**收敛机械（E3）**：`cifkit/export/convergence.py` 按代码生成参数扫描（NWChem `cutoff`、VASP `ENCUT`、
QE `ecutwfc`、CP2K `CUTOFF`）、解析各家能量方言、并按严格定义判定收敛——
**「从某个取值起，后续每一步的差都 ≤ 阈值」**（早期版本把"局部平坦三元组"的第一个值当收敛点，
会让一个下一步还差 0.5 eV 的取值被标成"已收敛"，测试抓出后改成尾部定义）。
本地入口 `scripts/run_convergence.py`，云端入口 `cloud_h3/run_convergence_nwchem.py` + `scripts/analyse_convergence.py`。

**第一次真实云端收敛实验立刻抓到模板缺陷**：5 个 cutoff **全部** `electron_init: out of heap memory 0`
——这个 NWChem 构建 **heap 默认为 0**，没有 `memory` 指令根本跑不起来（而且 `total = stack + heap + global`
必须自洽）。据此给 NWChem 导出加了"必需"说明与自洽示例（**只作为注释**，不把机器规格硬编码进可运行输入）。
证据保留在 `runs/cloud_h3/convergence_failed/`（5/5 失败原文）与
`runs/convergence/nwchem_failed_attempt.json`（由我们自己的分析器生成，失败的样本序列化成 `null` 而不是 `NaN`）。

**锁（G3）**：并发测试连跑 12 次逼出 4 个真实缺陷——属主已死但 mtime 新（等满 180 s）、**PID 复用**（探活被骗）、
`unlink` 失败被静默吞掉（僵尸锁）、**Windows 的 `O_EXCL` 冲突是 EACCES 不是 EEXIST**（直接崩）。
现在锁里记 **进程身份 token（pid + 启动时刻）**，释放失败会重试并把锁标记为过期，EACCES 与 EEXIST 同路处理。
修完后同样 12 连跑 **0 失败**。

### 8.31 服务的实测压力曲线（round 46，J5/J9）

`scripts/load_service.py` 用**闭环客户端**压真实代码路径（`validate` 一个真 CIF），
记录吞吐 / p50 / p90 / p99 / 拒绝原因，输出到 `runs/service_load*.json`。

| 负载档 | 吞吐 | p50 | p90 | 拒绝 |
|---|---|---|---|---|
| 并发 1 | 16.5 rps | 58 ms | 67 ms | 无 |
| 并发 2 | 16.4 rps | 116 ms | 142 ms | 无 |
| 并发 4 | 15.1 rps | 259 ms | 327 ms | 无 |
| 并发 8 | 14.8 rps | 268 ms | 341 ms | 无 |

**结论一（GIL）**：并发 1→8 吞吐**几乎不变**（1.0 / 0.996 / 0.913 / 0.897），p50 却线性上涨
——线程池不是这条路径的扩展手段。

**结论二（拒绝膝点）**：把 `queue_size` 收到 4、并发升到 16，出现 **790,718 次 `busy`**，
而成功吞吐跌到 4.5 rps：**拒绝太快会抢走已接纳请求的 CPU**，队列长度要按客户端重试策略调，不能一味求小。

数字是**本机单进程**的，只作为容量量级与调参依据。测试用 CPU-bound stub 锁住该性质，
防止有人把 `sleep` 型 stub 测出来的「线性扩展」写进文档。

### 8.32 slab 磁盘缓存（round 47，G2）

`make_slab` 的命中顺序现在是：**进程内 LRU（24 条）→ 磁盘条目 → 计算**。
磁盘键 = 结构指纹 + `hkl` + 厚度 + 真空 + termination + reps + frame，
条目是 `<cache>/slabs/<sha1>.json`（含 digest/键/信息/CIF 文本），
写走 `file_lock` + 原子替换，因此并发进程不会发布半个条目。

**缓存永不破坏几何**：目录不存在、JSON 坏掉、键不符、CIF 解析失败，一律按 miss 处理并重算
（`disk_corrupt` 计数可见）。`CIFKIT_SLAB_DISK_CACHE=0` 可整体关闭。

实现中修掉一个自己造的 bug：最初用 `list(payload["key"]) != list(key)` 校验键，
但 **JSON 会把元组变成列表**，于是每个条目都被判成"坏"并删除重算——改为比较规范化文本（digest）。

测试用**真子进程**验证跨进程命中（这才是 G2 的意义），另外覆盖参数不同不串号、坏条目被忽略并重写、
可用环境变量关闭。

### 8.33 第一张真实收敛表：模板默认值不够（round 48；round 51 更正）

> **round 51 更正**：新增 60/80 Ha 两点后发现它们**崩溃**（`out of heap memory`，exit 255），
> 而批次作业状态仍是 `succeeded`。因此 `output_completed()` 现在要求**正常结束标记**，
> 收集器把这两点标记为作废（报告 = **3 有效 + 2 作废**）。上面的 20/30/40 三点均有 `Total times`，仍然有效。
> 60/80 的**非单调**（+34.7 meV/atom 反弹）正是崩溃导致的假象——这也说明"能解析出数字"离"能当证据"很远。

#### 8.33 第一张真实收敛表：模板默认值不够（round 48）

三个云端作业（NWChem 7.2.2，16 原子周期胞，`c2_m8_cpu`，各自 15-31 分钟、9/13/21 光子）产出：

| cutoff (Ha) | 总能量 (Ha) | 相对上一步 (meV/atom) |
|---|---|---|
| 20 | -111.2953510 | — |
| 30 | -111.6378257 | -582.5 |
| 40 | -111.6688537 | -52.8 |

**结论（负面证据）**：`cifkit` 模板默认的 `cutoff 20` **远未收敛**；即使 40 Ha，步间仍变化 **52.8 meV/atom**
（判据 1 meV/atom 完全没到）。所以「模板能跑通」和「参数够用」是两件事——这正是 E3 存在的意义。

过程中又修掉两个自己的缺陷：
① 作业**成功退出 0 但解析不到能量**：NWChem 输出是 Fortran 风格 `Total PSPW energy     :  -0.1076404459E+03`
（用 `:` 不用 `=`、有 `E+03` 指数），而且**每次 SCF 迭代都打印一次**——改用「最后一个匹配」，
否则会把早期迭代当最终能量（那会得到一张**错**的表，而不是缺失的表）；
② 收集脚本里一个转义错误（`(\\S+)`）让目录名解析永远失败；现在有集成测试用临时目录跑一遍收集流程。

另外，单作业 5 个 cutoff 会 `deadline_exceeded`（90 分钟上限）**且被杀作业没有结果归档**，
所以扫描改成**一个 cutoff 一个作业** + 每个 cutoff 后落盘 checkpoint。

### 8.34 表面能工具 + 模板默认值的实测警告（round 49）

**表面能（D3 收窄）**：`cifkit surface-energy` 把「slab 结构 + 用户 DFT 能量」之间的算术固定下来：
`E_surf = (E_slab − n_slab·e_bulk) / (N_surface·A)`，输出 eV/Å² / meV/Å² / J/m²（1 eV/Å² = 16.02176634 J/m²），
并做**化学计量校验**（slab 组成必须是 bulk 的整数倍）与两种 bulk 参考写法的一致性检查。
测试 19 条，重点覆盖**拒绝**：组成不匹配、两种 bulk 参考打架、非正面积、负表面能如实报出。

**模板默认值的实测警告**：既然测出 cutoff 20→30 差 582 meV/atom、30→40 仍差 53 meV/atom，
NWChem 导出的注释里现在直接写明「`cutoff 20` 是 smoke-test 值，**不是收敛值**」，
并附上实测数字（`tests/test_nwchem_memory_guidance.py` 锁住这段警告不被删掉）。

### 8.35 协作式取消（round 50，J2）

`cifkit/cancel.py` 提供 `CancellationToken`（线程安全、一次性、带原因）与**线程本地** `checkpoint()`：
库代码不必把 token 一路传参，只在循环里调 `checkpoint()` 即可。

- `GuardedService` 每个请求建一个 token，在 worker 线程里 `use_token(...)` 安装；
  **超时的那一刻 `token.cancel("timeout")`**，于是 worker 在下一个 checkpoint 停下，
  而不是把整批任务跑完（错误文案也从 "best-effort" 改成 **"cooperative"**——说什么做什么）。
- `features_many` 的两个分支都加了 checkpoint。**顺序分支（`jobs<=1`）最初被漏掉**——
  这是最常用的路径，被测试当场抓出：`jobs=1` 时取消完全无效。
- 测试里还用真 op 名（契约会在 dispatch 前校验 op 名）打桩，验证「超时后 worker 没跑完循环」。

**诚实边界**：正在计算的那一个 item 仍然杀不掉（CPython 不能安全终止线程），
所以我们不宣称"可中断计算"，只宣称"**已加 checkpoint 的循环会在下一个安全点停止**"。

### 8.36 流式行导出（round 52，J4）

`dataset_rows` 早已分页（只读需要的行），但响应必须整个装进一个 JSON body。
现在拆成两件东西：

* `cifkit.api.iter_dataset_rows(...)` —— **生成器**，逐行读 `dataset.jsonl`，
  分页与流式**共用同一实现**（不可能出现两套语义）；
* `GET /stream/dataset_rows?dir=…&offset=&limit=` —— **NDJSON + chunked**，
  客户端断开即停止拉取（`BrokenPipeError` 就地收敛，不刷日志、不继续读）。
* **流式路由不绕过策略**：它复用 `check_params("dataset_rows", …)`，
  也就是 `/rpc` 的那套路径沙箱/租户/上限检查；越界 403，缺 `dir` 400。

测试（10 条）里最有价值的一条是**读行计数**：只为 2 行的页读了 3 行（多读 1 行用于判页尾），
证明生成器没有退化成"先全读再切片"。

### 8.37 真实二进制接受测试：一次真 bug 与三个 blocked（round 53，H3c）

新增 `cloud_h3/run_code_acceptance.py`：装代码 -> 跑**我们发布的输入原样** -> 要求出现该代码的
**正常结束标记** -> 写出 `acceptance_result.json`（含 markers、exit、route、scope）。
`scripts/check_software.py` 汇总成三级证据（verified / accepted / blocked）。

| 代码 | 级别 | 依据 |
|---|---|---|
| NWChem | **verified** | 我们模板完整跑完（`Total times`，1032 s） |
| LAMMPS | **accepted** | 发布的 `in.min` 原样跑完 `minimize`，`Total wall time`、exit 0（`pair_style zero`，无势场） |
| GROMACS | accepted | `editconf` 接受 `conf.gro` |
| ABINIT | **blocked** | 打包 9.10 拒绝运行：`This version of ABINIT is not supported anymore` |
| CP2K | blocked | 镜像无包（`Candidate: (none)`） |
| QE | blocked | 上游 SIGABRT（标准 H2O 输入同样崩） |
| ORCA（量子化学） | blocked | **Debian 的 `orca` 包是 GNOME 屏幕阅读器**（输出 "Cannot start the screen reader"） |

**这次测试抓到两个真缺陷**（同类：注释符）：`in.min` 用 `;` 注释 -> LAMMPS 报
`ERROR: Unknown command: ; ...`；`cp2k.inp` 用 `#` 注释 -> CP2K 不认 `#`。
两者都已修，并新增**每种代码只认一种注释符**的门禁规则
（`cifkit/export/bundle_check.py::COMMENT_STYLE`），该规则随后一次性扫出这两处。

**教训**：包名与版本号不构成身份证明（`orca 46.1` 是屏幕阅读器版本），必须真的跑一次看输出；
「作业/进程成功」也不等于「计算完成」（round 51）。

### 8.38 收敛扫描第二轮：60 Ha 完成，80 Ha 超时（round 54）

把失败点重跑在更大机器上（`c8_m32_cpu` + `MEMORY_FRACTION=0.8`）：

| cutoff (Ha) | 能量 (Ha) | 相对上一步 (meV/atom) | 结束标记 |
|---|---|---|---|
| 20 | -111.2953510 | — |
| 30 | -111.6378257 | -582.5 |
| 40 | -111.6688537 | -52.8 |
| 60 | -111.7286759 | -101.7 |

- **60 Ha 在 32 GiB 上正常结束**（8 GiB 上曾因 `out of heap memory` 崩溃）——
  这也是「同一次取值、两次尝试」的由来，收集器现在**优先采用完成的那次**并记录被取代的尝试；
- **80 Ha 超时**：单次 `subprocess` 上限 5400 s（现可用 `MAX_SECONDS_PER_RUN` 调大），
  作业级 `failed` 且无输出，因此**不产生数据点**；
- 40 -> 60 的步间变化（-101.8 meV/atom）**大于** 30 -> 40（-52.8），
  说明这套 plane-wave 设置到 60 Ha 仍**不呈收敛趋势**。诚实的结论是：
  **模板默认（cutoff 20）不可用于生产，且本设置下要收敛需要远高于 60 Ha 的截断与相应算力。**

### 8.39 语料级强验证：16 个结构 × (31 格式 + 12 包 + 5 模板)（round 55）

此前的门禁只验**一个** fixture（138 原子 ZIF-8）。「已验证」应当意味着"在一批结构上都成立"，
所以新增 `scripts/verify_corpus.py`：对每个结构跑完整导出契约，**多进程并行**（8 进程 18 秒跑完）：

| 语料 | 结果 |
|---|---|
| 16 个结构（16-750 原子；含 424/750 原子大胞、2 个 CoRE ASR 真实条目、1 个无序结构） | **16/16 结构全通过**，多数 31/31 |
| 每格式最小通过数 | 15/16 |
| 被判定为「该格式不支持」的样例数 | 23（全部来自无序结构） |

**这次语料扫查抓到三类真问题**：

1. **无序结构直接导出会抛库内部异常**：348 原子部分占据的 ZIF-8 让 22 个格式抛出
   `ValueError: ASE Atoms only supports ordered structures` / pymatgen 的 POSCAR 拒绝——
   都是**别人库的裸异常**，平台侧看不到该做什么。现在改为**类型化契约**
   `DisorderedStructureError(code="disordered")`，消息里说明「先解无序再导出」。
2. **CASTEP 会"静默丢信息"**：它不报错，而是把部分占据写成**主元素全占据**——
   比拒绝更危险。已加入 ordered-only 集合，改为显式拒绝。
3. 我自己的验证脚本两处缺陷：**手写 ASE 格式名**（`abinit` 而非 `abinit-in`）导致 5 个格式假失败
   ——改为用 `ast` 从**已经工作的** `verify_formats.py` 提取映射（单一事实来源）；
   以及 `check_template` 的 companion 必须是**文本字典**而非路径。

结论：无序输入的对外契约从"22 个库异常 + 1 个静默错文件"变成
"**23 个明确 unsupported + 其余全部正常**"，并写进测试（`tests/test_disorder_export.py` 14 条）。
