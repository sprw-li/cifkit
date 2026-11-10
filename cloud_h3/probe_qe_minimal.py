#!/usr/bin/env python3
"""Is `pw.x` usable at all in this image? Run a canonical minimal input (round 33).

Our exported QE input aborts with ``*** buffer overflow detected ***`` (SIGABRT) in
``__snprintf_chk`` right after the program banner — a known QE 6.7-on-new-glibc
fortify incompatibility rather than a chemistry error.  To separate "the binary is
broken here" from "our input is wrong", this probe runs:

* A — a canonical minimal QE input written by hand (H2O, the same UPFs);
* B — our exported input, sanitised.

and reports each one independently.  Writes ``qe_minimal.json``.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PSEUDO_DIR = "/usr/share/espresso/pseudo"

CANONICAL = """&CONTROL
  calculation = 'scf'
  prefix = 'minimal'
  outdir = './tmp'
  pseudo_dir = '/usr/share/espresso/pseudo'
/
&SYSTEM
  ibrav = 0
  nat = 3
  ntyp = 2
  ecutwfc = 30.0
/
&ELECTRONS
  conv_thr = 1.0d-4
  electron_maxstep = 30
/
ATOMIC_SPECIES
  O 15.999 O.pbe-rrkjus.UPF
  H 1.008  H.pbe-kjpaw.UPF
CELL_PARAMETERS angstrom
  10.0 0.0 0.0
  0.0 10.0 0.0
  0.0 0.0 10.0
ATOMIC_POSITIONS angstrom
  O 5.0 5.0 5.0
  H 5.757 5.586 5.0
  H 4.243 5.586 5.0
K_POINTS gamma
"""


def run_case(name: str, text: str, report: dict) -> None:
    workdir = Path("/tmp") / f"qe_{name}"
    workdir.mkdir(parents=True, exist_ok=True)
    target = workdir / "run.in"
    target.write_text(text, encoding="utf-8")
    started = time.time()
    proc = subprocess.run(["pw.x", "-in", str(target)], cwd=workdir, capture_output=True,
                          text=True, timeout=3600)
    blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    row = {"case": name, "exit": proc.returncode,
           "seconds": round(time.time() - started, 1),
           "job_done": "JOB DONE" in blob,
           "abort": "SIGABRT" in blob or "buffer overflow" in blob,
           "tail": blob[-1200:]}
    report["cases"].append(row)
    print(f"[{name}] exit={row['exit']} job_done={row['job_done']} abort={row['abort']} "
          f"({row['seconds']}s)")


def main() -> int:
    report: dict = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "pw": shutil.which("pw.x"),
                    "pseudo_present": {}, "cases": [], "errors": []}
    for upf in ("O.pbe-rrkjus.UPF", "H.pbe-kjpaw.UPF", "C.pbe-rrkjus.UPF"):
        report["pseudo_present"][upf] = (Path(PSEUDO_DIR) / upf).is_file()
    if not shutil.which("pw.x"):
        report["errors"].append("pw.x missing")
        Path("qe_minimal.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
        return 0

    run_case("canonical", CANONICAL, report)

    exported = HERE / "cases" / "qe_export.in"
    if exported.is_file():
        text = exported.read_text(encoding="utf-8")
        text = text.replace("&CONTROL\n/", f"&CONTROL\n  calculation='scf'\n  prefix='exp'\n"
                                           f"  outdir='./tmp'\n  pseudo_dir='{PSEUDO_DIR}'\n/", 1)
        text = re.sub(r"&SYSTEM\n/", "&SYSTEM\n  ecutwfc=30.0\n/", text, count=1)
        text = re.sub(r"&ELECTRONS\n/", "&ELECTRONS\n  conv_thr=1.0d-4\n  electron_maxstep=30\n/",
                      text, count=1)
        for card in ("&IONS", "&CELL", "&FCP", "&RISM"):
            text = re.sub(rf"{card}\s*\n\s*/\s*\n", "", text)
        text = text.replace("H 1.008 H.UPF", "H 1.008 H.pbe-kjpaw.UPF")
        text = text.replace("C 12.011 C.UPF", "C 12.011 C.pbe-rrkjus.UPF")
        text = text.replace("O 15.999 O.UPF", "O 15.999 O.pbe-rrkjus.UPF")
        run_case("exported", text, report)

    Path("qe_minimal.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    print("report written: qe_minimal.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
