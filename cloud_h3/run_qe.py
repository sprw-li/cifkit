#!/usr/bin/env python3
"""H3c probe: run **cifkit's own Quantum ESPRESSO export** in a real pw.x (round 33).

Facts established in round 33: this image's apt mirror has ``quantum-espresso``
(6.7) and ``quantum-espresso-data`` but **no** ``cp2k``.  So QE is the code we can
actually verify here.

What the probe does — and why each step is needed:

1. install ``quantum-espresso`` + ``quantum-espresso-data`` (the package ships UPF
   pseudopotentials; our export only writes placeholder ``<El>.UPF`` names);
2. locate the UPF files the package provides and check that H/C/O are covered;
3. patch our exported input into a *runnable* smoke test:
   * ``pseudo_dir`` → the package's pseudo dir,
   * ``ATOMIC_SPECIES`` → real UPF filenames,
   * ``ecutwfc`` 20 Ry (fast) and ``electron_maxstep 30`` / ``conv_thr 1e-4``
     (the export deliberately says "converged cutoff/k-points" is the user's job;
     one SCF iteration would abort, so we let it converge);
4. run ``pw.x`` and report ``JOB DONE``.

Writes ``qe_result.json``; exit 0 whenever the probe ran.
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


def run(command: str, timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-lc", command], capture_output=True, text=True,
                          timeout=timeout,
                          env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})


def install(report: dict) -> None:
    for command in ("apt-get update -qq",
                    "apt-get install -y -o Dpkg::Options::=--force-confdef "
                    "quantum-espresso quantum-espresso-data"):
        started = time.time()
        proc = run(command)
        report["install_steps"].append({"command": command[:70], "exit": proc.returncode,
                                        "seconds": round(time.time() - started, 1),
                                        "tail": (proc.stdout or proc.stderr or "")[-300:]})
        print(f"[install] {command[:55]}: exit {proc.returncode}")


def find_pseudo_dirs() -> list[Path]:
    dirs: list[Path] = []
    listing = run("dpkg -L quantum-espresso-data 2>/dev/null | head -200").stdout or ""
    for line in listing.splitlines():
        path = Path(line.strip())
        if path.suffix.lower() == ".upf":
            dirs.append(path.parent)
    if not dirs:
        for candidate in ("/usr/share/espresso/pseudo", "/usr/share/quantum-espresso/pseudo",
                          "/usr/share/espresso", "/usr/share/quantum-espresso"):
            if Path(candidate).is_dir():
                dirs.append(Path(candidate))
    unique: list[Path] = []
    for directory in dirs:
        if directory not in unique and directory.is_dir():
            unique.append(directory)
    return unique


def pick_upf(element: str, dirs: list[Path]) -> Path | None:
    """Prefer a PBE UPF with a reasonable cutoff ordering."""
    candidates: list[Path] = []
    for directory in dirs:
        candidates.extend(directory.glob(f"{element}*.UPF"))
        candidates.extend(directory.glob(f"{element.lower()}*.UPF"))
    if not candidates:
        return None
    def score(path: Path) -> tuple:
        name = path.name.lower()
        return (0 if "pbe" in name else 1, 0 if "rrkjus" in name else 1, len(name))
    return sorted(candidates, key=score)[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="cases/qe_export.in")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--ecutwfc", type=int, default=30)
    parser.add_argument("--maxstep", type=int, default=40)
    parser.add_argument("--out", default="qe_result.json")
    args = parser.parse_args()

    report: dict = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "input": args.input,
                    "install_steps": [], "pseudo_dirs": [], "upfs": {},
                    "binary": None, "exit": None, "job_done": False,
                    "errors": [], "tail": ""}

    if args.install and not shutil.which("pw.x"):
        install(report)

    binary = shutil.which("pw.x")
    report["binary"] = binary
    if not binary:
        report["errors"].append("pw.x not installed")
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        print("pw.x not installed")
        return 0

    dirs = find_pseudo_dirs()
    report["pseudo_dirs"] = [str(d) for d in dirs]
    source = HERE / args.input
    if not source.is_file():
        report["errors"].append(f"input not found: {args.input}")
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        return 0
    template = source.read_text(encoding="utf-8")

    species_block = re.search(r"ATOMIC_SPECIES(.*?)(?:\nK_POINTS|\nCELL_PARAMETERS)", template, re.S)
    elements = []
    if species_block:
        for line in species_block.group(1).splitlines():
            parts = line.split()
            if len(parts) >= 2:
                elements.append(parts[0])
    report["elements"] = elements

    chosen: dict[str, str] = {}
    for element in elements:
        path = pick_upf(element, dirs)
        if path:
            chosen[element] = str(path)
            report["upfs"][element] = str(path)
        else:
            report["errors"].append(f"no UPF for {element}")
    if len(chosen) != len(elements):
        report["errors"].append("missing pseudopotentials -> cannot run")
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        print("missing UPFs:", report["errors"])
        return 0

    pseudo_dir = str(Path(next(iter(chosen.values()))).parent)
    text = template
    text = text.replace("&CONTROL\n/", f"&CONTROL\n  calculation = 'scf'\n"
                                       f"  prefix = 'cifkit'\n"
                                       f"  pseudo_dir = '{pseudo_dir}'\n"
                                       f"  outdir = './tmp'\n/", 1)
    text = re.sub(r"&SYSTEM\n/",
                  f"&SYSTEM\n  ecutwfc = {args.ecutwfc}\n  nbnd = 40\n/", text, count=1)
    text = re.sub(r"&ELECTRONS\n/",
                  f"&ELECTRONS\n  conv_thr = 1.0d-4\n  electron_maxstep = {args.maxstep}\n/",
                  text, count=1)
    for element, path in chosen.items():
        text = re.sub(rf"(?m)^{element}\s+([0-9.]+)\s+\S+UPF.*$",
                      rf"{element} \g<1> {Path(path).name}", text)

    # QE 6.7 (Ubuntu 24.04, glibc 2.39 fortify) aborts with
    # "*** buffer overflow detected ***" while parsing **empty** namelists:
    # our export writes &IONS // &CELL // &FCP // &RISM with no content, and QE
    # only warns "card ignored" before the abort.  Drop the ones an SCF does not
    # need instead of feeding the parser empty blocks.
    for card in ("&IONS", "&CELL", "&FCP", "&RISM"):
        text = re.sub(rf"{card}\s*\n\s*/\s*\n", "", text)
    report["dropped_empty_cards"] = ["&IONS", "&CELL", "&FCP", "&RISM"]
    workdir = Path("/tmp/qe_h3c")
    workdir.mkdir(parents=True, exist_ok=True)
    target = workdir / "run.in"
    target.write_text(text, encoding="utf-8")
    report["runnable_chars"] = len(text)
    report["pseudo_dir"] = pseudo_dir

    started = time.time()
    proc = subprocess.run([binary, "-in", str(target)], cwd=workdir, capture_output=True,
                          text=True, timeout=3600)
    blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    report["seconds"] = round(time.time() - started, 1)
    report["exit"] = proc.returncode
    report["job_done"] = "JOB DONE" in blob
    report["tail"] = blob[-2500:]
    for line in blob.splitlines():
        low = line.lower()
        if "error" in low or "convergence not achieved" in low or "stopping" in low:
            report["errors"].append(line.strip()[:200])
    print(f"pw.x exit={proc.returncode} JOB DONE={report['job_done']} ({report['seconds']}s)")
    print(report["tail"][-1000:])

    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("report written:", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
