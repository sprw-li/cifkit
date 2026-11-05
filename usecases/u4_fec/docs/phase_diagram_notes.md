# Fe–C 相图与 0 K DFT 凸包：它们到底在说什么

本文件说明：**Fe–Fe₃C（亚稳）相图**的关键点、碳化物家族、以及本套件用 AFLOW LIB2
形成焓构建的 **0 K 凸包**如何与相图对应。

> 术语约定：本文中"未核实"表示该数字未能在本沙箱环境中从可访问的在线来源逐条核对，
> 只依据标准教材/手册的通行值，读者引用前请自行复核。

---

## 1. 先分清三张不同的图

| 图 | 变量 | 包含的相 | 本套件 |
|---|---|---|---|
| Fe–Fe₃C **亚稳**相图 | T–成分（wt%C），Gibbs 能 | bcc α(δ)、fcc γ、液相 L、Fe₃C | 与本文 §2、§3 对照 |
| Fe–**石墨**稳定相图 | 同上 | 上述 + 石墨（而不是 Fe₃C） | 概念对照，§3 |
| **0 K 凸包**（本套件 `data/hull_points.csv`） | 成分（at%C）– 形成焓 | 只有 Fe、C 与各种"线化合物" | 本套件直接计算 |

它们不是同一件事：相图是**有限温度下的 Gibbs 能**（含构型熵、振动熵、液相），
凸包是 **0 K、无熵、只含化学计量的焓**。把它们直接等同会犯两类错误（见 §5）。

---

## 2. Fe–Fe₃C 亚稳相图的关键点

纯 Fe 的同素异形转变（常压）：

| 转变 | 温度 | 说明 |
|---|---|---|
| α(bcc) → γ(fcc)，A₃ | **912 °C** | 纯铁 |
| γ(fcc) → δ(bcc)，A₄ | **1394 °C** | 纯铁 |
| δ(bcc) → 液相，熔点 | **1538 °C** | 纯铁 |
| 居里温度 A₂（α 相铁磁性消失） | **770 °C** | 纯铁 |

Fe–Fe₃C 亚稳系的三相/四相点：

| 反应 | 类型 | 温度 | 成分（wt%C） | 产物/相区 |
|---|---|---|---|---|
| δ + L → γ | 包晶 | **1493 °C** | 0.16（δ）、0.17（L→γ） | γ 开始 |
| L → γ + Fe₃C | **共晶** | **1147 °C** | **4.30** | **莱氏体**（γ+Fe₃C 的共晶组织） |
| γ → α + Fe₃C | **共析** | **727 °C**（A₁） | **0.76** | **珠光体**（α+Fe₃C 片层） |
| 碳在 γ 中的最大固溶度 | — | 1147 °C | **2.14** | 奥氏体上限（E 点） |
| 碳在 α 中的最大固溶度 | — | 727 °C | **0.022** | 铁素体上限（P 点） |

相区与组织：

* **δ-铁素体**：bcc，高温（1394–1538 °C）稳定，仅出现在包晶附近；
* **奥氏体 γ**：fcc，912–1394 °C 稳定；C 在 γ 中的溶解度大（1.7–2.14 wt%），
  是钢铁热加工与热处理的核心相；
* **铁素体 α**：bcc，室温稳定相，C 溶解度极低（≤0.022 wt% @727 °C）；
* **渗碳体 Fe₃C**：**正交 Pnma（#62, oP16）**，C 含量 6.67 wt%，硬而脆，
  在 230–727 °C 以下长期被认为"稳定"、实为**亚稳**；
* **珠光体** = α + Fe₃C 片层共析组织（727 °C、0.76 wt%C 附近）；
* **莱氏体** = γ + Fe₃C 共晶组织（1147 °C、4.30 wt%C 附近，白口铸铁）；室温下
  莱氏体中的 γ 还会继续转变为珠光体/马氏体（视冷却而定）；
* 亚共析钢（<0.76 wt%C）先析出 α；过共析钢（0.76–2.14 wt%C）先析出 **二次渗碳体**
  （Acm 线）。

**来源**

* W. D. Callister & D. G. Rethwisch, *Materials Science and Engineering: An Introduction*,
  9th ed., Ch. 9（Fe–C 相图：727 °C/0.76 wt%、1147 °C/4.30 wt%、1493 °C/0.16 wt%、
  2.14 wt%、0.022 wt%、770 °C、912 °C、1394 °C、1538 °C）。**教材值**，本环境未逐条联网复核。
* D. A. Porter, K. E. Easterling & M. Y. Sherif, *Phase Transformations in Metals and Alloys*,
  3rd ed., Ch. 1（Fe–C 系、Fe₃C 的亚稳性、珠光体/贝氏体/马氏体组织）。**教材值**。
* H. Föll, *The Iron Carbon Phase Diagram*（Kiel 大学教学页，可访问）：
  "Fe–Fe₃C 图不是真正的相图；真正稳定的是 Fe–石墨；渗碳体在常温下寿命以千年计"
  — https://www.tf.uni-kiel.de/matwis/amat/iss/kap_6/illustr/s6_1_2.html
  （2026-11 抓取，定性论述）
* DoITPoMS, University of Cambridge, *The Fe–C phase diagram* TLP（可访问）：
  共析成分约 Fe-0.8 wt%C、约 700 °C；珠光体=α+Fe₃C 片层；渗碳体为正交晶格
  — https://www.doitpoms.ac.uk/tlplib/microstructural_exam/HTML5/FeCphaseDiagram.html
  （2026-11 抓取，定性 + 约值）

**未核实/有争议的数字（本环境无可靠在线来源，未写入正文）**

* Fe₃C 自身熔点（常见引用 ~1227 °C 或 1250 °C，各教材不一致）——**未核实**；
* Fe–石墨**稳定**系的共晶（约 1153 °C / 4.26 wt%C）与共析（约 738 °C / 0.68 wt%C）
  ——**未核实**（ASM Handbook Vol. 3 应有，本环境无法访问，故不写入结论）；
* 各类碳化物在回火过程中的精确析出温度区间——**未核实**（只作定性描述）。

---

## 3. Fe–C 体系里到底有哪些"碳化物"

按碳含量从低到高（结构均以本套件 `data/fe_c_compounds.csv` 中实测 spglib 为准）：

| 化学式 | 结构（本套件实测） | Pearson | 常见称呼/说明 | 有 AFLOW 形成焓？ |
|---|---|---|---|---|
| Fe₂₃C₆ | Fm-3m #225 | cF116 | Cr₂₃C₆ 型；高碳/合金钢中常见 | 无（ICSD 结构） |
| Fe₃C | Pnma #62 | oP16 | **渗碳体 cementite** | **有，+0.0456 eV/atom** |
| Fe₂C（正交） | Pnnm #58 | oP6 | η-Fe₂C / 低对称 Fe₂C | 无；但 LIB2 中有同型 DFT 条目（+0.0516） |
| Fe₂C（六方） | P6/mmm #191 | hP3 | ε-Fe₂C 型（低温回火碳化物近似） | 无（ICSD 结构） |
| Fe₇C₃ | P6₃mc #186 | hP20 | 高碳钢/回火后期出现的过渡碳化物 | 无（ICSD 结构） |
| Fe₅C₂ | C2/c #15 | mS28 | **Hägg 碳化物 χ-Fe₅C₂** | 无（ICSD 结构） |
| FeC | P-6m2 #187 | hP2 | **WC 型 DFT 原型，实验无此相** | **有，+0.3957 eV/atom** |

* Fe₂C 还有多种多型（正交 Pnnm、六方 P6/mmm 等），本套件两种都收了；
* 实验上**没有**被确认的常压 FeC 化合物——本套件里的 `fec_wc_type` 是 AFLOW 在
  LIB2 中**用 DFT 构造**的 WC 型结构（P-6m2, hP2），只能当作"假想高碳端元"来用，
  不能当成实验相；
* 高温/高压下还存在其他 Fe–C 相（如 Fe₇C₃ 的正交多型、高压 Fe₂C 等），本套件未逐一收录。

**来源**：结构全部来自 AFLOW（LIB2 或 ICSD_WEB），空间群/Pearson 由
`scripts/fetch_structures.py` 用 spglib 实测（见 `data/fe_c_compounds.csv` 的
`spacegroup_number`/`pearson_symbol`/`sha256` 列）；相名称属于文献习惯用法，
"η/ε" 等标号在不同文献中并不完全统一。

---

## 4. 本套件的 0 K 凸包（可复跑）

`scripts/build_hull.py` 只读 `data/aflow_fe_c_energies.csv`（AFLOW LIB2 的 289 条
Fe–C 二元 DFT 条目，29 个不同 at%C 化学计量），取**每个成分的最低形成焓**，
加上按定义取 0 的两个元素端点（Fe bcc、C 参考态），求下凸包：

* 结果：**下凸包就是 x=0（Fe）到 x=100 at%C（C）的零线**，即 0 K 下
  **没有任何 Fe–C 二元化合物是热力学稳定的**；
* 因此所有碳化物都是**亚稳相**，其"高出 hull 的量"就等于它的形成焓：

| 相 | 来源条目 | at%C | E_form = E_above_hull（eV/atom） |
|---|---|---|---|
| Fe（bcc） | 端点 | 0 | 0 |
| **Fe₃C 渗碳体** | LIB2 C4Fe12 / prototype 180（Pnma 62, oP16） | 25.0 | **+0.0456** |
| **Fe₂C（正交 Pnnm）** | LIB2 C2Fe4 / prototype 257（与 ICSD 162104 同型） | 33.3 | **+0.0516** |
| **FeC（WC 型，DFT 假想相）** | LIB2 C1Fe1 / prototype 116（P-6m2 187, hP2） | 50.0 | **+0.3957** |
| FeC（50 at%C 处 LIB2 最低条目） | LIB2 C3Fe3 / prototype 721.BA（P-62m 189, hP6） | 50.0 | **+0.3843** |
| C（参考态） | 端点 | 100 | 0 |

其中 Fe₃C 的 +0.0456 eV/atom 与文献常见的 +0.05 eV/atom 量级一致（AFLOW LIB2 是
**别人算好的 PBE DFT 数据**，本套件没有重算）。Fe₂C（Pnnm）只比渗碳体高
**+6 meV/atom**，说明在 0 K DFT 里这两个亚稳相几乎简并——这解释了为什么
ε/η/χ 系列碳化物在回火过程中会随温度/时间竞争出现。

`data/hull_points.csv` 里每一行给出：该成分最低条目、形成焓、hull 能量、
`energy_above_hull_eV_per_atom`、`on_hull`、`status`（stable/metastable）。
由于两个端点都在 0，本体系的 hull 是平的，所以 `E_above_hull == E_form`，
这不是 bug，而是"Fe–C 没有稳定二元化合物"的直接体现。

**没有进入 hull 的相**：Fe₅C₂(Hägg)、Fe₇C₃、Fe₂C 实验结构、Fe₂₃C₆ 在 AFLOW 里
是 ICSD 结构条目，`enthalpy_formation_atom = null`，无法放到同一能量轴上。
本套件不拿文献值硬凑它们的凸包位置（那会引入未声明的误差来源）。
想看它们的位置，请在 `vasp_inputs/` 里自己算，然后用
`build_hull.py --energies my_energies.csv` 覆盖。

---

## 5. 0 K 凸包 vs 相图：怎么读才不自相矛盾

1. **hull 上只有 Fe 和 C**，不等于"相图是错的"。相图是有限温度 Gibbs 能：
   液相的混合熵、γ 相中间隙 C 的构型熵、以及振动熵都会改变相边界，
   0 K 的极小正形成焓（如 Fe₃C 的 45.6 meV/atom ≈ 4.4 kJ/(mol 原子)）在
   1000 K 量级的 TΔS 面前很小，但**不足以**让 Fe₃C 在 0 K 变稳定。
2. **为什么工业上还能用 Fe–Fe₃C 相图？** 因为石墨形核需要长程 C 扩散且界面能高，
   而渗碳体可以在晶界/位错处形核并长大，动力学上"锁定"了 Fe₃C；在普通碳钢的
   服役时间内石墨化几乎不发生（Föll 教学页："due time" 以千年计）。
   渗碳体因此是**长期存在**的亚稳相，"Fe–Fe₃C 相图"对工程是有效的。
3. **凸包能回答什么**：Fe₃C 是不是相对 Fe+石墨的亚稳相（是，+0.0456 eV/atom）；
   Fe₂C/Fe₇C₃/Hägg/FeC 的能量次序大概如何（本套件：Fe₂C≈Fe₃C ≪ FeC）；
   哪些成分值得用 DFT 再算（hull 上方 0.05–0.1 eV/atom 内的 Fe₂C/Fe₃C 是竞争最激烈的）。
4. **凸包的三个已知局限**（写论文/报告时必须声明）：
   * 0 K、无熵：不能预测共晶/共析温度，只能给"相对稳定性"；
   * 只含化学计量化合物：不能描述 γ/α 中的间隙固溶体，所以看不到"碳溶解度"；
   * 参考态：AFLOW 的元素参考是它自己的基态（C 端在 AFLOW LIB1 中最低的是类金刚石
     cF8 条目，比 hP4 石墨条目低约 2.5 meV/atom；这是 LDA 目录里的条目，
     LIB2 形成焓究竟以哪条为参考**未核实**）。
     这把 hull 在 C 端最多平移几 meV/atom，在 25 at%C 处影响 ≪ 1 meV/atom，
     **不改变"碳化物亚稳"的结论**。
5. **相图 ↔ 凸包 ↔ 碳化物清单的对应关系**：
   * 相图里 Fe₃C 的共析/共晶反应 → 凸包里 Fe₃C 的 +0.0456 eV/atom 亚稳点；
   * 相图里看不到 Hägg/Fe₇C₃ → 它们是回火过程中的**过渡**碳化物（动力学产物），
     在 0 K hull 上也应位于 hull 之上（本套件因无 AFLOW 焓未放入，**未核实**具体数值）；
   * 凸包里 FeC 很高（+0.38 eV/atom）→ 与"常压没有 Fe–C 1:1 稳定化合物"的实验事实一致。

---

## 6. 复现

```powershell
# 离线（只需 data/ 里的 CSV）
.venv\Scripts\python.exe usecases\u4_fec\scripts\build_hull.py
.venv\Scripts\python.exe usecases\u4_fec\scripts\plot_hull.py
# 网络（重新抓 AFLOW/ICSD 结构与能量）
.venv\Scripts\python.exe usecases\u4_fec\scripts\fetch_aflow_data.py
.venv\Scripts\python.exe usecases\u4_fec\scripts\fetch_structures.py
.venv\Scripts\python.exe usecases\u4_fec\scripts\make_vasp_inputs.py
```

所有数字都可在 `data/*.csv` 与脚本 stdout 中复现。
