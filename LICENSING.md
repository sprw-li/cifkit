# Licensing & commercial reuse

> 目标：让 cifkit 能被**商用平台**当作可复用接口嵌入（宽松许可、无强制授权、可替换数据源）。
> 本文是工程判断与事实清单，**不是法律意见**；商用前请让法务复核。

## 1. 一句话结论

- **本仓库代码：MIT**（见 [LICENSE](LICENSE)）——可商用、可闭源集成、可再分发，只需保留版权声明。
- **运行依赖：核心路径 GPL-free**（实测：屏蔽 Open Babel 后 31 种格式 + 12 个输入包全通过）。
- **数据集不是我们的**：CoRE MOF(CC-BY-4.0，需署名) / COD(公有领域) / MP(需 key 且受其条款) /
  AFLOW(受其条款) / QMOF(派生自 CoRE/CSD，谨慎)；**再分发数据前必须逐源核对**。
- **不提供** POTCAR/UPF/skf/力场/basis 等授权受限文件，也不提供任何计算软件的授权。

## 2. 依赖许可（`scripts/license_audit.py`，机器可复核）

最近一次审计（10 个运行时依赖）：

| 类别 | 数量 | 包 |
|---|---|---|
| 宽松 permissive | 8 | pymatgen(MIT)、spglib(BSD-3)、numpy(BSD-3+others permissive)、scipy(BSD-3)、matplotlib(PSF/BSD-compatible)、networkx(BSD-3)、rdkit(BSD-3)、Pillow(MIT-CMU) |
| 弱 copyleft | 1 | **ASE = LGPL-2.1-or-later** |
| 强 copyleft | 1 | **openbabel-wheel = GPL-2.0（Open Babel）** |

复现：`.venv\Scripts\python.exe scripts\license_audit.py [--all] [--strict]`（`--strict` 在运行时依赖含强 copyleft 时返回 1）。

### 关键事实

- **Open Babel（GPL-2.0）其实没有被任何代码路径 import**：仓库里只有许可证审计脚本和
  provenance 的可选包清单提到它。实测 `scripts/verify_formats_no_gpl.py`（用 `sys.meta_path`
  屏蔽 `openbabel`/`pybel`）仍然 **31/31 格式写出 + 25/25 第三方回读 + 12 bundle 全通过**。
  → 商用集成可以**不安装 openbabel-wheel**；`cifkit` 的核心 API 不依赖它。
  （若你另外用 ASE 的某些可选格式，ASE 可能自行调用 Open Babel——那是你的依赖选择。）
- **ASE 是 LGPL-2.1+**：未修改地以库形式导入（动态使用）通常可与专有代码共存，但
  **修改 ASE 源码**或**静态嵌入**会触发 LGPL 义务。本仓库不修改 ASE；若你的平台要裁剪/改写 ASE，请复核。
- 项目**没有**依赖任何 AGPL/GPL 组件（在 openbabel 被移除/不安装的前提下）。

## 3. 数据许可（逐源，商用关键）

| 数据源 | 许可/条款 | 商用 | 再分发 | 需要注意 |
|---|---|---|---|---|
| `core-mof`（CoRE MOF 2024） | **CC-BY-4.0**（Zenodo 15055758） | ✅ | ✅（需署名） | 必须保留 DOI/署名；CIF 来自 CSD 派生，CSD 原库另有条款 |
| `cod`（Crystallography Open Database） | **公有领域** | ✅ | ✅ | 无署名义务（仍建议引用） |
| `materials-project` | MP 使用条款 + 需 `MP_API_KEY` | ⚠️ 需自行同意条款 | ⚠️ 受条款限制 | 不要把 MP 数据再分发当作自有数据；key 由你的平台保管 |
| `aflow` | AFLOW 使用条款（免 key） | ⚠️ 需复核条款 | ⚠️ 需复核 | 只做引用/派生用途 |
| `qmof` | 派生自 CoRE/CSD 的 DFT 标注集 | ⚠️ 需复核 | ⚠️ 谨慎 | 本环境未打通官方下载，仅本地镜像 |
| `local`（用户自己的 CIF） | 用户自负 | — | — | 平台需自行处理用户上传内容的权属 |
| 生成的输入文件（POTCAR/UPF/basis 除外） | MIT 同代码 | ✅ | ✅ | 你写出的几何/输入模板可用 |

**不提供**：POTCAR（VASP 授权）、UPF 赝势、Slater-Koster 文件、力场、基组——这些由用户/平台自备并自负许可。

## 4. 商用集成清单（照做即可）

1. 保留本仓库 `LICENSE` 与 `THIRD-PARTY-NOTICES.md`；
2. 依赖里**不要**引入 openbabel-wheel（核心不需要）；ASE 不修改；
3. 数据落库时**逐条记录来源与许可**——`manifest.json` 已记录 `record_id/doi/sha256/license`，
   平台侧应把 `license` 字段透传到自己的元数据；
4. CoRE 派生数据对外展示时给出署名（DOI + "CoRE MOF 2024"）；
5. MP/AFLOW/QMOF 数据按各自条款使用，不要把 key 写进产物（cifkit 从不写入 key）；
6. 输入包是**模板**，不含授权文件，不承诺可运行——平台应引导用户补齐并做收敛测试。

## 5. 无授权/权限松（"权限松"落实到代码）

- 核心 API **不需要任何 API key**：`convert` / `features` / `dataset` / 本地 `fetch` 全部离线可用；
- 需要 key 的只有 `materials-project`，且通过环境变量注入、可替换（见 `docs/API.md` 的 `sources` 配置）；
- 无网络调用也能跑：`cifkit selftest`、`convert`、`features`、`dataset`、`teach/bravais/metals/fec` 的离线路径；
- 不收集遥测、不外发数据（除用户显式要求抓取的数据库请求）。

## 6. 已知不确定项（诚实边界）

- 代码是"作者的 MIT 声明"，**没有做过逐文件版权审计**（历史提交的第三方片段未逐一核验）；
- `pymatgen` 的某些数据文件、`spglib` 的对称性表等**未逐字节核验**其内嵌许可；
- 数据源条款会变化，本文记录的是 2026-11 的观察，**商用前请重新核对官方页面**；
- 本环境无法访问 figshare（QMOF）与部分官方条款页面，相关条目按"需复核"处理；
- 不构成法律意见。
