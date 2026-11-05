# Round 5 收尾确认：Round-4 P1/P2 修复 + 最终回归

> 评审员：`reviewer-r1`｜日期：2026-11-05｜时间盒：10–15 分钟轻量确认（不重跑数据源全量审计）。
> 对象：`D:\Dev\Project5-skill-cif` **HEAD=`bd9451d`**、`D:\agent-library` **HEAD=`b0aee05`**；两仓工作树干净（agent-library 仅无关历史 untracked `catalog/condopt-router/`）。
> 方法：所有结论由评审员本机重跑；**未改代码/文档**（只写本文件与 `runs/review_round5/`）。

## 0. 结论

**PASS（可作为最终交付基线），但 P2-3 只修到 PARTIAL —— 1 处重复行仍在。**

- **P1-1 **FIXED**（`fetch --json --outdir` stdout 为纯 JSON，`wrote …` 在 stderr；sha 三处一致；新测试存在且通过）。
- **P2-1 **FIXED**（实测 **144 passed, 2 warnings in 66.38s**；collect 144；README/PIPELINE 写 144，无 139/143 残留）。
- **P2-2 **FIXED**（PIPELINE §8.2 无控制字符、无 TAB、无字面 `\:`，`aflow` 正常）。
- **P2-3 **PARTIAL**（"raw.cif 是重写文件"已删、"同名不同变体"已去重、验收证据第 2 条已改写且提到 `wrote` 走 stderr ✓；但 `rcsr.anu.edu.au` 那一条**仍重复出现两次**（L161 与 L170）——见 §3）。
- 本轮新增修复（NL 识别 GaN/`mp-149`/AFLOW aurl、无机 0-H 的 `repair_h` no-op 不误判、auto 选源）**全部抽查通过**。
- 回归：`pytest tests` 144 passed / exit 0；`check_all.py --fast` **6/6 groups PASS**（含 verify_demo 8/8、eval 79/79、负例 0/25、槽位 11/11、ci 绿）；两仓 `git status` 干净。

**P0/P1：无。** 建议：删掉 `catalog/cif-fetch/SKILL.md` L170 的重复行（或 L161），重新提交 agent-library 后即可作为最终基线。

---

## 1. P1-1：`fetch --json --outdir` stdout 纯度 — **FIXED**

复现（用 local 源避免网络；COD 在 Round 4 已验）：

```powershell
& $PY -m cifkit fetch --source local --id tests\data\zif8_cr_sod.cif --outdir runs\review_round5\cod_local --json
```

| 检查 | 期望 | 实测 |
|---|---|---|
| stdout 可解析 | 单个 JSON 数组 | **`json.loads(stdout)` 成功**，1 hit，record_id=`local:…zif8_cr_sod.cif` |
| "wrote …" 位置 | stderr | **仅在 stderr**（`wrote_in_stdout=false`, `wrote_in_stderr=true`） |
| sha 三方一致 | `raw.cif` == `source.json.raw_cif_sha256` == `provenance.sha256` | 三者均 `cbeebc95…191510`，**一致** |
| 落盘 note | 字节拷贝说明 | `"raw_cif 是源 CIF 的字节拷贝，sha256 应与 provenance.sha256 一致"` |
| 新测试 | `tests/test_cli.py::test_fetch_json_with_outdir_stdout_is_pure_json` 存在且过 | **exit 0，通过**（单测 1 个点） |

证据：`runs/review_round5/round5_checks.json` `p1_1_fetch_json_outdir`、`p1_1_test`；代码 diff 见 `bd9451d`（`cifkit/cli.py` 6 行）。

## 2. P2-1 / P2-2

### P2-1 测试数 — **FIXED**

- `pytest tests` → **`144 passed, 2 warnings in 66.38s`**，exit 0（`runs/review_round5/pytest_summary.txt`）。
- `pytest tests --collect-only -q` → **144**：cli **11** / export 20 / geom 34 / pipeline 3 / repair 12 / sources 17 / sources_mp_aflow **11** / spec **7** / topology 15 / validate **14**。
- 文档 grep：README L97 `# 144 passed`、L133 `测试总数 **144**`；PIPELINE L252 `全套 **144** 条`；**全项目与 catalog/cif-fetch SKILL 无 `139`/`143` 残留**。（SOURCES/SKILL 本身不含"测试总数"字段，无过期数字。）

### P2-2 PIPELINE §8.2 — **FIXED**

用 Python 读 `docs/PIPELINE.md` 的 §8.2 区域：

| 检查 | 结果 |
|---|---|
| 控制字符（`\x00-\x08`） | **无**（`control_chars=[]`，`has_x07=false`） |
| TAB | **无**（`tab_lines=[]`） |
| 字面 `\:` | **无**（`literal_backslash_colon_lines=[]`） |
| `aflow` 单词 | 正常存在；表头/正文为正常 UTF-8 中文与 Markdown |

证据：`round5_checks.json` `p2_2_pipeline_82`。

## 3. P2-3 cif-fetch SKILL — **PARTIAL（重复行残留 1 处）**

| 检查 | 结果 |
|---|---|
| 删除"（`fetch --outdir` 的 `raw.cif` 是重写文件，别拿它和 provenance 比…）" | **已删**（`has_rewrite_claim=false`） |
| "同名不同变体"重复 | **已去重**（全文件仅 L163 一次） |
| 验收证据第 2 条改写 | ✓ L175-176：`source.json` 含 `record`/`provenance`/`raw_cif_sha256`；`provenance.sha256 == provenance.cif_path` 实测 sha，且 `raw_cif_sha256 == raw.cif` |
| 与"wrote 走 stderr"一致 | ✓ 验收/实测记录行写明 "stdout 为纯 JSON（wrote 行走 stderr）" |
| **重复行** | **仍残留**：`- **\`rcsr.anu.edu.au\` 不可达、figshare API 403**：…` 在 **L161** 与 **L170** 完全重复（评审员逐行比对） |

影响：纯文档冗余，不影响行为；但技能正文是唯一真源，建议删掉其中一处后重提交。
证据：`round5_checks.json` `p2_3_skill`；`catalog/cif-fetch/SKILL.md:161,170`。

## 4. 本轮新增修复抽查 — 全部 PASS

| 检查 | 命令 | 实测 | 判定 |
|---|---|---|---|
| NL 识别化学式 | `route "帮我下载 GaN 的晶体结构，补氢后导出 VASP" --json` | exit 0；`structure_name=GaN`；`output_formats=["vasp"]` | PASS |
| auto 选源（化学式→aflow） | `fetch --name GaN --limit 1` | exit 0；**`source=aflow`**；`aflow:0caf3eb84ed158c0`，formula `Ga1N1`，evidence=unknown，H=0 | PASS |
| auto 选源（MOF 名→core-mof） | `fetch --name ZIF-8 --raw --limit 1` | exit 0；**`source=core-mof`**；`ja204757x_si_002`，Zn12C96N48，156 原子，evidence=verified | PASS |
| 无机 0-H 进管线不误判 | `pipeline "帮我下载 GaN 的晶体结构，补氢后导出 VASP" --outdir runs\review_round5\gan --json` | **exit 0，ok=true**；7 步全 ok；`repair.added_h=0`；**validate PASS**（9 个 checks，其中 `hydrogen`/`carbon_coordination` 均通过）；source=aflow、formula `Ga1N1`、`topology_evidence=unknown` | PASS |
| 不伪造拓扑 | `fetch --source aflow --topology sod --json` | exit 0，**0 hits** | PASS |

证据：`runs/review_round5/round5_checks.json` `nl_gan_route` / `auto_source_*` / `gan_pipeline` / `aflow_topology_sod`；`runs/review_round5/gan/`。

## 5. 回归 / 提交状态

| 检查 | 结果 |
|---|---|
| `pytest tests` | **144 passed, 2 warnings in 66.38s**，exit 0 |
| `pytest tests --collect-only -q` | 144（分布见 §2） |
| `scripts/check_all.py --fast` | **6/6 groups PASS，exit 0**（selftest 7/7；pytest fast；verify_demo 8/8 artifacts=12；router 第一候选 cif-workbench；eval 79/79、负例 0/25、槽位 11/11；ci 绿） |
| `verify_demo` | 8/8 PASS（`report=True steps=10 artifacts=12`） |
| 项目仓 | `HEAD=bd9451d`（含 `cifkit/cli.py`、`cifkit/spec.py`、`cifkit/validate/checks.py`、`README.md`、`docs/PIPELINE.md`、`tests/test_cli.py`、`tests/test_spec.py`、`tests/test_validate.py`）；**`git status --short` 空** |
| agent-library | `HEAD=b0aee05`（`catalog/cif-fetch/SKILL.md`，5+/4-）；工作树干净（仅无关历史 untracked `catalog/condopt-router/`） |
| 评审员改动 | 无被跟踪文件改动；只新增本报告 + `runs/review_round5/`（runs 被 gitignore） |

## 6. 没有验证的部分

1. **MP live**：本机仍无 `MP_API_KEY`（不伪造 key），MP 真实检索/fetch/401 路径未 live 验证（与 Round 4 相同；mock 测试与文档诚实性已在 Round 4 验证）。
2. **AFLOW/COD 规模与限流**：只跑 GaN（1 条）/ZIF-8（core-mof）/ZnO（Round 4）；未测多条目、限流、特殊化学式。
3. **NL 解析边界**：只抽查 GaN / `mp-149`（Round 4 报告）/ AFLOW aurl；未枚举 `cifkit/spec.py` 新增 `_FORMULA_*` 规则的全部误判/漏判边界（如 `CoRE MOF` 与 `Co-Re` 混淆、混合大小写化学式）。
4. **`validate` 对其它无机体系**（氧化物/氮化物/含 H 无机）只测了 GaN；`repair_h` no-op 的更广覆盖未验证。
5. **最终交付后状态**：本报告基于 `bd9451d`/`b0aee05`；若 Lead 为修 P2-3 再提交，建议只重跑 `check_all --fast`（~40 s）确认，不必重跑本报告全部项。

## 7. 证据索引（`runs/review_round5/`）

| 文件/目录 | 内容 |
|---|---|
| `round5_checks.json`、`verify_round5.py/.log` | P1-1 纯度/sha、P2-1/2/3 检查、NL/auto-source/GaN pipeline 的结构化结果 |
| `cod_local/` | local 源 `fetch --json --outdir` 落盘（raw.cif / source.json） |
| `gan/` | GaN pipeline 产物（manifest/report/raw.cif…） |
| `pytest_summary.txt`、`collect2.txt` | 144 passed / 66.38 s；collect 144 分布 |
| `check_all_fast.txt` | check_all --fast 6/6 原始输出 |
