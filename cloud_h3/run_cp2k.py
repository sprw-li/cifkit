#!/usr/bin/env python3
"""H3c probe: run **cifkit's own CP2K export** in a real CP2K (round 33).

Our CP2K export is a geometry+MGRID skeleton and deliberately lacks
``&KIND``/``BASIS_SET``/``POTENTIAL`` (documented in ``BUNDLE_INFO['cp2k']['missing']``).
This probe does exactly what a user would have to do, **with CP2K's own shipped
data files**, and reports whether the result actually runs:

1. install CP2K (Ubuntu ``universe``; the image only has ``main`` enabled);
2. find ``BASIS_MOLOPT`` and ``GTH_POTENTIALS`` in the installed package;
3. for every element in the template, pick a basis set and a GTH potential from
   those files and append the ``&KIND`` sections;
4. run ``cp2k`` and look for its completion marker (``PROGRAM ENDED AT``).

Writes ``cp2k_result.json``.  Exit 0 whenever the probe ran (the platform treats a
non-zero user command as job failure, which would blur "CP2K missing" with "the
harness broke").
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

HERE = Path(__file__).resolve().parent


def run(cmd, timeout=None, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "DEBIAN_FRONTEND": "noninteractive", **(env or {})})


def install_cp2k(report: dict) -> None:
    steps = [
        ("apt-get update -qq", 900),
        ("apt-get install -y -o Dpkg::Options::=--force-confdef software-properties-common",
         900),
        ("add-apt-repository -y universe", 900),
        ("apt-get update -qq", 900),
        ("apt-get install -y -o Dpkg::Options::=--force-confdef cp2k", 1800),
    ]
    for command, timeout in steps:
        started = time.time()
        proc = subprocess.run(["bash", "-lc", command], capture_output=True, text=True,
                              timeout=timeout,
                              env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
        ok = proc.returncode == 0
        report["install_steps"].append({"command": command[:60], "exit": proc.returncode,
                                        "seconds": round(time.time() - started, 1),
                                        "tail": (proc.stdout or proc.stderr or "")[-300:]})
        print(f"[install] {command[:50]}: exit {proc.returncode}")
        if not ok and "cp2k" in command:
            report["errors"].append(f"cp2k install failed: {proc.returncode}")


def find_data_files() -> dict:
    """Locate BASIS_MOLOPT / GTH_POTENTIALS inside the installed package."""
    listing = run(["bash", "-lc", "dpkg -L cp2k 2>/dev/null | head -400"]).stdout or ""
    found: dict[str, str] = {}
    for line in listing.splitlines():
        name = os.path.basename(line)
        if name in ("BASIS_MOLOPT", "GTH_POTENTIALS", "BASIS_MOLOPT_UZH", "POTENTIAL"):
            found[name] = line.strip()
    if not found:
        search = run(["bash", "-lc",
                      "find / -xdev \\( -name BASIS_MOLOPT -o -name GTH_POTENTIALS \\) "
                      "2>/dev/null | head -10"]).stdout or ""
        for line in search.splitlines():
            found.setdefault(os.path.basename(line.strip()), line.strip())
    return found


def basis_for(symbol: str, basis_text: str) -> str | None:
    """Pick a DZVP-MOLOPT basis defined for this element."""
    pattern = re.compile(rf"^\s*{re.escape(symbol)}\s+(\S+)\s+(DZVP-MOLOPT-SR-GTH|DZVP-MOLOPT-GTH)")
    for line in basis_text.splitlines():
        match = pattern.match(line)
        if match:
            return match.group(1)
    return None


def potential_for(symbol: str, potential_text: str) -> str | None:
    """Pick a GTH-PBE pseudo-potential for this element."""
    pattern = re.compile(rf"^\s*{re.escape(symbol)}\s+(GTH-PBE-q\d+)")
    for line in potential_text.splitlines():
        match = pattern.match(line)
        if match:
            return match.group(1)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="cases/cp2k_export.inp")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--out", default="cp2k_result.json")
    args = parser.parse_args()

    report: dict = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "input": args.input, "install_steps": [], "data_files": {},
                    "kinds": [], "binary": None, "exit": None, "finished": False,
                    "errors": [], "tail": ""}

    if args.install and not shutil.which("cp2k"):
        install_cp2k(report)

    binary = next((p for p in ("cp2k.psmp", "cp2k.popt", "cp2k.ssmp", "cp2k")
                   if shutil.which(p)), None)
    report["binary"] = binary
    if not binary:
        report["errors"].append("no cp2k binary found")
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        print("cp2k not installed")
        return 0

    source = HERE / args.input
    if not source.is_file():
        report["errors"].append(f"input not found: {args.input}")
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        return 0
    template = source.read_text(encoding="utf-8")

    data = find_data_files()
    report["data_files"] = data
    basis_text = Path(data["BASIS_MOLOPT"]).read_text(encoding="utf-8", errors="replace") \
        if "BASIS_MOLOPT" in data else ""
    potential_text = Path(data["GTH_POTENTIALS"]).read_text(encoding="utf-8", errors="replace") \
        if "GTH_POTENTIALS" in data else ""

    # elements from the &COORD block
    coord = re.search(r"&COORD(.*?)&END COORD", template, re.S)
    elements: list[str] = []
    if coord:
        for line in coord.group(1).splitlines():
            parts = line.split()
            if parts and re.fullmatch(r"[A-Z][a-z]?", parts[0]) and parts[0] not in elements:
                elements.append(parts[0])
    report["elements"] = elements

    kinds = []
    for symbol in elements:
        basis = basis_for(symbol, basis_text)
        potential = potential_for(symbol, potential_text)
        kinds.append({"element": symbol, "basis": basis, "potential": potential})
        if not basis or not potential:
            report["errors"].append(f"no basis/potential for {symbol}")
    report["kinds"] = kinds

    if all(k["basis"] and k["potential"] for k in kinds):
        block = ["  &DFT"]
        where = template.index("  &DFT")
        rest = template[where + len("  &DFT"):]
        kind_lines = []
        for kind in kinds:
            kind_lines += [f"    &KIND {kind['element']}",
                           f"      BASIS_SET {kind['basis']}",
                           f"      POTENTIAL {kind['potential']}",
                           "    &END KIND"]
        # BASIS_SET_FILE_NAME / POTENTIAL_FILE_NAME must live inside &DFT
        header = [f'    BASIS_SET_FILE_NAME {data["BASIS_MOLOPT"]}',
                  f'    POTENTIAL_FILE_NAME {data["GTH_POTENTIALS"]}']
        runnable = template[:where] + block[0] + "\n" + "\n".join(header + kind_lines) + rest
        # global run type
        runnable = runnable.replace("&FORCE_EVAL", "&GLOBAL\n  RUN_TYPE ENERGY\n  PRINT_LEVEL LOW\n&END GLOBAL\n&FORCE_EVAL", 1)
        workdir = Path("/tmp/cp2k_h3c")
        workdir.mkdir(parents=True, exist_ok=True)
        target = workdir / "run.inp"
        target.write_text(runnable, encoding="utf-8")
        report["runnable_chars"] = len(runnable)

        started = time.time()
        proc = subprocess.run([binary, "-i", str(target)],
                              cwd=workdir, capture_output=True, text=True, timeout=1800)
        blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
        report["seconds"] = round(time.time() - started, 1)
        report["exit"] = proc.returncode
        report["finished"] = "PROGRAM ENDED AT" in blob and proc.returncode == 0
        report["tail"] = blob[-2500:]
        for line in blob.splitlines():
            if "ABORT" in line or "ERROR" in line.upper()[:40]:
                report["errors"].append(line.strip()[:200])
        print(f"cp2k exit={proc.returncode} finished={report['finished']} "
              f"({report['seconds']}s)")
        print(report["tail"][-900:])

    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print("report written:", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
