# Round 11 评审：round 10 四项优化的验证结果

> **重要说明（诚实标注）**：本轮原计划由独立评审 agent（`reviewer-r1`）执行，但该 agent 连续两次在
> 执行中失败（无任何产出），随后的两个 `subagent` 也都在启动后立即失败。因此本报告是
> **Lead 自己写的对抗性验证**，不是独立评审。方法上尽量替代独立性：
> 用与实现**不同的代码路径**验证（第三方库回读、独立公式核对环数、故意破坏输入），
> 并把检查固化成可复跑脚本 `scripts/adversarial_check.py`（16 项），而不是只复述实现。
> **独立性弱于前几轮**，用户若要严格独立的结论，需要换一个可用的评审 agent 重跑本清单。

- 基线：项目仓 `f5f36d5` + 本轮修复（见下）；agent-library `e29ab3b`
- 证据：`runs/lead_verify_r11/adversarial_check.json`、`runs/verify_formats/verify_formats.json`
- 复跑：`python scripts/adversarial_check.py`（本机 16/16 PASS，exit 0）

## 结论：PASS（含 1 个自查发现的 P1，已修）

## 逐项验证

| # | 检查 | 结果 | 证据（Lead 自算） |
|---|---|---|---|
| 1 | `convert` 单输入仍在 `--outdir` 根目录（不与旧行为冲突） | PASS | `exit=0`，`single/zif8_cr_sod.vasp`、`.xyz` |
| 2 | `convert` 目录批量：`.cif` 与 `.CIF` 去重（3 文件 → n_inputs=3） | PASS | `n_inputs=3 n_ok=3` |
| 3 | 批量为每个输入写 `outdir` + `convert_manifest.json` | PASS | manifest 的 `runs[].outdir` 都实际存在 |
| 4 | **同名不同目录不再互相覆盖** | **P1 → 已修** | 修复前只产出 1 个 `same.vasp`（manifest 却报 n_ok=2）；修复后 `same_001.vasp` + `same_002.vasp` |
| 5 | 目录里没有顶层 `*.cif`（只有子目录）→ 明确报错 | PASS | `exit=1`，stderr "目录里没有 .cif" |
| 6 | 坏输入不中断批量 | PASS | `exit=1`，`n_ok=1 n_failed=1`，好文件仍产出 |
| 7 | 未知 `--bundle` → exit 2 + 可用列表 | PASS | `exit=2`，stderr 列出 12 个 bundle |
| 8 | `verify_formats.py` 全量：31/31 写出 + 25/25 第三方回读 + 12 bundle | PASS | 报告 `n_ok=31 n_third_party_ok=25 bundles_ok=true` |
| 9 | 模板格式被标注而不是冒充"回读通过" | PASS | templates = {cp2k,siesta,abacus,orca,dftb}；note 明确"回读一致 ≠ 目标软件接受" |
| 10 | 验证前提成立（损坏的 CIF 确实会被读取库拒绝） | PASS | 截断 CIF → pymatgen 抛错 |
| 11 | `ring_statistics(diamond)` 与独立公式一致（8×12/6 = 16 个六元环/胞） | PASS | `6-rings=16.0`，`n_bonds=16`，`truncated=false` |
| 12 | 环数语义自洽（canonical 化后 `size × per_cell` 为整数） | PASS | `{6:96, 8:192}` 全为整数 |
| 13 | 孤立原子：零环、不崩 | PASS | 全部 `0.0` |
| 14 | 超大结构（700 原子）走 `truncated` 而不是卡死 | PASS | `truncated=true`，警告"原子数 700 > 600" |
| 15 | `features --rings` 金属/非金属分支正确 | PASS | ZIF-8 `metal-net`；diamond `full-bond-graph`（6 元环 16/胞） |
| 16 | `check_all` 的 `check_skill` 组真的调用外部脚本 | PASS | 代码里 `check_skill.py` + `check_skills()` + `"check_skill cif-*"` + `--skip-agentlib`；实跑 8 技能 errors=0 |

## 发现与修复

| 级别 | 问题 | 根因 | 修复 | 状态 |
|---|---|---|---|---|
| **P1** | 批量 `convert` 中同名文件（`d1/same.cif`、`d2/same.cif`）写进同一子目录，**静默覆盖**，manifest 仍报 `n_ok=2` | 批量子目录直接用 `src.stem`，未检测重名 | 检测重名后加序号后缀（`same_001`、`same_002`）；`entry["outdir"]` 写入 manifest | ✅ 已修 + 回归测试 `test_convert_batch_disambiguates_duplicate_stems` |
| P2 | `verify_formats` 报告 note 只说"未经真实软件运行"，没说清"回读 ≠ 软件接受" | 措辞不够强 | note 改为明确的 **"回读一致 ≠ 目标软件接受"** | ✅ 已修 |
| P2 | 派发的独立评审 agent/subagent 全部失败，导致本轮缺少严格独立评审 | 环境 agent 故障 | 用 Lead 对抗性自检替代，并在本报告顶部**明确标注独立性不足** | ⚠️ 遗留（需可用评审 agent 重跑） |

## 回归（Lead 自跑）

| 检查 | 结果 |
|---|---|
| `pytest tests -q`（`--junitxml` 计数） | **267 条 = 263 passed + 4 skipped**，exit 0（含新增的同名回归测试） |
| `scripts/check_all.py --fast` | **7/7**（新增 `check_skill cif-*` 组） |
| `scripts/verify_demo.py runs/demo_sod_zif8` | 8/8 |
| `usecases/verify_usecases.py` | 22/22 |
| `scripts/adversarial_check.py` | 16/16，exit 0 |
| agent-library `eval_router --all` | 89/89，负例 0/25，槽位 11/11 |
| agent-library `ci.py --fast` | 绿 |

## 没验证的部分

- **模板类格式（cp2k/siesta/abacus/orca/dftb）与其它 25 种格式都未在真实计算软件中运行**；
  "回读一致"只证明第三方库能解析出同样原子数，不证明软件接受（`docs/LIMITATIONS.md` E1/E3/H3 仍是 🟡/🔴）。
- 批量 `convert` 只在 3–4 个输入、单机 Windows 上测过；未测 1000+ 文件、未测并发/磁盘写满。
- `ring_statistics` 的节点上限（600）是保守估计，未在 500–600 区间做性能曲线；大体系只验证了"会 truncated"。
- `check_all --adversarial` 新增开关只在本机跑通，未在 CI 中启用。
- 未做 `SIGKILL` 中断批量转换的恢复测试（只覆盖输入错误路径）。
