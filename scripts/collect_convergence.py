#!/usr/bin/env python3
"""Collect a per-cutoff cloud sweep into one convergence report (round 48).

Each job writes its own directory (``cut_<value>/nwchem.out``) because a killed batch
job produces no archive; this script walks those directories and parses every output
with :func:`cifkit.export.convergence.parse_energy`, so the analysis does not depend
on whatever regex the *container* had at the time.

    .venv\\Scripts\\python.exe scripts\\collect_convergence.py \\
        --root runs/cloud_h3 --pattern 'conv_c*' --code nwchem --threshold 1e-3
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(ROOT / "runs" / "cloud_h3"))
    ap.add_argument("--pattern", default="conv_c*")
    ap.add_argument("--code", default="nwchem")
    ap.add_argument("--output-name", default="nwchem.out")
    ap.add_argument("--threshold", type=float, default=1e-3)
    ap.add_argument("--per-atom", type=int, default=16)
    ap.add_argument("--job-prefix", default="cut_")
    ap.add_argument("--json", default=str(ROOT / "runs" / "convergence" / "nwchem_report.json"))
    ap.add_argument("--markdown", default=None)
    args = ap.parse_args()

    from cifkit.export.convergence import Sample, analyse, parse_energy, render_markdown

    samples: list[Sample] = []
    sources: list[str] = []
    for job_dir in sorted(Path(args.root).glob(args.pattern)):
        candidates = sorted(job_dir.glob(f"{args.job_prefix}*/{args.output_name}"))
        if not candidates:
            # job may have nested the case one level differently
            candidates = sorted(job_dir.rglob(args.output_name))
        for output in candidates[:2]:
            value = None
            match = re.match(rf"{re.escape(args.job_prefix)}(\S+)", output.parent.name)
            if match:
                try:
                    value = float(match.group(1))
                except ValueError:
                    value = None
            text = output.read_text(encoding="utf-8", errors="replace")
            energy = parse_energy(text)
            status = "ok" if energy is not None else "no-energy"
            if value is None:
                continue
            samples.append(Sample(value=value, energy=energy, ok=energy is not None,
                                  detail=f"status={status} from {job_dir.name}/{output.parent.name}"))
            try:
                sources.append(str(output.resolve().relative_to(ROOT)))
            except ValueError:
                sources.append(str(output))

    if not samples:
        print(f"no outputs matched {args.pattern}/{args.job_prefix}* in {args.root}")
        return 1

    report = analyse(args.code, samples, args.threshold, per_atom=args.per_atom)
    payload = report.as_dict()
    payload["when"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    payload["sources"] = sources
    payload["per_atom"] = args.per_atom
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = Path(args.markdown or out.with_suffix(".md"))
    markdown.write_text(render_markdown(report, title=f"{args.code} cutoff (cloud sweep)"),
                        encoding="utf-8")
    print(f"samples={len(samples)} usable={sum(1 for s in samples if s.ok)} "
          f"converged_at={report.converged_at}")
    print(report.note)
    for sample in report.samples:
        print(f"  cutoff {sample.value:g}: {sample.energy} ({sample.detail})")
    print(f"report: {out}\nmarkdown: {markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
