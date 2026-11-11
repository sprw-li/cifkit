# CIF 处理工作台（cifkit）— Project5

把「从数据库下载下来的裸 CIF」变成「能直接喂给 VASP / QE / CP2K / LAMMPS 的结构」：
**选型下载 → 拓扑核实 → 修复（补氢 / 无序占位 / 近邻）→ 标准胞 → 超胞 → (hkl) 切面 → 真空层 → 导出 → 校验 → 入库**。

技能组在 `D:\agent-library\catalog\cif-*`（router 可命中）；本仓库是引擎、脚本与验收现场。

---

## 一条管线跑通（验收 demo）

用户原话：

> 帮我下载典型的RCSR为sod的mof，需要碳上补充氢，创建一个2x2x1的超胞（Supercell），沿(111)面切出表面，并加上15Å的真空层，导出为计算化学软件使用的格式。

```powershell
$PY = 'D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe'
$env:PYTHONIOENCODING='utf-8'
Set-Location 'D:\Dev\Project5-skill-cif'

# 首次在新机器上：准备 CoRE MOF 2024 缓存（Zenodo，~45 MB，幂等）
& $PY scripts\bootstrap_data.py

# 一条管线（缓存热时约 10 s）
& $PY -m cifkit pipeline "帮我下载典型的RCSR为sod的mof，需要碳上补充氢，创建一个2x2x1的超胞（Supercell），沿(111)面切出表面，并加上15Å的真空层，导出为计算化学软件使用的格式。" --outdir runs\demo_sod_zif8 --format vasp,cif,xyz --ingest

# 独立复核（不信自报，直接从产物结构验 DESIGN §1 的 9 条验收，其中 8 项自动复核）
& $PY scripts\verify_demo.py runs\demo_sod_zif8
```

实测结果（`runs/demo_sod_zif8/`，2026-11-05 本机）：

| 步骤 | 结果 |
|---|---|
| 来源 | CoRE MOF 2024（Zenodo 15055758，CC-BY-4.0）`SI/NCR/both/ja204757x_si_002_ASR_pacman.cif`；DOI 10.1021/ja204757x；sha256 记录在 manifest |
| 拓扑 | `sod`，证据 `verified`：underlying net 签名（4-配位；配位序列 4,10,20,34,52,74,100,130；4/6/8 元环分布）与 CoRE ASR `2015[Zn][sod]3[ASR]1` 一致 |
| 补氢 | 0 H → **+120 H**（每 mIm 5 个 H；环 C–H 平面内、甲基 109.5°），156 → **276 原子**，C 96/96 四配位，无 N–H |
| 标准化 | 常规胞 I-43m，276 原子（整数倍守卫，不翻倍） |
| (111) slab | 552 原子，面内 a=b≈24.08 Å，slab 厚≈19.28 Å |
| 2x2x1 | 作为 **slab 面内 2×2** 重复 → **2208 原子**，面内 a=b≈48.17 Å |
| 真空 15 Å | c⊥ = 34.283 Å；垂直真空实测 **15.000 Å**（另有最小周期像距离 15.240 Å） |
| 导出 | `structure.vasp` 2208 原子（读回一致）、`structure.cif`、`structure.xyz` |
| 校验 | 12 项通过（`dangling_bonds` 是表面必然的 WARN） |
| 独立验收 | **8/8 PASS**（`scripts/verify_demo.py`） |
| 产物 | `raw.cif` `repaired.cif` `standardized.cif` `slab.cif` `final.cif` `structure.vasp/.cif/.xyz` `preview.png` `report.md` `manifest.json` |

`2x2x1` 的语义：默认 **`--surface-frame slab`**（物理正确：先在体相常规胞上切 (111)，再做面内 2×2、沿法向 ×1）；
`--surface-frame cell` 是字面语义（先 2x2x1 超胞再切该胞的 (111)，取向不是立方 (111)），仅作对照，见 `docs/GEOM.md`。

---

## 能力矩阵

| 子命令 | 作用 | 示例 |
|---|---|---|
| `pipeline` | 一条管线，产出 manifest/report/预览 | 见上 |
| `batch` | 多条 pipeline 并发（每条独立子进程，写 batch_manifest.json） | `batch --spec "<一句话>" --spec "<另一句>" --jobs 4 --outdir runs\batch` |
| `fetch` | 按 RCSR 拓扑 / 名称 / id 从 **CoRE MOF 2024、COD、Materials Project、AFLOW、本地**检索并落盘 | `fetch --topology sod --raw`；`fetch --source aflow --name ZnO` |
| `sources` | 列出数据源、是否需要 key、缓存/网络状态（智能选型入口） | `sources --probe` |
| `repair` | 补氢 / 无序占位 / 过近原子 / 价态检查 | `repair raw.cif -o fixed.cif --add-h --json` |
| `geom` | 标准化 / 超胞 / (hkl) slab / 真空 / 金属簇-SBU | `geom s.cif -o slab.cif --standardize --surface 1 1 1 --supercell 2 2 1 --vacuum 15` |
| `export` | VASP/CIF/XYZ/LAMMPS/QE/CP2K/XSF（7 种，写出后尽量读回校验） | `export slab.cif --format vasp,cif -o out` |
| `validate` | 结构校验（原子数、最近邻、真空、悬空键、C 配位…） | `validate final.cif --json` |
| `route` | 一句话 → TaskSpec + 计划（不执行） | `route "…"`；退出码 2 = 缺少结构信息 |
| `formats` / `selftest` | 格式列表 / 环境自检 | |
| `teach` | Fd-3m 点群典例教学图（spglib 复核 → CSV + PNG） | `teach --spacegroup Fd-3m --outdir runs\uc\fd3m` |
| `bravais` | Bain 路径 + 14 种布拉维点阵对称性实测 | `bravais --outdir runs\uc\bravais --bain-range 0.9:1.7:0.05` |
| `metals` | 纯金属批量：bulk/slab/POSCAR/INCAR/KPOINTS（可打包 kit） | `metals --outdir runs\uc\metals --elements Fe,Cu,Mg` |
| `fec` | Fe-C 结构 + 0 K 凸包 + VASP 模板（离线，可打包 kit） | `fec --outdir runs\uc\fec --zip` |

> `teach/bravais/metals/fec` 由 `cifkit/usecases_cli.py` 提供；`usecases/` 里的原脚本保留为 fallback
> （`--help` 与默认输出目录兼容），都支持 `--outdir` 与 `--json`。

**数据源（6 个）**：

| source | 覆盖 | key | 拓扑元数据 | 经验 |
|---|---|---|---|---|
| `core-mof` | CoRE MOF 2024（MOF；NCR 原始 CIF） | 免（本地缓存） | **有**（仅 ASR） | 拓扑/MOF 首选；要缺氢原始 CIF 用 `--raw` |
| `cod` | Crystallography Open Database | 免 | 无 | 实验晶体兜底；公有领域；拓扑需结构比对 |
| `materials-project` | Materials Project（DFT） | **`MP_API_KEY`** | 无 | 只支持 `mp-id`/化学式，不支持名称；结构已计算就绪 |
| `aflow` | AFLOW（无机/合金） | 免 | 无 | 只支持化学式/aurl；MOF 极少；CIF 名含 `:` 需 URL-encode |
| `local` | 本地 `.cif` | 免 | 无 | 最快；拓扑需结构比对 |
| `qmof` | QMOF（DFT 标注 MOF；**本地镜像**） | 免 | 无 | 只读 `$CIFKIT_QMOF_DIR`；figshare 下载本环境不稳（403/502/截断），未完成 live 验证；`scripts/bootstrap_qmof.py` 供网络可达时用 |

环境：`.venv`（`--system-site-packages`）内含 `pymatgen`、`ase`、`openbabel-wheel`、`pytest`，继承全局 `rdkit`/`numpy`/`scipy`/`networkx`/`matplotlib`；`cifkit` 已 editable 安装，任意目录可 `python -m cifkit`。

---

## 并发与性能

- 批量：`cifkit batch --spec ... --jobs N`（独立子进程；3 条 demo：串行 41.0 s → 并发 14.8 s，2.8×）。
- slab 生成进程内缓存：同参数第二次 2.12 s → 0.014 s（~150×）。
- 缓存并发安全：CoRE 索引构建用文件锁 + 原子写，3 进程冷建实测 8300 条完整。
- 细节与复现命令：[docs/PERFORMANCE.md](docs/PERFORMANCE.md)、[docs/ROBUSTNESS.md](docs/ROBUSTNESS.md)。

---

> 完整**局限清单**（按类别、状态、影响、规避）见 [docs/LIMITATIONS.md](docs/LIMITATIONS.md)。

## 商用平台接入（可复用接口）

| 能力 | 入口 | 说明 |
|---|---|---|
| 进程内库 | `from cifkit import api` | `capabilities / features / features_many / convert / dataset / topology / validate`；返回值 JSON 可序列化、线程安全、无全局状态 |
| RPC 处理器 | `from cifkit.service import handle` | `{"op":..., "params":{...}}` → `{"ok":..., "data"/"error"}`；可挂 FastAPI/Flask/Lambda，自带零依赖 HTTP 服务器 |
| 机器可读契约 | [cifkit/schemas/](cifkit/schemas/request.json) | request / response / ops / feature_row 四个 JSON Schema；契约校验在派发前执行（400 + JSON 路径） |
| 许可 | [LICENSE](LICENSE) **MIT** + [LICENSING.md](LICENSING.md) | 代码可商用/可闭源；数据源逐源条款；**核心 GPL-free**（屏蔽 Open Babel 实测 31 格式全过） |
| 权限松 | 见 [docs/API.md](docs/API.md) §4 | 核心 API 不需要任何 key、可全离线；只有 Materials Project 需环境变量注入 |

接口契约、错误码、版本策略、平台清单：[docs/API.md](docs/API.md)。
机器可读依赖许可审计：`.venv\Scripts\python.exe scripts\license_audit.py [--all] [--strict]`。
数据覆盖审计：`.venv\Scripts\python.exe scripts\audit_dataset_coverage.py --name MIL-101`；
超大结构逐阶段实测：`.venv\Scripts\python.exe scripts\bench_large_structure.py`；
发布门禁（两仓干净 + 全绿 + 文档一致）：`.venv\Scripts\python.exe scripts\release_check.py --quick`；
数据集覆盖矩阵（哪些拓扑/MOF 家族有、能否离线验证）：[docs/COVERAGE.md](docs/COVERAGE.md)；
验收报告（本机 + 云端证据分级）：`.venv\Scripts\python.exe scripts\check_software.py`；
云端 GPU 并发（fan-out，含成本硬门禁）：[docs/CLOUD-GPU.md](docs/CLOUD-GPU.md)；
云端软件验收（H3 补证，需 Bohrium 凭据）：`scripts\cloud_h3_submit.py --check`；手册见 [runs/cloud_h3/RUNBOOK.md](runs/cloud_h3/RUNBOOK.md)。

---

## CIF → anything（任意格式 / 输入包 / 数据管线）

| 能力 | 命令 | 覆盖 |
|---|---|---|
| 任意格式导出 | `cifkit convert FILE_OR_DIR... --to vasp,cif,xyz,extxyz,json,pdb,sdf,mol,cfg,lammps,qe,cp2k,gromacs,gaussian,orca,abacus,dftb,siesta,nwchem,aims,castep,abinit,crystal,xsf,...` | **31 种格式**，第三方回读 25/31（`scripts/verify_formats.py`）；模板类标 `template` |
| 批量转换 | `cifkit convert <目录或文件...> --to ... --outdir DIR` | 每输入一个子目录 + `convert_manifest.json`（n_ok/n_failed/错误）；坏输入不中断 |
| 计算软件输入包 | `cifkit convert FILE --bundle vasp,qe,cp2k,lammps,gromacs,gaussian,orca,abacus,dftb,siesta,nwchem,aims` | **12 种**：结构 + 输入模板 + README + `missing`（POTCAR/UPF/basis/skf/力场） |
| 结构特征表（ML） | `cifkit features FILE_OR_DIR --out features.csv [--jobs] [--no-rdf] [--topology]` | 组成/晶格/对称性/配位数/RDF/拓扑/H/金属分数 |
| 数据集构建 | `cifkit dataset --from-runs runs/ --outdir dataset/ [--label-key topology]` | `dataset.csv/jsonl` + structures + manifest（errors/label/sha256） |

> 边界：`cifkit` 不提供 POTCAR/UPF/skf/力场文件，也不把这些模板说成"可直接运行"；
> 下载/补氢/超胞/切面/真空仍走 `cifkit pipeline`，最后再 `convert` 或 `pipeline --bundle`。

---

## 应用实例（第 5 轮 4 个真实需求）

| 需求 | 交付 | 关键数字 |
|---|---|---|
| Fd-3m 点群典例排成 png | [usecases/u1_fd3m](usecases/u1_fd3m/README.md) | 6 个真实结构（COD×5+AFLOW×1），spglib 全部 #227，3740×2822 PNG |
| cF 与 tI 关系 / 14 种布拉维点阵 | [usecases/u2_bravais](usecases/u2_bravais/README.md) | Bain 路径 82 点：80×tI#139 + 精确 cI#229/cF#225；14 种点阵 14/14；12 组等价实测 |
| 纯金属晶格 + 最密面表面能文件 | [usecases/u3_metals](usecases/u3_metals/README.md) | 87 种金属导出 69（ASE 58/AFLOW 7/COD 4），18 missing 有原因；真空全部 15.0 Å |
| Fe-C 化合物 + 相图 + 计算套件 | [usecases/u4_fec](usecases/u4_fec/README.md) | 7 结构；0K hull 仅 Fe/C 端点，Fe3C=+0.0456、Fe2C=+0.0516 eV/atom |

用 CI 子命令一键复跑（产物只写 `--outdir`，不动 `usecases/` 交付目录）：

```powershell
& $PY -m cifkit teach   --spacegroup Fd-3m --outdir runs\uc\fd3m --json
& $PY -m cifkit bravais --outdir runs\uc\bravais --bain-range 0.9:1.7:0.05 --json
& $PY -m cifkit metals  --outdir runs\uc\metals --elements Fe,Cu,Mg --json
& $PY -m cifkit fec     --outdir runs\uc\fec --zip --json
```

一键独立验收：`& $PY usecases\verify_usecases.py`（22/22 PASS，旧交付物）；
`& $PY -m pytest tests\test_usecase_cli.py -q`（4 子命令/JSON 纯度/错误码，本机 12 passed + 1 skipped，约 28 s）。
技能：`catalog/cif-usecases`（intent `cif-advanced-usecases`；旧脚本仍可单独运行）。
总览与诚实局限见 [usecases/README.md](usecases/README.md)。

---

## 关键设计

- **诚实溯源**：每次运行写 `manifest.json`（查询、来源 URL/DOI/sha256、每步耗时、校验数字、工具版本），`--ingest` 额外入库到 `library/`（`index.jsonl` + 每 run 目录）。
- **拓扑证据分级**：`metadata`（数据库列）→ `verified`（结构比对：金属节点配位、2–8 层配位序列、4–8 元环分布）→ `curated`（文献样例 + 复核）→ `unknown`/`mismatch`。不把“论文标题/名字”当已验证。
- **补氢**：周期键感知 + 金属配位约束 → 每个有机片段 RDKit capping + `AddHs(addCoords=True)` → 坐标映射回晶胞；纯几何 VSEPR 兜底；补后自检 C 价态、H–H/H–重原子最小距离。局限见 `docs/REPAIR.md`。
- **切面/真空**：`SlabGenerator` 多终止面候选按「悬空键 + 化学计量偏差」打分；真空层按**垂直定义**精确设置（`c⊥ = slab厚 + target`），同时报告最小周期像距离。
- **失败也写 manifest**：任一步失败仍产出 `manifest.json`/`report.md`（`ok: false`, `failed_step`），便于复盘。
- **离线优先**：索引与 CIF 全部走 `_cache/`；`bootstrap_data.py` 负责新机器首次下载。

---

## 测试与复现

```powershell
# 一键体检（selftest → pytest → verify_demo → router/eval/ci）
& $PY scripts\check_all.py

& $PY -m pytest tests -q            # 563 条（默认 557 passed + 6 条 opt-in/skipped：`test_metals_zip_full`×1、MP live×2 需 key、QMOF live×1 需镜像；含 demo 端到端，需 _cache）
& $PY -m cifkit selftest --verbose  # 离线自检 7/7
& $PY scripts\verify_demo.py runs\demo_sod_zif8              # 8/8（离线：sha256/DOI 格式与一致性/拓扑/补氢/几何/导出/校验）
& $PY scripts\verify_demo.py runs\demo_sod_zif8 --online     # 额外把 DOI 送 Crossref 解析
```

测试分布：export 20 / geom 34 / pipeline 3 / repair 12 / sources 17 / sources-mp-aflow 12 / spec 7 / topology 15 / validate 14 / cli 11 / batch 3 / repair-carboxylate 17 / robustness 6 / slab-cache 4 / sources-qmof 4 / topology-nets 34 / usecase-cli 13。

---

## 技能组（agent-library）

| skill | 作用 |
|---|---|
| `catalog/cif-workbench` | 总入口：一条管线 |
| `catalog/cif-fetch` | 数据库选型 + 下载 + 拓扑证据 |
| `catalog/cif-repair` | 补氢 / 无序 / 近邻 / 价态 |
| `catalog/cif-geometry` | 超胞 / 切面 / 真空 / 金属簇 |
| `catalog/cif-export` | 格式导出与读回验证 |

- 原句路由：`intent=cif-structure-pipeline`，第一候选 `cif-workbench`（修复前曾被误判为 `install-app`）。
- `eval_router --all`：正例 73/73（intent/skill top1/top5 100%），负例 0/25 误报，槽位 11/11；`ci.py --fast` 通过。

---

## 评审记录（评审-改进轮）

- **Round 1（独立对抗式评审，`reviewer-r1`）**：[docs/REVIEW-ROUND1.md](docs/REVIEW-ROUND1.md)，结论 **PASS / 无 P0**。
  - 评审员自写脚本独立复算：sha256 三方一致、DOI 经 Crossref 核实且来源标注 `curated`、拓扑 net 签名可复算、补氢几何/价态全对、垂直真空 15.000 Å、2208=552×4、导出读回一致；重跑 exit 0、`verify_demo` 8/8、pytest 119 全绿。
  - 提出 4 个 P1（JSON 污染、真空口径文档、artifacts 计数、字节数过期）+ 7 个 P2。
- **Round 2（修复轮）**：P1 全部修复、P2 基本处理，见 [docs/PIPELINE.md §8](docs/PIPELINE.md)；新增 `tests/test_cli.py`（8 条 CLI 合同测试），测试总数 **127**。
- **Round 3（二次独立复核）**：[docs/REVIEW-ROUND2.md](docs/REVIEW-ROUND2.md)，结论 **PASS**：4/4 P1 FIXED、无假修复、无新 P0/P1、无回归；127 passed、verify_demo 8/8、结构产物与留档逐字节一致。
- **Round 4（收尾修复）**：按 Round 3 剩余建议加强 DOI 校验（record/provenance 一致性 + DOI 正则 + curated 标注 + 可选 `--online` Crossref 解析）、统一 report 产物清单、更新文档数字、新增 `scripts/check_all.py` 一键体检。
- **Round 5（收尾确认）**：[docs/REVIEW-ROUND3.md](docs/REVIEW-ROUND3.md)，结论 **PASS**：2 个 PARTIAL 均 FIXED、6 条新 P2 中 5 条 FIXED（第 6 条"尚未提交"在最终 commit 后关闭）、无新 P0/P1；`check_all.py` fast/full 均 6/6 通过，`--online` Crossref 200 + 真实标题，tamper 用例全部 FAIL。
- **Round 6（数据源扩展）**：补齐 **Materials Project**（需 `MP_API_KEY`）与 **AFLOW**（免 key）适配器，
  COD/CoRE/local 保留；新增 `cifkit sources` 选型命令、数据源决策表与经验（`docs/SOURCES.md` §7d），
  路由 intent 增数据源关键词/examples（评测 89/89、负例 0/25），测试总数 **563 条（默认 557 passed + 6 条 opt-in/skipped：`test_metals_zip_full` 需 `CIFKIT_USECASE_FULL=1`、MP live 2 条需 `MP_API_KEY`、QMOF live 1 条需本地镜像）**。
  - 诚实标注：AFLOW/COD 为 **live 实测**；MP 因本机无 key 只做 **mock 测试**，文档/技能正文均写明"需 key"。

---

## 局限（先说清楚）

- 补氢针对有机配体/常规 MOF（C/N/O/S/B/P 等）：已覆盖咪唑 ZIF-8 与羧酸根 MOF-5/UiO-66/HKUST-1
  （BDC/BTC 环 C–H、UiO-66 的 μ3-OH、自由羧酸的 O–H；金属配位/桥联羧酸根 O 不加 H）。
  金属氢化物、自由基、纯无机周期体系、有机金属 M–C 键（Cp/烷基/CO 等）会如实给 warning
  或走几何兜底；μ3-O/μ3-OH 仅凭几何可能混淆（会保守不补并 warning），MIL-101 未验证，
  详见 `docs/REPAIR.md` §8/§10。
- 拓扑比对以单个金属原子为节点，未做 Zr6 等 SBU 收缩；参考取 CoRE 同拓扑 ASR 记录。
- 切面终止面是几何启发式（悬空键 + 化学计量偏差），不是表面能计算；表面有悬空键是正常现象。
- 导出 7 种格式；`gaussian/orca/abacus` 未实现，会明确报 unsupported（不会静默写错）。
- CoRE 2024 的 NCR 原始 CIF 只有 curated 样例带 DOI；其余 raw 记录 `doi=None` 并在 notes 说明。
- 数据源限制：Materials Project 需要用户自己的 `MP_API_KEY`（只支持 `mp-id`/化学式检索，不支持 "ZIF-8" 这类名称）；
  AFLOW 的 `structure_id` 只支持 aurl/URL（`aflow:<auid>` 无法经公共 AFLUX 反查），MOF 覆盖很少；
  MP/AFLOW 只记录官方 usage terms 提示，工具不替用户判断再分发许可。

## 文档索引

- [docs/DESIGN.md](docs/DESIGN.md) — 目标、架构、冻结接口、数据事实、验收数字
- [docs/PIPELINE.md](docs/PIPELINE.md) — 管线逐步验收
- [docs/SOURCES.md](docs/SOURCES.md) — 数据源、缓存、拓扑判定算法与证据分级
- [docs/REPAIR.md](docs/REPAIR.md) — 补氢/无序/近邻算法与局限
- [docs/GEOM.md](docs/GEOM.md) — 标准化/超胞/切面/真空/簇的实测与坑
- [docs/EXPORT.md](docs/EXPORT.md) — 导出格式、QE 赝势、读回校验
- [docs/SKILLS.md](docs/SKILLS.md) — 技能组索引、命令对应表、路由证据
- `D:\agent-library\catalog\cif-*/SKILL.md` — 技能正文（唯一真源）
