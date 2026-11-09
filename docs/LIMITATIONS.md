# 局限清单（cifkit / cif → anything）

> 更新：2026-11-08（round 9）。每一条都尽量给出**影响 / 现状 / 规避 / 证据**。
> 状态：✅ 已修或已覆盖；🟡 可绕过/有已知边界；🔴 未解决/未验证。
> 本表是"诚实边界"，不是 TODO 承诺；不把模板/预估说成已验证。

## A. 数据源

| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| A1 | QMOF 只有**本地镜像**，figshare/GitHub 在本环境不可稳定下载 | 🟡 | 不能在线拉 QMOF；只能读 `$CIFKIT_QMOF_DIR` | `scripts/bootstrap_qmof.py` 提供下载/提取（网络可达时）；缺镜像时报可操作错误，不伪造 | docs/SOURCES §7e |
| A2 | Materials Project 需要 `MP_API_KEY`，本机无 key | 🟡 | MP live 未验证；2 条 live 测试被 skip | 设置环境变量即可；mock 测试覆盖解析逻辑 | `tests/test_mp_live.py`（skipif） |
| A3 | CoRE MOF 2024 只有 ASR 子集带 RCSR 拓扑列；NCR 无拓扑元数据 | 🟡 | NCR 结构拓扑需 `topology.verify`，可能 `unknown` | 报告里区分 `metadata/verified/unknown` | docs/SOURCES §2/§5 |
| A4 | AFLOW 无 RCSR 拓扑；`aflow:<auid>` 不能反查 | 🟡 | AFLOW 结果只能按 aurl/化学式；拓扑 unknown | 用 aurl 或化学式；拓扑靠结构比对 | docs/SOURCES §7c |
| A5 | COD 无拓扑列、实验结构质量参差、检索按文本 | 🟡 | COD 结构需复核；拓扑 unknown | 用 spglib/validate 复核 | docs/SOURCES §6 |
| A6 | 未验证 AFLOW/COD 大规模限流与重试（只有单次重试逻辑） | 🔴 | 大批量抓取可能被限流 | 控制并发/加 sleep；未做压力测试 | Round4/7 报告"未验证" |

## B. 拓扑判定

| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| B1 | 落盘参考只有 **6 个 net**（sod/pcu/dia/fcu/tbo/bcu） | 🟡 | hms/qtz/cag 等 net 判 `unknown` | 可扩展 `cifkit/data/nets/`；未知不硬猜 | docs/SOURCES §5 |
| B2 | SBU 收缩是启发式；多齿配体结构会返回 `unknown` | 🟡 | 部分真实 MOF 无法识别 | 诚实返回 unknown；参考结构避开多齿 | docs/SOURCES §5.1 |
| B3 | 高配位 net（pcu/fcu/tbo/bcu）环统计有上限（`rings_truncated`） | 🟡 | 这些 net 靠 CN+配位序列+linker 比判定，不靠环 | `verified_on` 字段明确写出依据 | docs/SOURCES §5 |
| B4 | 参考签名来自单个代表性结构，不是完整 RCSR 库 | 🟡 | 同 net 不同 SBU/畸变可能 mismatch | 报告差异；可自行替换参考 | `cifkit/data/nets/*.json` |

## C. 补氢 / 修复

| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| C1 | μ3-O vs μ3-OH 仅凭 M–O 距离双峰判定 | 🟡 | 无双峰时保守按 oxo（可能少补 1 个 H） | 给出 warning；需要化学式/中子/DFT 才能确定 | docs/REPAIR §8 |
| C2 | **MIL-101 未验证**（CoRE 无条目；COD 部分占据展开 16000 原子） | 🔴 | 该 MOF 不在覆盖范围 | 已记录原因，不用坏 fixture 硬凑 | tests/data/REPAIR_FIXTURES.md |
| C3 | 有机金属 M–C σ 键（Cp/烷基/CO）不当配位键 | 🔴 | 有机金属体系不适用 | 文档声明适用范围 | docs/REPAIR §10 |
| C4 | 自由羧酸判定依赖"全结构无金属配位" | 🟡 | 混合体系可能误判 | 只对单相纯有机酸可靠 | docs/REPAIR §8.5 |
| C5 | 补的 H 是几何位置（RDKit/VSEPR），不是 DFT/QM 优化 | 🟡 | H 位置/键长是合理初值，非平衡态 | 后续做 DFT 弛豫 | docs/REPAIR |
| C6 | 无序/占位用启发式解析，非 CIF 精修 | 🟡 | 部分占据展开可能改变对称性 | 报告 `resolved_disorder`；建议回看原始 CIF | docs/REPAIR |

## D. 几何 / 切面 / 真空

| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| D1 | slab 终止面按"悬键+化学计量"启发式打分 | 🟡 | 不保证是能量最低表面 | 可指定 termination/shift；DFT 表面能另算 | docs/GEOM |
| D2 | `surface_frame="cell"` 是"先超胞再切"的字面语义，不是物理 (hkl) | 🟡 | 与默认 slab 语义不同 | 默认 `slab`；文档对比说明 | docs/GEOM |
| D3 | slab 未弛豫；表面能文件只是输入结构 | 🟡 | E_surf 需用户 DFT | 提供模板与公式；不含能量 | docs/PERFORMANCE / usecases/u3 |
| D4 | 超大超胞/slab 有原子数上限（`MAX_SLAB_ATOMS`） | 🟡 | 会明确报错而非 OOM | 降低厚度/超胞 | docs/GEOM |

## E. 导出 / 计算软件输入包（cif → anything）

> 已支持 `cifkit convert <文件或目录...> --to ... --bundle ...`：多输入时每输入一个子目录 + `convert_manifest.json`（n_ok/n_failed/每条错误），坏输入不中断批量；**同名文件（不同目录）会自动加序号后缀**，不会互相覆盖（round 10 自查修）。

> 已支持：`cifkit convert <文件或目录...> --to ... --bundle ...`（多输入 → 每输入一个子目录 + `convert_manifest.json`，坏输入单独记录不中断）。

| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| E1 | 31 种格式里 12 种电子结构代码是**模板**：POTCAR/UPF/basis/skf/力场不提供 | 🟡 | 不能"直接算" | bundle 带 `missing` 清单 + README；不谎称可运行 | docs/EXPORT §6 |
| E2 | 第三方独立回读覆盖 **25/31**（ASE 22 + pymatgen 3）；5 个模板 + png 走关键字/魔数检查 | 🟡 | 模板未在真实软件中执行；回读一致 ≠ 软件接受 | `scripts/verify_formats.py` 全量报告；`tests/test_verify_formats.py` 防止新增格式漏验证 | runs/verify_formats/verify_formats.json |
| E3 | 模板参数是默认值（ENCUT=520、2×2×2 k 点等），未做收敛测试 | 🟡 | 计算前必须自己收敛 | INCAR/KPOINTS/README 标注 | docs/EXPORT |
| E4 | PDB/SDF/MOL 不表达周期性；GRO 只有 3 位小数；LAMMPS data 为 atom_style atomic | 🟡 | 不能直接用于周期体系/带电体系 | 用 extxyz/vasp/cif；LAMMPS 需补力场/电荷 | docs/EXPORT |
| E5 | Gaussian/ORCA 模板默认电荷 0、多重度 1 | 🟡 | 开壳层/离子体系需改 | 模板注释提示 | docs/EXPORT |
| E6 | `cube`/`png` 之外的体积数据格式未实现（cube 需要 3D 数据数组） | 🟡 | 不能导出 volumetric cube | png 预览已支持；cube 文档标未实现 | docs/EXPORT §6 |

## F. 特征 / 数据集

| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| F1 | RDF 是有限网格近似（默认 50 bins × 8 Å），O(N²) | 🟡 | 大结构慢/列多 | `--no-rdf`；调 bins/max | docs/FEATURES |
| F2 | 特征全为几何/组成/对称性描述符，无 DFT 能量/带隙/电荷 | 🟡 | 不能直接当标签 | 用 `--label-key` 从 manifest 取，或自行 join | docs/FEATURES |
| F3 | 配位数按距离判据，不读化学价/自旋 | 🟡 | 氧化态/磁性不在特征里 | 结合外部数据 | docs/FEATURES |
| F4 | `rings` 已覆盖无金属框架（完整键图回退） | ✅ | 节点数上限 >600 原子跳过并标 `truncated` | 金属框架仍走 underlying net（`ring_basis=metal-net`） | `cifkit.topology.ring_statistics`；diamond 6 元环=16/胞实测 |
| F5 | dataset 只汇总已有 manifest，无去重/清洗/标签计算 | 🟡 | 数据集质量取决于 runs | 上游用 pipeline/batch 控制质量 | docs/FEATURES |
| F6 | 未做超大数据集流式处理（manifest 列表一次性载入） | 🔴 | 超大库可能内存吃紧 | 分批/分目录构建；from-library 已有测试 | tests/test_dataset.py |

## G. 性能 / 并发 / 稳定性

| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| G1 | batch 并发只在 3 并发测过（demo 2.8×，轻量 spec 1.91×），未测 8/16 扩展性 | 🟡 | 更大规模收益未知 | 起步 4；按机器/网络调 | docs/PERFORMANCE |
| G2 | slab 缓存是**进程内** LRU（24 条），跨进程不共享 | 🟡 | 多进程重复计算 | 单进程内批量复用 | docs/PERFORMANCE |
| G3 | `library/index.jsonl` 并发追加无跨进程行锁（只保证不产生半行） | 🟡 | 极端并发顺序不定 | 避免多进程同时 --ingest | docs/ROBUSTNESS |
| G4 | 文件锁只保护 CoRE 索引构建；其它缓存文件靠原子写 | 🟡 | 读者可能读到旧值 | 重跑/原子替换 | docs/ROBUSTNESS |
| G5 | 未做真实 SIGKILL 中途崩溃的完整恢复测试（只有锁 stale 恢复） | 🟡 | 崩溃后需重跑 | 重跑幂等 | docs/ROBUSTNESS |

## H. 技能 / 路由 / 测试覆盖

| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| H1 | 路由是 pattern+keyword+域先验，不是语义模型；罕见表述可能错 | 🟡 | 新说法可能落到 fallback | 已加 89 条 eval + 负例；持续补 eval | docs/SKILLS |
| H2 | 4 条 opt-in/skipped：MP live×2、QMOF live、metals 全量 zip | 🟡 | 未在 CI 覆盖 | 有 key/镜像/env 时打开 | tests |
| H3 | 252 条测试中，未在 CI 里跑真实 VASP/QE/CP2K/... 执行（环境无这些软件） | 🔴 | 模板正确性靠静态检查 | 用户侧验证；文档标注 | docs/EXPORT |
| H4 | 只在 Windows + Python 3.14 实测；未做 Linux/macOS CI | 🔴 | 跨平台差异未验证 | 文档说明 | README |
| H5 | `check_skill` 已接入 `check_all`（8 个 cif-* 技能 errors=0） | ✅ | 仍依赖 `D:\agent-library` 存在 | `--skip-agentlib` 可跳过 | check_all 第 7 组 |

## I. 许可 / 环境 / 网络

> 自检工具：`scripts/verify_formats.py`（31 格式独立回读）、`scripts/adversarial_check.py`（16 项破坏性检查）、`scripts/check_all.py [--fast] [--adversarial]`（7 组健康检查，含 `check_skill cif-*`）。

| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| I1 | 不提供 POTCAR/UPF/skf/力场/basis（许可与体积） | 🟡 | 用户必须自备 | bundle `missing` 明确列出 | docs/EXPORT |
| I2 | 数据许可：CoRE CC-BY-4.0；COD 公有领域；MP/AFLOW 条款；QMOF 派生自 CoRE/CSD | 🟡 | 再分发前需核对 | SOURCES/pipeline 记录 DOI/license | docs/SOURCES |
| I3 | 本环境网络受限：figshare 不稳、rcsr.anu.edu.au 不可达 | 🟡 | QMOF/RCSR 在线验证受限 | 本地镜像/缓存优先 | docs/SOURCES |
| I4 | MP 无 key（同 A2） | 🟡 | live 未验证 | 用户设置 key | tests/test_mp_live.py |
