---
name: cif-to-3dprint
description: >-
  把晶体 CIF 结构转成可 3D 打印的 STL/OBJ：球棍模型、SBU 提取、芳环薄板、元素材质
---

# CIF → 3D 打印

把晶体结构的 CIF 变成切片软件能直接用的 STL，或带材质、能逐零件编辑的 OBJ。

完整手册（209 行、含六个 MOF 结构的实测数据与全部参数说明）在 `references/cif2stl-manual.md`，正文只放跑得起来的最短路径。

## 依赖

只要 `numpy` + `trimesh`。换机器先：

```bat
uv pip install numpy trimesh
```

## 快速开始

```bat
python scripts\cif2stl.py 结构.cif -o 输出名 --supercell 3 3 3
```

同时产出三个文件，用途不同：

| 文件 | 内容 | 用途 |
|---|---|---|
| `<名>.stl` | 所有球和键合并成一个网格，无颜色 | 直接进切片软件打印 |
| `<名>.obj` | 每个球、每根键各一条 `o` 记录，带名字和 `usemtl` | 进 Blender 单独选中/删除/剪裁 |
| `<名>.mtl` | 元素颜色 + PBR 金属度/粗糙度 | 必须和同名 OBJ 放同一目录 |

## 最常用的几组参数

| 参数 | 作用 |
|---|---|
| `--supercell NX NY NZ` | 沿三个晶轴复制的胞数 |
| `--exclude H,Zn` | 丢弃指定元素（逗号分隔，不分大小写） |
| `--clip X0 X1 Y0 Y1 Z0 Z1` | 只保留分数坐标范围内原子；1/8 晶胞用 `0 0.5 0 0.5 0 0.5` |
| `--sbu` | 只提取二级构筑单元（金属簇 + 整条配体），走化学判据不是几何切割 |
| `--groups` | OBJ 按元素合并球，每根棍仍独立 |
| `--no-bonds` | 只画球（空间填充风格，模型更结实） |
| `--metal-diameter` / `--atom-diameter` / `--h-diameter` | 绝对毫米，跨结构固定才有一致观感 |
| `--mm-per-angstrom` | 整体缩放，1 Å 打多少 mm |
| `--stats` | 打印三角面数/顶点数 |

零件命名自带语义：球 `Na13`（元素+序号）、键 `bond_Cl10_Na13`（名字里就写着连谁）、双键拆两根后缀 `_d1`/`_d2`、芳环薄板 `ring0`。

## 三个必踩的坑

1. **路径别带中文。** Blender 的 STL 导入遇到中文路径报 `File format is not supported`。把文件挪到纯英文路径，或直接导 `.obj`。
2. **Blender 单位差 1000 倍。** STL/OBJ 不带单位，Blender 默认 1 单位 = 1 m。改 `Scene Properties → Unit System → Metric`，`Scale Length = 0.001`。
3. **本机是 780M 核显**，实时视口用 Eevee；Cycles GPU 渲染会非常慢，要么降采样，要么用 CPU。

## Blender 逐零件编辑

`bpy.ops.wm.obj_import(filepath=..., use_split_objects=True)` —— 脚本里的选项名是 `use_split_objects`，不是界面上的 "Split By Object"。导入后球/棍/环片各自独立，可按名字批量选。

无头复验脚本：`scripts/verify_obj_in_blender.py`（导入 OBJ，统计每个物体的面数与连通块数）。

## 输出物是重叠壳

球与键互相穿插，切片软件会当并集处理，正常打印。悬空多，FDM 记得开支撑；树脂机要加拉面或抽壳孔。

想更结实：`--no-bonds --atom-diameter 8 --metal-diameter 10` 做空间填充模型。
