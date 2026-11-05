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
$PY = 'D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe'
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
- slab 缓存是**进程内**的：跨进程不共享（跨进程可考虑落盘，但会引入失效问题，暂不做）。
