# 数据集覆盖矩阵（本地 CoRE MOF 2024 + 捆绑参考网络）

> 目标：让"我们到底有什么"可查询、可复现，而不是靠印象。生成方式：
> `.venv\Scripts\python.exe scripts\coverage_matrix.py --markdown runs\coverage_matrix.md`；
> 证据：`runs/coverage_matrix.json`（含每个 net 的示例条目与 `verify` 结果）。
> 更新：2026-11-09。

## 1. 拓扑覆盖（CoRE MOF 2024，8300 条）

| topology | 条目数（allnodes） | 本地有参考网络？ | 本机示例 `verify` |
|---|---|---|---|
| `sod` | 7 | ✅ | **verified**（`SI/CR/ASR/2011[Zn][sod]3[ASR]3.cif`） |
| `pcu` | 79 | ✅ | **verified** |
| `dia` | 33 | ✅ | **verified** |
| `fcu` | 10 | ✅ | **verified** |
| `tbo` | 16 | ✅ | **verified** |
| `bcu` | 13 | ✅ | **verified** |
| `mtn` | **0** | ❌ | —（MIL-101/MIL-100 属于 `mtn`） |
| `csq` | 5 | ❌ | 只能报"未验证" |
| `hcb` | 43 | ❌ | 只能报"未验证" |
| `sql` | 176 | ❌ | 只能报"未验证" |
| `kgd` | 32 | ❌ | 只能报"未验证" |
| `crb` | 16 | ❌ | 只能报"未验证" |
| `srs` | 15 | ❌ | 只能报"未验证" |
| `tfz-d` | 15 | ❌ | 只能报"未验证" |
| `rna` | 17 | ❌ | 只能报"未验证" |
| `nbo` | 5 | ❌ | 只能报"未验证" |
| `pts` | 6 | ❌ | 只能报"未验证" |
| `rht` / `bct` | 0 | ❌ | — |

**关键结论**：
1. **捆绑的 6 个参考网络全部在真实数据集上核对通过**（不是自测自）：sod/pcu/dia/fcu/tbo/bcu 各取一条真实 CoRE 条目跑 `cifkit.topology.verify` → `ok`；
2. **能离线验证的只有这 6 个 net**；其余拓扑（含 176 条 `sql`、43 条 `hcb`）**在数据里存在，但本项目没有参考网络**，`verify` 只能返回不确定——这是能力边界，不是数据缺失；
3. **`mtn` 条目数 = 0**：从"拓扑"这条独立路径再次证实 **MIL-101/MIL-100 不在本数据集**（与局限 C2 的结论互证）。

## 2. 常见 MOF 家族 → 网络 对应关系

| MOF 家族 | 典型网络 | 本数据集 |
|---|---|---|
| ZIF-8 / ZIF-67 | `sod` | ✅ 有（7 条，示例 verified） |
| MOF-5 / IRMOF-1 | `pcu` | ✅ 有（79 条，示例 verified） |
| HKUST-1 (Cu-BTC) | `tbo` | ✅ 有（16 条，示例 verified） |
| UiO-66 / UiO-67 / Zr-MOFs | `fcu` | ✅ 有（10 条，示例 verified） |
| MOF-74 / CPO-27（1D rod） | `hcb`/未命名 | 🟡 数据有（43 条 hcb），本地无参考网络 |
| MIL-101 / MIL-100 | `mtn` | ❌ **0 条** |
| PCN-222 / NU-1000 | `csq` | 🟡 有 5 条 `csq`，本地无参考网络 |
| NOTT-100 家族（NbO 型） | `nbo` | 🟡 有 5 条，本地无参考网络 |

**注意**：本数据集的 `name` 字段基本为空（8300 条里只有 1372 条有值，且多为期刊式 refcode，
如 `ja0c07257_si_005_ASR_pacman`），所以**不能靠名字找 MOF**——可靠的两个抓手是
**拓扑 token**（文件名/键里的 `[Zn][sod]3`）与**结构本身的 `verify`**。

## 3. 如何扩大覆盖（可执行）

| 想要 | 做法 |
|---|---|
| 验证新拓扑（如 `csq`/`hcb`/`mtn`） | 往 `cifkit/data/nets/` 放 `<net>.json` + `<net>-reference.cif`（参考结构的 `cif_sha256` 写进 json），然后 `cifkit topology --net <net>` 即可用；`scripts/coverage_matrix.py` 会自动把它纳入矩阵 |
| 找到某个具体 MOF | `scripts/audit_dataset_coverage.py --name <别名>`（name/refcode/DOI 子串）或 `--formula "Zr>=6,O>=30"`（元素指纹）或 `--largest <元素>` |
| 补 MIL-101 这类缺口 | 需要外部语料（如文献 CIF / 其它 CoRE 版本）；本仓不伪造结构 |
| 确认某条记录真的可用 | `cifkit validate` + `cifkit topology --net <net>`；两者都过才算"已验证" |

## 4. 复现与验收

```
.venv\Scripts\python.exe scripts\coverage_matrix.py --markdown runs\coverage_matrix.md
.venv\Scripts\python.exe scripts\audit_dataset_coverage.py --name MIL-101 --formula "Cr>=3,F>=1,C>=20"
.venv\Scripts\python.exe -m pytest tests\test_coverage_matrix.py -q      # 捆绑参考自洽性
```

测试保证：① 每个捆绑 net 的 `<net>.json` 与 `<net>-reference.cif` 存在且 `cif_sha256` 有值；
② **每个捆绑参考对自己的结构 `verify` 必须 ok**；③ 计数函数为纯函数（可单测）。
