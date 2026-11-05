# CIF 处理工作台（cifkit）— Project5

把晶体 CIF 从“数据库下载下来的原始文件”变成“能直接喂给 VASP/QE/CP2K/LAMMPS 的结构”：

**选型下载 → 修复（补氢 / 无序占位 / 近邻）→ 几何（标准胞 / 超胞 / (hkl) 切面 / 真空 / 金属簇）→ 导出 → 校验 → 入库**

技能组位于 `D:\agent-library\catalog\cif-*`，本仓库是可复用的引擎与验证现场。

## 30 秒读懂

```powershell
# 0) 环境（已建好，含 pymatgen/ase/openbabel/rdkit）
.\.venv\Scripts\python.exe -m cifkit selftest

# 1) 一句话 → 解析计划（不执行）
.\.venv\Scripts\python.exe -m cifkit route "帮我下载典型的RCSR为sod的mof，需要碳上补充氢，创建一个2x2x1的超胞，沿(111)面切出表面，并加上15Å的真空层，导出为计算化学软件使用的格式。"

# 2) 一条管线跑通
.\.venv\Scripts\python.exe -m cifkit pipeline "帮我下载典型的RCSR为sod的mof，需要碳上补充氢，创建一个2x2x1的超胞（Supercell），沿(111)面切出表面，并加上15Å的真空层，导出为计算化学软件使用的格式。" --outdir runs/demo_sod_zif8 --format vasp,cif,xyz --ingest
```

产物在 `runs/demo_sod_zif8/`：`raw.cif`、`repaired.cif`、`supercell.cif`、`slab.cif`、`structure.vasp`、`preview.png`、`report.md`、`manifest.json`。

## 文档

- [docs/DESIGN.md](docs/DESIGN.md) — 架构、冻结接口、数据事实
- [docs/PIPELINE.md](docs/PIPELINE.md) — 管线各步与验收
- [docs/SOURCES.md](docs/SOURCES.md) — 数据源、拓扑判定、缓存
- [docs/REPAIR.md](docs/REPAIR.md) — 补氢算法与无序处理
- [docs/GEOM.md](docs/GEOM.md) — 超胞 / 切面 / 真空 / 簇
- [docs/EXPORT.md](docs/EXPORT.md) — 导出格式与校验清单

## 状态

开发中。验收标准见 `docs/DESIGN.md` §1。
