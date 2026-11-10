#!/usr/bin/env python3
"""Which calculation codes are actually installable from this image's apt mirror?

Round 33: ``apt-get install cp2k`` failed (exit 100) even after enabling universe.
Rather than guessing again, report `apt-cache policy` for every code we care about,
plus the enabled sources, so H3c can be planned against facts.

Writes ``apt_packages.json``.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

PACKAGES = ["cp2k", "quantum-espresso", "quantum-espresso-data", "gromacs",
            "lammps", "nwchem", "siesta", "abacus", "openmx", "dftbplus",
            "octopus", "elk-lapw", "python3-ase"]


def run(command: str, timeout: int = 600) -> dict:
    started = time.time()
    proc = subprocess.run(["bash", "-lc", command], capture_output=True, text=True,
                          timeout=timeout)
    return {"command": command[:70], "exit": proc.returncode,
            "seconds": round(time.time() - started, 1),
            "stdout": (proc.stdout or "")[-2000:], "stderr": (proc.stderr or "")[-500:]}


def main() -> int:
    report: dict = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "os_release": Path("/etc/os-release").read_text(encoding="utf-8")
                    if Path("/etc/os-release").is_file() else "",
                    "sources": [], "policy": {}, "errors": []}

    run("apt-get update -qq", timeout=900)
    report["sources"] = [line for line in
                         run("grep -rhoE '^[^#]*ubuntu\\.com[^ ]*' /etc/apt/sources.list "
                             "/etc/apt/sources.list.d/* 2>/dev/null | head -20"
                             ).get("stdout", "").splitlines() if line.strip()]
    for package in PACKAGES:
        result = run(f"apt-cache policy {package} 2>&1 | head -6", timeout=120)
        report["policy"][package] = result.get("stdout", "").strip()
        installed = "Installed" in result.get("stdout", "") and \
            "Installed: (none)" not in result.get("stdout", "")
        print(f"{package:24s} {'INSTALLABLE' if 'Candidate:' in result.get('stdout','') and '(none)' not in result.get('stdout','').split('Candidate:')[1][:40] else 'not-available'}")

    Path("apt_packages.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    print("report written: apt_packages.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
