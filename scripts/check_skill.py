"""Zero-dependency linter for the ``cif-*`` skill folders shipped in ``skills/``.

Why this lives here
-------------------
The skill bodies used to be validated by a linter that belonged to a *different*
repository, so ``check_all`` (and therefore CI and the release gate) silently
depended on an external checkout: a clone of this engine could not lint its own
skills, and a change to that other repository could turn our gate red.  The
rules are small and self-contained, so they live here now and the catalog mirror
under ``skills/`` is linted by this file only.

What is checked (per ``skills/<id>/`` folder):

* ``manifest.json`` exists, parses, and has the required keys;
* ``kind`` is ``skill`` (the only kind shipped here);
* ``id`` equals the folder name, and the folder name is kebab-case;
* ``when`` / ``whenNot`` are non-empty arrays;
* a ``SKILL.md`` body exists, its front-matter ``name`` matches the folder and
  its ``description`` is non-empty;
* ``examples`` and ``intents`` are recommended, not required (warnings).

    .venv\\Scripts\\python.exe scripts/check_skill.py [skills/cif-export ...]
    .venv\\Scripts\\python.exe scripts/check_skill.py --all [--strict]

Exit 0 when there are no errors; ``--strict`` also fails on warnings (exit 2).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"

KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
REQUIRED = ("schemaVersion", "id", "kind", "mode", "when", "whenNot", "requires", "merge")
KINDS = {"skill"}


def frontmatter(path: Path) -> dict[str, str]:
    """Parse the ``---`` front-matter block of a SKILL.md (no YAML dependency)."""
    text = path.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    data: dict[str, str] = {}
    for line in text[3:end].splitlines():
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if match:
            data[match.group(1)] = match.group(2).strip().strip("\"'")
    return data


def check_one(folder: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    label = folder.name

    manifest_path = folder / "manifest.json"
    if not manifest_path.is_file():
        return [f"{label}: 缺 manifest.json"], warnings
    try:
        item = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{label}: manifest.json 无效（{exc}）"], warnings
    if not isinstance(item, dict):
        return [f"{label}: manifest.json 顶层必须是对象"], warnings

    if item.get("kind") not in KINDS:
        errors.append(f"{label}: kind 必须是 {'/'.join(sorted(KINDS))}，得到 {item.get('kind')!r}")
        return errors, warnings
    for key in REQUIRED:
        if key not in item:
            errors.append(f"{label}: 缺字段 {key}")
    if item.get("id") != label:
        errors.append(f"{label}: id ({item.get('id')!r}) 与目录名不一致")
    if not KEBAB.fullmatch(label):
        errors.append(f"{label}: 目录名不是 kebab-case")
    for key in ("when", "whenNot"):
        value = item.get(key)
        if not isinstance(value, list) or not value:
            errors.append(f"{label}: {key} 必须是非空数组")
    if not item.get("examples"):
        warnings.append(f"{label}: 缺 examples（真实用户话术）")
    if not item.get("intents"):
        warnings.append(f"{label}: 没有 intents（只能靠兜底匹配）")

    body = folder / "SKILL.md"
    if not body.is_file():
        errors.append(f"{label}: 缺正文 SKILL.md")
    else:
        meta = frontmatter(body)
        if not meta:
            errors.append(f"{label}: SKILL.md 缺 --- front-matter")
        else:
            if meta.get("name") != label:
                warnings.append(f"{label}: SKILL frontmatter name ({meta.get('name')!r}) 与目录名不一致")
            if not meta.get("description"):
                warnings.append(f"{label}: SKILL frontmatter 缺 description")
        if "\x08" in body.read_text(encoding="utf-8", errors="replace"):
            errors.append(f"{label}: SKILL.md 含 0x08 退格控制字符（会损坏示例路径）")

    scripts = folder / "scripts"
    if scripts.is_dir() and not any(scripts.iterdir()):
        warnings.append(f"{label}: scripts/ 为空")
    return errors, warnings


def discover() -> list[Path]:
    return sorted(d for d in SKILLS.glob("*") if d.is_dir() and d.name.startswith("cif-"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查 skills/ 下的 cif-* 技能是否符合规范")
    parser.add_argument("paths", nargs="*", help="单个或多个技能目录（默认 skills/cif-*）")
    parser.add_argument("--all", action="store_true", help="检查 skills/ 下全部 cif-*（默认行为）")
    parser.add_argument("--strict", action="store_true", help="有 warning 也返回非零（2）")
    args = parser.parse_args(argv)

    if args.paths:
        folders = [Path(p).expanduser() for p in args.paths]
        missing = [str(p) for p in folders if not p.is_dir()]
        if missing:
            for p in missing:
                print(f"ERROR 不是目录：{p}", file=sys.stderr)
            return 1
    else:
        folders = discover()
    if not folders:
        print(f"ERROR 没有找到技能目录：{SKILLS}", file=sys.stderr)
        return 1

    errors: list[str] = []
    warnings: list[str] = []
    for folder in folders:
        e, w = check_one(folder)
        errors.extend(e)
        warnings.extend(w)
    for line in warnings:
        print(f"WARN  {line}")
    for line in errors:
        print(f"ERROR {line}", file=sys.stderr)
    print(f"\nchecked={len(folders)} errors={len(errors)} warnings={len(warnings)}")
    if errors:
        return 1
    if warnings and args.strict:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
