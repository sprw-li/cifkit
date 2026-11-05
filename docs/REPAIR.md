# 修复层（REPAIR）：补氢 / 无序占位 / 过近原子 / 价态检查

> Owner：repair 队友（task-2）。接口冻结见 `docs/DESIGN.md` §6：
> `repair_all(structure, *, add_hydrogen=False, resolve_disorder=True, remove_close_contacts=True) -> (Structure, RepairReport)`。
> 入口：`D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe -m cifkit repair FILE ...`。
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
   `d < 1.30*(r_i+r_j)` 并标记为 **metal bond**。金属–金属、H–H 对不计成键。
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
| O | 2 | 与金属配位不补；**羧酸根 O 视为去质子化阴离子，不补 H**（action 中有说明） |
| S | 2（4/6 允许） | 金属配位不补 |
| B/P/Si/Se | 3/3/4/2 | 同上 |
| 其他元素 | 不处理 | 见 §9 局限 |

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
* 再叠加 §6 的独立 `valence.check_structure`（重新做一遍周期键感知），双保险。

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

## 8. 验收数字（本机实测，2026-11）

```powershell
$env:PYTHONIOENCODING='utf-8'
$PY = 'D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe'

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
```

补氢几何实测（`tests/test_repair.py` 内独立校验，不复用补氢代码的键表）：

* 环 C–H：H 在环平面内（最大偏离 0.004 Å），H–C–N/C 角 125.7°；
* 甲基：H–C–C = 109.5°，H–C–H = 109.5°（理想四面体）；
* 无 N–H（两个咪唑 N 都配位 Zn）；H···H 最小 1.796 Å；
* 补氢后再 `cifkit validate` 通过，`C–H` 为最短键（1.10 Å）；
* `2x2x1` 超胞（276×4 = 1104 原子）与 `(111)` slab + 15 Å 真空（实测 15.64 Å）可继续跑通
  （geom 队友的 `make_supercell` / `make_slab` 联调通过）。

## 9. 局限（务必如实引用）

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

## 10. 复现与自测

```powershell
$env:PYTHONIOENCODING='utf-8'
$PY = 'D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe'
Set-Location 'D:\Dev\Project5-skill-cif'

& $PY -m pytest tests/test_repair.py -q
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
