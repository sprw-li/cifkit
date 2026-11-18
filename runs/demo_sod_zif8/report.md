# CIF 处理报告：demo_sod_zif8

- 运行时间：2026-11-05T18:01:35+08:00
- 是否成功：✅
- 原始请求：帮我下载典型的RCSR为sod的mof，需要碳上补充氢，创建一个2x2x1的超胞（Supercell），沿(111)面切出表面，并加上15Å的真空层，导出为计算化学软件使用的格式。

## 1. 结构来源
- 来源库：core-mof
- 记录 id：core-mof:SI/NCR/both/ja204757x_si_002_ASR_pacman.cif
- refcode：ja204757x_si_002_ASR_pacman
- DOI：https://doi.org/10.1021/ja204757x
- 拓扑：sod（证据：verified）
- 组成：Zn12 C96 N48
- URL：https://zenodo.org/records/15055758
- CIF sha256：`c6939cf73df71087d558e3030f9227c535487243fdf019790924e94abef26cd3`

## 2. 执行步骤
### ✅ resolve
core-mof:SI/NCR/both/ja204757x_si_002_ASR_pacman.cif  Zn12 C96 N48  atoms=156  DOI=10.1021/ja204757x

### ✅ verify-topology
expected=sod evidence=verified 与参考 core-mof:SI/CR/ASR/2015[Zn][sod]3[ASR]1.cif 的 underlying net 签名一致：配位数[4-配位×1.00]；配位序列[2-8层: 4, 10, 20, 34, 52, 74, 100, 130]；环分布[4元环/节点=0.125, 6元环/节点=0.111, 8元环/节点=0.500]

### ✅ repair
add_H=120 removed=0 disorder=0 atoms=276

### ✅ standardize
atoms=276 formula=Zn12 H120 C96 N48 kept=input

### ✅ surface
hkl=(1, 1, 1) frame=slab reps=(2, 2, 1) atoms=2208 abc=[48.166, 48.166, 34.283] vacuum=15.0

### ✅ vacuum
target=15.0 Å measured=15.000 Å

### ✅ export
formats=vasp, cif, xyz

### ✅ validate
PASS checks=12

### ✅ render
runs\demo_sod_zif8\preview.png

### ✅ manifest
runs/demo_sod_zif8

## 3. 结构几何（实测）

- 切面：(111)，frame=slab，reps=(2, 2, 1)
- 切面原子数：base=552 → 面内重复后 2208
- slab 厚度（原子垂直跨度）：19.283 Å
- 终止面选择：shift=0.207317, dangling_bonds=20
- 生成时垂直真空：15.0 Å
- 最小周期像距离：15.24 Å
- 最终垂直真空（实测）：15.0 Å
- 最终原子数 / 组成：2208 / Zn96 H960 C768 N384
- 最终晶胞：a,b,c = [48.1661, 48.1661, 34.2826] Å；angles = [90.0, 90.0, 60.0]°

## 4. 校验：通过
- ✅ natoms：2208 atoms
- ✅ composition：Zn96 H960 C768 N384 (2208 atoms; 4 elements)
- ✅ finite_coordinates：all coordinates finite
- ✅ lattice：a,b,c = 48.1661, 48.1661, 34.2826 Å; alpha,beta,gamma = 90.00, 90.00, 60.00 deg; V = 68879.175 Å^3
- ✅ duplicate_atoms：no atom pair closer than 0.4 Å
- ✅ min_distance：shortest interatomic distance 1.100 Å (C-H)
- ✅ vacuum：真空层（垂直）= 15.000 Å；最小周期像距离 = 15.240 Å；要求 ≥ 15.00 Å
- ✅ slab_continuity：largest internal gap along the surface normal is 0.43 Å (vacuum layer 15.00 Å, slab thickness 19.28 Å)
- ⚠️ dangling_bonds：80 dangling bond(s) on 700 surface atoms: C:16, H:16, N:24, Zn:24
- ✅ hydrogen：960 H atoms
- ✅ carbon_coordination：all 504 interior C atoms have >= 3 bonds
- ✅ charge：no oxidation states in the structure (charge not assessed)

```json
{
  "natoms": 2208,
  "formula": "Zn96 H960 C768 N384",
  "reduced_formula": "ZnH10(C2N)4",
  "element_counts": {
    "C": 768,
    "H": 960,
    "N": 384,
    "Zn": 96
  },
  "elements": [
    "C",
    "H",
    "N",
    "Zn"
  ],
  "lattice": {
    "abc": [
      48.1661,
      48.1661,
      34.2826
    ],
    "angles": [
      90.0,
      90.0,
      60.0
    ],
    "volume": 68879.175,
    "volume_per_atom": 31.1953
  },
  "density_g_cm3": 0.5268,
  "duplicate_pairs": 0,
  "min_distance": 1.1,
  "min_distance_pair": [
    "C",
    "H"
  ],
  "min_distance_sites": [
    1351,
    443
  ],
  "min_distance_by_element_pair": {
    "C-C": 1.3489,
    "C-H": 1.1,
    "C-N": 1.3424,
    "C-Zn": 3.0138,
    "H-H": 1.7963,
    "H-N": 2.2044,
    "H-Zn": 2.8672,
    "N-N": 2.2279,
    "N-Zn": 1.9911
  },
  "vacuum_gaps_all_axes": [
    1.3424,
    1.1,
    15.2396
  ],
  "is_slab": true,
  "is_cluster": false,
  "vacuum_measured": 15.0,
  "vacuum_perp": 15.0,
  "vacuum": 15.0,
  "min_image_distance": 15.2396,
  "slab_thickness": 19.283,
  "slab_frac_span": 0.5625,
  "surface_area": 2009.159,
  "surface_atoms": 700,
  "vacuum_target": 15.0,
  "internal_max_gap": 0.433,
  "dangling_bonds": 80,
  "dangling_by_element": {
    "C": 16,
    "H": 16,
    "N": 24,
    "Zn": 24
  },
  "h_count": 960,
  "carbon_atoms": 768,
  "carbon_interior": 504,
  "c_coordination": {
    "3": 360,
    "4": 144
  },
  "c_missing_h": 0,
  "c_missing_h_indices": [],
  "charge_sum": null
}
```

## 5. 产物
- raw.cif: `runs\demo_sod_zif8\raw.cif`
- repaired.cif: `runs\demo_sod_zif8\repaired.cif`
- standardized.cif: `runs\demo_sod_zif8\standardized.cif`
- slab.cif: `runs\demo_sod_zif8\slab.cif`
- final.cif: `runs\demo_sod_zif8\final.cif`
- export.vasp: `runs\demo_sod_zif8\structure.vasp`
- export.cif: `runs\demo_sod_zif8\structure.cif`
- export.xyz: `runs\demo_sod_zif8\structure.xyz`
- preview.png: `runs\demo_sod_zif8\preview.png`
- report: `runs\demo_sod_zif8\report.md`
- manifest: `runs\demo_sod_zif8\manifest.json`
- library: `<repo>\library\demo_sod_zif8`
