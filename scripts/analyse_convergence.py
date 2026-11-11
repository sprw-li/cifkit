"""Analyse a fetched convergence job with cifkit's own convergence module.

    .venv\\Scripts\\python.exe scripts\\analyse_convergence.py \
        --log runs/cloud_h3/convergence2/log --code nwchem [--per-atom 16] [--json OUT]

Reads the ``CONVERGENCE value=… energy=… status=…`` lines the cloud script prints
(falling back to ``convergence_raw.json`` when the log was truncated), rebuilds
:class:`cifkit.export.convergence.Sample` objects, and writes the JSON + Markdown
convergence report that becomes the evidence for limitation E3.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINE = re.compile(r"CONVERGENCE value=(\S+) energy=(\S+) status=(\S+)"
                  r"(?: seconds=(\S+))?")


def read_samples(log_path: Path, raw_path: Path | None):
    from cifkit.export.convergence import Sample

    samples = []
    if log_path.is_file():
        for match in LINE.finditer(log_path.read_text(encoding="utf-8", errors="replace")):
            value, energy, status, seconds = match.groups()
            try:
                number = float(energy)
            except ValueError:
                number = None
            samples.append(Sample(value=float(value), energy=number, ok=status == "ok",
                                  detail=f"status={status}"
                                         + (f" seconds={seconds}" if seconds else "")))
    if not samples and raw_path is not None and raw_path.is_file():
        for row in json.loads(raw_path.read_text(encoding="utf-8")):
            samples.append(Sample(value=float(row["value"]), energy=row.get("energy"),
                                  ok=row.get("status") == "ok",
                                  detail=f"status={row.get('status')} exit={row.get('exit')}"))
    return samples


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--raw", default=None)
    ap.add_argument("--code", default="nwchem")
    ap.add_argument("--threshold", type=float, default=1e-3)
    ap.add_argument("--per-atom", type=int, default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--markdown", default=None)
    args = ap.parse_args()

    from cifkit.export.convergence import analyse, render_markdown

    log_path = Path(args.log)
    raw_path = Path(args.raw) if args.raw else log_path.parent / "convergence_raw.json"
    samples = read_samples(log_path, raw_path)
    if not samples:
        print(f"no CONVERGENCE lines in {log_path} (and no usable {raw_path})")
        return 1
    report = analyse(args.code, samples, args.threshold, per_atom=args.per_atom)
    payload = report.as_dict()
    payload["when"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    payload["source_log"] = str(log_path)
    out = Path(args.json or (ROOT / "runs" / "convergence" / f"{args.code}_report.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = Path(args.markdown or out.with_suffix(".md"))
    markdown.write_text(render_markdown(report, title=f"{args.code} cutoff"), encoding="utf-8")
    print(f"samples={len(samples)} usable={sum(1 for s in samples if s.ok)} "
          f"converged_at={report.converged_at}")
    print(report.note)
    print(f"report: {out}\nmarkdown: {markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
