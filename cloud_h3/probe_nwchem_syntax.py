#!/usr/bin/env python3
"""Find NWChem's *own* periodic (pspw/nwpw) examples inside the container.

Instead of guessing the plane-wave syntax (round 28 wasted one job on a guess and
was rejected with ``nwpw_input: unknown directive: ecut``), this probe reads the
examples that ship with the program:

    python probe_nwchem_syntax.py [--install]

It writes ``nwchem_syntax.json`` containing, for every file it finds that mentions
``pspw``/``nwpw``: the path, its size, and the first N lines.  The host then fixes
our exporter against a **real** example, not against a guess.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

#: where a Debian/Ubuntu nwchem package puts binaries, data and documentation
SEARCH_ROOTS = [
    "/usr/share/nwchem", "/usr/share/nwchem-*", "/usr/lib/nwchem",
    "/usr/share/doc/nwchem", "/usr/share/doc/nwchem-*", "/opt/nwchem",
    "/usr/local/share/nwchem", "/usr/lib/x86_64-linux-gnu/nwchem",
]
#: directives that mark a file as plane-wave input
MARKERS = ("task pspw", "task nwpw", "nwpw", "pspw", "simulation_cell")
EXCLUDES = ("/usr/share/doc/nwchem/copyright",)


def run(cmd: list[str], cwd: str | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def candidate_dirs() -> list[str]:
    found: list[str] = []
    for pattern in SEARCH_ROOTS:
        import glob

        found.extend(sorted(glob.glob(pattern)))
    return [path for path in found if os.path.isdir(path)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--max-files", type=int, default=12)
    parser.add_argument("--head", type=int, default=60)
    parser.add_argument("--out", default="nwchem_syntax.json")
    args = parser.parse_args()

    report: dict = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "install": None,
                    "binary": None, "roots": [], "files": [], "examples": [],
                    "notes": []}

    if args.install and not shutil.which("nwchem"):
        started = time.time()
        proc = run(["bash", "-lc", "apt-get update -qq && apt-get install -y nwchem"], timeout=1800)
        report["install"] = {"exit": proc.returncode, "seconds": round(time.time() - started, 1)}
        print(f"[install] nwchem exit {proc.returncode}")

    report["binary"] = shutil.which("nwchem")
    if not report["binary"]:
        report["notes"].append("nwchem not installed")
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    # where does the package keep its data?
    dpkg = run(["bash", "-lc", "dpkg -L nwchem 2>/dev/null | head -200"])
    report["dpkg_files"] = [line for line in (dpkg.stdout or "").splitlines() if line.strip()][:200]

    roots = candidate_dirs()
    report["roots"] = roots
    print("data roots:", roots)

    matches: list[Path] = []
    for root in roots:
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                path = Path(dirpath) / name
                if str(path) in EXCLUDES:
                    continue
                try:
                    if path.stat().st_size > 400_000:
                        continue
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                lowered = text.lower()
                if any(marker in lowered for marker in MARKERS):
                    matches.append(path)
                    if len(matches) >= args.max_files:
                        break
            if len(matches) >= args.max_files:
                break

    report["files"] = [str(path) for path in matches]
    print(f"files mentioning pspw/nwpw: {len(matches)}")
    for path in matches:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        head = "\n".join(text.splitlines()[: args.head])
        report["examples"].append({"path": str(path), "bytes": path.stat().st_size,
                                   "head": head})
        print(f"  {path} ({path.stat().st_size} B)")
        print("    " + "\n    ".join(text.splitlines()[:6]))

    # also: what does the binary itself know about the module names?
    help_proc = run(["bash", "-lc", "nwchem -help 2>&1 | head -40"])
    report["help"] = (help_proc.stdout or "")[:2000]

    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
