# 修复层（REPAIR）：补氢 / 无序占位 / 过近原子 / 价态检查

> Owner：repair 队友（task-2）。接口冻结见 `docs/DESIGN.md` §6：
> `repair_all(structure, *, add_hydrogen=False, resolve_disorder=True, remove_close_contacts=True) -> (Structure, RepairReport)`。
> 入口：`<repo>\.venv\Scripts\python.exe -m cifkit repair FILE ...`。
> 对应的纯 Python API：`from cifkit.repair import repair_all, add_hydrogens, resolve_disorder_sites, find_close_contacts, remove_close_contacts_atoms, check_structure`。

## 0. 文件与职责

| 文件 | 职责 |
|---|---|
| `cifkit/repair/__init__.py` | `repair_all` 串联：disorder → contacts → hydrogen → valence，产出 `RepairReport` |
| `cifkit/repair/bonds.py` | 周期键感知 / 金属键标记 / 5-6 元环识别 / 芳香性 / Kekulé 键级 / 每原子缺氢数 |
| `cifkit/repair/hydrogen.py` | 补氢核心：RDKit capping 路线 + 纯几何兜底 + 冲突最小化 + 补后价态自检 |
| `cifkit/repair/disorder.py` | CIF 文本 `_atom_site_*` 解析 + 部分占据/统计原子消解 |
| `cifkit/repair/contacts.py` | 过近原子/重复原子检测与删除 |
| `cifkit/repair/valence.py` | 补后价态、金属配位数、异常距离检查（写 `RepairReport.warnings`） |
| `cifkit/repair/_labels.py` | 保证输出 CIF 的 `_atom_site_label` 唯一（新补/新提升的原子不留重复 label） |

所有函数都**不修改输入结构**（pymatgen 2026 的 `remove_sites` / `replace` 是原地修改，代码内部先 `copy()`）。

## 1. 管线顺序与报告结构

```python
repair_all(s, add_hydrogen=True, resolve_disorder=True, remove_close_contacts=True)
# 1) disorder   部分占据/统计原子 -> 有序结构
# 2) contacts   < 0.85*(r_i+r_j) 的重复/重叠原子
# 3) hydrogen   每个原子按价态补 H（核心）
# 4) valence    补后价态/配位/距离检查
```

`RepairReport.actions` 每一步一条结构化记录（可直接引用）：

```json
{
  "action": "hydrogen",
  "detail": "补氢：新增 120 个 H（{'sp2 C-H': 48, 'sp3 C-H3': 72}；路线 rdkit-capped；"
            "RDKit 片段 24/24 成功；每个有机片段补 H 数量分布 {5: 24}）；C–H 键长 1.100–1.100 Å；"
            "最小 H···H 1.80 Å；最小 H···重原子 2.13 Å；最小 H···金属 2.87 Å",
  "route": "rdkit-capped",
  "added_h": 120,
  "h_types": {"sp2 C-H": 48, "sp3 C-H3": 72},
  "per_ligand_h": {"5": 24},
  "rdkit": {"available": true, "fragments_total": 24, "fragments_ok": 24, "fragments_failed": 0},
  "min_hh": 1.796, "min_h_heavy": 2.131, "min_h_metal": 2.867,
  "c_valence_ok": true
}
```

`RepairReport.warnings` 是**补完之后**仍然存在的问题（补前问题由各步骤 action 记录）：

```json
{"action": "valence", "ok": true,
 "detail": "价态检查：C 96/96 四配位；金属配位 Zn CN={4: 12}；H 120 个；最小原子间距 1.10 Å；通过",
 "metrics": {"c_four_coordinate": 96, "metal_coordination": {"Zn": {"4": 12}}, ...}}
```

## 2. 周期键感知（`bonds.py`）

1. **成键判据**：共价半径表（Cordero 2008，与 ASE 默认一致；pymatgen 2026 已移除
   `Element.covalent_radius`，所以表内置在 `bonds.py`）+ `Structure.get_neighbor_list`
   给出的**周期最小镜像**。非金属对用 `d < 1.15*(r_i+r_j)`；涉及金属的对用
   `d < 1.30*(r_i+r_j)` 并标记为 **metal bond**，且**只有 donor 元素**
   （`METAL_COORDINATING_ELEMENTS = {N,O,S,Se,P,F,Cl,Br,I,Te}`）才算配位键。
   金属–金属、H–H 对不计成键；**金属···C 不算键**（见 §8.3：羧酸根 MOF 里
   Zr···C ≈ 3.24 Å 这类穿空间接触若算成键会把羧基 C 算成五/六价，抑制环 C–H 补位）。
2. **最小镜像**：`get_neighbor_list` 返回 `(i, j, image, distance)`，键方向向量为
   `cart[j] + image @ lattice - cart[i]`，所以跨晶胞边界的配体/环也能正确成键。
3. **环识别**：对每个非金属原子做深度 ≤6 的平移感知 DFS（路径带累计平移向量，
   只有回到起点且净平移 = 0 才算成环），支持环跨晶胞边界；再去重、拒绝带弦环。
4. **芳香性**：5/6 元环、所有原子 ∈ {B,C,N,O,P,S,Se}、环平面最大偏差 < 0.20 Å、
   所有环键 ≤ 1.50 Å 且 ≥ 1.20 Å → 判为芳香环。
5. **键级**：
   - 芳香环外：按 `d/(r_i+r_j)` 比例给 1/2/3 键（<0.80 三键、<0.92 双键、否则单键）；
   - 羧酸根/碳酸根：C 连两个 O 且两个 C–O 都"偏短"时，按较短者给 C=O、另一个给 C–O，
     保证羧基 C 键级和 = 4（去质子化 MOF 里两个 C–O 常是 1.25–1.27 Å 的对称结构，
     否则会被误判成两个 C=O 而把 C 算成五价）；
   - 芳香环内：把"还需要一个环 π 键才能到价态"的碳作为必覆盖点，在环键上做一次
     最小代价匹配（Kekulé 结构；代价 = 双键键长和），杂原子（N/O/S）可被匹配也可不
     被匹配 —— 被匹配的是"吡啶型"（无 H），未被匹配的是"吡咯型"（补 N–H）。
     5 元咪唑环因此得到 `C4=C5` + `C2=N` 的 Kekulé 结构，C2（连甲基）无 H。
   - 匹配失败时退化为"分数 π 键"（`virtual_pi`），并在 `BondGraph.warnings` 中记录。
6. **每原子键级和**：所有键的键级之和（金属键按 1 计入），π 键按整数 2/3 计入，
   因此价态判据是精确整数，不用浮点距离猜测。

## 3. 缺氢数（价态判据）

`hydrogen_demand()` 对每个非金属、非 H 原子计算 `missing = 目标价态 - 键级和`：

| 元素 | 目标价态 | 备注 |
|---|---|---|
| C | 4 | 芳香/双键碳由键级吸收，只补剩余 σ 位 |
| N | 3（4 允许） | **与金属配位的 N 一律不补 H**（Zn–N 计 1 键；ZIF-8 两个环 N 都配位 → 0 N–H） |
| O | 2（金属氧化物簇例外） | 与金属配位不补；羧酸根 O 不补（见 §8.1）；μ3/μ4 簇氧按 oxo/hydroxo 判据（§8.2）；**只有全结构无任何金属配位键（自由羧酸分子/分子晶体）才补 O–H** |
| S | 2（4/6 允许） | 金属配位不补 |
| B/P/Si/Se | 3/3/4/2 | 同上 |
| 其他元素 | 不处理 | 见 §10 局限 |

特殊情况：

* 孤立原子（没有任何键）：不补 H，记录"可能是未被识别的配位键"；
* 键级和超过目标价态：不补 H，进入 `BondGraph.warnings`；
* 已有 H 全部计入键级和，所以**满氢结构是 no-op**（`added_h=0`）；
* 对芳香环原子，杂化标签强制为 `sp2`（环平面内补位），其余按 π 键数判 sp/sp2/sp3。

## 4. 补氢路线（`hydrogen.py`）

### 4.1 首选：RDKit capping + `AddHs(addCoords=True)`

1. 切断所有金属–配体键，得到若干**有限有机片段**（配体/溶剂分子；H 原子保留在片段里）。
2. 对每个断开的配位原子加**占位 H（cap）**：沿原金属键方向放一个 H，使片段成为闭合
   价态的分子（例：ZIF-8 的 mIm⁻ 切掉两个 Zn–N 后，一个 N 本来已经是吡啶型（无 cap），
   另一个补 cap H → 中性 2-甲基咪唑模型）。cap 只用于价态约束，最后丢弃。
3. 把几何键级（§2 的 Kekulé/双键）交给 RDKit，`Chem.SanitizeMol` + 隐式 H 数校验
   （必须与 §3 的 `missing` 逐个原子一致），然后 `Chem.AddHs(mol, addCoords=True)`。
4. 用片段的**真实 3D 构象**（BFS 展开跨晶胞平移）生成 H 坐标，再映射回原晶胞
   （减去母原子的展开平移、wrap 回 [0,1)）。

RDKit 失败/不可用/片段是周期性有机聚合物（展开平移不一致）时，**逐片段**改用几何法，
路线记录为 `mixed (...)`；全部走几何法时为 `geometric-vsepr`。

### 4.2 纯几何兜底：VSEPR 补位

由现有键方向构造候选方向：

* sp3：1 个邻居 → 24 个绕轴旋转的四面体三重位（H–C–X = 109.47°）；2 个邻居 →
  解析解 `h = a·s ± b·p`（`a = -1/(3cos(α/2))`）；3 个邻居 → `-normalize(Σu)`；
* sp2：2 个邻居 → 角平分线反向（环平面内，H–C–X ≈ 126°）；1 个邻居 → 120° 锥面采样；
* sp：`-u`（直线）；
* 其它/孤立：Fibonacci 球面采样 + 贪心（角度接近理想值、互相分散）。

### 4.3 冲突最小化

每个候选 H 位置对**所有原子 × 27 个周期像**检查最近距离（H 与母原子的键长排除在外）：

| 对 | 期望 ≥ | 硬拒绝 < |
|---|---|---|
| H···H | 1.4 Å | 1.2 Å |
| H···重原子（非母原子） | 1.5 Å | 0.9 Å |
| H···金属 | 2.0 Å | 1.5 Å |

按"最小距离/期望阈值"的最大边际打分选候选组；同一原子多个 H（如甲基）作为一组
整体打分（组内也要 >1.4 Å）。无候选能完全避开时选最好者并写 warning。

### 4.4 补后自检

* 每个 C 的键级和 + 新 H 键 = 4（`c_valence_ok`）；
* C–H 键长范围、最小 H···H / H···重原子 / H···金属 写入 action；
* 再叠加 §7 的独立 `valence.check_structure`（重新做一遍周期键感知），双保险。

## 5. 无序 / 占位（`disorder.py`）

* **CIF 文本解析**：`parse_atom_site_loop()` 直接解析 `_atom_site_*` 循环，支持
  `_atom_site_occupancy`、`_atom_site_disorder_group`、`_atom_site_disorder_assembly`、
  `_atom_site_symmetry_multiplicity`、`_atom_site_charge`，容错 `0.123(4)` 与 `'x, y, z'`。
  pymatgen 的 `CifParser` 只保留占据率、丢 disorder group，所以 `repair_all(..., cif_text=...)`
  可以直接吃原始 CIF 文本（CLI 不传时用 Structure 里内嵌的占据率，效果相同）。
* **重原子部分占据**：0.7 Å 内的替代位点成组，保留占据率最高者（平局按 label/索引），
  无替代位点的孤立部分占据按主元素升为全占据（warning）。
* **H 部分占据**（ZIF-8 统计甲基）：每个部分占据 H 按最近重原子（<1.65 Å）归到母原子；
  母原子"还缺几个 H"由**去掉全部 H 后的重原子键图**（同一套价态/芳香规则）给出，
  减去该母原子上全占据 H 的个数；再从候选 H 位点中选互相兼容（H···H > 1.2 Å）的子集：
  - 若 CIF 有 `_atom_site_disorder_group`：按组整体选总占据率最大的一组（平局按 label）；
  - 否则枚举组合，按（兼容、总占据率、最小间距、索引）排序选最优；
  - 选中的半占据位点升为全占据，未选中的删除。
* 金属上的部分占据 H（疑似金属氢化物）保留并 warning，不做补氢推断。

ZIF-8 实测：348 原子（48 全占据 H + 144 个 H:0.5）→ 每个甲基 6 选 3 个兼容位点 →
删除 72、保留 120 H，输出 276 原子 Zn12C96H120N48，无警告。

## 6. 过近原子（`contacts.py`）

* 检测：`d < 0.85*(r_i+r_j)`（重复/重叠重原子）；H 专用阈值
  `H···H < 1.0 Å`、`H···重原子 < 0.9 Å`（可配置）。
* **H–X 键豁免**：每个 H 的最近重原子视为它的 X–H 键。X 射线结构常见 N–H 0.86 Å、
  C–H 0.93 Å 这类"偏短"键长（例如 `sod_zn_mof.cif` 的 N–H = 0.86 Å），它们低于 0.9 Å
  阈值但**是化学键不是重叠**，因此最近邻那一对 H–X 不删（只由价态检查判断是否异常）。
  其它 H···重原子距离 < 0.9 Å 才视为冲突并删除 H。
* 处理：保留先出现者；H 参与时删 H；占据率高者优先保留；自周期像过近（晶胞/周期性异常）
  只 warning，不删原子。
* 输出 `removed_atoms` 与每条 contact（i, j, 距离, image, kept/removed）。
* 注意：正常 C–H 1.09 Å、O–H 0.96 Å、H···H 1.78 Å 都高于阈值，不会被误删。
  实测含溶剂大结构 `sod_zn_mof.cif`（750 原子，N–H 0.86 Å）删除 0、补氢 0、无警告。

## 7. 价态检查（`valence.py`）

重新做一次周期键感知，输出 `ok / warnings / metrics / detail`：

* C 必须键级和 4（±0.01）——ZIF-8 补氢验收的"每个 C 四键"；
* N 允许 3/4（4 常见于金属配位或 N⁺），O 2，S 2/4/6，B/P/Si 正常价态；
  例外：金属配位的羧酸根 O 允许键级和 3（C=O 双键 + 金属配位键计 1），
  去质子化且未配位的羧酸根 O 允许键级和 1（阴离子，不是缺陷）；
* 每个 H 必须恰好与 1 个重原子成键（0 = 游离 H/氢化物；>1 = 桥氢）；
* 金属配位数按元素统计（ZIF-8：Zn CN={4: 12}），孤立金属 / CN>9 警告；
* 异常距离：任意原子对 <0.5 Å、H···H <1.2 Å、H···重原子（非自身键）<0.9 Å、
  H···金属 <1.5 Å；
* metrics 还包含 `min_distance`、`min_hh`、`min_h_heavy`、`min_h_metal`、价态直方图。

## 8. 羧酸根 MOF（Round-2 WP2：MOF-5 / UiO-66 / HKUST-1）

本轮把补氢从「咪唑 N–Zn」扩展到「羧酸根 + 金属氧簇 + Cu 桨轮」：新增
`bonds.METAL_COORDINATING_ELEMENTS` / `bonds.classify_cluster_oxygen`，修改
`hydrogen_demand()` 的 O 规则与 `valence` 的 O 例外。fixture 来源与生成方式见
`tests/data/REPAIR_FIXTURES.md`，验收测试 `tests/test_repair_carboxylate.py`。

### 8.1 羧酸根 O（–COO–）的补氢规则

- **金属配位 O（单齿/桥联/螯合）一律不加 H**：羧酸根去质子化后 O 的价态由
  `C–O`（单/双）与 `M–O` 配位键共同满足，加 H 会得到不中性的 –COOH。
- 未配位但属于「带金属配位结构」的羧酸根 O：视为阴离子/缺陷，不加 H（在 action 中记录
  "羧酸根 O（金属配位/桥联或去质子化阴离子），不补 H"）。
- **只有整个结构没有任何金属配位键**（metal-free 的羧酸分子/分子晶体）才把单键 O
  质子化：例如对苯二甲酸 H-free（C8H4O4）→ 补 2 个 O–H（`terephthalic_acid_hfree.cif`）。
- 判据：`graph.metal_coordination`（结构中是否存在任何金属–donor 键）+
  `is_carboxylate_oxygen()`；不是按距离猜质子化状态。

### 8.2 UiO-66 `Zr6O4(OH)4` 的 μ3-O / μ3-OH 判据

- `classify_cluster_oxygen()`：把「≥3 个金属邻居、无 H」的 O 按（金属元素, 配位数）分组，
  比较组内**平均 M–O 距离**。若距离分成两族且间隙 ≥ 0.10 Å，**长的一族判为 μ-OH**
  （补 1 个 H），短的一族判为 μ-O（oxo，不补 H）。
- UiO-66 实测（CoRE CR）：4 个 μ3-O 的 Zr–O = 2.065 Å；4 个 μ3-OH 的 Zr–O = 2.268 Å；
  间隙 0.20 Å，非常清楚。H-free fixture 里 8 个 O 全部无 H，仍能按距离分成 4+4，
  给 4 个长 Zn–O 的 O 各补 1 个 O–H（O–H ≈ 0.96 Å，H 朝远离 Zr 的方向）。
- 若组内只有 1 个 O、或距离连续无明确双峰：**保守按 oxo 不补 H**，并写 warning
  「无法仅凭几何区分 oxo/OH」——oxo 与 hydroxo 的本质差别在质子/电荷，仅凭重原子
  坐标并不总能区分，这是本方法的根本局限（见 §10）。
- 结构本身已有 μ3-OH 的 H 时（H 完整 CR），O 键级和 = 3M + 1H → 不会重复加 H。

### 8.3 金属···C 假键（羧酸根 MOF 通用坑）

羧酸根 MOF 里羧基 C 与金属的穿空间距离很短（UiO-66 的 Zr···C ≈ 3.24 Å），早期实现
用 `1.30*(r_M+r_C)` 判为配位键 → 羧基 C 出现 5 个邻居、键级和 6，芳香环 Kekulé 匹配
失败/环 C 误判为"已满价"，导致 BDC/BTC 环 C–H 漏补并产生大量假 valence warning。

修复：**金属键只允许 donor 元素**（`METAL_COORDINATING_ELEMENTS`：N/O/S/Se/P/F/Cl/Br/I/Te）。
UiO-66 CR 的 48 个 Zr–O 键保留、24 个 Zr···C 假键消失，Zr 配位数从 12 修正为 8。
代价是真正的有机金属 M–C σ 键（Zn–CH3、Cp 等）不会被当作配位键（见 §10 局限）。

### 8.4 Cu 桨轮（HKUST-1）

- `Cu···Cu ≈ 2.6 Å` 的金属–金属接触**不计键**（perceive 阶段直接跳过 metal–metal），
  不影响有机片段与 H 计数。
- Cu–O 羧酸根 O 不补 H；BTC（苯-1,3,5-三甲酸根）环上 3 个 C–H 在环平面内补齐。
- H-free fixture 实测：Cu12 C72 O48 (132 原子) → Cu12 H24 C72 O48 (156 原子)，
  RDKit 片段 8/8 成功（每个 BTC 片段 3 H），Cu CN=4，价态检查通过。

### 8.5 真实 NCR 缺氢 CIF / MIL-101 的搜索结论（诚实记录）

- **MOF-5**：CoRE MOF 2024 里 MOF-5 的 index 记录被归一化为
  `heavy_key = Zn:1|C:6|O:3.25`（直接按 `Zn4 C24 H12 O13` 匹配不到，这也是最初误选
  `2015[Zn][pcu]3[ASR]2` 的原因）。WP3 拓扑评审核实的真实记录是 **`2007[Zn][pcu]3[ASR]3`**
  （refcode `ja074366osi20070816_031204_ASR_pacman`，DOI **10.1021/ja074366o**，topology pcu，
  **Zn8 H24 C48 O26 = 2×Zn4O(BDC)3**，106 原子，primitive rhombohedral a=18.2486 Å、α=60°）。
  该文件 2 个 μ4-O 各连 4 个 Zn（Zn–O = 1.943 Å）、6 个 BDC 各 4 个环 C–H，`--add-h` 为 no-op。
  任务书中提到的 `SI/CR/ASR/2015[Zn][pcu]3[ASR]2.cif`（Zn4 H8 C24 O14）**不是 MOF-5**：它是
  Zn4O2 + 三联苯四羧酸根、`topology(AllNodes)=scn` 的 pcu/scn MOF（DOI 10.1039/C5TA04552E），
  H 完整且 `--add-h` no-op；`2011[Zn][pcu]3[ASR]8` 虽也是 MOF-5 记录，但其 CR 文件含额外 H/
  几何异常（直接补氢会 added_h=27 且报 C 五价 warning），故未采用。
  `mof5_hfree.cif` = 从 `2007[Zn][pcu]3[ASR]3` 删全部 24 H（synthetic，82 原子），
  另用 **COD 真实 H-free CIF**（4340010，原始文件本身无 H，Zn32 C192 O104）做独立交叉验证；
  H 完整对照为同记录 CR / COD 1516287。两套来源每 Zn 均为 3 H、6 C、3.25 O，一致。
- **UiO-66**：找到真实 NCR 缺氢候选
  `SI/NCR/mofchecker/c9sc01301f2_1_FSR_pacman.cif`（Zr6 H24 C48 O32，108→110 原子，
  比 H 完整少 4 个 OH H）与 `SI/NCR/both/ja8b07050_si_003_FSR_pacman.cif`
  （Zr6 H16 C48 O32，少 12 H）。但两者几何都不可靠：前者存在 1.27 Å 的 C···C 接触，
  且 8 个 μ3-O 的 Zr–O 只有 2.125/2.149 Å 两个值、没有 oxo/OH 双峰；后者连接方式异常
  （C–C 1.34–1.49 Å 混杂）。**保留前者为溯源 fixture `uio66_raw_ncr_h24.cif`，不参与验收**，
  验收用 CoRE CR 删 H 的 synthetic fixture。
- **HKUST-1**：CoRE 中所有同组成条目（CR 与 NCR）H 都已完整（H24），没有真实缺氢版
  → 用 CoRE NCR 删 H 的 synthetic fixture。
- **MIL-101**：CoRE 2024 无条目（按 Cr/C24/O 数与 name 搜索均为 0）；COD 有结构
  `4000663`，但默认 pymatgen 解析失败（occupancy 1.00002），放宽 occupancy_tolerance 后
  展开为 **16000 原子**（Cr816 C6528 O8560，a ≈ 88.87 Å）且含部分占据 O（192×O:0.5），
  不适合做补氢验收 fixture。**本轮 MIL-101 未提供 fixture、未验证**。

### 8.6 本轮验收数字（fixture → added_h / natoms / H）

| fixture | 输入 | added_h | 输出 natoms | 输出 H | 对照 H 完整参考 | warnings |
|---|---|---|---|---|---|---|
| `mof5_hfree.cif`（CoRE `2007[Zn][pcu]3[ASR]3` 删 24 H，synthetic） | Zn8 C48 O26, 82 | **24** | 106 | 24 | CoRE `2007[Zn][pcu]3[ASR]3` 完全一致 | 0 |
| `mof5_cod_hfree.cif`（COD 4340010，真实 H-free CIF） | Zn32 C192 O104, 328 | **96** | 424 | 96 | COD 1516287 完全一致 | 0 |
| `uio66_hfree.cif`（CoRE CR 删 H，synthetic） | Zr6 C48 O32, 86 | **28** | 114 | 28 | CoRE CR 完全一致 | 0 |
| `hkust1_hfree.cif`（CoRE NCR 删 H，synthetic） | Cu12 C72 O48, 132 | **24** | 156 | 24 | CoRE NCR 完全一致 | 0 |
| `terephthalic_acid_hfree.cif`（synthetic 自由羧酸） | C8 H4 O4, 16 | **2** | 18 | 6 | —（2 个 O–H） | 0 |
| `mof5_h.cif` / `mof5_cod_h.cif` / `uio66_h.cif` / `hkust1_h.cif`（真实 H 完整） | 106 / 424 / 114 / 156 | **0** | 不变 | 24/96/28/24 | 自身 | 0 |

补氢类型拆分：MOF-5 `{sp2 C-H: 24}`（6 BDC × 4，COD 8 倍胞为 `{sp2 C-H: 96}` / 24 BDC）；
UiO-66 `{sp2 C-H: 24, sp3 O-H: 4}`（6 BDC × 4 + 4 μ3-OH）；HKUST-1 `{sp2 C-H: 24}`（8 BTC × 3）。
几何自检：环 C–H 在环平面内（最大偏离 < 0.1 Å）、H–C–C 角 115–125°、C–H 1.10 Å、
O–H 0.96 Å、最小 H···H > 1.4 Å、最小 H···金属 > 2.0 Å；`check_structure` 全部通过
（C 四配位、Zn CN=4 / Zr CN=8 / Cu CN=4）。**MOF-5 的 2 个 μ4-O（4 Zn，Zn–O 1.943 Å）
与 24 个羧酸根 O 均未被加 H**（`classify_cluster_oxygen` 判为 oxo）。

## 9. 验收数字（本机实测，2026-11）

```powershell
$env:PYTHONIOENCODING='utf-8'
$PY = '<repo>\.venv\Scripts\python.exe'

& $PY -m pytest tests/test_repair.py -q
# 12 passed

& $PY -m cifkit repair tests/data/zif8_raw_hfree.cif -o runs/_repair_check.cif --add-h --json
# report.added_h = 120, natoms = 276, formula Zn12 H120 C96 N48,
# warnings = [], route = "rdkit-capped", RDKit 24/24 片段成功,
# per_ligand_h = {5: 24}, h_types = {sp2 C-H: 48, sp3 C-H3: 72},
# C-H 1.100 Å, 最小 H···H 1.796 Å, 最小 H···金属 2.867 Å

& $PY -m cifkit repair tests/data/zif8_cr_sod.cif -o runs/_repair_cr.cif --add-h --json
# added_h = 0, natoms = 138, warnings = []

& $PY -m cifkit repair tests/data/zif8_disordered_h.cif -o runs/_repair_disorder.cif --json
# resolved_disorder = 24, natoms = 276, H = 120, warnings = []

& $PY -m cifkit repair tests/data/sod_zn_mof.cif -o runs/_repair_solvent.cif --add-h --json
# 750 原子含溶剂大结构：added_h = 0, removed_atoms = 0, warnings = []
# （X 射线 N–H 0.86 Å 不被当成重叠；C 312/312 四配位）

# --- Round-2 WP2：羧酸根 MOF -------------------------------------------------
& $PY -m pytest tests/test_repair.py tests/test_repair_carboxylate.py -q
# 29 passed（ZIF-8 12 + 羧酸根 17）

& $PY -m cifkit repair tests/data/mof5_hfree.cif   -o runs/_wp2_mof5.cif   --add-h --json
# added_h=24,  natoms=106, Zn8 H24 C48 O26, warnings=[], route=rdkit-capped,
# per_ligand_h={4:6}, h_types={sp2 C-H:24}; 与 CoRE 2007[Zn][pcu]3[ASR]3 组成一致；
# μ4-O（4 Zn，Zn-O 1.943 Å）与羧酸根 O 均未加 H

& $PY -m cifkit repair tests/data/mof5_cod_hfree.cif -o runs/_wp2_mof5_cod.cif --add-h --json
# added_h=96,  natoms=424, Zn32 H96 C192 O104, warnings=[]; 与 COD 1516287 组成一致
# （COD 4340010 原始 CIF 本身无 H，独立真实数据交叉验证）

& $PY -m cifkit repair tests/data/uio66_hfree.cif  -o runs/_wp2_uio66.cif  --add-h --json
# added_h=28,  natoms=114, Zr6 H28 C48 O32, warnings=[], route=mixed（BDC RDKit + 4 个 μ3-OH 几何）,
# per_ligand_h={4:6, 1:4}, h_types={sp2 C-H:24, sp3 O-H:4}; 与 CoRE CR 组成一致

& $PY -m cifkit repair tests/data/hkust1_hfree.cif -o runs/_wp2_hkust1.cif --add-h --json
# added_h=24,  natoms=156, Cu12 H24 C72 O48, warnings=[], route=rdkit-capped,
# per_ligand_h={3:8}, h_types={sp2 C-H:24}; 与 CoRE NCR 组成一致

& $PY -m cifkit repair tests/data/terephthalic_acid_hfree.cif -o runs/_wp2_tpa.cif --add-h --json
# added_h=2（自由羧酸 2 个 O–H）, natoms=18, C8 H6 O4, warnings=[]

# H 完整参考：必须 no-op（added_h=0, warnings=[]）
& $PY -m cifkit repair tests/data/mof5_h.cif     --add-h --json
& $PY -m cifkit repair tests/data/mof5_cod_h.cif --add-h --json
& $PY -m cifkit repair tests/data/uio66_h.cif    --add-h --json
& $PY -m cifkit repair tests/data/hkust1_h.cif   --add-h --json
```

补氢几何实测（`tests/test_repair.py` / `tests/test_repair_carboxylate.py` 内独立校验，
不复用补氢代码的键表）：

* 环 C–H：H 在环平面内（最大偏离 0.004 Å / 羧酸根 MOF < 0.1 Å），H–C–N/C 角 125.7°，
  BDC/BTC 环 H–C–C 115–125°；
* 甲基：H–C–C = 109.5°，H–C–H = 109.5°（理想四面体）；
* 无 N–H（两个咪唑 N 都配位 Zn）；H···H 最小 1.796 Å；
* 羧酸根 MOF：C–H 1.10 Å、μ3-O–H 0.96 Å，H 背离 Zr（H···Zr > 2.5 Å），
  H···H > 1.4 Å、H···金属 > 2.0 Å；
* 补氢后再 `cifkit validate` 通过，`C–H` 为最短键（1.10 Å）；
* `2x2x1` 超胞（276×4 = 1104 原子）与 `(111)` slab + 15 Å 真空（实测 15.64 Å）可继续跑通
  （geom 队友的 `make_supercell` / `make_slab` 联调通过）。

## 10. 局限（务必如实引用）

1. **只对有机骨架补 H**：C/N/O/S/B/P/Si/Se 的常规价态。硝酸根、高氯酸根、叠氮、硼烷/
   碳硼烷、金属有机配体（Cp、CO、卡宾、烷基）等特殊价态没有专门建模，可能不补或误补。
2. **金属氢化物/氢负离子**：H 与金属成键的结构（如 ZrH、MgH₂）不适用；已与 H 成键的 H
   不会被处理，孤立 H 只报 warning。
3. **自由基、碳正/碳负离子、混合价**：价态按"中性闭壳层"推断，自由基/离子会按中性补 H；
   需要外部电荷/自旋信息才能正确判断。
4. **羧酸根的质子化状态无法从几何唯一确定**：本实现默认去质子化（不补 O–H），
   若输入实际是 –COOH 且 O–H 缺失，会漏补（action 中记录"carboxylate-O 阴离子"）。
   同理，未配位的去质子化杂环（游离咪唑负离子）可能按中性分子补 1 个 N–H。
5. **依赖输入几何质量**：成键用共价半径 + 1.15/1.30 因子；金属–配体键特别长（>2.6 Å 量级）
   或距离异常时可能漏判配位键，从而误补 H。未经 DFT 优化的 CIF（如 X 射线 H 位置偏短、
   N–H ≈0.86 Å、C–H ≈0.93 Å）不做键长归一化：已有 H 原样保留，补氢时新放的 H 用
   1.09/1.01/0.96 Å 标准键长。**已有 X 射线 H 键长偏短不算缺陷**（contacts/valence 都做了
   "最近邻 H–X 是键"的豁免）。
6. **部分占据重原子**：没有 disorder group、也没有 0.7 Å 内替代位点时按主元素升为全占据，
   会丢信息（warning 记录）。
7. **周期性有机聚合物片段**（没有金属断开、共价连接跨晶胞）：RDKit capping 无法构造有限
   分子，自动退回纯几何补位（route = `geometric-vsepr` / `mixed`）。
8. **单胞/对称性**：本层不做对称化、不改变晶胞/坐标框架；成键分析按输入结构（含 H 位置）。
9. **不支持的键**：三中心键、H 桥、金属–金属键、f 电子强关联体系不在建模范围内。
10. **性能**：补氢需要按原子枚举候选并对 27 个周期像做距离检查；ZIF-8（276 原子）约 2 s，
    750 原子级约 10 s 量级，超大结构（>1 万原子）会明显变慢（无邻居裁剪）。
11. **拓扑/化学正确性边界**：报告只声称"价态与几何合理"，不声称"已做量子化学验证"。
12. **有机金属 M–C 键只建模 σ 型**（round 17）：距离窗口
    `min(max(1.02·(r_M+r_C), 2.30), 2.65) Å` + **价键守卫**（碳必须还有空价）；
    η⁵/η⁶ 离域、M–M、M–H、桥连羰基、4d/5d 长 σ 键（>2.65 Å）仍不建模，
    且每个环碳各记一条 σ 键会使金属**配位数偏高**。详见 §12。
13. **μ3-O / μ3-OH 仅靠几何可能混淆**：判据是 M–O 距离双峰（§8.2）。若距离单峰或连续，
    保守按 oxo 不补 H 并写 warning，可能少补 O–H；若结构在去质子化/脱 H 后发生弛豫，
    距离判据也可能失效。oxo/hydroxo 的最终判定需要化学式 H 预算、电荷或中子/DFT 信息。
14. **自由羧酸判定依赖"全结构无金属配位"**：带金属的 MOF 里若真有未配位的 –COOH
    （缺陷/客体重排），会被保守当作阴离子不补 O–H；需要外部化学式/电荷信息才能判定。
15. **真实缺氢 NCR 数据几何质量**：CoRE 2024 的 UiO-66 真实 NCR 缺氢候选几何扭曲
    （1.27 Å C···C 接触、μ3-O 距离无双峰），本轮不用于验收；CoRE 2024 没有 canonical
    MOF-5（MOF-5 fixture 来自 COD 真实 CIF）；HKUST-1 无真实缺氢版（用 synthetic）；
    MIL-101 未验证（COD 4000663 解析为 16000 原子且含部分占据 O）。详见 §8.5。

## 11. 复现与自测

```powershell
$env:PYTHONIOENCODING='utf-8'
$PY = '<repo>\.venv\Scripts\python.exe'
Set-Location '<repo>'

& $PY -m pytest tests/test_repair.py -q
& $PY -m pytest tests/test_repair.py tests/test_repair_carboxylate.py -q
& $PY -m pytest tests -q            # 全量（含其它模块）
```

单独使用补氢：

```python
from pymatgen.core import Structure
from cifkit.repair import repair_all, add_hydrogens, check_structure

s = Structure.from_file("tests/data/zif8_raw_hfree.cif")
repaired, report = repair_all(s, add_hydrogen=True)
print(report.added_h, len(repaired), report.warnings)      # 120 276 []
print(report.actions[1]["route"])                           # rdkit-capped

repaired2, stats = add_hydrogens(s)                         # 只补氢
print(stats["detail"])
print(check_structure(repaired2)["detail"])
```

---

## 12. 有机金属 M–C 键（round 17，局限 C3 的部分修复）

修复层过去**完全忽略**金属–碳接触，以避免羧酸型 through-space 接触（Zr···C ≈ 3.2 Å）
污染碳价键。代价是真实的 σ 型 M–C 键（Cp、烷基、羰基）不被识别 → 碳看起来缺价 →
修复层会**乱补氢**（实测：二茂铁被补 8 个 H，ZnMe₂ 每个甲基被补 2 个 H）。

现在按两条互补判据识别：

| 判据 | 规则 | 依据 |
|---|---|---|
| 距离窗口 | `min(max(1.02·(r_M+r_C), 2.30), 2.65) Å` 之内 | 真实 σ 键：Fe–C 2.04（Cp）、Zn–C 1.95（ZnMe₂）、Cr–C 1.92（Cr(CO)₆）、Mg–C ~2.15、Cp₂ZrCl₂ Zr–C ~2.5；through-space 羧酸 M···C ≥ 2.8 |
| **价键守卫** | 只有当碳的**非金属**键级和 < 4 时才保留 M–C 键；否则丢弃并记警告 | 羧酸/酰胺碳已被自身 σ/π 键饱和，短 M···C 是"配位到基团"而非碳 σ 键 |

识别到的键标记为 `Bond.organometallic=True`，计入碳价键和（这正是阻止补氢的机制），
并在 `BondGraph.organometallic_bonds` 计数、`warnings` 说明。

**实测效果**（`tests/test_organometallic.py`，12 条）：

| 体系 | 修复前 | 现在 |
|---|---|---|
| 二茂铁（Cp₂Fe，Fe–C 2.04） | 10 个 Cp 碳中 8 个被判缺 1 H → **+8 H** | 10 条 Fe–C，全部 C 价键和 = 4，**+0 H** |
| ZnMe₂（Zn–C 1.95） | 每个甲基 **+2 H** | 2 条 Zn–C，**+0 H** |
| η⁶-苯–Cr（Cr–C ~2.2） | 苯环碳缺价 | ≥6 条 Cr–C，**+0 H** |
| 乙酸根 Zr···C 2.5 Å（窗口内） | — | **被价键守卫丢弃**（碳已饱和，记警告） |
| 乙酸根 Zr···C 2.8 / 3.2 Å | 不识别 | 不识别 ✅ |
| ZIF-8（真实 Zn–N MOF 回归） | 无警告 | **0 条 Zn–C**、**0 警告**（Zn–N⁺=C 的 Kekulé 形式被允许） |

顺带修正的两个 Kekulé 缺陷（由本轮测试暴露）：
① 解可能给同一碳两条环双键（价键和 5）→ 现在有**价键后验**，越界就退回分数 π 键并记警告；
② 饱和杂原子（如 Zn 配位的咪唑 N）过去会被静默写成四配位 → 现在作为"高代价候补"，
优先选有空价的伙伴，必要时才写成 `Zn–N⁺=C`。

**仍然不建模**：η⁵/η⁶ 的多重度与离域（每个环碳一条 σ 键 → 金属配位数偏高）、M–M 键、
金属氢化物 M–H、桥连羰基、4d/5d 金属 >2.65 Å 的长 σ 键。
