---
name: cif-fetch
description: >-
  按拓扑/名称/id 从结构数据库检索并取回 CIF：CoRE MOF 2024（离线缓存、RCSR 拓扑过滤）优先，
  COD / Materials Project（需 MP_API_KEY）/ AFLOW（免 key）按需切换，本地文件直读；
  附带来源 DOI、sha256 和 topology_evidence 证据等级。
---

# cif-fetch（数据库选型 + 下载）

把“要哪个结构”变成一条可复核的 `StructureRecord`：来源、变体（computation-ready / raw）、
原子数、H 数、DOI、sha256、拓扑证据。下载之后才轮到修复/几何/导出。

**六类数据源**：`core-mof`（MOF + RCSR 拓扑，离线）、`cod`（实验晶体，公有领域）、
`materials-project`（DFT 结构，需 `MP_API_KEY`）、`aflow`（无机/合金，免 key）、
`qmof`（QMOF，DFT 标注 MOF；**只读本地镜像** `$CIFKIT_QMOF_DIR`，官方 figshare/GitHub 在本环境不可达）、
`local`（本地文件）。
拓扑证据只有 CoRE 的 ASR 能直接给 `metadata`；其余源一律 `unknown`，需要拓扑断言时由
`cifkit.topology.verify` 做结构比对。

## 何时使用

- 用户说“下载/找/取 一个 sod 的 MOF”“要典型的 ZIF-8”“从 CoRE MOF 里挑一个”；
- 要给后续步骤一个**原始 CIF**（缺氢、待修复）或 computation-ready CIF；
- 需要记录来源证据（DOI/sha256/topology_evidence）时。

**不要用**：处理本地已有结构文件（直接 `cifkit repair/geom/export` 或 `pipeline --spec` 的 `source=local`）；只查文献（`literature-search`）。

## 依赖

```powershell
$PY = 'D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe'
Set-Location 'D:\Dev\Project5-skill-cif'
$env:PYTHONIOENCODING='utf-8'
& $PY -m cifkit --version
```

离线缓存（已就绪，勿重下）`D:\Dev\Project5-skill-cif\_cache\core-mof-2024\`：

| 文件 | 内容 |
|---|---|
| `CoREMOF2024DB.zip` | 44 MB，8300 个 CIF；目录 `SI/CR/{ASR,FSR,Ion}/` 与 `SI/NCR/{both,Chen_Manz,mofchecker}/` |
| `ASR_data_SI_20250204.csv` | 1372 行；含 `topology(SingleNodes)`、`topology(AllNodes)`、`refcode`、`natoms`、`DOI` 等列 |
| `NCR_ASR_SI.xlsx` | NCR 质检标记 |
| `CoRE2019_FSR.csv` | 备用 |

## 命令

```powershell
# 0) 先看有哪些数据源、是否需要 key、缓存/网络状态
& $PY -m cifkit sources --probe

# 1) 按拓扑检索（只列命中，不落盘）
& $PY -m cifkit fetch --topology sod --limit 10 --json

# 2) 要“缺氢、需要修复”的原始 CIF（--raw），并把 raw.cif + source.json 落盘
& $PY -m cifkit fetch --topology sod --name ZIF-8 --raw --outdir runs\fetch_sod --json

# 3) 要 computation-ready（H 已完整）版本
& $PY -m cifkit fetch --topology sod --ready --limit 5 --json

# 4) 换数据源兜底（COD 按 id / 名称）
& $PY -m cifkit fetch --source cod --id 7111973 --outdir runs\cod --json
& $PY -m cifkit fetch --source cod --name ZIF-8 --limit 5 --json

# 5) Materials Project（需先设置 $env:MP_API_KEY；免费申请 https://materialsproject.org/api）
& $PY -m cifkit fetch --source mp --id mp-149 --outdir runs\mp --json
& $PY -m cifkit fetch --source mp --name NaCl --limit 3 --json      # 只支持化学式，不支持 "ZIF-8"

# 5b) QMOF：先把官方数据解压到 $CIFKIT_QMOF_DIR（qmof.csv + structures/*.cif 或 qmof_cifs.zip）
& $PY -m cifkit sources --probe          # 看 qmof 是否 local mirror ready
& $PY -m cifkit fetch --source qmof --name ZIF-8 --limit 5 --json
#    注意：本环境 figshare/GitHub 下载不可达 → 未 live 实测；缺镜像时命令给出可操作错误，不伪造

# 6) AFLOW（免 key；--name 必须是化学式；或直接给 aurl）
& $PY -m cifkit fetch --source aflow --name ZnO --limit 3 --json
& $PY -m cifkit fetch --source aflow --id "aflowlib.duke.edu:AFLOWDATA/LIB1_WEB/Zn:PAW_PBE:06Sep2000/A9" --outdir runs\aflow --json

# 7) 本地文件（也可以直接用 pipeline --spec 的 source=local）
& $PY -m cifkit fetch --source local --id D:\path\x.cif --outdir runs\local --json
```

## 参数表

| 参数 | 说明 | 默认 |
|---|---|---|
| `--source` | `auto` / `core-mof` / `cod` / `local` / `materials-project`（别名 `mp`） / `aflow` | `auto` |
| `--topology` | RCSR 拓扑码（`sod`、`pcu`、`dia`…），只对支持拓扑过滤的源有效 | 无 |
| `--name` | 结构名（`ZIF-8`、`MOF-5`）或化学式（`NaCl`、`ZnO`，MP/AFLOW 用） | 无 |
| `--id` | 结构 id：`mp-149` / `7111973` / `aflowlib.duke.edu:AFLOWDATA/...` / 本地 `.cif` 路径 | 无 |
| `--raw` / `--ready` | 优先原始 CIF（缺氢/待修复）/ 优先 computation-ready | `--raw` 关 |
| `--no-typical` | 不要求“典型/代表性”样本 | 关（默认 `typical=true`） |
| `--limit N` | 返回候选数 | 10 |
| `--outdir DIR` | 落盘：`raw.cif`（源 CIF 字节拷贝）+ `source.json`（record + provenance） | 无（只打印） |
| `--json` | JSON 输出（推荐，字段最全） | 人类可读 |

`auto` 规则：`mp-<数字>` → materials-project；`aflow:`/`AFLOWDATA/` → aflow；
7 位数字 → cod；`.cif` → local；有 topology → core-mof；
只有名称时：化学式（GaN/NaCl）→ aflow，MOF 名称（ZIF-8/UiO-66）→ core-mof。

## 数据源怎么选

| 场景 | 选 | 理由 / 注意 |
|---|---|---|
| 按 RCSR 拓扑找 MOF | `core-mof` | 本地 CSV 有 `topology(AllNodes)`，离线、快、可复现 |
| 要 H 缺失的原始 CIF 做补氢 demo | `core-mof` + `--raw` | NCR 目录是原始 CIF，典型缺氢 |
| 已知 `mp-<id>` / 要 DFT 结构/性质 | `materials-project` | 需 `MP_API_KEY`；结构已计算就绪（一般不用补氢） |
| 无机/合金/金属间化合物 | `aflow` | 免 key；`--name` 必须是化学式；MOF 极少 |
| 特定 COD 编号 / CoRE 没有的实验结构 | `cod` | 网络可达；无拓扑列；公有领域 |
| 用户给了本地 `.cif` | `local` / `fetch --source local --id PATH` | 不下载、只读文件 |
| 不确定用哪个 | 先 `cifkit sources --probe` 看状态，再按上表选 | MP 无 key 时不要硬用 |

**经验（踩过）**：
- MP/AFLOW **没有 RCSR 拓扑列**：请求 `--topology sod` 时它们返回空列表，不是“没这个结构”，
  而是没有可过滤的元数据；要么改用 core-mof，要么下载后 `topology.verify`。
- MP 只支持 `mp-id` 和**化学式**检索，`--name ZIF-8` 查不到（会返回空列表）；MOF 名称请用 core-mof/COD。
- AFLOW 的条目 id 形如 `aflow:<auid>`，但公共 AFLUX **不能反查 auid → aurl**（实测返回空）；
  要下 AFLOW 结构请用 aurl/URL，或 `--name <化学式>`。
- AFLOW 的 CIF 文件名含 `:`，下载 URL 必须 percent-encode（`%3A`），否则 404 —— 适配器已处理。
- COD/MP/AFLOW 的 CIF 语义不同：MP 的 CIF 由 API JSON 生成（`provenance.cif_generated=True`），
  AFLOW/COD 是下载的 CIF 文件；三者 sha256 都单独记录，别混用。

## `topology_evidence` 四档（报告里必须写清，不许含糊）

| 值 | 含义 | 可信度 |
|---|---|---|
| `metadata` | 数据库元数据标签（CoRE CSV 的 `topology(AllNodes)`/`topology(SingleNodes)`） | 高，首选 |
| `verified` | `cifkit.topology.verify()` 用结构比对（underlying net 签名）核实 | 高，NCR 文件只能靠它 |
| `curated` | 文献 DOI + 人工复核，但没有算法证据 | 中，报告里要注明 |
| `unknown` | 没有任何证据 → **禁止**在报告里把拓扑写成“已验证” | 无 |
| `mismatch` | 比对失败，结构不是该拓扑 | 直接失败，换记录 |

`cifkit.topology` 现在带**落盘参考签名**（`cifkit/data/nets/<net>.json`）：`pcu / dia /
fcu / tbo / bcu / sod` 可在**离线、不依赖 CoRE zip** 的情况下 `verify`，并可用
`identify(structure)` 自动判定最佳 net（多重匹配或无线索时诚实返回 `unknown`）。

## 本机实测输出（2026-11-05）

```text
& $PY -m cifkit fetch --topology sod --limit 10 --json
→ 7 hits（全部 topology=sod / evidence=metadata / variant=computation-ready）:
  core-mof:SI/CR/ASR/2015[Zn][sod]3[ASR]1.cif   Zn6 H60 C48 N24   138 原子  doi=10.1021/ic5028256
  core-mof:SI/CR/ASR/2011[Zn][sod]3[ASR]3.cif   Zn6 H60 C48 N24   138 原子  doi=10.1021/ja202154j
  core-mof:SI/CR/ASR/2017[Zn][sod]3[ASR]1.cif   Zn6 H360 C312 N24 O48  750 原子
  core-mof:...Cd... / ...Zr...                  其它 4 条（Cd/Zr 体系）

& $PY -m cifkit fetch --topology sod --name ZIF-8 --raw --outdir runs\fetch\zif8_raw --json
→ 首条 core-mof:SI/NCR/both/ja204757x_si_002_ASR_pacman.cif
  formula=Zn12 C96 N48  variant=raw  natoms=156  h_count=0  h_expected=120.0
  topology=sod  topology_evidence=verified（NCR 无元数据列，靠结构比对）
  doi=10.1021/ja204757x
  provenance: cache_reused=true, dataset=CoRE MOF 2024 v1.1, dataset_doi=10.5281/zenodo.15055758,
              zip_sha256=d07a0c…, cif_sha256=c6939c…, license=CC-BY-4.0
```

注意：`--name ZIF-8` 仍会返回多条候选（`--limit` 默认 10），**按 record_id / variant / h_count 挑**，不要盲取输出里的任意一条。

## 已验证的数据事实（别再重新调研）

- CoRE 2024 `ASR` 中 `topology(AllNodes)==sod` 共 **7 条**；典型代表：
  - `2015[Zn][sod]3[ASR]1`（refcode `ic5028256_si_002_ASR_pacman`，ZIF-8，rhombohedral a=14.669 Å，H 完整，138 原子）→ computation-ready；
  - `2011[Zn][sod]3[ASR]3`（refcode `ja202154j_si_002_ASR_pacman`，ZIF-8）。
- NCR 原始 CIF：`SI/NCR/both/ja204757x_si_002_ASR_pacman.cif`
  - DOI `10.1021/ja204757x`；组成 `Zn12 C96 N48`，cubic `I-43m`，a=17.029 Å，156 原子，**H/C=0** → 补氢主用例；
  - `SI/NCR/both/ja204757x_si_003_ASR_pacman.cif` 是第二组采样（a=16.933 Å），同样无 H。
- `SI/NCR/both/ja202154j_si_003_ASR_pacman.cif`：a=17.107 Å，48 个全占据 H + 144 个 `H:0.5` → 无序/统计原子用例。
- COD ZIF-8（7111973）H 完整，**只能当对照**，不要用于补氢 demo。
- CoRE 2024 `CR/ASR` 的 CIF 是 computation-ready、H 完整，**不要**拿它演示补氢。

## 坑

- **`rcsr.anu.edu.au` 不可达、figshare API 403**：拓扑元数据只能从本地 CoRE CSV 取，别写代码去官网抓。
- **NCR 文件没有拓扑元数据列**：必须靠 `topology.verify` 结构比对，报告里 evidence 写 `verified`/`unknown`，不能写 `metadata`。
- **同名不同变体**：`variant` 字段区分 `computation-ready` / `raw`；拿错变体会让“补氢”变成 no-op（CR 已满氢）或失败。
- **`fetch` 无命中时退出码**：人类可读模式返回 1（打印 `no hits`），`--json` 模式返回 0 且输出 `[]`——脚本里请检查 JSON 列表是否为空，不要只看退出码。
- **`fetch --outdir` 的 `raw.cif`**：现在与 `pipeline` 一致，是源 CIF 的**字节拷贝**（`provenance.sha256` 可复核）；
  只有源文件不可直接拷贝时（极少数）才用 `CifWriter` 重写，此时 `source.json` 的 `note` 会说明。
- **Materials Project 需要 key**：未设置时命令会直接失败并提示申请地址（不是 traceback）；不要把 key 写进 spec/manifest。
- **AFLOW 的 aurl 形式**：`aflowlib.duke.edu:AFLOWDATA/.../A9`；`aflow:<auid>` 不能直接检索（见上）。
- **重复下载**：CoRE 已缓存在 `_cache/`，新下载必须写 provenance + sha256；不要拉第二个大 zip。

## 验收证据

1. `--json` 输出里每条命中都有 `record_id`、`source`、`formula`、`topology`、`topology_evidence`、`natoms`、`h_count`、`h_expected`、`variant`；
2. 落盘时 `runs\<name>\source.json` 里有 `record`/`provenance`/`raw_cif_sha256`；
   `provenance.sha256` 应等于 `provenance.cif_path` 实测 sha256，且 `raw_cif_sha256` 与 `raw.cif` 一致
   （源 CIF 可拷贝时 raw.cif 是字节拷贝；极少数不可拷贝才重写，`note` 会说明）；
   `--json` 模式下 "wrote ..." 走 stderr，stdout 仍是单个合法 JSON 数组；
3. 后续 pipeline 的 `manifest.json` 里 `source.record`/`source.provenance` 与本次 fetch 结果一致（同一 record_id / sha256）；
4. 报告写清 `topology_evidence` 的档次（NCR 用 `verified`），`unknown` 不许冒充 `verified`。

```powershell
& $PY -m cifkit fetch --topology sod --limit 10 --json
Get-Content runs\fetch\zif8_raw\source.json -Raw
& $PY -c "import hashlib,json; p=json.load(open(r'runs\fetch\zif8_raw\source.json',encoding='utf-8'))['provenance']; print('cif_path ok:', hashlib.sha256(open(p['cif_path'],'rb').read()).hexdigest()==p['sha256'])"
```

## 实测记录（2026-11-05，本机）

| 命令 | 结果 |
|---|---|
| `fetch --topology sod --limit 10 --json` | 7 hits（sod/metadata/computation-ready） |
| `fetch --topology sod --name ZIF-8 --raw --outdir runs\fetch\zif8_raw --json` | 首条 NCR `ja204757x_si_002`，156 atoms / 0 H / evidence=verified；落盘 `raw.cif` + `source.json`；`raw_cif_sha256 == provenance.sha256`；stdout 为纯 JSON（wrote 行走 stderr） |
| `fetch --topology sod --ready --limit 5 --json` | 5 hits，全部 `variant=computation-ready`（例：`2015[Zn][sod]3[ASR]1`，138 atoms，H=60） |
| `fetch --source cod --name ZIF-8 --limit 5 --json` | exit 0（约 11 s），COD 命中 `cod:2300691`（ZIF-8，146 atoms，H=60，evidence=unknown） |
| `fetch --source cod --id 7111973 --outdir runs\cod --json` | 命中 `cod:7111973`，落盘 `raw.cif`，provenance 有 sha256 |
| `fetch --source aflow --name ZnO --limit 3 --json` | 命中 3 条（如 `aflow:0265806d7329d48e`，O8Zn4，evidence=unknown）；`aflowlib.duke.edu:AFLOWDATA/...` 实测可下 CIF 并跑完 pipeline |
| `fetch --source mp --id mp-149`（本机无 key） | 按预期失败退出，错误信息含申请地址与 `MP_API_KEY` 提示；有 key 的解析路径用 mock 测试覆盖（生成 CIF + JSON sha256） |
| `cifkit sources` | 5 个源：core-mof/cod/local/materials-project/aflow；MP 显示 missing MP_API_KEY |
| `available_sources()` | `core-mof` / `cod` / `local` / `materials-project` / `aflow` |
| provenance sha256 校验 | `cif_path` 实测 sha256 == `provenance.sha256`（c6939c…），`cache_reused=true` |
