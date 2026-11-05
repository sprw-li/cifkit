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

不支持：gaussian/orca/abacus（需要各自专门的输入语义，不在本任务范围）。

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
