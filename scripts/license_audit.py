"""Dependency licence audit for commercial reuse.

Reads installed distribution metadata and classifies each dependency as
permissive / weak-copyleft / strong-copyleft / unknown, because embedding this
workbench in a commercial (often closed-source) platform is a stated goal and
copyleft dependencies change what is possible.

    .venv\\Scripts\\python.exe scripts\\license_audit.py [--json OUT] [--all]

Exit code 0 always (this is a report, not a gate) unless ``--strict`` is given,
in which case strong copyleft in the runtime dependency set fails the run.
"""
from __future__ import annotations

import argparse
import importlib.metadata as md
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: runtime deps this project imports (plus the optional extras)
RUNTIME = [
    "pymatgen", "ase", "spglib", "numpy", "scipy", "matplotlib", "networkx",
    "openbabel-wheel", "rdkit", "Pillow",
]

#: licence fingerprints -> class.  Checked against the metadata ``License`` field
#: and any ``License ::`` classifier (case-insensitive substring match).
CLASS_PATTERNS: list[tuple[str, str]] = [
    ("agpl", "strong-copyleft"),
    ("gnu affero", "strong-copyleft"),
    ("gpl-3", "strong-copyleft"),
    ("gplv3", "strong-copyleft"),
    ("gnu general public license v3", "strong-copyleft"),
    ("gnu general public license (gpl)", "strong-copyleft"),
    ("gpl-2", "strong-copyleft"),
    ("gplv2", "strong-copyleft"),
    ("gnu general public license v2", "strong-copyleft"),
    ("gnu general public", "strong-copyleft"),
    ("lgpl", "weak-copyleft"),
    ("gnu lesser", "weak-copyleft"),
    ("mpl", "weak-copyleft"),
    ("mozilla public", "weak-copyleft"),
    ("epl", "weak-copyleft"),
    ("eupl", "weak-copyleft"),
    ("cddl", "weak-copyleft"),
    ("mit", "permissive"),
    ("bsd", "permissive"),
    ("apache", "permissive"),
    ("isc", "permissive"),
    ("psf", "permissive"),
    ("python software foundation", "permissive"),
    ("zlib", "permissive"),
    ("unlicense", "permissive"),
    ("public domain", "permissive"),
    ("cc0", "permissive"),
    ("mpl-2.0", "weak-copyleft"),
]

#: manual overrides where the metadata is missing or misleading
KNOWN: dict[str, tuple[str, str]] = {
    "ase": ("weak-copyleft", "LGPL-2.1-or-later (metadata often blank)"),
    "openbabel-wheel": ("strong-copyleft", "GPL-2.0 (Open Babel); redistribution/embedding has copyleft obligations"),
    "rdkit": ("permissive", "BSD-3-Clause"),
    "pymatgen": ("permissive", "MIT"),
    "spglib": ("permissive", "BSD-3-Clause"),
    "pytest": ("permissive", "MIT"),
    "scipy": ("permissive", "BSD-3-Clause (long licence text mentions GPL compatibility only)"),
    "matplotlib": ("permissive", "PSF-based matplotlib licence (BSD-compatible)"),
    "pillow": ("permissive", "MIT-CMU"),
    "networkx": ("permissive", "BSD-3-Clause"),
    "numpy": ("permissive", "BSD-3-Clause (bundled components are permissive too)"),
}


def _match(blob: str, evidence: str) -> tuple[str, str]:
    for needle, cls in CLASS_PATTERNS:
        if needle in blob:
            return cls, evidence
    return "unknown", evidence


def classify(name: str, meta: md.PackageMetadata) -> tuple[str, str]:
    """Classify a dependency, preferring structured metadata over free text.

    ``License ::`` classifiers and ``License-Expression`` are authoritative; the
    free-text ``License`` field is only a fallback because several permissive
    packages embed long licence agreements that *mention* the GPL (scipy and
    matplotlib both did, and were mis-flagged as copyleft by a naive substring
    search).
    """
    if name in KNOWN:
        return KNOWN[name]
    classifiers = [str(c) for c in (meta.get_all("Classifier") or []) if c.startswith("License")]
    if classifiers:
        return _match(" ".join(classifiers).lower(), " | ".join(classifiers)[:120])
    expression = meta.get("License-Expression")
    if expression:
        return _match(str(expression).lower(), str(expression)[:120])
    text = meta.get("License")
    if text:
        # strip a trailing long agreement: the first line is usually the label
        head = str(text).strip().splitlines()[0] if str(text).strip() else ""
        cls, _ = _match(head.lower(), "")
        if cls != "unknown":
            return cls, head[:120]
        return _match(str(text).lower(), f"(full text, {len(str(text))} chars)")
    return "unknown", "no License field/classifier in metadata"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(ROOT / "runs" / "license_audit.json"))
    ap.add_argument("--all", action="store_true", help="audit *every* installed distribution")
    ap.add_argument("--strict", action="store_true", help="fail on strong copyleft in runtime deps")
    args = ap.parse_args()

    if args.all:
        names = sorted({d.metadata["Name"] for d in md.distributions() if d.metadata and d.metadata["Name"]})
    else:
        names = RUNTIME

    rows = []
    for name in names:
        try:
            meta = md.metadata(name)
        except md.PackageNotFoundError:
            rows.append({"name": name, "version": None, "class": "not-installed", "evidence": ""})
            continue
        cls, evidence = classify(name.lower(), meta)
        rows.append({
            "name": meta["Name"],
            "version": meta["Version"],
            "class": cls,
            "evidence": evidence,
            "home": meta.get("Home-page") or meta.get("Project-URL") or "",
        })

    runtime_rows = [r for r in rows if r["name"].lower().replace("_", "-") in
                    {n.replace("_", "-") for n in RUNTIME}]
    counts: dict[str, int] = {}
    for row in runtime_rows:
        counts[row["class"]] = counts.get(row["class"], 0) + 1

    report = {
        "audited_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "scope": "all installed distributions" if args.all else "runtime dependencies",
        "counts": counts,
        "rows": rows,
        "note": (
            "分类依据是安装元数据的 License 字段/classifier，并对已知不一致的包做人工覆盖；"
            "这不是法律意见。strong-copyleft（GPL/AGPL）会限制闭源商用分发；"
            "weak-copyleft（LGPL/MPL）通常可用于动态链接/独立进程，但需要复核。"
        ),
    }
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"scope: {report['scope']}  ({len(rows)} packages)")
    for row in rows:
        print(f"  {row['class']:16s} {row['name']:22s} {str(row['version']):12s} {row['evidence'][:70]}")
    print(f"\ncounts: {counts}\nreport: {out}")

    if args.strict and counts.get("strong-copyleft"):
        print("STRICT: strong copyleft present in runtime dependencies", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
