# `skills/` — the `cif-*` skill bodies shipped with cifkit

This directory is a **mirror** of the eight `cif-*` skills that belong to this
project.  It exists so that a clone of the engine also carries the documents that
tell an agent *how to drive* the engine — reviewed and versioned together — instead
of relying on a checkout of a second repository to read them.

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

Each skill directory holds its `SKILL.md` (the body) and `manifest.json` (id,
intents, keywords, examples, requirements).

## It is a mirror, not the source of truth

The **live** skill catalog that a router actually loads is the separate
`agent-library` repository (`catalog/cif-*`).  This copy is a snapshot of that
catalog's `cif-*` entries:

* edit skills in the catalog repository first, then refresh this mirror;
* do not edit only here — the router never reads this directory;
* `scripts/check_skill.py` (a gate inside `check_all.py`) lints the live catalog,
  not this mirror, and needs `CIFKIT_AGENTLIB` (default `D:\agent-library`) to find
  it.

Refresh and verify (byte-identical copies):

```powershell
$env:PYTHONIOENCODING='utf-8'
$src = if ($env:CIFKIT_AGENTLIB) { $env:CIFKIT_AGENTLIB } else { 'D:\agent-library' }
foreach ($s in Get-ChildItem "$src\catalog" -Directory -Filter 'cif-*') {
    $t = Join-Path 'skills' $s.Name
    New-Item -ItemType Directory -Force -Path $t | Out-Null
    Copy-Item "$($s.FullName)\SKILL.md", "$($s.FullName)\manifest.json" $t -Force
}

# verify: every mirrored file must match its source once line endings are
# normalised to LF - this repository is `* text=auto eol=lf` (.gitattributes),
# so the committed copy is LF even when the catalog's working tree is CRLF.
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe -c @"
import hashlib, pathlib
src_root = pathlib.Path(r'D:\agent-library\catalog')   # or $env:CIFKIT_AGENTLIB + '\catalog'
def h(p): return hashlib.sha256(pathlib.Path(p).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
bad = [f'{s.name}/{f}' for s in sorted(src_root.glob('cif-*')) for f in ('SKILL.md', 'manifest.json')
       if (s / f).is_file() and h(s / f) != h(pathlib.Path('skills') / s.name / f)]
print('drift:', bad or 'none')
raise SystemExit(1 if bad else 0)
"@
```

The committed blobs were verified this way (16/16 files, 0 mismatches).

## What this snapshot carries from round 58

The mirror was taken after the delivery review fixed four defects in the skill bodies
(they were only ever visible in the private catalog working tree):

* `cif-data` — removed the documented `cifkit features --jsonl` flag, which does
  not exist (the CLI answers `unrecognized arguments`, exit 2); JSONL now points at
  `cifkit dataset`;
* `cif-workbench` — repaired three `0x08` backspace characters that had corrupted
  the `runs\batch` example path;
* `cif-export` — the format count is 31 everywhere (one place said 30) and `png` is
  no longer listed as unimplemented (only `cube` is);
* `cif-usecases` — gained a `cifkit surface-energy` section (the subcommand had been
  documented nowhere in the skill group).

The provenance of the mirror and the four repairs are also recorded in
[CHANGELOG.md](../CHANGELOG.md) and
[docs/REVIEW-ROUND58-FIXES.md](../docs/REVIEW-ROUND58-FIXES.md).
