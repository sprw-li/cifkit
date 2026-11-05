# Round 6 独立评审：4 个测试实例（u1–u4）+ cif-usecases 技能

> 评审员：`reviewer-r1`｜日期：2026-11-05｜时间盒：30–45 min。
> 基线：项目仓 `c32f57d`、agent-library `75acddd`（两仓工作树干净；agent-library 仅无关历史 untracked `catalog/condopt-router/`）。
> 方法：先跑 Lead 的 `usecases/verify_usecases.py`（22/22 PASS，作为对照），**再全部用评审员自写脚本独立复算**（`runs/review_round6/independent_round6.py`，不调用 verify_usecases）。未改任何代码/文档。

## 0. 结论

**交付本体：PASS。** 4 个用例的关键数字我均独立复算通过；诚实性（来源标注、未核实标注、69 vs 100 表述）没有发现造假。**但发现 1 个 P1（路由）+ 1 个 P2（测试数）**，建议修复后再作为最终基线。

| 项 | 判定 | 独立复算数字 |
|---|---|---|
| u1 Fd-3m 6 例 | **PASS** | 6/6 CIF 我自己用 pymatgen `SpacegroupAnalyzer` → **#227**；6/6 本地 CIF sha256 == examples.csv；COD 在线重下 9008564 → sha `ba61fb…` == provenance；PNG 3740×2822 |
| u2 cF/tI + 14 Bravais | **PASS** | 自建 14 种点阵 **14/14** SG 与 expected 一致（含 aP#2/mC#12/oF#69/hR#166/tI#139）；自建 bct **c/a=1→#229、c/a=√2→#225、c/a=1.2→#139**；5 组等价实测全中；report 明确"特殊度量等价 ≠ 点群相同"（阶 48 vs 16） |
| u3 金属批量 | **PASS** | 独立数 pymatgen `is_metal`=**87**；summary=69、元素目录=69、failures=18、run_report=87；5 元素 bulk SG 与 CSV 全一致；5 个 slab 真空自算 **15.0 Å**；slab 面积与 CSV 一致；缺 18 元素目录确实不存在 |
| u4 Fe-C 套件 | **PASS** | 7/7 CIF 我自己 spglib → SG 与 CSV 一致（62/15/186/58/191/187/225），sha 与 aflow_cif_sha256 一致；自建 289 条 (x_C,E) 下凸包 → **顶点只有 x=0/1（Fe、C）**；25 at%C 最低 C4Fe12 **+0.0456359 eV/atom**；Fe2C **+0.0515647**；zip 87 项含 README/scripts/VASP |
| 诚实性 | **PASS** | AFLOW/ICSD/COD/教材来源均显式标注；u3 明确"用户说 100 是近似→87 种→导出 69、18 missing 未编造"；u4 相图数字标"教材值/未逐条联网复核"；无 MP 冒充 live |
| 路由 | **FAIL → P1-1** | 4 条用户原句中 **#1 失败**（见 §2） |
| 回归 | **PASS** | pytest **145 passed / 290 s**；check_all --fast **6/6**；verify_demo 8/8；eval 83/83；ci 绿；两仓 git 干净 |

---

## 1. 各项独立复算细节

### u1（Fd-3m 教学图）
- 6 个结构（C/Si/MgAl2O4/Fe3O4/Y2Ti2O7/LiTi2O4）逐个用 `SpacegroupAnalyzer(symprec=0.01/0.1)` → **全部 #227（Fd-3m, m-3m）**。
- `data/structures/*.cif` 的 sha256 与 `examples.csv` 的 `sha256` **6/6 一致**；`provenance.json` 记录 **COD×5 + AFLOW×1**（与 README "COD×5 + AFLOW/ICSD×1" 一致：LiTi2O4 为 `aflow:…ICSD_81329`）。
- 在线复核 COD 9008564：重新 `GET https://www.crystallography.net/cod/9008564.cif` → 5034 B，sha256 == provenance（`ba61fb…`），证明 COD id 确实对应该结构。
- 图 `fd3m_examples.png`：**3740×2822**、1 964 175 B（README 声称 3740×2822 ✓）。

### u2（cF/tI + 14 Bravais）
- 按 `bravais14.csv` 的 construction 字段**自建** 14 个点阵（P/C/I/F 心基元）→ 14/14 SG 与 expected 一致：aP 2、mP 10、**mC 12**、oP 47、oC 65、oI 71、**oF 69**、tP 123、**tI 139**、hP 191、**hR 166**、cP 221、cI 229、cF 225。
- 自建 bct（a=b=2.5562；2 原子基元）：c/a=1 → **#229 Im-3m**；c/a=√2 → **#225 Fm-3m**；c/a=1.2 → **#139 I4/mmm**。
- 等价对照独立复现：E00 (1.20→139)、E01 (1→229)、E02 (√2→225)、E03 (菱方 α=60°→225)、E05 (α=109.4712°→229) 全中。
- `report.md` 口径正确：**"cF≡tI 是特殊度量下的等价，不是点群相同；点群阶 48 vs 16、空间群号 225 vs 139"** —— 没有把"特殊度量等价"说成"点群相同"。

### u3（87 金属 → 69 导出）
- 我独立用 pymatgen 遍历 118 元素：`is_metal` 计数 = **87**；`metals_summary.csv` 69 行、`elements/` 69 个目录、`failures.json` 18 项、`run_report.csv` 87 行；18 个 missing 元素**确实没有目录**。
- 来源拆分与 README 一致：ASE 58 / AFLOW 7 / COD 4（我按 `lattice_source` 前缀统计）。
- 抽 5 个元素：bulk SG 与 CSV 全一致（Fe 229 Im-3m / Cu 225 Fm-3m / Mg 194 P6₃/mmc / Sn 141 I4₁/amd / Mn 217 I-43m）；slab 我自算真空全部 **15.0 Å**、表面积与 CSV 一致（±5%）；schicht 厚度是层间距的整数倍（Fe/Cu=5.0×d；Mg/Sn 以半层间距计=5×；Mn 复杂结构非整数但 SG/面积/真空一致）。
- 缺失原因与任务提示一致：Fr/Cm/Bk/Cf/Es → AFLOW LIB1 查询 0 条（"无公开结构"）；Fm–Cn 等 13 个 → ASE 无条目且无确立的实验结构。u3 README 明确"**100 是近似 → 87 种**，导出 69，18 missing 未编造"，未把 69 说成 100。

### u4（Fe-C 套件）
- 7 个结构 CIF 自算 SG 与 `fe_c_compounds.csv` 全一致（Fe3C 62 Pnma、Fe5C2 15 C2/c、Fe7C3 186 P6₃mc、Fe2C-ortho 58 Pnnm、Fe2C-hex 191 P6/mmm、FeC-WC 187 P-6m2、Fe23C6 225 Fm-3m），CIF sha256 == `file_sha256_cif`。
- **独立凸包复算**（289 条 AFLOW LIB2 形成焓 + Fe/C 端点，单调链求下凸包）：hull 顶点只有 `x_C=0.0`（Fe）与 `1.0`（C）；25 at%C 处最低条目 C4Fe12 = **+0.0456359 eV/atom**（== README 的 +0.0456）；Fe2C 最低 C2Fe4 = **+0.0515647**（== +0.0516）。`hull_points.csv` 的 `energy_above_hull` 与我的复算一致。
- `fe_c_kit.zip`：87 项，含 README、data CSV、structures/CIF+POSCAR、vasp_inputs/INCAR+KPOINTS、scripts（可离线重算，替换 VASP 能量）。
- 相图笔记：数字均标"教材值"（Callister 9e / Porter-Easterling）且**显式写"本环境未逐条联网复核"**；争议值（Fe3C 熔点等）标"未核实"——诚实。

---

## 2. 问题清单

### P0：无。

### P1-1（路由）：用户原句 #1 第一候选不是 cif-usecases（eval 83/83 掩盖了空格差异）

- 复现（用户原句，来自 `usecases/README.md` 表格）：
  ```powershell
  py -3 D:\agent-library\router.py route --agent dsh "我需要向学生们讲解 Fd3m 点群的性质，帮我找一些典例，排成 png"
  ```
- 期望：`intent=cif-advanced-usecases`，第 1 候选 `cif-usecases`。
- 实际：**`intent=molecular-property`，第 1 候选 `rdkit-screen`（score=5）**。
- 根因/证据：`catalog/evals/routing.jsonl` 新增的第 1 条 eval 文本是**无空格变体** `"我需要向学生们讲解Fd3m点群的性质，帮我找一些典例，排成png"`（真实文件里无空格），该变体路由正确（score=15 → cif-usecases）；而用户原句（讲解 + " Fd3m" 有空格、`排成 png` 有空格）失败。
- 影响：`eval_router --all` 仍 **83/83 = 100%**（eval 用的是无空格文本），但**用户实际原句会被派给 rdkit-screen**；任务要求的"4 条用户原句第一候选"为 3/4。另外 3 条原句均正确（cF/tI、100 金属、Fe-C → cif-usecases）。
- 建议：① 在 `cif-advanced-usecases` 的 patterns 里加空格容忍（如 `F\s*d\s*-?\s*3\s*m`、`点群`、`布拉维`、`纯金属`、`铁碳` 等强词）；② 给 `molecular-property`/`install-app` 加 excludes（含 `点群|布拉维|Fd3m|Fd-3m|晶格|相图`）；③ 把**用户原句原文**（含空格）加入 eval，重新跑 eval/ci。

### P2-1：测试数 144 → 实际 **145**（文档过期）

- 声称：`README.md:112` `# 144 passed`、`README.md:148` `测试总数 **144**`、`docs/PIPELINE.md:230`/`252` `144`。
- 实测（本机）：`pytest tests` → **145 passed, 2 warnings in 290.36s**，exit 0；`--collect-only` = **145**：cli 11 / export 20 / geom 34 / pipeline 3 / repair 12 / sources 17 / sources_mp_aflow **12** / spec 7 / topology 15 / validate 14。
- 差异来源：`tests/test_sources_mp_aflow.py` 从 11 → **12**（新增 1 条，疑与 AFLOW PAW 势名修复/98c2a71 相关）。建议改为 145。

### P2-2（观察，非缺陷）：本轮全量 pytest / check_all 运行时间显著变长

- `pytest tests` 290 s（Round 5 为 66 s）；`check_all --fast` 中 pytest(cli+spec) 265 s（Round 5 为 24 s）、eval 165 s、ci 129 s。评审时我并行跑了多组 pytest/eval（CPU 竞争）+ 部分用例含 COD/AFLOW 联网，估计是环境/网络负载导致，不是功能回归；`eval 83/83`、`verify_demo 8/8`、`check_all 6/6` 均通过。建议 Lead 在干净环境复跑一次记录真实耗时。

---

## 3. 我实际跑过什么

1. `& $PY usecases\verify_usecases.py` → **22/22 PASS，exit 0**（对照）。
2. **自写 `runs/review_round6/independent_round6.py`**（不 import verify_usecases）：
   - u1：6 CIF 逐个 spglib；sha 对照 examples.csv；COD 9008564 重新下载比对 sha；PNG 尺寸。
   - u2：按 CSV construction 自建 14 点阵 + bct 三度量 + 5 组等价，spglib 复算。
   - u3：独立数 `is_metal`=87；解析 5 元素 bulk/slab，自算真空/面积/SG；检查 18 missing 无目录。
   - u4：7 CIF spglib；从 289 条 formation energy 独立求下凸包与 Fe3C/Fe2C above-hull；zip 内容。
3. `route` 4 条用户原句（含空格原文）→ P1-1；另测无空格变体确认差异。
4. `eval_router --all` → 83/83、负例 0/25、槽位 11/11、exit 0；`ci.py --fast` → 同上、exit 0。
5. `pytest tests` → **145 passed / 290 s / exit 0**；`--collect-only` → 145。
6. `scripts/check_all.py --fast` → **6/6 groups PASS**（selftest 7/7、pytest fast、verify_demo 8/8 artifacts=12、router 第一候选 cif-workbench、eval 83/83、ci 绿）。
7. `git log/status` 两仓；`c32f57d` 含 `usecases/`（639 个跟踪文件）与 verifier；`75acddd` 含 `catalog/cif-usecases/{SKILL.md,manifest.json}` + intents/domains/evals。

## 4. 没有验证的部分

1. **教材相图数字**（1147/727 °C、4.30/0.76 wt%C、熔点等）：Lead 自己已标"教材值、未逐条联网复核"，我也**未**联网逐条核对（无可靠公开源时无法独立验证）。
2. **AFLOW LIB2 数据的新鲜度/完整性**：我基于交付的 289 条 CSV 复算 hull；未重新从 AFLOW 拉全库核对 289 条是否完整（只抽查了 Fe3C 对应 CIF 的 sha 与 CSV 一致）。
3. **u3 全部 69 元素**：只抽 5 个（Fe/Cu/Mg/Sn/Mn）做 bulk SG/slab 真空/面积复核；未逐个元素检查面指数合理性（如复杂结构的平面选择启发式）。
4. **u1 PNG 内容级校验**：只验证尺寸/字节数与结构来源；未 OCR 检查图中每个标注文字与 CSV 完全一致。
5. **AFLOW/COD 在线可用性波动**：只做了一次 COD 重下载；AFLOW 未重新拉数据（依赖已缓存的 CIF/sha）。
6. **MP**：4 个用例未使用 MP；MP 无 key / 未 live 的诚实性在 Round 4/5 已审，本轮未重复。
7. **修复后复验**：若 Lead 修 P1-1（路由 patterns）与 P2-1（145），建议只重跑 4 条原句 route + eval_router + 一次 collect 计数即可。

## 5. 证据索引（`runs/review_round6/`）

| 文件 | 内容 |
|---|---|
| `independent_round6.py`、`round6_checks.json`、`independent_round6.log` | u1–u4 全部独立复算结果 |
| `router_four.txt` | 4 条用户原句路由（含 #1 失败证据） |
| `pytest.txt`（145 passed / 290 s） | 全量测试 |
| `collect.txt` | collect 145 分布 |
| `check_all_fast.txt` | 6/6 groups PASS 原始输出 |
| `verify_demo.txt` | verify_demo 8/8 artifacts=12 |
