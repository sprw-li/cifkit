# Round 58：交付阻塞清障（独立评审 → 5 路并行修复 → 独立回归）

> 流程：round 57 之后的**独立评审**（3 名队友并行：全量验收链 / 技能与路由 / 对抗式缺陷猎取；Lead 另跑官方门禁与
> 「干净 HEAD 副本」反证）→ 判定 **不可交付** → **5 路并行修复**（P0 守卫 / 导出与语料记账 / 服务与 CLI /
> LAMMPS WIP 收编 / 文档与技能正文）→ Lead 统一回归、入账与发布门禁。
> 基线 HEAD `50451b8`（round 57）；评审与修复的原始证据在 `.review/`（gitignored 脚手架，**不随仓库交付**）。
> 每一条修复的证据都可由本仓命令复跑，不依赖 `.review/`。

## 结论

**三条交付阻塞全部清除，可交付。** 评审发现的 1 条 P0、2 条 P1、6 条 P2（均未入账）全部修复并带回归测试；
`docs/LIMITATIONS.md` 由 81 条扩到 **89 条（30 ✅ / 59 🟡 / 0 🔴）**；
官方门禁 `scripts/release_check.py --quick --package` 的结果见 §四（本仓仓态干净；`<agent-library>`
的 23 条 dirty 属其它项目、不在本次交付范围，门禁以 `--allow-dirty` 记为**范围外告警**）。

## 一、评审发现的缺陷（本轮修复对象）

### 三条交付阻塞

| # | 阻塞 | 证据 |
|---|---|---|
| B1 | 官方门禁 FAIL：本仓 9 条未跟踪 WIP + `<agent-library>` 23 条 dirty + `check_all` 两组红 | `release_check.py --quick` → FAIL 10/14 |
| B2 | **HEAD 自带回归**：round 57 的 LAMMPS tilt 守卫对**已跟踪**夹具 `tests/data/sod_zn_mof.cif` 抛 `ValueError`，`verify_corpus` 把"正确拒绝"记成坏格式 → `check_all`/`release_check`/`test_check_all_report` 连锁红；**干净 HEAD 副本（无任何 WIP）实测仍红** | `git archive HEAD` 到独立副本后 `pytest tests/test_check_all_report.py` 仍 failed；`verify_corpus` 13/14 |
| B3 | 全量测试 732 = 720 passed + **6 failed** + 6 skipped，且 round 57 的「4 failed 全部归因于未跟踪 WIP」**不成立** | `.review/verifier/REPORT.md`（junit 逐条统计） |

### P0（未记录）

**P0-1 含 `nan` 的 CIF 让进程 native 崩溃，单个 RPC 请求杀死服务**
`cifkit features` / `geom --standardize` / `--surface` → exit `0xC0000005`（`-1073741819`）、stdout 0 字节、无 traceback；
`POST /rpc {"op":"features","params":{"cif_text":"…nan…"}}` 让 `serve()` 进程死亡（`/health` 不可达）。
根因：`SpacegroupAnalyzer(Structure(NaN 晶格))` 在 spglib native 代码里 access violation；`features`/`geom`/`SlabGenerator`
路径进 spglib 前没有晶胞有限性守卫（`validate/checks.py` 早有守卫，说明这是"已知类别、漏了这几条路径"）。

### P1（未记录）

| # | 缺陷 | 证据 |
|---|---|---|
| P1-1 | 裸 `--to dftb` 只写 515 B 的 `dftb_in.hsd`（引用**不存在**的 `geo.gen`）却 `ok:true`/exit 0；`verify_formats.py` 验 dftb 时切到 `dftb_bundle` 目录，官方「31/31」从未覆盖裸产物 | `.review/adversary/REPORT.md` B1 |
| P1-2 | `/stream/dataset_rows` 运行时错误路径发**双重 HTTP 响应**（200+chunked 头之后再把整个 404 响应嵌进 body，无 `0\r\n\r\n`）→ 标准客户端 `IncompleteRead` | 原始 socket 字节见 `.review/adversary/REPORT.md` B2 |

### P2（未记录）

非 JSON 模式 `convert` 隐藏失败原因；CLI `--json`/`cifkit.api` 可输出裸 `NaN`（与 README「可序列化」冲突）；
`standardized.cif` 实测 #42 `Fmm2` 而文档写 I-43m；`docs/SKILLS.md` 评测数字停在 89；`cif-data` 写了不存在的
`--jsonl`；`cif-workbench` 正文 3 个 `0x08` 退格字符损坏示例路径；README 技能表只列 5/8；`cifkit surface-energy`
在技能里 0 提及；`verify_corpus` 单坏结构崩溃且聚合丢失；`pipeline --spec` 未知键静默丢弃；`test_service_load`
在负载下假红；`write_bundle` 不申报 `README.md`（调用方文件数少计）。

## 二、修复（按施工队，全部带回归测试）

### 2.1 P0：非有限晶胞守卫（`p0-guard`）

- 新增 `cifkit/guards.py`：`DegenerateCellError(ValueError)`（带 `.violations`/`.context`）+ `cell_violations` /
  `assert_finite_cell`（矩阵全有限、`|det| > 1e-8`、abc 为正有限、角度严格在 (0,180)）。
- 覆盖入口：`cifkit/features.py`（`extract_features` 前置守卫，覆盖 RDF / `--no-rdf` / `--topology` / `--rings` /
  配位分支，`_symmetry` 内再守一道且在 best-effort `try` **之外**）、`cifkit/geom/standardize.py`（输入与派生胞各一道）、
  `cifkit/geom/surface.py`（`SlabGenerator` **内部也会调 spglib**，故在 `make_slab` 与 `_make_slab_uncached` 前置守卫）、
  `cifkit/geom/disk_cache.py`（退化缓存条目按 corrupt → miss）。
- 判据：`python -m cifkit features <nan cif> --json` 由 `-1073741819`/0 字节 → **exit 1 + 严格 JSON + 可读错误**；
  对照 `tests/data/zif8_cr_sod.cif` 行为不变（#217 I-43m、138 原子）。
- 测试：`tests/test_degenerate_cell_guard.py`（21 条，退化 CIF **内嵌**并写进 `tmp_path`，不依赖任何 gitignored 路径；
  含子进程级"非 0xC0000005 / 非零退出 / 严格 JSON"断言）。
- **可证伪性**：把 `cifkit/ tests/` 复制到临时树（其中 `.review` 条目数 = 0）后该文件 exit 0。

### 2.2 导出与语料记账（`export-gate`）

- 新增 `cifkit/export/refusals.py`：`ExportRefusalError` 基类 + `CellNotRepresentableError`；LAMMPS 的 tilt 超半盒拒绝
  由裸 `ValueError` 升级为类型化异常，`DisorderedStructureError` / `FormatLimitError` 继承同一基类。
- `scripts/verify_corpus.py` / `scripts/verify_formats.py` 统一 `except ExportRefusalError` → 计入 `unsupported`
  （附 `code: message`），**不再计为 bad**；报告新增 `n_unsupported` / `n_bad` / `all_representable_ok` /
  `by_format_unsupported`，口径写明"**可表示的都通过；不可表示的被显式拒绝**"。拒绝本身**没有**被改成静默写错盒
  （错误消息保留 tilt 数值、超限事实与出路）。
- `verify_corpus` 的行 key 集合补全、加载失败不再提前 `return`、`aggregate()` 改用**全行 key 并集**、
  `format_row()` 全 `.get` → 单坏结构不再触发 `KeyError`，聚合不再整份丢失。
- 裸 `--to dftb` 现在在 HSD 同级写出配套 `geo.gen`（与 bundle 同 title 下**字节一致**）；`writers._verify` 校验
  HSD+`geo.gen` **配对**（缺失/截断即报错）；`verify_formats` 改为验证**裸产物自身**、bundle 另行验证；
  `dftb` 入 `ORDERED_ONLY`。
- `write_bundle` 改为返回它**真正写出的全部文件**（含 `README.md`，并对账"本次新增但未申报"的文件），
  `missing` 语义不变 → CLI/API 的文件计数与磁盘一致（实测 `--to cif --bundle dftb`：`n_files=5` == 磁盘 5）。
- 判据：`verify_corpus` **exit 0**（16/16；`sod_zn_mof.cif formats=30/31 unsupported=['lammps'] bad=[][][]`）、
  `verify_formats` **exit 0**（31/31 + 第三方 25/25 + 12 bundle）、`check_bundles.py` **exit 0**（12/12）。
- 测试：`tests/test_export_refusal_accounting.py`（9）、`tests/test_dftb_single_format.py`（8）、
  `tests/test_bundle_check.py`（+3 参数化：12 个 bundle 的返回文件集合 == 磁盘集合）。

### 2.3 服务与 CLI 错误路径（`service-cli`）

- `cifkit/service.py::_send_chunked`：**先拉第一个 chunk，成功后才写 200 + chunked 头**；首个 chunk 前失败 → 在写任何头
  之前逃出，由外层发出**单个**正常 4xx JSON；头已提交后失败 → 只截断（`close_connection`），**绝不再写第二个响应**；
  成功路径保证 `0\r\n\r\n` 终止符。判据：原始 socket 从 **2 个 status line** → **1 个**（`HTTP/1.0 404` + 可解析 JSON）。
- 非 JSON 模式 `convert` 打印失败项与原因（批量分支原本会打印；`exit` 仍 1）。
- 新增 `cifkit.api.sanitize_nonfinite`：非有限浮点 → `null`（类型保持），CLI `--json` 与 `api` 返回路径统一清洗；
  `validate` 对非有限晶胞仍 exit 1 且 stdout 可被严格 JSON 解析（`"abc": [null, null, 5.0]`）。
- `pipeline --spec` 未知键 → `stderr` 警告（列键名）+ `spec.spec_unknown_keys`，行为不变（选警告不选退出＝兼容既有脚本）。
- `--to dftb --json` 的 `n_files` 反映伴随文件（+`companion_files`），并保留 CLI 侧"未申报文件"兜底检测。
- `tests/test_service_load.py` 的性能断言改为**同轮配对 + 中位数**：空载 3/3、3 个 CPU burner 满载 2/2 通过，
  且"CPU-bound 不凭空产生吞吐"的语义未被削弱（真并行会是 ~4×，带宽 1.6 仍强证伪）。
- 测试：`tests/test_stream_error_path.py`（原始 socket，6 条）、`tests/test_cli_json_strictness.py`。

### 2.4 收编 LAMMPS 物理交叉验证 WIP（`wip-lammps`）——并顺带挖出 2 个**实现**缺陷

这部分原本是工作区里**未提交**的 WIP（`cifkit/lammps_{data,reference}.py`、`scripts/check_lammps_physics.py`、
`tests/test_lammps_physics.py`、`cloud_lj/**`），本轮正式入库：

1. `scripts/check_ci.py` 把 `check_lammps_physics.py` 诚实归入 `ON_DEMAND`（需要 `cloud_lj/` 数据；不塞进 CI 充数）→
   `check_ci` **exit 0（10/10）**，`unclassified` 为空。
2. **测试缺陷**：`test_periodic_images_are_counted` 用 `rel=1e-6` 比较"无镜像单对值"与"周期总能量"，而该构型近接触
   排斥 ~5.5e5 eV、镜像修正只有 2.1e-2 eV（3.8e-8 相对）→ 断言恒假。改为绝对余量 + 新增"最小镜像主导"手算用例
   （6 Å 胞 x=0/5.5，手算 `402716826.4002885 eV`，`rel=1e-9`）。
3. **实现缺陷（真漏镜像，已修 `cifkit/lammps_reference.py`）**：
   - **D1**：`_image_shifts` 的 `cutoff + max|lattice|` 过滤丢掉了立方胞的**体对角平移**（hkust1 偏 +1.6e-3 eV、
     mof5 偏 +2.6e-2 eV＝1.5e-7 相对，**都小于旧 gate 的 `rtol=1e-5`**，所以旧 gate 对坏枚举器**无证伪力**）；
   - **D2**：镜像距离矩阵只取 `triu(k=1)`，漏掉**原子与自身镜像**的相互作用（4 个 bundle 胞长 > cutoff 恰好掩盖；
     6 Å 单原子应为 −4.976e-3 eV，旧实现给 **0.0**）。
   - 修复后与 LAMMPS 记录值的一致性从 4.0e-9 / 1.5e-7 提升到 **~2e-15**，并用**显式穷举格点和**与 **ASE 邻居表**
     独立复核（三者差 ≤1.1e-9 eV）；gate 容差随证据收紧 `1e-5 → 1e-8`（`regression_proof.txt` 证明旧实现必红）。
4. 新增 `cloud_lj/README.md`（4 个结构、能量来源与参数、复跑方式、能力边界）与
   `cloud_h3/cases/acceptance/{cp2k,qe,siesta}/README.md`（如实写明：该批第三方解析证据**目前并不存在**——
   归档作业里 `cp2k-input-tools`/`sisl`/`qeschema` 因 PEP 668 未装成功）。
5. `cifkit/lammps_data.py` 的错误处理从"静默给错结果"改为显式 `ValueError`（无 `xlo xhi` 头 / 无 `Atoms` 段 /
   原子行格式错），并核对 LAMMPS restricted-triclinic 的边矢量约定与之一致。

### 2.5 文档与技能正文真实性（`docs-skills`）

README 技能表 5→**8**；`README`/`DESIGN` 的标准化措辞按实测改写（产物保留输入常规胞形/276 原子；spglib 读作
**#42 `Fmm2`**、conventional 552；`#217 I-43m` 属 `raw.cif`）；`docs/SKILLS.md` 评测口径 89→**96**（实测复跑）、
命令示例补 `$env:PYTHONIOENCODING='utf-8'`；`cifkit surface-energy` 写入 `cif-usecases` 技能与命令对应表；
`cif-data` 删除不存在的 `features --jsonl`；`cif-workbench` 清除 3 个 `0x08`；`cif-export` 统一 31 种并把 `png`
移出"未实现"；新增 `CHANGELOG.md`。（历史评审报告里的 `89/89` **刻意保留不改**——那是过去轮次的实测记录。）

### 2.6 缺陷入账（Lead）

`docs/LIMITATIONS.md` 新增 **8 条**并把统计对账（门禁 `limitations_summary_ok` /
`limitations_group_table_ok` 强制）：**E7/E8**（dftb 半成品、convert 隐藏错误）、**G11/G12**（P0 崩溃、
`verify_corpus` 崩溃与聚合丢失）、**H7**（"正确拒绝被记成坏格式"的 HEAD 回归）、**J14/J15/J16**（流式双响应、
裸 NaN、`--spec` 未知键）；同时在 **E2** 注明 round 58 的口径变更（"320/320"应读作"**可表示的** 320/320"）。
另在 `docs/REVIEW-ROUND57-OPT.md` 顶部加**更正注**（不改原文）：§六的「4 failed 全归因于 WIP」与
「干净树 0 failed」两句不成立。

## 三、诚实性修正汇总（文档 vs 实测）

| 原声明 | 实测 | 处置 |
|---|---|---|
| round 57 §六：干净树 `0 failed` | 干净 HEAD 副本 `test_check_all_report` 仍 failed | 加更正注 + H7 入账 + 修复 |
| round 57 §六：4 failed 全归因于 WIP | 只有 3 条成立 | 同上 |
| README/round 57：31/31 格式全过 | 裸 `--to dftb` 从未被覆盖 | 修 dftb + `verify_formats` 改为验裸产物（E7） |
| LIMITATIONS E2：320/320 全通过 | round 57 守卫后已不成立 | 改为"可表示的 320/320"+ 新增 `n_unsupported` |
| README：`api` 返回值 JSON 可序列化 | 畸形晶胞会输出裸 `NaN` | 修 CLI/API 清洗（J15） |
| README/DESIGN：标准化产物是 I-43m | spglib 实测 #42 `Fmm2`（conventional 552） | 措辞按实测改写 |
| CHANGELOG/README：测试条数 | 见 §四 | 按最终实测刷新 |

## 四、最终回归与发布门禁

所有命令在**冻结后的工作树**上运行；`.review/lead/source_snapshot_before.txt` / `_after.txt` 是源码 SHA256 快照，
用于证明验收期间没有并发写入（全量测试 503 s 内只有本文件与 `REVIEW-ROUND57-OPT.md` 的更正注被 Lead 改动）。

| 门禁 / 检查 | 命令 | 结果 |
|---|---|---|
| 全量测试 | `.venv\Scripts\python.exe -m pytest tests -q --junitxml .review\lead\junit_final.xml` | **exit 0：808 collected = 802 passed + 0 failed + 6 skipped**（503.4 s；6 条 skip 全为环境/opt-in 型） |
| 全链体检（含对抗组） | `python scripts\check_all.py --adversarial` | **exit 0：14/14 组**（内部再跑一次 full pytest 730 s；含 `verify_corpus` / `check_ci` / `verify_demo` / agentlib 4 组 / `adversarial_check` 31/31 / `check_eol` / `sca_scan` / `check_bundles` / `check_portability`） |
| 自检 | `python -m cifkit selftest --verbose` | exit 0：**7/7** |
| 验收 demo | `python scripts\verify_demo.py runs\demo_sod_zif8`（另跑过 `--online`） | exit 0：**8/8**（离线 + 联网 Crossref 200） |
| 格式 / 语料 / 输入包 | `verify_formats.py`、`verify_corpus.py`、`check_bundles.py` | **31/31** 写出 + 第三方回读 **25/25**；语料 **16/16**（`unsupported=['lammps']`，`bad=[]`）；bundle **12/12** |
| CI 定义 | `check_ci.py` | **10/10**，`unclassified` 为空（WIP 脚本已诚实归类） |
| 技能与路由 | `eval_router.py --all`、`check_skill cif-*` | **96/96**、负例 0/25、槽位 11/11；8 个技能 errors=0 warnings=0 |
| P0 判据 | `python -m cifkit features <nan cif> --json` | exit **1** + 严格 JSON + 可读 `DegenerateCellError`（修复前 `0xC0000005`、stdout 0 字节） |
| 发布门禁 | `python scripts\release_check.py --quick --allow-dirty --package` | **PASS 15/15 gates**（162.9 s）：`project repo clean` = ok（HEAD `9cd5c2d`，**0 dirty**）、`check_all` **14/14**、`formats` 31/31 + 25/25、`check_ci` 10/10、`check_bundles` 12/12、6 个拓扑参考全部 verify、`package: wheel builds, installs and imports`（85 文件、4 schema、12 net）；唯一 WARN = `agent-library repo clean`（27 条，**范围外**）。报告 `.review/lead/release_check_final.json` |

> `--allow-dirty` 的唯一作用是让门禁 1 对 **`<agent-library>` 的 23 条 dirty（其它项目，不在本次交付范围）**
> 记为 WARN 而不是 FAIL；**本仓自身**在提交后由 `git status --porcelain` 独立验证为空。门禁 2–14 不做任何降级。


## 五、本轮**未**修的项（如实记录）

1. `<agent-library>` 的 23 条 dirty 属**其它项目**的技能，用户明确不在本次交付范围；门禁 1 对它的判定以
   `--allow-dirty` 记为**范围外告警**（本仓自身干净，可由 `git status --porcelain` 独立验证）。
2. `cloud_h3/cases/acceptance/{cp2k,qe,siesta}` 的**第三方解析证据仍缺**（归档作业 PEP 668 导致解析器未安装）；
   目录 README 已如实写明"只是准备好的输入"。补证需要再花一次云端光子，本轮**不花**。
3. `lammps__zif8_cr_sod` 有数据文件但**没有可核对的 LAMMPS 能量**（当年只探了排序前 3 个 batch），故不在 gate 内；
   `cloud_lj/README.md` 写明补录路径。
4. `cloud_lj/README.md` 里的作业标签 `060f75f5` **无法从产物独立核验**（`realphysics_probe.json` 不含 job id）；
   已改写为"项目标签，非已验证的作业引用"。
5. `cifkit/locks.py` 的两处 TOCTOU（G9）与 `--ingest` 同名覆盖（J12）、`fetch` 0 命中退出码漂移（J13）按原计划
   保留为 🟡（边界已知、可绕过）。
6. `cifkit/lammps_reference.py` 的镜像枚举是 O(shifts × N²)（132 原子 ~0.4 s）；大胞需邻居表优化，本轮不做。

## 六、证据索引（`.review/`，gitignored 脚手架）

| 内容 | 路径 |
|---|---|
| 全量验收链（含干净副本反证） | [.review/verifier/REPORT.md](.review/verifier/REPORT.md) |
| 对抗式缺陷猎取（P0/P1/P2 复现命令与原始日志） | [.review/adversary/REPORT.md](.review/adversary/REPORT.md) |
| 技能与路由审计 | [.review/skills/REPORT.md](.review/skills/REPORT.md) |
| P0 守卫修复证据 | [.review/p0-guard/REPORT.md](.review/p0-guard/REPORT.md)（+ `acceptance.txt`、`clean_copy_run.txt`） |
| 导出/记账/dftb/bundle 修复证据 | [.review/export-gate/REPORT.md](.review/export-gate/REPORT.md) |
| 服务/CLI 修复证据（原始 socket 字节） | [.review/service-cli/REPORT.md](.review/service-cli/REPORT.md) |
| LAMMPS WIP 收编证据（含可证伪性证明） | [.review/wip-lammps/REPORT.md](.review/wip-lammps/REPORT.md) |
| 文档/技能正文清扫 | [.review/docs-skills/REPORT.md](.review/docs-skills/REPORT.md) |
| Lead 的最终门禁与回归 | `.review/lead/`（`release_check*.json`、`junit_final.xml`、`pytest_final.log`、`source_snapshot_*.txt`） |
