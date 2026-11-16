# Round 3 轻量确认（收尾项 + 提交状态）— CIF 处理工作台

> 评审员：`reviewer-r1`｜日期：2026-11-05｜时间盒内只做收尾确认，不重跑全量审计。
> 对象：`D:\Dev\Project5-skill-cif`（工作树，`HEAD=a3e4bde` + Round-4 未提交改动）+ `D:\agent-library`。
> 方法：逐条构造最小命令验证 Round 2 报告的 PARTIAL P2-5 / P2-6 与 6 条新 P2 的收尾；**未改代码/文档**（只写本文件与 `runs/review_round3/`）。

## 0. 结论

**PASS（收尾项全部 FIXED，无新 P0/P1）。**

- Round 2 遗留的 **2 个 PARTIAL**：P2-5（DOI 校验）**FIXED**，P2-6（README 126）**FIXED**。
- Round 2 的 **6 条新 P2**：5 条 FIXED；1 条（"工作树未提交"）在本报告写作时**仍处于未提交状态**——Lead 已说明会在本次复核后 `git add -A` 提交，属预期流程，不是缺陷，但需要提交后才能作为最终交付基线。
- 回归抽查全绿：`check_all.py --fast` **6/6 组 PASS**、`pytest tests/test_cli.py` 8 条 exit 0、127 tests collected、`verify_demo` 三个 run 均 8/8（artifacts 12/11/12）、`--online` Crossref status=200 + 真实标题。
- 只新增 1 条**极低风险文档 nit**（§8 历史条目对 `finish_run` 顺序的描述已被 §8.1 取代，见 §3）。

**验证时的 git 状态（记录在案，供最终提交后比对）**：

```text
$ git -C D:\Dev\Project5-skill-cif status --short
 M README.md
 M cifkit/cli.py
 M cifkit/provenance.py
 M docs/PIPELINE.md
 M runs/demo_sod_zif8/manifest.json
 M runs/demo_sod_zif8/report.md
 M scripts/verify_demo.py
 M tests/test_cli.py
?? docs/REVIEW-ROUND2.md
?? scripts/check_all.py
$ git log --oneline -2
a3e4bde round2: fix review P1/P2 (...); add tests/test_cli.py (126 tests)
a3056f5 docs: final README with verified demo numbers; ...
```

> 即：**Round 4 的全部改动在写报告时尚未 commit**；`docs/REVIEW-ROUND1.md` 已在 `a3e4bde` 中跟踪，`REVIEW-ROUND2/3` 未提交。最终提交后若需再确认，直接对比新 commit 的 `git show --stat` 与本节清单即可。

---

## 1. 逐条确认

### 1.1 P2-5 PARTIAL（DOI 校验强化）— **FIXED**

`scripts/verify_demo.py` 新版逻辑（已读代码确认）：DOI 正则 `^10\.\d{4,9}/\S+$` + `record.doi == provenance.doi` 一致性 + curated/metadata 标注必需；`--online` 追加 Crossref 解析。

| 场景（评审员自建副本，均在 `runs/review_round3/`） | 结果 | check-1 detail 关键字段 |
|---|---|---|
| 真 demo 离线 `verify_demo.py runs/demo_sod_zif8` | **8/8 PASS**，exit 0 | `fmt=True consistent=True note_ok=True (offline: existence 未联网核验，用 --online 可查 Crossref)` |
| 真 demo `--online` | **8/8 PASS**，exit 0 | `… crossref=status=200 title='Capture of Volatile Iodine, a Gaseous Fission Product, by Zeolitic Imidazolate F'` |
| tamper①：改 `record.doi=10.9999/fake.doi` | **FAIL 第 1 项**，exit 1（7/8） | `fmt=True consistent=False` |
| tamper②：删 `provenance.doi_note` | **FAIL 第 1 项**，exit 1（7/8） | `fmt=True consistent=True note_ok=False` |
| tamper③：两处都改成 `not-a-doi` | **FAIL 第 1 项**，exit 1（7/8） | `fmt=False` |

- **诚实性**：离线 detail 明确写"existence 未联网核验"，文档 PIPELINE §7.3 第 177 行也如实说明"离线模式只做格式/一致性/curated 标注检查"；`--online` 才查 Crossref。没有把离线存在性检查冒充"DOI 真伪已验证"。**FIXED。**

### 1.2 P2-6 PARTIAL（README 126/7 条残留）— **FIXED**

- `README.md` 现为：L86 `# 127 passed`、L92 `… / cli 8`、L116 "新增 tests/test_cli.py（**8 条** CLI 合同测试），测试总数 **127**"、L27 "DESIGN §1 的 **9 条**验收，其中 **8 项**自动复核"。
- `docs/PIPELINE.md` §8 末尾同步为 119 → **127**（8 条 CLI 测试）。
- `catalog/cif-workbench/SKILL.md` L49/L168 同样为"9 条验收，其中 8 项自动复核"，L177/178 真空 15.000 与 min_image 分列。
- 残留 grep `126 / 7 条 CLI / 15.2396`：只剩合法命中（`min_image_distance=15.2396` 的明确标注、PIPELINE §8 历史条目、REPAIR 的 126° 键角），无新的口径错误。**FIXED。**

### 1.3 新 P2-3/4/5（§7.3 非逐字、§7.1 UTF-16、§7.2 耗时）— **FIXED**

- `docs/PIPELINE.md` §7.1 L143：`--spec` 支持 **UTF-8 / UTF-8-BOM / UTF-16** ✓（代码 `cli._read_spec_text()` 已实现，Round 2 已实测三种编码 + 我实测 UTF-16BE）。
- §7.2 L154：`elapsed 2–4 s（随机器负载）` ✓（实测 2.23/2.89/3.63 s）。
- §7.3 L166–173 已更新为当前实测格式：`fmt=True consistent=True note_ok=True`、`reported=14.999999999999993`、`artifacts=12`；§7.3 后新增一行说明 `--online` 与离线限定 ✓。与本次实跑的 `verify_demo` 输出逐字段一致（除转抄时省略的 detail 长文本）。

### 1.4 新 P2-6（report 产物清单与 manifest 一致）— **FIXED**

`cifkit/provenance.py::finish_run` 已改为**先把 report/manifest 路径登记进 `result.artifacts` 再渲染 report**（读 diff 确认），`--ingest` 分支二次重写。评审员用本地 fixture 各跑一次：

| run | manifest.artifacts 键数 | report "5. 产物" 行数 | 含 `report` | 含 `manifest` | 含 `library` |
|---|---|---|---|---|---|
| 非 `--ingest`（`runs/review_round3/parity_non_ingest/`） | **7** | **7** | ✓ | ✓ | —（未 ingest，符合预期） |
| `--ingest`（`runs/review_round3/parity_ingest/`） | **8** | **8** | ✓ | ✓ | ✓ |
| 仓库留档 `runs/demo_sod_zif8/`（ingest） | **12** | **12** | ✓ | ✓ | ✓ |

（Round 2 时非 ingest 是 9 行且缺 report/manifest，现 7/7 与 8/8 完全对齐。）**FIXED。**

### 1.5 新 P2-2（工作树未提交 / check_all.py 未跟踪）— **尚未发生（预期流程）**

- 写报告时 `git status --short` 仍列出 9 个 M + 2 个 `??`（见 §0）；`scripts/check_all.py` 仍 untracked。
- Lead 已声明"之后我会 git add -A 做最终提交"；本报告将其记为**提交前状态**，不计缺陷。最终提交后请以新 commit 复核。
- `scripts/check_all.py` 本体我已实跑：`--fast` **6/6 组 PASS，exit 0**（selftest / pytest-fast / verify_demo / router / eval_router / ci），功能正常，建议保留并提交。

---

## 2. 回归抽查（轻量，非全量）

| 检查 | 命令 | 结果 | 证据 |
|---|---|---|---|
| 一键体检（fast） | `.venv\Scripts\python.exe scripts\check_all.py --fast` | **6/6 组 PASS，exit 0**：selftest 7/7；pytest(cli+spec) 14 点；verify_demo 8/8 artifacts=12；router 第一候选 cif-workbench；eval/ci 73/73、负例 0/25、槽位 11/11 | `runs/review_round3/check_all_fast.txt` |
| 一键体检（full） | `.venv\Scripts\python.exe scripts\check_all.py` | **6/6 组 PASS，exit 0**：selftest 7/7；**pytest full 60.3 s**；verify_demo 8/8 artifacts=12；router 第一候选 cif-workbench；eval/ci 73/73、负例 0/25、槽位 11/11 | `runs/review_round3/check_all_full.txt` |
| CLI 合同测试 | `pytest tests/test_cli.py -q` | **exit 0**，8 条（pipeline JSON、manifest 自含、BOM、UTF-16、失败 report、非法格式、route exit2、repair 建父目录） | `runs/review_round3/pytest_cli.txt` |
| 测试收集 | `pytest tests --collect-only` | **127 tests collected**（cli 8 + 其余 119） | `runs/review_round3/pytest_collect.txt` |
| verify_demo ×3 | `verify_demo.py runs/demo_sod_zif8` / `runs/review_round2/demo` / `.../demo_ingest` | **均 8/8 PASS**（artifacts 12 / 11 / 12） | `runs/review_round3/verify_runs_*.txt`、`round3_checks.json` |
| 文档字节数 | `runs/demo_sod_zif8/` 实测 vs PIPELINE §7.4 | report 5248 / manifest 74320 / repaired 15379 / preview 300594 … **全部一致** | 见 §3 |
| 仓库卫生 | `git ls-files` 过滤 `_cache/library/runs` | 只有 `runs/demo_sod_zif8/` 12 个归档文件被跟踪；无 `_cache`、无 `library`、无评审 run；最大跟踪文件 300 KB（preview.png） | 命令输出 |
| agent-library | `git log -1` / `git show --stat HEAD` | 最近 commit 含 5 个 `catalog/cif-*/SKILL.md` + manifest + `intents.json`/`domains.json`/`evals/routing.jsonl`；工作树干净（仅一个与本任务无关的历史 untracked `catalog/condopt-router/`） | 命令输出 |

---

## 3. 文档数字与实测（收尾抽查）

| 位置 | 声称 | 实测 | 判定 |
|---|---|---|---|
| README L27/L86/L92/L116 | 9 条/8 项；127 passed；cli 8；8 条/127 | collect 127、test_cli 8 | ✓ |
| PIPELINE §7.1 L143 | UTF-8 / BOM / UTF-16 | CLI 三种都实测通过 | ✓ |
| PIPELINE §7.2 L154 | elapsed 2–4 s | 2.23 / 2.89 / 3.63 s | ✓ |
| PIPELINE §7.3 L166–173 | fmt/consistent/note_ok、reported=、artifacts=12 | 实跑输出逐字段一致 | ✓ |
| PIPELINE §7.4 | 5248 / 74320 / 15379 / 300594 / 10816 / 121521 / 152719 / 134797 | 与 `runs/demo_sod_zif8/` 逐项相同 | ✓ |
| catalog SKILL L49/L168/L177/L178 | 9 条/8 项；真空 15.000 + min_image 分列 | 与 README/PIPELINE 一致 | ✓ |
| 残留 grep | 无 "126/7 条 CLI" 口径错误 | 仅合法引用 | ✓ |

---

## 4. 新发现（P0/P1/P2）

**P0：无。P1：无。**

- **P2-N1（极低风险，文档 nit）**：`docs/PIPELINE.md` §8（Round-2 历史表）P2-4 行仍写"`finish_run` 先写 report 再写 manifest，两者互相登记"，而 Round-4 已改为"先登记 report/manifest 再渲染 report"；§8.1 的新描述是正确的。两处并存可能让读者困惑。
  - 证据：`docs/PIPELINE.md:209` vs `docs/PIPELINE.md:222`（§8.1 新 P2-6 行）。
  - 建议：把 §8 该行改为"（Round 4 起：先登记后渲染，见 §8.1）"，或删掉顺序描述只留结论。
- **流程项（非缺陷）**：项目仓尚未最终提交（§0）；`docs/REVIEW-ROUND2/3.md` 与 `scripts/check_all.py` 仍是 untracked，需在 `git add -A` 时确认包含。agent-library 仓的 `catalog/condopt-router/` 是无关的历史 untracked 目录，与本任务无关（但若要求 agent-library `git status` 全空，需要 Lead 决定是否处理）。

---

## 5. 未验证项（本轮轻量确认范围外）

1. **最终 commit 内容**：写报告时提交尚未发生；提交后建议用 `git show --stat HEAD` 对照 §0 清单（尤其 `scripts/check_all.py`、`docs/REVIEW-ROUND2/3.md`、`runs/demo_sod_zif8/{manifest,report}`、`cifkit/provenance.py`、`scripts/verify_demo.py`、`tests/test_cli.py`）确认无遗漏/无多余大文件。
2. **`--online` 的失败路径**：只验证了真实 DOI 的 200/title；未构造"网络可达但 Crossref 404/超时"的场景（代码会返回 `ok=False` 并 FAIL 第 1 项，属预期）。
3. **`check_all.py` full 模式**：已完整跑完（`runs/review_round3/check_all_full.txt`，6/6 组 PASS，exit 0，full pytest 60.3 s），与 fast 结果一致；未单独再跑一次。
4. **CI/评测重跑**：只通过 `check_all.py` 的 fast 模式跑了 router/eval/ci（数字与 Round 1/2 一致）；未单独再跑 `eval_router --all`（fast 已覆盖）。
5. **与最终 commit 对应的产物字节数**：§3 的字节数对应当前工作树的 `runs/demo_sod_zif8/`；若提交时重新生成 demo，需重新核对 §7.4。
6. Round 1/2 已列出的深层未验证项（冷启动下载、非 (111) 面、Zr6 SBU、COD 名称检索等）本轮不再重复。

---

## 6. 证据索引（`runs/review_round3/`）

| 文件/目录 | 内容 |
|---|---|
| `round3_checks.json`、`confirm_round3.py/.log` | DOI 离线/在线/3 个 tamper + report 产物 7/7、8/8 的结构化结果 |
| `tamper_fake_record_doi/`、`tamper_no_doi_note/`、`tamper_fake_both/` | P2-5 三类篡改副本（manifest 已改，结构与 raw.cif 来自留档 demo） |
| `parity_non_ingest/`、`parity_ingest/` | report 产物清单一致性验证 run（7/7、8/8） |
| `verify_runs_review_round2_demo*.txt` | 另两个 demo run 的 8/8 原始输出 |
| `pytest_cli.txt`、`pytest_collect.txt` | test_cli 8 条 exit 0；127 tests collected |
| `check_all_fast.txt`、`check_all_full.txt` | 一键体检 fast 6/6（21 s）/ full 6/6（60.3 s pytest） |
| `REVIEW-ROUND2.md`、`REVIEW-ROUND3.md`（同目录） | Round 2/3 报告 |

> 备注：`check_all.py` full 已跑完 → `CHECK_ALL_FULL_EXIT=0`、6/6 组 PASS（full pytest 60.3 s），与 fast 一致。
