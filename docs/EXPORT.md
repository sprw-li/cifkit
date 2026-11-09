# 导出层（cifkit.export）

Owner: `geom-export`。代码：`cifkit/export/writers.py`。测试：`tests/test_export.py`。

## 1. 公开接口

```python
write_structure(structure, path, fmt, *, title=None, pseudopotentials=None) -> str
supported_formats() -> dict[str, str]
normalize_format(fmt_or_alias) -> str          # 辅助：格式名/别名归一化
```

- `fmt` 大小写、空格不敏感；未知格式抛 `ValueError` 并**列出全部可用格式与别名**。
- `title` 写入 VASP 第一行注释 / XYZ 注释行 / CP2K 首行注释。
- `pseudopotentials` 仅对 `qe` 生效（可选）：`{元素: UPF 文件名}`。
- 每个文件写完后**读回校验**；VASP/CIF/XYZ 是严格校验（必须能解析且原子数一致）。

## 2. 支持格式

| fmt | 别名 | 写出实现 | 读回校验 | 说明 |
|---|---|---|---|---|
| `vasp` | `poscar`, `contcar`, `vasp5` | pymatgen `Poscar` | `Poscar.from_file` 原子数 | VASP5，第 6 行元素名、第 7 行计数 |
| `cif` | `cif2`, `mcif` | pymatgen `CifWriter(symprec=None)` | `Structure.from_file` 原子数 | **不做对称性折叠**（slab 必需） |
| `xyz` | `xyz2` | 自写（逐行 `元素 x y z`） | `ase.io.read` 原子数 | 非周期格式；晶胞参数写进第 2 行注释 |
| `lammps` | `lammps-data`, `data` | `ase.io` `lammps-data` | `ase.io.read` 原子数 | atom style `atomic` |
| `qe` | `espresso`, `espresso-in`, `pwscf` | `ase.io` `espresso-in` | `ase.io.read` + 关键字检查 | 见 §3 赝势 |
| `cp2k` | `cp2k-in`, `cp2k_input` | 自写模板 | 关键字 + `&COORD` 行数 | 见 §4 骨架说明 |
| `xsf` | `xcrysden` | `ase.io` `xsf` | `ase.io.read` 原子数 | 周期晶体（PRIMVEC/PRIMCOORD） |

（早期版本只支持 7 种格式；round 3 已扩展到 31 种格式 + 12 种输入包，见 §6。）

## 3. Quantum ESPRESSO 赝势（本次修复的缺陷）

ASE 的 `espresso-in` writer 在缺少 `pseudopotentials` 映射时会抛裸 `KeyError: 'C'`
（Lead 联调实测）。现在：

- 默认自动为结构中**每个元素**生成占位名称 `<Element>.UPF`（例：`Zn.UPF`、`H.UPF`），
  保证 `pw.x` 输入文件语法完整、能被 ASE 读回；真正跑 QE 时把占位名换成实际 UPF 文件即可；
- 可传自定义映射：

  ```python
  write_structure(s, "structure.qe", "qe",
                  pseudopotentials={"Zn": "Zn.pbe-vdz.UPF",
                                    "C":  "C.pbe-n-kjpaw_psl.1.0.0.UPF"})
  ```

  未在映射里的元素继续用占位名；
- 若结构里出现**不是真实元素**的符号（如 `X`），抛
  `ValueError("QE export: cannot generate pseudopotential names for element(s) [...] ...")`，
  不再泄漏裸 `KeyError`；
- 写完后校验文件含 `ATOMIC_SPECIES` / `CELL_PARAMETERS` / `ATOMIC_POSITIONS` 三个关键字，且能读回同样原子数。

实测（138 原子 `zif8_cr_sod.cif`）：`structure.qe` 6648 B，三个关键字齐全，ASE 读回 138 原子。

## 4. CP2K 骨架

`cp2k` 写的是**可直接编辑的最小骨架**：`&FORCE_EVAL / &SUBSYS / &CELL(ABC, ALPHA_BETA_GAMMA) /
&COORD / &DFT / &MGRID(CUTOFF, NGRIDS)`。真实计算还需用户补 `&KIND`（BASIS_SET / POTENTIAL）
或外部 basis/potential 文件——文件首行注释里也写了这一点，不会伪装成"可直接运行"。

## 5. 实测文件大小（`zif8_cr_sod.cif`，138 原子）

| fmt | 字节数 |
|---|---|
| vasp | 9771–9790 |
| cif | 8139 |
| xyz | 8505–8524 |
| lammps | 11856 |
| qe | 6648 |
| cp2k | 9754–9773 |
| xsf | 9586 |

2208 原子 (111) slab 的 POSCAR ≈ 2 MB，pymatgen 可正常读回、原子数一致（`tests/test_geom.py` 有断言）。

## 6. CLI 用法

```powershell
$env:PYTHONIOENCODING='utf-8'
# 单格式
.venv\Scripts\python.exe -m cifkit export tests/data/zif8_cr_sod.cif --format vasp -o runs/_export_check

# 批量（一次全成功；CLI 把每个格式写成 structure.<fmt>）
.venv\Scripts\python.exe -m cifkit export tests/data/zif8_cr_sod.cif `
  --format vasp,cif,xyz,qe,lammps,cp2k,xsf -o runs/_export_all

# 列出格式
.venv\Scripts\python.exe -m cifkit formats
```

实测验收命令输出（`--format vasp,cif,xyz -o runs/_export_check`）：

```
vasp: runs\_export_check\structure.vasp
cif:  runs\_export_check\structure.cif
xyz:  runs\_export_check\structure.xyz
```

批量 7 格式（`runs/_export_all`，同一命令一次成功；产物均非空并读回校验通过）：

| 文件 | 字节数 |
|---|---|
| `structure.vasp` | 9790 |
| `structure.cif` | 8139 |
| `structure.xyz` | 8524 |
| `structure.qe` | 6648 |
| `structure.lammps` | 11856 |
| `structure.cp2k` | 9773 |
| `structure.xsf` | 9586 |

`tests/test_export.py` 覆盖：7 格式逐个写出 + 单次批量全成功（`test_batch_export_all_formats_at_once`）、
QE 关键字与自定义赝势、别名、读回校验、非法格式报错。

## 7. 限制

- `xyz` 不保存周期性（晶胞只写在注释行里）；需要周期信息用 `cif`/`vasp`/`xsf`/`qe`。
- `lammps` 用 ASE 默认 `atomic` atom style，不含力场/电荷；要别的 style 请自行后处理。
- `cp2k` 是输入骨架，不含基组/赝势；`qe` 的 UPF 名是占位，需替换成实际文件。
- 写出的 VASP 文件仅 POSCAR 内容（不含 POTCAR/KPOINTS/INCAR）。
- 大结构（> 20000 原子）导出前建议先在几何层裁剪；写出本身不做规模限制，但读回校验会花时间。

## 6. CIF → anything 能力矩阵（round 3）

`cifkit convert FILE --to <fmt1,fmt2> --bundle <code>`：输入可以是 cif/poscar/xyz/json/xsf 等
pymatgen/ASE 能读的任意结构文件；每个格式写出后都做回读校验。

| 类别 | 格式（31） | 写出方式 | 回读校验 |
|---|---|---|---|
| 结构/通用 | `cif`、`vasp`、`xyz`、`extxyz`、`json` | pymatgen / 自写 / ASE | 是（原子数一致） |
| 可视化/分析 | `xsf`、`cfg`、`pdb`、`sdf`、`mol`、`struct`、`res`、`png`（预览图） | ASE / cifkit.render | 是（PDB/SDF/MOL 不表达周期性；png 只验证 PNG 魔数） |
| 分子动力学 | `lammps`、`gromacs`、`gen` | ASE | 是（骨架，无力场/质量） |
| 电子结构（输入） | `qe`、`cp2k`、`gaussian`、`orca`、`abacus`、`dftb`、`siesta`、`nwchem`、`aims`、`castep`、`abinit`、`crystal`、`onetep`、`dmol`、`turbomole` | ASE writer / 自写模板 | 模板：检查关键段落；**不是收敛输入** |
| 视觉预览 | `png`（结构预览图，非计算输入） | `cifkit.render` | 魔数检查 |
| （未实现） | `cube` | 需要 3D 数据数组/额外依赖，**不在当前 31 种内** | — |

- 模板类格式在 `FORMAT_INFO` 描述里明确写"needs ... / template"；`write_bundle` 返回
  `template=True` + `missing` 列表（POTCAR/UPF/basis/skf/力场等）。
- 未支持格式：`normalize_format` 抛 `ValueError` 并列出全部可用格式与别名。

### 输入包（12）：`write_bundle(structure, code, outdir, *, title=None)`

| code | 写出文件 | 用户必须补 |
|---|---|---|
| vasp | POSCAR + INCAR + INCAR.static + KPOINTS + POTCAR.readme | POTCAR |
| qe | pw.in + README.KPOINTS + PSEUDO.readme | UPF 赝势、收敛参数 |
| cp2k | cp2k.inp + README | BASIS_SET/POTENTIAL |
| lammps | data.lammps + in.min + README | 力场（pair_style/coeff） |
| gromacs | conf.gro + md.mdp + TOP.readme | 力场 .top/.itp |
| gaussian | mol.gjf + README | 方法/基组、电荷/多重度 |
| orca | orca.inp + coords.xyz + README | 方法/基组、电荷/多重度 |
| abacus | STRU + INPUT.readme + README | upf 赝势、orb 轨道、INPUT |
| dftb | geo.gen + dftb_in.hsd + SLKO.readme | slakos/ 下 .skf 文件 |
| siesta | structure.fdf + README | psf 赝势、PAO 基组、k 点 |
| nwchem | mol.nw + README | theory/basis、电荷/多重度 |
| aims | geometry.in + control.readme + README | control.in（species defaults） |

### 独立回读验证（`scripts/verify_formats.py`）

```powershell
& $PY scripts\verify_formats.py                                  # 31 格式 + 12 bundle，写 runs/verify_formats/verify_formats.json
& $PY scripts\verify_formats.py --only vasp,cif,extxyz,png        # 快速子集
```

用**与写出器不同的库**读回并比对原子数（pymatgen / ASE）；模板类与 png 走关键字/魔数检查，
结果单独标注，不冒充第三方回读。最近一次实测（ZIF-8，138 原子）：

| 回读方式 | 格式数 | 说明 |
|---|---|---|
| ASE 第三方回读 | 22 | abinit/aims/cfg/crystal/dmol/extxyz/gaussian/gen/gromacs/lammps/mol/nwchem/onetep/pdb/qe/res/sdf/struct/turbomole/xsf/xyz/castep |
| pymatgen 第三方回读 | 3 | cif / json / vasp |
| 结构关键字检查 | 5 | cp2k / siesta / abacus / orca / dftb（输入模板，无可回读解析器） |
| 魔数检查 | 1 | png |
| **合计** | **31/31 写出成功，25/25 第三方回读原子数一致** | bundle 12/12 文件+README 齐全 |

结果 JSON：`runs/verify_formats/verify_formats.json`（含每个格式的字节数、耗时、回读库、错误）。
`tests/test_verify_formats.py` 断言"每个受支持格式都有验证路径"且第三方读者 ≥20，防止以后新增格式时漏掉验证。

**注意**：回读一致只证明"文件能被另一个库解析出同样多的原子"，不证明目标计算软件会接受它；
模板类仍未在真实软件中运行（见 `docs/LIMITATIONS.md` E1/E3/H3）。

### 如何新增格式

1. 在 `cifkit/export/writers.py` 的 `FORMAT_INFO` 加名称与说明；别名加 `_ALIASES`。
2. 写出：优先 `_ASE_WRITERS[fmt] = "<ase-format>"`（大多数格式 ASE 原生支持）；
   否则写 `_write_<fmt>` 模板并注册进 `_WRITERS`。
3. 回读：在 `_readback_natoms` 加回读（ASE/pymatgen）；模板类在 `_verify` 里检查关键段落。
4. 测试：`tests/test_export_ext.py` 会自动遍历 `supported_formats()`，无需逐格式加用例（模板类要可回读或关键字齐全）。
5. 文档：更新本文件的能力矩阵。
