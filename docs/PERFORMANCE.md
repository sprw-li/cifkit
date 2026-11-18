# 批量与性能（`cifkit batch` / slab 缓存）

> 本机实测（Windows，Python 3.14 venv；AFLOW/COD 网络缓存已热）。数字是**墙钟时间**，用于对比，
> 不是承诺；换机器/冷缓存会变。复现命令见每节末尾。

## 1. `cifkit batch`：多结构并发

```powershell
# 3 条 demo 请求（sod MOF 全流程：下载→补氢→超胞→(111) 切面→真空→导出）
& $PY -m cifkit batch --spec "<demo>" --spec "<demo>" --spec "<demo>" --jobs 1 --outdir runs\batch1
& $PY -m cifkit batch --spec "<demo>" --spec "<demo>" --spec "<demo>" --jobs 3 --outdir runs\batch3
```

| 并发度 | 3 次运行总墙钟 | 单次耗时 | 说明 |
|---|---|---|---|
| `--jobs 1`（串行） | **41.0 s** | 13.2 / 13.7 / 14.0 s | 每次一个子进程，串行 |
| `--jobs 3` | **14.8 s** | 14.6 / 14.6 / 14.8 s | 3 个 run 同时跑，**2.8×** 加速 |

- 每条 run 用**独立子进程**（`python -m cifkit pipeline ... --json`）→ 无 GIL 限制、单条崩溃不影响其它；
  批处理总入口写 `batch_manifest.json`（每 run 的 exit code、秒数、stderr 尾部、摘要）。
- 独立评审（Round 7）用 3 条**轻量本地 spec**（单 run ~5–7 s，固定启动开销占比大）测得：
  `--jobs 1` 16.98 s → `--jobs 3` 8.87 s（**1.91×**）；与完整 demo 的 2.8× 方向一致，差在固定开销。
- 一条 run 各写自己的 `outdir`，互不共享可变状态；缓存（CoRE/AFLOW/COD）由各源自己保证并发安全
  （见 `docs/ROBUSTNESS.md`）。
- 失败语义：`batch` 全部成功 exit 0；任一失败 exit 1 但**其余 run 仍完成**并进入 manifest
  （`ok/jobs` + 每条 `returncode`）。

复现：

```powershell
$PY = '<repo>\.venv\Scripts\python.exe'
$spec = '帮我下载典型的RCSR为sod的mof，需要碳上补充氢，创建一个2x2x1的超胞，沿(111)面切出表面，并加上15A的真空层，导出为计算化学软件使用的格式'
Measure-Command { & $PY -m cifkit batch --spec $spec --spec $spec --spec $spec --jobs 1 --outdir runs\_bench_b1 --json }
Measure-Command { & $PY -m cifkit batch --spec $spec --spec $spec --spec $spec --jobs 3 --outdir runs\_bench_b3 --json }
```

## 2. slab 生成缓存（`cifkit.geom.make_slab`）

切一次 slab 要枚举所有 termination 并算配位数；500+ 原子常规胞一次约 2 s。`make_slab` 现在按
**结构 hash + 全部几何参数**做进程内缓存（LRU，24 条）：

| 情况 | 墙钟 | 说明 |
|---|---|---|
| 首次 `make_slab(zif8, (1,1,1), thickness=10, vacuum=15)` | **2.12 s** | miss，完整枚举 |
| 相同参数第二次 | **0.014 s** | hit，**~150×** 加速（返回副本） |

- 返回的是 **copy**，调用方改动不会污染缓存；`info["cache"]` 标 `hit`/`miss`。
- 键包含结构（CIF 文本 sha1）、hkl、thickness、vacuum、termination、reps、frame；任一不同即 miss。
- 工具函数：`from cifkit.geom.surface import slab_cache_info, clear_slab_cache`（测试/基准用）。
- 典型收益：E_surf 扫描同一 bulk 的多个 termination/vacuum、批量表面能套件（如 usecases/u3_metals）。

## 3. 其它已做的低风险优化

- `cifkit fetch --json --outdir`：状态行写 stderr，不破坏 JSON（见 REVIEW-ROUND4/5）。
- CoRE 索引 `index.json` 读取路径 ~0.09 s（8300 条，JSON 加载）；只在 zip/CSV 变更时重建。
- AFLOW CIF 缓存在 `_cache/aflow/`，重复 fetch 不重新下载。

## 4. 未做/未验证

- 未在 Linux/macOS 上测；未对 87 元素全量 `metals` 做端到端计时（子集 Fe/Cu/Mg 3.6 s，见 WP1 报告）。
- `batch` 的并发上限取决于机器核心数与网络；没有做 N=8/16 的扩展性曲线。
- slab 缓存是**进程内 + 磁盘**两层：进程内 LRU → 磁盘（`_cache/slabs`，键 = 结构指纹 + 全部几何参数，
  round 47 落盘）→ 重算；坏条目一律按 miss 处理（见 LIMITATIONS G2 与 `cifkit/geom/disk_cache.py`）。

## 10. 嵌入接口基准（round 15，`scripts/bench_api.py`）

> **环境与免责**：单机 Windows / Python 3.14.8 / 16 核，
> **测量时机器有其它负载**（纯 Python 对照实验只有 `0.78x`（线程）
> 与 `0.84x`（进程）——连对照实验都上不去，说明机器饱和）。
> 这些数字只表示量级，**不是性能承诺**，也没有 CI 阈值。

### 10.1 吞吐（ZIF-8，138 原子）

| 操作 | 时间 | 吞吐 |
|---|---|---|
| `features`（不含 RDF） | 0.0209 s | **47.88 /s** |
| `features`（含 RDF，50 bins） | 0.1952 s | **5.12 /s** |
| `features` 冷启动（首次 import） | 0.6829 s | — |
| `convert` → vasp+xyz（落盘） | 0.0621 s | **16.1 /s** |
| `convert` → 内存返回 | 0.0422 s | **23.69 /s** |

RDF 是主要成本（约 5–10×）；`convert` 落盘与内存返回几乎同价（写入不是瓶颈）。

### 10.2 并行：`jobs>1` **不是加速承诺**（诚实结论）

| 场景 | 串行 | jobs=4 线程 | jobs=4 进程 |
|---|---|---|---|
| 8× ZIF-8 `features_many`(无 RDF) | 0.1602 s | 0.1829 s（**0.88x**） | 1.392 s（**0.12x**） |

原因：pymatgen 大量工作持 GIL，加上单项工作量小、Windows 进程启动 ~0.3–0.5 s。
因此 `features_many(executor=...)` 默认用线程，`process` 仅在调用方确信批足够长时可选
（见 `cifkit/features.py` 的 docstring）。**不要**把 `--jobs` 当成提速手段宣传。

### 10.3 数据集流式（F6）：结构保证 vs 实测内存

| 语料 | 模式 | `max_rows_held` | 峰值内存（tracemalloc，含预热） |
|---|---|---|---|
| 8× ZIF-8（无 RDF） | stream | **1** | 1.152 MiB |
| 8× ZIF-8（无 RDF） | materialised | 8 | 1.347 MiB |
| 12× 2208 原子 slab（RDF） | stream | **1** | 2.058 MiB |
| 12× 2208 原子 slab（RDF） | materialised | 12 | 1.936 MiB |

**诚实解读**：
- 可验证的是**结构性质**——流式全程只持有 1 行（`max_rows_held=1`），与语料规模无关；
  而传统模式持有全部行。
- **峰值内存差异在这个规模上是噪声**（1.17× 与
  0.94×），因为峰值被 pymatgen/特征提取的
  工作内存（几 MiB）主导。要看出流式的内存收益需要**千级/更大行**的语料，本机未验证。
- 两种模式的 **CSV/JSONL 输出一致**（`tests/test_dataset.py::test_stream_and_materialised_modes_agree`）。

### 10.4 `GuardedService` 并发曲线

| workers | 请求 | 吞吐 | p50 | p95 |
|---|---|---|---|---|
| 1 | 4 | 25.33 /s | 38.6 ms | 39.7 ms |
| 2 | 8 | 27.47 /s | 69.9 ms | 76.0 ms |
| 4 | 16 | 31.0 /s | 113.2 ms | 170.2 ms |

并发提升有限（4 worker 吞吐约 1.2×）而 p50 延迟明显上升（GIL + 机器负载）——
**该服务适合"多小请求"而不是"并行大计算"**；重计算请放进程池或工作队列。

复现：`.venv\Scripts\python.exe scripts\bench_api.py [--quick]`（写 `runs/bench_api.json`）。

### 10.5 流式数据集：千级语料实测（round 19，局限 F6/F7）

前面的 8–12 run 测量看不出内存差异（峰值被 pymatgen 工作内存主导）。用合成微型结构
把语料放大到 **2000**（以及 RDF 变体 **1000**）后，差异变成硬数字：

| 语料 | 模式 | `max_rows_held` | 峰值内存 | 墙钟 |
|---|---|---|---|---|
| 2000 runs，无 RDF | stream | 1 | **3.4 MiB** | 21.229 s |
| 2000 runs，无 RDF | materialised | 2000 | 12.08 MiB | 18.048 s |
| 1000 runs，含 RDF | stream | 1 | **2.29 MiB** | 12.436 s |
| 1000 runs，含 RDF | materialised | 1000 | 9.95 MiB | 14.177 s |

- **峰值内存比（传统/流式）：3.55×（无 RDF）、4.34×（含 RDF）** —— 行越大、行数越多，收益越大；
- **墙钟代价**：0.85×（无 RDF）/ 1.14×（含 RDF），即流式多读一遍 JSONL 的固定开销（±20% 量级），**不随语料增长**；
- 两种模式的 **CSV sha256 完全相同**（`same_csv=True`），输出无差异。

复现：`.venv\Scripts\python.exe scripts\bench_stream_scale.py --runs 2000 [--rdf] [--refresh]`
（写 `runs/bench_stream_scale.json` / `_rdf.json`；语料落在 `runs/bench_scale/`，可删）。

> 口径声明：tracemalloc 峰值（含预热）；单机 Windows、机器有其它负载；这是**量级证据**，
> 不是承诺。旧文件旧结论保留在 §10.3 作为对照。

### 10.6 超大结构实测：11152 原子 Cr/F-MOF（round 20）

CoRE MOF 2024 里可用的最大 Cr 基 MOF（`SI/NCR/Chen_Manz/am9b13361_si_002_ASR_pacman.cif`，
`Cr3H6C18O13F`，**11152 原子**）逐阶段实测：

| 阶段 | 时间 | 结果 |
|---|---|---|
| 解析 CIF（pymatgen） | 25.36 s | 11152 原子 |
| 键感知 `perceive_bonds` | 1.01 s | 14144 条键、0 警告、0 有机金属 |
| 缺氢计划 `hydrogen_demand` | 0.04 s | 1536 个 H 位点 |
| `features`（无 RDF） | 2.23 s | 密度 0.705417 |
| `features --rings` | 3.34 s | `ring_basis=metal-net`、`truncated=True`（>600 原子按设计跳过） |
| `validate` | 3.43 s | ok=True, 9 项检查 |

**边界（实测结论）**：11k 原子可以解析/建键/出特征；但 **2×2×1 超胞会是
44608 原子**，切面后 >5 万，本仓**未尝试** ——
这不是"支持超大体系"的承诺。解析本身（pymatgen）就要 25.36 s，
是整条链路的瓶颈。

### 10.7 性能回归门禁（round 26/27）

`scripts/perf_gate.py`：`--record` 存本机基线，`--check` 与之比较（中位数 + warm-up + 抖动区间）。
**负载感知**：基线含一个纯 Python 控制循环；若机器比基线时慢 >2×，时间类指标记为
`inconclusive` 而非回归（内存类不受影响）。当前基线（2026-11-09 23:40）：
`features` 无 RDF 0.020 s、RDF 0.127 s、`convert` 0.039 s、`features_many`(6) 0.142 s、
流式数据集(60 run) 1.90 s / 峰值 1.164 MiB、控制循环 0.172 s。
它是 **opt-in** 门（`release_check --perf`），不阻塞默认发布流程。

## slab 磁盘缓存（round 47）

进程内 LRU 只帮单进程；批量扫参/多 worker 场景下重复的 slab 会被反复计算。
现在第二层是磁盘缓存（`_cache/slabs`，可用 `CIFKIT_CACHE` 指定位置），
跨进程复用，坏条目自动忽略；`CIFKIT_SLAB_DISK_CACHE=0` 关闭。
