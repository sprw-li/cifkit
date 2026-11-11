#!/usr/bin/env python3
"""Which LAMMPS force fields does this build actually have? (round 56)

The previous acceptance run used ``pair_style zero``, i.e. **zero force evaluations**
- it proved the file parses, nothing more.  Real physics needs a real force field, so
this probes:

* which ``pair_style`` point styles the binary supports (``uff``? ``lj/cut``? ...);
* whether ``pair_style uff`` can minimise our exported data file (real energies);
* the same question for GROMACS (does it have a force field it can apply?).

Prints one line per probe and writes ``forcefield_probe.json``.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path


def apt_install(package: str) -> bool:
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    proc = subprocess.run(
        ["bash", "-lc", f"export DEBIAN_FRONTEND=noninteractive; apt-get update -qq && "
                       f"apt-get install -y -qq --no-install-recommends {package}"],
        capture_output=True, text=True, env=env, timeout=1800)
    print(f"apt {package}: exit={proc.returncode}", flush=True)
    return proc.returncode == 0


def probe_lammps() -> dict:
    binary = shutil.which("lmp") or shutil.which("lmp_mpi")
    result: dict = {"binary": binary, "styles": [], "uff_minimise": None}
    if not binary:
        return result
    # ask the binary to print its styles
    proc = subprocess.run([binary, "-h"], capture_output=True, text=True, timeout=300)
    blob = (proc.stdout or "") + (proc.stderr or "")
    section = re.search(r"Pair styles:(.*?)\n\n", blob, re.S)
    if section:
        result["styles"] = [token for token in section.group(1).split()
                            if token in ("uff", "zero", "lj/cut", "eam/alloy", "reaxff",
                                         "tersoff", "buck", "coul/long", "meam")]
    print(f"lammps {binary}; pair styles found: {result['styles']}", flush=True)

    # real calculation: minimise our exported file with pair_style uff
    cases = sorted(path for path in Path("cases/batch").glob("lammps__*") if path.is_dir())
    runs = []
    for case in cases[:3]:
        work = Path("uff_run") / case.name
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        for source in case.iterdir():
            if source.is_file():
                shutil.copy2(source, work / source.name)
        data = (work / "data.lammps").read_text(encoding="utf-8")
        species = sorted(set(re.findall(r"^#\s*type\s+(\d+)\s*->\s*([A-Z][a-z]?)\s*:",
                                       data, re.M)) or [])
        elements = sorted({symbol for _number, symbol in species})
        if not elements:
            elements = sorted(set(re.findall(r"\b([A-Z][a-z]?)\b", data.split("Masses")[1]
                                             .split("\n\n")[0]))) if "Masses" in data else []
        typed = " ".join(symbol for _number, symbol in species) or " ".join(elements)
        script = f"""# real force field: UFF has parameters for every element
units           metal
atom_style      atomic
boundary        p p p
read_data       data.lammps
pair_style      uff
pair_coeff      * * {typed}
thermo          1
min_style       cg
minimize        1e-4 1e-6 50 500
"""
        (work / "in.uff").write_text(script, encoding="utf-8")
        started = time.time()
        try:
            proc = subprocess.run([binary, "-in", "in.uff"], cwd=str(work),
                                  capture_output=True, text=True, timeout=1200)
            blob = (proc.stdout or "") + (proc.stderr or "")
            code = proc.returncode
        except subprocess.TimeoutExpired as exc:
            blob, code = str(exc), "timeout"
        (work / "uff.log").write_text(blob, encoding="utf-8")
        energies = re.findall(r"^\s*(\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)",
                              blob, re.M)
        iters = re.search(r"Iterations, force evaluations = (\d+) (\d+)", blob)
        ok = "ERROR" not in blob and iters is not None
        runs.append({"case": case.name, "exit": code, "elements": elements,
                     "force_evaluations": int(iters.group(2)) if iters else 0,
                     "minimisation_steps": int(iters.group(1)) if iters else 0,
                     "steps_recorded": len(energies),
                     "final_energy": float(energies[-1][3]) if energies else None,
                     "seconds": round(time.time() - started, 1), "ok": ok})
        print(f"  uff {case.name}: exit={code} ok={ok} "
              f"steps={runs[-1]['minimisation_steps']} "
              f"forces={runs[-1]['force_evaluations']} "
              f"E={runs[-1]['final_energy']}", flush=True)
    result["uff_minimise"] = runs
    return result


def main() -> None:
    payload: dict = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if apt_install("lammps"):
        payload["lammps"] = probe_lammps()
    if apt_install("gromacs"):
        gmx = shutil.which("gmx") or shutil.which("gmx_mpi")
        payload["gromacs_binary"] = gmx
        if gmx:
            proc = subprocess.run([gmx, "--version"], capture_output=True, text=True,
                                  timeout=300)
            blob = (proc.stdout or "") + (proc.stderr or "")
            forced = re.search(r"GROMACS version:\s*(\S+)", blob)
            payload["gromacs_version"] = forced.group(1) if forced else None
            # is there a force field shipped with the package?
            ffs = []
            for root in ("/usr/share/gromacs/top", "/usr/share/gromacs"):
                base = Path(root)
                if base.is_dir():
                    ffs = sorted(path.name for path in base.glob("*.ff"))
                    break
            payload["gromacs_forcefields"] = ffs[:12]
            print(f"gromacs {payload.get('gromacs_version')}; force fields: {ffs[:6]}",
                  flush=True)
    Path("forcefield_probe.json").write_text(json.dumps(payload, ensure_ascii=False,
                                                        indent=2), encoding="utf-8")
    print("PROBE_DONE")


if __name__ == "__main__":
    main()
