"""Audit dataset coverage: ask the bundled CoRE MOF index what it actually has.

Written for limitation C2 (MIL-101 was "not verified" — now it is *verified absent*)
and generally useful whenever you need to know whether a MOF family is in the
local dataset before promising it.

Search handles, in order:

1. **name / CSD refcode / DOI / coreid** (substring, case-insensitive);
2. **formula fingerprint** (``--formula`` like ``Cr>=3,F>=1,C>=20``);
3. **largest unit cells** for a given element (``--largest Cr``).

    .venv\\Scripts\\python.exe scripts\\audit_dataset_coverage.py --name MIL-101 --name OCUNAC
    .venv\\Scripts\\python.exe scripts\\audit_dataset_coverage.py --formula "Cr>=3,F>=1,C>=20"
    .venv\\Scripts\\python.exe scripts\\audit_dataset_coverage.py --largest Cr --limit 10
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def composition(formula: str | None) -> Counter:
    return Counter({el: float(n) for el, n in re.findall(r"([A-Z][a-z]?)([0-9.]+)", formula or "")})


def parse_fingerprint(text: str) -> list[tuple[str, str, float]]:
    """Parse ``"Cr>=3,F>=1,C>=20"`` into [(element, op, value), ...]."""
    out = []
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        match = re.fullmatch(r"([A-Z][a-z]?)\s*(>=|<=|>|<|=)\s*([0-9.]+)", chunk)
        if not match:
            raise ValueError(f"bad fingerprint item: {chunk!r} (expected e.g. Cr>=3)")
        element, op, value = match.group(1), match.group(2), float(match.group(3))
        out.append((element, op, value))
    return out


def matches(fp: list[tuple[str, str, float]], comp: Counter) -> bool:
    for element, op, value in fp:
        actual = comp.get(element, 0.0)
        if op == ">=" and not actual >= value:
            return False
        if op == "<=" and not actual <= value:
            return False
        if op == ">" and not actual > value:
            return False
        if op == "<" and not actual < value:
            return False
        if op == "=" and not abs(actual - value) < 1e-9:
            return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", action="append", default=[], help="substring of name/refcode/doi")
    ap.add_argument("--formula", default=None, help="fingerprint, e.g. 'Cr>=3,F>=1,C>=20'")
    ap.add_argument("--largest", default=None, help="show the largest cells containing this element")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--json", default=str(ROOT / "runs" / "dataset_coverage.json"))
    args = ap.parse_args()

    from cifkit.sources.core_mof import build_index

    index = build_index()
    entries = index["entries"]
    report: dict = {"n_entries": len(entries), "queries": {}, "results": {}}
    print(f"CoRE MOF index: {len(entries)} entries "
          f"({sum(1 for e in entries.values() if (e.get('name') or '').strip())} with a name)")

    if args.name:
        for needle in args.name:
            hits = []
            for key, entry in entries.items():
                blob = " ".join(str(entry.get(f) or "") for f in
                                ("name", "refcode", "coreid", "doi")).lower()
                if needle.lower() in blob or needle.lower() in key.lower():
                    hits.append({"key": key, "name": entry.get("name"),
                                 "refcode": entry.get("refcode"),
                                 "formula": entry.get("formula"), "natoms": entry.get("natoms")})
            report["results"][f"name:{needle}"] = hits
            print(f"  name/refcode {needle!r}: {len(hits)} hits")
            for hit in hits[: args.limit]:
                print(f"     {hit['key']}  {hit['refcode']}  {hit['formula']}")

    if args.formula:
        fingerprint = parse_fingerprint(args.formula)
        hits = [{"key": k, "formula": e.get("formula"), "natoms": e.get("natoms"),
                 "name": e.get("name"), "refcode": e.get("refcode"),
                 "topology": e.get("topology_allnodes")}
                for k, e in entries.items()
                if matches(fingerprint, composition(e.get("formula")))]
        hits.sort(key=lambda row: -(row["natoms"] or 0))
        report["results"][f"formula:{args.formula}"] = hits
        print(f"  formula {args.formula}: {len(hits)} hits")
        for hit in hits[: args.limit]:
            print(f"     {hit['key']}  {hit['formula']}  natoms={hit['natoms']}")

    if args.largest:
        hits = sorted(
            ({"key": k, "formula": e.get("formula"), "natoms": e.get("natoms"),
              "name": e.get("name"), "topology": e.get("topology_allnodes")}
             for k, e in entries.items()
             if args.largest in composition(e.get("formula"))),
            key=lambda row: -(row["natoms"] or 0),
        )[: args.limit]
        report["results"][f"largest:{args.largest}"] = hits
        print(f"  largest cells containing {args.largest}: {len(hits)}")
        for hit in hits:
            print(f"     {hit['key']}  {hit['formula']}  natoms={hit['natoms']}")

    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
