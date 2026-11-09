# 局限清单（cifkit / cif → anything）

> 更新：2026-11-09（round 13）。每一条都尽量给出**影响 / 现状 / 规避 / 证据**。
> 状态：✅ 已修或已覆盖；🟡 可绕过/有已知边界；🔴 未解决/未验证。
> 本表是"诚实边界"，不是 TODO 承诺；不把模板/预估说成已验证。

## 摘要

**共 69 条局限 = 7 ✅（已修/已覆盖） / 59 🟡（可绕过/已知边界） / 3 🔴（未解决/未验证）**

| 组 | 主题 | 条目 | ✅ | 🟡 | 🔴 |
|---|---|---|---|---|---|
| A | 数据源 | 6 | 0 | 6 | 0 |
| B | 拓扑判定 | 5 | 0 | 5 | 0 |
| C | 补氢 / 修复 | 6 | 0 | 5 | 1 |
| D | 几何 / 切面 / 真空 | 4 | 0 | 4 | 0 |
| E | 导出 / 计算软件输入包（cif → anything） | 6 | 0 | 6 | 0 |
| F | 特征 / 数据集 | 6 | 1 | 5 | 0 |
| G | 性能 / 并发 / 稳定性 | 7 | 1 | 6 | 0 |
| H | 技能 / 路由 / 测试覆盖 | 6 | 2 | 2 | 2 |
| I | 环境 / 网络 / 依赖获取 | 4 | 0 | 4 | 0 |
| J | 嵌入接口 / 商用平台（cifkit.api + cifkit.service） | 8 | 1 | 7 | 0 |
| L | 许可 / 商用合规 | 11 | 2 | 9 | 0 |

**未解决的 🔴 一览（需要外部条件或额外工程）**

- **C2** **MIL-101 未验证**（CoRE 无条目；COD 部分占据展开 16000 原子） → 该 MOF 不在覆盖范围
- **H3** 测试套件里未在 CI 跑真实 VASP/QE/CP2K/... 执行（环境无这些软件） → 模板正确性靠静态检查
- **H4** 只在 Windows + Python 3.14 实测；未做 Linux/macOS CI → 跨平台差异未验证（行尾问题已由 G6 兜住）

---

## A. 数据源


| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| A1 | QMOF 只有**本地镜像**，figshare/GitHub 在本环境不可稳定下载 | 🟡 | 不能在线拉 QMOF；只能读 `$CIFKIT_QMOF_DIR` | `scripts/bootstrap_qmof.py` 提供下载/提取（网络可达时）；缺镜像时报可操作错误，不伪造 | docs/SOURCES §7e |
| A2 | Materials Project 需要 `MP_API_KEY`，本机无 key | 🟡 | MP live 未验证；2 条 live 测试被 skip | 设置环境变量即可；mock 测试覆盖解析逻辑 | `tests/test_mp_live.py`（skipif） |
| A3 | CoRE MOF 2024 只有 ASR 子集带 RCSR 拓扑列；NCR 无拓扑元数据 | 🟡 | NCR 结构拓扑需 `topology.verify`，可能 `unknown` | 报告里区分 `metadata/verified/unknown` | docs/SOURCES §2/§5 |
| A4 | AFLOW 无 RCSR 拓扑；`aflow:<auid>` 不能反查 | 🟡 | AFLOW 结果只能按 aurl/化学式；拓扑 unknown | 用 aurl 或化学式；拓扑靠结构比对 | docs/SOURCES §7c |
| A5 | COD 无拓扑列、实验结构质量参差、检索按文本 | 🟡 | COD 结构需复核；拓扑 unknown | 用 spglib/validate 复核 | docs/SOURCES §6 |
| A6 | 限流/退避行为已在**本地 mock 服务器**上验证（429/503/Retry-After/退避/限速），但**公网真实端点配额未知** | 🟡 | 真实限额、长时间高并发抓取仍未测 | 统一 `HttpClient`（指数退避+抖动+Retry-After+默认 0.25s/请求限速）；实测服务器 5 req/s 时 30 次批量抓取违规 0 次 | tests/test_http_client.py、tests/test_sources_http.py、docs/SOURCES.md |

## B. 拓扑判定


| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| A7 | 数据源适配器**未做失败注入**（磁盘满、代理中断、缓存写坏） | 🟡 | 极端环境下行为未知 | 缓存写用原子替换（locks.atomic_write_*）；网络错误统一重试 | tests/test_robustness.py、cifkit/locks.py |
| B1 | 落盘参考只有 **6 个 net**（sod/pcu/dia/fcu/tbo/bcu） | 🟡 | hms/qtz/cag 等 net 判 `unknown` | 可扩展 `cifkit/data/nets/`；未知不硬猜 | docs/SOURCES §5 |
| B2 | SBU 收缩是启发式；多齿配体结构会返回 `unknown` | 🟡 | 部分真实 MOF 无法识别 | 诚实返回 unknown；参考结构避开多齿 | docs/SOURCES §5.1 |
| B3 | 高配位 net（pcu/fcu/tbo/bcu）环统计有上限（`rings_truncated`） | 🟡 | 这些 net 靠 CN+配位序列+linker 比判定，不靠环 | `verified_on` 字段明确写出依据 | docs/SOURCES §5 |
| B4 | 参考签名来自单个代表性结构，不是完整 RCSR 库 | 🟡 | 同 net 不同 SBU/畸变可能 mismatch | 报告差异；可自行替换参考 | `cifkit/data/nets/*.json` |

## C. 补氢 / 修复


| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| C1 | μ3-O vs μ3-OH 仅凭 M–O 距离双峰判定 | 🟡 | 无双峰时保守按 oxo（可能少补 1 个 H） | 给出 warning；需要化学式/中子/DFT 才能确定 | docs/REPAIR §8 |
| C2 | **MIL-101 未验证**（CoRE 无条目；COD 部分占据展开 16000 原子） | 🔴 | 该 MOF 不在覆盖范围 | 已记录原因，不用坏 fixture 硬凑 | tests/data/REPAIR_FIXTURES.md |
| C3 | **σ 型 M–C 已建模**（距离窗口 + 价键守卫）：二茂铁/ZnMe₂/η⁶-芳烃不再被乱补氢；但**离域多重度未建模**，M–M / M–H / 桥连羰基 / 4d-5d 长 σ 键仍漏 | 🟡 | 金属配位数会偏高；极端有机金属体系仍不适用 | `Bond.organometallic`、`ORGANOMETALLIC_MIN/MAX_DISTANCE`、`_prune_saturated_organometallic_bonds`；乙酸根 Zr···C 即使 2.5 Å 也被价键守卫拒绝 | tests/test_organometallic.py；docs/REPAIR.md |
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
> 语义细节：**给目录就一定走批量**（即使目录里只有 1 个 CIF → 子目录 + manifest）；单文件保持扁平输出（`outdir/<stem>.vasp`，`--stem X` → `outdir/X.vasp`）；子目录**不递归**扫描。

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
| F6 | 数据集**已流式**（manifest 惰性遍历 + 行不驻留 + 分页读取），但内存收益未在大语料量化 | 🟡 | 本机 8–12 runs 的峰值差异在噪声内（1.17×/0.94×），千级语料未测 | `build_dataset(stream=True)`（默认）、`iter_manifests`、`api.dataset_rows` 分页；结构性证据是 `max_rows_held=1` | docs/PERFORMANCE.md §10.3；tests/test_dataset.py |

## G. 性能 / 并发 / 稳定性


| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| F7 | 流式/并行的**收益未在大规模语料或空闲机器上验证**（本机饱和：纯 Python 对照 4 线程仅 0.78x） | 🟡 | 不要把 `--jobs`/流式当性能承诺 | `scripts/bench_api.py` 记录 `cpu_load_percent`+对照实验，随时可复测 | docs/PERFORMANCE.md §10 |
| G1 | batch 并发只在 3 并发测过（demo 2.8×，轻量 spec 1.91×），未测 8/16 扩展性 | 🟡 | 更大规模收益未知 | 起步 4；按机器/网络调 | docs/PERFORMANCE |
| G2 | slab 缓存是**进程内** LRU（24 条），跨进程不共享 | 🟡 | 多进程重复计算 | 单进程内批量复用 | docs/PERFORMANCE |
| G3 | `library/index.jsonl` 并发追加无跨进程行锁（只保证不产生半行） | 🟡 | 极端并发顺序不定 | 避免多进程同时 --ingest | docs/ROBUSTNESS |
| G4 | 文件锁只保护 CoRE 索引构建；其它缓存文件靠原子写 | 🟡 | 读者可能读到旧值 | 重跑/原子替换 | docs/ROBUSTNESS |
| G5 | 未做真实 SIGKILL 中途崩溃的完整恢复测试（只有锁 stale 恢复） | 🟡 | 崩溃后需重跑 | 重跑幂等 | docs/ROBUSTNESS |
| G6 | 行尾（EOL）会破坏按字节 sha256 钉住的文件 | ✅ | 修复前**任何干净 clone 都会红**（nets 参考哈希 FAIL、verify_demo 7/8、check_all 6/7） | `.gitattributes` 统一 `eol=lf`；`runs/**` 标 `-text`；已实测 clone 通过 | `.gitattributes`；REVIEW-ROUND11-OPT P1-b |

## H. 技能 / 路由 / 测试覆盖


| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| G7 | 锁等待在**高负载**下过紧（8 并发构建索引时 waiter 曾 120s 超时）——现已改为「超时后先复查缓存 + 有界重试」 | ✅ | 极端负载下仍可能整体超时（此时会明确报错） | `CIFKIT_LOCK_TIMEOUT`(120s)/`CIFKIT_LOCK_TOTAL_TIMEOUT`(900s) 可调；对等进程完成后 waiter 直接复用其索引 | tests/test_lock_contention.py；cifkit/sources/core_mof.py |
| H1 | 路由是 pattern+keyword+域先验，不是语义模型；罕见表述可能错 | 🟡 | 新说法可能落到 fallback | 已加 89 条 eval + 负例；持续补 eval | docs/SKILLS |
| H2 | 4 条 opt-in/skipped：MP live×2、QMOF live、metals 全量 zip | 🟡 | 未在 CI 覆盖 | 有 key/镜像/env 时打开 | tests |
| H3 | 测试套件里未在 CI 跑真实 VASP/QE/CP2K/... 执行（环境无这些软件） | 🔴 | 模板正确性靠静态检查 | 用户侧验证；文档标注 | docs/EXPORT |
| H4 | 只在 Windows + Python 3.14 实测；未做 Linux/macOS CI | 🔴 | 跨平台差异未验证（行尾问题已由 G6 兜住） | 文档说明；`.gitattributes` 保证各平台 checkout 字节一致 | README、.gitattributes |
| H5 | `check_skill` 已接入 `check_all`（8 个 cif-* 技能 errors=0） | ✅ | 仍依赖 `D:\agent-library` 存在 | `--skip-agentlib` 可跳过 | check_all 第 7 组 |

## I. 环境 / 网络 / 依赖获取


> 自检工具：`scripts/verify_formats.py`（31 格式独立回读）、`scripts/adversarial_check.py`（18 项破坏性检查）、`scripts/check_all.py [--fast] [--adversarial]`（7 组健康检查，含 `check_skill cif-*`）。
> 干净 clone 验收（round 12）：`git clone` → 拓扑参考哈希测试通过、`verify_demo` 8/8、`check_all --fast` 7/7（修复前分别是 FAIL / 7-of-8 / 6-of-7）。

| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| I1 | 不提供 POTCAR/UPF/skf/力场/basis（许可与体积） | 🟡 | 用户必须自备 | bundle `missing` 明确列出 | docs/EXPORT |
| I2 | 数据许可：CoRE CC-BY-4.0；COD 公有领域；MP/AFLOW 条款；QMOF 派生自 CoRE/CSD | 🟡 | 再分发前需核对 | SOURCES/pipeline 记录 DOI/license | docs/SOURCES |
| I3 | 本环境网络受限：figshare 不稳、rcsr.anu.edu.au 不可达 | 🟡 | QMOF/RCSR 在线验证受限 | 本地镜像/缓存优先 | docs/SOURCES |
| I4 | MP 无 key（同 A2） | 🟡 | live 未验证 | 用户设置 key | tests/test_mp_live.py |

## J. 嵌入接口 / 商用平台（cifkit.api + cifkit.service）


| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| J1 | **提供** `authorizer=` 钩子与 per-tenant `Policy`，但**不含**鉴权实现（无 JWT/OAuth/密钥库） | 🟡 | 平台仍需自己做认证与授权决策 | `GuardedService(policy, authorizer=...)`；`request["auth"]` 走信封层，不进入 op 契约 | cifkit/platform.py；tests/test_platform.py |
| J2 | 超时是**尽力而为**（线程超时返回 504，但无法安全终止已在跑的计算） | 🟡 | 超时后 worker 可能仍在后台跑完 | `Policy(timeout_s=...)` → 504 `timeout`；需要硬杀用 `executor="process"` | cifkit/platform.py；tests/test_platform.py |
| J3 | `handle()` 吞掉异常（防 traceback 外泄） | 🟡 | 线上排障只能看日志 | 复现时直接调 `api.*` 拿真实异常 | `cifkit/service.py` |
| J4 | 已有**分页**（`dataset_rows` 只读 offset+limit 行；`features_many` 支持 offset/limit + total），但**无流式响应/HTTP chunked** | 🟡 | 极大响应仍需一次性 JSON | 平台按页拉取；`columns=` 投影减小体积 | cifkit/api.py；tests/test_pagination.py |
| J5 | 有**背压与并发上限**（`max_concurrency` + `queue_size` → 503 `busy`），但仍无压力曲线 | 🟡 | 真实吞吐/延迟未测 | `GuardedService` 有界准入 + 统计计数；压测仍需平台侧做 | tests/test_platform.py::test_backpressure_rejects_when_saturated |
| J6 | 1.0 是首个冻结版本，无 LTS 承诺 | 🟡 | 次版本兼容、主版本可能破坏 | 平台按 `api_version` 分支；schema 文件可做网关校验 | docs/API.md §5 |
| J7 | `structure` 参数接受 pymatgen 对象 → RPC 场景不可用 | 🟡 | HTTP 调用者只能用 `path`/`cif_text` | 平台把结构序列化成 CIF 文本传入 | `cifkit/contract.py` ops.json |
| J8 | 已有**路径沙箱**（read_roots/write_roots，resolve 后包含性检查，挡 `..` 与逃逸符号链接） | ✅ | 进程内检查（TOCTOU 非绝对；跨盘符按拒绝处理） | `Policy(read_roots=..., write_roots=...)` → 403 `forbidden-path`；另限 `max_bytes`/`max_atoms`/`max_inputs` | cifkit/platform.py；tests/test_platform.py |

## L. 许可 / 商用合规


| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| J9 | CPU 密集 op 的并发扩展性差（GIL）：4 worker 吞吐仅约 1.2×，p50 延迟上升约 3× | 🟡 | 该服务适合多小请求，不适合并行大计算 | 重计算放工作队列/进程池；`executor="process"` 仅在长批时可选 | docs/PERFORMANCE.md §10.4 |
| L1 | 本仓代码许可此前未声明 | ✅ | 商用集成无从判断 | 已加 **MIT** `LICENSE`（可商用/可闭源/可再分发） | LICENSE |
| L2 | Open Babel 是 **GPL-2.0**，曾出现在依赖清单里 | ✅ | GPL 会传染闭源商用 | 实测**核心不 import 它**（屏蔽后 31 格式 + 12 包全过）；已从"运行时 packages"移到可选清单 | scripts/verify_formats_no_gpl.py；LICENSING.md §2 |
| L3 | **ASE 是 LGPL-2.1+** | 🟡 | 修改 ASE/静态嵌入会触发 LGPL 义务 | 本仓不修改 ASE；动态使用通常可与专有代码共存，**商用前请法务确认** | scripts/license_audit.py |
| L4 | 数据源许可各不相同（CoRE CC-BY-4.0 / COD 公有领域 / MP+条款 / AFLOW 条款 / QMOF 派生 CSD） | 🟡 | 再分发数据可能违约 | `manifest` 记录 `license`；逐源表见 LICENSING.md §3；平台需透传署名 | LICENSING.md |
| L5 | 下载的 `core-mof` 缓存**不建议再分发**（CSD 派生） | 🟡 | 打包镜像可能侵权 | 只分发代码/脚本，让用户自行 `bootstrap_data.py` 取数 | LICENSING.md §3 |
| L6 | 不提供 POTCAR/UPF/skf/力场/basis | 🟡 | 输入包不能直接算 | `missing` 列表 + README 明确；平台需引导用户自备 | docs/EXPORT.md §6 |
| L7 | 已有 **SCA-lite**（区分代码/注释；源码级 copyleft = 0，`--strict` 进 CI）；**仍非**代码溯源/相似度审计 | 🟡 | 不能证明与外部 GPL 代码无实质性相似 | `scripts/sca_scan.py --strict`（check_all 第 8 组）；完整 SCA 用 ScanCode/FOSSology | runs/sca_scan.json |
| L8 | 依赖许可审计基于安装元数据 + 人工覆盖，非法律意见；条款会变 | 🟡 | 审计可能过期 | 定期重跑 `license_audit.py --all`，核对官方页面 | scripts/license_audit.py |
| L9 | Python 依赖的**间接依赖**未展开（只审运行时直接依赖） | 🟡 | 传递依赖里可能藏 copyleft | `license_audit.py --all` 全量扫描（本机 100+ 包）后人工复核 | scripts/license_audit.py --all |
| L10 | 平台若把生成的结构/输入包再分发，需自行确认基础数据许可 | 🟡 | 连带责任 | 平台侧做数据血缘与许可标记 | LICENSING.md §4 |
