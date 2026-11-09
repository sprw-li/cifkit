# 嵌入接口（cifkit.api / cifkit.service）— 商用平台接入契约

> 目标：让平台把 cifkit 当**库**或**服务**复用，而不是解析 CLI 文本。
> 契约版本：`API_VERSION = 1.0`；特征表版本：`cifkit-features/v1`。
> 机器可读 schema：[cifkit/schemas/](cifkit/schemas/request.json)（`request.json` / `response.json` / `ops.json` / `feature_row.json`）。

## 1. 两种接入方式

### 1.1 进程内库（推荐，权限最松，无网络）

```python
from cifkit import api

api.capabilities()                                   # 发现：格式/输入包/数据源/版本/限制
api.features(path="a.cif", rdf=False, rings=True)    # 特征 dict
api.convert(path="a.cif", formats=["vasp","png"])    # 内存返回（text / base64），不落盘
api.convert(path="a.cif", formats=["vasp"], bundles=["qe"], outdir="out")  # 落盘
api.features_many(["a.cif","b.cif"], jobs=4)         # 批量，坏文件单独报错
api.topology(path="a.cif")                           # 识别 net（sod/pcu/dia/fcu/tbo/bcu）
api.topology(path="a.cif", net="sod")                # 核对（返回 ok/evidence）
api.validate(path="a.cif", vacuum=15.0)              # 校验报告
api.dataset(runs_dir="runs", outdir="ds", label_key="topology")
```

**保证**：返回值全部 JSON 可序列化（无 pymatgen/Path 对象）；无全局可变配置；
线程安全（`tests/test_api.py::test_api_is_thread_safe`）；错误是带 `code` 的异常。

### 1.2 服务（RPC 处理器，可挂任意框架）

```python
from cifkit.service import handle
handle({"op": "features", "params": {"path": "a.cif", "rdf": False}})
# -> {"ok": true, "op": "features", "api_version": "1.0", "elapsed_ms": 12.3, "data": {...}}
# -> {"ok": false, "op": "features", "error": {"code": "not-found", "message": "..."}, "http_status": 404}
```

挂载示例（FastAPI / Flask / Lambda / 裸 HTTP）见 `cifkit/service.py` 顶部 docstring；
自带零依赖 HTTP 服务器（仅用于本地联调/自测）：

```python
from cifkit.service import serve
server, thread = serve("127.0.0.1", 8765, background=True)
# GET /health ; POST /rpc  {"op": ..., "params": {...}}
```

## 2. 操作（ops）

| op | 必填参数 | 可选参数 | 返回 |
|---|---|---|---|
| `capabilities` | — | — | 格式/输入包/数据源/版本/limits |
| `features` | `path` \| `cif_text` \| `structure` | `rdf`(true)、`rdf_bins`(50)、`rdf_max`(8.0)、`topology`(false)、`rings`(false)、`symprec`(0.1) | 特征行（`cifkit-features/v1`） |
| `features_many` | `paths[]` | `jobs`(4)、`rdf`、`rings`、`topology` | `{n_inputs,n_ok,n_failed,rows[]}` |
| `convert` | 结构 + (`formats[]` 或 `bundles[]`) | `outdir`（省略=内存返回）、`title` | `{formats,bundles,natoms}` |
| `dataset` | `runs_dir`、`outdir` | `label_key`、`rdf`、`topology`、`features_enabled`、`copy_structures` | dataset 摘要（含 `csv_sha256`、`errors`） |
| `topology` | 结构（可选 `net`） | — | `identify` 或 `verify` 结果 |
| `validate` | 结构 | `vacuum` | `{ok,checks[],metrics}` |

结构参数三选一（`path` / `cif_text` / `structure`），**同时给多个会被拒绝**（400）。

## 3. 错误码（稳定，可直接映射 HTTP）

| code | HTTP | 触发 |
|---|---|---|
| `invalid-request` | 400 | 参数缺失/多余/类型错/取值范围错、结构无法解析、互斥参数、契约校验失败（`detail.violations` 给出 JSON 路径） |
| `unsupported-format` | 400 | 未知 `formats`/`bundles`（消息里列出可用项） |
| `not-found` | 404 | `path`/`runs_dir` 不存在 |
| `upstream-unavailable` | 502 | 数据源网络/上游失败（`cifkit.sources` 抛出时映射） |
| `internal-error` | 500 | 其它异常（**不返回 traceback**） |

契约校验在派发前执行：`{"op":"features","params":{"rdf_bins":0}}` →
`400 invalid-request` + `detail.violations = ["$.params.rdf_bins: 0 < minimum 1"]`。

## 4. 安全与多租户（平台职责）

cifkit 侧只做两件事：**不泄漏 secret**、**不越权读文件**。

- `api_key` / `token` / `password` 等字段：服务层回显参数时会**打码**（`"***"`），
  且 API 不接受 key 作为参数——key 只能通过环境变量（`MP_API_KEY` 等）注入；
- `path`/`runs_dir`/`outdir` 由调用方给出，**平台必须自己做路径白名单/沙箱**（cifkit 不做租户隔离）；
- 无遥测、无外发数据；除显式抓取数据库外不发网络请求。

平台仍需自备：鉴权、配额/限流、租户隔离、审计日志、并发上限、超时与取消、磁盘配额。
这些**不在本接口范围内**（见 [docs/LIMITATIONS.md](LIMITATIONS.md) §J）。

## 5. 版本与兼容策略

- `API_VERSION` 走主版本号：**新增可选参数/新增 op = 次版本（兼容）**；删除参数、改返回结构、
  改错误码 = 主版本（不兼容），并在本文件与 `docs/LIMITATIONS.md` 记录。
- 特征表用独立的 `feature_version`（当前 `cifkit-features/v1`）；列名变更会升版本，
  平台应按版本分支解析，不要假设列固定。
- schema 文件由 `cifkit.contract` 生成：`python -m cifkit.contract --dump`；
  `tests/test_contract.py` 保证代码与 JSON 不漂移。
- 目前是 **1.0（首个冻结版本）**：接口已可用，但尚未承诺长期支持窗口（无 LTS 政策）。

## 6. 平台接入清单

1. 选择接入方式（库 / RPC / HTTP），把 `capabilities()` 结果缓存为服务发现信息；
2. 用 `cifkit/schemas/request.json` 在网关层先挡非法请求（或直接依赖服务的契约校验）；
3. 数据落库时透传 `manifest`/`provenance` 里的 `record_id`、`doi`、`license`、`sha256`；
4. 记住输入包是**模板**：不要对用户承诺"可直接计算"（见 `docs/EXPORT.md` §6、`docs/LIMITATIONS.md` E1/E3）；
5. 许可：代码 MIT（[LICENSE](LICENSE)）；数据源逐源条款（[LICENSING.md](LICENSING.md)）；
   依赖里**不要**引入 GPL 的 openbabel（核心不需要，实测见 `scripts/verify_formats_no_gpl.py`）。

## 7. 已知限制（接口层）

- 无异步/队列：长任务（大结构 RDF、87 元素批量）会占满调用线程；平台应放工作队列；
- 无线程池/进程池上限控制；`features_many(jobs=N)` 的 N 由调用方负责；
- 无请求级超时/取消（Python 侧无法安全中断 pymatgen 计算）；
- 无流式响应（大结果一次性 JSON）；无分页；
- `handle()` 会捕获所有异常（避免 traceback 外泄），**调试时需要看日志/直接调 `api.*`**；
- 未做压力/并发压测，也未做多租户隔离测试。
