# 羧酸根 MOF 补氢 fixture 说明（Round-2 WP2）

> 记录 `tests/data/` 下本轮新增 fixture 的**来源、真实性、生成方式、原子数/公式与期望补氢数**。
> 真实数据库 CIF 与「我们删 H 生成的 synthetic fixture」严格区分，不冒充数据库原始文件。
> 验收测试：`tests/test_repair_carboxylate.py`；算法说明：`docs/REPAIR.md` §8。

## 0. 重要更正：MOF-5 的真实记录

WP3 拓扑评审确认：`SI/CR/ASR/2015[Zn][pcu]3[ASR]2.cif`（Zn4 H8 C24 O14）**不是 MOF-5**
（它是 Zn4O2 + 三联苯四羧酸根、`topology(AllNodes)=scn` 的 pcu/scn MOF，DOI 10.1039/C5TA04552E；
`--add-h` 为 no-op，0 added / 0 warnings）。**真正的 MOF-5 记录**是 CoRE MOF 2024：

- coreid **`2007[Zn][pcu]3[ASR]3`**，refcode `ja074366osi20070816_031204_ASR_pacman`，
  DOI **10.1021/ja074366o**，topology pcu，
  公式 **Zn8 H24 C48 O26 = 2 × Zn4O(BDC)3**，106 原子，primitive rhombohedral
  a=18.2486 Å、α=60°（index.json 的 `heavy_key=Zn:1|C:6|O:3.25`）。
  同类的 `2011[Zn][pcu]3[ASR]8` 也对应 MOF-5，但其 CR 文件含额外 H/几何异常
  （直接补氢会 added_h=27 并报 C 五价 warning），故未采用。

此外用 **COD 真实数据库 CIF** 做独立交叉验证：COD 4340010（原始文件本身无 H，
Zn32 C192 O104，Fm-3m a=25.555 Å）与 COD 1516287（H 完整，Zn32 H96 C192 O104，a=25.825 Å）。
两套来源的成分一致（每 Zn 对应 3 H、6 C、3.25 O）。

## 1. fixture 一览

| fixture | 真实性 | 来源 | 原子数 | 公式 | 期望补 H |
|---|---|---|---|---|---|
| `mof5_hfree.cif` | **synthetic**（从 CoRE CR 删全部 24 H） | CoRE `SI/CR/ASR/2007[Zn][pcu]3[ASR]3.cif`（coreid `2007[Zn][pcu]3[ASR]3`，DOI 10.1021/ja074366o） | 82 | Zn8 C48 O26（a=18.2486 Å, α=60°） | **24**（6 BDC × 4 环 C-H；2 个 μ4-O oxo 不加） |
| `mof5_h.cif` | **真实**（CoRE CR 原始 CIF，H 完整） | 同上 | 106 | Zn8 H24 C48 O26 | 0（no-op 对照） |
| `mof5_cod_hfree.cif` | **真实**（COD 4340010，原始 CIF 本身无 H） | COD [4340010](https://www.crystallography.net/cod/4340010.html) | 328 | Zn32 C192 O104（Fm-3m a=25.555 Å） | **96**（24 BDC × 4） |
| `mof5_cod_h.cif` | **真实**（COD 1516287，H 完整） | COD [1516287](https://www.crystallography.net/cod/1516287.html) | 424 | Zn32 H96 C192 O104（a=25.825 Å） | 0（no-op 对照 / 交叉验证） |
| `uio66_hfree.cif` | **synthetic**（从 CoRE CR 删全部 28 H） | CoRE `SI/CR/ASR/2015[Zr][fcu]3[ASR]1.cif`（coreid `2015[Zr][fcu]3[ASR]1`，refcode `c5cp03920g2_ASR_pacman`，DOI 10.1039/C5CP03920G，topology fcu） | 86 | Zr6 C48 O32（a=14.7368 Å, α=60°） | **28**（24 环 C-H + 4 μ3-OH） |
| `uio66_h.cif` | **真实**（CoRE CR 原始 CIF） | 同上 | 114 | Zr6 H28 C48 O32 | 0（no-op 对照） |
| `hkust1_hfree.cif` | **synthetic**（从 CoRE NCR 删全部 24 H） | CoRE `SI/NCR/mofchecker/c8tc01703d2_ASR_pacman.cif`（refcode `c8tc01703d2_ASR_pacman`，tbo） | 132 | Cu12 C72 O48（a=18.6538 Å, α=60°） | **24**（8 BTC × 3 环 C-H；羧酸根 O/Cu 桨轮不加） |
| `hkust1_h.cif` | **真实**（CoRE NCR 原始 CIF，H 已全） | 同上 | 156 | Cu12 H24 C72 O48 | 0（no-op 对照） |
| `terephthalic_acid_hfree.cif` | **synthetic**（RDKit 生成的对苯二甲酸分子晶体，删 2 个酸 H） | RDKit ETKDG seed=42 + MMFF94，15 Å 立方盒 | 16 | C8 H4 O4 | **2**（自由 -COOH 的 2 个 O-H） |
| `uio66_raw_ncr_h24.cif` | **真实**（CoRE NCR，仅留作溯源，不参与验收） | CoRE `SI/NCR/mofchecker/c9sc01301f2_1_FSR_pacman.cif` | 110 | Zr6 H24 C48 O32 | 见 §4（几何不可判，不用于验收） |

fixture 文件 sha256（用于复现/防篡改）：

```text
mof5_hfree.cif                9f4df006bef2e952c512b7e547ed44e650bf9d3cd23501eafc6087f85141b12f
mof5_h.cif                    ebbb01ca08ccee5fa01bc3858469cc080db7e8d6e62d0451db157b9777b88fdb
mof5_cod_hfree.cif            2c8a2f003c19a8f60e9504496744eff7e0af86d76a2a6ffbbd21fb381995800c
mof5_cod_h.cif                1394b3146d5972ef724e11f56a782dbd828041e8fc7385e9660f009ff7960f93
uio66_hfree.cif               752ecb921b2a3d4d0d860ed9e71c96f0f84ffab44b4e1ce281a6b17144cb536e
uio66_h.cif                   f3584bc63f1f47b8026c8592fe466010a10143917bb0ef71a0eaec9fd38a3b45
hkust1_hfree.cif              8f771929a59ec4e195dcca5aaff0debfc1bf9c623e60b530d484b1fd345dbe86
hkust1_h.cif                  8a4af937aea0e79a7d62cbaf66665fde7468375eddfb16ba0f4e1d3fa0cd05a6
terephthalic_acid_hfree.cif   4aa4534716522cdf0f508f4224efcec854c5df2a558fa99aa1b5b8bbfdf36f23
uio66_raw_ncr_h24.cif         cac65895e1cc491c06bfad17270130048533c85824eea0eae2dbaf9e99bec170
```

## 2. 真实来源与生成方式

### 2.1 MOF-5（CoRE `2007[Zn][pcu]3[ASR]3` + COD 交叉验证）

- 真实 H 完整 CIF：CoRE 2024 `SI/CR/ASR/2007[Zn][pcu]3[ASR]3.cif`
  （cache zip 内文件 sha256=`f32e6e751798e4de182a4374297863515270f6e677c96747c8683eec6cc6cea9`），
  原样复制为 `mof5_h.cif` + 顶部 provenance 注释。
  该文件 106 原子、Zn8 H24 C48 O26；2 个 μ4-O 各与 4 个 Zn 成键（Zn–O = 1.943 Å），
  6 个 BDC 每个 4 个环 C–H；`repair --add-h` 为 no-op（0 added / 0 warnings）。
- `mof5_hfree.cif` 生成方式（synthetic，已标注）：
  ```python
  from pymatgen.core import Structure
  from pymatgen.io.cif import CifWriter
  cr = Structure.from_file("SI/CR/ASR/2007[Zn][pcu]3[ASR]3.cif")
  heavy = Structure(cr.lattice,
                    [s.species_string for s in cr if s.species_string != "H"],
                    [s.frac_coords for s in cr if s.species_string != "H"],
                    coords_are_cartesian=False, validate_proximity=False)
  CifWriter(heavy, symprec=None).write_file("tests/data/mof5_hfree.cif")
  ```
  即：只删 H（24 个），重原子坐标/晶胞完全不变 → 82 原子 Zn8 C48 O26。
- 独立**真实**交叉验证：COD 4340010（原始下载 sha256=`87af3d9397e6bae59140c63cec0beae3063df5f39420a457214d261d4f659abb`，
  该 CIF 本身无 H）复制为 `mof5_cod_hfree.cif`；COD 1516287
  （原始下载 sha256=`4da88094b25093673f33a8bce2705eabd1e03732d58f5b2fbc63e5057e93e2bd`）
  复制为 `mof5_cod_h.cif`。两者成分与 CoRE 记录一致（H/Zn=3、C/Zn=6、O/Zn=3.25）。

### 2.2 UiO-66（CoRE CR 真实 + synthetic H-free）

- 真实 H 完整 CIF：CoRE 2024 `SI/CR/ASR/2015[Zr][fcu]3[ASR]1.cif`
  （cache zip 内文件 sha256=`9414a51fbb116a53044ff90d6a81e1ead88c90b539624111413098f30aa5f741`），
  原样复制为 `uio66_h.cif` + 顶部注释。
- `uio66_hfree.cif` 生成方式：同 2.1 的 `CifWriter` 删 H 脚本（只删 28 个 H，重原子不变 → 86 原子）。

### 2.3 HKUST-1（CoRE NCR 真实 + synthetic H-free）

- 真实 H 完整 CIF：CoRE 2024 `SI/NCR/mofchecker/c8tc01703d2_ASR_pacman.cif`
  （cache zip 内文件 sha256=`ffdd861bdb9b2a854c25819f2dcca1b56139637cbb591bb476f7cb9d85337609`），
  NCR 质检 flags：`has_geometrically_exposed_metal=true`，无原子重叠/过配位原子；原样复制为
  `hkust1_h.cif` + 顶部注释。
- `hkust1_hfree.cif` 生成方式：同 2.1 的 `CifWriter` 删 H 脚本（删除全部 24 个 H → 132 原子）。

### 2.4 自由羧酸（synthetic，小分子对照）

`terephthalic_acid_hfree.cif`：RDKit 从 SMILES `O=C(O)c1ccc(C(=O)O)cc1` 生成 3D 构象
（ETKDG seed=42 + MMFF94 优化），删掉两个羧酸 H 后放进 15 Å 立方盒。用于验证
「只有自由羧酸才补 O–H」——金属羧酸根 O 不能被质子化。

## 3. 期望补氢数的推导

- **MOF-5**：Zn8 C48 O26 = 2 × Zn4O(BDC)3。每个 BDC（对苯二甲酸根 C8H4O4）有 4 个环 C–H；
  2×3×4 = **24**。μ4-O 是 oxo（每个 O 连 4 个 Zn，Zn–O 1.943 Å），羧酸根 O 全部金属配位
  → 都不补 H。修复后组成 Zn8 H24 C48 O26，与 CoRE H 完整记录/COD H 完整文件一致
  （COD 的 8 倍胞为 Zn32 H96 C192 O104）。
- **UiO-66**：Zr6O4(OH)4(BDC)6 每个 cluster 有 6 个 BDC ⇒ 6×4 = 24 环 C–H；另有 4 个
  μ3-OH ⇒ 4 O–H；共 **28**。μ3-O（4 个）是 oxo 不补。修复后组成与 CoRE CR 完全一致。
- **HKUST-1**：Cu12(BTC)8 = Cu12 C72 O48 + 8×(BTC 环上 3 个 H) = **24**；羧酸根 O 与 Cu 桨轮
  不加 H。修复后组成与 CoRE NCR 完全一致。
- **对苯二甲酸**：C8H4O4 + 2 O–H = C8H6O4 ⇒ **2**。

## 4. 真实 NCR 缺氢 CIF 的搜索与结论（诚实记录）

CoRE 索引（`_cache/core-mof-2024/index.json` 的 `heavy_key`/`formula`/`h_count`）按同组成搜索：

| 候选（CoRE NCR） | 公式 / H 数 | 与 H 完整的 28 H 相比 | 结论 |
|---|---|---|---|
| `SI/NCR/mofchecker/c9sc01301f2_1_FSR_pacman.cif` | Zr6 H24 C48 O32（110 原子，sha256 `50b30d0e…`） | 少 4 H（4 个 μ3-OH 的 H） | **真实缺氢**，但该 NCR 模型几何扭曲：存在 1.27 Å 的 C···C 接触（低于任何化学 C–C 键），且 8 个 μ3-O 的 Zr–O 距离只有 2.125/2.149 Å 两种、没有 oxo/OH 双峰 → 仅凭几何无法判定 4 个 OH。**保留为溯源 fixture `uio66_raw_ncr_h24.cif`，不参与验收**。 |
| `SI/NCR/both/ja8b07050_si_003_FSR_pacman.cif` | Zr6 H16 C48 O32（102 原子，sha256 `19dec89f…`） | 少 12 H | 真实缺氢，但同样存在异常几何/连接方式（C–C 1.34–1.49 Å 混杂、晶胞角 94.7–117.3°），补氢期望不唯一，**不采用**。 |
| HKUST-1 同组成 NCR/CR 条目 | 全部 Cu12 H24 C72 O48 | H 完整 | 没有真实缺氢版本 → HKUST-1 用 synthetic H-free。 |
| MOF-5 | CoRE 2024 只有 `2007[Zn][pcu]3[ASR]3` / `2011[Zn][pcu]3[ASR]8`（H 完整），无 H-free CR/NCR；但 **COD 有真实 H-free CIF** | — | 主 fixture 用 CoRE 记录 + synthetic H-free；另用 COD 真实 H-free 交叉验证（§2.1）。 |

结论：**MOF-5 有真实 H-free 数据库 CIF（COD）**，且 CoRE 有 WP3 核实的 MOF-5 记录；
UiO-66/HKUST-1 没有几何上干净可用的真实缺氢 CIF，因此验收用「CoRE CR 删 H」的 synthetic
fixture，并在文件名/注释/docstring 中明确标注 synthetic。真实 NCR 候选的路径、H 数、拒绝
原因见上表与 `docs/REPAIR.md` §8.5。

## 5. MIL-101（尽力而为，未提供 fixture）

- CoRE MOF 2024：按 Cr 含量 + C24/C48 + O 数、按 name `MIL-101` 搜索均为 0 条；
- COD：找到 MIL-101 结构 `4000663`（"First direct imaging of giant pores of MIL-101"，
  Fd-3m），但该 CIF 用 pymatgen 默认参数无法解析（occupancy 1.00002 超过 tolerance），
  放宽 occupancy_tolerance 后展开为 **16000 原子**（Cr816 C6528 O8560，a=88.87 Å）且含
  部分占据 O（O:0.5 ×192、O:1.0 ×64），不适合作为补氢验收 fixture。
- 因此本轮 MIL-101 **未提供 fixture / 未验证**，已写入 `docs/REPAIR.md` 局限与未验证项。
