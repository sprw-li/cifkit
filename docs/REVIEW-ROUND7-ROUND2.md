# Round 7 独立评审：初始 goal round 2（CLI / 羧酸根补氢 / 拓扑库 / QMOF / 鲁棒性 / 性能）

> 评审员：`reviewer-r1`｜日期：2026-11-05｜时间盒 40–60 min。
> 基线：项目仓启动时 `3b42c9e`（评审期间前进到 **`d8106bb`**：仅 `README.md`+`docs/SOURCES.md` 两行文档同步，无代码/测试变化）；agent-library `ba469cf`。两仓 `git status` 干净（agent-library 仅无关历史 untracked `catalog/condopt-router/`）。
> 方法：**全部自写脚本独立复算**，未依赖 Lead 的测试数字；未改任何代码/文档。

## 0. 结论

**PASS（6 个 WP 全部通过；仅 1 个 P2 文档计数口径 + 1 个观察项）。** 关键数字（补氢数、MOF-5 来源、拓扑离线识别、QMOF 非 live、并发安全、batch 加速、slab 缓存副本语义）均由评审员独立复算/实测，未发现虚假声明。

| WP | 判定 | 我的独立复算/实测 |
|---|---|---|
| WP1 CLI 子命令 | **PASS** | 4 个 `--help` exit 0；`teach --offline` / `bravais --bain-range 0.9:1.7:0.05` / `metals --elements Fe,Cu,Mg --no-zip` / `fec --no-zip` 全部 exit 0 且 **`--json` 纯 JSON**；非法 flag/值 exit 2 |
| WP2 羧酸根 MOF 补氢 | **PASS** | 10 个 fixture 的 `added_h` 全中（24/96/28/24/2/0/0/0/0/120）；MOF-5 的 μ4-O（2 个）与羧酸根 O（24 个）**H=0**；UiO-66 有 4 个 μ3-OH（O–H=4）、4 个 oxo；HKUST-1 无 O–H；MOF-5 来源独立核实（见 §2） |
| WP3 拓扑参考离线库 | **PASS** | `CIFKIT_CACHE` 空目录（无 CoRE zip）下 identify **6/6** 正确（bcu/dia/fcu/pcu/sod/tbo）+ ZIF-8→sod；交叉 mismatch 3/3；参考 JSON `cif_sha256` 与 -reference.cif 实测 **6/6 一致** |
| WP4 QMOF 本地镜像 | **PASS** | `sources --json` = **6 源**（含 qmof，status "local mirror missing"）；缺镜像 exit 1 报错含 `CIFKIT_QMOF_DIR`+可操作提示；自建临时镜像 search/fetch 成功、evidence=unknown；**文档明确"未 live 下载"**；MP 无 key 行为不变 |
| WP5 鲁棒性 | **PASS** | 3 进程并发冷建索引全部 exit 0、`index.json` 解析 **8300** 条、无 `*.lock`/`*.tmp*` 残留；`bootstrap_data.py --check` 空缓存 exit 1/MISSING、真实缓存 exit 0/cache OK；batch 一条失败 exit 1 但另一条 success 且都进 manifest |
| WP6 性能 | **PASS** | `batch --jobs 1` **16.98 s** vs `--jobs 3` **8.87 s**（3 条本地 spec，**1.91×**；manifest 含 concurrency/seconds/returncodes）；`make_slab` 同参 miss **1.757 s** → hit **0.0052 s / 0.0077 s**，`info['cache']=hit`，**返回副本**（改第一个不影响第二个） |
| 回归 | **PASS（1 处计数口径）** | `pytest tests`：**225 passed + 1 skipped**（opt-in，见 P2-1）/ 180.3 s / exit 0；collect **226**；`check_all --fast` **6/6**；`verify_demo` 8/8；`verify_usecases` 22/22；eval **84/84**、负例 0/25、槽位 11/11；ci 绿 |

**P0/P1：无。**

---

## 1. WP2 补氢细节（独立键分析，不用 RepairReport）

| fixture | 期望 added_h | 实测 added_h | 最终原子/公式 | 独立 O 分类 |
|---|---|---|---|---|
| mof5_hfree | 24 | **24** | 106 / Zn8 H24 C48 O26 | oxo(≥3 Zn)=2、羧酸根=24、**O–H=0** |
| mof5_cod_hfree | 96 | **96** | 424 / Zn32 H96 C192 O104 | oxo=8、羧酸根=96、**O–H=0** |
| uio66_hfree | 28 | **28** | 114 / Zr6 H28 C48 O32 | oxo=4、羧酸根=24、**O–H=4（μ3-OH 合理）** |
| hkust1_hfree | 24 | **24** | 156 / Cu12 H24 C72 O48 | 羧酸根=48、**O–H=0** |
| terephthalic_acid_hfree | 2 | **2** | 18 / H6 C8 O4 | 自由羧酸 **O–H=2**（正确） |
| mof5_h / mof5_cod_h / uio66_h / hkust1_h | 0 | **0/0/0/0** | 106/424/114/156 | no-op 正确 |
| zif8_raw_hfree | 120 | **120** | 276 / Zn12 H120 C96 N48 | 不回归 |

- fixture 文件 sha256 与 `REPAIR_FIXTURES.md` 记录的 **9/9 全部一致**；synthetic fixture 均在文档/注释中明确标注。
- `mof5_hfree` 我也从 CoRE zip 直接取 `SI/CR/ASR/2007[Zn][pcu]3[ASR]3.cif` 解析：**106 原子、Zn8 H24 C48 O26**、sha256 `f32e6e75…`（与 fixture 文档一致），CSV 行：`topology(AllNodes)=pcu`、DOI **10.1021/ja074366o** ✓。
- **MOF-5 来源更正独立验证**：`2015[Zn][pcu]3[ASR]2.cif` 实际为 **50 原子、Zn4 H8 C24 O14**，CSV `topology(AllNodes)=scn`、DOI `10.1039/C5TA04552E` —— 确实**不是 MOF-5**（也非 pcu-AllNodes）；`2011[Zn][pcu]3[ASR]8` 为 106 原子 MOF-5 记录。文档/`REPAIR_FIXTURES.md` 的更正与数据库事实一致，没有把 2015 记录讲成 MOF-5。

## 2. WP3 离线拓扑库细节

- `available_reference_nets()`（`CIFKIT_CACHE` 指向空目录）→ `["bcu","dia","fcu","pcu","sod","tbo"]`。
- 每个 `*-reference.cif` 自算 `identify()` → **6/6 `ok=true, evidence=verified`**，net 名与文件名一致（含参考记录 coreid/DOI 写入 detail）；`zif8_raw_hfree` → **sod**。
- 交叉 mismatch：`pcu` vs 期望 sod → mismatch；`sod` vs pcu → mismatch；`dia` vs fcu → mismatch（3/3）。
- 6 个 JSON 的 `cif_sha256` 与对应 `-reference.cif` 实测 sha256 **6/6 一致**（如 sod `cbeebc95…`、pcu `f32e6e75…`、fcu `9414a51f…`）。
- 文档检查：README/SOURCES/REPAIR/REPAIR_FIXTURES 均**没有**把 `2015[Zn][pcu]3[ASR]2` 说成 MOF-5（且明确写"不是/未采用"）。

## 3. WP4 QMOF 诚实性 / WP1 CLI / WP5–6 摘要

- **QMOF**：README L83、SOURCES §7e、PIPELINE、ROBUSTNESS 均写"本地镜像、figshare/GitHub 不可达、**未 live 下载/未 live 实测**"；`sources --json` 的 qmof `auth_hint` 也写"本环境网络不可达，未实测在线下载"，`status="local mirror missing (…)"`。缺镜像报错含目录与设置方法。自建 `CIFKIT_QMOF_DIR`（2 个 CIF + 最小 csv）后 `fetch --source qmof --json` 命中 `qmof:mof5`、evidence=unknown；`source.json` note 明确"读取本地镜像；不是在线下载"，且 raw.cif 为 CifWriter 重写（note 说明 sha 可能与 provenance 不同）——**没有伪造 live**。
- **CLI**：4 命令 `--json` 纯可解析；`teach --bogus-flag` 与 `metals --elements ""` 均 exit 2。批次 `batch` 用独立子进程、manifest 记录每 run `returncode/seconds/stderr_tail`。
- **鲁棒性**：3 进程冷建（临时缓存含 zip+csv）→ 全部打印 8300、`index.json` 8300 条可解析、锁/tmp 无残留；`bootstrap --check` 空 exit 1（MISSING 清单）/真实 exit 0（cache OK）；batch 一条不存在路径 → exit 1，两个 outdir 均生成、manifest `ok`=1、returncodes=[1,0]。
- **性能**：见 §0 WP6；slab 缓存 copy 语义用"改第一个返回结构再加一次调用"验证第二个/第三次坐标不变 ✓。

## 4. 问题清单

### P0/P1：无。

### P2-1：测试计数口径 —— 文档写"226 passed"，实测 **225 passed + 1 skipped**（collect 226）

- 文档：`README.md:140` `# 226 passed`、`README.md:176`/`docs/PIPELINE.md` `测试总数 226`。
- 实测：`pytest tests` → **`225 passed, 1 skipped, 2 warnings in 180.30s`**，exit 0；`--collect-only` = **226**（batch 3/cli 11/export 20/geom 34/pipeline 3/repair 12/repair-carboxylate 17/robustness 6/slab-cache 4/sources 17/sources-mp-aflow 12/sources-qmof 4/spec 7/topology 15/topology-nets 34/usecase-cli 13/validate 14 = 226）。
- 跳过的是 `tests/test_usecase_cli.py::test_metals_zip_full`（`@pytest.mark.skipif(not FULL, reason="opt-in full-ish run via CIFKIT_USECASE_FULL=1")`），属**设计内的 opt-in**，不是失败。
- 建议：文档写"226 条（225 默认通过 + 1 条 opt-in 需 `CIFKIT_USECASE_FULL=1`）"，或在 check_all 里设该环境变量后记录 226。

### P2-2（观察，非缺陷）：batch 加速倍数与文档不同但方向一致

- doc/PERFORMANCE 用 3 条完整 demo（各 13–14 s）：41.0 s → 14.8 s（2.8×）；我用 3 条轻量本地 spec（各 4–6 s）：16.98 s → 8.87 s（1.91×），单 run 仍有 5–7 s 固定启动开销，符合预期。manifest 结构、`--jobs` 语义均正常；不是回归。

## 5. 我实际跑过什么（命令/脚本摘要）

1. `pytest tests`（225 passed+1 skip/180 s）、`--collect-only`（226）、`check_all --fast`（6/6）、`verify_demo`（8/8）、`usecases/verify_usecases.py`（22/22）、`eval_router --all`（84/84、负例 0/25、槽位 11/11）、`ci --fast`（绿）。
2. `runs/review_round7/verify_wp1234.py`：10 个 repair fixture 的 CLI 补氢 + 自写键分析（O 分类/μ4-O/羧酸根 O/μ3-OH）；CoRE zip 内 2007/2015 记录 + CSV 行核对；离线（空 `CIFKIT_CACHE`）identify 6 参考 + zif8 + 3 交叉 mismatch + JSON sha；sources 6 源、QMOF 缺镜像/临时镜像/MP 无 key；4 个 CLI 子命令 + 错误参数。
3. `runs/review_round7/verify_wp56.py`：batch jobs=1/3 计时与 manifest；make_slab miss/hit + 副本语义；3 进程并发冷建索引；bootstrap `--check` 空/真实；batch 部分失败。
4. `git log/status` 两仓（`3b42c9e`→`d8106bb` 两行文档同步；工作树干净）。

## 6. 没有验证的部分

1. **真实数据库新下载**：本轮补氢/拓扑/QMOF 都基于已缓存 CIF 或本地临时镜像；未重新从 CoRE/COD/AFLOW 拉数据（与 Round 1–4 的 live 验证不重复）。QMOF 官方 figshare/GitHub 本环境不可达，**未 live**（文档已如实标注）。
2. **并发极限**：只测 3 进程并发冷建（与文档一致），未测 8/16 进程或 SIGKILL 中途杀进程的锁恢复（文档也列为未验证）。
3. **batch 的完整 demo 级 41 s→14.8 s 数字**：用轻量 spec 复测加速（1.91×），未重复 Lead 的 3×完整 demo 计时；数值随机器/负载变化。
4. **补氢化学的 DFT 级正确性**：只验证价态/键长/键拓扑与预期组成（与 Round 1 方法一致）；未做量子化学验证（文档本身不声称）。
5. **MIL-101 / μ3-O-OH / 多齿配体**：文档写为限制/未验证；我未提供新 fixture 复核（CoRE 无干净条目、COD 条目超大，与文档一致）。
6. **10 个 fixture 之外的羧酸根 MOF**：未验证（如 MOF-177、MIL-53 等）。

## 7. 证据索引（`runs/review_round7/`）

| 文件/目录 | 内容 |
|---|---|
| `verify_wp1234.py`、`wp1234_checks.json`、`wp1234.log` | WP2 补氢/MOF-5 来源、WP3 离线拓扑、WP4 QMOF、WP1 CLI 全部结果 |
| `verify_wp56.py`、`wp56_checks.json`、`wp56.log` | WP5 并发/bootstrap/batch 隔离、WP6 batch 计时 + slab 缓存 |
| `wp2/` | 10 个 fixture 的 repaired 输出 |
| `empty_cache/`、`conc_cache/` | WP3 空缓存（离线验证）、WP5 3 进程并发冷建 |
| `qmof_mirror/`、`qmof_fetch/` | QMOF 本地临时镜像与 fetch 产物（含 source.json） |
| `batch_j1/`、`batch_j3/`、`batch_fail/` | batch manifest/outdir 证据 |
| `pytest.txt`、`collect.txt`、`check_all_fast.txt`、`verify_usecases.txt` | 回归原始输出（225 passed+1 skip / 226 collect / 6/6 / 22/22） |
