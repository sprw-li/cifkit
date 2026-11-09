"""Famous-MOF / topology coverage matrix for the bundled dataset (round 23).

Answers, with evidence, the question "what do we actually have?":

1. **which topologies are present** in the CoRE MOF 2024 index (and how often);
2. **which of them we can verify offline** — only the nets bundled in
   ``cifkit/data/nets`` have a reference, so everything else is "present but
   unverifiable here" (an honest gap, not a silent success);
3. **a real round trip per bundled net**: pull an example entry from the archive,
   run ``cifkit.topology.verify``, and record the result.

    .venv\\Scripts\\python.exe scripts\\coverage_matrix.py [--json OUT] [--markdown OUT]

Writes ``runs/coverage_matrix.json`` and (with ``--markdown``) a table that
``docs/COVERAGE.md`` embeds.  Nothing here is a claim about MOF naming: names are
mostly absent in this dataset, so the *topology token* and the structure itself are
the handles.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: topologies worth reporting: the bundled references + common MOF nets
INTERESTING = ["sod", "pcu", "dia", "fcu", "tbo", "bcu", "mtn", "csq", "rht", "hcb",
               "bct", "pts", "nbo", "sql", "kgd", "crb", "srs", "tfz-d", "rna"]

#: which MOF families are (approximately) represented by which net
FAMILIES = {
    "ZIF-8 / ZIF-67": "sod",
    "MOF-5 / IRMOF-1": "pcu",
    "HKUST-1 (Cu-BTC)": "tbo",
    "UiO-66 / UiO-67 / Zr-MOFs": "fcu",
    "MOF-74 / CPO-27 (1D rods)": "hcb (rod SBU; often 'unnamed')",
    "MIL-101 / MIL-100": "mtn",
    "PCN-222 / NU-1000": "csq (not in the bundled reference set)",
    "diamondoid MOFs (e.g. COF-300-like)": "dia",
    "NbO-type (NOTT-100 family)": "nbo",
}


def bundled_nets(reference_dir: Path) -> list[str]:
    """Net names that ship a reference CIF under ``cifkit/data/nets``."""
    return sorted(p.stem.replace("-reference", "") for p in reference_dir.glob("*-reference.cif"))


def topology_counts(entries: dict) -> dict[str, Counter]:
    """Count topology values per column (missing → ``"-"``). Pure function."""
    return {
        "allnodes": Counter((e.get("topology_allnodes") or "-") for e in entries.values()),
        "singlenodes": Counter((e.get("topology_singlenodes") or "-") for e in entries.values()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(ROOT / "runs" / "coverage_matrix.json"))
    ap.add_argument("--markdown", default=None)
    args = ap.parse_args()

    from cifkit.sources.core_mof import build_index

    data = build_index()
    entries = data["entries"]
    archive_path = ROOT / "_cache" / "core-mof-2024" / "CoREMOF2024DB.zip"

    counts = topology_counts(entries)
    counts_allnodes, counts_singlenodes = counts["allnodes"], counts["singlenodes"]

    reference_dir = ROOT / "cifkit" / "data" / "nets"
    bundled = bundled_nets(reference_dir)

    report: dict = {
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "n_entries": len(entries),
        "bundled_reference_nets": bundled,
        "topology_presence": {name: {"allnodes": counts_allnodes.get(name, 0),
                                     "singlenodes": counts_singlenodes.get(name, 0),
                                     "verifiable_offline": name in bundled}
                              for name in INTERESTING},
        "family_map": FAMILIES,
        "examples": [],
    }

    if archive_path.is_file():
        from pymatgen.core import Structure
        from cifkit.topology import verify

        with zipfile.ZipFile(archive_path) as zf:
            members = zf.namelist()
            for net in bundled:
                candidates = [m for m in members
                              if m.endswith(".cif") and f"[{net}]" in m]
                row: dict = {"net": net, "candidates": len(candidates)}
                if not candidates:
                    row["status"] = "no example in the archive"
                    report["examples"].append(row)
                    print(f"{net:5s} no example")
                    continue
                member = sorted(candidates, key=len)[0]
                row["example"] = member
                try:
                    with tempfile.NamedTemporaryFile("wb", suffix=".cif", delete=False) as handle:
                        handle.write(zf.read(member))
                        path = handle.name
                    structure = Structure.from_file(path)
                    Path(path).unlink(missing_ok=True)
                    result = verify(structure, net)
                    row.update({"n_atoms": len(structure), "verified": bool(result.get("ok")),
                                "signature": result.get("signature") or result.get("observed"),
                                "detail": str(result.get("detail") or result.get("note") or "")[:200]})
                    row["status"] = "verified" if result.get("ok") else "MISMATCH"
                except Exception as exc:  # noqa: BLE001
                    row["status"] = f"error: {type(exc).__name__}: {exc}"
                report["examples"].append(row)
                print(f"{net:5s} {row['status']:22s} {member}")
    else:
        report["examples_note"] = f"archive not present: {archive_path}"

    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {out}")

    if args.markdown:
        lines = ["| topology | entries (allnodes) | bundled reference? | example verify |",
                 "|---|---|---|---|"]
        for net in INTERESTING:
            info = report["topology_presence"][net]
            example = next((e for e in report["examples"] if e["net"] == net), None)
            status = example["status"] if example else "-"
            lines.append(f"| `{net}` | {info['allnodes']} | "
                         f"{'yes' if info['verifiable_offline'] else 'no'} | {status} |")
        md = Path(args.markdown)
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"markdown: {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
