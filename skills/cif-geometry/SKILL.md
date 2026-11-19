---
name: cif-geometry
description: >-
  晶体结构几何变换：标准化原胞/常规胞、做超胞（Supercell）、沿 (hkl) 切 slab 表面、
  设置并实测真空层、提取金属簇/SBU；每步输出原子数、晶胞参数和实测真空值。
---

# cif-geometry（超胞 / 切面 / 真空 / 金属簇）

只改几何（晶胞、原子位置、周期性），不改化学组成。真空层一律**实测**（原子到周期像的最小距离），
报告里写实测值，不写名义值。

## 何时使用

- 要把原胞放大成超胞（如 `2x2x1`）；
- 要沿某个晶面切 slab（如 `(111)`），并设层厚/真空层；
- 要调真空层厚度或核验现有真空够不够；
- 要提取金属簇 / SBU 做后续计算。

**不要用**：补氢/修无序（用 `cif-repair`）；只是换文件格式（用 `cif-export`）；整条链（用 `cif-workbench`）。

## 关键语义：`--supercell` + `--surface` 一起给时才叫“面内重复”

`make_slab(..., reps=..., frame=...)` 有两套语义（DESIGN §6f），CLI 用 `--surface-frame` 选：

| 场景 | 语义 | 原子数 |
|---|---|---|
| 只给 `--supercell 2 2 1`（无 `--surface`） | 普通超胞（直接乘晶胞） | 输入 × 2×2×1 = **×4** |
| `--surface 1 1 1` + `--supercell 2 2 1`，**默认 `--surface-frame slab`** | 先切体相的 `(111)` 面得到 slab，再把 `2x2` 作为 **slab 面内重复**（`reps[2]` 必须为 1） | `base_atoms × 4`；demo：276 → base 552 → **2208** |
| `--surface 1 1 1` + `--supercell 2 2 1` + `--surface-frame cell` | 字面语义：先做 2x2x1 超胞，再切该胞的 `(111)` | 另一张表面；**取向不是立方 (111)**，仅作 caveat 对照 |

“2x2x1 超胞，再沿 (111) 切”在物理上应理解为 **slab 面内 2x2**（默认 `slab`）；
要严格字面复现“先超胞后切面”才用 `--surface-frame cell`，并在报告里注明是另一种表面。

## 依赖

```powershell
$PY = 'D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe'
Set-Location 'D:\Dev\Project5-skill-cif'
$env:PYTHONIOENCODING='utf-8'
```

## 命令

```powershell
# 1) 纯超胞 2x2x1（无切面 → 原子数 = 输入 × 4）
& $PY -m cifkit geom "D:\Dev\Project5-skill-cif\tests\data\zif8_cr_sod.cif" `
    -o runs\geom\supercell.cif --supercell 2 2 1 --json

# 2) 标准胞（原胞 <-> 常规胞，去重复）
& $PY -m cifkit geom "D:\Dev\Project5-skill-cif\tests\data\zif8_cr_sod.cif" `
    -o runs\geom\standard.cif --standardize --json

# 3) (111) slab + 面内 2x2 + 15 Å 真空（demo 语义，默认 frame=slab）
& $PY -m cifkit geom "D:\Dev\Project5-skill-cif\tests\data\zif8_cr_sod.cif" `
    -o runs\geom\slab2x2.cif --standardize --surface 1 1 1 --supercell 2 2 1 `
    --thickness 15 --vacuum 15 --json

# 4) 字面语义对照：先 2x2x1 超胞，再切该胞 (111)（报告里注明不是立方 (111)）
& $PY -m cifkit geom "D:\Dev\Project5-skill-cif\tests\data\zif8_cr_sod.cif" `
    -o runs\geom\slab2x2_cellframe.cif --standardize --surface 1 1 1 --supercell 2 2 1 `
    --surface-frame cell --thickness 15 --vacuum 15 --json

# 5) 只调真空层（单步，返回实测值）
& $PY -m cifkit geom runs\geom\slab.cif -o runs\geom\slab_vac20.cif --vacuum 20 --json

# 6) 提取金属簇 / SBU
& $PY -m cifkit geom "D:\...\zif8_cr_sod.cif" -o runs\geom\sbu.cif --cluster sbu --json
```

## 参数表

| 参数 | 说明 | 默认 |
|---|---|---|
| `FILE` | 输入 CIF | — |
| `-o/--out` | 输出 CIF | 不写（只报告） |
| `--standardize` | 标准化：原胞 ↔ 常规胞、去重复、整理对称性 | 关 |
| `--supercell nx ny nz` | 三个整数倍；有 `--surface` 时按 `--surface-frame` 解释 | 无 |
| `--surface h k l` | 三个整数晶面指数（`1 1 1`） | 无 |
| `--surface-frame slab\|cell` | 有 `--surface` 时 `--supercell` 的语义（见上表） | `slab` |
| `--thickness Å` | slab 层厚目标 | 15.0 |
| `--vacuum Å` | 目标真空层厚度（会再精确设置并返回实测） | 无（`--surface` 时默认 15） |
| `--cluster sbu\|metal_cluster\|core` | 提取金属簇/SBU/核 | 无 |
| `--json` | 输出 `{natoms, formula, abc, angles, info:{slab, vacuum}}` | 人类可读 |

注意：有 `--surface` 时 `--supercell` **不会**先生成一个 `supercell.cif` 文件，而是作为 slab 的 `reps` 交给 `make_slab`；
`info.slab.frame / reps / in_plane_reps / base_atoms / atoms_after_reps` 会写清楚实际做了什么。

## 坑（都是真会踩的）

- **2x2x1 的语义**：默认是 slab 面内 2x2（demo 2208 原子 = 276 × 8），不是“先 ×4 再切”，
  更不是原子数 ×8 的普通超胞；只看 `natoms` 会误判，先看 `info.slab.frame/in_plane_reps`。
- **纯超胞是 ×4 不是 ×8**：`--supercell 2 2 1` 无 `--surface` 时，原子数 = 输入 × 4；`2x2x2` 才是 ×8。
- **真空按实测**：`info.vacuum` / `info.slab.vacuum_measured` 是原子到周期像的最小距离（Å），不是 `c/2`；
  目标 15 Å 时要求 `measured ≥ 15`。
- **slab 终止面**：切面时从多个候选终止面里按“悬空键 + 化学计量偏差”评分选最优，`info.slab.termination` 给出依据；
  不同终止面原子数不同，不能只看“成功了”。
- **`--thickness` 是目标不是承诺**：实际 `slab_thickness` 可能略大于目标（按完整原子层切），报告写实测。
- **standardize 会改原子数**：原胞/常规胞转换后原子数变化，先 standardize 再算倍数。
- **`--surface` 参数是整数 h k l**：`--surface 1 1 1`，不要传 `(111)` 字符串。
- **cluster 与其他几何操作一般不同时用**：先提簇再切面通常没意义；确定要做才叠加。
- **输出直接覆盖**：保留中间态就每步换 `-o` 文件名。
- **`--json` 的 slab 信息很大**（含全部候选终止面）；只看顶层字段或重定向到文件。

## 验收证据

1. `--json` 里有 `natoms`、`formula`、`abc`、`angles`；
2. 纯超胞：`after == before × 4`（2x2x1），且 `supercell.cif` 读回原子数一致；
3. slab（默认 frame=slab）：`info.slab.frame=="slab"`、`in_plane_reps==[2,2]`、`atoms_after_reps == base_atoms × 4`、
   `atoms_after_reps == len(slab2x2.cif)`；demo 数字 276 → 552 → 2208；
4. 真空：`info.slab.vacuum_measured`（或单步 `--vacuum` 的 `info.vacuum`）≥ 目标 15/20 Å；
5. 产物再过 `cifkit validate`，并核对晶胞参数变化符合预期。

```powershell
& $PY -m cifkit geom "D:\Dev\Project5-skill-cif\tests\data\zif8_cr_sod.cif" -o runs\geom\slab2x2.cif --standardize --surface 1 1 1 --supercell 2 2 1 --thickness 15 --vacuum 15 --json
& $PY -m cifkit validate runs\geom\slab2x2.cif --json
```

## 实测记录（2026-11-05，本机）

| 命令 | 结果 |
|---|---|
| `geom ... --supercell 2 2 1`（无 surface） | 138 → **552** 原子（×4），abc 29.339/29.339/14.669 |
| `geom ... --standardize` | 138 → **276** 原子（rhombohedral → cubic 16.939 Å） |
| `geom ... --standardize --surface 1 1 1 --supercell 2 2 1 --thickness 15 --vacuum 15` | frame=slab、in_plane_reps=[2,2]、input 276 → base **552** → after **2208**；abc 47.91/47.91/33.922；`vacuum_measured=15.1978`；耗时 3.58 s |
| 同上 + `--surface-frame cell` | frame=cell、reps=[2,2,1]、input 276 → cut_cell 1104 → base/after **2208**；abc 37.876/37.876/42.485、beta=101.54°（**不是立方 (111)**）；vac 15.4792 |
| `geom slab2x2.cif --vacuum 20` | 2208 原子，实测 `info.vacuum=20.149 Å` |
| `geom ... --cluster sbu` | 45 原子（Zn1 H20 C16 N8） |
| `validate slab2x2.cif --json` | `ok=true`，12 检查无 error |
