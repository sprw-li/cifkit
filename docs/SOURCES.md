# 数据源与拓扑判定（cifkit.sources / cifkit.topology）

> Owner：`sources-topology`。接口冻结见 `docs/DESIGN.md` §6/§6b；本文件记录实现细节、
> 证据等级与离线/联网行为。

## 1. 数据源一览

| source | 类 | 用途 | 元数据 | 网络 / key |
|---|---|---|---|---|
| `core-mof` | `sources/core_mof.py` | **MOF 首选**：CoRE MOF 2024，按拓扑 / 常用名检索 | 有 RCSR 拓扑列（仅 ASR） | 离线（zip 已缓存） |
| `cod` | `sources/cod.py` | 实验晶体兜底：Crystallography Open Database | **无拓扑列** | 网络（下载后缓存） |
| `materials-project` | `sources/materials_project.py` | DFT 结构：按 `mp-<id>` / 化学式检索 | 无 RCSR 拓扑列；有 material_id/spacegroup | 网络 + **需要 `MP_API_KEY`** |
| `aflow` | `sources/aflow.py` | 无机/合金计算结构：AFLUX 检索 + aflowlib CIF | **无拓扑列** | 网络，免 key |
| `local` | `sources/local.py` | 用户本地 `.cif` / 测试 fixture | 无 | 无 |
| `qmof` | `sources/qmof.py` | QMOF（DFT 标注 MOF；**本地镜像读取**） | 无 RCSR 拓扑列 | 读 `$CIFKIT_QMOF_DIR`；官方 figshare/GitHub 本环境不可达（未 live 实测） |

`available_sources()` 返回 `{name: description}`；`source_status()` 返回结构化清单
（含 `requires_auth` / `auth_hint` / 缓存状态），CLI：`python -m cifkit sources [--probe] [--json]`。
`get_source(name)` 支持别名（`core_mof` / `mp` / `aflowlib` / `file` …）并返回**单例**。
`pick_source(spec)` 是 `auto` 规则入口：`mp-<digits>` → materials-project；
`aflow:`/`AFLOWDATA/` → aflow；7 位数字 → cod；`.cif` → local；有 **topology** → core-mof；
只有名称时：**化学式**（GaN/NaCl/Fe2O3，能被 `Composition` 解析）→ aflow，
**MOF 名称**（ZIF-8/UiO-66/HKUST-1，解析失败）→ core-mof。

### CoRE MOF 2024 缓存

```text
_cache/core-mof-2024/
  CoREMOF2024DB.zip           # 44 MB，8300 个 CIF
    SI/CR/{ASR,FSR,Ion}/      # computation-ready（CR）
    SI/NCR/{both,Chen_Manz,mofchecker,occupancy}/   # 原始 NCR
  ASR_data_SI_20250204.csv    # 1372 行 ASR 元数据（topology(AllNodes)/SingleNodes/DOI/natoms…）
  NCR_ASR_SI.xlsx             # NCR 质检标记（Chen_Manz / mofchecker）
  index.json                  # 本模块生成的索引（约 4 MB）
  extracted/                  # fetch 时从 zip 解出的 CIF（按 sha256 去重）
```

数据集信息（DataCite 元数据核实）：**CoRE MOF 2024 v1.1**，
DOI `10.5281/zenodo.15055758`，Zenodo record `15055758`，license **CC-BY-4.0**。
`ASR_data_SI_20250204.csv` 对应 v1.1（2025-03）。

### 索引（`index.json`）

- 每个 zip 内 CIF 只读**头部 6144 字节**（`_chemical_formula_sum` + 晶胞参数），
  8300 个文件约 1–2 s；之后 `search/fetch` 全部走 JSON，不再解压。
- 条目字段：`variant`（computation-ready/raw）、`section`、`subset`、`refcode`、`coreid`、
  `doi`、`topology_allnodes`、`topology_singlenodes`、`metal_types`、`formula`、
  `heavy_key`（去 H、按金属数归一化的重原子组成指纹）、`natoms`、`h_count`、`abc`、
  `angles`、`number`、`ncr_flags`。
- 自动失效：zip / CSV 的 size/mtime 变化后重新建索引；损坏索引自动重建。
- 手动重建：`python -c "from cifkit.sources.core_mof import build_index; print(build_index(rebuild=True)['n_entries'])"`
  （CLI 命令面冻结，未加 `--rebuild` 参数）。

索引统计（当前缓存）：`n_entries=8300`，`n_computation_ready=2664`，`n_raw=5636`；
`topology(AllNodes)=='sod'` 的 ASR 记录 7 条。

## 2. 证据等级（诚实性规则，DESIGN §5）

`StructureRecord.topology_evidence` / `topology.verify(...)["evidence"]` 只允许：

| evidence | 含义 | 触发条件 |
|---|---|---|
| `metadata` | 数据库元数据标注 | CR/ASR 记录的 `topology(AllNodes)`（或 SingleNodes）列；或结构指纹与 CoRE ASR labeled 记录完全一致 |
| `verified` | **结构比对通过** | `topology.verify` 用 underlying net 签名与同拓扑参考结构比对全部一致 |
| `curated` | 文献关联、未经结构核实 | NCR 原始 CIF 的文献关联候选，且结构比对因参考缺失无法完成；会写清依据 |
| `mismatch` | 明确冲突 | 元数据标注不符，或结构签名不一致 |
| `unknown` | 无法判定 | 无金属节点（主族/纯有机）、无参考签名、解析失败、稠密 net 预算耗尽 |

规则：

- **绝不**把"论文/俗称是 ZIF-8"当拓扑证据；NCR 原始 CIF 没有拓扑列，必须
  `topology.verify` 结构比对后才标 `verified`。
- `ok=True` 只允许配 `metadata` / `verified`；`unknown` 永远不会返回 True。
- 报告/记录里 metadata 与 verified 不混用。

## 3. `search(SourceQuery)` / `fetch(record)`

### `prefer_raw` 语义（demo 依赖）

`spec.repair_h=True`（"需要碳上补充氢"）→ `SourceQuery(prefer_raw=True)`：

- 候选 = **与 sod ASR 记录重原子组成指纹一致的 NCR 原始结构** ∪
  `RAW_EXEMPLARS` 里的人工文献样例（目前只有 `sod → ja204757x_si_002`，附 DOI
  与匹配依据）。
- 候选按 `(H 数升序, ASR 优先于 FSR, curated 优先, 路径)` 稳定排序，**同一查询第一个
  结果可复现**：`SI/NCR/both/ja204757x_si_002_ASR_pacman.cif`
  （Zn12C96N48、156 原子、0 H、cubic a=17.029、DOI `10.1021/ja204757x`）。
- 每条候选都先 `topology.verify`；`verified` 的才返回（并写数值到 notes /
  `extra["topology_verification"]`）。参考不可用时，curated 文献样例降级为
  `curated`；其余跳过。
- `record.variant='raw'`；`h_count` 用真实解析结果覆盖；`h_expected` 由"同组成 H 完整
  的 CoRE ASR 参考按 H/金属比缩放"估计（ZIF-8：60/6×12 = **120**），notes 明确标
  "估计值，非实测"。

`prefer_raw=False`（不补氢）→ 返回 CoRE ASR 里 H 完整的计算就绪结构，证据
`metadata`（sod 首个 = `2015[Zn][sod]3[ASR]1`，Zn6H60C48N24，138 原子）。

### 常用名检索

CoRE 元数据没有通用名称列（1372 行里只有 1 行 `name`），因此 `structure_name`
走两条路：索引里的 `name`/refcode/coreid 匹配；以及 `NAME_HINTS` **curated 别名表**
（ZIF-8/ZIF-67/ZIF-4/MOF-5/HKUST-1/UiO-66/MOF-801），别名只用于**筛候选**，拓扑证据
仍来自数据集拓扑列或结构比对。别名指定的金属在该拓扑下没有记录时回退到该拓扑典型
结构并在 notes 说明。

### 候选核实上限

原始结构每条都要解析 + 做结构比对，为控制检索耗时，`search` 最多核实 6 条候选
（排序保证目标结构在最前面）；`resolve` 的查询 `limit=3`。

### `fetch` 的 provenance

```json
{
  "source": "core-mof",
  "record_id": "core-mof:SI/NCR/both/ja204757x_si_002_ASR_pacman.cif",
  "zip_path": "SI/NCR/both/ja204757x_si_002_ASR_pacman.cif",
  "zip_sha256": "...", "zip_size": 44022768,
  "dataset": "CoRE MOF 2024", "dataset_version": "1.1 (2025-03)",
  "dataset_doi": "10.5281/zenodo.15055758",
  "dataset_url": "https://zenodo.org/records/15055758",
  "url": "https://zenodo.org/records/15055758",
  "file_url": "https://zenodo.org/records/15055758/files/CoREMOF2024DB.zip?download=1",
  "license": "CC-BY-4.0",
  "doi": "10.1021/ja204757x",
  "sha256": "<解出 CIF 的 sha256>", "cif_sha256": "...",
  "cif_path": "_cache/core-mof-2024/extracted/....cif",
  "cache_reused": true, "fetched_at": "...",
  "topology": "sod", "topology_evidence": "verified",
  "h_count": 0, "h_expected": 120.0
}
```

`pipeline.py` 的 resolve 步骤依赖 `provenance["cif_path"]`（存在时直接复制为
`raw.cif`），报告依赖 `url/sha256/doi`。

## 4. `resolve(spec)` 语义

数据源选择（`spec.source == "auto"` 时）：

1. `structure_id` 以 `.cif/.mmcif/.mcif` 结尾 → `local`；
2. `structure_id` 为 7 位数字 → `cod`；
3. 有 `topology` 或 `structure_name` → `core-mof`；
4. 都没有 → `ValueError`（说明缺什么）。

`prefer_raw = bool(spec.repair_h)`。多候选时：带 `typical` / `prefer_raw` /
`structure_name` / `structure_id` 则按检索的确定性排序取第一条，并把候选数与选择
规则写入 `provenance["resolution"]`；否则视为多候选冲突抛 `ValueError` 并列出候选。
无命中抛 `ValueError`。

```bash
# demo 查询 → NCR 原始缺氢 ZIF-8
.venv\Scripts\python.exe -c "from cifkit.sources import resolve; from cifkit.spec import parse_request; f=resolve(parse_request('下载典型的RCSR为sod的mof，需要碳上补充氢')); print(f.record.record_id, f.record.topology_evidence, len(f.structure))"
# core-mof:SI/NCR/both/ja204757x_si_002_ASR_pacman.cif verified 156
```

## 5. `cifkit.topology` 结构比对（Round2：落盘参考 net 库 + identify）

### 5.1 落盘参考 net 库（离线可用，`cifkit/data/nets/`）

`<net>.json`（签名 + 来源溯源）+ `<net>-reference.cif`（参考结构，供审计/自验），随包分发；
`verify`/`identify` **优先**用它，不联网、不需要 CoRE zip。支持：

| net | CoRE MOF 2024 ASR 参考记录 | DOI | 原子数 | 签名要点 | 备注 |
|---|---|---|---|---|---|
| `sod` | `2015[Zn][sod]3[ASR]1` | 10.1021/ic5028256 | 138 | 4-c；CS `[4,10,20,34,52,74,100,130]` | ZIF-8，环分布完整 |
| `pcu` | `2007[Zn][pcu]3[ASR]3` | 10.1021/ja074366o | 106 | 6-c；CS `[6,18,38,66,102,146,198,258]` | Zn4O(BDC)3 = MOF-5；环统计触顶（高配位） |
| `dia` | `2017[Ni][dia]3[ASR]3` | 10.1021/jacs.6b10455 | 54 | 4-c；CS `[4,12,24,42,64,92,124,162]` | Ni 基 dia，环分布完整 |
| `fcu` | `2015[Zr][fcu]3[ASR]1` | 10.1039/C5CP03920G | 114 | 12-c；CS `[12,42,92,162,252,362,492,642]` | UiO-66（Zr6 SBU 收缩） |
| `tbo` | `2020[Cu][tbo]3[ASR]1` | 10.1021/acsami.0c18970 | 156 | 8-c；CS `[8,30,68,126,180,286,348,510]` | HKUST-1（Cu2 paddlewheel 收缩） |
| `bcu` | `2018[Zr][bcu]3[ASR]1` | 10.1021/jacs.8b07050 | 70 | 8-c；CS `[8,26,56,98,152,218,296,386]` | Zr6 基 bcu；与 tbo 靠 CS 区分 |

> 任务建议的 pcu 参考 `2015[Zn][pcu]3[ASR]2` **未采用**：经核查它不是 MOF-5，而是
> 多齿 PAH 配体 + Zn4 簇结构（`topology(AllNodes)=scn`），按 ditopic-linker 简化会产生
> 30 配位假 net。真正的 MOF-5 是 `2007[Zn][pcu]3[ASR]3` / `2011[Zn][pcu]3[ASR]8`
> （Zn8 H24 C48 O26 = 2×Zn4O(BDC)3）。

JSON 字段：`schema` / `net` / `source{record_id, refcode, coreid, doi, natoms, formula,
spacegroup}` / `cif` + `cif_sha256` / `signature` / `net_summary` / `generated_at` /
`generated_by{algorithm, command}` / `selection_reason`。

- API：`available_reference_nets()` / `load_reference(net)` / `write_net_reference(...)` /
  `regenerate_bundled_references()`。
- 重建（生成侧，需要 CoRE zip 缓存）：
  `python -c "from cifkit.topology import regenerate_bundled_references as r; print(r())"`
- 参考结构要求：CoRE 2024 ASR（computation-ready）且 `topology(AllNodes)==net`。

### underlying net（LQG，v2 含 SBU 收缩）

1. 周期成键图：`structure.get_neighbor_list(3.2 Å)` + 共价半径判据
   `d ≤ (r_i + r_j) × 1.25`（抑制芳香环次近邻假键）。
2. 金属节点：d/f 区 + 碱/碱土金属（p 区主族不算金属 → 纯主族体系走 `unknown`）。
3. **SBU/金属簇收缩**：金属–金属直接键、以及无碳无机桥连单元（μ-O/μ-OH/μ-F/μ-Cl…，
   连到 ≥2 个金属）把相关金属并成同一个 net 节点（MOF-5 的 Zn4O、UiO-66 的
   Zr6O4(OH)4、HKUST-1 的 Cu2 paddlewheel 都靠这一步得到 6/12/8 配位净）。
   含碳有机 linker 仍作为边；单齿端基不计边；孤立金属（簇）排除并记 warning；
   周期/聚合物组分跳过并记 warning。
4. 簇内整数平移量按金属–金属键/无机桥传播；有机 linker 的配位点减去簇内平移，
   得到正确的**相对平移向量**（LQG 商图 shift）。
5. 回退：SBU 收缩后没有任何有机 linker 连接（离子/无机体系，如 CsCl）时，退回 Round1
   的"逐金属节点"表示，避免把离子晶体误收缩成单节点。

### 签名（signature）

- `coordination_numbers`：金属节点配位数分布（占比，归一化）；
- `coordination_sequence`：2–8 层配位序列（周期图上 BFS，按节点平均）；
- `rings_per_node`：4/5/6/7/8 元环（平移矢量和为 0 的周期环，按节点归一化，
  与原胞/常规胞选择无关）；
- `linkers_per_metal`、`n_metal_nodes`、`n_edges`、`n_linkers`。
- 安全上限：CS 每起点 8000 状态、环枚举 20000 访问/（环大小,起点）、总 150000；
  触顶时 `rings_truncated / coordination_sequence_truncated = True`。
  `coordination_sequence_truncated=True` → `unknown`（配位序列都不可信，不能判 verified）；
  **仅环统计触顶**（高配位 fcu/tbo/bcu/pcu 的正常情况）→ verify 用
  "配位数 + 配位序列 + linker/金属比"判定，并在 `verified_on` 字段与 detail 里写清
  "环统计不完整、未参与判定"；sod/dia 的环分布完整，会额外比环。

ZIF-8 实测（原胞 6 Zn 与常规胞 12 Zn 完全一致）：
配位数 `{"4": 1.0}`；配位序列 `[4, 10, 20, 34, 52, 74, 100, 130]`；
每节点环数 `4: 0.125, 6: 0.111, 8: 0.500`（无 5/7 元环）。

### verify 顺序

1. 显式 `record` 且元数据标注一致 → `metadata`；
2. 结构与 CoRE ASR labeled 记录做化学式/原子数/晶胞指纹匹配（唯一且拓扑不冲突）
   → `metadata` / `mismatch`；CoRE 缓存不可用时该步自动跳过；
3. 参考签名：显式 `reference=`（Structure / 路径 / 提供 signature 的 dict）> **落盘
   `cifkit/data/nets/<net>.json`** > CoRE ASR 实时计算（离线时不需要第 3 项）；
4. 计算 net 签名，先比便宜的（配位数、配位序列、linker 比）→ 不符直接 `mismatch`；
5. 环统计两侧都完整时再比环分布 → 全一致 `verified`；任一侧不完整时按第 4 步
   （`verified_on` 标注）；只可能 `verified`/`mismatch`/`unknown`，不会含糊；
6. 无金属节点 / 无参考签名 → `unknown`。

结果内进程缓存（化学式+晶胞+原子坐标指纹为键），避免 `resolve` 已核实过的结构在
pipeline `verify-topology` 步骤重复解析；`topology.clear_cache()` 可清空（测试/长进程）。

### identify：最佳 net 判定

```python
identify(structure, nets=None) -> {
    "ok": bool, "net": str|None, "best_net": str|None,
    "evidence": "verified"|"unknown", "detail": str,
    "signature": {...}|None,
    "candidates": [{"net","base_ok","rings_ok","issues","record_id","doi"}...],
    "reference": {...}|None,
}
```

- 在落盘参考里逐个比较（可传 `nets=["pcu","fcu"]` 限制候选集）；先比配位数/配位序列/
  linker 比，环统计两侧完整时再比环分布。
- 唯一命中 → `ok=True, net=<net>, evidence="verified"`；都不匹配 → `ok=False,
  net=None, evidence="unknown"` 且 detail 给出"最接近 net + 差异摘要"；多个 net
  同时匹配 → `unknown`（不硬猜）；无金属节点 → `unknown`。
- 实测：`identify(MOF-5 pcu 参考结构) = pcu`、`identify(UiO-66 fcu 参考结构) = fcu`、
  `identify(zif8_raw_hfree) = sod`。
- 局限：SBU 收缩按"金属–金属键 / 无碳无机桥连原子"启发式；多齿配体（一个有机分子
  连接 >2 个金属簇）目前按成对连接展开，不能还原成独立 linker 节点（这类结构的
  AllNodes 拓扑常与 SingleNodes 不同，选参考时已避开）。

## 6. COD 适配器

- 检索：`https://www.crystallography.net/cod/result?text=<query>&format=json`；
  CIF：`https://www.crystallography.net/cod/<id>.cif`。
- `SourceQuery(structure_id="7111973")` 直接按 id 取；`structure_name` 走检索接口。
- 下载缓存 `_cache/cod/<id>.cif`；重复请求命中缓存（`cache_reused=True`）。
- 30 s 超时、3 次重试；404 → `ValueError`；网络失败 → `RuntimeError` 带 URL。
- **COD 没有拓扑元数据**：返回记录 `topology_evidence="unknown"`，拓扑必须再经
  `topology.verify` 结构比对；COD 数据为公有领域。
- `cod_available()`：socket 探测 `www.crystallography.net:443`（测试 skipif 用）。

## 7. local 适配器

- 接受 `.cif/.mmcif/.mcif`；不存在/不是 CIF → `ValueError`。
- 无元数据 → `topology_evidence="unknown"`；缺氢只做经验估计标记
  （`variant="raw"`，`h_expected` 来自 `base.expected_hydrogen`，notes 标明非实测）。
- `fetch` 计算文件 sha256，`provenance["cif_path"]` 指向原文件。

## 7b. Materials Project 适配器（需要 API key）

- 端点：`GET https://api.materialsproject.org/materials/summary/`，header `X-API-KEY`。
  key 来源：环境变量 `MP_API_KEY`（旧名 `PMG_MAPI_KEY`），申请：https://materialsproject.org/api。
  未设置 key 时 `search/fetch` 抛 `ValueError` 并给出申请与设置提示（不会 traceback/联网）。
- 检索：`structure_id="mp-149"`（可逗号分隔多个）→ `material_ids` 查询；
  `structure_name` 若是化学式（`NaCl` / `Fe2O3`）→ `formula=` 查询；不是化学式（如 `ZIF-8`）
  → 返回空（MP 无名称检索），请改用 core-mof/COD。
- `topology` 查询 → 返回空（MP 无 RCSR 拓扑列）；拓扑断言需 `topology.verify`。
- `fetch`：取 `structure` dict → pymatgen `Structure` → 生成 CIF 存
  `_cache/materials-project/<mpid>.cif`，**同时**保存 API JSON `<mpid>.mp.json`。
  provenance 同时记录 `structure_json_sha256` 与 `sha256`(CIF)，并标
  `cif_generated=True`（不是 deposited CIF）。
- 许可：记录 `Materials Project usage terms` 说明，提醒再分发/发表前自行确认；
  工具不替用户做版权判断。
- 经验：MP 是 **DFT 计算结构**（通常已含 H、无部分占据/无序），一般不需要补氢/修无序；
  要"原始缺氢/有统计原子"的 CIF 请用 CoRE NCR 或 COD。

## 7c. AFLOW 适配器（免 key）

- 检索：AFLUX `https://aflow.org/API/aflux/?species(Zn,O),nspecies(2),paging(0,N)`。
  `paging` 响应是 `{"1 of 289": {...}}` 字典（本适配器兼容 dict/list）。
  `structure_name` 必须是化学式（`ZnO`/`GaN`）；不是化学式（`ZIF-8`）→ 返回空。
- `structure_id`：接受 aflowlib **aurl/URL**（`aflowlib.duke.edu:AFLOWDATA/.../A9`
  或完整 URL）。**注意**：`aflow:<auid>` 目前无法通过公共 AFLUX 反查 aurl
  （实测 `auid(...)` 查询返回空），会抛 `ValueError` 并提示改用 aurl 或 `--name <化学式>`。
- `fetch`：`{aurl}/?files` 列文件 → 选主 CIF（排除 `_sprim/_sconv/_corner`）→
  下载。**坑**：CIF 文件名含 `:`，必须 URL-encode（`%3A`），否则服务器 404。
- **坑（已修）**：AFLOW CIF 的 `_atom_site_type_symbol` 写的是 PAW 势名（如 `potpaw_PBE.54/Fe_sv`），
  pymatgen 会误解析成 P/Po 等错误元素；`sanitize_aflow_cif()` 在解析前归一化为元素符号
  （缓存文件保留原始 CIF，provenance 记 `cif_sanitized_for_parsing`）。
- **坑（重要）**：AFLUX 的字段过滤（如 `spacegroup_relax(141*)`）并不可靠/会被忽略——
  要按空间群/原型选结构，请查全量后**客户端过滤** `spacegroup_relax`/`Pearson_symbol_relax`；
  LIB1 每个元素常有几十条多型，不能用 min(energy_atom) 直接当基态
  （实测 Sn→diamond、Hg→bcc、Ga→bct、In→hcp、Mn→hcp 都是错的）。
- 缓存 `_cache/aflow/<slug>.cif`；provenance 记录 aurl/auid/文件名的 sha256。
- 经验：AFLOW 覆盖无机/金属/合金（ICSD_WEB + LIB1/2/3），MOF 极少；无 RCSR 拓扑列；
  结构是 DFT 弛豫结果，不含有机 H 补氢需求。

## 7e. QMOF（Quantum MOF Database，本地镜像）

- **定位**：CoRE/CSD 的 DFT 标注子集（Rosen et al.），有形成能/带隙等标签；适合"结构 + DFT 标签"。
- **接入方式**：`cifkit` 的 `qmof` 适配器**只读本地镜像**，目录由 `$CIFKIT_QMOF_DIR` 指定
  （默认 `_cache/qmof/`）。期望 `qmof.csv` + `structures/*.cif`，或 `qmof_cifs.zip`
  （无 CSV 也能按 CIF 文件名检索）。
- **实测程度（诚实）**：本环境尝试过的下载路径：
  - figshare **file-level** 下载 → HTTP **403**；
  - figshare **article-level versions zip**（`ndownloader.figshare.com/articles/13147324/versions/1`）
    → 曾返回 200（约 351 MB），但多次下载被截断、后续 HEAD 返回 502（本网络不稳定），**未取得完整数据**；
  - GitHub codeload 可下载（200）但仓库只含代码/示例，**不含 QMOF 数据库**（数据在 figshare）。
  因此**没有完成 QMOF live 验证**；`scripts/bootstrap_qmof.py` 提供"下载+提取+sha256 记录"，网络可达时可用。
  适配器逻辑用本地临时镜像 + 单元测试验证（search/fetch/provenance/缺失报错），不伪造在线结果。
- **限制**：QMOF 没有 RCSR 拓扑列（`topology_evidence=unknown`），拓扑仍需 `cifkit.topology.verify`；
  许可/再分发受 CoRE/CSD 来源约束，使用前核对官方说明。
- **缺失时行为**：`cifkit sources` 显示 `local mirror missing (set CIFKIT_QMOF_DIR ...)`；
  `fetch --source qmof` 给出可操作的 `FileNotFoundError`（含申请/下载地址与目录设置方法）。

## 7d. 数据源选择决策表（经验）

| 需求 | 首选 | 备选 / 说明 |
|---|---|---|
| "典型 RCSR 拓扑（sod/pcu…）的 MOF" | **core-mof** | 拓扑列只在 ASR；要原始缺氢 CIF 用 `prefer_raw`（NCR） |
| 已知 CSD/CoRE refcode 或 MOF 常用名（ZIF-8/MOF-5…） | **core-mof** | COD 可兜底但无拓扑列 |
| 已知 `mp-<id>` / DFT 结构 / 带隙等性质 | **materials-project** | 需 key；结构已计算就绪 |
| 无机/合金/金属间化合物晶体结构 | **aflow** | 免 key；`--name` 传化学式 |
| 实验小分子/无机晶体、无拓扑要求 | **cod** | 公有领域；无拓扑列，需结构比对 |
| 用户本地文件 | **local** | 最快，无网络 |

三档拓扑证据仍然适用：只有 CoRE ASR 能直接给 `metadata`；MP/AFLOW/COD/local 一律
`unknown`，请求拓扑时由 `topology.verify` 做结构比对（`verified/mismatch/unknown`）。

```powershell
$PY = '<repo>\.venv\Scripts\python.exe'
& $PY -m cifkit sources --probe                 # 各源状态 + 可达性
& $PY -m cifkit fetch --source core-mof --topology sod --raw --limit 3
& $PY -m cifkit fetch --source cod --id 7111973 --outdir runs\cod
& $PY -m cifkit fetch --source mp --id mp-149 --outdir runs\mp      # 需 MP_API_KEY
& $PY -m cifkit fetch --source aflow --name ZnO --limit 3
& $PY -m cifkit fetch --source aflow --id "aflowlib.duke.edu:AFLOWDATA/LIB1_WEB/Zn:PAW_PBE:06Sep2000/A9" --outdir runs\aflow
```

## 8. 测试策略

- `tests/test_sources.py`：离线优先（`_cache/core-mof-2024/` 缺失自动 skip）——
  索引完整性、sod ready/raw 检索、fetch sha256、`resolve` demo 一行、本地文件、
  错误路径；COD 用例用 `cod_available()` skipif（离线不失败）。
- `tests/test_topology.py`：fixtures 离线；`zif8_raw_hfree` vs `zif8_cr_sod` 显式参考
  必须 `ok=True/evidence=verified` 且 detail/signature 有数值；CsCl 型强不匹配 →
  `mismatch`；Si/O 主族 → `unknown`；无参考拓扑 → `unknown`；CoRE 缓存存在时验证
  默认参考路径与真实 pcu 结构 mismatch。
- `tests/test_topology_nets.py`：**完全离线**（只读 `cifkit/data/nets/`，不联网、不依赖
  CoRE zip）——参考 JSON/CIF 的 sha256 与溯源字段、6 个 net 的数值签名、各参考结构
  `verify` 自身 net（关掉 metadata 指纹走结构比对）、交叉错配 mismatch
  （pcu↔sod、fcu↔pcu、tbo↔bcu、sod↔dia）、6 个 net 的 `identify`、无金属 → unknown、
  以及 `CIFKIT_CACHE` 指向空目录时的离线自验。
- `tests/test_sources_mp_aflow.py`：
  - MP：无 key 时报 `ValueError`（含申请地址）；monkeypatch `_REQUEST_JSON` 后测
    `search("mp-22862")` + `fetch`（生成 CIF、JSON sha256、`cif_generated=True`）；
    拓扑查询返回空；非法 id 报错。
  - AFLOW：`normalize_aurl` 两种格式；`_formula_query("ZnO")`；CIF 选择优先主文件；
    `_REQUEST_TEXT` mock 后测 `search(aurl)` + `fetch`（URL-encode `%3A`）；
    `topology` 查询返回空；`aflow_available()` skipif 的**联网真下载**用例。
  - CLI：`tests/test_cli.py::test_sources_command_lists_databases`、
    `test_fetch_mp_without_key_fails_clearly`。
- 运行：`.venv\Scripts\python.exe -m pytest tests/test_sources.py tests/test_topology.py tests/test_sources_mp_aflow.py -q`

## 9. 已知限制

- 结构比对以**单个金属原子**为节点，不做 SBU（如 Zr6 簇）收缩；对 AllNodes/SingleNodes
  不同的拓扑，参考结构优先取 `topology(AllNodes)` 一致的记录。
- NCR 原始 CIF 缺 H 时 linker 重原子骨架仍可识别，因此拓扑比对对缺氢是鲁棒的；
  若缺的是骨架原子则可能 `unknown`/`mismatch`。
- 主族元素（Al/Si/P/S…）与无金属体系按设计降级 `unknown`，不强行给拓扑。
- 稠密 net（高配位、多平行边）的环统计有预算上限，超限诚实降级 `unknown`。
- NCR 无 DOI 元数据列：只有 `RAW_EXEMPLARS` 收录的文献样例带 DOI，其余 raw 记录的
  `doi=None`，notes 会说明。
- **Materials Project**：需要用户自己的 API key（本工具不内置 key，也不代注册）；
  MP 的 `search` 只支持 material_id / 化学式，**不支持按名称**（"ZIF-8" 查不到）；
  MP 数据以 DFT 结构为主，拓扑需结构比对；许可条款请自行确认。
- **AFLOW**：`structure_id` 只支持 aurl/URL；`aflow:<auid>` 无法经公共 AFLUX 反查
  （实测返回空），需改传 aurl 或用化学式检索；AFLOW 无 MOF 拓扑标签、MOF 覆盖很少。
- MP/AFLOW 的 CIF 与 provenance 语义：MP 的 CIF 由 API JSON 生成（`cif_generated=True`），
  AFLOW 下载的是 aflowlib 仓库里的 CIF 文件；两者的 sha256 都单独记录，可复核。
- 许可：CoRE MOF 2024 为 CC-BY-4.0（DataCite 核实）；COD 公有领域；MP/AFLOW 只记录
  官方 usage terms 提示，**不替用户断言可再分发**。

## 网络策略与限流（round 16）

所有数据源共用 `cifkit/sources/http.py::HttpClient`（`tests/test_http_client.py`、
`tests/test_sources_http.py` 用**本地 mock 服务器**验证，不碰外网）：

| 行为 | 规则 |
|---|---|
| 可重试状态 | 408 / 425 / 429 / 500 / 502 / 503 / 504 |
| 直接失败（不重试） | 400 / 401 / 403 / 404 / 422 |
| 退避 | 指数退避（COD 1.5s 起、AFLOW 2.0s 起、MP 1.5s 起），上限 30 s，带 25% 抖动 |
| `Retry-After` | 优先采用（支持秒数与 HTTP-date），并受 `max_backoff` 上限约束 |
| 限速（pacing） | 同一 host 两次请求间隔默认 **0.25 s**；`CIFKIT_COD_MIN_INTERVAL` / `CIFKIT_AFLOW_MIN_INTERVAL` / `CIFKIT_MP_MIN_INTERVAL` 可覆盖（设 0 关闭） |
| 网络错误 | `URLError`/超时/`OSError` 同样重试并计入 `client.stats` |

验证过的场景：服务器允许 5 req/s 时，**30 次批量抓取的违规次数 = 0**；
被限流后靠退避重试最终全部成功。**未验证**：公网真实端点的实际限额
（我们不知道 COD/AFLOW/MP 的真实配额），以及长时间高并发抓取。

### COD id 写法（round 20）

`search(structure_id=...)` 现在同时接受 `7111973` 和 `cod:7111973`（也支持逗号分隔多 id）。
原因：`search()` 返回的记录 `record_id` 形如 `cod:<id>`，此前用它回查会被拒绝——
即 **search → 按 record_id 回查**这条正常用法会报错（已修并有回归测试）。

## 实时可用性（round 25，`scripts/sources_live_check.py`）

文档里的"支持某数据源"是能力描述，不等于"此刻能用"。下面的表由脚本实测生成
（2026-11-09T22:50:31+0800；证据 `runs/sources_live.json`，可随时重跑）：

| 数据源 | 状态 | 实测 | 证据 |
|---|---|---|---|
| `core-mof` | ok | 0.04 s | 8300 条索引 |
| `cod` | ok | 3.37 s | by_id: n_hits=1, first=cod:7111973; by_text: n_hits=3, first=cod:2300691 |
| `aflow` | ok | 6.31 s | n_hits=3, first=aflow:0265806d7329d48e |
| `materials-project` | needs-key | 0.31 s | set MP_API_KEY (never echoed, never written to artifacts) |
| `qmof` | not-configured | - s | 官方 figshare 下载在本环境不可达；仅有本地镜像时才算可用 |
| `local` | ok | 0.001 s | 16 个 CIF |

口径与边界：

- **`needs-key` 不是失败**：Materials Project 的 TCP 可达，但没有 `MP_API_KEY` 就不发请求
  （key 从不回显、从不写进产物）；
- **`qmof` 是 `not-configured`**：官方 figshare 下载在本环境不可达，只有本地镜像时才算可用——
  因此文档中 QMOF 一律标注"未实时验证"；
- **`cod` / `aflow` 的耗时包含限速**（同 host 默认 0.25 s/请求，见上文网络策略）；
- 该检查**不作为发布门禁**（数据库抖动不该阻塞发布），只作为信息项进入 `runs/release_check.json`；
- 结果有时效性：**表格是某一刻的快照**，不是 SLA。

重跑：

```powershell
.venv\Scripts\python.exe scripts\sources_live_check.py
.venv\Scripts\python.exe scripts\release_check.py --quick   # 信息项里会带上这次的 summary
```

## 真实限流实测（`scripts/probe_source_limits.py`）

本地 mock 覆盖了 429/503/Retry-After/退避，但**真实配额**只能实测。该脚本对每个源最多发
**10 个请求**（5 个按生产节奏 0.25 s + 5 个无间隔 burst），**不做压测**，结果写
`runs/source_limits.json`：

| 源 | 结果 | 单请求延迟（中位） | 429/503 | Retry-After |
|---|---|---|---|---|
| COD | 10/10 成功 | **2.16 s** | 无 | 未出现 |
| AFLOW | 10/10 成功 | **2.92 s** | 无 | 未出现 |

**可操作结论**：服务器延迟（2-3 s）比我们的 0.25 s 间隔大一个数量级 ——
在这类源上**调节奏参数没有意义**，要吞吐就**跨源/跨连接并列**；配额上限仍未知（我们故意不去打）。
