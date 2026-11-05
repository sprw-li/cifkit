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
测试总数 119 → **127**（新增 `tests/test_cli.py` 8 条 CLI 合同测试；数据源扩展后全量为 **226**）。

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
  `tests/test_cli.py` 中 `sources`/MP 无 key 2 条、`test_spec`/`test_validate` 各若干；全套 **226** 条。

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
