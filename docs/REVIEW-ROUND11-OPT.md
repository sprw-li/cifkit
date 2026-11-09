# Round 11 独立评审：round 10 四项优化的对抗性复核

> **独立评审声明**：本报告由独立评审 agent 编写（不是实现者、也不是 Lead）。所有数字均由评审方在本机重跑得到，
> 不采信交付说明或前一份自评里的数字。任务给到的"预期值"只用于对表，逐项都做了自算。
> 本文件原有内容是 **Lead 的自评**（因早前派发的独立评审 agent 连续失败而临时替代），为避免丢失证据，
> **原文完整保留在文末「附录 A」**，并已标注为非独立评审。阅读结论请只依据正文。

- 被评审对象：项目仓 **`f5f36d5`（round 10）**；协作仓库 agent-library **`e29ab3b`**
- 复核时点：复核开始于工作区仍带 round-11 未提交改动、随后仓库前进到 `bbc5adf` → `c1f516a`。
  为保证不被在途改动污染，**所有 round-10 结论都在 `git archive f5f36d5` 解出的纯净副本上复算**
  （`runs/review_round11/baseline/`）；另对当前 HEAD 单独跑了回归。
- 证据目录：`runs/review_round11/`（命令输出、JSON/JUnit 报告、独立脚本）
- 约定：`$PY = .venv\Scripts\python.exe`，命令均从仓库根或下文标注的目录执行

## 结论

**PASS。** round 10 承诺的四项优化在 `f5f36d5` 上**全部可复现通过**：convert 批量（含 manifest）、
独立格式验证器（31/31 写出 + 25/25 第三方回读 + 12 bundle）、无金属环统计、`check_all` 第 7 组
`check_skill cif-*`。回归全绿（266 = 262 passed + 4 skipped；check_all 7/7；verify_demo 8/8；
usecases 22/22；eval_router 89/89、负例 0/25、槽位 11/11）。

但对抗测试发现 **2 个 P1**，其中 1 个属于 round 10 交付面、另 1 个是全仓结构性问题（干净 clone 即触发）：

1. **P1-a（round 10，已在后续提交修复）**：批量 `convert` 中不同目录的同名文件写进同一子目录，**静默覆盖**，
   而 manifest 仍报 `n_ok=2`、两条 `runs[].outdir` 相同。
2. **P1-b（全仓，尚未修复）**：仓库没有 `.gitattributes`，而 `core.autocrlf=true`（本机全局配置）。
   **一次全新 `git clone` 会让被 sha256 钉死的 CIF 变成 CRLF，导致
   `tests/test_topology_nets.py::test_reference_files_exist_and_are_consistent` 失败、
   `verify_demo` 第 1 项"来源追溯"失败（7/8），从而 `check_all` 也会失败。**
   本机现有工作区恰好是 LF，所以这条一直没被看见。

## 逐项 PASS/FAIL（数字为评审方自算）

### 1. `convert` 批量（`cifkit convert`）

| # | 检查 | 结果 | 我自算的数字 | 复现命令 / 证据 |
|---|---|---|---|---|
| 1.1 | 目录 `a.cif`+`b.CIF`+`c.cif`（Windows 大小写不敏感）→ 每个输入一个子目录 + `convert_manifest.json` | **PASS** | `exit=0`，`n_inputs=3 / n_ok=3 / n_failed=0`；产物 `out_multi/{a,b,c}/{a,b,c}.{vasp,extxyz}` + `convert_manifest.json` | `baseline_conv/multi.json`、`runs/review_round11/baseline_conv/out_multi/` |
| 1.2 | 混入坏 CIF：exit 1，但好文件仍转、manifest 记 error | **PASS** | `exit=1`，`n_inputs=2 / n_ok=1 / n_failed=1`；`out_mixed/good/good.vasp` 存在；坏条 `error="ValueError: 无法解析结构文件 …"` | `baseline_conv/mixed.json` |
| 1.3 | 单输入与旧行为一致：文件落在 `--outdir` 根目录（不进子目录） | **PASS** | `exit=0`，`out_single/zif8_cr_sod.vasp`（根目录，无子目录、无 manifest） | `baseline_conv/single.json` |
| 1.4 | 未知 `--bundle` → exit 2 + 可用列表 | **PASS** | `exit=2`，stderr 列出 12 个 bundle（abacus…vasp） | `baseline_conv/ub.err` |
| 1.5 | 未知 `--to` → exit 2 + 31 格式列表（附加） | **PASS** | `exit=2`，列出 31 个格式 | `uf.err`（主工作区） |
| 1.6 | 目录里没有 `*.cif` → 干净报错，不抛栈（附加） | **PASS** | `exit=1`，`error: ValueError: 目录里没有 .cif：…` | `nocif.err` |
| 1.7 | **不同目录同名文件不互相覆盖** | **FAIL（P1-a，仅 f5f36d5）** | `exit=0`，`n_ok=2`，两条 run 的 `outdir` 都是 `…\out_collide_base\same`；磁盘上**只有 1 个** `same/same.vasp`，且是第二个输入（750 原子 Zn 结构），第一个（138 原子 ZIF-8）被静默覆盖 | `baseline_adv/collide_base.json`、`runs/review_round11/baseline_adv/out_collide_base/` |
| 1.8 | 只有 1 个 `*.cif` 的目录（附加边界） | **P2-b** | 被当成"单输入"：写进 `--outdir` 根目录、**不写 `convert_manifest.json`**（与"每输入一个子目录 + manifest"的字面表述不符） | `baseline_adv/one.json`、`out_one/only.vasp` |
| 1.9 | 单输入 + `--stem X`（附加边界） | **P2-c** | 产物变成 `outdir/X/X.vasp`；round 9 是 `outdir/X.vasp`（`git show f5f36d5^:cifkit/cli.py`）。属未文档化的行为变更，且无测试覆盖 | `baseline_adv/stem_base.json`、`out_stem_base/renamed/renamed.vasp` |

第 1.7 条我在**当前 HEAD（`c1f516a`）复验已修复**：产物为 `same_001/same_001.vasp`、`same_002/same_002.vasp`，
manifest 两条 `outdir` 不同（修复提交 `bbc5adf`，含回归测试 `test_convert_batch_disambiguates_duplicate_stems`）。
因此 1.7 是 **round 10 基线的 P1、当前 HEAD 的 FIXED**。

### 2. 独立格式验证器 `scripts/verify_formats.py`

| # | 检查 | 结果 | 我自算的数字 | 复现命令 / 证据 |
|---|---|---|---|---|
| 2.1 | 全量：exit 0、31/31 写出、25/25 第三方回读一致、5 模板关键字、png 魔数、12 bundle 文件+README | **PASS** | `formats: 31/31 ok; third-party readback 25/25 ok`；`bundles: 12 written, all files+README: True`；`exit=0`；报告 `n_ok=31 n_third_party_ok=25 bundles_ok=true` | `$PY scripts\verify_formats.py` → `baseline_verify_formats.txt`、`baseline_vf.json`（在 `baseline/` 下运行） |
| 2.2 | 自查 4 格式（vasp/castep/extxyz/png）用 ASE/pymatgen 独立回读，核对原子数=138 与 vasp/cif 晶格 | **PASS** | 我自己写的脚本（不调用 `verify_formats.py`）：vasp→pymatgen 138；castep→ASE 138；extxyz→ASE 138 且 cell=14.6693³；png 魔数+PIL 解码 1200×900 RGBA；输入/`cif`/`vasp` 晶格 `abc=14.6693³, α=β=γ=109.471°` 全部一致 | `$PY runs\review_round11\indep_readback.py` → `indep_readback/report.json` |
| 2.3 | `--only` 子集只跑这些（且接受别名） | **PASS** | `--only vasp,castep` → `2/2 ok`（`--only poscar,ext_xyz` 也归一到 vasp/extxyz）；`--only cp2k` → 模板路径；子集模式不写 bundle（`0 written`） | `vf_only.txt`、`vf_only.json`、`vf_alias.json` |
| 2.4 | 未知格式 → exit 2 | **PASS** | `exit=2` + `unsupported export format 'zzz'` + 31 格式与 50 个别名 | `vf_bad.err` |
| 2.5 | 报告 note 是否诚实说明"回读一致 ≠ 目标软件接受" | **部分 PASS（P2-a）** | `f5f36d5` 的报告 note 只说"模板……未经真实软件运行"，**没有**"回读一致 ≠ 目标软件接受"这句；该句只出现在 `docs/LIMITATIONS.md` E2 与 `docs/EXPORT.md` §6。机器可消费的 JSON 报告本身弱于文档口径 | `baseline_vf.json` 的 `note` 字段 |

第 2.5 条在 `bbc5adf` 已修（note 改为明确的"**回读一致 ≠ 目标软件接受**"），HEAD 上复验通过。

### 3. 非金属环统计

| # | 检查 | 结果 | 我自算的数字 | 复现命令 / 证据 |
|---|---|---|---|---|
| 3.1 | `ring_statistics(diamond_8atom_cell)` | **PASS** | `n_nodes=8`、`n_bonds=16`、`rings_per_cell["6"]=16.0`、`rings_per_cell["8"]=24.0`、`truncated=False` | `$PY runs\review_round11\rings_check.py` → `rings_report.json`、`rings.txt` |
| 3.2 | 空结构不崩 | **PASS** | `ring_sizes=[]`, `n_nodes=0`, `n_bonds=0`, `warnings=["空结构"]`，无异常 | 同上 |
| 3.3 | **独立复算环数**（不借用 cifkit 的枚举/规范化） | **PASS** | 用 ASE `neighbor_list` 自建周期键图 + 自写 DFS：`n_bonds=16/胞`；6 元环 `12 个/原子 → 12×8/6=16.0/胞` 与 cifkit 一致；8 元环 `24 个周期简单环 → 24.0/胞` 与 cifkit 一致。（附带确认定义：cifkit 允许同一原子在**不同晶胞**再次出现，这是金刚石 8 元环的必要条件）另用两个教科书体系交叉验证：孤立环己烷 → 1 个六元环；六方石墨 → 2 个六元环/胞、`n_nodes=4`、`n_bonds=6`，全部正确 | `$PY runs\review_round11\diamond_indep.py`；`$PY runs\review_round11\rings_known.py` → `diamond_indep.txt`、`rings_known.txt` |
| 3.4 | `cifkit features --rings`：ZIF-8（含金属） | **PASS** | `ring_basis=metal-net`，`n_metal_nodes=6`，`ring_sizes=[4,5,6,7,8]` | `rings_check.py`（走真实 CLI） |
| 3.5 | `cifkit features --rings`：diamond（无金属） | **PASS** | `ring_basis=full-bond-graph`，`rings_per_cell={"6":16.0,"8":24.0,...}` | `rings_check.py` |
| 3.6 | >600 原子走 `truncated` 而不是硬算/卡死 | **PASS** | 1000 原子金刚石：`rings_per_cell={}`、`truncated=True`、`warnings=["原子数 1000 > 600，跳过环统计（过大）"]`；`features` 也如实给 `rings_truncated=True` | `rings_known`/评审脚本输出 |

附加 P2-d：**金属分支不暴露顶层截断标志**。2208 原子 ZIF-8 slab 走 `metal-net`，`rings_per_node["8"].truncated=true`，
但 features 行里 `rings_truncated=None`（非金属分支才写该字段）。文档 `FEATURES.md` 只描述非金属侧字段，
所以不算假话，但消费者容易漏掉"这一档环计数不完整"。

### 4. `check_all` 第 7 组

| # | 检查 | 结果 | 我自算的数字 | 复现命令 / 证据 |
|---|---|---|---|---|
| 4.1 | `check_all.py --fast` 7/7 且含 `check_skill cif-*` | **PASS** | 7 个组全 PASS；第 7 组 `check_skill cif-*`：**8 个技能，全部 `errors=0 warnings=0`**（cif-data/cif-export/cif-fetch/cif-geometry/cif-repair/cif-to-3dprint/cif-usecases/cif-workbench） | `$PY scripts\check_all.py --fast` → `check_all_fast.txt`（另 `baseline_check_all_fast.txt`） |
| 4.2 | `--skip-agentlib` 跳过该组 | **PASS** | `3/3 groups passed`（只剩 selftest / pytest-fast / verify_demo，第 4–7 组整体跳过） | `check_all_fast_skipagentlib.txt` |

注：在 `baseline/` 纯净副本里跑 `check_all --fast` 会因该副本缺 `_cache/`（gitignore，未被 `git archive` 带出）
使 `verify_demo` 组失败（6/7），这是**副本环境缺失**而非基线缺陷；第 7 组本身在该副本中仍 PASS。
主工作区（LF 行尾）跑同一命令为 7/7。

### 回归（自己数的数）

| 检查 | 我的结果 | 证据 |
|---|---|---|
| `pytest tests -q` @ `f5f36d5` | **266 collected = 262 passed + 4 skipped**，0 failed / 0 errors，155.9 s。4 条 skip 为 `test_mp_live`×2、`test_sources_qmof`×1、`test_usecase_cli::test_metals_zip_full`×1 | `junit.xml`、`pytest.txt` |
| `pytest tests -q` @ `c1f516a`（HEAD） | **267 collected = 263 passed + 4 skipped**，0 failed / 0 errors，166.0 s | `head_junit.xml`、`head_pytest.txt` |
| `scripts/check_all.py --fast` @ `c1f516a`（HEAD） | **7/7**，exit 0（第 7 组 8 技能 `errors=0`） | `head_check_all_fast.txt` |
| `scripts/check_all.py --fast` | **7/7**，exit 0 | `check_all_fast.txt` |
| `scripts/check_all.py --fast --skip-agentlib` | **3/3**，exit 0 | `check_all_fast_skipagentlib.txt` |
| `scripts/verify_demo.py runs/demo_sod_zif8` | **8/8**，exit 0（本机 LF 工作区） | `verify_demo.txt` |
| `usecases/verify_usecases.py` | **22/22**，`ISSUES: none`，exit 0 | `verify_usecases.txt` |
| agent-library `py -3 scripts/eval_router.py --all` | **89/89**（intent top1 也是 89/89）、负例 **0/25**、槽位 **11/11**，exit 0 | `eval_router.txt` |

## P0 / P1 / P2 清单

### P1-a：批量 convert 同名文件静默覆盖（round 10 基线；HEAD 已修）
- 级别：P1（数据丢失，且 manifest 谎报成功）
- 复现：
  ```powershell
  # 在 baseline/ (f5f36d5) 目录下
  $PY -m cifkit convert <d1>\same.cif <d2>\same.cif --to vasp --outdir <out> --json
  ```
- 期望：两个输入各自一个子目录、两份产物；实际：只有一个 `same/same.vasp`（后写入者胜），
  manifest `n_ok=2` 且两条 `runs[].outdir` 相同，`exit=0`。
- 自算证据：输入分别 138/750 原子；存活文件实测 750 原子（`ZnH60C52(NO2)4`）。
- 证据路径：`runs/review_round11/baseline_adv/collide_base.json`、`runs/review_round11/baseline_adv/out_collide_base/`
- 状态：`bbc5adf` 已修（`same_001/same_002` + 回归测试），我在 HEAD 复验通过。

### P1-b：缺 `.gitattributes` → 干净 clone 下 sha256 溯源与测试失败（全仓；尚未修）
- 级别：P1（干净 checkout / Linux CI 上验收套件直接红；"sha256 溯源"是交付卖点）
- 复现：
  ```powershell
  git clone --no-hardlinks <repo> runs\review_round11\clone_head
  cd runs\review_round11\clone_head
  $PY -m pytest tests/test_topology_nets.py::test_reference_files_exist_and_are_consistent -q   # FAIL
  $PY scripts\verify_demo.py runs\demo_sod_zif8                                                # 7/8（第 1 项来源追溯 FAIL）
  ```
- 期望：干净 clone 上测试全绿、demo 溯源 sha256 一致；实际：`bcu/dia/fcu/pcu/sod/tbo` 6 个
  bundle 参考 CIF 的 sha256 全部不匹配；`verify_demo` 第 1 项 `sha256 matches=False`（7/8，exit 1），
  因此 **clone 里 `check_all --fast` = 6/7，exit 1**（失败组就是 verify_demo）。
- 根因（已实证，不是推测）：仓库里被 sha256 钉住的是 **LF 字节**（`git cat-file -s f5f36d5:cifkit/data/nets/bcu-reference.cif` = 5308，
  与 JSON 里的哈希一致）；而全局 `core.autocrlf=true`（`file:C:/Users/Morrow/.gitconfig`）且**仓库无 `.gitattributes`**，
  所以 fresh clone 落成 CRLF（5404 字节）→ 哈希不匹配。演示数据同样：
  `runs/demo_sod_zif8/raw.cif` 在 clone 里 CRLF，其字节哈希不在 manifest 中，而**把 CRLF 归一成 LF 后哈希就在 manifest 中**。
  本机现有工作区是 LF（非 checkout 产生），所以一直没暴露。
- 证据路径：`runs/review_round11/clone_head/`（clone 实测本身）、`runs/review_round11/P1b_eol_evidence.md`（原始数字）、
  `runs/review_round11/baseline_pytest2.txt`、`runs/review_round11/baseline/`（`git archive` 同为 CRLF，复现同一失败）
- 建议修法：加 `.gitattributes`，例如 `* text=auto eol=lf` 或对哈希敏感文件显式 `-text`
  （`cifkit/data/nets/*.cif -text`、`runs/** -text`），并让 sha256 与文件字节策略一致。

### P2-a：`verify_formats` 报告 note 弱于文档口径（基线；HEAD 已修）
- 复现：`$PY scripts\verify_formats.py --json runs\review_round11\baseline_vf.json`（在 `baseline/` 下）
- 期望：报告 note 明说"回读一致 ≠ 目标软件接受"；实际（`f5f36d5`）：只说了模板"未经真实软件运行"。
- 证据：`runs/review_round11/baseline_vf.json` → `note`
- 状态：`bbc5adf` 已修。

### P2-b：`--stem` + 单输入行为变更（未文档化）
- 复现：`$PY -m cifkit convert FILE --to vasp --stem renamed --outdir OUT`
- 期望（round 9 行为）：`OUT/renamed.vasp`；实际（round 10）：`OUT/renamed/renamed.vasp`。
- 证据：`runs/review_round11/baseline_adv/out_stem_base/renamed/renamed.vasp`；对比 `git show f5f36d5^:cifkit/cli.py`

### P2-c：单文件目录 = "单输入"（无子目录、无 manifest）
- 复现：目录里只放一个 `only.cif` → `convert <dir> --to vasp --outdir OUT --json`
- 实际：`OUT/only.vasp`，`n_inputs=1`，**没有** `convert_manifest.json`。文档写的是"多输入时每输入一个子目录"，
  严格说没撒谎，但"目录批量"的语义在 1 个文件时退化，建议文档点明或对目录输入恒写 manifest。
- 证据：`runs/review_round11/baseline_adv/one.json`

### P2-d：`features` 金属分支不暴露顶层 `rings_truncated`
- 复现：`$PY -m cifkit features runs\demo_sod_zif8\final.cif --rings --no-rdf --json`
- 实际：`ring_basis=metal-net`，`rings_per_node["8"].truncated=true`，但行里 `rings_truncated` 缺失（None）。
- 证据：`runs/review_round11/big_metal_features.json`

### P2-e：`_expand_structure_inputs` 的去重理由不成立（无害）
- `*.cif` 与 `*.cif.gz` 两个 pattern 互斥，且大小写不敏感文件系统上 `x.cif`/`x.CIF` 不可能并存为两个文件，
  所以按 `resolve().lower()` 去重实际是死代码。结果正确，但注释声称的作用不真实。

### P2-f：文档口径残留（`c1f516a` 仍存在）
- `docs/EXPORT.md:126` 表头写 **"格式（30）"**；`docs/EXPORT.md:132` 把 `png` 列进"（未实现）…**不在当前 30 种内**"，
  而同文件 `:129` 又把 `png` 当作已实现的可视化格式，`:158/:171` 写 31 格式 / 31-31。自相矛盾且数字过期。
- `docs/LIMITATIONS.md` 有两行重复的 `> 已支持 cifkit convert …` 引用块（round 11 只更新了其中一行）。
- 历史：`f5f36d5` 的 `LIMITATIONS.md` H3 写"**252 条测试**"，与实测 266 不符（`c1f516a` 已改为不带数字的表述）。

### 文档 / 诚实性核对（30 秒版）
- `LIMITATIONS.md` **E2 仍是 🟡 且诚实**：明说"模板未在真实软件中执行；回读一致 ≠ 软件接受"。
- **F4 ✅ 成立**：无金属框架走完整键图（`full-bond-graph`），diamond 6 元环 16/胞由我独立复算一致，>600 标 `truncated`。
- **H5 ✅ 成立**：`check_all` 第 7 组实调 `check_skill.py`，8 个 `cif-*` 技能 `errors=0`，`--skip-agentlib` 可跳过。
- **31 格式 / 25 第三方回读 / 12 bundle**：与实测一致（README 104、EXPORT 158/171、SKILLS 16、PIPELINE 307）。
- **266 测试**：`f5f36d5` 实测 266 = 262 + 4，与 README/PIPELINE 一致。
- **convert 批量**：README 105 / LIMITATIONS 49,51 的"每输入一个子目录 + `convert_manifest.json`、坏输入不中断"与实测一致
  （1 个输入/1 个文件目录的退化情况见 P2-c）。
- 未发现任何"把模板说成可直接运行"或"把回读一致说成软件接受"的表述；E1/E3/I1 的限制都写明了。

## 我实际跑了什么

- `git archive f5f36d5` → `runs/review_round11/baseline/`（纯净基线副本，所有 round-10 复算都在此目录下执行）
- convert：目录批量 / 坏输入批量 / 单文件 / 单文件+`--stem` / 单文件目录 / 同名冲突 / 重复输入 / 未知 `--to`、`--bundle` / 空目录
- `scripts/verify_formats.py`：全量（31 格式 + 12 bundle）、`--only vasp,castep`、`--only poscar,ext_xyz`、`--only cp2k`、`--only zzz`
- 自写独立回读：`runs\review_round11\indep_readback.py`（vasp→pymatgen、castep/extxyz→ASE、png→魔数+PIL，晶格比对）
- 自写独立环复算：`runs\review_round11\diamond_indep.py`（ASE 建图 + 自写 DFS，6/8 元环 /胞）
  与 `runs\review_round11\rings_known.py`（环己烷=1、石墨=2 六元环/胞）
- `rings_check.py`：diamond / 空结构 / `features --rings`（ZIF-8 与 diamond，走真实 CLI）
- `scripts/check_all.py --fast`、`--fast --skip-agentlib`；`scripts/verify_demo.py`；`usecases/verify_usecases.py`
- `pytest tests -q --junitxml`（基线副本与当前 HEAD 各一次）；`git clone` 到 `runs/review_round11/clone_head/` 复现 P1-b
- agent-library（`e29ab3b`）：`py -3 scripts/eval_router.py --all`；另经 `check_all` 跑了 router/eval/ci/check_skill
- 文档数字 grep：README / PIPELINE / SKILLS / EXPORT / FEATURES / LIMITATIONS（分别在 `f5f36d5` 与 `c1f516a` 上）

## 没验证的部分

- **任何格式都没有在真实计算软件里运行**（VASP/QE/CP2K/LAMMPS/Gaussian/ORCA/ABACUS/DFTB/SIESTA/NWChem/AIMS/CASTEP/…）。
  "第三方回读一致"只证明另一个库能解析出同样多的原子，不等于目标软件接受该输入。本环境无这些软件与 license 文件。
- 只做了 4 个格式（vasp/castep/extxyz/png）的第三方回读抽检；其余 21 个第三方回读结果采信验证器报告，未逐一复算。
- 未验证 bundle 的物理/化学正确性（力场、赝势、基组、k 点收敛等），只核了"文件 + README 齐全"。
- 未做 1000+ 文件批量、并发写盘、磁盘写满、SIGKILL 中断等压力/故障注入。
- 未验证非 Windows 行尾/文件系统行为（除 P1-b 用 clone 模拟 CRLF 外）。
- agent-library 的 `catalog/bohrium-*` 与 `catalog/intents.json` 属他人未提交改动，未触碰、未评审。
- 未修改任何代码/测试/其它文档；未 `git commit`。

## 复核期间仓库前进的事实（影响阅读方式）

复核开始时工作区仍有 round-11 未提交改动（`cifkit/cli.py`、`scripts/verify_formats.py`、`scripts/check_all.py`、
`tests/test_cli_convert.py`、`docs/PIPELINE.md`、新增 `scripts/adversarial_check.py`、`docs/REVIEW-ROUND11-OPT.md`）。
为避免"跑着跑着代码变了"，我把全部 round-10 结论钉在 `git archive f5f36d5` 的副本上。
期间仓库提交为 `bbc5adf`（round 11 修复）与 `c1f516a`（改 LIMITATIONS H3），HEAD 现状：

- `bbc5adf` 正是把 P1-a（同名覆盖）、P2-a（报告 note）修掉，并补了 `--adversarial` 自检；我在 HEAD 复验这两项通过。
- `c1f516a` 清掉了 H3 的过期测试数。
- 仍未修：**P1-b（`.gitattributes`/行尾）**、P2-f（EXPORT 的 30/png 矛盾）、LIMITATIONS 重复引用块。
- 我复验 `c1f516a`（HEAD）的测试总数为 **267 = 263 passed + 4 skipped**（较 `f5f36d5` 的 266 多 1 条同名回归测试），
  `check_all --fast` 7/7。

---

# 附录 A：Lead 自评原文（**非独立评审**，保留以防信息丢失）

> 以下内容为仓库原有文件内容，非本评审所写。其"结论 PASS"只代表实现方自检，独立性弱于本报告正文；
> 其中"note 已明确写回读 ≠ 软件接受"一条对应的是**本轮修复后**的状态，并非 `f5f36d5` 基线。

# Round 11 评审：round 10 四项优化的验证结果

> **重要说明（诚实标注）**：本轮原计划由独立评审 agent（`reviewer-r1`）执行，但该 agent 连续两次在
> 执行中失败（无任何产出），随后的两个 `subagent` 也都在启动后立即失败。因此本报告是
> **Lead 自己写的对抗性验证**，不是独立评审。方法上尽量替代独立性：
> 用与实现**不同的代码路径**验证（第三方库回读、独立公式核对环数、故意破坏输入），
> 并把检查固化成可复跑脚本 `scripts/adversarial_check.py`（18 项），而不是只复述实现。
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

---

## Lead 后续处理（round 12，2026-11-09）

本节由 Lead 添加，记录对上面评审结论的处置；**评审正文与附录 A 保持原样，未改动**。

| 评审发现 | 处置 | 验证 |
|---|---|---|
| **P1-b**（无 `.gitattributes`，`core.autocrlf=true` 下干净 clone 全红） | 新增 `.gitattributes`：`* text=auto eol=lf`、`cifkit/data/nets/*` + `tests/data/*.cif` 显式 `eol=lf`、`runs/** -text`、二进制 `binary`；并用 `git add --renormalize` 把 12 个 CRLF 存储的 run 产物改成 LF | **实测干净 clone**（`git clone` 到 `D:\Dev\_clone_check`）：nets 参考 CIF `sha256=cbeebc95…`（LF）、demo `raw.cif` `sha256=c6939cf7…`（LF）与 manifest 一致；`pytest tests/test_topology_nets.py` 35 passed；`verify_demo` **8/8**；`check_all --fast` **7/7** |
| **P1-a**（批量 convert 同名覆盖，仅 f5f36d5） | 已在 `bbc5adf` 修（`same_001`/`same_002` + 回归测试） | 评审已在 HEAD 复验通过；`scripts/adversarial_check.py` 常驻该检查 |
| P2：`docs/EXPORT.md` 30/31 自相矛盾 | 表头改 **31**；png 从"未实现"行拆出为"视觉预览"行，`cube` 单独标未实现 | `Select-String` 复核无 30 残留 |
| P2：单输入 + `--stem` 行为变化且无测试 | 恢复 round-9 语义（`outdir/X.vasp`，扁平）；新增 `_convert_one(..., in_subdir=)` 区分"输出名"与"是否进子目录" | `test_convert_single_with_stem_stays_flat`；adversarial 检查 |
| P2：只有 1 个 CIF 的目录被当单输入、不写 manifest | **给目录就一定走批量**（`batch_mode = len(inputs) > 1 or any(Path(i).is_dir())`） | `test_convert_single_cif_directory_is_batch`；adversarial 检查 |
| P2：`features` 金属分支不暴露 `rings_truncated` | 金属分支也写 `rings_truncated`（由 per-node 的 truncated 汇总） | `test_features_rings_reports_truncation` |
| P2：LIMITATIONS 有重复的 convert 引用块 | 去重；并把 convert 语义（目录=批量、单文件扁平、不递归）写进 E 组开头 | 文档复核 |

round 12 复跑（Lead）：`pytest` **270 条 = 266 passed + 4 skipped**（0 fail）；`check_all --adversarial` **8/8**（含 adversarial 18/18）；干净 clone `check_all --fast` **7/7**。提交 `6bd641d` + 本次文档提交。

**仍未处理**：本轮只修了评审列出的问题，没有改变"模板未在真实计算软件运行"（H3）与"无 Linux/macOS CI"（H4）这两个 🔴 项。
