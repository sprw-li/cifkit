#!/usr/bin/env python3
"""Cloud convergence study: NWChem plane-wave cutoff on our own periodic template.

Round 45 (limitation E3).  Runs the *shipped* NWChem periodic pattern
(``nwpw`` + ``cutoff`` + ``xc pbe`` + ``task pspw energy``) at several cutoffs in one
batch job and prints one machine-readable line per cutoff:

    CONVERGENCE value=<cutoff> energy=<hartree> status=<ok|no-energy> seconds=<t>

The local ``cifkit.export.convergence`` module parses these lines, so the study can
be analysed and committed as evidence rather than as a screenshot.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_CUTOFFS = "20,30,40"
CUTOFFS = [float(value) for value in
           os.environ.get("CUTOFFS", DEFAULT_CUTOFFS).split(",")]


def _parse_argv() -> list[float]:
    """``--cutoffs 20,30`` overrides ``$CUTOFFS`` (one job per value is safest)."""
    argv = sys.argv[1:]
    for index, token in enumerate(argv):
        if token == "--cutoffs" and index + 1 < len(argv):
            return [float(value) for value in argv[index + 1].split(",")]
        if token.startswith("--cutoffs="):
            return [float(value) for value in token.split("=", 1)[1].split(",")]
    return CUTOFFS


def memory_directive(fraction: float = 0.6) -> str:
    """NWChem's heap defaults to **zero**: without this the SCF aborts immediately.

    Evidence: the round-45 job (id 4f204600..., 5/5 cutoffs) died with
    ``electron_init: out of heap memory 0``.  NWChem also requires the parts to add
    up (``total = stack + heap + global``), otherwise it reports
    "Inconsistent memory specification".
    """
    total_mb = 8192
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    total_mb = int(line.split()[1]) // 1024
                    break
    except OSError:
        pass
    fraction = float(os.environ.get("MEMORY_FRACTION", fraction))
    total = max(1024, int(total_mb * fraction))
    stack = max(200, total // 12)
    heap = max(512, int((total - stack) * 0.45))
    global_mem = total - stack - heap
    return (f"memory total {total} mb stack {stack} mb "
            f"heap {heap} mb global {global_mem} mb")
DEFAULT_INPUT = Path("cases/mol_small.nw")
ENERGY = re.compile(r"Total (?:DFT|PSPW)?\s*energy\s*=\s*(-?\d+\.\d+)")


def main() -> None:
    cutoffs = _parse_argv()
    source = DEFAULT_INPUT
    if not source.is_file():
        raise SystemExit(f"input not found: {source}")
    template = source.read_text(encoding="utf-8")
    template = memory_directive() + "\n" + template
    print(f"memory directive: {template.splitlines()[0]}", flush=True)

    binary = shutil.which("nwchem")
    if binary is None and os.environ.get("SKIP_INSTALL") != "1":
        print("nwchem missing: installing the Debian package (network needed)", flush=True)
        started = time.time()
        proc = subprocess.run(
            ["bash", "-lc",
             "export DEBIAN_FRONTEND=noninteractive; "
             "apt-get update -qq && apt-get install -y -qq --no-install-recommends nwchem"],
            capture_output=True, text=True, timeout=2400)
        print(f"apt-get exit={proc.returncode} in {time.time() - started:.0f}s", flush=True)
        if proc.returncode != 0:
            print((proc.stdout or "")[-1500:])
            print((proc.stderr or "")[-1500:])
        binary = shutil.which("nwchem")
    print(f"nwchem binary: {binary}", flush=True)
    if binary is None:
        raise SystemExit("nwchem unavailable (not installed and could not install)")

    results = []
    for cutoff in cutoffs:
        workdir = Path(f"cut_{cutoff:g}")
        workdir.mkdir(exist_ok=True)
        text = re.sub(r"(?m)^(\s*)cutoff\s+\S+\s*$", rf"\g<1>cutoff {cutoff:g}", template, count=1)
        target = workdir / "mol.nw"
        target.write_text(text, encoding="utf-8")
        started = time.time()
        proc = subprocess.run([binary, target.name], cwd=str(workdir), capture_output=True,
                              text=True, timeout=5400)
        blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
        (workdir / "nwchem.out").write_text(blob, encoding="utf-8")
        match = ENERGY.search(blob)
        energy = float(match.group(1)) if match else None
        status = "ok" if energy is not None else "no-energy"
        print(f"CONVERGENCE value={cutoff:g} energy={energy if energy is not None else 'nan'} "
              f"status={status} seconds={time.time() - started:.1f}", flush=True)
        results.append({"value": cutoff, "energy": energy, "status": status,
                        "exit": proc.returncode})
        # checkpoint after every cutoff: a killed job must still leave evidence
        Path("convergence_raw.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    Path("convergence_raw.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("CONVERGENCE_DONE", len(results))


if __name__ == "__main__":
    main()
