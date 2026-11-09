#!/usr/bin/env python3
"""Find a *working* periodic NWChem input pattern by experiment (round 29).

Facts already gathered: the plane-wave source fragments use ``cutoff`` (not
``ecut``), and the module needs pseudopotentials.  This probe locates the shipped
pseudopotential library and then tries a few minimal periodic inputs, reporting
for each one the exit code, the offending input line, and whether NWChem printed
``Total times`` (i.e. actually finished).

Writes ``nwchem_pspw_probe.json``.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

GEOMETRY = """start probe
permanent_dir .
scratch_dir .
geometry units angstrom
  system crystal
    lattice_vectors
      6.0 0.0 0.0
      0.0 6.0 0.0
      0.0 0.0 6.0
  end
  H 0.0 0.0 0.0
  H 0.0 0.0 0.74
end
"""

#: candidate task/theory snippets, from most to least standard
VARIANTS = {
    "block_cutoff_pspw": "nwpw\n  cutoff 20\n  xc pbe\nend\ntask pspw energy\n",
    "block_cutoff_nwpw": "nwpw\n  cutoff 20\n  xc pbe\nend\ntask nwpw energy\n",
    "set_cutoff_pspw": "set nwpw:cutoff 20\nset nwpw:xc pbe\ntask pspw energy\n",
    "bare_pspw": "task pspw energy\n",
}


def run(command: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-lc", command], capture_output=True, text=True, timeout=timeout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="nwchem_pspw_probe.json")
    args = parser.parse_args()

    report: dict = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "install": None,
                    "psp_files": [], "nwchem_tree": [], "variants": [], "notes": []}
    if not shutil.which("nwchem"):
        started = time.time()
        proc = subprocess.run(["bash", "-lc", "apt-get update -qq && apt-get install -y nwchem"],
                              capture_output=True, text=True, timeout=1800)
        report["install"] = {"exit": proc.returncode, "seconds": round(time.time() - started, 1)}
        print(f"[install] exit {proc.returncode}")

    report["psp_files"] = [line for line in
                           run("find / -xdev \\( -name '*.psp' -o -name '*.vps' -o -name '*.hgh' \\) "
                               "2>/dev/null | head -40").stdout.splitlines() if line.strip()]
    report["nwchem_tree"] = [line for line in
                             run("find /usr/share/nwchem -maxdepth 3 2>/dev/null | head -60"
                                 ).stdout.splitlines() if line.strip()]
    print("psp files:", report["psp_files"][:10])
    print("tree:", report["nwchem_tree"][:15])

    workdir = Path("/tmp/pspw_probe")
    workdir.mkdir(parents=True, exist_ok=True)
    for name, snippet in VARIANTS.items():
        input_path = workdir / f"{name}.nw"
        input_path.write_text(GEOMETRY + "\n" + snippet, encoding="utf-8")
        started = time.time()
        proc = subprocess.run(["nwchem", input_path.name], cwd=workdir, capture_output=True,
                              text=True, timeout=900)
        blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
        offending = ""
        for line in blob.splitlines():
            if "current input line" in line.lower():
                offending = line.strip()
            if "unknown directive" in line.lower() or "There is an error" in line:
                offending = offending or line.strip()
        row = {
            "variant": name,
            "exit": proc.returncode,
            "seconds": round(time.time() - started, 1),
            "finished": "Total times" in blob,
            "unknown_directive": "unknown directive" in blob.lower(),
            "error_lines": [line.strip()[:160] for line in blob.splitlines()
                            if "error" in line.lower()][:4],
            "tail": blob[-700:],
        }
        report["variants"].append(row)
        print(f"[{name}] exit={row['exit']} finished={row['finished']} "
              f"unknown_directive={row['unknown_directive']}")

    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
