"""Do any exported files leak host-specific absolute paths?

A generated input that contains ``D:\\path\\to\\repo\\...`` (or ``/home/someone``)
is not portable: it fails on a cluster or in a container.  Round 28 found exactly
that in the NWChem export (ASE's default ``permanent_dir``), by running the file
in a cloud container.

    .venv\\Scripts\\python.exe scripts\\check_portability.py [--json OUT]

Exit 1 when a generated artifact contains a host path, a Windows drive path, the
user profile directory, or a POSIX home path.  ``--allow PATTERN`` adds an
exception (repeatable) for cases that are legitimately host-specific.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "data" / "zif8_cr_sod.cif"

#: patterns that must not appear in a generated artifact
def forbidden_patterns() -> list[tuple[str, re.Pattern]]:
    patterns = [
        ("workspace-root", re.compile(re.escape(str(ROOT)), re.IGNORECASE)),
        ("windows-drive", re.compile(r"[A-Za-z]:\\\\[^\\s\"']+")),
        ("windows-drive-forward", re.compile(r"[A-Za-z]:/[^\\s\"']+")),
        ("posix-home", re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+")),
    ]
    profile = str(Path.home())
    if profile:
        patterns.append(("user-profile", re.compile(re.escape(profile), re.IGNORECASE)))
    return patterns


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(ROOT / "runs" / "portability.json"))
    ap.add_argument("--allow", action="append", default=[])
    ap.add_argument("--fixture", default=str(FIXTURE))
    args = ap.parse_args()

    from pymatgen.core import Structure  # noqa: PLC0415

    from cifkit.export import supported_formats, write_structure  # noqa: PLC0415

    patterns = forbidden_patterns()
    allowed = [re.compile(pattern) for pattern in args.allow]

    findings: list[dict] = []
    checked: list[str] = []
    skipped: list[str] = []
    structure = Structure.from_file(args.fixture)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        for fmt in supported_formats():
            # Writers pick their backend from the file extension, so try the real
            # suffix first and fall back to a bare name (that is what the ``cif``
            # and image formats want).
            written: Path | None = None
            last_error: Exception | None = None
            for candidate in (out / f"artifact.{fmt}", out / fmt.replace("/", "_")):
                try:
                    write_structure(structure, candidate, fmt=fmt)
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    continue
                if candidate.is_file():
                    written = candidate
                    break
            if written is None:
                findings.append({"format": fmt, "kind": "write-error",
                                 "detail": f"{type(last_error).__name__}: {last_error}"})
                continue
            target = written
            raw = target.read_bytes()
            if b"\x00" in raw:
                # binary artifact (e.g. PNG): scanning it as text yields false
                # positives from embedded metadata strings
                skipped.append(fmt)
                continue
            checked.append(fmt)
            text = raw.decode("utf-8", errors="replace")
            for name, pattern in patterns:
                for match in pattern.finditer(text):
                    matched = match.group(0)
                    if any(ok.search(matched) for ok in allowed):
                        continue
                    findings.append({"format": fmt, "kind": name, "match": matched[:120]})

    report = {"checked": checked, "n_formats": len(checked), "skipped_binary": skipped,
              "findings": findings}
    out_path = Path(args.json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"checked {len(checked)} text formats ({len(skipped)} binary skipped); "
          f"findings: {len(findings)}")
    for finding in findings[:25]:
        print("  ", json.dumps(finding, ensure_ascii=False))
    print(f"report: {out_path}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
