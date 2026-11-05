# 几何层（cifkit.geom）

Owner: `geom-export`。代码：`cifkit/geom/{_common,standardize,supercell,surface,vacuum,cluster}.py`。
测试：`tests/test_geom.py`。

本文件记录**实测数字**与**已知坑**，报告（`report.md`）引用几何结果时以这里的口径为准。

---

## 1. 公开接口

```python
standardize(structure, *, target="conventional") -> Structure
make_supercell(structure, reps) -> Structure
make_slab(structure, hkl, *, slab_thickness=15.0, vacuum=15.0,
          termination=None, reps=None, frame="slab") -> tuple[Structure, dict]
set_vacuum(structure, vacuum, axis=2) -> tuple[Structure, float]
extract_cluster(structure, *, mode="sbu") -> Structure
```

`make_slab` 在冻结签名基础上新增了 `reps` / `frame` 两个关键字（DESIGN.md §6f，Lead 批准），
旧调用 `make_slab(s, hkl, slab_thickness=…, vacuum=…)` 行为兼容。

所有函数都**不修改**输入结构；返回对象上附带 `_cifkit_geom_info` 字典（若对象允许设置属性），
内容是本次调用的元信息（`kept`/`reason`/`reps`/`natoms_*` 等），便于报告与调试。

---

## 2. standardize

- `target="conventional"`：`SpacegroupAnalyzer(symprec=0.01).get_conventional_standard_structure()` + 重复位点去除（同元素、< 0.05 Å 才合并）。
- `target="primitive"`：`get_primitive_standard_structure()`。
- **P1 安全 no-op**：对称性分析得到 `P1` 时原样返回（不改坐标、不重排）。
- **sanity gate**（不满足就 no-op 并记录 `kept="input"` + `reason`，绝不下传错误的大胞）：
  1. 原子数比例必须是均匀整数倍且在 `{1,2,3,4}` 内；
  2. 各元素计数比例一致（避免只放大某几种元素）；
  3. 体积/原子漂移 ≤ 3%；
  4. 晶胞参数与角度有限、物理合理。
- **原胞整数倍守卫（防"补氢后原子数翻倍"）**：若输入本身就是自身原胞的整数倍（≥2×），
  视为"已经是常规胞/超胞"，原样返回（`kept="input"`、`note="symmetry kept as input"`）。
  这个守卫是联调时实测出来的必需项：**补氢后的 276 原子常规胞被 spglib 判为 Fmm2 (#42)，
  其 conventional setting 是 552 原子**（a=17.029，b=c=24.083 的正交胞）；若不拦住，
  pipeline 的 standardize 步骤会把 276 变成 552，导致后续 slab 4416 而不是 2208。
  守卫生效时 `info` 里会带 `primitive_atoms` 与 `reason`（如 "input is already a 2x cell of the
  138-atom primitive cell"）。

实测（`tests/data/zif8_cr_sod.cif`，CoRE ASR sod、原胞 rhombohedral）：

| 输入 | 输出 | 说明 |
|---|---|---|
| 138 原子，a=14.669 Å，α=109.47°，I-43m | **276 原子，a=16.939 Å，90/90/90，I-43m** | 原胞 → 常规胞（×2），Zn12 H120 C96 N48；`kept="standardized"` |
| `zif8_raw_hfree.cif`：156 原子，a=17.029 Å，I-43m | **156 原子，a=17.029 Å** | 已是常规胞：`kept="input"`, `note="symmetry kept as input"` |
| 补氢后 276 原子常规胞（实测被 spglib 判 Fmm2，conventional=552） | **276 原子（原样）** | 整数倍守卫生效：`primitive_atoms=138`、`reason` 说明是 2× 原胞 |

---

## 3. make_supercell

- 严格校验：`len(out) == len(in) × r0 × r1 × r2`，不等直接 `RuntimeError`（pymatgen 回归才可能触发）。
- `reps` 必须是 3 个 ≥1 的整数；超过 50000 原子拒绝（防 CLI 手滑）。
- 实测：138 → **552**（2×2×1）；276 → **1104**（2×2×1）。

---

## 4. make_slab（重点）

### 4.1 frame 语义（必须写进报告的 caveat）

- `frame="slab"`（**默认，物理语义**）：先在传入的（已 standardize 的）**常规胞**上切 `hkl`，
  再把 `reps[:2]` 作为 **slab 面内重复**（第 3 维沿表面法向，必须为 1，否则 `ValueError`）。
  这样得到的是母体晶体真正的 `(hkl)` 表面，面内周期 = 常规胞表面胞 × reps。
- `frame="cell"`（**字面语义，对照用**）：先做 `structure * reps` 超胞，再切**该超胞的** `(hkl)`。
  注意：2×2×1 四方超胞的 (111) 法向在笛卡尔坐标下是 `(1/2a, 1/2a, 1/a)`，与立方晶体的
  `(111)` **不是同一个物理表面**。报告若要宣称"ZIF-8 (111) 表面"，必须用 `frame="slab"`。

### 4.2 终止面选择

枚举 `SlabGenerator.gen_possible_terminations()` 的全部终止面（本 demo 36 个），逐个打分：

```
score = dangling_bonds + 100 × stoichiometry_deviation
```

- `dangling_bonds`：表面层（沿法向深度 `min(3.0 Å, 厚度/4)`）内原子相对**体相该元素中位配位数**缺失的键数总和；
- `stoichiometry_deviation`：slab 元素摩尔分数相对体相的最大相对偏差；
- 默认取 `score` 最小者（同分按原子数、shift 排序保证确定性）。
- `termination` 还支持：整数候选编号（`info["candidates"][i]`）、浮点 shift、元素符号（如 `"Zn"`，
  在表面元素匹配的候选里取最优）。找不到时抛 `ValueError` 并列出可用表面元素。

`info` 里会返回**全部候选摘要**（`candidates`：shift/natoms/thickness/vacuum_as_generated/
dangling_bonds/stoichiometry_deviation/surface_elements_top/bottom/score），供报告引用"为什么选这个终止面"。

### 4.3 实测数字（ZIF-8 demo，`zif8_cr_sod.cif`）

CLI 验收命令：

```powershell
.venv\Scripts\python.exe -m cifkit geom tests/data/zif8_cr_sod.cif -o runs/_geom_check.cif `
  --standardize --surface 1 1 1 --supercell 2 2 1 --vacuum 15 --json
```

| 项目 | 实测值 |
|---|---|
| 输入 → standardize | 138 → 276 原子，a=16.939 Å |
| slab 未重复（base） | **552 原子** |
| 面内 2×2 后 | **2208 原子**（= base × 4） |
| slab 厚度（原子沿法向跨度） | **18.922 Å**（目标 ≥ 15 Å，pymatgen 按整层数取整） |
| 生成时的真空（垂直） | 20.196 Å（`SlabGenerator` 只保证下限，故远大于 15；其最小周期像距离 20.704 Å） |
| **最终真空（垂直，主指标）** | **15.000 Å = target** |
| 最小周期像距离（安全下界，单独报） | 15.198 Å |
| 最终 c 轴长 | **33.922 Å** = 18.922 + 15.000（c 已正交化到法向） |
| 最终晶胞 | a=b=47.910 Å，c=33.922 Å，α=β=90°，γ=60°；V=67431.3 Å³ |
| 表面面积 | 1987.84 Å² |
| 终止面 | 36 个候选中选 `shift=0.360055`，dangling_bonds=21，stoichiometry_deviation=0 |
| 表面元素（top/bottom） | C/H/N/Zn（见 `info["termination"]`） |
| 耗时 | 5.5 s（内存充足时；机器内存紧张时实测 ~25 s） |

> 目标 `slab_thickness=15 Å` 是**下限**语义：pymatgen 按整层取整后原子实际跨度 18.9 Å（层间空隙不含原子）。
> 本环境实测厚度 18.9 Å 与设计文档预估的 20.5 Å 有差异，报告以 18.92 Å 为准（`info["slab_thickness"]`）。

> **两个真空量（重要，见 §5）**：`vacuum_perp`（= `vacuum`/`vacuum_measured`，主指标）是垂直真空层厚度，
> 设真空后**精确等于 target**（15.000 Å）；`min_image_distance` 是任意原子到周期像的 3D 最近距离
> （本 slab 为 15.198 Å，略大于垂直值，因为它把两表面的横向错位也算进去了）。报告/评审引用"真空层厚度"
> 必须用 `vacuum_perp`，不能引用 `min_image_distance`。

### 4.4 已知坑（都是实测踩过的）

1. **`primitive=True` 会 OOM**：pymatgen 2026.10 的 `SlabGenerator.get_slab` 在 `primitive=True`
   （该版本默认）时调用 `Structure.get_primitive_structure()`，500+ 原子时会申请巨量临时数组
   （本机直接 numpy `MemoryError`）。实现里固定 `primitive=False, lll_reduce=True`，保留超胞面内面积语义。
2. **`lll_reduce=True` 会让 c 轴不垂直**：返回的 slab `c·n < |c|`（例：|c|=58.68 Å，垂直分量 55.32 Å）。
   因此厚度/真空一律用**笛卡尔投影到表面法向**测（`_common.vacuum_metrics` 的
   `d_perp`/`thickness`/`vacuum_perp`），并由 `set_vacuum` 把 c 重设为法向向量，最终 c ⊥ (a,b)。
3. **`get_slabs()` 的 `filter_out_sym_slabs=True` 很贵**：实现改成自己遍历
   `gen_possible_terminations()` + `get_slab(shift)`，逐候选打分后只保留最优者，内存/时间可控。
4. `min_vacuum_size` 只是下限，生成时垂直 gap 可能远大于目标（实测 20.196 Å）→ `make_slab` 内部最后
   一定调 `set_vacuum` 把真空精确设到目标，并返回真实测量值（`vacuum_measured` = 垂直值）。

### 4.5 `info` 关键字段

`frame`, `hkl`, `reps`, `in_plane_reps`, `input_atoms`, `cut_cell_atoms`, `base_atoms`,
`atoms_after_reps`, `natoms`, `formula`, `slab_thickness`,
**`vacuum_measured` = `vacuum_perp` = `vacuum`（垂直真空层，主指标）**、`min_image_distance`（3D 最小周期像距离，安全下界）、
`vacuum_target`, `vacuum_as_generated`（生成时的垂直真空）, `min_image_distance_as_generated`,
`c_length`, `lattice{abc,angles,volume}`, `surface_area`,
`termination{mode,shift,surface_elements_top/bottom,dangling_bonds,dangling_by_element,stoichiometry_deviation,score}`,
`candidates[]`（每个候选含 `vacuum_perp` 与 `min_image_distance`）, `n_candidates`, `generator{...}`, `elapsed_s`。

---

## 5. set_vacuum 与"真空层厚度"的定义（重要）

### 5.1 两个量，别混用

| 量 | 定义 | 本 demo（ZIF-8 (111) 2208 原子 slab） |
|---|---|---|
| `vacuum_perp`（= `vacuum` / `vacuum_measured`，**主指标**） | `d_perp - thickness`：垂直真空层厚度（表面科学标准定义） | **15.000 Å**（= target） |
| `min_image_distance` | `min_{i,j} |r_i - (r_j + c)|`：任意原子到周期像的 **3D 笛卡尔最近距离** | 15.198 Å |

- 对有横向错位的两个表面，`min_image_distance` **大于** `vacuum_perp`（它多算了横向偏移），
  只能当"原子绝不会比这更近"的安全下界，**不是真空层厚度**。
- 设真空后 `vacuum_perp` 精确等于 target；`c = thickness + target`（本 demo：18.922 + 15.000 = 33.922 Å）。
- `vacuum_metrics()` 同时返回：`d_perp`、`thickness`、`frac_span`、`vacuum_perp`、`vacuum`（= `vacuum_perp`）、
  `min_image_distance`（旧的 `gap_geometric` 键保留为 `vacuum_perp` 的别名）。

### 5.2 算法（支持任意 `axis`，斜晶胞用投影）

1. 取另外两个晶格向量的叉积作为表面法向 `n`，`d_perp = c·n`；
2. 原子在 `n` 上的高度 `h_i = cart_i·n`，slab 厚度 `T = max h - min h`；
3. 令 `d_new = T + target`，把该轴向量替换为 `n * d_new`（c 严格垂直表面），原子沿 `n` 刚移居中
   （笛卡尔位置只做整体平移，不改变结构）→ 于是 `vacuum_perp = d_new - T = target`；
4. 同时用 cKDTree 测一次 `min_image_distance`（O(N log N)）作为安全下界一并返回；
5. 返回 `(新结构, vacuum_perp)`，对同一结构**幂等**
   （pipeline 在 surface 之后还会再跑一次 `set_vacuum`，实测 `delta_c = 0`、真空值一致）。

### 5.3 实测

- 手搓 0.8 Å 厚 slab + target 15：`c = 15.8 Å`，`vacuum_perp = 15.000 Å`，`min_image_distance = 15.411 Å`。
- ZIF-8 (111) slab（CLI 验收）：`c = 33.922 Å = 18.922 + 15`，`vacuum_perp = 15.000 Å`，`min_image_distance = 15.198 Å`。
- Lead 的 demo `runs/demo_sod_zif8/final.cif`（2208 原子，用本模块复测）：
  `thickness = 19.2826 Å`、`c = 34.2826 Å`、`vacuum_perp = 15.0000 Å`、`min_image_distance = 15.2396 Å`
  （与 Lead 独立计算一致）。

参数校验：`vacuum` 必须有限且 > 0，空结构、退化晶胞抛 `ValueError`。

---

## 6. extract_cluster

模式（`mode`）：

- `sbu`（默认）：金属簇（金属–金属键连通的整簇，如 Zr6）+ 与金属相连的**完整配体**
  （BFS 只在非金属原子间扩展，遇金属即停，因此不会走进相邻节点）；
- `metal_cluster`：金属簇 + 第一配位壳层；
- `core`：只保留金属簇核心。

周期像正确处理：以笛卡尔坐标做 BFS，邻居来自 `get_all_neighbors` 的周期像，按 < 0.05 Å 去重；
结果是有限团簇，放进正交盒（最小 20 Å 真空，边界留 20 Å padding）。

实测（ZIF-8 原胞）：

| 模式 | 原子数 | 组成 |
|---|---|---|
| `sbu` | 45 | Zn1 C16 N8 H20（= 1 Zn + 4 个完整 2-甲基咪唑 C4H5N2） |
| `metal_cluster` | 5 | Zn1 N4 |
| `core` | 1 | Zn1 |

无金属原子时抛 `ValueError`（列出结构里有哪些元素）；团簇 > 800 原子也拒绝（防 BFS 跑飞）。

---

## 7. 校验（validate）与预览（render）摘要

本模块的产物最终由 `cifkit.validate` 校验、`cifkit.render` 出图；两者实现同在 `geom-export` 的
写范围内（`cifkit/validate/checks.py`、`cifkit/render.py`），这里只记录与几何相关的口径。

### 7.1 validate 的稳定检查名（report.md 直接引用）

`natoms` / `composition` / `lattice` / `finite_coordinates` / `duplicate_atoms` / `min_distance` /
`vacuum` / `slab_continuity` / `dangling_bonds` / `hydrogen` / `carbon_coordination` / `charge`
（共 12 项；`severity ∈ {error, warning, info}`，`report.ok` 只看 error）。

- 判定为 slab：沿 c 法向实测垂直真空 > 6 Å 且不是三轴都 > 6 Å 的团簇；
- **真空检查用垂直真空 `vacuum_perp` 与 target 比较**（≥ target - 0.01 才过）；`min_image_distance`
  作为独立 metric 一并给出，不参与通过判据。检查 detail 形如：
  `真空层（垂直）= 15.000 Å；最小周期像距离 = 15.240 Å；要求 ≥ 15.00 Å`；
- 真空口径与 `set_vacuum` 完全一致（同一 `vacuum_metrics` 实现），因此
  `validate.metrics["vacuum_measured"]` 与 `make_slab.info["vacuum_measured"]` 差异 < 0.01 Å（测试有断言）；
- 关键 metrics：`natoms`、`formula`、`lattice{abc,angles,volume,volume_per_atom}`、`min_distance`、
  `min_distance_pair`、`min_distance_by_element_pair`、`vacuum_measured`（=`vacuum_perp`=`vacuum`）、
  **`min_image_distance`**、`vacuum_target`、
  `slab_thickness`、`surface_area`、`surface_atoms`、`dangling_bonds`、`dangling_by_element`、
  `h_count`、`c_coordination`、`c_missing_h`、`is_slab`、`is_cluster`；
- `spec.repair_h=True` 时 `hydrogen`、`carbon_coordination` 升级为 error（缺 C–H 会 FAIL）；
  不传 spec 时同样的信息降级为 warning/info，不误判为失败；
- 实测：ZIF-8 原胞 12 项全过（`ok=True`），H-free 原始 CIF + `repair_h` → `ok=False`（hydrogen/carbon_coordination FAIL）；
  (111) slab + `vacuum=15` → `ok=True`，`vacuum_measured=15.000`、`min_image_distance=15.198`、
  `slab_thickness=18.922`，`dangling_bonds` 为 WARN；
  对 `runs/demo_sod_zif8/final.cif` 复测：`vacuum_measured=15.000`、`min_image_distance=15.2396`、
  `slab_thickness=19.283`，detail 即上面那行。

### 7.2 render

`render_structure(structure, path, *, view="auto", title=None, repeat=(1,1,1))`：

- 强制 `Agg` 后端，无显示环境可用；输出 **1200×900 PNG**（figsize 12×9 @ dpi=100）；
- `view="auto"`：slab → **侧视图**（水平=面内方向，竖直=表面法向，真空区域浅蓝填充并标注厚度/真空），
  其余 → 3D 视角（画晶胞框、按元素固定配色、球径按共价半径）；
- 元素颜色固定（Jmol 风格，`ELEMENT_COLORS`），`repeat` 只影响显示（slab 的法向重复强制为 1）。
- **中文标题**：`render_structure` 会探测 CJK 字体（候选 `Microsoft YaHei` / `SimHei` /
  `Noto Sans CJK SC` / `Source Han Sans SC` / `WenQuanYi Zen Hei`，本机命中 `Microsoft YaHei`），
  命中则直接绘制中文标题；未命中时自动退化为 ASCII 标题
  （`structure overview - <reduced formula> - N atoms`），并屏蔽 matplotlib 的
  `Glyph ... missing from font` 警告——不会再出现"方块字 + 刷屏 warning"。

实测：`render_structure(Structure.from_file('tests/data/zif8_cr_sod.cif'), 'runs/_render_check.png')`
→ 1200×900 PNG 正常；中文查询文本作 title（pipeline 的行为）也能正确渲染（`runs/_render_cjk.png`），
无 glyph 警告（`tests/test_geom.py` 有断言）。

---

## 8. 复现与测试

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe -m pytest tests/test_geom.py tests/test_export.py tests/test_validate.py -q
.venv\Scripts\python.exe -m cifkit geom tests/data/zif8_cr_sod.cif -o runs/_geom_check.cif `
  --standardize --surface 1 1 1 --supercell 2 2 1 --vacuum 15 --json
```

---

## 9. 局限

- 只有 (hkl) 低指数面被实测验证（(111)）；高指数面 OUC 很大，超过 30000 原子会直接 `ValueError`。
- 终止面分数是**几何启发式**（悬空键 + 化学计量），不是表面能计算；报告必须写明"按几何打分选择"。
- `frame="cell"` 仅作对照，其 (111) 与母体晶体 (111) 不是同一表面（见 4.1）。
- slab 厚度按 pymatgen 整层取整，可能明显大于 `slab_thickness` 目标（15 → 18.9 Å），报告用实测值。
- 不处理极性表面/对称化终止（`symmetrize` 未启用）。
