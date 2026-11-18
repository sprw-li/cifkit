# 局限清单（cifkit / cif → anything）

> 更新：2026-11-17（round 58）。每一条都尽量给出**影响 / 现状 / 规避 / 证据**。
> 状态：✅ 已修或已覆盖；🟡 可绕过/有已知边界；🔴 未解决/未验证。
> 本表是"诚实边界"，不是 TODO 承诺；不把模板/预估说成已验证。

## 摘要

**共 89 条局限 = 30 ✅（已修/已覆盖） / 59 🟡（可绕过/已知边界） / 0 🔴（未解决/未验证）**

| 组 | 主题 | 条目 | ✅ | 🟡 | 🔴 |
|---|---|---|---|---|---|
| A | 数据源 | 8 | 1 | 7 | 0 |
| B | 拓扑判定 | 4 | 0 | 4 | 0 |
| C | 补氢 / 修复 | 6 | 0 | 6 | 0 |
| D | 几何 / 切面 / 真空 | 4 | 0 | 4 | 0 |
| E | 导出 / 计算软件输入包（cif → anything） | 8 | 2 | 6 | 0 |
| F | 特征 / 数据集 | 7 | 4 | 3 | 0 |
| G | 性能 / 并发 / 稳定性 | 12 | 10 | 2 | 0 |
| H | 技能 / 路由 / 测试覆盖 | 9 | 5 | 4 | 0 |
| I | 环境 / 网络 / 依赖获取 | 4 | 0 | 4 | 0 |
| J | 嵌入接口 / 商用平台（cifkit.api + cifkit.service） | 16 | 5 | 11 | 0 |
| K | 可移植性 / 产物卫生 | 1 | 1 | 0 | 0 |
| L | 许可 / 商用合规 | 10 | 2 | 8 | 0 |

> 统计口径（round 57 起，门禁 `release_check.limitations_group_table_ok` 强制）：按**条目 ID 前缀**计数；
> 部分编号历史上跨节存放（A7/A8 在 B 节、F7 曾在 G 节、J9-J11/H3b/H3c/K9 在 L 节），本表与逐条状态列保持一致，
> 与物理章节的对应关系留待后续统一重编号。
> round 58 新增 8 条（E7/E8/G11/G12/H7/J14/J15/J16），全部因当轮对抗评审发现并修复而计入 ✅。

**未解决的 🔴 一览（需要外部条件或额外工程）**

当前**没有** 🔴 条目：原先唯一的红项（H3 真实软件验收）已拆成 H3a/H3b/H3c，分别以「云端管线跑通 + NWChem 完整计算」「本仓 NWChem 模板跑完」「其余软件在做 parse/能量级验证，QE/CP2K 受镜像上游限制」结案。剩下的都是 🟡（边界已知、可绕过）或 ✅（已修）。

---

## A. 数据源


| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| A1 | QMOF 只有**本地镜像**，figshare/GitHub 在本环境不可稳定下载 | 🟡 | 不能在线拉 QMOF；只能读 `$CIFKIT_QMOF_DIR` | `scripts/bootstrap_qmof.py` 提供下载/提取（网络可达时）；缺镜像时报可操作错误，不伪造 | docs/SOURCES §7e |
| A2 | Materials Project 需要 `MP_API_KEY`，本机无 key | 🟡 | MP live 未验证；2 条 live 测试被 skip | 设置环境变量即可；mock 测试覆盖解析逻辑 | `tests/test_mp_live.py`（skipif） |
| A3 | CoRE MOF 2024 只有 ASR 子集带 RCSR 拓扑列；NCR 无拓扑元数据 | 🟡 | NCR 结构拓扑需 `topology.verify`，可能 `unknown` | 报告里区分 `metadata/verified/unknown` | docs/SOURCES §2/§5 |
| A4 | AFLOW 无 RCSR 拓扑；`aflow:<auid>` 不能反查 | 🟡 | AFLOW 结果只能按 aurl/化学式；拓扑 unknown | 用 aurl 或化学式；拓扑靠结构比对 | docs/SOURCES §7c |
| A5 | COD 无拓扑列、实验结构质量参差、检索按文本 | 🟡 | COD 结构需复核；拓扑 unknown | 用 spglib/validate 复核 | docs/SOURCES §6 |
| A6 | 限流：**本地 mock** 已覆盖 429/503/Retry-After/退避/限速；**公网真实端点已小规模实测**（COD 与 AFLOW 各 5 次按 0.25 s 节奏 + 5 次无间隔 burst）：**10/10 全部成功，无 429/503、无 Retry-After**；单请求耗时中位 **2.16 s（COD）/2.92 s（AFLOW）** | 🟡 | 真实配额**故意没有去打**（不做压测），所以上限仍未知；但已确认**服务器延迟(2-3 s)远大于我们的 0.25 s 间隔**，即在这类源上节奏参数不是瓶颈、跨源并列才是 | `scripts/probe_source_limits.py`（可复跑，写 runs/source_limits.json，单源最多 10 请求） |

## B. 拓扑判定


| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| A7 | 已做**故障注入**（磁盘满/只读/权限拒绝/坏 JSON/锁崩溃），验证「旧文件不被破坏 + 无残留临时文件 + 明确报错」 | ✅ | 故障类型仍有边界（代理级中断、NFS 语义、杀进程时序未单独注入） | `tests/test_failure_injection.py`（11 条，全部用 monkeypatch 注入，无需真满盘） | tests/test_failure_injection.py |
| A8 | 数据源可用性是**一次性快照**、不是监控：COD/AFLOW/MP 的实时状态每次都得手动跑；没有任何告警或历史曲线 | 🟡 | 平台若依赖外部源，需要自己的探测/告警 | `scripts/sources_live_check.py`（各源 TCP + 真实小查询 + 时间戳，写 runs/sources_live.json），已作为信息项进入 release_check | 2026-11-09 快照：core-mof/cod/aflow/local = ok，MP = needs-key，QMOF = not-configured |
| B1 | 落盘参考只有 **6 个 net**（sod/pcu/dia/fcu/tbo/bcu） | 🟡 | hms/qtz/cag 等 net 判 `unknown` | 可扩展 `cifkit/data/nets/`；未知不硬猜 | docs/SOURCES §5 |
| B2 | SBU 收缩是启发式；多齿配体结构会返回 `unknown` | 🟡 | 部分真实 MOF 无法识别 | 诚实返回 unknown；参考结构避开多齿 | docs/SOURCES §5.1 |
| B3 | 高配位 net（pcu/fcu/tbo/bcu）环统计有上限（`rings_truncated`） | 🟡 | 这些 net 靠 CN+配位序列+linker 比判定，不靠环 | `verified_on` 字段明确写出依据 | docs/SOURCES §5 |
| B4 | 参考签名来自单个代表性结构，不是完整 RCSR 库 | 🟡 | 同 net 不同 SBU/畸变可能 mismatch | 报告差异；可自行替换参考 | `cifkit/data/nets/*.json` |

## C. 补氢 / 修复


| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| C1 | μ3-O vs μ3-OH 仅凭 M–O 距离双峰判定 | 🟡 | 无双峰时保守按 oxo（可能少补 1 个 H） | 给出 warning；需要化学式/中子/DFT 才能确定 | docs/REPAIR §8 |
| C2 | **已查证为数据缺口**：CoRE MOF 2024（8300 条）**无** MIL-101 / OCUNAC 条目（名字字段只填了 1372 条，指纹检索 Cr≥3+F≥1+C≥20 只命中一个 Cr/F-MOF）；COD 全文检索 “MIL-101” 只返回无关小分子 | 🟡 | 该 MOF 不在覆盖范围；需要外部语料才能覆盖 | 已用 `runs/c2_core_mil_search.json` / `runs/c2_mil101_probe.json` 留证；可用最大 Cr/F-MOF（11152 原子）已做能力实测 | docs/PERFORMANCE.md §10.6 |
| C3 | **σ 型 M–C 已建模**（距离窗口 + 价键守卫）：二茂铁/ZnMe₂/η⁶-芳烃不再被乱补氢；但**离域多重度未建模**，M–M / M–H / 桥连羰基 / 4d-5d 长 σ 键仍漏 | 🟡 | 金属配位数会偏高；极端有机金属体系仍不适用 | `Bond.organometallic`、`ORGANOMETALLIC_MIN/MAX_DISTANCE`、`_prune_saturated_organometallic_bonds`；乙酸根 Zr···C 即使 2.5 Å 也被价键守卫拒绝 | tests/test_organometallic.py；docs/REPAIR.md |
| C4 | 自由羧酸判定依赖"全结构无金属配位" | 🟡 | 混合体系可能误判 | 只对单相纯有机酸可靠 | docs/REPAIR §8.5 |
| C5 | 补的 H 是几何位置（RDKit/VSEPR），不是 DFT/QM 优化 | 🟡 | H 位置/键长是合理初值，非平衡态 | 后续做 DFT 弛豫 | docs/REPAIR |
| C6 | 无序/占位用启发式解析，非 CIF 精修 | 🟡 | 部分占据展开可能改变对称性 | 报告 `resolved_disorder`；建议回看原始 CIF | docs/REPAIR；**round 56 量化**：320 个真实 CoRE MOF 中 **147 个（46%）有部分占据**，直接导出时 22 个格式拒绝（类型化 `disordered`/`format-limit` 错误）；但走项目自己的修复阶段后，抽样的 60 个**全部**变成有序结构并 **31/31 格式导出成功** |

## D. 几何 / 切面 / 真空


| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| D1 | slab 终止面按"悬键+化学计量"启发式打分 | 🟡 | 不保证是能量最低表面 | 可指定 termination/shift；DFT 表面能另算 | docs/GEOM |
| D2 | `surface_frame="cell"` 是"先超胞再切"的字面语义，不是物理 (hkl) | 🟡 | 与默认 slab 语义不同 | 默认 `slab`；文档对比说明 | docs/GEOM |
| D3 | slab 未弛豫（不变），但**表面能算术与配套工具已提供**：`cifkit surface-energy`（`E_surf = (E_slab - n_slab * e_bulk) / (N_surface * A)`），支持两种 bulk 参考写法、**化学计量校验**（组成不是整数倍就报错，避免拿不同组成的 bulk 相减）、eV/Å²、meV/Å²、J/m²（1 eV/Å² = 16.02176634 J/m²）、单/双表面 | 🟡 | 能量仍需用户自己的 DFT；工具只保证**算式与记账正确**，不产生能量 | `cifkit/surface_energy.py`、`cifkit/cli.py`（`surface-energy` 子命令）、`tests/test_surface_energy.py`（13 条）、`tests/test_surface_energy_cli.py`（6 条） |
| D4 | 超大超胞/slab 有原子数上限（`MAX_SLAB_ATOMS`） | 🟡 | 会明确报错而非 OOM | 降低厚度/超胞 | docs/GEOM |

## E. 导出 / 计算软件输入包（cif → anything）


> 已支持 `cifkit convert <文件或目录...> --to ... --bundle ...`：多输入时每输入一个子目录 + `convert_manifest.json`（n_ok/n_failed/每条错误），坏输入不中断批量；**同名文件（不同目录）会自动加序号后缀**，不会互相覆盖（round 10 自查修）。
> 语义细节：**给目录就一定走批量**（即使目录里只有 1 个 CIF → 子目录 + manifest）；单文件保持扁平输出（`outdir/<stem>.vasp`，`--stem X` → `outdir/X.vasp`）；子目录**不递归**扫描。

> 已支持：`cifkit convert <文件或目录...> --to ... --bundle ...`（多输入 → 每输入一个子目录 + `convert_manifest.json`，坏输入单独记录不中断）。

| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| E1 | 31 种格式里 12 种电子结构代码是**模板**：POTCAR/UPF/basis/skf/力场不提供；且这 12 个 bundle 的**跨文件契约现在被门禁校验**（必需文件、交叉引用、声明缺失必须真缺失，12/12 一致、54 条检查） | 🟡 | 模板仍不可直接运行（数据由用户提供），但**包内部不再自相矛盾**；检查器用故意破坏的包做过负例测试 | `scripts/check_bundles.py`、`cifkit/export/bundle_check.py`、`tests/test_bundle_check.py`（18 条）、`release_check` 第 13 道门；**新增注释风格门禁**：每种代码只认一种注释符（LAMMPS/DFTB+ 用 `#`、CP2K/QE 用 `!`、GROMACS 用 `;`），写错即被真实软件判为未知命令——该规则当场抓到 **LAMMPS `in.min` 与 CP2K `cp2k.inp` 两处真缺陷** |
| E2 | 第三方独立回读 **25/31**，而且**已从「原子数」升级为「几何」**：25 个格式全部通过几何比对（20 个精确到 ≤1e-6 Å；`gromacs` 3.2e-3 Å 对应其 3 位小数精度，`pdb` 3.5e-4 Å）；5 个模板格式（abacus/cp2k/dftb/orca/siesta）**没有第三方读取器**（ASE 实测读不了），改用自研严格解析；`png` 用魔数 | 🟡 | 模板仍只能自研校验；其它格式的「回读」只证明读取器能读回，不代表目标软件能算 | `cifkit/export/geometry_check.py`（周期走 StructureMatcher，无晶胞走「排序配对距离指纹」）、`scripts/verify_formats.py`（报告含 `n_geometry_checked`/`worst_deviation_A`）、`tests/test_export_fidelity.py`（8 条，含「合成晶胞不得触发周期匹配」「位移/换晶胞/换元素必须失败」）、`tests/test_template_check.py`；**round 55 升格为语料级验证**：`scripts/verify_corpus.py` 对 **16 个结构**（16-750 原子，含 424/750 原子大胞与 2 个 CoRE ASR 真实条目）跑完 31 格式 + 12 bundle + 5 模板，**逐个结构 31/31**（16/16 结构全通过），并行 8 进程 18 s；**round 56 扩到 320 个真实 CoRE MOF**（28-9872 原子，共 153226 原子，9920 次格式检查，8 进程 281 s）：**320/320 结构全通过**；本轮由此修掉 3 个真缺陷（`.struct` 静默截断、`.pdb` 容差模型、指纹回退漏检换元素）；**round 58 口径变更**：无法表示的晶胞由 `cifkit/export/refusals.py` 显式拒绝并记为 `unsupported`（不再算 bad），因此「320/320 全通过」应读作「**可表示的** 320/320 通过」，其余按 `n_unsupported` 单列（例：`sod_zn_mof.cif` 的 `lammps` 因 tilt 超半盒被拒） |
| E3 | 模板参数此前**没有收敛性验证**。现有完整机械（按代码生成扫描、解析各家能量方言、按「从某取值起后续每步 <= 阈值」判定、**要求输出有正常结束标记**、同一取值多次尝试时**优先采用完成的那次**）与真实云端数据（NWChem 7.2.2，16 原子周期胞，全部有 `Total times` 结束标记）：`20 -> -111.2953510 Ha`、`30 -> -111.6378257`、`40 -> -111.6688537`、`60 -> -111.7286759`；步间变化 **-582.5 / -52.8 / -101.8 meV/atom**（注意 40->60 又变大）。**结论：模板默认 cutoff 20 远未收敛，且到 60 Ha 仍在动 ~100 meV/atom**——这是**否定性**结果：该 smoke-test 设置不能用于生产 | 🟡 | 80 Ha 在 5400 s 单次上限内**超时**（作业级 failed，无输出）；高位扫描需要更长时限与更大机器（`MAX_SECONDS_PER_RUN` 已可调）；VASP/QE/CP2K 仍只能生成扫描 | `cifkit/export/convergence.py::output_completed`、`scripts/{run,collect,analyse}_convergence.py`、`cloud_h3/run_convergence_nwchem.py`、`tests/test_convergence.py`（21 条）、`tests/test_output_completion.py`（20 条）、证据 `runs/cloud_h3/conv_c*`、`runs/convergence/nwchem_cloud_report.json`（4 有效 + 1 作废 + 1 次被取代的尝试） |
| E4 | PDB/SDF/MOL 不表达周期性（不变）；GRO 3 位小数（不变）；**LAMMPS 现在带完整 `Masses` + `in.min` 三种力场选项**（`zero` 几何检查 / 通用 LJ 占位（明确标注不是拟合力场）/ 真实 FF 示例）；**GROMACS 现在带 `topol.top` 骨架**（每个原子含元素质量、`[ bonds ]` 来自 cifkit 的键感知、所有必需 section 齐全），但 **[ atomtypes ]/[ atoms ] 的电荷与 LJ 参数是占位值** | 🟡 | 力场无法从 CIF 推导——骨架把「写拓扑」的工作量降到「填参数」 | `cifkit/export/bundles.py::_gromacs_topology`、`tests/test_ff_skeletons.py`（6 条：section 齐全、原子数/质量、键引用合法、占位已标注、readme 说明、LAMMPS 三选项）；bundle 门禁规则同步更新 |
| E5 | Gaussian/ORCA 模板默认电荷 0、多重度 1 | 🟡 | 开壳层/离子体系需改 | 模板注释提示 | docs/EXPORT |
| E6 | `cube`/`png` 之外的体积数据格式未实现（cube 需要 3D 数据数组） | 🟡 | 不能导出 volumetric cube | png 预览已支持；cube 文档标未实现 | docs/EXPORT §6 |
| E7 | **裸 `--to dftb` 曾经只写 515 B 的 `dftb_in.hsd`（引用不存在的 `geo.gen`）却报 `ok:true`/exit 0**；且 `scripts/verify_formats.py` 验 dftb 时切到 `dftb_bundle` 目录，官方「31/31」从未覆盖裸产物（round 58 对抗评审发现） | ✅ | 已修：裸 `--to dftb` 在 HSD 同级写出配套 `geo.gen`（与 bundle 同 title 下字节一致），`writers._verify` 校验 HSD+`geo.gen` 配对，缺失/截断即报错；`verify_formats` 改为验证裸产物自身、bundle 另行验证；`dftb` 入 `ORDERED_ONLY` | `cifkit/export/writers.py`、`scripts/verify_formats.py`、`tests/test_dftb_single_format.py`（8 条） |
| E8 | 非 JSON 模式的单文件 `cifkit convert` 在**部分格式失败**时只打印成功项、exit 1 却零说明（round 58 对抗评审发现） | ✅ | 已修：非 JSON 模式同样打印失败项与原因；批量分支原本就会打印 | `cifkit/cli.py`、`tests/test_cli_json_strictness.py` |

## F. 特征 / 数据集


| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| F1 | RDF 是有限网格近似（默认 50 bins × 8 Å），O(N²) | 🟡 | 大结构慢/列多 | `--no-rdf`；调 bins/max | docs/FEATURES |
| F2 | 特征全为几何/组成/对称性描述符，无 DFT 能量/带隙/电荷 | 🟡 | 不能直接当标签 | 用 `--label-key` 从 manifest 取，或自行 join | docs/FEATURES |
| F3 | 配位数按距离判据，不读化学价/自旋 | 🟡 | 氧化态/磁性不在特征里 | 结合外部数据 | docs/FEATURES |
| F4 | `rings` 已覆盖无金属框架（完整键图回退） | ✅ | 节点数上限 >600 原子跳过并标 `truncated` | 金属框架仍走 underlying net（`ring_basis=metal-net`） | `cifkit.topology.ring_statistics`；diamond 6 元环=16/胞实测 |
| F5 | dataset 新增 **`--dedupe KEY`**（`structure_sha256`/`structure_file`/`formula`/`reduced_formula`/`label`）：保留首次出现、**失败 run 永不被去掉**、流式与物化两种模式一致、内存只占「键集合」而非行；summary 增 `dedupe`/`n_deduped` 字段 | ✅ | 仍无更复杂的清洗（电荷/自旋一致性、留一法去重、跨源同一结构判定） | `cifkit/dataset.py::dedupe_rows`、`cifkit/cli.py --dedupe`、`tests/test_dataset_dedupe.py`（6 条） |
| F6 | 数据集**已流式**（manifest 惰性遍历 + 行不驻留 + 分页读取），并在 2000 run 语料上量化：峰值内存 **3.55× 更低**（RDF 变体 4.34×），代价是墙钟 0.85×（多读一遍 JSONL） | ✅ | 极端语料（百万 run、超大行）仍未测 | `build_dataset(stream=True)`（默认）、`iter_manifests`、`api.dataset_rows` 分页；CSV 哈希与流式/传统一致 | docs/PERFORMANCE.md §10.5；tests/test_dataset.py |
| F7 | dataset 现在**有 `--jobs`**（`build_dataset(jobs=N)` / `cifkit dataset --jobs N`，顺序保持、在飞窗口 jobs×2、`max_rows_held` 仍为 1，测试保证 jsonl/csv 与串行逐字节一致）；但**实测无加速**：40 run 语料 jobs=1/2/4/8 → 13.7/14.9/13.8/12.9 s（0.92-1.06×），瓶颈是 GIL（pymatgen 解析 + 纯 Python 特征） | ✅ | 并行**正确但无效**，要吞吐请按语料分片起多个进程（或多机 fan-out） | `runs/bench_dataset_jobs.json`、`tests/test_dataset_jobs.py`（4 条：一致性/流式界/失败行/默认值） |

## G. 性能 / 并发 / 稳定性


| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| G1 | batch 并发扩展性**已实测**（8 个真实 pipeline 作业，两次独立运行）：jobs=1 约 147-149 s；jobs=2 **1.66×**；jobs=4 **2.05-2.93×**（效率 0.51-0.73）；jobs=8 **3.11-3.85×**（效率 0.39-0.48）；**jobs=16 反而更慢（2.78×）**——过订阅 | ✅ | 数字来自共享机器，是数量级证据；建议 `--jobs 4`（效率高）或 8（吞吐最高），不要 16 | `scripts/bench_batch_scale.py`（可复测，写 runs/bench_batch_scale*.json） |
| G2 | slab 缓存**已加磁盘层**（G2 关闭）：键 = 结构指纹 + 全部几何参数，存 `<cache>/slabs/<sha1>.json`（原子写 + 锁），跨进程复用；坏条目（缺字段/无法解析/键不符）一律按 **miss** 处理并重算，缓存永不破坏几何；`CIFKIT_SLAB_DISK_CACHE=0` 可关 | ✅ | 条目会累积（无容量上限/淘汰），需要时手工清理 `_cache/slabs` | `cifkit/geom/disk_cache.py`、`cifkit/geom/surface.py::make_slab`（命中顺序：进程内 LRU -> 磁盘 -> 计算）、`tests/test_slab_disk_cache.py`（6 条，含**真起子进程**验证跨进程命中） |
| G3 | `library/index.jsonl` 的并发追加走跨进程锁（`append_jsonl_locked`，持锁写入 + `fsync`，崩溃不留半行）。**且这把锁被压力测试反复捶过**（并发测试连跑 12 次）并修掉 4 个真实缺陷：① SIGKILL 的持锁者留下新 mtime 的锁 → 改按**属主探活**；② 只探活会被 **PID 复用**骗过 → 锁里记**进程身份 token**（pid+启动时刻）；③ Windows 上别人在读文件时 `unlink` 会失败，而失败被**静默吞掉**→ 产生永久僵尸锁 → 改为重试 + 失败则**记为过期**；④ Windows 的 `O_EXCL` 冲突抛的是 **EACCES 而非 EEXIST**→ 原代码只捕后者，直接崩 | ✅ | 无锁读者仍非线程安全（已写明） | `cifkit/locks.py`（`file_lock`/`_pid_alive`/`_process_token`/`_release`/`append_jsonl_locked`）、`tests/test_concurrent_index.py`（4 进程真并发）、`tests/test_lock_liveness.py`（9 条）、`tests/test_crash_recovery.py`（SIGKILL） |
| G4 | 文件锁覆盖范围：**CoRE 索引构建**用锁；**`library/index.jsonl` 追加**现在也用锁（round 42）；其余缓存文件（数据集清单、格式校验报告等）靠**原子写**（同目录 temp + `os.replace`），并发读者可能读到旧内容但**不会读到半个文件**（round 57 复核时发现 dataset manifest / verify_formats 报告 / run manifest+report 当时还是裸 `write_text`，声明超前于实现，已全部换成 `atomic_write_json`/`atomic_write_text`，声明与实现现在一致） | ✅ | 语义已明确写出：「写者原子、读者无锁」——需要强一致的场景请显式加锁 | `cifkit/locks.py`（`file_lock`/`atomic_write_text`/`atomic_write_json`/`append_jsonl_locked`）、`tests/test_concurrent_index.py`（含 stale 锁回收、锁互斥） |
| G5 | 崩溃恢复**已做真实进程杀死测试**：SIGKILL 追加者后索引**只剩完整行**（逐行可解析、结尾必有换行）；SIGKILL 原子写者后**目标文件始终是完整的旧/新一代、绝无截断**（round 58 实测：硬杀可能落在"写 tmp"与 `os.replace` 之间，此时会留下一个**完整的或部分写的** `*.tmp*` 且被杀进程无法清理——读者从不读它，契约本身只保证目标文件与"无多余的面向读者的文件"；原"绝不留临时文件"的描述与断言已在 round 58 改正）；崩溃后重跑幂等（读者按 run_id 去重） | ✅ | 测试覆盖文件级契约，不是全流程混沌测试；临时文件残留是硬杀的必然结果、不是撕裂写 | `tests/test_crash_recovery.py`（3 条，真起子进程并强杀）、`tests/test_lock_liveness.py`（5 条） |
| G6 | 行尾（EOL）会破坏按字节 sha256 钉住的文件 | ✅ | 修复前**任何干净 clone 都会红**（nets 参考哈希 FAIL、verify_demo 7/8、check_all 6/7） | `.gitattributes` 统一 `eol=lf`；`runs/**` 标 `-text`；已实测 clone 通过 | `.gitattributes`；REVIEW-ROUND11-OPT P1-b |
| G7 | 锁等待在**高负载**下过紧（8 并发构建索引时 waiter 曾 120s 超时）——现已改为「超时后先复查缓存 + 有界重试」 | ✅ | 极端负载下仍可能整体超时（此时会明确报错） | `CIFKIT_LOCK_TIMEOUT`(120s)/`CIFKIT_LOCK_TOTAL_TIMEOUT`(900s) 可调；对等进程完成后 waiter 直接复用其索引 | tests/test_lock_contention.py；cifkit/sources/core_mof.py |
| G8 | 超大结构能力已实测到 **11152 原子**（解析 25s、建键 1.0s、特征 3.3s、校验 3.4s），但 2×2×1 超胞（44608 原子）**未尝试** | 🟡 | 不要宣称支持 5 万+ 原子体系 | `runs/c2_large_mof_probe.json`；环统计 >600 原子按设计标 `truncated` | docs/PERFORMANCE.md §10.6 |
| G9 | unlink 型文件锁有**已知竞态窗口**（round 57 对抗评审）：①`O_CREAT+O_EXCL` 成功到写入 pid 之间，另一进程读到空锁体 → 误判 stale 并抢锁（双持锁）；②持锁者超过 stale 期后锁被他人抢占，其 finally `_release` 会误删他人的锁；`_release` 失败后的 "pid=0" 中性化同样可能改写他人锁 | 🟡 | 仅在「持锁 > 180s」或「极窄创建窗口」的并发场景触发；当前调用点（CoRE 索引、slab 磁盘缓存）单写者/短临界区，实测未触发 | 需要 owner-token 校验后再 unlink（`_process_token` 基础设施已在）；并发同目标写入请用进程级隔离 | runs/_council_review_b/（round 57 评审记录）；cifkit/locks.py:128-185 |
| G10 | `atomic_write_text` 的临时文件名只含 pid（不含线程 id/uuid）：**同进程多线程**并发写同一目标会互踩 tmp（round 57 对抗评审实测：两线程 build_dataset 同一 outdir 4/6 轮 PermissionError） | ✅ | 单线程主路径本就无影响 | **round 57 已修**：tmp 名加 pid+线程 id+随机后缀，`os.replace` 遇 Windows 读者持锁的有界重试（5 次×20ms 递增）；`tests/test_concurrent_index.py::test_atomic_write_survives_concurrent_thread_writers`（4 线程×20 轮全成、无 tmp 残留） | runs/_adversarial_r57/；cifkit/locks.py::atomic_write_text |
| G11 | **含 `nan`/非有限晶胞的 CIF 让进程 native 崩溃**：`features` / `geom --standardize` / `--surface` exit `0xC0000005`（`-1073741819`）、stdout 0 字节、无 traceback；`POST /rpc {"op":"features"}` 一个请求即可杀死 `serve()` 进程（round 58 对抗评审发现，P0） | ✅ | 已修：新增 `cifkit/guards.py`（`DegenerateCellError`；矩阵全有限、`|det|>1e-8`、abc 正有限、角度 (0,180)），在 features、standardize、surface（`SlabGenerator` 之前）、slab disk cache 全部前置守卫；CLI 现在 exit 1 + 可读错误 + 严格 JSON | `cifkit/guards.py`、`cifkit/features.py`、`cifkit/geom/{standardize,surface,disk_cache}.py`、`tests/test_degenerate_cell_guard.py`（21 条） |
| G12 | `scripts/verify_corpus.py` 在"加载失败的结构排在第一个"时：`by_format`/`by_bundle` 聚合整份丢失，且打印行 `row['bad_formats']` 抛 `KeyError` 崩溃（round 57 §五 提及、round 58 复现并修复） | ✅ | 已修：`check_one` 的行 key 集合完整、加载失败不再提前 return；`aggregate()` 取全行 key 并集；`format_row()` 全 `.get`；新增 `by_format_unsupported` / `by_bundle_unsupported` | `scripts/verify_corpus.py`、`tests/test_export_refusal_accounting.py`（9 条） |

## H. 技能 / 路由 / 测试覆盖


| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| H1 | 路由是 pattern+keyword+域先验，不是语义模型；罕见表述可能错 | 🟡 | 新说法可能落到 fallback | 已加 96 条 eval + 负例；持续补 eval | docs/SKILLS |
| H2 | 6 条 skipped：opt-in 4 条（MP live×2、QMOF live、metals 全量 zip）+ 环境型 2 条（Windows 只读目录不强制、symlinks 不可用） | 🟡 | 未在 CI 覆盖 | 有 key/镜像/env 时打开 | tests |
| H3a | 云端验收管线**已跑通**：Bohrium `batchjob`（光子付费）提交 → 调度 → 运行 → 取回；**NWChem 7.2.2 接受并跑完**本项目写的最小自洽算例（`Total times` 输出、exit 0、作业 succeeded，237 s / 5 光子） | ✅ | 只覆盖 NWChem；VASP/QE/CP2K/ORCA 等本机与云端镜像都没有 | `runs/cloud_h3/CLOUD-LOG.md`（5 个作业的 jobId/耗时/光子）、`runs/cloud_h3/artifacts_cp2k/acceptance_result.json`、`scripts/cloud_h3_submit.py --bohr-status` |
| H4 | CI workflow **仍未在真实 runner 上跑过**（本机只有 Windows）；但已加**定义漂移门禁**：`scripts/check_ci.py` 解析 workflow，校验 10 项（两个 job、3 OS × 2 Python、3.11 在列、LF 设置、引用的脚本都存在、**每个 gate 脚本都能从 CI 到达**、每个非 CI 脚本都有明确 on-demand 归类、import 冒烟指向真实模块） | 🟡 | 只证明「定义与仓库一致」，不证明其它 OS 能跑 | `scripts/check_ci.py`（可 `--run` 在本机执行可移植步骤）、`tests/test_check_ci.py`（5 条，含注入缺失脚本的负例）、`release_check` 门禁；**同时把 check_bundles/check_portability 接进 check_all（现 13 组）**，让 CI 通过 check_all 覆盖它们 |
| H5 | `check_skill` 已接入 `check_all`（8 个 cif-* 技能 errors=0） | ✅ | 仍依赖 `<agent-library>` 存在 | `--skip-agentlib` 可跳过 | check_all 第 7 组 |
| H6 | 打包/发布：**已在本机实跑验证**——`pip wheel` 构建出 70 文件的 wheel（237 KB），用 `pip install --no-deps --target` 装进干净目录后**从安装副本导入**（`is_target_copy=true`）、CLI 可跑、4 个 contract schema 与 6 个拓扑参考都在包内且全部 verify 通过 | ✅ | 仍缺的是 PyPI 上传与多平台测试（CI 定义已有） | `scripts/check_package.py`（构建→安装→导入→CLI→拓扑，写 runs/check_package.json）；`release_check --package`；`tests/test_packaging.py`（5 条，含 package-data 声明回归） |
| H7 | **验收脚本把"写入方正确拒绝"记成坏格式**：round 57 的 LAMMPS tilt 守卫对已跟踪夹具 `tests/data/sod_zn_mof.cif` 抛 `ValueError`，`verify_corpus` 记为 `bad` → `check_all` / `release_check` / `test_check_all_report` 连锁变红（HEAD 自带回归，round 58 发现） | ✅ | 已修：新增 `cifkit/export/refusals.py`（`ExportRefusalError` + `CellNotRepresentableError`），`DisorderedStructureError` / `FormatLimitError` 继承同一基类；两个校验脚本统一按 `unsupported`（带 `code: message`）记账、**不再算 bad**，同时拒绝本身没有被改成静默写错盒 | `cifkit/export/refusals.py`、`cifkit/export/{writers,disorder_guard,format_limits}.py`、`scripts/{verify_corpus,verify_formats}.py`、`tests/test_export_refusal_accounting.py` |

## I. 环境 / 网络 / 依赖获取


> 自检工具：`scripts/verify_formats.py`（31 格式独立回读）、`scripts/adversarial_check.py`（18 项破坏性检查）、`scripts/check_all.py [--fast] [--adversarial]`（**13 组**健康检查，含 `check_skill cif-*`；可选 `--adversarial` 为第 14 组）。
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
| J2 | 超时从「尽力而为」升级为**协作式取消**：新增 `cifkit/cancel.py`（线程安全的 `CancellationToken` + 线程本地 `checkpoint()`），`GuardedService` 每个请求持一个 token，**超时即 `token.cancel("timeout")`**；`features_many`（含 `jobs<=1` 的顺序路径）在每个 item 前后调用 checkpoint，被取消时抛 `Cancelled` 而不是把整批跑完 | 🟡 | 仍**杀不掉**正在算的那一个 item（CPython 无法安全终止线程）；只有显式调 checkpoint 的循环可取消，未加 checkpoint 的重计算仍跑完 | `cifkit/cancel.py`、`cifkit/platform.py::GuardedService._run`、`cifkit/features.py::features_many`、`tests/test_cancellation.py`（11 条，含「取消后批处理真的提前停止」与「超时后 worker 未跑完循环」） |
| J3 | `handle()` 吞掉异常（防 traceback 外泄） | 🟡 | 线上排障只能看日志 | 复现时直接调 `api.*` 拿真实异常 | `cifkit/service.py` |
| J4 | 分页早就有（只读 offset+limit 行）；**现在还有真正的流式响应**：`cifkit.api.iter_dataset_rows`（生成器，逐行读 JSONL，内存有界）与 `GET /stream/dataset_rows?dir=…&offset=&limit=`，用 **`Transfer-Encoding: chunked`** 输出 `application/x-ndjson`，客户端断开即停止拉取；**流式路由复用 `/rpc` 的策略检查**（路径沙箱/租户/上限），不是沙箱后门 | ✅ | 只对 `dataset_rows` 做流式；其它 op 仍是单次 JSON 响应 | `cifkit/api.py::iter_dataset_rows`/`stream_dataset_rows_ndjson`、`cifkit/service.py`（`/stream/dataset_rows`）、`tests/test_streaming_rows.py`（10 条，含**逐行计数证明只为 2 行页读 3 行**、沙箱拒绝、`Content-Type` 断言） |
| J5 | 有背压与并发上限（`max_concurrency` + `queue_size` -> 503 `busy`），**现在有实测压力曲线**（`scripts/load_service.py`，闭环客户端 + 真结构 `validate`）：并发 1/2/4/8 时吞吐 **~16.5 rps 几乎不变**（1.0 / 0.996 / 0.913 / 0.897），p50 从 58 ms 线性涨到 268 ms；把 `queue_size` 收到 4 后在并发 16 处**出现拒绝膝点**（790,718 次 `busy`） | 🟡 | 数字是**本机、单进程、GIL 限制**下的，不是集群容量；拒绝过快反而抢走已接纳请求的 CPU（并发 16 时成功吞吐掉到 4.5 rps），说明队列长度需要按客户端重试策略调 | `scripts/load_service.py`、`runs/service_load.json`、`runs/service_load_saturated.json`、`tests/test_service_load.py`（7 条，含 CPU-bound stub 证明线程不会凭空造吞吐） |
| J6 | 1.0 是首个冻结版本，无 LTS 承诺 | 🟡 | 次版本兼容、主版本可能破坏 | 平台按 `api_version` 分支；schema 文件可做网关校验 | docs/API.md §5 |
| J7 | `structure` 参数接受 pymatgen 对象 → RPC 场景不可用 | 🟡 | HTTP 调用者只能用 `path`/`cif_text` | 平台把结构序列化成 CIF 文本传入 | `cifkit/contract.py` ops.json |
| J8 | 已有**路径沙箱**（read_roots/write_roots，resolve 后包含性检查，挡 `..` 与逃逸符号链接） | ✅ | 进程内检查（TOCTOU 非绝对；跨盘符按拒绝处理） | `Policy(read_roots=..., write_roots=...)` → 403 `forbidden-path`；另限 `max_bytes`/`max_atoms`/`max_inputs` | cifkit/platform.py；tests/test_platform.py |
| J12 | `--ingest` 以 **outdir 目录名**为唯一入库 key：两个不同 run 的 outdir 基名相同（如都叫 `demo`）时，后入库者覆盖 `library/<name>/` 内同名产物，index.jsonl 出现两条指向同一目录的记录（round 57 对抗评审实测） | 🟡 | 同名 run 会静默互相覆盖；不同名不受影响 | 冲突时加时间戳/序号后缀或显式 supersede（待修）；暂避免用相同 `--outdir` 基名重复 ingest | runs/_council_review_b/（round 57 评审记录）；cifkit/provenance.py:132-155 |
| J13 | `fetch` **0 命中**的退出码口径漂移：无 `--json` exit 1、带 `--json` exit 0（两分支必有一错，round 57 对抗评审实测） | 🟡 | 调用方按退出码决定重试/放弃时会误判 | 统一口径并写入文档（待修）；暂以 stdout 内容为准 | runs/_council_review_b/（round 57 评审记录）；cifkit/cli.py:582-624 |
| J14 | `/stream/dataset_rows` 的**运行时错误路径**发双重 HTTP 响应：先发 `200 + Transfer-Encoding: chunked` 头，再把一整个 `HTTP/1.0 404` 响应嵌进 chunked body（且无 `0\r\n\r\n` 终止符）→ 标准客户端 `IncompleteRead`，拿不到那个 404 JSON（round 58 对抗评审发现） | ✅ | 已修：200 头推迟到首个 chunk 成功产生之后，首 chunk 前失败直接走 `_send`；原始 socket 级回归测试证明只出现一个响应 | `cifkit/service.py`、`tests/test_stream_error_path.py` |
| J15 | CLI `--json` 与 `cifkit.api` 的返回值可含**裸 `NaN`**（RFC 8259 禁止；`validate` 畸形晶胞 → `"abc":[NaN,NaN,5.0]`），与 README「api 返回值 JSON 可序列化」冲突（round 58 对抗评审发现） | ✅ | 已修：CLI/API 输出统一清洗非有限浮点；`validate` 对非有限晶胞仍 exit 1 且 stdout 可被严格 JSON 解析 | `cifkit/cli.py`、`cifkit/api.py`、`tests/test_cli_json_strictness.py` |
| J16 | `pipeline --spec` 的**未知键静默丢弃**：`supercel` 拼写错误会让行为悄悄退回默认值（round 57 §五 提及、round 58 修复） | ✅ | 已修：保留原始 JSON 到 `spec_inputs` 的同时，对未知键发明确警告（`--json` 下进结果对象、不污染 stdout）；回归测试钉住"有警告且不改行为" | `cifkit/cli.py`、`tests/test_cli_json_strictness.py` |

## L. 许可 / 商用合规


| # | 局限 | 状态 | 影响 | 规避 / 说明 | 证据 |
|---|---|---|---|---|---|
| J9 | CPU 密集 op 的并发扩展性差（GIL）：**实测**4 线程吞吐 0.913x（并发 4 时 p50 从 58 ms 涨到 259 ms）；并发 8 时 0.897x。该服务适合「多而小」的请求，不适合并行大计算 | 🟡 | 重计算应放进程池/工作队列（`GuardedService` 用的是线程池，所以 GIL 是硬顶） | `scripts/load_service.py`、`runs/service_load.json`、`tests/test_perf_gate.py` |
| J10 | 性能回归门禁存在，但**容差很宽**（时间 0.5×、内存 2.0×）且基线是**单机**的；在共享/高负载机器上无法检测中小幅度的性能退化 | 🟡 | 只能抓数量级回归 | `scripts/perf_gate.py`（多次取中位数 + warm-up + 抖动区间），`release_check --perf` opt-in；基线换机器必须重录 | runs/perf_baseline.json；tests/test_perf_gate.py |
| K9 | 导出产物**曾**泄露宿主绝对路径（NWChem `permanent_dir`，ASE 默认行为）；已修并有门禁，但同类问题仍可能出在**新增**格式上 | ✅ | 新增格式时门禁会自动扫到 | `scripts/check_portability.py`（31 格式全扫，二进制跳过）+ `tests/test_portability.py`；云端跑作业时发现 | runs/portability.json |
| H3b | **本仓导出的 NWChem 模板**未在真实软件中跑完 → **已关闭**：Bohrium 作业 `774a6dd5…` 用 cifkit 生成的 16 原子周期胞输入，在 NWChem 7.2.2 里 **exit 0、打印 `Total times`**（cpu 1020.8 s / wall 1031.8 s，作业 succeeded，1064 s / 4 光子） | ✅ | 只证明 NWChem 这一条路径；大体系仍受内存约束（见 H3c） | `runs/cloud_h3/artifacts_ours_v9/our_template_result.json`、`CLOUD-LOG.md`；导出器 `_adapt_nwchem_periodicity()`（模式来自真实程序实验，不是文档猜测） |
| H3c | 12 个模板格式里只有少数被真实二进制接受；**round 55 把证据扩到一批结构**：**LAMMPS 5/5**、**GROMACS 4/4** 唯一用例被真实二进制接受，且**报告原子数与文件原子数逐一相等**（132/82/16/86/138）；NWChem 模板完整跑通（verified）。**blocked 证据**：ABINIT（打包 9.10 拒绝运行）、CP2K（镜像无包）、QE（上游 SIGABRT）、ORCA（Debian 的 `orca` 包是 GNOME 屏幕阅读器）。镜像可用性：abinit 9.10.4 / elk-lapw 9.2.12 / qe 6.7 / lammps 20240207 / gromacs 2023.3 / nwchem 7.2.2 | 🟡 | 其余 8 个格式仍只有自研解析；接受⾃文件 ≠ 能算出物理量（LAMMPS 用 `pair_style zero`）| `cloud_h3/run_acceptance_batch.py`、`scripts/collect_acceptance.py`（去重 + 定量比对）、`tests/test_acceptance_matrix.py`（5 条）、`tests/test_acceptance_batch_logic.py`（9 条）、证据 `runs/cloud_h3/acceptance_matrix.json`、`runs/cloud_h3/batch_*` |
| J11 | 云端 GPU：已验证**8 作业并发提交 + 3 卡同时运行**、**单机 2 卡**（缩放效率 84.2%）；**单机 8 卡（c128_m512_8×L20）三次尝试全部 `scheduling_timeout`**（45/25/25 min 等待窗口，均 0 光子 0 算力） | 🟡 | 同构并行可用，但必须 ~2.5× 超额提交并容忍重试；单机 8 卡在这个账号的可用时段内**始终未排上**，只能按「该 SKU 基本不可得」来规划 | `scripts/cloud_gpu_fanout.py`、`cloud_gpu/gpu_bench.py`（多卡逐卡+并发聚合，已就绪）；`docs/CLOUD-GPU.md`；证据 `runs/cloud_gpu/fanout_8x4090*.json`、`multi2l20_v2/`、三次 8 卡尝试的 `scheduling_timeout` 记录 |
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
