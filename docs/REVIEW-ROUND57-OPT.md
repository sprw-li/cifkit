# Round 57：OPT 批次（council 选点 → 实施 → 对抗复核 → 修复闭环）

> 本轮流程：**council 多模型选点**（3 个独立评审员并行 + 主席复核关键指控）→ OPT 批次实施 →
> **独立对抗复核**（bohrium 评审员，产物 `runs/_adversarial_r57/`）→ 复核挖出 4 个 P1 → 修复闭环 → 全量回归。
> council_review 工具本身两次全模型失败（runId `cmwj03bmupz4s9`、`cmwj0hsiz4egvq`，三个默认模型同因「阶段失败」），
> 按 council 的「提案 → 互审 → 主席定稿」流程用 3 个 bohrium 独立评审员等价替代：
> 评审员 A（文档一致性）、B（代码缺陷）、C（测试盲区与诚实性）；主席对全部 P1 指控逐条亲手复核/复跑后才实施；
> 实施完成后由第 4 个独立评审员对抗复核（见 §四）。
> 基线：HEAD `ed8d2e8`（round 56）；证据目录 `runs/_council_review_b/`（评审员 B 复现产物）、`runs/_lead_verify_opt/`（主席复跑产物）、`runs/_adversarial_r57/`（对抗复核产物）。

## 结论

**6 个代码修复 + 文档真实性清扫落地；对抗复核的声明验收全部成立、随后挖出的 4 个 P1（F1-F4）全部修复闭环**。
全量回归 **723 collected = 713 passed + 4 failed + 6 skipped**（4 failed 全部来自工作区**未跟踪的 WIP 脚本**
`scripts/check_lammps_physics.py` 未归类触发 check_ci 门禁，与本轮无关，见 §六）。本轮新增 **22 条测试**
（convert 碰撞×2、batch spawn/timeout×2、契约对抗×7、streaming 边界×4、RDF 物理×2、并发原子写×1、release 分组门禁×2、LAMMPS tilt×2）。

## 一、 council 评审确认的问题（全部主席复核过）

| # | 级别 | 问题 | 评审员 | 主席复核方式 |
|---|---|---|---|---|
| 1 | P1 | **RDF 特征列恒全 0**：邻居物种解析走了 Site 助手 `element_symbol()`，喂裸 `Element/Species` 恒得 "X" → 每条观测被丢弃且无 `rdf_error`；另有壳层体积 `(4/3)πΔr³`（应为 r₂³−r₁³）与归一化用总原子数两处潜伏错 | B | 复跑：ZIF-8 全部 10 列 sum=0.0，`element_symbol(Element('Cl'))='X'` |
| 2 | P1 | **LAMMPS 导出对非正交晶胞写错盒子**：用晶格长度当轴对齐盒边界、不写 tilt 行；六方 y 周期 2.8146 Å 被写成 3.25 Å（+15.5% 密度），原子甚至落在声明盒外；且 geometry_check 的指纹回退对该缺陷**全盲** | B | 复跑：`Lattice.hexagonal(3.25, 5.2)` 导出无 tilt 行、y 盒 3.25 |
| 3 | P1 | **convert 批量去重后缀可撞真实文件名**：`d1/same.cif + d2/same.cif + d3/same_001.cif` → 3 输入只产出 2 个子目录，先者被静默覆盖、manifest 仍 `n_ok=3`、exit 0（round 11 的修复只挡了同名变体） | B | 复跑：3 输入 → 2 目录，manifest n_ok=3 |
| 4 | P1 | **契约数值校验对 NaN/±Infinity 全失效**：普通比较对 NaN 恒 False → 坏值穿透派发层变 500；`service.handle` 重建 `{"op","params"}` 后校验 → 顶层 `additionalProperties:false` 与 auth 类型检查是死代码；流式路由 `int()` 在 try 外 + limit 口径与契约脱节 | C | 读码确认 contract.py:225-231 / service.py:81 / service.py:186-201 |
| 5 | P1 | **batch 只捕 TimeoutExpired**：spawn 失败（OSError）会让 `future.result()` 冒泡 → batch_manifest.json 永远不写，违背 PERFORMANCE.md「任一失败仍进 manifest」；timeout 路径零测试 | C | 读码确认 cli.py:215-250 |
| 6 | P1 | **README 声称 export 只有 7 种、gaussian/orca/abacus「未实现」**——实际 31 种全支持 | A | 复跑：三格式全部 exit 0 写出 |
| 7 | P1 | **LIMITATIONS G4「原子写」声明超前于实现**：dataset 清单、verify_formats 报告、run manifest/report 全是裸 `write_text`，全仓 `atomic_write_text` 只有 2 处调用 | C | grep 确认 dataset.py:395/:448、verify_formats.py:280、provenance.py:96/:123 |
| 8 | P2×N | 文档漂移一批（LIMITATIONS J 组统计、skip 枚举 4 vs 6、API.md §7 与已实现能力矛盾、SKILLS「五个数据源」、COVERAGE 与 SOURCES 的 name 字段口径、PERFORMANCE slab 缓存自相矛盾、LICENSING permissive 计数、check_all 组数 7→13、E1 43→54 条、3 个断链） | A/C | grep/程序化核对 |

**评审员的 P1 里有一条不复现**（如实记录）：C 的「单原子 validate 响应含 Infinity」在 HEAD 实测**不成立**
——`checks.py:302` 的 `isfinite` 守卫已把非有限距离映射为 None，单原子响应严格 JSON 合法（主席复跑）。
该场景已转为回归测试钉死（`test_responses_are_strict_json_for_degenerate_structures`），HTTP 层另加了响亮防线。

## 二、实施（全部带回归测试）

| 修复 | 文件 | 要点 |
|---|---|---|
| OPT-1 RDF | `cifkit/features.py` | `el_j = getattr(nb.specie, "symbol", None) or str(nb.specie)`；壳层体积 `(4/3)π(r₂³−r₁³)`；归一化改为配对密度（A≠B：`N_A·ρ_B+N_B·ρ_A`；A=B：`N_A·ρ_A`），列集合不变（对称定义写入 FEATURES.md）。**实测**：ZIF-8 10/10 列非零、C–C 峰 1.36 Å g=6.8、随机理想混合平台 0.948–1.009 ≈ 1 |
| OPT-2 LAMMPS 盒 | `cifkit/export/writers.py`、`cifkit/export/geometry_check.py` | 盒子数学交给 ASE `Prism`（旋转 + tilt 因子 + 坐标 wrap；**不做约化**——约化会改变晶胞形状、与读回守卫矛盾），**超半盒限的 tilt 直接拒绝**（真实 LAMMPS 本就会拒收，γ=170° 用例锁定）；正交胞输出不变；geometry_check 新增**方向自由 cellpar 守卫**（长度 0.02 Å / 角 1°），错盒必 FAIL（旧式文件 gamma 90≠120 被抓）、旋转差异不误杀；对无 cell 容器（xyz/mol）不触发 |
| OPT-3 convert 碰撞 | `cifkit/cli.py` | stem 全局唯一化：预留集 = 全部输入 stem，后缀循环避开一切已占用名；**判重在 `casefold` 上做**（对抗复核 F2：Windows 大小写不敏感文件系统上 `Same`/`same` 物理同目录，字符串判重挡不住） |
| OPT-4 契约加固 | `cifkit/contract.py`、`cifkit/service.py` | 数值必须 `isfinite`（NaN/±Inf → 400 violations）；`validate_request(request)` 校验原始对象（顶层键/auth 复活）；HTTP 边界 `parse_constant` 拒 NaN 字面量、`parse_float` 拒溢出到 inf 的**合法 JSON 数字**（1e309）；`params_echo` 清洗非有限值（否则带 violations 的 400 自身不可序列化 → 降级 500）；流式路由 int 解析入 try、limit 对齐契约（默认 10000，上限 10000），坏参数回 JSON 400 |
| OPT-5 batch manifest | `cifkit/cli.py` | `run_one` 捕 `OSError` 记录（永不抛）；`future.result()` 防线兜底记录 worker 崩溃——manifest 永远写出 |
| OPT-6 原子写 | `cifkit/provenance.py`、`cifkit/dataset.py`、`cifkit/locks.py`、`scripts/verify_formats.py` | G4 点名文件全部换 `atomic_write_json`/`atomic_write_text`；G4 条目补「round 57 复核」注记；**locks.py 的 tmp 名加 pid+线程 id+随机后缀**（对抗复核 F4：仅 pid 时两线程互踩），`os.replace` 遇 Windows 读者持锁做有界重试 |
| OPT-7 文档清扫 | README、docs/{API,SKILLS,FEATURES,COVERAGE,PERFORMANCE,LIMITATIONS}.md、LICENSING.md | 见 §三 |
| OPT-8 严格 JSON | `cifkit/service.py` | `_send` 用 `allow_nan=False`，非有限响应 → 响亮 500（不静默发非法 JSON） |
| 门禁升级 | `scripts/release_check.py` | 新增 `limitations_group_table_ok`：分组表按**条目 ID 前缀**与逐条状态列对账（J 行 1✅/7🟡 漂移存活数周的原因就是没人解析这张表）；含真实文件一致性测试 + 注入负例 |

## 三、文档修正清单（本轮全部经 grep/程序化核对）

- README：export「7 种/未实现」→ 31 种（能力矩阵 + 局限清单两处）；fetch 数据源补 QMOF；测试分布 4 处过期数字（sources 18、robustness 8、sources-qmof 5、topology-nets 35、batch 5）+ 标注覆盖范围；eval 数字统一为实测 **96/96**（catalog 已从 89 涨到 96，历史数字保留在评审记录段）；测试总数 701→723（695+6 → 713+4F+6S，如实标注 4F 根因）。
- SKILLS.md：六个数据源（补 qmof）；cif-export 行「当前支持 7 种」→ 31 种。
- API.md：§7「已知限制」删除与 round 50/52 矛盾的「无超时/取消/流式/分页」三句；§2 op 表补 `dataset_rows`；流式示例 limit=100000 → 100 并写明契约上限；3 个断链修复（schemas/LICENSE 路径）。
- LIMITATIONS：J 组行 1✅/7🟡 → 2✅/11🟡（最终口径 13 条 2✅/11🟡，含新增 J12/J13）；H2 skip 枚举 4 → 6（补 2 条环境型）；组表整表与逐条状态列**程序化对账**（新增 K 行；A/B/F/G/H/I/J/L 多行数字按 ID 前缀口径修正，F7/G7/G8 移回各自组节）；E1「43 条检查」→ 54；H4/自检工具「7 组」→ 13；G4 补 round 57 复核注记；**新增 G9（锁 TOCTOU 🟡）、G10（原子写 tmp 仅 pid → 对抗闭环后转 ✅）、J12（--ingest 同名覆盖 🟡）、J13（fetch 0 命中退出码口径 🟡）**。
- COVERAGE.md：name 字段口径对齐 SOURCES（1372 行里真名仅 1 条 MOF-801，非「多为 refcode」）。
- PERFORMANCE.md：slab 缓存「暂不做磁盘」→ 磁盘层已做（round 47）。
- LICENSING.md：permissive 7 → 8（列了 8 个包）。
- REVIEW-ROUND3.md：`../../docs/` 断链修复。

## 四、对抗复核（第 4 个独立评审员）挖出的 4 个 P1 → 全部修复闭环

> 复核员对每项修复都先确认「声明验收标准成立、无造假」，再从平台/并发/边界维度攻击。
> 完整报告与自跑脚本：`runs/_adversarial_r57/REPORT.md`。复核基线 717 = 707 passed + 4 failed（已知 check_ci 家族）+ 6 skipped（当时的收集数；
> 对抗修复再加 4 条测试后终态 **723 = 713 + 4F + 6S**）。

| # | 级别 | 复核发现 | 修复 | 回归测试 |
|---|---|---|---|---|
| F1 | P1 | **「tilt 约化」声明为假**：`Prism(pbc=True)` 默认 `reduce_cell=False`，γ=170° 写出 xy=−3.94（超半盒限），真实 LAMMPS 拒收，cifkit 静默；ASE 回读+cellpar 守卫对该缺陷结构性全盲；且若改 `reduce_cell=True`，cellpar 守卫会误 FAIL（writer 与守卫互相矛盾） | **超半盒 tilt 直接拒绝**（真实 LAMMPS 本就拒收；约化会改晶胞形状、与守卫矛盾，拒绝是唯一自洽解）；γ=170° 用例锁定（不落盘、报错文案含 tilt factor） | `test_skewed_cell_beyond_half_box_is_refused`、`test_edge_tilt_exactly_half_the_box_is_allowed`（六方 γ=120° 恰在半盒限，保持可用） |
| F2 | P1 | **大小写碰撞**：Windows 上 `Same.cif + same.cif`（两个不同结构）→ 子目录物理同名 → 第一输入导出被静默覆盖销毁，manifest 仍 n_ok=2/exit 0 | stem 判重改在 `casefold` 上（保留原大小写用于输出） | `test_convert_batch_case_insensitive_stems_do_not_collide`（原子数 16/138 双存活） |
| F3 | P1 | **1e309 是合法 JSON**（溢出为 inf，`parse_constant` 看不见）：契约正确拒了，但 400 的 `params_echo` 带 inf → `allow_nan=False` 崩 → 降级 500，violations 送不到客户端 | 边界加 `parse_float` 钩子拒溢出数字；`params_echo` 递归清洗非有限值（repr 字符串） | `test_rpc_body_with_overflow_number_is_400`、`test_rejected_request_echo_is_strictly_serialisable` |
| F4 | P1 | **并发原子写互踩**：tmp 名仅 pid，两线程写同一 outdir 的 dataset manifest 4/6 轮 PermissionError、无锁读者致写者崩、一次 manifest 消失（Windows `os.replace` 撞读者） | tmp 名加 pid+线程 id+随机后缀；`os.replace` 有界重试（5×20ms 递增）；**G10 转正 ✅** | `test_atomic_write_survives_concurrent_thread_writers`（4 线程×20 轮全成、无 tmp 残留） |
| F5 | P2 | 文档数字漂移：715/705 → 复核时点实测 717/707（最后 2 条 release gate 测试晚于全量跑）；「新增 14 条」实为 16；「pagination 3」实为 8；「export 全家 56」不可复现 | 全部数字按**最终实测**刷新：**723 = 713 passed + 4 failed + 6 skipped**（junit），export 相关 6 个测试文件 58 passed，各分项见 §六 | junit 存档 `runs/_adversarial_r57/junit_r57.xml`、`runs/_lead_verify_opt/junit_final.xml` |

**复核员总结的根因模式**（原话保留）：F1/F3 都是"修复正确但证据通道看不见它"——ASE 回读看不见 LAMMPS 的盒约束，handle() 看不见序列化失败；F2/F4 是修复声明覆盖了触发类但平台/并发维度漏了。

## 五、明确不修（本轮如实入账，见 LIMITATIONS G9/J12/J13）

- `cifkit/locks.py` 两处竞态（空锁体窗口、stale 抢占后误删他人锁）——当前调用点单写者/短临界区，实测未触发（G9 🟡）；
- ~~`atomic_write_text` tmp 名仅 pid~~ → **本轮 F4 已修**（G10 ✅）；
- `--ingest` 以 outdir 基名为 key 的同名覆盖（J12 🟡）；
- `fetch` 0 命中退出码 1/0 摇摆（J13 🟡）；
- `pipeline --spec` 未知键静默丢弃、`verify_corpus.py` 单坏结构丢整份报告——评审员证据成立，留待下轮（改动面涉及 CLI 语义契约，需要先定口径）。

## 六、回归与已知红

- **全量 pytest（对抗修复后实测，junit）：723 collected = 713 passed + 4 failed + 6 skipped**。4 failed（`test_check_ci`×3、`test_check_all_report`×1）
  全部断言 `unclassified=['check_lammps_physics.py']`——**工作区未跟踪的他人 WIP 脚本**触发 check_ci 的「每个非 CI 脚本必须有归类」门禁；
  提交时点（无该文件）等价于 713 passed + 6 skipped、0 failed。本轮零新增失败。
- 分项（对抗修复后）：export 相关 6 个测试文件 **58 passed**（含 F1 的 2 条）；本轮触碰的 streaming/contract-adv/convert/batch/concurrent-index/release-gate 合计 **56 passed**；
  features+dataset **22 passed**；`verify_formats` 31/31 + 第三方回读 25/25（worst deviation 3.16e-3 Å 与基线一致）+ 12 bundle。
- LIMITATIONS 双门禁（headline 22✅/59🟡/0🔴 + 分组表 12 组）实测 PASS。
- `eval_router --all`（agent-library，catalog 96 条）：intent/skill top1/top5 96/96、负例 0/25、槽位 11/11。

## 七、诚实边界

- **council 独立性弱于以往轮次**：council_review 工具不可用，选点阶段三个评审员 + 实施后对抗复核一个评审员均为同一 provider（bohrium）；
  实施者（主席）与复核者是分离的，但「互审」没有跨 provider。建议在 council 通道恢复后对 §二的 diff 做一轮跨 provider 评审。
- LAMMPS 修复未在真实 `lmp` 二进制上重跑（云端验收通道需要凭据/光子）；ASE 读回 + cellpar 守卫 + hex/tri/ortho/γ170 四类用例为当前证据。
- RDF 修复没有理论解析验证（解析 g(r) 需要解析配分），证据是「随机混合平台 ≈1 + 真实结构第一峰物理合理 + 2 原子体系解析校验（复核员：g=68.155 与解析值逐位一致）+ 旧公式反例」。
- 4 个 check_ci 失败依赖他人文件归类，若该脚本最终移出 `scripts/`，本节的数字表述依然成立（写的是因果不是快照）。
- 分组表统计口径是「条目 ID 前缀」，与物理章节仍有历史漂移（A7/A8 在 B 节、J9-J11/H3b/H3c/K9 在 L 节）——表已与逐条状态列程序化对账，重编号留待后续轮次。
