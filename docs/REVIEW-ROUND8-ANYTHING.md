# Round 8 独立评审：cif → anything（30 格式 / 12 输入包 / convert·features·dataset / 路由）

> 评审员：`reviewer-r1`｜日期：2026-11-06｜时间盒 40–60 min（实际紧凑模式）。
> 基线：项目仓启动 `b9a6a28`，评审期间前进到 **`638b347`**（仅 docs：澄清 cube/png 不在 30 格式内，无代码/测试变化）；agent-library `feb5cdf`。两仓 `git status` 干净。
> 方法：全部自写脚本独立复算（未使用 Lead 的测试结论）；未改代码/文档。

## 0. 结论

**PASS（交付本体，含 1 个 P1 数据正确性 bug + 2 个 P2 文档口径问题需修）。** 30 格式全部写出非空、抽 8 个独立回读一致；12 个 bundle 齐全且**不含 POTCAR/UPF/skf 等 license 文件**；特征数字（ZIF-8 138/60/Zn6H60C48N24/SG 217/60 H、RDF 长度 50、SiO2 metal_fraction=0）与路由（5/5）均独立验证通过。**但 `features` 对目录输入会产生重复行（14 个文件→28 行）**，属新的 P1；测试数 248 与实测 251 不符属 P2。

| 项 | 判定 | 我的自算数字 |
|---|---|---|
| 30 格式写出 | **PASS** | `supported_formats()` = **30**；30/30 文件非空（`runs/review_round8/formats/`）；抽 8 个独立回读：vasp/cif/json（pymatgen）与 extxyz/xyz/pdb/xsf/lammps（ASE）**原子数均 138 = 输入**；vasp/cif/json 晶格 abc=14.669 ✓ |
| 模板格式 | **PASS（1 处描述小出入）** | siesta（AtomicCoordinatesFormat/LatticeVectors/NumberOfAtoms）、orca（`* xyz` + route）、dftb（Geometry/Hamiltonian/SCC）、castep（LATTICE_CART+POSITIONS_FRAC）、gaussian（route+`0 1`）、qe（三段落）关键段齐全；**ABACUS 实际写的是现代 `ATOMIC_POSITIONS` 段，而 FORMAT_INFO 文案写 "…+ ATOMS"**（见 P2-2）；文档都写明是模板/需补，未谎称可直接运行 |
| 12 输入包 | **PASS** | `supported_bundles()` = **12**（vasp/qe/cp2k/lammps/gromacs/gaussian/orca/abacus/dftb/siesta/nwchem/aims）；每个都有 files + README + `missing`；**实际文件里没有 POTCAR/UPF/skf/psf**（0 个；只有 `POTCAR.readme` 说明）；VASP bundle 有 POSCAR/INCAR(ENCUT/EDIFF/ISIF)/KPOINTS(2×2×2)/POTCAR.readme；LAMMPS `in.min` 明确留 `pair_style ... / pair_coeff ...` 占位与"choose a force field"注释 |
| CLI convert | **PASS** | `convert --to vasp,cif,xyz --json` exit 0、纯 JSON、产物 3 个；`convert --bundle vasp,qe --json` exit 0、两目录齐全；坏输入 exit 1 + `ValueError: 结构文件不存在：…` |
| CLI features | **FAIL → P1-1** | 对目录 `tests/data`：**`n_inputs=28`、rows=28、唯一路径=14**（每个 CIF 重复一次）；CSV 也是 28 行。单个/多个显式文件正常（2 文件→2 行） |
| CLI dataset | **PASS** | `dataset --from-runs runs/demo_sod_zif8 --label-key topology --json` exit 0 纯 JSON；dataset.csv **1 行**、label=`sod`；dataset_manifest.json 的 `csv_sha256` 与 CSV 实测 **一致**；复制 structures、errors=[] |
| 特征正确性 | **PASS** | ZIF-8（`zif8_cr_sod.cif`）：**natoms=138、H=60、formula=Zn6H60C48N24、SG=217 I-43m**（与我独立 `SpacegroupAnalyzer` 的 217 一致）、metal_fraction=6/138=0.043478、rdf_bins=50 且 `rdf_*` JSON 数组长度均 50；SiO2 构造结构 metal_fraction=**0.0**；`features_many([好,坏,好])` → 3 条、**仅坏路径 1 条 error** |
| 路由 / eval | **PASS** | 5 句：LAMMPS 转换→`cif-convert`/`cif-export`(31)；CP2K+QE→`cif-convert`/`cif-export`(21)；Gaussian+ORCA→`cif-convert`/`cif-export`(30)；批量特征 CSV→`cif-data`/`cif-data`(18)；runs→ML dataset→`cif-data`/`cif-data`(7)，**5/5 正确**；`eval_router --all` **89/89**、负例 0/25、槽位 11/11；`ci --fast` 绿 |
| 文档数字 | **部分 PASS（P2）** | README/PIPELINE/SKILLS/EXPORT 均含 30/12/89，模板限制写明；但**测试数 248 ≠ 实测 251**（见 P2-1） |
| 回归 | **PASS（1 处计数）** | `pytest tests`：**247 passed + 4 skipped**，exit 0（collect **251**）；`check_all --fast` **6/6**；`verify_demo` 8/8；`verify_usecases` 22/22；eval 89/89；两仓 git 干净 |

**P0：无。P1：1 个（features 目录重复行）。**

---

## 1. P1 / P2 明细

### P1-1（新发现）：`cifkit features <目录>` 对每个 CIF 重复处理一次

- 复现：
  ```powershell
  & $PY -m cifkit features tests/data --no-rdf --json     # n_inputs=28（实际 14 个 CIF）
  & $PY -m cifkit features tests/data --out runs/review_round8/features.csv --no-rdf
  # CSV 28 行，且每个路径出现两次
  ```
- 期望：14 个 CIF → 14 行；实际：**28 行（n_inputs=28/rows=28，唯一路径 14）**。
- 根因（`cifkit/cli.py::_expand_structure_inputs`，约 L373-378）：
  `found = sorted(p.glob("*.cif")) + sorted(p.glob("*.CIF")) + sorted(p.glob("*.cif.gz"))`
  —— Windows 的 glob **大小写不敏感**，`*.cif` 与 `*.CIF` 匹配同一批文件 → 每个文件被加两次（重复路径未去重）。
- 影响：批量特征表/CSV 出现静默重复行（统计、dataset 前处理会翻倍）；单个/显式文件列表不受影响（已测 2 files → 2 rows）。`dataset` 走 manifest 扫描，不受此 bug 影响（实测 1 run → 1 行）。
- 建议：`_expand_structure_inputs` 用 `dict.fromkeys(resolved_paths)` 去重，或 windows 上只保留一个大小写 glob（或 `p.glob("*")` + `suffix.lower()` 过滤）。补一条 CLI 测试：14 文件目录 → 14 行。

### P2-1：测试数口径 248 vs 实测 **251 收集 / 247 passed + 4 skipped**

- 文档/交付声明：README/PIPELINE 等写"248 条（默认 244 passed + 4 opt-in/skipped）"。
- 实测：`pytest tests` → **`247 passed, 4 skipped, 17 warnings in 208.25s`**，exit 0；`--collect-only` → **251**（新增 test_mp_live 2 条、test_robustness 8 等使总数从 226→251）。
- 4 个 skipped 为 opt-in/关键依赖（MP live 2 条需 key、`test_metals_zip_full` 需 `CIFKIT_USECASE_FULL=1` 等），属设计内。
- 建议：全仓统一写"**251 条（247 默认通过 + 4 opt-in/跳过的环境依赖用例）**"，并更新 README/PIPELINE/交付说明中的 248。

### P2-2：ABACUS 模板描述与实际段落名不一致

- `FORMAT_INFO["abacus"]` 文案写"ATOMIC_SPECIES + LATTICE_CONSTANT + **ATOMS**"，实际写出的 `structure.abacus` 使用现代 ABACUS 的 **`ATOMIC_POSITIONS`**（`ATOMIC_SPECIES/NUMERICAL_ORBITAL/LATTICE_CONSTANT/LATTICE_VECTORS/ATOMIC_POSITIONS`，结构上更完整）。
- 影响：仅文档/描述口径（用户按 ATOMS 关键字找会困惑）；不是功能错误。建议文案改成 `ATOMIC_POSITIONS`（或两种都提）。

---

## 2. 我实际跑过什么

1. `cifkit formats` → 30 格式；`export.supported_formats()` → 30。
2. 自写 `runs/review_round8/verify_round8.py`：逐格式 `write_structure(zif8_cr_sod)`（30/30 非空）+ 8 个独立回读（pymatgen/ASE，原子数/晶格）+ 7 个模板关键字 + 12 个 `write_bundle`（files/README/missing/禁止文件扫描）+ VASP/LAMMPS 模板抽查 + `convert`/`features`/`dataset` CLI（JSON 纯度/产物/坏输入）+ 特征 ZIF-8/SiO2/features_many + 文档数字 grep。
3. `cifkit features tests/data --no-rdf --json` 复核目录重复（28 vs 14）。
4. `router.py route` 5 句（cif-convert/cif-data 全部正确）；`eval_router --all` 89/89；`ci --fast`。
5. `pytest tests`（247 passed+4 skipped/208s）、`--collect-only`（251）、`check_all --fast`（6/6）、`verify_demo`（8/8）、`verify_usecases`（22/22）。
6. `git log/status` 两仓（`b9a6a28`→`638b347` docs-only 提交；工作树干净）。

## 3. 没有验证的部分

1. **模板/输入包未用真实计算软件执行**：仅做关键字/结构/占位符检查，没有跑 VASP/QE/CP2K/LAMMPS/Gaussian/ORCA/ABACUS/DFTB/SIESTA/NWChem/AIMS 的真实计算（环境无这些软件与 license 文件；与文档"不含 POTCAR/UPF/skf、需用户补"的声明一致）。
2. **30 格式中只独立回读 8 个**；其余做的是"写出后由 cifkit 自身回读通过 + 文件非空"，未逐一用第三方解析器验证（如 sdf/mol 的键级、res→SHELX、dmol .arc 等）。
3. **`pipeline --bundle`** 只通过 `convert --bundle` 验证等价产物，未单独跑 pipeline+`--bundle` 组合（时间盒）。
4. **features 的 CN/RDF 物理正确性**：只核对了长度/字段/与独立 SG 一致性，未逐元素对 CN 直方图做参考比对。
5. **dataset 的 from-library 路径与多 run**：只测 `--from-runs runs/demo_sod_zif8`（1 run）；多 run/去重/大目录未测。
6. **check_skill** 未跑（时间盒；路由 eval/ci 已覆盖技能可用性）。
7. **cube/png 不在 30 格式**：与 638b347 的文档澄清一致；未验证它们是否在其它分支实现（本轮代码无）。

## 4. 证据索引（`runs/review_round8/`）

| 文件/目录 | 内容 |
|---|---|
| `verify_round8.py`、`round8_checks.json`、`round8.log` | 30 格式/8 回读/模板/12 bundle/CLI/特征/文档断言完整结果 |
| `formats/` | 30 个写出文件（含模板） |
| `bundles/` | 12 个输入包（VASP 6 文件、LAMMPS 3 文件等） |
| `cli_convert/`、`cli_bundle/`、`cli_c2/` | convert 产物 |
| `features.csv`（28 行，P1 证据）、`features_dir.json` | features 目录重复行证据 |
| `dataset/` | dataset.csv/jsonl/structures/manifest（1 run，label=sod，csv sha 匹配） |
| `router_five.txt` | 5 句路由结果 |
| `pytest.txt`、`collect.txt`、`check_all_fast.txt` | 247 passed+4 skipped / collect 251 / 6/6 |
