#!/usr/bin/env python3
"""Real LAMMPS physics check + honest force-field inventory (round 56).

The earlier acceptance used ``pair_style zero``: **zero force evaluations**, i.e. no
physics at all.  This job answers three questions with output we keep:

1. which pair styles does the Debian LAMMPS actually have? (save the raw ``lmp -h``);
2. can our exported ``data.lammps`` run a **real** minimisation with nonzero forces -
   ``pair_style lj/cut`` (built in, no external file) with explicitly documented
   placeholder parameters;
3. what does GROMACS have, and can it build a topology for our file at all?

The LJ numbers are **not** chemistry: they are evidence that the file drives a real
force/energy computation, with the parameter choice stated in the output.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

PLACEHOLDER = {"epsilon_eV": 0.0103, "sigma_A": 3.4, "cutoff_A": 10.0}


def apt(package: str) -> bool:
    proc = subprocess.run(
        ["bash", "-lc", f"export DEBIAN_FRONTEND=noninteractive; apt-get update -qq && "
                       f"apt-get install -y -qq --no-install-recommends {package}"],
        capture_output=True, text=True,
        env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"}, timeout=1800)
    print(f"apt {package}: exit={proc.returncode}", flush=True)
    return proc.returncode == 0


def element_types(data_text: str) -> list[str]:
    """Element per LAMMPS type, from the '# type N -> El' comment cifkit writes."""
    pairs = re.findall(r"^#\s*type\s+(\d+)\s*->\s*([A-Z][a-z]?)\s*:",
                       data_text, re.M)
    return [symbol for _number, symbol in sorted(pairs, key=lambda item: int(item[0]))]


def probe_lammps() -> dict:
    binary = shutil.which("lmp") or shutil.which("lmp_mpi")
    out: dict = {"binary": binary}
    if not binary:
        return out
    proc = subprocess.run([binary, "-h"], capture_output=True, text=True, timeout=300)
    header = (proc.stdout or "") + (proc.stderr or "")
    Path("lmp_header.txt").write_text(header, encoding="utf-8")
    # the header lists styles under headings like "Pair styles:" or "* pair styles:"
    styles = set()
    for line in header.splitlines():
        if re.search(r"pair styles", line, re.I):
            continued = line.split(":", 1)[-1]
            styles.update(token for token in re.split(r"[\s,]+", continued) if token)
    out["pair_style_heading_lines"] = [line.strip() for line in header.splitlines()
                                       if re.search(r"pair styles", line, re.I)][:4]
    out["styles_sample"] = sorted(styles)[:40]
    out["has_lj_cut"] = any("lj/cut" in token for token in styles) or "lj/cut" in header
    out["has_uff"] = any(token == "uff" for token in styles) or re.search(r"\buff\b", header) is not None

    runs = []
    for case in sorted(path for path in Path("cases/batch").glob("lammps__*") if path.is_dir())[:3]:
        work = Path("lj_run") / case.name
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        for source in case.iterdir():
            if source.is_file():
                shutil.copy2(source, work / source.name)
        data_text = (work / "data.lammps").read_text(encoding="utf-8")
        symbols = element_types(data_text)
        typed = " ".join(symbols)
        script = f"""# REAL forces: lj/cut is built in (no potential file needed).
# Parameters below are PLACEHOLDERS ({PLACEHOLDER['epsilon_eV']} eV, {PLACEHOLDER['sigma_A']} A),
# NOT a fitted force field - this run proves the file drives a real computation.
units           metal
atom_style      atomic
boundary        p p p
read_data       data.lammps
pair_style      lj/cut {PLACEHOLDER['cutoff_A']}
pair_coeff      * * {PLACEHOLDER['epsilon_eV']} {PLACEHOLDER['sigma_A']} {typed}
neighbor        2.0 bin
thermo          1
thermo_style    custom step pe etotal press
min_style       cg
minimize        1e-6 1e-8 200 2000
"""
        (work / "in.lj").write_text(script, encoding="utf-8")
        started = time.time()
        try:
            proc = subprocess.run([binary, "-in", "in.lj"], cwd=str(work),
                                  capture_output=True, text=True, timeout=900)
            blob = (proc.stdout or "") + (proc.stderr or "")
            code = proc.returncode
        except subprocess.TimeoutExpired as exc:
            blob, code = str(exc), "timeout"
        (work / "lj.log").write_text(blob, encoding="utf-8")
        iters = re.search(r"Iterations, force evaluations = (\d+) (\d+)", blob)
        energies = re.findall(r"^\s*(\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)",
                              blob, re.M)
        final = re.search(r"Energy initial, next-to-last, final =\s*\n\s*"
                          r"(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)", blob)
        runs.append({
            "case": case.name, "exit": code,
            "elements": symbols,
            "force_evaluations": int(iters.group(2)) if iters else 0,
            "minimisation_steps": int(iters.group(1)) if iters else 0,
            "energy_rows": len(energies),
            "energy_initial": float(final.group(1)) if final else None,
            "energy_final": float(final.group(3)) if final else None,
            "seconds": round(time.time() - started, 1),
            "error_line": next((line.strip() for line in blob.splitlines()
                                if "ERROR" in line), None),
            "ok": code == 0 and iters is not None and int(iters.group(2)) > 0,
        })
        print(f"  lj {case.name}: exit={code} elements={symbols} "
              f"steps={runs[-1]['minimisation_steps']} "
              f"forces={runs[-1]['force_evaluations']} "
              f"E={runs[-1]['energy_initial']}->{runs[-1]['energy_final']} "
              f"err={runs[-1]['error_line']}", flush=True)
    out["lj_minimise"] = runs
    return out


def probe_gromacs() -> dict:
    gmx = shutil.which("gmx") or shutil.which("gmx_mpi")
    out: dict = {"binary": gmx}
    if not gmx:
        return out
    proc = subprocess.run([gmx, "--version"], capture_output=True, text=True, timeout=120)
    out["version"] = ((proc.stdout or "") + (proc.stderr or "")).splitlines()[:1]
    ffs = []
    for root in ("/usr/share/gromacs/top",):
        base = Path(root)
        if base.is_dir():
            ffs = sorted(path.name for path in base.glob("*.ff"))
    out["forcefields"] = ffs[:20]
    # can pdb2gmx build a topology for our chemistry?  (expect: no, metals)
    case = next((path for path in Path("cases/batch").glob("gromacs__*")), None)
    if case:
        work = Path("gmx_run")
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        for source in case.iterdir():
            if source.is_file():
                shutil.copy2(source, work / source.name)
        proc = subprocess.run([gmx, "pdb2gmx", "-f", "conf.gro", "-o", "out.gro",
                               "-p", "out.top", "-ff", "amber99sb", "-water", "none",
                               "-ignh"],
                              cwd=str(work), capture_output=True, text=True, timeout=300)
        blob = (proc.stdout or "") + (proc.stderr or "")
        (work / "pdb2gmx.log").write_text(blob, encoding="utf-8")
        out["pdb2gmx_exit"] = proc.returncode
        out["pdb2gmx_error"] = next((line.strip() for line in blob.splitlines()
                                     if "Fatal error" in line or "not found" in line), None)
        print(f"  pdb2gmx exit={proc.returncode} err={out['pdb2gmx_error']}", flush=True)
    return out


def main() -> None:
    payload: dict = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "placeholder": PLACEHOLDER}
    if apt("lammps"):
        payload["lammps"] = probe_lammps()
    if apt("gromacs"):
        payload["gromacs"] = probe_gromacs()
    Path("realphysics_probe.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
    print("PROBE_DONE")


if __name__ == "__main__":
    main()
