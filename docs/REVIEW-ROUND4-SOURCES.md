# Round 4 轻量评审：数据源扩展（CoRE / COD / MP / AFLOW / local）

> 评审员：`reviewer-r1`｜日期：2026-11-05｜时间盒：轻量验证，只针对数据源扩展 + 回归，不重跑全量审计。
> 对象：`<repo>`、`<agent-library>`；**验证时工作树**：项目 `HEAD=819fa5a`（评审期间由 `5dce12c` 前进到 `819fa5a`），且评审结束时仍有 Lead 正在进行的未提交改动（见 §6）；agent-library `HEAD=b162d66`。
> 方法：所有命令由评审员本机重跑（COD/AFLOW 走真实网络，MP 不伪造 key）；**未改代码/文档**（只写本文件与 `runs/review_round4/`）。

## 0. 结论

**数据源扩展本体：PASS。** 5 个源真实可用（CoRE/COD/MP/AFLOW/local）；MP 的"无 key 只做 mock、未 live 实测"在 README/PIPELINE/SKILL 三处**如实标注**，没有伪造 live 结果；AFLOW 的 live 检索/下载/pipeline 我全部独立跑通，sha256、`%3A` 编码、`topology_evidence=unknown`、`aflow:<auid>` 限制均与文档一致；路由三类 query 第一候选正确，eval 79/79、负例 0/25、槽位 11/11、ci 绿。

但发现 **1 个 P1**（`fetch --json --outdir` stdout 不是合法 JSON，且这正是文档/技能里给出的组合用法）与 **3 个 P2**（文档测试数 139 与实测 141 不符；PIPELINE §8.2 有控制字符/转义损坏；cif-fetch SKILL 里 `raw.cif` 说明自相矛盾且有重复行）。详见 §2/§3。

| 维度 | 判定 |
|---|---|
| 5 个源齐全 + `cifkit sources`/`--json`/`--probe` | **PASS** |
| COD live（下载/sha/解析） | **PASS** |
| AFLOW live（检索/aurl 下载/%3A/sha/pipeline） | **PASS** |
| MP 无 key 失败路径 + mock 测试真实性 + 文档诚实性 | **PASS** |
| 拓扑诚实性（MP/AFLOW=unknown，无伪 verified） | **PASS** |
| 文档/技能命令与过期说法 | **PASS（有 3 个 P2 残留）** |
| 路由/评测/CI | **PASS** |
| `fetch --json` 机器可读性 | **FAIL → P1-1** |

---

## 1. 五个源逐条验证

### 1.1 源清单/状态（`cifkit sources`）

- `python -m cifkit sources` → exit 0，打印 5 个源；`--json` → **n=5**：`core-mof`（status `cache ready`，requires_auth=false）、`cod`（ready）、`local`（ready）、`materials-project`（**status `missing MP_API_KEY`**，requires_auth=true）、`aflow`（ready）。
- `--probe` → `core-mof cache ready`、`cod ready network=up`、`local ready`、`materials-project missing MP_API_KEY network=up` + 申请提示、`aflow ready network=up`；exit 0。
- 证据：`runs/review_round4/round4_checks.json` `sources_*`。

### 1.2 COD（live，评审员实跑）

```powershell
& $PY -m cifkit fetch --source cod --id 7111973 --outdir runs\review_round4\cod --json
```

- exit 0；`raw.cif` 实测 sha256 `963e1235…a8793` == `source.json.provenance.sha256`；`source.json` 的 note 明确写"raw_cif 是源 CIF 的**字节拷贝**，sha256 应与 provenance 一致"（诚实，与旧说法相反）；pymatgen 解析 348 原子、`Zn12 H120 C96 N48`；`topology_evidence="unknown"`，record_id=`cod:7111973`。
- 证据：`runs/review_round4/cod/`、`round4b_checks.json` `cod`。

### 1.3 AFLOW（live，评审员实跑）

| 检查 | 命令 | 实测 | 判定 |
|---|---|---|---|
| 化学式检索 | `fetch --source aflow --name ZnO --limit 2 --json` | exit 0，**2 hits**（`aflow:0265806d7329d48e` 等），formula `O8Zn4`，**evidence=unknown** | PASS |
| aurl 下载 | `fetch --source aflow --id "aflowlib.duke.edu:AFLOWDATA/LIB1_WEB/Zn:PAW_PBE:06Sep2000/A9" --outdir runs\review_round4\aflow --json` | exit 0；`raw.cif` sha256 `19cd50cf…ef367` == provenance.sha256；URL 实测含 `Zn%3APAW_PBE%3A06Sep2000.A9.cif`（`%3A` 编码生效）；缓存文件存在；evidence=unknown，formula `Zn4` | PASS |
| 进管线 | `pipeline --spec`（source=aflow, 同一 aurl） | exit 0，ok=true，7 artifacts；manifest `source.record.record_id=aflow:aflowlib.duke.edu-...`、`topology_evidence=unknown` | PASS |
| auid 限制 | `fetch --source aflow --id aflow:abc123` | exit 1，`ValueError: AFLOW 的 auid 不能直接检索；请改传 aurl/URL 或用 --name <化学式>` —— 与 docs §7c/§9 一致 | PASS |
| 请求拓扑 | `fetch --source aflow --topology sod --json` | exit 0，**0 hits**（不伪造命中） | PASS |
| 管线里请求拓扑 | `pipeline --spec`（source=aflow + `topology=sod`） | exit 1；`verify-topology` failed，**evidence=unknown**；未伪 verified | PASS |

证据：`runs/review_round4/round4_checks.json` `aflow_*`、`round4b_checks.json` `aflow_pipeline_manifest`。

### 1.4 Materials Project（无 key，评审员不伪造 key）

- 清空 `MP_API_KEY`/`PMG_MAPI_KEY` 后 `fetch --source mp --id mp-149` → **exit 1**，错误信息同时含 `MP_API_KEY` 与申请地址 `https://materialsproject.org/api`，无 traceback（`round4_checks.json` `mp_no_key`）。
- mock 测试真实性（读代码 + 实跑）：`tests/test_sources_mp_aflow.py::test_mp_search_and_fetch_mocked` 用 `monkeypatch.setattr(mp_mod, "_REQUEST_JSON", fake_request)` **真正绕过网络**，并断言：CIF 文件存在、`cif_generated is True`、`structure_json_sha256` 非空、`sha256 == cif_sha256`、search 走 `/materials/summary/`；不是空断言/`pass`。
- 文档诚实性（三处均有）：`README.md:134` "AFLOW/COD 为 **live 实测**；MP 因本机无 key 只做 **mock 测试**，文档/技能正文均写明需 key"；`docs/PIPELINE.md:239` "本机无 key 故未做 live 检索"；`catalog/cif-fetch/SKILL.md:197` "有 key 的解析路径用 mock 测试覆盖"。**未发现把 MP 写成 live 实测**。
- 证据：`round4_checks.json` `mp_no_key`；上面三处文档行。

### 1.5 CoRE / local

- CoRE：`sources` 显示 `cache ready`；本轮未重跑 CoRE 检索（Round 1/2/3 已实测 index 8300、sod 7 条、demo 路径），无回归。
- local：`sources` 显示 ready；本轮未单独跑 local fetch（Round 1/2 的多份 spec/本地 pipeline 已覆盖），无回归。

---

## 2. P0 / P1 / P2 清单

### P0：无。

### P1-1（新发现，既有缺陷被文档组合用法暴露）：`fetch --json --outdir` 的 stdout 不是合法 JSON

- 复现：
  ```powershell
  & $PY -m cifkit fetch --source cod --id 7111973 --outdir runs\review_round4\cod2 --json
  ```
- 期望（`--json` 语义 + SKILL "`--json` 输出（推荐，字段最全）"）：stdout 是 JSON，可 `json.loads`。
- 实际：stdout 先是 JSON 数组（正确），随后多出一行人类提示 `wrote runs\review_round4\cod2\raw.cif (sha256=963e1235...)`；`json.loads(stdout)` 报 `JSONDecodeError: Extra data: line 32 column 1`。**不带 `--outdir` 时 stdout 是纯 JSON**（已实测）。
- 影响面：`docs/SOURCES.md` §7d 与 `catalog/cif-fetch/SKILL.md` L55/L61/L65/L70/L73/L136 都给出 `fetch ... --outdir ... --json` 的组合用法；脚本/agent 按文档消费会失败。与 Round-1 P1-1（`pipeline --json`）同类，pipeline 已修、fetch 未修。
- 根因：`cifkit/cli.py::cmd_fetch` 在 `_print_json(hits)` 之后无条件 `print(f"wrote {path} ...")`。建议：`--json` 时把该行写 stderr（或并入 JSON 的 `written` 字段）。
- 证据：`runs/review_round4/round4b_checks.json` `fetch_json_with_outdir`（含 stdout_tail）；`fetch_json_no_outdir` 对照。

### P2-1 文档测试总数 139 与实测 141 不符（且树仍在变动）

- 声称：`README.md:97` `# 139 passed`、`README.md:133` "测试总数 **139**"、`docs/PIPELINE.md:248` "全套 **139** 条"。
- 实测（快照）：`pytest tests` → **141 passed, 2 warnings in 64.60s**，exit 0；`--collect-only` → **141 tests collected**（cli 10 / export 20 / geom 34 / pipeline 3 / repair 12 / sources 17 / sources_mp_aflow 11 / spec 7 / topology 15 / validate 12）。
- 说明：139 = 127 + 5dce12c 新增 10 mp_aflow + 2 cli；之后 `819fa5a` 又 +1 mp_aflow，另有 +1 spec 测试，合计 141；评审结束时 Lead 仍在改 `tests/test_spec.py`/`test_validate.py`，当前收集已变成 **143**。请在最终提交后按 `pytest tests` 实际数字统一更新。
- 证据：`runs/review_round4/pytest_summary.txt`、`pytest_collect.txt`、`pytest_collect2.txt`。

### P2-2 `docs/PIPELINE.md` §8.2 表格中存在控制字符/转义损坏

- 实测原始字节（`repr`）：
  - `'| \x07flow | sources/aflow.py | …'` —— 行首 `a` 被写成了 **BEL 控制字符 `\x07`**（显示成 "flow"），应恢复为 `aflow`；
  - `'CIF 文件名含 \\:\\ 需 percent-encode'` —— 字面 `\:` 转义残留，应为 `` `:` ``；
  - `'- 测试：新增 \tests/test_sources_mp_aflow.py…'` 与下一行 `'  \tests/test_cli.py…'` —— `tests/` 前是**字面 TAB/反斜杠**，应为 `tests/…`。
- 影响：Markdown 表格/文字可读性受损（内容仍可理解），不涉及数据正确性。
- 证据：`runs/review_round4/round4b_checks.json` 之外的 repr 命令输出（见 §5）；`docs/PIPELINE.md` §8.2。

### P2-3 `catalog/cif-fetch/SKILL.md` 内部自相矛盾 + 重复行

- 同一文件：L166–167 已改为正确说法"`fetch --outdir` 的 `raw.cif` 与 pipeline 一致，是源 CIF 的**字节拷贝**（`provenance.sha256` 可复核）"；但 **L177 仍写"（`fetch --outdir` 的 `raw.cif` 是重写文件，别拿它和 provenance 比；pipeline 的 `raw.cif` 才逐字节一致）"** —— 与本轮实测（COD source.json note、sha 相等）矛盾。
- 另有重复行：L163 与 L164 完全相同（"同名不同变体…"重复一次）；L161 与 L171 完全相同（"rcsr.anu.edu.au 不可达…"重复一次）。
- 影响：技能正文是"唯一真源"，会让 agent 错误地跳过 sha256 校验或重复执行。**建议优先修 L177 与两处重复行。**
- 证据：`runs/review_round4/`（见 §5 的读取记录）；`catalog/cif-fetch/SKILL.md:161,163-164,166-167,171,177`。

---

## 3. 文档/技能命令一致性（抽查）

- `docs/SOURCES.md` §7b/§7c/§7d 与 `catalog/cif-fetch/SKILL.md` 的 5 源命令：`sources`/`--probe`、COD `--id`、AFLOW `--name`/`--id`（aurl）、MP 无 key、AFLOW auid 限制全部实跑，行为与文档一致（§1）。
- 过期说法 grep：未发现 "fetch 没有 --id" / "available_sources 只有 3 个" / "只有 3 个源" / "3 个数据源"；`fetch --help` 确认有 `--id`、`--source`；`--help` 有 `sources` 命令。
- 但 `raw.cif 是重写文件` 这一过期说法**仍在 SKILL L177**（见 P2-3）。
- `docs/SKILLS.md` 已写"五个数据源"并新增 MP/AFLOW 路由示例 ✓；`catalog/cif-workbench/SKILL.md` 源表已含 5 源 ✓。

---

## 4. 路由 / 评测 / 回归

| 检查 | 结果 | 证据 |
|---|---|---|
| 原 demo 句 | intent `cif-structure-pipeline`，**第 1 候选 cif-workbench**（score 91） | `router_three.txt` |
| "从 Materials Project 下载 mp-149 的 CIF" | **第 1 候选 cif-fetch**（score 32） | 同上 |
| "从 AFLOW 下载 Zn 的晶体结构 CIF" | **第 1 候选 cif-fetch**（score 30） | 同上 |
| `eval_router.py --all` | cases=**79**；intent/skill top1 79/79；top5 79/79；负例 0/25；槽位 11/11；exit 0 | `eval_router.txt` |
| `ci.py --fast` | 同上，exit 0 | `ci.txt` |
| `pytest tests` | **141 passed, 2 warnings in 64.60s**，exit 0（快照；文档写 139，见 P2-1） | `pytest_summary.txt`、`pytest_collect.txt` |
| `cifkit sources` / `--probe` / `--json` | exit 0，5 源状态正确（MP missing key、core-mof cache ready） | `round4_checks.json` |
| 提交卫生 | 项目 `5dce12c` 含 `cifkit/sources/{materials_project,aflow}.py`、`tests/test_sources_mp_aflow.py`、`docs/SOURCES.md`、`cifkit/cli.py`；`819fa5a` 加公式 auto-select；agent-library `2975908`（5 源 skill/intents/domains/evals）+ `b162d66`（auto-source 规则） | `git show --stat` |

---

## 5. 我实际跑过什么（命令 + 关键输出）

1. `git log/status/show --stat`（项目 + agent-library），确认 `5dce12c`/`819fa5a`/`2975908`/`b162d66` 内容与工作树状态。
2. `python -m cifkit sources` / `sources --json` / `sources --probe` → 5 源、MP missing key、core-mof cache ready、cod/aflow network=up。
3. `fetch --source cod --id 7111973 --outdir runs/review_round4/cod --json` → exit 0；sha 一致；348 原子；evidence unknown（`source.json` note 为字节拷贝）。
4. `fetch --source aflow --name ZnO --limit 2 --json` → 2 hits，evidence unknown。
5. `fetch --source aflow --id "aflowlib.duke.edu:AFLOWDATA/LIB1_WEB/Zn:PAW_PBE:06Sep2000/A9" --outdir runs/review_round4/aflow --json` → exit 0；sha 一致；URL 含 `%3A`；cache 存在。
6. `pipeline --spec aflow_spec.json` → exit 0，7 artifacts，record `aflow:...`，evidence unknown。
7. `pipeline --spec aflow_sod_spec.json`（topology=sod）→ exit 1，verify-topology failed/unknown（不伪造 verified）。
8. `fetch --source aflow --topology sod --json` → 0 hits。
9. `fetch --source aflow --id aflow:abc123` → exit 1，清晰的 auid 限制提示。
10. 清空 `MP_API_KEY`/`PMG_MAPI_KEY` + `fetch --source mp --id mp-149` → exit 1，含 `MP_API_KEY` + `https://materialsproject.org/api`。
11. `fetch --source cod --id 7111973 --json`（无 outdir）→ 纯 JSON；带 `--outdir` → JSON + `wrote...` 行（P1-1）。
12. `pytest tests` → 141 passed / 64.60 s / exit 0；`--collect-only` → 141（后变 143，树仍在动）。
13. `router.py route` 三类 query → 第一候选 workbench/cif-fetch/cif-fetch；`eval_router --all` 79/79、负例 0/25、槽位 11/11；`ci --fast` 绿。
14. 读 `tests/test_sources_mp_aflow.py` 的 mock 测试实现（monkeypatch `_REQUEST_JSON`、断言 CIF/JSON 双 sha256）；读 `docs/SOURCES.md` §7b/7c/7d、`docs/PIPELINE.md` §8.2、`catalog/cif-fetch/SKILL.md` 相关行并 repr 检查异常字符。

## 6. 验证时的仓库状态（供最终提交后比对）

- 项目仓：`HEAD` 从 `5dce12c` 前进到 **`819fa5a`**（评审期间 Lead 提交了 formula-aware auto source selection）；
  - 评审进行中工作树曾出现未提交的 3 个 M（`sources/__init__.py`/`SOURCES.md`/`test_sources_mp_aflow.py`），随后被提交为 `819fa5a`；
  - **评审结束时**仍有 Lead 正在进行的未提交改动：`M cifkit/spec.py`、`M cifkit/validate/checks.py`、`M docs/PIPELINE.md`、`M tests/test_spec.py`、`M tests/test_validate.py`（测试收集数已从 141 → **143**）。因此本报告所有测试数字是**快照**，最终提交后请以 `scripts/check_all.py` 或 `pytest tests` 的实际输出为准。
- agent-library：`HEAD=b162d66`，工作树干净（仅有一个与本任务无关的历史 untracked `catalog/condopt-router/`）。
- 我没有修改任何被跟踪文件；本报告与 `runs/review_round4/` 为新增。

## 7. 没有验证的部分

1. **MP live 检索/fetch**：本机无 `MP_API_KEY`，按任务要求未伪造 key；只验证了无 key 失败路径 + mock 测试代码真实性，**没有真实 MP 网络响应验证**（key 缺失、401/403、rate limit、字段变更均未实测）。
2. **AFLOW 长时间稳定性/限制**：只跑 1 次 ZnO 检索 + 1 个 aurl 下载；未测大量条目、限流、特殊化学式、非 LIB1_WEB 数据集。
3. **COD 其他条目**：只测 id 7111973（与 Round 1 同一条），未测 COD 按名称检索/多命中排序。
4. **`fetch --json` 的 batch 语义**：只测了单条 id / 少量 hits；`--limit` 大时的 JSON 体积与 `--outdir` 组合未测。
5. **最终提交后状态**：评审结束时树仍在变动（143 collected），未对 `cifkit/spec.py`/`validate/checks.py` 的未提交改动做代码审查；最终 commit 后的 `check_all` 结果与文档测试数需复核。
6. **MP/AFLOW 的许可与数据条目质量**（结构是否 DFT 合理、是否有重复/错误条目）未做科学抽检——只验证了适配器行为与溯源字段。
7. CoRE/local 两个源本轮只读状态，未重跑完整检索/下载（前几轮已覆盖）。

## 8. 证据索引（`runs/review_round4/`）

| 文件/目录 | 内容 |
|---|---|
| `round4_checks.json`、`verify_round4.py/.log` | sources 清单/COD/AFLOW/MP/拓扑/pipeline/文档断言的完整结果 |
| `round4b_checks.json`、`verify_round4b.py/.log` | `fetch --json` 纯度、COD sha、aflow manifest、doc grep、CLI help |
| `cod/`、`cod2/` | COD live 下载（`raw.cif`、`source.json`）；cod2 为 `--json --outdir` 污染对照 |
| `aflow/`、`aflow_pipeline/`、`aflow_sod_pipeline/` | AFLOW 下载、正常 pipeline、请求 sod 拓扑的诚实失败 |
| `aflow_spec.json`、`aflow_sod_spec.json` | 两个 pipeline spec |
| `router_three.txt` | 三类 query 路由结果 |
| `eval_router.txt`、`ci.txt` | 79/79、负例 0/25、槽位 11/11、exit 0 |
| `pytest_summary.txt`、`pytest_collect.txt`、`pytest_collect2.txt` | 141 passed 64.60 s；收集 141 → 143（树变动） |
