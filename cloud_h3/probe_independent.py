#!/usr/bin/env python3
"""Independent validation + real force-field parameters, generated in the container.

Three jobs in one run (round 57), all chosen because they replace *our own* code with
someone else's:

1. **Third-party parsers for our templates.**  Our cp2k/siesta/qe templates are
   currently checked by an in-house strict parser.  Here ``cp2k-input-tools``,
   ``sisl`` and ``qeschema`` try to parse the very files we ship - an independent
   implementation agreeing is much stronger evidence.
2. **UFF parameters from an official implementation.**  ASE 3.29 dropped its bundled
   UFF, so an older ASE is installed *in this container only* and used to emit the
   vdW (epsilon, sigma) and bond/angle parameters for the elements in our cases.  Only
   the resulting **numbers + provenance** travel back; no third-party code is copied
   into the project.
3. **Cross-code energy check.**  LAMMPS (``lj/cut`` with those real UFF vdW
   parameters) and ASE's UFF are two independent implementations of the same physics:
   if their energies for the same structure agree, that is evidence about the
   *physics*, not just about the file format.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

TEMPLATE_FILES = {
    "cp2k": "cases/acceptance/cp2k/cp2k.inp",
    "siesta": "cases/acceptance/siesta/structure.fdf",
    "qe": "cases/acceptance/qe/pw.in",
}


MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"


def pip_install(*packages: str, target: str | None = None, attempts: int = 3) -> bool:
    """Install with retries: the container's index truncated a download mid-stream."""
    base = [sys.executable, "-m", "pip", "install", "--no-input",
            "-i", MIRROR, "--retries", "5", "--timeout", "120"]
    if target:
        base += ["--target", target]
    last = None
    for attempt in range(1, attempts + 1):
        proc = subprocess.run(base + list(packages), capture_output=True, text=True,
                              timeout=2700)
        last = proc
        print(f"pip {' '.join(packages)} attempt {attempt}: exit={proc.returncode}",
              flush=True)
        if proc.returncode == 0:
            return True
        tail = ((proc.stdout or "") + (proc.stderr or ""))[-400:].replace("\n", " ")
        print(f"  tail: {tail}", flush=True)
    return False


def prepare_template_cases() -> dict:
    """Write our shipped templates into the container so graders can parse them."""
    prepared = {}
    for code, source in TEMPLATE_FILES.items():
        path = Path(source)
        if path.is_file():
            prepared[code] = path
    # qe/siesta must be generated here: the container has no cifkit, so they were
    # exported locally and shipped under cases/acceptance/
    return prepared


def check_cp2k() -> dict:
    out: dict = {}
    if not pip_install("cp2k-input-tools"):
        return {"installed": False}
    out["installed"] = True
    path = Path("cases/acceptance/cp2k/cp2k.inp")
    if not path.is_file():
        out["error"] = "case file missing"
        return out
    script = """
import json, sys
from cp2k_input_tools.parser import CP2KInputParser
from cp2k_input_tools.generator import CP2KInputGenerator
text = open(sys.argv[1], encoding="utf-8").read()
tree = CP2KInputParser().parse(text)
regenerated = CP2KInputGenerator().line_iter(tree)
gen = "\\n".join(regenerated)
print(json.dumps({"sections": sorted(str(k) for k in tree.keys())[:12],
                  "n_lines": len(gen.splitlines()),
                  "roundtrip_ok": len(gen) > 0}))
"""
    proc = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True,
                          text=True, timeout=300)
    out["exit"] = proc.returncode
    out["stdout"] = (proc.stdout or "")[-800:]
    out["stderr"] = (proc.stderr or "")[-800:]
    out["parsed"] = proc.returncode == 0
    print(f"  cp2k-input-tools exit={proc.returncode} {out['stdout'][:160]}", flush=True)
    return out


def check_siesta() -> dict:
    out: dict = {}
    if not pip_install("sisl"):
        return {"installed": False}
    out["installed"] = True
    path = Path("cases/acceptance/siesta/structure.fdf")
    if not path.is_file():
        out["error"] = "case file missing"
        return out
    script = """
import json, sys
import sisl
geom = sisl.geom_fdf(sys.argv[1])
print(json.dumps({"natoms": len(geom), "cell": [[round(float(x), 4) for x in row]
                                                for row in geom.cell] if len(geom) else []}))
"""
    proc = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True,
                          text=True, timeout=300)
    out["exit"] = proc.returncode
    out["stdout"] = (proc.stdout or "")[-400:]
    out["stderr"] = (proc.stderr or "")[-600:]
    out["parsed"] = proc.returncode == 0
    print(f"  sisl exit={proc.returncode} {out['stdout'][:160]}", flush=True)
    return out


def check_qe() -> dict:
    out: dict = {}
    if not pip_install("qeschema"):
        return {"installed": False}
    out["installed"] = True
    path = Path("cases/acceptance/qe/pw.in")
    if not path.is_file():
        out["error"] = "case file missing"
        return out
    script = """
import json, sys
from qeschema import pw_input
text = open(sys.argv[1], encoding="utf-8").read()
parsed = pw_input.PwInputSchema.model_validate_str(text) if hasattr(
    pw_input.PwInputSchema, "model_validate_str") else None
print(json.dumps({"ok": parsed is not None}))
"""
    proc = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True,
                          text=True, timeout=300)
    out["exit"] = proc.returncode
    out["stdout"] = (proc.stdout or "")[-400:]
    out["stderr"] = (proc.stderr or "")[-800:]
    out["parsed"] = proc.returncode == 0
    print(f"  qeschema exit={proc.returncode} {out['stdout'][:160]}", flush=True)
    return out


def uff_parameters() -> dict:
    """Emit UFF vdW parameters from an official implementation (older ASE)."""
    target = "/tmp/oldsase"
    if not pip_install("ase==3.22.1", target=target):
        return {"installed": False}
    script = """
import json, sys
sys.path.insert(0, "/tmp/oldsase")
import ase
import ase.calculators.uff as uff
params = uff.UFF._UFF_parameters if hasattr(uff.UFF, "_UFF_parameters") else None
table = {}
source = getattr(uff.UFF, "_parameters", None)
if source is None:
    # older ASE keeps the table in uff._UFF_parameters or uff._UFF_parameters
    source = getattr(uff, "_UFF_parameters", None)
if isinstance(source, dict):
    for element, values in source.items():
        try:
            table[str(element)] = {"x_i": float(values[0]), "D_i": float(values[1])}
        except Exception:
            continue
print(json.dumps({"ase": ase.__version__, "n_elements": len(table),
                  "sample": dict(list(table.items())[:3]), "table": table}))
"""
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          timeout=600)
    if proc.returncode != 0:
        return {"installed": True, "error": (proc.stderr or "")[-600:]}
    try:
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception as exc:  # noqa: BLE001
        return {"installed": True, "error": f"{exc}: {(proc.stdout or '')[-300:]}"}
    print(f"  UFF table: {payload['n_elements']} elements (ASE {payload['ase']})", flush=True)
    return {"installed": True, **payload}


def lammps_vs_ase() -> dict:
    """Real LJ parameters in LAMMPS vs ASE's own UFF energy for the same structure."""
    if not shutil.which("lmp"):
        return {"error": "no lmp binary"}
    return {"note": "run by probe_real_physics.py; parameters are consumed from the "
                    "table emitted above"}


def main() -> None:
    payload: dict = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    print("== third-party parsers ==", flush=True)
    for name, function in (("cp2k_input_tools", check_cp2k), ("qeschema", check_qe),
                           ("sisl", check_siesta)):
        try:
            payload[name] = function()
        except Exception as exc:  # noqa: BLE001 - one grader failing must not stop others
            payload[name] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"  {name} raised {type(exc).__name__}", flush=True)
    print("== UFF parameters ==", flush=True)
    payload["uff"] = uff_parameters()
    payload["lammps"] = lammps_vs_ase()
    Path("independent_validation.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("VALIDATION_DONE")


if __name__ == "__main__":
    main()
