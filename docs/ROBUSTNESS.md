# 缓存并发与冷启动鲁棒性

> 目标：多个 `cifkit` 进程共享同一个缓存目录（`$CIFKIT_CACHE` 或 `<project>/_cache`）时不损坏数据；
> 新机器冷启动有可检查、可诊断的状态。测试见 `tests/test_robustness.py`。

## 1. 文件锁 + 原子写（`cifkit/locks.py`）

- `file_lock(path, timeout=60, stale=180)`：`O_CREAT|O_EXCL` 锁文件，超时抛 `LockTimeout`；
  锁文件超过 `stale` 秒视为崩溃残留并清理。
- `atomic_write_text/atomic_write_json`：同目录 `*.tmp<pid>` + `os.replace`，读者不会看到半截 JSON。
- 用在 **CoRE 索引构建**：`build_index()` 先无锁读缓存（快路径），miss 后取
  `index.json.lock` → **双重检查**（等锁期间别的进程可能已建好）→ 构建 → 原子替换。
- 并发实测（`tests/test_robustness.py::test_concurrent_index_build_is_safe`）：
  3 个进程同时冷建索引 → 全部 exit 0，`index.json` 解析出 **8300** 条且 `entries` 完整，
  `index.json.lock` 已清理。
- 锁是 advisory（建议性）的：只保护走 `file_lock` 的写者；读者应依赖原子替换保证一致性。

## 2. 冷启动（`scripts/bootstrap_data.py`）

```powershell
& $PY scripts\bootstrap_data.py --check    # 只检查，不下载；缺文件 exit 1
& $PY scripts\bootstrap_data.py            # 幂等下载（已有且大小合格则跳过）
& $PY scripts\bootstrap_data.py --force    # 强制重下
```

- 下载 **重试 3 次**（指数退避），先写 `.part` 再 `replace`；大小下限校验防止半截文件。
- 成功后写 `_cache/core-mof-2024/SOURCES.json`（DOI、license、每文件 size+sha256、时间）。
- `--check` 输出每个文件的 `ok/MISSING` 与大小；空缓存 exit 1（测试覆盖）。
- 下一步自检：`python -m cifkit selftest`（7 项，离线）。

## 3. 批量任务的隔离

- `batch` 每条 run 独立子进程 + 独立 `outdir`；一条失败不影响其它（manifest 记录 returncode/stderr）。
- 并发写的共享内容：
  - CoRE/AFLOW CIF 缓存：下载写各自文件；索引构建有锁+原子写；
  - `library/` 入库：每条 run 独立文件名（时间戳+slug），不会并发覆盖。
- 已知边界：多个进程同时 `--ingest` 写 `library/index.jsonl` 是追加写（单行 < PIPE_BUF），
  极端情况下顺序不确定但不会产生半行；未做跨进程行锁（记录在案）。

## 4. 离线/网络异常

- `cifkit sources --probe`：逐个探测可达性（COD/AFLOW/MP key），不联网也能看缓存状态。
- 依赖网络的步骤（COD/AFLOW 搜索、MP）失败时抛**可操作的错误**（含 URL/申请地址），
  不会静默返回空结果；本地缓存命中时不发起网络请求。
- QMOF：无本地镜像时明确报"缺镜像 + 去哪里下载 + 设置 `CIFKIT_QMOF_DIR`"（不伪造在线数据）。

## 5. 未验证

- 未在真实断网环境跑全链路（仅验证错误路径与缓存路径）。
- 未做 `SIGKILL` 中途杀进程的锁恢复测试（`stale` 清理逻辑有单元测试，但没做真实崩溃注入）。
- Windows 与 Linux 的 `os.replace`/锁语义都适用，但只在 Windows 实测。
