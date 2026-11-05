# Round 1 独立评审（对抗式复核）— CIF 处理工作台

> 评审员：`reviewer-r1`（独立评审，未参与实现）｜日期：2026-11-05
> 评审对象：`D:\Dev\Project5-skill-cif` @ `a3056f5`（main，工作区干净）+ `D:\agent-library\catalog\cif-*`
> 方法：**不信任何自报**。所有 PASS 均由评审员本机重跑、重算或读回产物得到；不转述 manifest/测试报告。
> 约束：只写本文件与 `runs/review_round1/`，**未改任何代码/文档，未 git commit**（`git status --porcelain` 为空）。
> 环境：Python 3.14.8（venv）、pymatgen 2026.10.24、ase 3.29.0、rdkit 2026.9.1、numpy 2.5.4、scipy 1.18.1；
> Shell 为 Windows PowerShell 5.1，`$env:PYTHONIOENCODING='utf-8'`；缓存 `_cache/core-mof-2024`（44 022 768 B zip，未重新下载）。

---

## 0. 整体结论

**整体 PASS（可接受）**：DESIGN §1 的 9 条输出要求全部满足（映射到管线文档的 8 条验收，见 §2）；无 **P0**（无虚假声明、无结果错误、无阻断缺陷）。

关键复核结果（全部为本评审员独立跑出/重算，见 §4 证据）：

| 维度 | 结论 | 关键数字 |
|---|---|---|
| 诚实性：sha256 | **真** | `raw.cif` sha256 = zip 内成员 = 解出文件 = manifest = `c6939cf7…`（三方一致，非"写进去再读回"的自洽） |
| 诚实性：DOI | **真**（且标注为 curated） | Crossref `10.1021/ja204757x` = JACS 2011, 133, 12398–12401, "Capture of Volatile Iodine … ZIF-8"；NCR CIF 内无 DOI 字段，provenance 明确写 `doi_note`，未伪造 |
| 诚实性：topology verified | **可独立复算** | 自写 net 重建：目标与参考结构 CN=`{4:1.0}`、配位序列=`4,10,20,34,52,74,100,130` 完全一致；目标环分布 `4:0.125, 6:0.111, 8:0.5` 与 detail 一致 |
| 诚实性：硬编码 | **未发现** | grep 全包无"按名字/化学式返回 True"；`RAW_EXEMPLARS` 只用于筛候选，拓扑仍走结构比对；`verify(structure, expected)` 不带 record，只走结构路径 |
| 化学（补氢） | **正确** | 24 个 mIm 每个 5 H、共 +120；C–H 全部 1.1000 Å；环 C–H 面内偏差 ≤0.0046 Å；H–C–N=125.67°；甲基 H–C–H=109.47°；无 N–H；H···H 最小 1.7963 Å；RDKit 独立判键 96/96 碳键级和=4.0 |
| 几何 | **正确** | 垂直真空自算 **15.0000 Å**；slab 厚 19.2826 Å；2208=552×4=276×8；面内 |a|=24.0831=a√2、γ=60.000°、底面积 502.2896=a²√3、厚度/d111=1.96 → 立方 {111} 指纹；最大内部间隙 0.433 Å（无原子横跨真空） |
| 导出 | **一致** | VASP/CIF/XYZ 读回 2208 原子、元素计数、晶格参数、分数坐标全一致；VASP 元素行 `Zn H C N`/计数 `96 960 768 384`（按物种分组有效）；gaussian/orca/abacus 明确报错 exit 2 |
| 失败路径 | **符合文档** | 纯有机物 → evidence=unknown（非伪 verified）；空缓存报错清晰；route 缺信息 exit 2；非法 format exit 2；三类 repair fixture 数字全对 |
| 技能/测试 | **通过** | 路由第一候选 `cif-workbench`（score 82）；eval 73/73、负例 0/25 误报、槽位 11/11；`ci.py --fast` exit 0；`pytest tests -q` exit 0（119 用例）；`git status` 干净 |

**P1（文档/CLI 合同，不推翻 8 条验收，但 Round 2 应修）**：

1. `pipeline --json` 的标准输出**不是合法 JSON**（前面混入 `[step] ok …` 日志行）——与 DESIGN §6c、SKILL.md "`--json` 里 `"ok": true`" 的合同不符。
2. 文档/技能正文把 **`min_image_distance` 当成 `vacuum_measured`**（"vacuum=15.2396 / measured=15.240"），与 GEOM.md §5.1 自己的定义（垂直真空=15.000）冲突；实测 `surface.data.vacuum_measured=15.0`。
3. PIPELINE.md §7.3 粘贴的 `verify_demo.py` 输出块不可复现（写 `artifacts=10`，实测输出 `artifacts=9`）。
4. 文档里"关键产物字节数"4 项全部过期（`repaired.cif 15 489→15 379`、`preview.png 296 775→300 594`、`report.md 4 587→4 689`、`manifest.json 71 861→73 561`）。

**P0：无。**

---

## 1. 核心复核细节（每条都有原始数字）

### 1.1 干净重跑与可复现性

```powershell
$env:PYTHONIOENCODING='utf-8'
$PY='D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe'
$DEMO='帮我下载典型的RCSR为sod的mof，需要碳上补充氢，创建一个2x2x1的超胞（Supercell），沿(111)面切出表面，并加上15Å的真空层，导出为计算化学软件使用的格式。'
& $PY -m cifkit pipeline $DEMO --outdir runs\review_round1\demo --format vasp,cif,xyz --json
```

- **exit=0，耗时 14.27 s**（缓存热；文档"约 10 s"量级相符）。
- 10 个步骤全 `ok`：resolve（1.31 s）/verify-topology（0.00 s，缓存命中）/repair（1.76 s）/standardize（0.06 s）/surface（3.63 s）/vacuum（0.13 s）/export（2.56 s）/validate（1.20 s）/render（1.22 s）/manifest。
- `verify_demo.py runs\review_round1\demo` → **8/8 PASS，exit 0**（`runs/review_round1/verify_demo.txt`）。
- 与仓库留档 `runs/demo_sod_zif8/` 逐文件 sha256 对比：`raw.cif`、`repaired.cif`、`standardized.cif`、`slab.cif`、`final.cif`、`structure.vasp/.cif/.xyz` **全部字节相同**；仅 `report.md`/`manifest.json` 因时间戳与 outdir 路径不同（report diff 29 行，均为时间戳/路径行）。
- 第二次带 `--ingest` 重跑：exit 0；`cache_reused=true`；`raw.cif` sha256 不变；`library/demo_ingest/structure.vasp` 与 run 里同名文件 sha256 相同（`D1B3B30E…`）；`library/index.jsonl` 新增一条记录。

### 1.2 溯源诚实性（sha256 / DOI / 拓扑 / 硬编码）

**sha256 是"真校验"而不是自洽**（关键：manifest 的 sha 可能只是抄自己写出的文件；我另行从 zip 原始字节核对）：

```powershell
(Get-FileHash runs\review_round1\demo\raw.cif -Algorithm SHA256).Hash                       # c6939cf7…26cd3
(Get-FileHash _cache\core-mof-2024\extracted\ja204757x_si_002_ASR_pacman-c6939cf73df7.cif) # 同上
# 再直接读 zip 成员 SI/NCR/both/ja204757x_si_002_ASR_pacman.cif 求 sha256                 # 同上，10816 B
```

三方一致 = `c6939cf73df71087d558e3030f9227c535487243fdf019790924e94abef26cd3`；zip 本体 sha256 `d07a0c1f…fa8a`、44022768 B 与 manifest/index 一致。

**DOI**：`raw.cif` 头部只有 `data_`/晶胞/原子坐标，**没有任何 DOI 或期刊字段**；DOI 来自代码里 curated 表 `RAW_EXEMPLARS`，provenance 明确写 `doi_note: "DOI 来自 curated 文献关联（NCR 无元数据列）"`，record.notes 写"curated 候选（文献关联，非拓扑答案）"。评审员用 Crossref 核实 DOI 真实性：
`https://api.crossref.org/works/10.1021/ja204757x` → title "Capture of Volatile Iodine, a Gaseous Fission Product, by Zeolitic Imidazolate Framework-8"，JACS 2011, 133(32), 12398–12401。文件名前缀 `ja204757x` 与 DOI 后缀一致。同时确认 NCR 无拓扑元数据：`ASR_data_SI_20250204.csv` 中 `ja204757x` **0 行**。
⇒ "DOI 对应结构"的链条是：DOI 真实且是 ZIF-8 文献 + SI 文件名为该 DOI 的 SI + 组成/晶胞与 ZIF-8 一致；**不是**从 CIF 元数据独立证明的（文档已如实标注 curated，这一点合规）。

**拓扑 verified 可复算**（不调用 cifkit.topology）：评审员自写 `runs/review_round1/independent_topology.py`（pymatgen 只用于取周期邻居；金属=Zn、去掉金属后的连通分量=linker、attachment 平移得到商图、按 (node,shift) 状态做 BFS），对 `raw.cif` 和参考 `SI/CR/ASR/2015[Zn][sod]3[ASR]1.cif` 分别重算：

| 不变量 | 目标 raw.cif（156 原子） | 参考 CR ASR（138 原子） | manifest detail |
|---|---|---|---|
| 金属配位数分布 | `{4: 1.0}` | `{4: 1.0}` | `4-配位×1.00` |
| 配位序列（2–8 层） | `4, 10, 20, 34, 52, 74, 100, 130` | `4, 10, 20, 34, 52, 74, 100, 130` | 同 |
| 环/节点 | `4:0.125, 6:0.111, 8:0.5` | —（我的枚举器在原始胞上对 8 环给出 0.667，见 §6 未验证） | `4元环0.125, 6元环0.111, 8元环0.500` |

参考记录本身在 ASR CSV 中有 `topology(AllNodes)=sod`（number 1086，refcode `ic5028256_si_002_ASR_pacman`，DOI `10.1021/ic5028256`，natoms 138）——不是随便拿一个结构当参考。

**硬编码检查**：`Get-ChildItem cifkit -Recurse -Filter *.py | Select-String 'ZIF-8|zif8|ja204757x|2015\[Zn\]|return True'`：
- `return True` 只出现在金属判定、价态检查、几何合法性等纯函数里，没有"名字→True"；
- `ZIF-8/ja204757x/2015[Zn]` 出现在 `sources/core_mof.py`（curated 候选表/别名）与注释里；
- `topology._verify_impl` 的 `metadata` 证据分支只在**外部显式传 record** 时触发（`pipeline` 的 verify-topology 不传 record），`verified` 分支必须过配位数→配位序列→linker 比→环分布四关；签名不完整时降级 `unknown`，不会拿不完整签名判 verified。

### 1.3 补氢化学（独立脚本，未用 cifkit.repair 的结论）

脚本 `runs/review_round1/independent_chem.py`（pymatgen 仅用于 CIF 解析/周期最小像距离；键判据 = Cordero 共价半径 ×1.20，硬编码在脚本内；RDKit 仅用于独立判键）。输入 `runs/review_round1/demo/repaired.cif`：

| 检查 | 结果（实测） | 文档声称 | 判定 |
|---|---|---|---|
| 原子数/组成 | 276，Zn12 H120 C96 N48 | 276，同 | PASS |
| 每 mIm 的 H 数 | 24 个配体，每个 `C4H5N2`（11 原子），**每个 5 H** | 每 mIm 5 H | PASS |
| C–H 键长 | n=120，min=max=mean=**1.1000 Å**，std=0 | 1.100 Å | PASS |
| C 上 H 分布 | 0H:24（C2）、1H:48（环 C4/C5）、3H:24（甲基） | sp2 C-H 48 / sp3 CH3 72 | PASS |
| 咪唑 5 元环 | 24 个 `C3N2` 环，平面最大偏差 **0.0039 Å** | 环 C–H 平面内 | PASS |
| 环 C–H 的 H 离面 | 最大 **0.0046 Å** | 面内 | PASS |
| H–C–N 角（环） | min=max=mean=**125.67°** | 125.7° | PASS |
| H–C–C 角（环） | 125.67° | — | 合理 |
| H–C–H 角（甲基） | 109.47°（全部） | 109.5° | PASS |
| H–C–C 角（甲基） | 109.47°（全部） | — | 合理 |
| 甲基 C 离环平面 | ≤0.0214 Å | — | 合理 |
| N–H | **0 个**；48 个 N 全部配位 (2C,1Zn,0H)；最近 N···H 2.2044 Å | 无 N–H | PASS |
| H···H 最近距离 | **1.7963 Å**；<1.4 Å 的对数 **0** | 1.796 Å | PASS |
| H···Zn 最近距离 | 2.8672 Å | 2.867 Å | PASS |
| C 键级和 | RDKit `DetermineBonds` 对 24 个 mIm⁻ 片段（charge=-1）独立判键：24/24 成功，**96/96 碳键级和 = 4.0** | C 96/96 四配位 | PASS |

（注：C–H 键长 std=0 是因为 RDKit `AddHs(addCoords=True)` 用理想键长放置 H，非 DFT 弛豫；这是文档已声明的实现路线，不算缺陷。）

### 1.4 几何（自算，未用 cifkit.geom）

脚本 `runs/review_round1/independent_geom.py`（pymatgen 仅用于解析 CIF 与直接调用 `SlabGenerator` 做独立复核；真空/厚度/最小像距离均为评审员自写算法）：

| 检查 | 实测 | 文档/验收 | 判定 |
|---|---|---|---|
| final.cif | 2208 原子；abc=[48.166134, 48.166134, 34.282598]；angle=[90,90,60] | a=b≈48.17、c=34.283 | PASS |
| 垂直真空（自算：投影到 a×b 单位法向） | **15.000000 Å**（c_perp 34.282598 − 厚 19.282598） | ≥15 且实测 15.000 | PASS |
| slab 厚度（沿法向原子跨度） | **19.282598 Å** | ≈19.28 | PASS |
| 最小周期像距离（c 平移、i≠j） | **15.239588 Å** | 15.240（作为安全下界） | PASS |
| 最小原子间距 | 1.099922 Å（C–H） | 1.10 | PASS |
| 表面法向 | c 轴与 (a×b) 法向夹角 **0.000°**；真空沿法向 | 正交化到法向 | PASS |
| (111) 指纹 | 面内 |a|=|b|=48.1661；γ=**60.000°**；2×2 后单胞底面积=**502.2896 Å² = a_parent²√3**（a_parent=17.0293）；底胞 |a|/2=24.0831=**a√2**；d111=a/√3=9.8319，厚度/d111=**1.9612**（≈2 个 (111) 重复单元） | 立方 {111} 表面 | PASS |
| 2208 来源 | 2208 = 552×4 = 276×8；独立用 pymatgen `SlabGenerator` 从 `standardized.cif` 直接切 (1,1,1)（min_size=15/15，lll_reduce，primitive=False）：**32 个终止面中前 6 个均为 552 原子**，abc=[24.0831,24.0831,41.7131] | base 552 → 2×2 = 2208 | PASS |
| 原子是否横跨真空 | 法向相邻原子最大内部间隙 **0.432996 Å**；外部间隙=15.000 Å（真空区无原子） | 真空连续 | PASS |
| slab.cif vs final.cif | `same_as_slab_cif: true`（字节相同） | vacuum 步骤幂等（delta_c=0） | 与 GEOM §5.2 相符 |

> 关于"表面法向是否等于立方 [111]"：`SlabGenerator` 返回的 slab 已把表面法向旋转到自身 z 轴，因此不能直接拿 final.cif 的笛卡尔 z 去和母体 [111] 比（直接比会得到 54.7356°=arccos(1/√3)，那是坐标系旋转造成的假象，不是缺陷）。评审员改用**与坐标系无关的指纹**验证：面内 60° 六方胞、|a|=a√2、底面积=a²√3、厚度=2×d111 —— 这是立方晶格 {111} 面的唯一组合，足以判定切的是立方 (111)，而非 (100)/(110) 或 `frame=cell` 的伪 (111)。

### 1.5 导出读回

脚本 `runs/review_round1/independent_export.py`：

- `structure.cif` 与 `final.cif` **字节相同**（sha256 `88ae3409…6856`）。
- `structure.vasp`：读回 2208 原子；元素行 `Zn H C N`、计数行 `96 960 768 384`（和=2208）；abc/角度与 final 一致；最大分数坐标差 **1e-4**；按行检查物种确实按 `Zn96,H960,C768,N384` 分组（VASP5 物种映射有效）。
- `structure.xyz`：ase 读回 2208 原子、元素计数一致；第 2 行注释含 `cell=(48.166134,48.166134,34.282598) angles=(90,90,60)`。
- 7 格式批导出（138 原子 fixture）全部成功：`cif 8139 / cp2k 9773 / lammps 11856 / qe 6648 / vasp 9790 / xsf 9586 / xyz 8524` —— 与 EXPORT.md §5 完全一致。
- 不支持格式：`export --format gaussian`（以及 orca/abacus）→ **exit 2**，明确报 `error: unsupported format(s): gaussian; supported: cif, cp2k, lammps, qe, vasp, xsf, xyz`（`runs/review_round1/export_unsupported.txt`）。无静默成功。

### 1.6 失败路径 / 边界（10 个，均记录实际行为）

| # | 场景 | 命令要点 | 实际结果 | 与文档是否一致 |
|---|---|---|---|---|
| 1 | 纯有机 CIF + 要求 sod（无金属） | `pipeline --spec organic_spec_nobom.json` | exit 1；`verify-topology` failed，**evidence=unknown**，detail "结构中没有可用的金属节点网络…不做拓扑断言"；manifest `ok=false, failed_step=verify-topology`；report 顶部 `是否成功：❌` | 一致（诚实降级，不伪 verified） |
| 2 | 缺氢 fixture | `repair tests/data/zif8_raw_hfree.cif --add-h` | +120 H，276 原子，warnings 0，route=rdkit-capped，RDKit 24/24，`h_types={sp2C-H:48, sp3CH3:72}`，min H···H 1.7963 | 一致 |
| 3 | 满氢 fixture | `repair tests/data/zif8_cr_sod.cif --add-h` | +0 H，138 原子，warnings 0（no-op） | 一致 |
| 4 | 无序 H fixture | `repair tests/data/zif8_disordered_h.cif` | resolved_disorder=24，276 原子，H=120，warnings 0 | 一致 |
| 5 | route 缺结构信息 | `route "帮我看看这个结构怎么样"` | **exit 2** + "没有识别到拓扑/结构名/结构 id：需要用户补充要什么结构" | 一致 |
| 6 | 空缓存 `fetch --topology sod` | `CIFKIT_CACHE=<空临时目录>` | exit 1，`FileNotFoundError: CoRE MOF 2024 zip 不在缓存：…\CoREMOF2024DB.zip。请把 … （本工具不重复下载大文件）`；**未联网下载** | 一致（报错清晰） |
| 7 | 非法格式 | `export … --format nonsense` | exit 2 + 支持列表 | 一致 |
| 8 | `--spec` JSON 路径 | 无 BOM：`pipeline --spec spec_local_nobom.json` | exit 0：local 138 → standardize 276 → supercell **1104** → export cif,vasp → validate **PASS 9 checks** | 一致（PIPELINE §7.1 数字复现） |
| 9 | **UTF-8 BOM 的 spec JSON** | `Set-Content -Encoding UTF8`（Windows PowerShell 5.1 默认带 BOM） | exit 1，`error: JSONDecodeError: Unexpected UTF-8 BOM (decode using utf-8-sig)` | **文档未覆盖 → P2** |
| 10 | `--ingest` | `pipeline … --ingest` | exit 0；`library/demo_ingest/` 产物齐全，artifact sha256 与 run 相同；`library/index.jsonl` +1 条（原 4 条，均为 `demo_sod_zif8`） | 一致（注：写入 `library/`，gitignore，未污染仓库） |

评审员自选的额外 adversarial case：

| # | 场景 | 结果 |
|---|---|---|
| A | `frame=cell` 字面对照 | 2208 原子；abc=[38.0787,38.0787,42.6509]，γ=**101.537°**（文档 [37.876,37.876,42.485]/101.54 用的是 a=16.939 的 CR fixture；用 demo 的 a=17.029 重跑，长度按 17.029/16.939=1.0053 缩放、角度完全一致）→ 证明确实不是立方 (111)（γ≠60° 且 c 不垂直面内），文档 caveat 成立 |
| B | 金属簇提取 | `geom tests/data/zif8_cr_sod.cif --cluster sbu` → **45 原子，Zn1 H20 C16 N8**（= 1 Zn + 4 个完整 mIm），与 GEOM §6 一致 |
| C | COD 联网下载 | `pipeline --spec cod_spec.json`（source=cod, id=7111973）→ exit 0，`cod:7111973` 348 原子（H 完整），repair 解析无序 24 → 276，validate PASS 9 checks |
| D | VASP 物种顺序有效性 | POSCAR 内原子按 `Zn96,H960,C768,N384` 连续分组；按同顺序与 final.cif 比物种 0 处不一致，分数坐标最大差 1e-4 → 不是"元素行对但坐标错位"的隐蔽错误 |
| E | `route --json` 可解析性 | 合法 JSON（`spec.topology=sod, supercell=[2,2,1], surface=[1,1,1], vacuum=15.0`）；与 `pipeline --json`（P1-1）形成对照 |

### 1.7 技能路由 / eval / CI

| 命令 | 结果 | exit |
|---|---|---|
| `py -3 D:\agent-library\router.py route --agent dsh "<原句>"` | intent=`cif-structure-pipeline`；**第 1 候选 `cif-workbench` score=82**（第 2–5 为 fetch/export/geometry/repair） | 0 |
| `py -3 scripts\eval_router.py --all` | cases=73；intent top1 73/73；skill top1 73/73；skill top5 73/73；negatives=25 fp=0 (0.0%)；slot 11/11 | 0 |
| `py -3 scripts\ci.py --fast` | 同上三套评测全绿 | 0 |

SKILL.md 命令抽查：`pipeline`、`verify_demo`、`route`、`--spec`、`fetch`、`repair`、`geom`、`export`、`formats`、`selftest` 均实跑可用（见 §4）。发现两处号码错误（P1-2/P1-4）。

### 1.8 测试与仓库状态

- `pytest tests -q` → **exit 0**；进度点 72+47=119 全部通过；`--collect-only` 按模块统计 = export 20 / geom 34 / pipeline 3 / repair 12 / sources 17 / spec 6 / topology 15 / validate 12 = **119**，与 README 测试分布完全一致。
- `cifkit selftest --verbose` → **7/7 passed，exit 0**。
- `git status --porcelain` → **空（干净）**；`runs/`、`library/`、`_cache/` 均被 `.gitignore` 覆盖，评审产物未进入版本库。

---

## 2. DESIGN §1 逐条 PASS/FAIL

DESIGN §1 实际有 **9 条**编号要求；PIPELINE/README/verify_demo 把它们合并成 **8 条**（第 8+9 合成"manifest + 可复现"）。下表按 9 条判定，并标注对应的 8 条验收项。

| # | DESIGN §1 要求 | 判定 | 证据指针（均为本评审员实测） |
|---|---|---|---|
| 1 | 真实下载/缓存的 SOD MOF（ZIF-8），带来源/DOI/sha256 | **PASS** | zip 成员→raw.cif sha 三方一致 `c6939cf7…`；Crossref DOI 核实；`runs/review_round1/demo/manifest.json` source.record/provenance；`_cache/core-mof-2024/CoREMOF2024DB.zip` |
| 2 | 补氢前后对照（缺多少→补多少，逐碳价态） | **PASS** | 0→120，156→276；`independent_chem.py`：C–H 1.1000、96/96 C 键级和=4、无 N–H；`runs/review_round1/independent_chem.json` |
| 3 | 2x2x1 = 原胞×4；surface 请求下作为 slab 面内重复并写明 frame | **PASS** | manifest surface：`frame=slab, in_plane_reps=[2,2], base=552, after=2208`；report.md 步骤行含 `frame=slab`；`independent_geom.json` 独立复算 552 |
| 4 | (111) slab（表面周期、层厚、终止面选择依据） | **PASS**（有 P2 证据位置瑕疵） | 层厚 19.2826、终止面 shift 0.360055/score 明细、32 候选均在 manifest `surface.data`；report.md 只给摘要（见 P2-3）；{111} 指纹自算通过 |
| 5 | 真空 ≥15 Å（实测非名义值） | **PASS** | 自算垂直真空 15.0000 Å；最小周期像 15.2396 Å；`independent_geom.json` |
| 6 | 计算化学格式导出（≥VASP + CIF/XYZ） | **PASS** | VASP 2208 原子/元素行/计数/分数坐标读回一致；CIF 与 final 字节相同；XYZ ase 读回一致；`independent_export.json` |
| 7 | 结构校验报告 + 预览图 | **PASS** | 12 checks，11 ok + `dangling_bonds` WARN；`preview.png` 300 594 B 可打开（1200×900）；report.md 含来源/步骤/校验/产物四节 |
| 8 | manifest.json 全链路溯源（查询/来源/下载/每步耗时/校验/工具版本） | **PASS** | manifest 含 query/spec/environment（python 3.14.8、pymatgen 2026.10.24…）/source.record+provenance/steps（含 elapsed_s）/validation/artifacts（9 项，见 P2-4） |
| 9 | 同一查询重跑可复现（缓存命中、不重复下载） | **PASS** | 二跑 14.27 s、`cache_reused=true`、raw sha 不变、8 个结构产物逐字节相同；zip mtime/size 未变 |

**8 条验收（README/PIPELINE 口径）**：第 1–8 项对应表内 1–8，全部 PASS（8/8，`verify_demo.py` 复现通过）。

---

## 3. 问题清单（P0 / P1 / P2）

### P0 — 阻断 / 虚假声明 / 结果错误

**无。** 未发现：伪造 sha256、DOI 张冠李戴、拓扑伪 verified、按名字硬编码、化学/几何结果错误、把"没验证"写成"已验证"。

### P1 — 重要缺陷 / 文档与实现不符（建议 Round 2 修）

#### P1-1 `pipeline --json` 输出不是合法 JSON（CLI 合同被破坏）

- 复现：
  ```powershell
  & $PY -m cifkit pipeline "<原句>" --outdir runs\review_round1\demo_ingest --format vasp,cif,xyz --ingest --json
  & $PY -m cifkit pipeline --spec runs\review_round1\spec_local_nobom.json --outdir runs\review_round1\spec_run --json
  ```
- 期望（DESIGN §6c / SKILL.md "`--json` 里 `"ok": true`" / PIPELINE §7.1）：stdout 是 RunResult JSON，可直接 `json.loads`。
- 实际：stdout 先是每步的人类日志行，例如第一行 `[resolve] ok core-mof:SI/NCR/… atoms=156 DOI=…`，JSON 在后面；`json.loads` 直接 `JSONDecodeError`。
- 证据：`runs/review_round1/pipeline_ingest_stdout.txt`、`runs/review_round1/spec_run_stdout.txt`（第一行即 `[resolve] ok …`）；`runs/review_round1/route_json.txt` 证明 `route --json` 是干净的（对照）。
- 影响面：任何用 `--json | ConvertFrom-Json` / 脚本消费结果的用法都会失败；文档里"exit code=0 且 `--json` 里 `"ok": true`"的验收步骤实际上无法按字面执行。不推翻管线结果本身。
- 建议：`_Ctx.step` 的 `print` 改 `file=sys.stderr`，或 `--json` 时静默；补一条 pytest 断言 `json.loads(stdout)`。

#### P1-2 文档/技能正文把 `min_image_distance` 当作 `vacuum_measured`（违反自身定义）

- 位置：`docs/PIPELINE.md` §7.2 第 154–155 行；`D:\agent-library\catalog\cif-workbench\SKILL.md` 第 177–178 行。
  - 写：`surface … vacuum_measured=15.2396`；`vacuum target 15.0 → measured 15.240 Å`。
- 实测（同一份 `runs/review_round1/demo/manifest.json`）：`surface.data.vacuum_measured = 15.0`、`surface.data.min_image_distance = 15.2396`；`vacuum.data.measured = 14.999999999999993`。`docs/GEOM.md` §5.1 也明确要求"真空层厚度必须用 `vacuum_perp`（15.000），不能引用 `min_image_distance`"。
- 期望 vs 实际：文档说 measured=15.240；实际垂直真空 measured=15.000，15.2396 是最小周期像距离。README/DESIGN/GEOM 这三处是对的，PIPELINE 与技能正文错——自相矛盾。
- 证据：`runs/review_round1/demo/manifest.json`、`runs/review_round1/independent_geom.json`（垂直 15.0000、min-image 15.239588）。
- 建议：把这 4 行改成 `vacuum_measured=15.000；min_image_distance=15.2396`，并同步技能正文。

#### P1-3 PIPELINE §7.3 粘贴的独立验收输出不可复现（`artifacts=10` vs 实测 9）

- 复现：`& $PY scripts\verify_demo.py runs\review_round1\demo`
- 期望（PIPELINE §7.3 粘贴块）：`[PASS] 8 report.md / manifest 完整 report=True steps=10 artifacts=10`
- 实际：`report=True steps=10 artifacts=9`（8/8 PASS 其余一致）。
- 证据：`runs/review_round1/verify_demo.txt`；`manifest.json` 的 `artifacts` 键只有 9 项（缺 manifest/report 自身，见 P2-4）。
- 影响：这是一段"独立验收证据"的转抄，数字对不上会让复核者怀疑其余粘贴输出；建议重新生成并标明 run id/时间。

#### P1-4 文档关键产物字节数 4/4 全部过期

| 文件 | 文档声称 | 实测（本次重跑） | 出处 |
|---|---|---|---|
| `repaired.cif` / `standardized.cif` | 15 489 B | **15 379 B** | PIPELINE §7.4、catalog SKILL.md 第 185 行 |
| `preview.png` | 296 775 B | **300 594 B** | PIPELINE §7.4 |
| `report.md` | 4 587 B | **4 689 B**（留档 demo）/ 4 678 B（本次重跑，路径长度不同） | PIPELINE §7.4 |
| `manifest.json` | 71 861 B | **73 561 B**（留档）/ 73 465 B（本次） | PIPELINE §7.4 |

- 其余字节数（raw.cif 10 816、slab/final/structure.cif 121 521、structure.vasp 152 719、structure.xyz 134 797）与实测一致。
- 期望 vs 实际：文档声称的四个数字在本机同一 build 上均不可复现；不影响 8 条验收，但属于"证据数字不实"。
- 建议：重新生成文档中的产物表（或去掉易变字节数，改列 sha256 前 12 位）。

### P2 — 改进建议

1. **`--spec` 对 UTF-8 BOM JSON 不健壮**：Windows PowerShell 5.1 的 `Set-Content/Out-File -Encoding UTF8` 会写 BOM，`json.loads` 报 `Unexpected UTF-8 BOM`，CLI 只是原样抛出 `JSONDecodeError`（exit 1）。建议 `Path.read_text(encoding="utf-8-sig")` 或捕获后给出"spec JSON 带 BOM，请另存为 UTF-8 无 BOM"。复现：`runs/review_round1/spec_local_run.json`（BOM）vs `spec_local_nobom.json`（OK）；原始报错 `runs/review_round1/bom_spec_error.txt`。
2. **失败 run 的 report.md 重复记录失败步骤、且缺第 3 节**：`verify-topology` 失败时先被 `_step_verify_topology` 记一次 failed，异常再被外层循环记一次，报告出现两个 `### ❌ verify-topology`；且 `validation` 未运行导致标题从"## 2"跳到"## 4"。复现：`runs/review_round1/organic_fail/report.md`。建议外层捕获时跳过已记录的步骤。
3. **report.md 未包含 slab 厚度/终止面选择依据**（DESIGN §1 第 4 条要求"层厚、终止面选择依据"）：report 只有一行 `hkl/frame/reps/abc/vacuum`，厚度 19.2826、终止面 `shift=0.360055`、32 个候选的评分只在 `manifest.json` 里。建议 report 增加一节 slab 摘要（从 `info` 取）。
4. **`manifest.artifacts` 不包含 manifest/report 自身**（9 项 vs `RunResult.artifacts` 11 项）：`pipeline._step_commit` 在 `finish_run` 写 manifest/report 之前就固化了 `manifest["artifacts"]`。建议写完 report 后回填。
5. **`verify_demo.py` 两处检查名/实现不一致**：第 1 项名为"来源追溯（sha256/record/DOI）"但代码只比 sha256 和打印 record_id，**没有检查 DOI 是否存在/合法**；第 8 项"report.md / manifest 完整"只 grep 4 个中文字段。建议：DOI 非空断言；或改检查名以免高估独立验收强度。
6. **DESIGN §1 是 9 条，管线文档/verify 用"8 条"**（第 8+9 合并）。建议在 DESIGN §1 或 PIPELINE §3 明确"9 条 → 8 项验收"的映射，避免复核者按字面找第 9 条。
7. **standardize 的"整数倍守卫"依据未落盘**：manifest `standardize.data` 只有 `natoms`，没有 `kept/reason/primitive_atoms`（GEOM §2 声称 info 里有）。行为本身正确（276 未被翻倍成 552，已用 `standardized.cif` 原子数验证），但溯源证据链弱。建议把 `info` 摘要写入 step.data。

---

## 4. 我实际跑过的东西（命令 + 关键输出摘要）

> 全部在 `D:\Dev\Project5-skill-cif`、`$env:PYTHONIOENCODING='utf-8'` 下执行；`$PY=.venv\Scripts\python.exe`。

**主链路**
1. `& $PY -m cifkit --version` → `cifkit 0.1.0`；`& $PY --version` → 3.14.8。
2. `& $PY -m cifkit selftest --verbose` → 7/7 passed，exit 0（`runs/review_round1/selftest.txt`）。
3. `& $PY -m cifkit pipeline "<原句>" --outdir runs\review_round1\demo --format vasp,cif,xyz --json` → **exit 0，14.27 s**，10 步全 ok，validation PASS checks=12（`pipeline_stdout.json`）。
4. `& $PY scripts\verify_demo.py runs\review_round1\demo` → **8/8 PASS，exit 0**（`verify_demo.txt`）。
5. 与 `runs/demo_sod_zif8/` 逐文件 `Get-FileHash`：8 个结构产物 sha256 全同；report/manifest 因时间戳/路径不同。
6. `pipeline … --ingest --outdir runs\review_round1\demo_ingest` → exit 0；`library/demo_ingest/structure.vasp` sha256 = run 内同名文件；`library/index.jsonl` 5 行（+1）。

**诚实性**
7. `Get-FileHash runs\review_round1\demo\raw.cif` / extracted CIF / zip 成员（`System.IO.Compression` 读原始字节求 SHA256）→ 三者均 `c6939cf7…26cd3`，10816 B。
8. zip 本体 `Get-FileHash` → `d07a0c1f…fa8a`，44 022 768 B（与 manifest/index 一致）。
9. `Select-String ASR_data_SI_20250204.csv 'ja204757x'` → 0 行；`'2015\[Zn\]\[sod\]3'` → 1 行：`topology(AllNodes)=sod, DOI=10.1021/ic5028256, natoms=138`。
10. Crossref `GET https://api.crossref.org/works/10.1021/ja204757x` → 200，JACS 2011 133(32) 12398–12401，标题为 ZIF-8 碘吸附论文。
11. `Get-ChildItem cifkit -Recurse -Filter *.py | Select-String 'ZIF-8|zif8|ja204757x|return True'` → 无名字→True 逻辑；curated 表只在 sources。
12. `& $PY runs\review_round1\independent_topology.py` → 目标/参考 CN `{4:1.0}`、CS `[4,10,20,34,52,74,100,130]` 完全一致；目标环 `4:0.125,6:0.111,8:0.5`（`independent_topology.json`）。

**化学**
13. `& $PY runs\review_round1\independent_chem.py` → 276 原子；24×`C4H5N2`（每 mIm 5 H）；C–H 全部 1.1000 Å；环平面偏差 ≤0.0039 Å；H–C–N 125.67°；甲基 H–C–H 109.47°；N–H 0；H···H 1.7963 Å；RDKit 96/96 C 键级和=4.0（`independent_chem.json`）。

**几何**
14. `& $PY runs\review_round1\independent_geom.py` → 垂直真空 15.000000 Å；厚 19.282598；min-image 15.239588；γ=60.000°；底面积 502.2896=a²√3；独立 `SlabGenerator` 首 6 个终止面均 552 原子（`independent_geom.json`）。
15. `& $PY -m cifkit geom tests\data\zif8_cr_sod.cif -o … --standardize --surface 1 1 1 --supercell 2 2 1 --vacuum 15 --json` → 2208 原子，abc 47.910/47.910/33.922，base 552，厚 18.922，vacuum 15.0，min-image 15.1978，36 候选、shift 0.360055 —— 逐项复现 GEOM §4.3。
16. `geom runs\review_round1\demo\repaired.cif … --surface-frame cell` → 2208 原子，abc 38.079/38.079/42.651，γ=101.537°（frame=cell caveat 成立）。
17. `geom tests\data\zif8_cr_sod.cif --cluster sbu` → 45 原子 Zn1 H20 C16 N8。

**导出**
18. `& $PY runs\review_round1\independent_export.py` → VASP/CIF/XYZ 读回 2208、元素计数/晶格/分数坐标一致；VASP `Zn H C N` + `96 960 768 384`（`independent_export.json`）。
19. `& $PY -m cifkit export tests\data\zif8_cr_sod.cif --format vasp,cif,xyz,lammps,qe,cp2k,xsf -o runs\review_round1\export_all` → exit 0，7 文件字节数与 EXPORT.md 完全一致。
20. `export … final.cif --format gaussian|orca|abacus` → 均 exit 2 + `unsupported format(s)`（`export_unsupported.txt`）。

**失败路径**
21. 纯有机：`pipeline --spec organic_spec_nobom.json` → exit 1，evidence=unknown，report ❌，manifest failed_step=verify-topology（`organic_fail/`）。
22. BOM spec：`pipeline --spec spec_local_run.json`（PS 5.1 写的 BOM）→ exit 1 `JSONDecodeError: Unexpected UTF-8 BOM`。
23. 正常 spec：`pipeline --spec spec_local_nobom.json` → exit 0，138→276→1104，validate PASS 9。
24. `repair` 三 fixture → +120→276 / +0→138 / disorder 24→276（`repair_*.json`）。
25. `route "帮我看看这个结构怎么样"` → exit 2（缺结构信息）。
26. 空 `CIFKIT_CACHE` + `fetch --topology sod` → exit 1，清晰 FileNotFoundError，未联网下载（`fetch_empty_cache.txt`）。
27. COD：`pipeline --spec cod_spec.json`（id 7111973）→ exit 0，348→276 原子，PASS 9。
28. `pipeline --json` 可解析性探针（两次）→ 无效 JSON；`route --json` → 有效 JSON。

**技能/测试/仓库**
29. `py -3 D:\agent-library\router.py route --agent dsh "<原句>"` → `cif-workbench` 第 1（score 82）。
30. `py -3 scripts\eval_router.py --all` → 73/73、neg 0/25、slot 11/11，exit 0。
31. `py -3 scripts\ci.py --fast` → exit 0。
32. `& $PY -m pytest tests -q` → exit 0；`--collect-only` 各模块 20/34/3/12/17/6/15/12 = 119。
33. `git status --porcelain` → 空；`& $PY -m cifkit formats` → 7 种格式。

---

## 5. 文档数字 vs 实测（除 §3 已列出的 P1 外，其余均复现）

| 文档位置 | 声称 | 实测 | 判定 |
|---|---|---|---|
| README 表格 | 2208 原子；552→2208；a=b≈48.17；厚≈19.28；c⊥=34.283；真空 15.000（min-image 15.240） | 全中 | PASS |
| README 表格 | +120 H、156→276、每 mIm 5 H、环 C–H 平面内、无 N–H | 全中 | PASS |
| README | 12 项校验、dangling_bonds 为 WARN；8/8 | 全中 | PASS |
| README | 119 passed；测试分布 20/34/3/12/17/6/15/12 | 全中 | PASS |
| README | eval 73/73、负例 0/25、槽位 11/11、ci 通过 | 全中 | PASS |
| DESIGN §7.1 | 2208 / 552 / 真空 15.000 / 15.240 / 276 / 12 项 / ~10 s | 全中（14.27 s 同量级） | PASS |
| GEOM §4.3 | 47.910、33.922、18.922、36 候选、shift 0.360055、vacuum 15.000、min-image 15.198 | 逐项复现 | PASS |
| GEOM §5.3 | demo final：厚 19.2826、c 34.2826、真空 15.0000、min-image 15.2396 | 全中 | PASS |
| GEOM §6 | sbu 45 原子 Zn1 C16 N8 H20 | 全中 | PASS |
| EXPORT §5 | 7 格式字节数（9771–9790/8139/8505–8524/11856/6648/9754–9773/9586） | 全中 | PASS |
| SOURCES | 8300 / 2664 / 5636 / 7 条 sod / CSV 1372 行 | 全中（`index.json`、CSV 实测） | PASS |
| REPAIR §1/§8 | route、24/24、h_types、per_ligand、min 距离、C 96/96 | 全中 | PASS |
| PIPELINE §7.1 | spec 路径 138→276→1104、PASS(9) | 全中 | PASS |
| PIPELINE §7.2 | `vacuum_measured=15.2396`；`vacuum measured 15.240` | **错**（应 15.000 / 15.000；15.2396 是 min_image_distance） | **P1-2** |
| PIPELINE §7.3 | verify_demo `artifacts=10` | **错**（实测 9） | **P1-3** |
| PIPELINE §7.4 / catalog SKILL.md | 4 个字节数 | **错** | **P1-4** |
| PIPELINE §7.2 | surface elapsed 17.95 s | 本次 3.63 s（机器负载差异，非缺陷） | 说明 |

---

## 6. 我没有验证的部分（如实列出）

1. **冷启动/首次下载路径**：未跑 `bootstrap_data.py`，未验证"新机器首次下载 44 MB、首跑约 100 s"的声明（按任务要求不重复下载大文件；本次全部走已就绪 `_cache/`）。
2. **环签名对"原始胞"参考的独立复算**：我的环枚举器在参考的 6-金属原始胞上给出 8 元环/节点=0.667，而 manifest 声称参考与目标一致（0.5）。差异可归因于我自写枚举器对"同原子不同平移重复出现在环上"的规范化处理不完善（目标胞 12 金属时我的结果与 manifest 完全一致：4:0.125/6:0.111/8:0.5）。因此"环分布一致"这一子项**只验证到目标结构侧**，参考侧的相等性依赖 cifkit 自身代码；配位数与配位序列则已由我完全独立复算并一致。
3. **DOI 与 SI 文件的唯一绑定**：Crossref 只能证明 DOI 是真论文（ZIF-8 碘吸附）；CIF 内无 DOI 字段，DOI↔`ja204757x_si_002` 的绑定依赖文件名与 curated 表（文档已如实标注 curated）。未从出版社 SI 页面下载原文比对。
4. **非 (111) 面、高指数晶面、`Zr6` SBU 收缩、AllNodes/SingleNodes 不同的拓扑**：均未测（属文档声明的范围外/局限）。
5. **`frame=slab` 的物理优越性**（表面能/极性终止面）未评估——文档自己说终止面是几何启发式，我按此口径只验证了几何自洽与 {111} 指纹。
6. **COD 只测了 id=7111973 的下载与 repair 路径**；COD 名称检索、COD 与缓存命中、Materials Project 数据源均未测。
7. **`min_image_distance` 的"3D 全像最近距离"另一口径**：我复现的是 c 平移口径（15.2396，与 manifest 一致）；未验证文档"横向错位下 3D 最小像距离更大"的论证。
8. **大规模/内存边界**：(hkl) 高指数 >30000 原子拒绝、`primitive=True` OOM 描述、>1 万原子补氢性能——均未实测。
9. **ingest 库内容的完整审计**：只验证了新条目的 artifact sha256 与 run 一致、index 追加 1 行；`library/` 里原有的 4 条 `demo_sod_zif8` 记录（开发期遗留）未逐条审计。
10. **pytest 的 "119 passed" 汇总行**：PowerShell 5.1 下 `-q` 的汇总行未被管道捕获（看到 72+47 进度点、exit 0、collect-only 119）；我按退出码 + 点数 + 收集数判定全绿，未逐条读断言输出。

---

## 7. 证据文件索引（`runs/review_round1/`）

| 文件/目录 | 内容 |
|---|---|
| `demo/` | 本次干净重跑的 13 个产物（manifest/report/raw/repaired/standardized/slab/final/structure.vasp/.cif/.xyz/preview.png/plan.json） |
| `demo_ingest/` | 带 `--ingest` 的第二次重跑产物 |
| `verify_demo.txt` | 8/8 PASS 原始输出 |
| `pipeline_stdout.json` / `spec_run_stdout.txt` / `pipeline_ingest_stdout.txt` | `--json` 污染证据（P1-1） |
| `pytest.txt` / `pytest_collect.txt` / `pytest_summary.txt` | 测试证据（exit 0、119 用例） |
| `independent_chem.py/.json/.log` | 补氢独立复核（§1.3） |
| `independent_geom.py/.json/.log` | 真空/厚度/法向/552/2208 独立复算（§1.4） |
| `independent_topology.py/.json`、`independent_topology2.py/.log` | 配位数/配位序列独立复算（§1.2；环枚举第二版） |
| `independent_export.py/.json/.log` | VASP/CIF/XYZ 读回一致（§1.5） |
| `repair_hfree.json` / `repair_cr.json` / `repair_disordered.json` + `fix_*.cif` | 三类 repair fixture |
| `organic.cif` / `organic_spec*.json` / `organic_fail/` | 纯有机物 → topology=unknown 失败路径 |
| `spec_local_nobom.json` / `spec_run/` | `--spec` 正常路径（138→276→1104，PASS 9） |
| `spec_local_run.json` | 带 BOM 的 spec（复现 P2-1） |
| `bom_spec_error.txt` | BOM spec 的原始报错（exit 1，JSONDecodeError） |
| `fetch_empty_cache.txt` | 空缓存报错 |
| `export_unsupported.txt` | gaussian/orca/abacus 明确报错 exit 2 |
| `export_all/` + `export_all.log` | 7 格式导出与字节数 |
| `geom_check.json/.cif` | GEOM §4.3 数字逐项复现 |
| `cell_frame.json/.cif`、`cluster.json/.cif` | frame=cell 对照、SBU 提取 |
| `cod_run/`、`cod_run_stdout.txt`、`cod_spec.json` | COD 联网下载路径 |
| `router_route.txt`、`eval_router.txt` | 路由 / eval / ci 原始输出 |
| `selftest.txt`、`formats.txt`、`route_json.txt` | 自检、格式列表、route --json 对照 |
| `empty_cache/` | 空缓存临时目录（未下载任何文件） |
