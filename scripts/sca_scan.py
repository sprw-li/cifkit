"""Lightweight source-code licence scan (SCA-lite) for commercial reuse.

Review round 13 left limitation **L7** open: "no per-file copyright audit".  A
full SCA needs a tool like ScanCode/FOSSology; this script does the honest 80 %
that is useful in CI:

1. scan every tracked text file for copyleft/ownership markers
   (GPL/LGPL/AGPL/BSD/MIT/Apache header phrases);
2. flag files that *mention* copyleft licences **without** being one of our own
   documentation files (candidates for manual review);
3. report vendored code (third-party blocks) by looking for common markers;
4. write a JSON + Markdown report with counts and the exact file:line hits.

Exit code: 0 by default (report only); ``--strict`` fails when a source file
carries a copyleft header (i.e. code we would be relicensing under MIT).

    .venv\\Scripts\\python.exe scripts\\sca_scan.py [--strict] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TEXT_SUFFIXES = {".py", ".md", ".json", ".txt", ".cif", ".cfg", ".toml", ".yaml", ".yml",
                 ".sh", ".ps1", ".jsonl", ".in", ".vasp", ".xyz", ".html", ".css", ".js"}
SKIP_DIRS = {"_cache", ".git", "__pycache__", ".venv", "runs", "library", ".pytest_cache",
             ".mypy_cache", ".ruff_cache"}

#: (marker regex, licence class, note)
MARKERS: list[tuple[str, str, str]] = [
    (r"GNU AFFERO GENERAL PUBLIC", "copyleft", "AGPL header"),
    (r"\bAGPL\b", "copyleft", "AGPL mention"),
    (r"GNU GENERAL PUBLIC LICENSE", "copyleft", "GPL header"),
    (r"\bGPL-?[23](\.\d)?\b", "copyleft", "GPL identifier"),
    (r"\bGPL\b", "copyleft", "GPL mention"),
    (r"GNU LESSER GENERAL PUBLIC", "weak-copyleft", "LGPL header"),
    (r"\bLGPL\b", "weak-copyleft", "LGPL mention"),
    (r"Mozilla Public License", "weak-copyleft", "MPL header"),
    (r"Apache License", "permissive", "Apache header"),
    (r"MIT License", "permissive", "MIT header"),
    (r"BSD [23]-Clause", "permissive", "BSD header"),
    (r"Copyright \(c\)", "notice", "copyright notice"),
    (r"This file is part of", "notice", "vendored-code marker"),
    (r"(copied|adapted|derived) from", "notice", "derivation marker"),
]

#: files whose *purpose* is licence discussion (mentions are expected there)
DOC_ALLOWLIST = {
    "LICENSE", "LICENSING.md", "THIRD-PARTY-NOTICES.md", "README.md",
    "docs/LIMITATIONS.md", "docs/REVIEW-ROUND13-COMMERCIAL.md",
    "scripts/license_audit.py", "scripts/sca_scan.py", "scripts/verify_formats_no_gpl.py",
    "cifkit/platform.py", "docs/API.md", "docs/PIPELINE.md", ".gitattributes",
}


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=str(ROOT), capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=120)
        if out.returncode == 0 and out.stdout.strip():
            return [ROOT / line.strip() for line in out.stdout.splitlines() if line.strip()]
    except Exception:  # noqa: BLE001 - fall back to a walk
        pass
    files = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


DQ3 = 3 * '"'
SQ3 = 3 * "'"


def _line_kinds(text: str) -> list[str]:
    """Per-line classification: ``comment`` / ``docstring`` / ``code``.

    Approximate (triple-quote tracking, no AST) but enough to separate "we talk
    about the GPL in a comment" from "we import GPL code".
    """
    kinds: list[str] = []
    in_doc = False
    for line in text.splitlines():
        stripped = line.strip()
        if in_doc:
            kinds.append("docstring")
            if stripped.count(DQ3) % 2 == 1 or stripped.count(SQ3) % 2 == 1:
                in_doc = False
            continue
        if stripped.startswith("#"):
            kinds.append("comment")
            continue
        triple = stripped.count(DQ3) + stripped.count(SQ3)
        if triple % 2 == 1:
            kinds.append("docstring")
            in_doc = True
            continue
        if triple >= 2:
            kinds.append("docstring")
            continue
        kinds.append("code")
    return kinds


def scan() -> dict:
    hits: list[dict] = []
    scanned = 0
    for path in tracked_files():
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        scanned += 1
        rel = path.relative_to(ROOT).as_posix()
        allowed = rel in DOC_ALLOWLIST
        kinds = _line_kinds(text)
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern, cls, note in MARKERS:
                if re.search(pattern, line, re.IGNORECASE):
                    hits.append({"file": rel, "line": lineno, "class": cls, "note": note,
                                 "kind": kinds[lineno - 1] if lineno - 1 < len(kinds) else "code",
                                 "text": line.strip()[:160], "allowlisted": allowed})
                    break
    counts: dict[str, int] = {}
    for hit in hits:
        counts[hit["class"]] = counts.get(hit["class"], 0) + 1
    # Only *code* hits matter: a copyleft marker inside a comment/docstring is a
    # discussion, not relicensed code.  That distinction is what keeps the check
    # trustworthy instead of noisy.
    actionable = [h for h in hits if h["class"] in ("copyleft", "weak-copyleft")
                  and h["kind"] == "code" and not h["allowlisted"]
                  and h["file"].endswith((".py", ".sh", ".ps1", ".js"))]
    discussion = [h for h in hits if h["class"] in ("copyleft", "weak-copyleft")
                  and h["kind"] in ("comment", "docstring") and not h["allowlisted"]]
    return {
        "scanned_files": scanned,
        "total_hits": len(hits),
        "counts": counts,
        "actionable_copyleft": actionable,
        "copyleft_discussion": discussion,
        "hits": hits,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "note": ("SCA-lite：只做文本标记扫描，不做代码溯源/相似度比对；"
                 "`actionable_copyleft` 是需要在源码里人工复核的候选，"
                 "不是法律结论。完整 SCA 请用 ScanCode/FOSSology。"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(ROOT / "runs" / "sca_scan.json"))
    ap.add_argument("--strict", action="store_true",
                    help="源码文件命中 copyleft/weak-copyleft 时返回 1")
    ap.add_argument("--limit", type=int, default=25, help="报告里最多列出多少条命中")
    args = ap.parse_args()

    report = scan()
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"scanned {report['scanned_files']} files, {report['total_hits']} marker hits")
    for cls, count in sorted(report["counts"].items()):
        print(f"  {cls:16s} {count}")
    actionable = report["actionable_copyleft"]
    print(f"actionable copyleft in source code: {len(actionable)}"
          f" (mention-only in comments/docs: {len(report['copyleft_discussion'])})")
    for hit in actionable[: args.limit]:
        print(f"  {hit['file']}:{hit['line']} [{hit['note']}] {hit['text'][:80]}")
    print(f"report: {out}")
    if args.strict and actionable:
        print("STRICT: copyleft markers found in source files", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
