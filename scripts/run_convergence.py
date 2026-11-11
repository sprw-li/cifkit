"""Convergence-study runner: generate a sweep, run it (if a binary exists), analyse.

    .venv\\Scripts\\python.exe scripts\\run_convergence.py --code nwchem \
        --input cloud_h3/cases/mol_small.nw --values 20,30,40,50 [--json OUT]

Without a local binary the sweep is still generated and the report says plainly
that nothing ran (the same inputs can be dispatched through the cloud fan-out).
Exit code is 0 when the study ran or was honestly reported as not-run; 1 only on a
malformed request.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BINARIES = {"nwchem": ("nwchem",), "vasp": ("vasp_std", "vasp_gam", "vasp"),
            "qe": ("pw.x",), "cp2k": ("cp2k.psmp", "cp2k.popt", "cp2k")}
COMMANDS = {"nwchem": "{binary} {input}", "qe": "{binary} -in {input}",
            "cp2k": "{binary} -i {input}", "vasp": "{binary}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True, choices=sorted(BINARIES))
    ap.add_argument("--input", required=True)
    ap.add_argument("--values", default=None, help="逗号分隔的取值（默认用内置序列）")
    ap.add_argument("--threshold", type=float, default=None,
                    help="收敛阈值（默认 1e-3 eV 或 1e-4 Ry）")
    ap.add_argument("--per-atom", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=1800.0)
    ap.add_argument("--workdir", default=str(ROOT / "runs" / "convergence"))
    ap.add_argument("--json", default=str(ROOT / "runs" / "convergence" / "report.json"))
    args = ap.parse_args()

    from cifkit.export.convergence import (SWEEPS, Sample, analyse, parse_energy,
                                           render_markdown, sweep)

    source = Path(args.input)
    if not source.is_file():
        print(f"error: input not found: {source}")
        return 1
    text = source.read_text(encoding="utf-8")
    values = [float(token) for token in args.values.split(",")] if args.values else None
    variants = sweep(args.code, text, values)
    threshold = args.threshold if args.threshold is not None else (
        1e-4 if args.code in ("qe", "cp2k") else 1e-3)

    workdir = Path(args.workdir) / args.code
    if workdir.is_dir():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    binary = next((shutil.which(name) for name in BINARIES[args.code]
                   if shutil.which(name)), None)
    report: dict = {"code": args.code, "input": str(source), "binary": binary,
                    "values": [value for value, _ in variants], "ran": bool(binary),
                    "samples": [], "threshold": threshold}
    samples: list[Sample] = []
    if binary is None:
        for value, variant in variants:
            target = workdir / f"input_{value:g}"
            target.write_text(variant, encoding="utf-8")
            samples.append(Sample(value, None, False, "not run: no local binary"))
        print(f"{args.code}: no local binary; wrote {len(variants)} inputs to {workdir}")
    else:
        for value, variant in variants:
            target = workdir / f"input_{value:g}"
            target.write_text(variant, encoding="utf-8")
            command = COMMANDS[args.code].format(binary=binary, input=target.name)
            started = time.time()
            try:
                proc = subprocess.run(command.split(), cwd=str(workdir), capture_output=True,
                                      text=True, encoding="utf-8", errors="replace",
                                      timeout=args.timeout)
                blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
                energy = parse_energy(blob)
                ok = energy is not None
                samples.append(Sample(value, energy, ok,
                                      "ok" if ok else f"no energy in output (exit {proc.returncode})"))
                (workdir / f"output_{value:g}.log").write_text(blob, encoding="utf-8")
            except subprocess.TimeoutExpired:
                samples.append(Sample(value, None, False, f"timeout after {args.timeout}s"))
            print(f"  {value:g}: {samples[-1].energy} ({samples[-1].detail})")

    verdict = analyse(args.code, samples, threshold, per_atom=args.per_atom)
    report.update(verdict.as_dict())
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = workdir / "convergence.md"
    markdown.write_text(render_markdown(verdict, title=f"{args.code} ({source.name})"),
                        encoding="utf-8")
    print(f"\n{verdict.note}\nreport: {out}\nmarkdown: {markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
