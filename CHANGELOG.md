# Changelog

本文件记录 `cifkit` 面向用户可见的变化。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added

- **非有限/退化晶胞守卫**：NaN/Inf、零体积或非正晶格参数的晶胞在进入对称性分析（spglib）**之前**被
  显式拒绝并抛出类型化 `DegenerateCellError`（带可读消息与违反项），覆盖 `features`（含 `--no-rdf` /
  `--topology` / 配位路径）、`geom --standardize` 与 `geom --surface`。此前这类输入会让进程 native 崩溃
  （`0xC0000005`）、CLI 零诊断。修复后 CLI 返回非零退出码 + 可读错误，stdout 仍是严格 JSON。
- **LAMMPS 物理交叉验证入库**：新增 `cifkit/lammps_data.py`（读 LAMMPS data 文件）、
  `cifkit/lammps_reference.py`（独立 Lennard-Jones 参考能量，含周期镜像计数）、
  `scripts/check_lammps_physics.py` 与 `cloud_lj/` 已存数据集（含来源与复跑说明）。
  脚本登记为**按需运行**（需要 `cloud_lj/` 数据），产物 `runs/lammps_physics.json`。

### Fixed

- **导出：正确拒绝不再被记成"坏格式"**。LAMMPS 等物理上不可表示的晶胞（如 tilt 超过盒半长）的拒绝
  从裸 `ValueError` 升级为类型化异常；`verify_corpus` / `verify_formats` 把它计入 `unsupported`（附原因），
  不再计为 `bad`——此前一次**正确**的拒绝会让验收组连锁变红。
- **导出：裸 `--to dftb` 的产物可用性**。单格式 DFTB+ 导出不再只留下一个引用 `geo.gen` 的半成品；
  与 `--bundle dftb` 一致地产出 `geo.gen`（不可表示时显式拒绝），且 `/verify_formats/` 同时验证裸产物与 bundle。
- **导出：单文件 `convert` 的失败原因可见**。非 JSON 模式下也会打印失败格式与原因（此前只列成功项、
  exit 1 却不说为什么），批量分支行为保持不变。
- **服务：流式接口的错误路径协议损坏**。`/stream/*` 在运行时错误时不再先发 `200` 头再嵌一个 `404`
  （客户端 `IncompleteRead`）；错误以一个完整的 4xx/5xx JSON 响应返回，成功路径保证 chunked 终止符。
- **CLI/API：`--json` 不再输出裸 `NaN`/`Infinity`**（RFC 8259 非法，与"返回值 JSON 可序列化"的承诺冲突）。
  非有限浮点被清洗为 `null`（`cifkit.api.sanitize_nonfinite`，类型保持）；`cifkit validate` 对非有限晶胞仍然返回
  非零退出码、stdout 可被严格 JSON 解析。（例外：HTTP 被拒请求的 `params_echo` 诊断回显仍以字符串形式带回
  原始非有限值——它是"你发来的东西"的回执，且本身是合法 JSON。）

### Changed

- **文档与技能正文真实性清扫**（交付前，只改既成事实、不改代码行为）：
  - `README.md` 技能表从 5 个补齐到实际交付的 **8** 个 `cif-*` 技能；
  - 标准化产物的空间群措辞按实测修正：产物 `repaired.cif` / `standardized.cif` 保留输入的常规胞形
    （276 原子，整数倍守卫不翻倍），按 spglib 是 **#42 `Fmm2`（正交）**、其 conventional cell 为 552；
    **#217 `I-43m` 属于 `raw.cif`**（156 原子）——旧措辞"产物是 I-43m"不成立；
  - `docs/SKILLS.md` 的路由评测口径与实测对齐，路由示例命令补 `$env:PYTHONIOENCODING='utf-8'`
    （GBK 控制台下否则 `UnicodeEncodeError`）；
  - `cifkit surface-energy` 写入 `cif-usecases` 技能正文与 `docs/SKILLS.md` 命令对应表；
  - `cif-export` 技能正文的格式计数统一为 **31**，`png` 从未实现清单移出（仍未实现的是 `cube`）；
  - `cif-workbench` 技能正文清除损坏示例路径的 3 个 `0x08` 退格控制字符。

### Removed

- `cif-data` 技能正文删除 CLI **不存在**的 `features --jsonl` 参数说明（实测 `unrecognized arguments`，
  exit 2）；需要 JSONL 时改用 `--out` 写 CSV 自行转换，或使用 `cifkit dataset` 的 `dataset.jsonl`。

## [0.1.0] - 2026-11-17

首个交付版本：把"从数据库下载下来的裸 CIF"变成"能直接喂给 VASP / QE / CP2K / LAMMPS 的结构"。

### Added

- `cifkit pipeline`：选型下载 → 拓扑核实 → 修复（补氢 / 无序占位 / 近邻）→ 标准胞 → 超胞 → (hkl) 切面 →
  真空层 → 导出 → 校验 → `manifest.json` 一条命令跑通；`batch` 支持多结构并发（独立子进程）。
- 六个数据源：`core-mof`（CoRE MOF 2024 离线缓存 + RCSR 拓扑过滤）、`cod`、`materials-project`（需
  `MP_API_KEY`）、`aflow`（免 key）、`qmof`（本地镜像）、`local`；`sources` 选型命令与
  `topology_evidence` 四档证据（`metadata`/`verified`/`curated`/`unknown`）。
- 单步命令：`fetch`（检索下载）、`repair`（周期键感知补氢 + RDKit capping + 价态检查）、
  `geom`（标准化 / 超胞 / (hkl) slab / 实测真空 / 金属簇-SBU）、`export`+`convert`（**31 种格式** +
  **12 种**计算软件输入包，写出后尽量回读校验）、`validate`（原子数 / 近邻 / 真空 / 悬空键 / C 配位）。
- ML 与进阶：`route`（自然语言 → TaskSpec）、`features`（结构特征 CSV）、`dataset`（runs/library →
  `dataset.csv/jsonl` + 结构副本 + manifest）、`surface-energy`（slab/bulk 能量 → E_surf 算术与单位换算）、
  `teach`/`bravais`/`metals`/`fec` 四类进阶应用（`--outdir` 一键复跑）。
- 可复用接入层：`from cifkit import api`（返回值 JSON 可序列化、线程安全）、
  `from cifkit.service import handle`（RPC 处理器 + 零依赖 HTTP 服务器）、
  `cifkit/schemas/` 四个机器可读 JSON Schema（契约校验在派发前执行）。
- 诚实溯源：每次运行写 `manifest.json`（查询、来源 URL/DOI/sha256、每步耗时、校验数字、工具版本）；
  `--ingest` 额外入库 `library/`。
- 技能组交付到 `D:\agent-library\catalog\cif-*`，与引擎命令面（`docs/DESIGN.md` §6c 冻结）逐条对应。
