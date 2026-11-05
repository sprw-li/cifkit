# Round 2 独立复核（修复验证 + 回归）— CIF 处理工作台

> 评审员：`reviewer-r1`（同一评审员，独立复核）｜日期：2026-11-05
> 评审对象：`D:\Dev\Project5-skill-cif`，基线 **commit `a3e4bde`** + 评审期间 Lead 的新增强（**工作树未提交**：`M README.md / M cifkit/cli.py / M docs/PIPELINE.md / M tests/test_cli.py`，`?? scripts/check_all.py`）；`D:\agent-library` 工作树干净（`catalog/cif-workbench/SKILL.md` 已更新并已提交）。
> 方法：只验证"修复是否真实、是否回归"，全部命令由评审员重跑；不转述 Lead 的自报。**未改代码/文档/未 commit**（只写本文件与 `runs/review_round2/`）。
> 环境同 Round 1：Python 3.14.8、pymatgen 2026.10.24、Windows PowerShell 5.1、缓存 `_cache/core-mof-2024`（未重新下载）。

---

## 0. 结论

**Round 2：PASS（修复真实，无回归，无新 P0/P1）。**

- **4 个 P1：4/4 FIXED**（全部用独立命令复现了修复后的正确行为，见 §1）。
- **7 个 P2：5 个 FIXED，2 个 PARTIAL**（P2-5 DOI 检查只做到"存在性+note 语义"，伪造 DOI 仍能通过；P2-6 文档仍有一处 126/7 条残留，见 §2/§3）。
- **回归全绿**：`pytest tests` **127 passed**（exit 0；collect 分布 8/20/34/3/12/17/6/15/12=127）；`verify_demo` 8/8（新跑、ingest、仓库留档三个 run 均通过）；重跑结构产物与 `runs/demo_sod_zif8` 逐字节一致；`selftest` 7/7；router/eval/ci 数字与 exit code 全部不变。
- **新增 P2 共 6 条**（均为文档/契约细节或流程问题，不阻断验收），见 §3。最需要注意的一条：**当前工作树未提交**——若以 `commit a3e4bde` 作为最终交付基线，则"UTF-16 支持 / 127 测试 / README 与 PIPELINE 的新数字"都不在其中；若以工作树交付，则这些改动和未跟踪的 `scripts/check_all.py` 需要先提交。

**没有发现"假修复"**：每一条 P1/P2 的修复都能在产物/输出里被独立复现到（个别只修到一半的已按 PARTIAL 标出），也未发现修复引入的行为回归。

---

## 1. P1 逐条验证（FIXED / NOT-FIXED）

| ID | 问题 | 判定 | 我的验证（命令 + 实测） | 证据 |
|---|---|---|---|---|
| P1-1 | `pipeline --json` stdout 被步骤日志污染 | **FIXED** | `python -m cifkit pipeline "<原句>" --outdir runs/review_round2/demo --format vasp,cif,xyz --json`：**exit 0，stdout 首字符 `{`，`json.loads(stdout)` 成功**（`ok=true`，10 steps，11 artifacts）；步骤日志确实转到 **stderr**（stderr 含 `[resolve]`）。失败 run + `--json` 同样纯 JSON（exit 1，`ok=false`）；`--ingest` + `--json` 也纯 JSON（12 artifacts）；`route --json` 仍合法。 | `runs/review_round2/round2_checks.json`、`round2c_checks.json`、`pipeline` 相关子目录 |
| P1-2 | 文档把 `min_image_distance` 当 `vacuum_measured` | **FIXED** | 全项目 + `catalog/cif-*` grep `15.2396/15.240`：剩余命中全部**明确标注为 min_image_distance**（README L41、DESIGN L213、GEOM L181/226/239、PIPELINE L154/155、SKILL L177/178）。实测 manifest：`surface.vacuum_measured=15.0`、`surface.min_image_distance=15.2396`、`vacuum.measured=14.999999999999993`；PIPELINE §7.2 现在写 `vacuum_measured=15.000（垂直）、min_image_distance=15.2396`。 | `runs/review_round2/round2_checks.json` `manifest` 字段；`runs/demo_sod_zif8/manifest.json` |
| P1-3 | §7.3 粘贴的 `artifacts=10` 不可复现 | **FIXED（数字对；仍非逐字转抄，见 P2-N3）** | 实际运行 `scripts/verify_demo.py runs/demo_sod_zif8` → `report=True steps=10 artifacts=12`，与 PIPELINE §7.3 第 173 行一致；manifest `artifacts` 实测 12 项。 | `runs/review_round2/verify_committed_utf8.txt`、`round2d_checks.json` |
| P1-4 | 4 个产物字节数过期 | **FIXED** | 与当前 `runs/demo_sod_zif8/` 实测逐项比对：`repaired/standardized 15379`、`preview 300594`、`report.md 5248`、`manifest.json 74320`、`raw 10816`、`slab/final/structure.cif 121521`、`structure.vasp 152719`、`structure.xyz 134797` —— **PIPELINE §7.4 与 catalog SKILL.md 第 185–187 行全部一致**。 | `round2_checks.json` `committed_demo_sizes`、`round2d_checks.json` |

---

## 2. P2 逐条验证

| ID | 问题 | 判定 | 我的验证 | 证据 |
|---|---|---|---|---|
| P2-1 | `--spec` 遇 UTF-8 BOM / UTF-16 报原始错误 | **FIXED** | ① UTF-8-BOM spec（首字节 `EF BB BF`）→ exit 0，stdout 纯 JSON，repair `added_h=120`；② **UTF-16LE**（PowerShell 5.1 `>` 默认，首字节 `FF FE`）→ exit 0、纯 JSON、`added_h=120`；③ 我额外测 **UTF-16BE**（`FE FF`）→ exit 0、纯 JSON；④ 非法 JSON spec → exit 1、stdout 为空、stderr 可读（`error: --spec 不是合法 JSON（…）：Expecting property name … 提示：… 支持 UTF-8/UTF-8-BOM/UTF-16 …`）。 | `round2c_checks.json`、`runs/review_round2/spec_bom.json` / `spec_utf16.json` / `spec_utf16be.json` / `spec_bad.json` |
| P2-2 | 失败 run 的 report 重复 failed 步骤、缺第 4 节 | **FIXED** | 纯有机 CIF + 要求 `sod`（`--spec`）：exit 1；manifest `ok=false, failed_step=verify-topology`；`failed` 步骤条目 **恰好 1 个**；report 中 `❌ verify-topology` 出现 **1 次**；report 有 `## 4. 校验：未运行（步骤 \`verify-topology\` 失败）`；失败 run 仍写 manifest/report（artifacts = raw.cif/manifest/report 3 项）。 | `round2_checks.json` `failed_run`、`runs/review_round2/fail_run/` |
| P2-3 | report 缺 slab 厚度/终止面依据 | **FIXED** | 新 run 与仓库留档 report 均含 `## 3. 结构几何（实测）`：`切面 (111), frame=slab, reps=(2,2,1)`、`base=552 → 2208`、`slab 厚度 19.283 Å`、`终止面选择 shift=0.207317, dangling_bonds=20`、`生成时垂直真空 15.0`、`最小周期像距离 15.24`、`最终垂直真空 15.0`、最终原子数/组成/晶胞。数值与 manifest 逐项一致（厚度 19.283 vs 19.283；最终晶胞 [48.1661,48.1661,34.2826]、[90,90,60]）。 | `round2_checks.json` `report`；`runs/demo_sod_zif8/report.md` §3 |
| P2-4 | `manifest.artifacts` 不含 manifest/report 自身 | **FIXED** | 非 ingest run：`artifacts` 11 项（含 `manifest`、`report`）；`--ingest` run：12 项（再含 `library`）；仓库留档 demo：12 项。三种情况**所有 artifact 路径都真实存在**（`missing=[]`）。 | `round2d_checks.json` `artifact_paths` |
| P2-5 | `verify_demo` 检查名含 DOI 但未校验 | **PARTIAL** | 缺失 DOI：`[FAIL] 1 来源追溯（sha256/record/DOI）`，7/8（**真的会失败**）✓；但**伪造 DOI 仍 PASS**：把 manifest `record.doi` 改成 `10.9999/fake.doi`（provenance 仍是原值）→ 8/8 PASS；两处都改 → 8/8 PASS；删 `doi_note` 但保留 DOI → 8/8 PASS（与 PIPELINE §8 声称"curated 来源必须显式标注"不符）。即：只查"DOI 非空 + note 语义"，不查真伪、也不做 `record.doi == provenance.doi` 一致性。 | `round2b_checks.json` `doi_tamper`；`runs/review_round2/tamper_doi_*/` |
| P2-6 | "DESIGN §1 是 9 条、文档说 8 条" | **PARTIAL** | 已改：README L27、catalog SKILL L49/168 均写"9 条验收，其中 8 项自动复核"✓；SKILL 实测复核证据行同步 ✓。仍残留：**README L112** 还写"`tests/test_cli.py`（7 条 CLI 合同测试），测试总数 **126**"，与同文件 L83 `127 passed`、L88 `cli 8` 矛盾；`docs/PIPELINE.md` §3 标题仍是"八条验收标准"（表格 8 行本身没错，但未注明 9→8 映射）。 | `README.md:112`；`docs/PIPELINE.md:67` |
| P2-7 | standardize 整数倍守卫依据未落盘 | **FIXED** | `manifest.steps[standardize].data.geom_info` 实测含 `kept="input"`、`reason="input is already a 2x cell of the 138-atom primitive cell (276 atoms); keeping the input setting instead of re-standardising to a different conventional cell"`、`primitive_atoms=138`；新跑 run 与仓库留档 demo 都有。 | `round2_checks.json` `manifest.standardize_geom_info`；`runs/demo_sod_zif8/manifest.json` |

---

## 3. 新发现的问题（P0/P1/P2）

**P0：无。P1：无。**

### P2-N1 README 内部数字仍自相矛盾（126/7 条 vs 127/8 条）

- 位置：`README.md:112`（Round 2 记录条目）。
- 证据：`README.md:83` 写 `# 127 passed`；`README.md:88` 写 `… / cli 8`；`docs/PIPELINE.md:213` 写 `119 → 127（新增 tests/test_cli.py 8 条）`；但 L112 仍写"新增 `tests/test_cli.py`（7 条 CLI 合同测试），测试总数 **126**"。
- 复现：`Select-String -Path README.md -Pattern '126|127'`。
- 期望 vs 实际：三处应一致为 127/8 条；实际 L112 未更新（Leads 的 UTF-16 增强只改了 L83/L88，漏了 L112）。
- 建议：把 L112 改为"8 条 CLI 合同测试，测试总数 127（含 UTF-16 spec 支持）"。

### P2-N2 工作树未提交 + 新增文件未跟踪（交付基线风险）

- 现状（评审时）：`git status --porcelain` →
  `M README.md`、`M cifkit/cli.py`、`M docs/PIPELINE.md`、`M tests/test_cli.py`、`?? scripts/check_all.py`。
- 基线 `commit a3e4bde` 只含"126 tests / 7 条 CLI / 无 UTF-16"的版本；**UTF-16 自动识别、127 测试、README/PIPELINE 新数字都在工作树里未提交**。`scripts/check_all.py`（Lead 新增的一键健康检查脚本，实跑 `--fast --skip-agentlib` → 3/3 组 PASS，exit 0）也是未跟踪文件。
- 风险：若以 commit 作为最终交付/评审基线，上述修复"不存在"；若以工作树交付，这些文件未入库。
- 建议：收尾前 `git add -A && git commit`（含 `scripts/check_all.py` 若要保留），并在 REVIEW 报告里记录最终 commit hash。

### P2-N3 PIPELINE §7.3 的"粘贴输出"仍非逐字一致

- 实测 `scripts/verify_demo.py runs/demo_sod_zif8` 第 1 项 detail 为：
  `sha256 matches=True record=… doi=10.1021/ja204757x doi_note=DOI 来自 curated 文献关联（NCR 无元数据列）`；
  §7.3 转抄成 `doi_note=curated`。
- 实测第 5 项 detail 为 `… measured_vacuum=15.000Å target=15.0 reported=14.999999999999993`；§7.3 丢了 `reported=`。
- `artifacts=12` 已正确（P1-3 的数字问题已修）。属"证据块转抄未逐字"的低风险文档问题。
- 建议：直接贴原始输出（文档里注明生成命令与 run）。

### P2-N4 PIPELINE §7.1 未记录 UTF-16 支持；§7.2 的 `surface elapsed ≈1.5 s` 与实测有漂移

- `docs/PIPELINE.md:143` 仍写"`--spec` 支持 UTF-8/UTF-8-BOM"（未提新增的 UTF-16，与 §8 / README 不一致）。
- `docs/PIPELINE.md:154` 写 `surface … elapsed ≈1.5 s`；实测该步 `elapsed_s` 为 2.23 s（本轮新跑）与 2.89 s（仓库留档），Round 1 为 3.63 s。属机器负载波动，建议改为"≈2–4 s（随负载）"或删掉单个数字。

### P2-N5 `report.md` 的"产物"清单在非 `--ingest` 时不含 report/manifest 自身

- 现象：非 ingest run 的 `report.md` §5 只有 9 行（raw…preview），不含 `- report:` / `- manifest:`；而 `--ingest` run 因 `finish_run` 被调用两次，report 里有 13 行（含 report/manifest/library）。同一 build、同一份 manifest 的 `artifacts` 两种情况都包含 manifest/report。
- 根因：`provenance.finish_run()` 先 `render_report()` 再登记 report/manifest，非 ingest run 只调用一次。
- 影响：小（manifest 才是真源）；但"report 与 manifest 的产物清单不一致"会在人工复核时造成困惑。
- 建议：render 前把 report/manifest 路径先登记，或渲染后重写一次 report（像 ingest 路径那样）。

### P2-N6 `verify_demo` 的 DOI 校验弱（P2-5 的残留，独立列一条以便跟踪）

- 现状：只检查 DOI 非空 + `doi_note`（若存在）包含 curated/metadata；**不检查 `record.doi` 与 `provenance.doi` 是否一致、不校验 DOI 语法（`^10\.\d{4,9}/`）**。
- 后果：`record.doi` 被改、或两处一起被改成任意字符串，仍 8/8 PASS（见 §2 P2-5 的 4 个篡改场景）。
- 建议（低成本）：加 `record.doi == provenance.doi`（或明确允许单侧缺省）与正则检查；在线真伪校验可留给人工（报告里注明"offline presence check only"），不要声称"校验 DOI 真伪"。

---

## 4. 回归复核（全部由评审员重跑）

| 检查 | 命令 | 结果 | 证据 |
|---|---|---|---|
| 全量测试 | `.venv\Scripts\python.exe -m pytest tests` | **exit 0**；**`127 passed, 2 warnings in 63.26s`**；进度点 72+55=127；collect 分布 **cli 8 / export 20 / geom 34 / pipeline 3 / repair 12 / sources 17 / spec 6 / topology 15 / validate 12 = 127** | `pytest_capture.txt`、`pytest_summary_full.txt`、`pytest_collect_utf8.txt` |
| CLI 合同测试 | `pytest tests/test_cli.py` | 8 个点全过，exit 0 | `pytest_cli_capture.txt` |
| 独立验收（新跑） | `scripts/verify_demo.py runs/review_round2/demo` | **8/8 PASS**，`report=True steps=10 artifacts=11`（非 ingest） | `round2b_checks.json` `fresh` |
| 独立验收（ingest） | `scripts/verify_demo.py runs/review_round2/demo_ingest` | **8/8 PASS**，`artifacts=12` | `round2b_checks.json` `ingest` |
| 独立验收（仓库留档） | `scripts/verify_demo.py runs/demo_sod_zif8` | **8/8 PASS**，`artifacts=12`，check1 含 doi + doi_note | `verify_committed_utf8.txt` |
| 重跑一致 | 新 demo vs `runs/demo_sod_zif8` 9 个结构产物 sha256 | **9/9 逐字节相同**（raw/repaired/standardized/slab/final/vasp/cif/xyz/preview） | `round2_checks.json` `byte_identical_all=true` |
| demo `--json` | `pipeline "<原句>" --outdir runs/review_round2/demo … --json` | exit 0；stdout 合法 JSON；stderr 有步骤日志；wall ≈8 s | `round2_checks.json`、`round2c` |
| ingest `--json` | 同上 `--ingest` | exit 0；纯 JSON；artifacts=12（含 library） | `round2_checks.json` |
| 失败 run `--json` | 纯有机 spec（`topology=sod`） | exit **1**；stdout 仍为合法 JSON（`ok=false`）；stderr 有日志 | `round2_checks.json` |
| selftest | `-m cifkit selftest` | 7/7，exit 0 | `selftest.txt` |
| 路由 | `router.py route --agent dsh "<原句>"` | intent `cif-structure-pipeline`；第 1 候选 **cif-workbench**（score 82） | `router_route.txt` |
| eval | `eval_router.py --all` | cases=73；intent/skill top1 73/73；top5 73/73；负例 0/25 误报；槽位 11/11；exit 0 | `eval_router.txt` |
| ci | `ci.py --fast` | 同上，exit 0 | `ci.txt` |
| 一键健康检查（Lead 新增） | `scripts/check_all.py --fast --skip-agentlib` | 3/3 组 PASS（selftest / pytest-fast / verify_demo），exit 0 | 运行输出（`scripts/check_all.py` 未跟踪） |
| 技能正文数字 | `catalog/cif-workbench/SKILL.md` | 真空 15.000 + min_image 分开、字节数 15379/300594/5248/74320、9 条/8 项 —— 与实测一致 | 见 §5 |
| 仓库状态 | `git status --porcelain` | 仅 Lead 的 4 个 M + `?? scripts/check_all.py`；评审员未改任何被跟踪文件 | §3 P2-N2 |

---

## 5. 文档数字 vs 实测（抽查 Lead 声称的改动落点）

| 文档位置 | 声称 | 实测 | 判定 |
|---|---|---|---|
| PIPELINE §7.2 surface | `vacuum_measured=15.000（垂直）`、`min_image_distance=15.2396` | manifest surface：15.0 / 15.2396 | ✓ |
| PIPELINE §7.2 vacuum | 垂直真空 measured 15.000；min_image 15.240 另计 | vacuum.measured=14.999999999999993 = 15.000 | ✓ |
| PIPELINE §7.3 | `artifacts=12` | verify_demo 实测 artifacts=12 | ✓（转抄非逐字，P2-N3） |
| PIPELINE §7.4 | 15379 / 15379 / 300594 / 5248 / 74320 / 10816 / 121521 / 152719 / 134797 | 与 `runs/demo_sod_zif8` 逐项相同 | ✓ |
| catalog SKILL L177-178 | vacuum=15.000（min_image=15.2396 另列）；measured=15.000（min_image 15.240 另计） | manifest 同 | ✓ |
| catalog SKILL L185-187 | 同上字节数 + `report.md 5248`、`manifest 74320` | 同 | ✓ |
| catalog SKILL L49/168 | "DESIGN §1 的 9 条验收，其中 8 项自动复核" | verify_demo 8 项 | ✓ |
| README L27 | 同上 | ✓ | ✓ |
| README L83/L88 | 127 passed；测试分布 … cli 8 | collect 127，分布一致 | ✓ |
| README L112 | "7 条 CLI 合同测试，测试总数 126" | 实际 8 条 / 127 | **✗ P2-N1** |
| PIPELINE §7.1 L143 | `--spec` 支持 UTF-8/UTF-8-BOM | 实际还支持 UTF-16（未写） | **✗ P2-N4** |
| PIPELINE §7.2 L154 | surface elapsed ≈1.5 s | 实测 2.23–3.63 s（负载相关） | 漂移（P2-N4） |
| PIPELINE §8 | P2-5 "curated 来源必须显式标注" | 删掉 `doi_note` 仍 8/8 PASS | **✗ 与实现不符（P2-N6）** |

---

## 6. 我实际跑过的东西（命令 + 关键输出）

> 脚本：`runs/review_round2/verify_round2.py`（主验证）、`verify_round2b.py`（verify_demo + DOI 篡改）、`verify_round2c.py`（UTF-16BE/非法 JSON/失败 ingest/耗时）、`verify_round2d.py`（artifact 路径/report 产物/转抄块比对）。

1. `git log --oneline -5` / `git status --porcelain` / `git diff --stat a3e4bde..HEAD` / `git diff`（确认基线 commit 与未提交改动，见 P2-N2）。
2. `python -m cifkit pipeline "<原句>" --outdir runs/review_round2/demo --format vasp,cif,xyz --json` → exit 0、stdout 纯 JSON、stderr 有 `[resolve] ok …`；10 steps；11 artifacts。
3. 同上 `--ingest` → 12 artifacts（含 library），stdout 纯 JSON。
4. `scripts/verify_demo.py` 三个 run → 8/8 PASS（artifacts 11/12/12），check1 打印 doi + doi_note。
5. 9 个结构产物的 sha256 对比 `runs/demo_sod_zif8` → 全同。
6. `--spec` BOM（EF BB BF）/ UTF-16LE（FF FE）/ UTF-16BE（FE FF）/ 非法 JSON → 前三个 exit 0 纯 JSON；非法 JSON exit 1 + 可读 stderr。
7. 纯有机 spec：`--json` → exit 1，stdout 合法 JSON（ok=false），manifest failed_step=verify-topology、failed 条目 1 个；report 含"校验：未运行（步骤 `verify-topology` 失败）"；`--ingest` 失败 run 不崩（exit 1、library=null、report 存在）。
8. DOI 篡改 4 场景（缺 DOI / 只改 record.doi / 两处都改 / 删 doi_note）→ 缺 DOI 7/8 FAIL，其余 8/8 PASS。
9. `pytest tests` → 127 全过 exit 0；`pytest tests/test_cli.py` → 8 全过；`pytest --collect-only` → 127（cli 8 等）。
10. `pytest` 各模块分布核对；`selftest` 7/7。
11. `router.py route` / `eval_router --all` / `ci.py --fast` → 一候选 cif-workbench；73/73、负例 0/25、槽位 11/11；exit 0。
12. `scripts/check_all.py --fast --skip-agentlib` → 3/3 PASS。
13. 全项目 + catalog grep `15.2396/15.240/artifacts=10/15489/126/7 条` → 仅剩本轮点出的 P2 残留。
14. 文档 §7.4/§7.2 数字与 `runs/demo_sod_zif8` 实测逐项比对；§7.3 粘贴块 vs 实际 verify 输出逐字段比对。

## 7. 我没有验证的部分

1. **未提交工作树的最终 commit**：本报告结论针对评审时的工作树（`a3e4bde` + 未提交增强）。Lead 提交后应复核最终 commit hash 与工作树一致（尤其 `scripts/check_all.py` 是否入库）。
2. **新测试的"有效性"只到"能跑且通过"层面**：`test_spec_with_utf16_encoding` 用 Python 写 UTF-16（带 BOM），不是我验证的 PowerShell 5.1 `>` 实际输出，但两者字节格式一致（`FF FE` 开头），我用 PowerShell 风格 BOM 的 UTF-16 独立跑通了 CLI；未验证"UTF-16 无 BOM"（PowerShell 不会产生这种）。
3. **DOI 真伪**：仍未联网复核本轮 manifest（Round 1 已用 Crossref 核实过），本轮只测"缺失/篡改检测能力"。
4. **`report.md` 在失败 run 中无第 3 节**（无 surface 步骤，属预期）——未要求补空节，只确认第 4 节存在。
5. **`scripts/check_all.py`** 只跑了 `--fast --skip-agentlib`；未跑完整（full pytest + agentlib），因为它会重复我已在做的检查。
6. 冷启动下载、非 (111) 面、高指数面、COD 名称检索、Materials Project 等 Round 1 的未验证项依旧未验证（本轮范围是"修复 + 回归"）。
7. `manifest.artifacts` 中 `library` 是**目录**而非文件；我按目录存在性检查（存在 ✓），未校验目录内每个副本的 sha256。

---

## 8. 证据索引（`runs/review_round2/`）

| 文件/目录 | 内容 |
|---|---|
| `demo/`、`demo_ingest/`、`demo_timed/`、`demo_timed2/` | 本轮新跑产物（--json / --ingest / 计时） |
| `round2_checks.json`、`round2b_checks.json`、`round2c_checks.json`、`round2d_checks.json` | 四个验证脚本的结构化结果 |
| `verify_round2*.py`、`verify_round2*.log` | 验证脚本与日志 |
| `verify_committed_utf8.txt` | 仓库留档 demo 的 verify_demo 原始输出（UTF-8） |
| `pytest_capture.txt` / `pytest_summary_full.txt` / `pytest_cli_capture.txt` / `pytest_collect_utf8.txt` | 127 全过、cli 8、collect 分布 |
| `selftest.txt`、`router_route.txt`、`eval_router.txt`、`ci.txt` | 回归输出 |
| `spec_bom.json` / `spec_utf16.json` / `spec_utf16be.json` / `spec_bad.json`、`bom_run/`、`utf16_run/`、`utf16be_run/` | P2-1 各编码场景 |
| `fail_run/`、`fail_ingest/` | P2-2 失败 run（含 --ingest） |
| `tamper_doi_missing/`、`tamper_doi_fake_record/`、`tamper_doi_fake_both/`、`tamper_doi_missing_note/`、`tamper_doi_note_missing/` | P2-5 DOI 篡改场景 |
| `bom_spec_error.txt` | Round-1 时期的 BOM 失败对照（旧行为） |
| `../demo_sod_zif8/` | 仓库留档（Lead 已按新 build 重新生成 manifest/report） |
