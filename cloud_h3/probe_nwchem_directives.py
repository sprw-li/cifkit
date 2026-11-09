#!/usr/bin/env python3
"""Extract NWChem's *actual* plane-wave input directives from its shipped sources.

Round 29: ``nwpw`` + ``ecut 20`` was rejected with ``nwpw_input: unknown
directive: ecut``.  Rather than guessing a third time, read the program's own
source fragments (Debian ships them under ``/usr/share/nwchem/libraryps``) and
find the code that raises ``unknown directive``; the surrounding string literals
are the accepted keyword list.

Writes ``nwchem_directives.json``.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

ROOTS = ["/usr/share/nwchem", "/usr/lib/nwchem", "/usr/share/doc/nwchem", "/opt/nwchem"]


def run(command: str, timeout: int = 300) -> str:
    proc = subprocess.run(["bash", "-lc", command], capture_output=True, text=True, timeout=timeout)
    return (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="nwchem_directives.json")
    parser.add_argument("--context", type=int, default=60)
    args = parser.parse_args()

    report: dict = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "install": None,
                    "examples_dir": None, "hits": [], "directive_names": [],
                    "nwpw_inp_fh": "", "notes": []}

    if not shutil.which("nwchem"):
        started = time.time()
        proc = subprocess.run(["bash", "-lc", "apt-get update -qq && apt-get install -y nwchem"],
                              capture_output=True, text=True, timeout=1800)
        report["install"] = {"exit": proc.returncode, "seconds": round(time.time() - started, 1)}
        print(f"[install] exit {proc.returncode}")

    report["examples_dir"] = run("ls /usr/share/doc/nwchem/examples/ | head -60")
    print("examples:", report["examples_dir"][:600])

    # 1) the include file that defines the block
    for candidate in ("/usr/share/nwchem/libraryps/nwpw_inp.fh",
                      "/usr/share/nwchem/libraryps/nwpw_input.F"):
        if os.path.isfile(candidate):
            text = Path(candidate).read_text(encoding="utf-8", errors="replace")
            if candidate.endswith(".fh"):
                report["nwpw_inp_fh"] = text[:4000]
            print(f"--- {candidate} ({len(text)} bytes) ---")
            print(text[:1500])

    # 2) the error site + the keyword list around it
    roots = " ".join(root for root in ROOTS if os.path.isdir(root))
    if roots:
        grep = run(f"grep -rn 'unknown directive' {roots} 2>/dev/null | head -5")
        report["error_site"] = grep
        print("error site:", grep[:400])
        for line in grep.splitlines():
            parts = line.split(":", 2)
            if len(parts) < 2:
                continue
            path, lineno = parts[0], int(parts[1]) if parts[1].isdigit() else 0
            if not lineno:
                continue
            start = max(1, lineno - args.context)
            report["hits"].append({
                "file": path, "line": lineno,
                "context": run(f"sed -n '{start},{lineno + 10}p' {path}"),
            })

    # 3) candidate directive names: quoted lowercase tokens in the plane-wave sources
    names = run(f"grep -rhoE \"'[a-z_][a-z_0-9]*'\" {roots} 2>/dev/null | sort | uniq -c | sort -rn | head -80")
    report["directive_names_raw"] = names
    tokens = re.findall(r"'([a-z_][a-z_0-9]*)'", names or "")
    report["directive_names"] = sorted(set(tokens))
    print("candidate tokens:", ", ".join(report["directive_names"][:40]))

    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
