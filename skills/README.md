# `skills/` — the `cif-*` skill bodies (source of truth)

This directory **is** the source of truth for the eight `cif-*` skills that belong to
this project.  The engine and the documents that tell an agent *how to drive* it
ship, version and get reviewed together — a clone of this repository is complete,
with no second checkout involved.

| Skill | What it is for |
|---|---|
| `cif-workbench` | 总入口：一句话 → 计划 → 一条管线跑通 |
| `cif-fetch` | 数据源选型、下载、拓扑证据分级 |
| `cif-repair` | 补氢 / 无序占位 / 近邻 / 价态检查 |
| `cif-geometry` | 标准化 / 超胞 / (hkl) 切面 / 真空 / 金属簇-SBU |
| `cif-export` | 31 种格式导出与读回验证、12 种计算软件输入包 |
| `cif-data` | `features` 结构特征表、`dataset` 数据集构建 |
| `cif-usecases` | `teach` / `bravais` / `metals` / `fec` / `surface-energy` 进阶工作流 |
| `cif-to-3dprint` | CIF → 可 3D 打印的 STL/OBJ |

Each skill directory holds its `SKILL.md` (the body) and `manifest.json` (id, kind,
intents, keywords, examples, requirements).

## Linting (this is the only place it happens)

`scripts/check_skill.py` validates every folder here and is wired into
`scripts/check_all.py` as the `skills: check_skill cif-*` group, so a skill whose
manifest or body stops validating fails the health check, CI and the release gate.
It is a zero-dependency linter that lives in this repository — deliberately, because
the gate must not depend on another checkout.

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe scripts\check_skill.py                    # all cif-* skills
.venv\Scripts\python.exe scripts\check_skill.py skills\cif-export   # one folder
.venv\Scripts\python.exe scripts\check_skill.py --strict           # warnings fail too
```

## Relationship to any external agent catalog

Some agent setups keep a shared *catalog* repository (e.g. an `agent-library`
checkout with `catalog/<id>/`) and route over it.  If you feed these skills to such
a catalog, the direction is one-way:

* **edit here** — this directory is upstream for the `cif-*` entries;
* copy *out* to the catalog when you want that router to pick the change up;
* nothing in this project reads the catalog: `scripts/check_all.py` and
  `scripts/release_check.py` treat it as an optional extra.  `CIFKIT_AGENTLIB` (a
  path to such a checkout) only adds a few informational rows — the project's
  acceptance never depends on it.

The provenance of these eight skills (they were authored alongside the engine and
kept in a shared catalog during development) and the four defect repairs applied to
their bodies in round 58 are recorded in [CHANGELOG.md](../CHANGELOG.md) and
[docs/REVIEW-ROUND58-FIXES.md](../docs/REVIEW-ROUND58-FIXES.md): `cif-data`'s
nonexistent `features --jsonl` flag, three `0x08` backspace characters that corrupted
`cif-workbench`'s `runs\batch` example, `cif-export`'s 30-vs-31 count and `png`
status, and `cif-usecases` gaining the `surface-energy` section.
