---
name: cif-repair
description: >-
  修复 CIF 结构：缺氢补齐（碳上 H）、无序/部分占位解析、过近重复原子清理，
  输出 RepairReport（补了多少 H、去重多少、解析多少无序、警告）并做价态/近邻校验。
---

# cif-repair（补氢 / 无序 / 近邻）

原始 CIF 常见问题：碳上没有 H（论文只报重原子）、`H:0.5` 半占据、原子挨得过近。
这一步只改结构本身，不动晶胞参数。

## 何时使用

- 下载到的是 **raw / not computation-ready** CIF：`H/C=0` 或 H 明显少于化学计量；
- 结构里有 `0.5` 占据、统计原子、多位置/无序组；
- 有原子距离过近/重复原子，需要清理；
- 需要一份“补氢前后对照”的修复记录（`RepairReport`）。

**不要用**：结构本身已 computation-ready（补氢会 no-op，见“不适用”）；要改晶胞/超胞/切面（用 `cif-geometry`）；要做晶体学精修（本工具不做 Rietveld/精修）。

## 依赖

```powershell
$PY = 'D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe'
Set-Location 'D:\Dev\Project5-skill-cif'
$env:PYTHONIOENCODING='utf-8'
```

测试 fixture（已就绪，勿改）：

| 文件 | 用途 |
|---|---|
| `tests\data\zif8_raw_hfree.cif` | ZIF-8 常规胞 a=17.029，`Zn12 C96 N48`，**0 个 H** → 补氢主用例 |
| `tests\data\zif8_cr_sod.cif` | CoRE ASR sod 原胞 a=14.669，H 完整 → 补氢 no-op 对照 |
| `tests\data\zif8_disordered_h.cif` | a=17.107，48 全占据 H + 144 个 `H:0.5` → 无序用例 |

## 命令

```powershell
# 0) -o 的父目录要先存在（repair 不会自动建目录）
New-Item -ItemType Directory -Force runs\repair | Out-Null

# 1) 主用例：缺氢 ZIF-8 补碳上氢（预期 H: 0 -> 120，原子 156 -> 276）
& $PY -m cifkit repair "D:\Dev\Project5-skill-cif\tests\data\zif8_raw_hfree.cif" `
    -o runs\repair\zif8_repaired.cif --add-h --json

# 2) no-op 对照：H 完整的 computation-ready 结构，added_h 必须为 0
& $PY -m cifkit repair "D:\Dev\Project5-skill-cif\tests\data\zif8_cr_sod.cif" `
    -o runs\repair\zif8_cr_noop.cif --add-h --json

# 3) 无序/占位：解析 partial occupancy（默认开启）
& $PY -m cifkit repair "D:\Dev\Project5-skill-cif\tests\data\zif8_disordered_h.cif" `
    -o runs\repair\zif8_disordered_fixed.cif --json

# 4) 只做近邻清理，不允许补氢/不动无序
& $PY -m cifkit repair "D:\...\x.cif" -o runs\repair\contacts_only.cif --no-disorder --json

# 5) 修复后必须校验（价态/近邻/组成）
& $PY -m cifkit validate runs\repair\zif8_repaired.cif --json
```

## 参数表

| 参数 | 说明 | 默认 |
|---|---|---|
| `FILE` | 输入 CIF（位置参数） | — |
| `-o/--out` | 输出 CIF | 不写（只报告） |
| `--add-h` | 补碳上缺失的 H（核心能力） | 关 |
| `--no-disorder` | **不**解析无序/部分占位 | 关（默认解析） |
| `--no-contacts` | **不**清理过近/重复原子 | 关（默认清理） |
| `--json` | 输出 `{"report": {...}, "natoms": N, "formula": "..."}` | 人类可读 |

## 怎么读 RepairReport

`--json` 的 `report` 字段：

| 字段 | 含义 | 怎么用 |
|---|---|---|
| `added_h` | 本次补了多少个 H | 必须等于 `输出H - 输入H` |
| `removed_atoms` | 去掉的过近/重复原子数 | 非 0 要在报告里解释 |
| `resolved_disorder` | 解析的无序/占位原子数 | 与输入里的 `0.5` 占据数对照 |
| `actions[]` | 逐步动作 + 细节 | 写进报告“修复记录” |
| `warnings[]` | 无法自动处理的告警 | **必须逐条看**，不能吞掉 |

## 适用 / 不适用

| 适用 | 不适用 |
|---|---|
| 只报重原子的 raw CIF（碳上缺 H，如 ZIF-8 NCR `ja204757x_si_002`） | 已 computation-ready、H 完整（CoRE `CR/ASR`、COD 7111973）→ `added_h=0`，别当失败 |
| `H:0.5` / 统计原子 / 多位置 | 本来就不含 H 的体系（氧化物、金属、卤化物） |
| 原子过近/重复原子 | 需要电荷态/自旋态判定的体系（本工具不做） |
| 补氢前后对照的“体检” | 需要精修晶胞或实验数据约束的场景（不做 Rietveld） |

## 已验证的真实样例（本机实测）

`tests\data\zif8_raw_hfree.cif`（ZIF-8 常规胞，a=17.029 Å，`Zn12 C96 N48`，0 H）：

- 补氢后：`H` 0 → **120**，总原子 156 → **276**，`added_h=120`，`removed_atoms=0`；
- 补氢路线 `route=rdkit-capped`：24/24 个 2-甲基咪唑片段补氢成功，每配体 5 H（`sp2 C-H` 48 个 + `sp3 C-H3` 72 个）；
- 几何：C–H 键长 1.100 Å，最小 H···H 1.80 Å，最小 H···重原子 2.13 Å，最小 H···金属 2.87 Å；
- 价态：C **96/96 四配位**，Zn 配位 `CN={4: 12}`，`H/Zn = 10`，`c_valence_ok=true`；
- 输出的 `cifkit validate`：`ok=true`，9 个检查全过（natoms/composition/lattice/min_distance/hydrogen/carbon_coordination…）。

其它 fixture 实测：

- `zif8_cr_sod.cif`（H 完整）：`--add-h` → `added_h=0`，138 原子（`Zn6 H60 C48 N24`，rhombohedral）——正确 no-op；
- `zif8_disordered_h.cif`（含 `H:0.5`）→ `resolved_disorder=24`，276 原子（`Zn12 H120 C96 N48`），`added_h=0`（未要求补氢）。

在报告里写“补氢前后对照”时，贴出：`输入 H 数 / 输出 H 数 / added_h / C 键数分布 / warnings / route`。

## 坑

- **`--add-h` 的效果依赖输入**：拿到 computation-ready CIF（H 已完整）时 `added_h=0` 才是正确行为；这不是 bug，报告里要注明输入变体（`raw`/`computation-ready`）。
- **无序默认开**：只想看原始补氢效果时用 `--no-disorder --no-contacts` 固定变量，避免同时改两处。
- **补氢只补“碳上”**：金属配位水/羟基、末端 O–H 不保证补全；遇到 `warnings` 要人工判断。
- **几何不是 DFT 级**：补出的 H 位置是化学合理的几何，用于建模/预优化；正式计算前仍需弛豫。
- **别用 `tests/data/zif8_cr_sod.cif` 演示补氢**：它 H 完整，演示会得到 +0。
- **输出目录要先建好**：`-o runs\repair\x.cif` 的父目录不存在会 `FileNotFoundError`；先 `New-Item -ItemType Directory -Force`。
- **site label 警告可忽略**：无序修复后 `CifWriter` 可能报 “Site labels are not unique” UserWarning（label 重复，不是结构错误），但报告里要提一句。
- **输出覆盖**：`-o` 直接覆盖已有文件；保留原始文件用不同输出名。

## 验收证据

1. `--json` 的 `report.added_h == 输出结构 H 数 - 输入结构 H 数`；
2. 主用例数字：`added_h=120`、`natoms 156→276`；
3. `validate` 全绿（尤其 C 四键、近邻距离），`--json` 里 `"ok": true`；
4. `warnings` 每条都有处置说明；`resolved_disorder` 与输入占位数对得上。

```powershell
& $PY -m cifkit repair "D:\Dev\Project5-skill-cif\tests\data\zif8_raw_hfree.cif" -o runs\repair\zif8_repaired.cif --add-h --json
& $PY -m cifkit validate runs\repair\zif8_repaired.cif --json
```

## 实测记录（2026-11-05，本机）

| 命令 | 结果 |
|---|---|
| `repair tests\data\zif8_raw_hfree.cif --add-h` | `added_h=120`、156→276 原子、`route=rdkit-capped`、24/24 片段成功、C 96/96 四配位、`c_valence_ok=true` |
| `repair tests\data\zif8_cr_sod.cif --add-h` | `added_h=0`（no-op 对照）、138 原子 |
| `repair tests\data\zif8_disordered_h.cif` | `resolved_disorder=24`、276 原子（Zn12 H120 C96 N48） |
| `repair zif8_disordered_h.cif --no-disorder` | `added_h=0`、`resolved_disorder=0`，但默认近邻清理 `removed_atoms=72`（0.5 占位重复被删）——报告要解释 |
| `validate zif8_repaired.cif --json` | `ok=true`，9 检查全过（natoms/composition/min_distance/hydrogen/carbon_coordination…） |
