---
name: cif-export
description: >-
  把结构导出成"任何东西"：31 种计算/数据格式（VASP POSCAR、CIF、XYZ、EXTXYZ、JSON、PDB、SDF、MOL、
  LAMMPS data、QE pw.x、CP2K、GROMACS、Gaussian、ORCA、ABACUS、DFTB+、SIESTA、NWChem、FHI-aims、
  CASTEP、ABINIT、CRYSTAL、CUBE、XSF、CFG、Turbomole、DMol3、SHELX…），以及 12 种计算软件
  输入包（结构 + 输入模板 + README，明确列出 POTCAR/UPF/basis/skf 等用户必须补的项）。
---

# cif-export（cif → anything：格式 + 计算软件输入包）

把"处理好的结构"变成目标软件真正需要的文件。**凡是要导出/转换/生成输入，先看本技能。**
所有写出都会做回读校验（能回读的格式断言原子数一致；模板类断言关键段落并标 `template=True`）；
不提供 POTCAR/UPF/skf/赝势/力场文件，也不会把它说成"可直接运行"。

## 一、格式导出（`cifkit convert`）

```powershell
$PY = 'D:\Dev\Project5-skill-cif\.venv\Scripts\python.exe'
Set-Location 'D:\Dev\Project5-skill-cif'; $env:PYTHONIOENCODING='utf-8'

# 一个结构 → 多种格式（输入可以是 cif/poscar/xyz/json/xsf 等 pymatgen/ASE 能读的文件）
& $PY -m cifkit convert runs\demo_sod_zif8\standardized.cif --to vasp,cif,xyz,extxyz,json,lammps,qe,cp2k --outdir runs\exports --json
```

| 类别 | 格式 | 说明 |
|---|---|---|
| 结构/通用 | `cif`、`vasp`(POSCAR/CONTCAR)、`xyz`、`extxyz`、`json` | `extxyz` 带 Lattice/Properties，ML 友好；`json` 是 pymatgen 全量 dict |
| 可视化/分析 | `xsf`、`cfg`、`pdb`、`sdf`、`mol`、`struct`、`res`、`png`（预览图） | PDB/SDF/MOL 不表达周期性（用于分子/可视化）；`res` 是 SHELX 格式 |
| 分子动力学 | `lammps`(data)、`gromacs`(.gro)、`gen` | 只有坐标/拓扑骨架，力场/质量需自己补 |
| 电子结构 | `qe`(pw.x)、`cp2k`、`gaussian`(.gjf)、`orca`、`abacus`(STRU)、`dftb`(hsd)、`siesta`(fdf)、`nwchem`(nw)、`aims`(geometry.in)、`castep`(.cell)、`abinit`、`crystal`、`onetep`、`dmol`、`turbomole` | 多数是**输入模板**：赝势/basis/k 点/方法要用户补 |

- 别名：`poscar`/`contcar`→vasp、`gjf`→gaussian、`gro`→gromacs、`ext_xyz`→extxyz、`pymatgen-json`→json、`abacus-stru`→abacus、`fdf`→siesta、`data`→lammps、`pwscf`→qe、`xcrysden`→xsf。
- `--json` 时 stdout 是合法 JSON（`formats` 字段给每个格式的路径）；日志在 stderr。
- 写前会检查格式名，未支持会列出全部可用格式并 exit 2。

## 二、计算软件输入包（`--bundle`）

```powershell
# 结构 + 输入模板 + README（VASP: POSCAR/INCAR/INCAR.static/KPOINTS/POTCAR.readme）
& $PY -m cifkit convert runs\demo_sod_zif8\standardized.cif --bundle vasp,qe,cp2k --outdir runs\decks --json

# 也可以让 pipeline 在最后一步顺手生成（outdir\bundles\<code>\）
& $PY -m cifkit pipeline "<原句>" --outdir runs\demo --bundle vasp,cp2k
```

支持的 bundle：`vasp`、`qe`、`cp2k`、`lammps`、`gromacs`、`gaussian`、`orca`、`abacus`、`dftb`、`siesta`、`nwchem`、`aims`。
每个 bundle 返回 `files`、`missing`、`template=True` 与 README.md；**missing 列表就是用户必须补的东西**：

| bundle | 用户必须补 |
|---|---|
| vasp | POTCAR（按 POSCAR 元素顺序，用你 license 的 PAW） |
| qe | `<Element>.UPF` 赝势 + 收敛 ecutwfc/ecutrho/k 点 |
| cp2k | BASIS_SET / POTENTIAL（或 global basis 文件） |
| lammps | 力场（pair_style/pair_coeff）、data 里没有质量时补 mass |
| gromacs | 力场 .top/.itp（本工具不生成拓扑） |
| gaussian / orca | 方法/基组、电荷/多重度（模板默认 0/1） |
| abacus | upf 赝势 + orb 数值轨道 + INPUT（ecut/k 点/基组） |
| dftb | slakos/ 下的 Slater-Koster 文件 |
| siesta | psf 赝势 + PAO 基组参数 + k 点 |
| nwchem | theory/basis block、电荷/多重度 |
| aims | control.in（species defaults、k 网格、xc） |

## 三、批量转换（目录/多输入）

```powershell
# 多输入 → 每个输入一个子目录 + convert_manifest.json（n_ok/n_failed/每条错误）；坏输入不中断
& $PY -m cifkit convert runs\export_demo --to vasp,extxyz --outdir runs\bulk --json
& $PY -m cifkit convert a.cif b.cif --bundle vasp --outdir runs\decks --json
```

- 目录里的 `*.cif` 全部转换（大小写不敏感，自动去重）；
- 单输入时文件直接落在 `--outdir`（与旧行为一致）；多输入时落在 `--outdir/<stem>/`；
- `convert_manifest.json` 记录每个输入的 `ok`、`outdir`、`n_files`、`error`；任一失败 exit 1 但其余照常完成。

## 三-b、独立回读验证

```powershell
& $PY scripts\verify_formats.py                 # 31 格式 + 12 bundle → runs/verify_formats/verify_formats.json
& $PY scripts\verify_formats.py --only vasp,cif,extxyz,png
```

用**与写出器不同的库**读回并比对原子数（ASE 22 种 / pymatgen 3 种；模板 5 种走关键字、png 走魔数）。
实测 31/31 写出、25/25 第三方回读一致。**回读一致 ≠ 目标软件接受**，模板仍需用户补赝势/基组并做收敛。

## 三-c、批量与数据管线

```powershell
# 批量转换：对目录里每个结构逐个 convert（数据集用 cif-data 技能）
Get-ChildItem runs\export_demo\*.cif | ForEach-Object {
  & $PY -m cifkit convert $_.FullName --to vasp,extxyz --outdir runs\bulk --json
}
```

- 要 **ML 特征表 / dataset** → 用 `cif-data` 技能（`cifkit features` / `cifkit dataset`）。
- 要 **下载/补氢/超胞/切面/真空** → 先用 `cif-workbench`，再回来导出。

## 四、已知坑（实测）

- **CIF 的对称性不折叠**：`cif` 格式用 `CifWriter(symprec=None)`，保留全部原子（slab 必需）。
- **PDB/SDF/MOL 不表达周期性**：用于分子/可视化；周期性计算请用 extxyz/vasp/cif。
- **QE/KPOINTS/CP2K 骨架不是收敛输入**：`qe` 的 `ATOMIC_SPECIES` 用占位 `<Element>.UPF` 名；
  CP2K 只有 CELL+COORD+DFT 骨架；跑前补赝势/basis 并做收敛测试。
- **Gaussian/ORCA 模板**：`* xyz 0 1` 默认中性单重态，按体系改电荷/多重度。
- **LAMMPS data 是 atom_style atomic**：没有质量/电荷/键；in.min 里也没有力场。
- **GRO 精度有限**（3 位小数）且不含拓扑。
- **CASTEP/ABINIT/CRYSTAL 等**：只给几何 + 骨架，keywords/赝势另配。
- **不提供任何 license 文件**（POTCAR、UPF、skf、力场、basis）；不谎称"能直接算"。
- 大结构（500+ 原子）写出一般没问题；`png` 已实现（上表"可视化/分析"类，走 `cifkit.render`，回读用魔数校验）；`cube` 需要 3D 数据数组，**当前未实现**（不在 31 种内）。

## 五、验收

```powershell
& $PY -m cifkit convert <file> --to vasp,cif,xyz --outdir runs\check --json    # exit 0，JSON 可解析
& $PY -m cifkit convert <file> --bundle vasp --outdir runs\check_vasp --json   # POSCAR+INCAR+KPOINTS+POTCAR.readme
& $PY -m cifkit formats                                                       # 31 种格式
```

测试：`tests/test_export.py`（20）、`tests/test_export_ext.py`（31 格式 + 12 bundle）。
文档：`docs/EXPORT.md`（能力矩阵/新增格式方法）。
