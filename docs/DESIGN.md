# CIF 处理工作台（cifkit）设计

> 状态：v1 冻结接口，供并行开发。任何接口改动先改本文件并通知 Lead。
> 工作目录：`D:\Dev\Project5-skill-cif`；唯一真源技能库：`D:\agent-library\catalog\`。

## 1. 目标（验收标准）

一句话管线直接跑通，输入：

> 帮我下载典型的 RCSR 为 sod 的 MOF，需要碳上补充氢，创建一个 2x2x1 的超胞（Supercell），沿 (111) 面切出表面，并加上 15Å 的真空层，导出为计算化学软件使用的格式。

输出必须包含：

1. 真实下载/缓存的 SOD 拓扑 MOF（ZIF-8 体系），带来源、DOI、sha256；
2. 补氢前后对照（缺多少 H → 补了多少，逐碳价态检查通过）；
3. 2x2x1 超胞（= 原胞 × 4；对 surface 请求，物理默认语义是把 2x2x1 作为 **slab 面内重复**：先切 (111) 再面内 2x2，报告里必须写明 frame=slab 还是 frame=cell）；
4. (111) slab（含表面周期、层厚、终止面选择依据）；
5. 真空层 ≥ 15 Å（从原子到周期像的最小距离实测，不是名义值）；
6. 计算化学格式导出（至少 VASP POSCAR，另加 CIF/XYZ 等）；
7. 结构校验报告（组成、原子数、近邻距离、悬空键/配位、真空层）+ 预览图；
8. `manifest.json` 全链路溯源（查询、来源、下载记录、每步耗时、校验结论、工具版本）；
9. 同一查询重跑可复现（缓存命中，不重复下载）。

## 2. 目录与职责

```text
cifkit/            # 可安装 Python 包（python -m cifkit）
  __init__.py      # 版本、公开 API
  types.py         # 所有共享 dataclass（Lead 独占）
  spec.py          # 自然语言 -> TaskSpec（Lead）
  plan.py          # TaskSpec -> 步骤计划（Lead）
  pipeline.py      # 执行计划、产出 artifacts/manifest（Lead）
  provenance.py    # 运行记录、sha256、版本、入库（Lead）
  cache.py         # 缓存根目录解析（Lead，各模块共用）
  cli.py           # 子命令（Lead）
  sources/         # 数据源适配层（队友 sources）
    __init__.py    # registry + get_source()
    base.py        # SourceQuery/FetchedStructure + Source 协议（Lead 给骨架）
    core_mof.py    # CoRE MOF 2024/2019：元数据、拓扑过滤、CIF 提取、缓存
    cod.py         # Crystallography Open Database 检索/下载
    local.py       # 本地 .cif 文件
    materials_project.py  # 可选，MP API key 存在时
    index.py       # 本地结构索引构建（zip -> index.json）
  repair/          # 修复层（队友 repair）
    __init__.py    # repair_all(structure, options) -> (Structure, RepairReport)
    disorder.py    # 占位/统计原子/多位置/无序组
    hydrogen.py    # 缺氢补齐（核心算法）
    contacts.py    # 原子过近/重复原子
    valence.py     # 价态/配位数检查（C 必须 4 键、金属配位等）
  geom/            # 几何操作（队友 geom）
    __init__.py
    standardize.py # 原胞 <-> 常规胞、去重复、对称性
    supercell.py
    surface.py     # (hkl) slab + 终止面选择
    vacuum.py      # 精确真空层设置/测量
    cluster.py     # 金属簇 / SBU 提取
  export/          # 导出（队友 geom）
    __init__.py
    writers.py     # vasp/cif/xyz/lammps/qe/cp2k...
  validate/        # 校验（队友 geom）
    __init__.py
    checks.py      # 结构校验指标与 pass/fail
  render.py        # 预览 PNG（队友 geom）
tests/             # pytest；每人只改自己命名的测试文件
  data/            # 小体积 fixture
docs/              # DESIGN/PIPELINE/SOURCES/REPAIR/GEOM/EXPORT/VALIDATION
runs/              # 运行输出（gitignore，保留 demo 关键文件）
```

## 3. 环境（已就绪，勿重复安装）

- Python：`D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe`（venv，`--system-site-packages`）
  - 已装：`ase 3.29`、`pymatgen 2026.10`、`openbabel-wheel 3.1.1.23`（`from openbabel import openbabel`）、`pytest`；全局继承 `rdkit 2026.09`、`numpy`、`scipy`、`pandas`、`matplotlib`、`networkx`。
- 网络：COD、Zenodo、PyPI 可达；`rcsr.anu.edu.au` 不可达；figshare API 403。
- 数据缓存：`D:\Dev\Project5-skill-cif\_cache\core-mof-2024\`（已下载）
  - `CoREMOF2024DB.zip`（44 MB，8300 个 CIF，目录 `SI/CR/{ASR,FSR,Ion}/` 与 `SI/NCR/{both,Chen_Manz,mofchecker}/`）
  - `ASR_data_SI_20250204.csv`（1372 行；含 `topology(SingleNodes)`、`topology(AllNodes)`、`refcode`、`natoms`、`DOI` 等列）
  - `NCR_ASR_SI.xlsx`（NCR 质检标记）
  - `CoRE2019_FSR.csv`（备用）
- 测试：`.venv\Scripts\python.exe -m pytest tests -q`

## 4. 关键数据事实（已验证，别重新调研）

1. CoRE MOF 2024 CSV 的拓扑列是 RCSR code（小写，如 `sod`）。ASR 中 `topology(AllNodes)==sod` 共 7 条；典型代表：
   - `2015[Zn][sod]3[ASR]1`（refcode `ic5028256_si_002_ASR_pacman`，ZIF-8，原胞 rhombohedral a=14.669Å，H 完整，138 原子）
   - `2011[Zn][sod]3[ASR]3`（refcode `ja202154j_si_002_ASR_pacman`，ZIF-8，同）
2. NCR（not computation-ready）目录含**原始 CIF**：`SI/NCR/both/ja204757x_si_002_ASR_pacman.cif`
   - 文献 DOI `10.1021/ja204757x`（JACS 2011, “Capture of volatile iodine … by zeolitic imidazolate framework-8”）
   - 组成 `Zn12 C96 N48`，cubic `I-43m`，a=17.029 Å，156 原子，**完全没有 H**（H/C=0）→ 这就是“缺氢、需要碳上补氢”的真实样例（ZIF-8 = sod）。
   - 同目录 `ja204757x_si_003_ASR_pacman.cif` 为第二组采样（a=16.933 Å），同样无 H。
   - 注意：NCR 文件没有拓扑元数据列 → 拓扑需 `topology.py` 用结构比对（见 §5）核实，或由 curated 表给出证据。
3. `SI/NCR/both/ja202154j_si_003_ASR_pacman.cif` 是 ZIF-8 常规胞 a=17.107 Å，但 H 有半占据（48 个全占据 + 144 个 `H:0.5`）→ “统计原子/多位置”样例，可用于 disorder 测试。
4. 下载的 COD ZIF-8（7111973）H 完整，只能当对照，不要用于补氢 demo。
5. CoRE 2024 的 CR/ASR CIF 都是 `computation-ready`，H 完整；**不要**用它们演示补氢。

## 5. 拓扑判定（诚实性要求）

- 首选：数据库元数据标签（`ASR_data_SI_20250204.csv` 的 `topology(AllNodes)` / `topology(SingleNodes)` / `topology(...)-zeo`）。
- 次选：结构比对。`cifkit.topology`：
  - `underlying_net(structure)`：金属节点 + 通过有机 linker 的连接 → 周期图（LQG：节点、边、平移向量）；
  - `net_signature(...)`：配位数、环大小分布（4/6/8 元环）、配位序列（coordination sequence）等不变量；
  - `verify(structure, expected)`：与参考结构（同拓扑的 CoRE ASR CIF，或 bundled 参考）比对签名 → `verified` / `mismatch`；
  - 对 sod 的 demo：把 H-free ZIF-8 与 `2015[Zn][sod]3[ASR]1` 的 net 签名比对，必须一致才标 `verified`。
- 禁止把“论文标题写了 ZIF-8”直接当拓扑证据；可以记录为 `curated`（附 DOI 与复核结果）。
- 报告里必须写清 `topology_evidence ∈ {metadata, verified, curated, unknown}`。

## 6. 共享接口（types.py，Lead 冻结）

```python
TaskSpec(query, source, topology, structure_name, structure_id, typical,
         repair_h, repair_disorder, remove_close_contacts, extract_cluster,
         supercell, surface, vacuum, slab_thickness, output_formats, outdir)

StructureRecord(record_id, source, formula, topology, topology_evidence,
                refcode, coreid, doi, variant, natoms, h_count, h_expected,
                path, url, sha256, notes, extra)

SourceQuery(topology, typical, prefer_raw, structure_name, structure_id,
            limit, source)

FetchedStructure(structure, record, provenance)   # provenance: dict

RepairReport(actions: list[dict], added_h: int, removed_atoms: int,
             resolved_disorder: int, warnings: list[str])

StepResult(name, status, detail, artifacts, data)

RunResult(spec, steps, artifacts, outdir, manifest_path, validation)
```

模块函数签名（必须遵守）：

```python
# sources
def search(query: SourceQuery) -> list[StructureRecord]        # 可能触发下载/建索引
def fetch(record: StructureRecord) -> FetchedStructure
# repair
def repair_all(structure, *, add_hydrogen=False, resolve_disorder=True,
               remove_close_contacts=True) -> tuple[Structure, RepairReport]
# geom
def standardize(structure, *, target="conventional") -> Structure
def make_supercell(structure, reps: tuple[int,int,int]) -> Structure
def make_slab(structure, hkl, *, slab_thickness=15.0, vacuum=15.0,
              termination=None, reps=None, frame="slab") -> tuple[Structure, dict]
    # frame="slab"（默认）：从传入的体相结构切 (hkl)，再把 reps 作为 slab 面内重复
    # frame="cell"：字面语义，先把体相结构按 reps 扩展，再切该胞的 (hkl)
    # dict 必含：frame, hkl, reps, base_atoms, atoms_after_reps,
    #            slab_thickness, vacuum_measured, termination, candidates
def set_vacuum(structure, vacuum: float, axis=2) -> tuple[Structure, float]  # (新结构, 实测真空)
def extract_cluster(structure, *, mode="sbu") -> Structure
# export
def write_structure(structure, path, fmt: str, *, title=None) -> str
def supported_formats() -> dict[str, str]
# validate
def validate_structure(structure, *, spec=None, extra=None) -> ValidationReport
# render
def render_structure(structure, path, *, view="auto", title=None) -> str
```

## 6b. 额外接口（Lead 已冻结）

```python
# sources/__init__.py
available_sources() -> dict[str, str]
get_source(name: str) -> Source
resolve(spec: TaskSpec) -> FetchedStructure      # 按 spec.source（auto 自动选）检索并取回

# topology.py
verify(structure, expected: str) -> dict
    # {"ok": bool, "evidence": "metadata"|"verified"|"curated"|"mismatch",
    #  "detail": str, "signature": {...}, "reference": {...}}
describe(structure) -> dict
underlying_net(structure) -> dict
```

## 6c. CLI 命令面（技能包装层依赖，不可改）

```text
python -m cifkit route "TEXT" [--json]
python -m cifkit pipeline "TEXT" --outdir DIR [--format vasp,cif,xyz] [--source auto] [--ingest] [--json]
python -m cifkit pipeline --spec spec.json --outdir DIR
python -m cifkit fetch --topology sod [--name ZIF-8] [--raw|--ready] [--limit N] [--outdir DIR] [--json]
python -m cifkit repair FILE -o OUT [--add-h] [--no-disorder] [--no-contacts] [--json]
python -m cifkit geom FILE -o OUT [--standardize] [--supercell 2 2 1] [--surface 1 1 1] [--surface-frame slab|cell] [--vacuum 15] [--thickness 15] [--cluster sbu] [--json]
python -m cifkit export FILE --format vasp,cif -o OUT [--json]
python -m cifkit validate FILE [--json]
python -m cifkit formats
python -m cifkit selftest
```

统一入口：`D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe -m cifkit`（包已 editable 安装）。

## 6d. 测试 fixture（已放好，勿改）

```text
tests/data/zif8_raw_hfree.cif      # ZIF-8 常规胞 a=17.029，Zn12C96N48，0 个 H —— 补氢主用例
tests/data/zif8_cr_sod.cif         # CoRE ASR sod 原胞 a=14.669，H 完整 —— 拓扑参考/补氢 no-op 对照
tests/data/zif8_disordered_h.cif   # ZIF-8 常规胞 a=17.107，48 全占据 H + 144 个 0.5 占据 H —— 无序用例
tests/data/sod_zn_mof.cif          # 2017[Zn][sod]（含溶剂 O），750 原子 —— 大结构/含溶剂对照
```

## 7. 验收与演示

### 7.1 demo 的已知实测数字（ZIF-8 / sod，H-free 原始 CIF）

| 步骤 | 结果 |
|---|---|
| 原始 CIF | `SI/NCR/both/ja204757x_si_002_ASR_pacman.cif`，Zn12 C96 N48，156 原子，0 H，a=17.029 Å |
| 补氢 | +120 H → 276 原子（Zn12 C96 H120 N48），RDKit-capped，24/24 片段，C 96/96 四配位 |
| 标准化 | 常规胞 I-43m，276 原子（整数倍守卫生效，不翻倍成 552） |
| (111) slab（target 厚 15 Å） | 552 原子；面内 a=b≈24.08 Å；原子垂直跨度（slab 厚）≈19.28 Å |
| slab 面内 2x2（2x2x1） | **2208 原子**，面内 a=b≈48.17 Å |
| 真空 15 Å | c_perp = 19.283 + 15.000 = **34.283 Å**；垂直真空实测 = **15.000 Å**；最小周期像距离（3D，横向错位下更大）= 15.240 Å |
| 导出 | `structure.vasp` 2208 原子，pymatgen 读回原子数一致；`structure.cif` / `structure.xyz` 同 |
| 用时 | 缓存已热时整条管线 ~10 s（冷启动需先建 CoRE 索引，约 10 s） |

（`frame=cell` 的字面语义对照：先 2x2x1 超胞 1104 原子 → 该胞 (111) 切面 ≈2208 原子，但取向不是立方 (111)，报告里只作 caveat 对照。真空层厚度一律用**垂直**定义 `c_perp - slab_thickness`；`min_image_distance` 只作为安全下界单独报告。）

- `tests/` 全绿（含 demo 端到端测试）；`_cache` 存在时可全离线跑通。
- `runs/demo_sod_zif8/` 保留：`raw.cif`、`repaired.cif`、`standardized.cif`、`slab.cif`、`final.cif`、`structure.vasp`、`structure.cif`、`structure.xyz`、`preview.png`、`report.md`、`manifest.json`。
- 报告必须包含：来源 URL/DOI/sha256、sod 拓扑证据、补氢统计、超胞倍数核对、slab 参数、真空实测值、导出格式清单。
- 技能：`D:\agent-library\catalog\cif-workbench/`、`cif-fetch/`、`cif-repair/`、`cif-geometry/`、`cif-export/` + intents + evals，`py -3 scripts\ci.py` 相关项通过。

## 8. 协作约定

1. 先 `git status`，只改自己 scope 内文件；共享文件（types.py、pipeline.py、cli.py、intents.json）只由 Lead/指定 owner 改。
2. 每个模块自带 pytest；提交前 `.venv\Scripts\python.exe -m pytest tests -q` 至少自己那部分全绿。
3. 不要往网络重复下载大文件；用 `_cache/`。新增下载要写进 `sources` 的 provenance 并有 sha256。
4. 遇到接口不够用：先在 task/消息里说明，Lead 改 types.py，不要各自造 DTO。
5. 绝对不要在报告里把“推测”写成“已验证”。
