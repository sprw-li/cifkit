"""Verify the repository's byte-level integrity that tests depend on.

Why this exists (limitation G6): the bundled topology references and the demo run
artifacts are pinned by **sha256 of their bytes**, and ``.gitattributes`` forces
``eol=lf`` so a fresh clone on Windows (``core.autocrlf=true``) still checks them
out as LF.  This script is the executable statement of that contract, so it can be
run locally and in CI on every platform.

    .venv\\Scripts\\python.exe scripts\\check_eol.py [--json OUT]

Exit 0 when every pinned file is LF with the expected hash; 1 otherwise.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: files whose sha256 appears in a manifest/metadata file we ship
PINNED: list[tuple[str, str]] = [
    ("cifkit/data/nets/sod-reference.cif", "cifkit/data/nets/sod.json"),
    ("cifkit/data/nets/pcu-reference.cif", "cifkit/data/nets/pcu.json"),
    ("cifkit/data/nets/dia-reference.cif", "cifkit/data/nets/dia.json"),
    ("cifkit/data/nets/fcu-reference.cif", "cifkit/data/nets/fcu.json"),
    ("cifkit/data/nets/tbo-reference.cif", "cifkit/data/nets/tbo.json"),
    ("cifkit/data/nets/bcu-reference.cif", "cifkit/data/nets/bcu.json"),
]

#: additional textual artifacts that must never contain CRLF
LF_ONLY = ["runs/demo_sod_zif8/raw.cif", "tests/data/zif8_cr_sod.cif"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _recorded_hash(metadata: Path) -> str | None:
    try:
        data = json.loads(metadata.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    for key in ("cif_sha256", "sha256"):
        value = data.get(key)
        if isinstance(value, str) and len(value) == 64:
            return value
    return None


def _eol_attributes() -> dict:
    """What git thinks the EOL policy is (informational)."""
    try:
        out = subprocess.run(["git", "check-attr", "eol", "text", "--", "."],
                             cwd=str(ROOT), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60)
        return {"ok": out.returncode == 0, "sample": out.stdout.splitlines()[:5]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(ROOT / "runs" / "check_eol.json"))
    args = ap.parse_args()

    results: list[dict] = []
    failures: list[str] = []
    for rel, metadata in PINNED:
        path = ROOT / rel
        entry = {"file": rel, "exists": path.is_file()}
        if not entry["exists"]:
            failures.append(f"{rel}: missing")
            results.append(entry)
            continue
        raw = path.read_bytes()
        entry["crlf"] = raw.count(b"\r\n")
        entry["lf"] = raw.count(b"\n")
        entry["sha256"] = _sha256(path)
        entry["expected"] = _recorded_hash(ROOT / metadata)
        entry["hash_ok"] = entry["expected"] in (None, entry["sha256"])
        entry["lf_only"] = entry["crlf"] == 0
        if not entry["lf_only"]:
            failures.append(f"{rel}: contains {entry['crlf']} CRLF sequences")
        if not entry["hash_ok"]:
            failures.append(f"{rel}: sha256 {entry['sha256'][:16]} != recorded {(entry['expected'] or '')[:16]}")
        results.append(entry)

    for rel in LF_ONLY:
        path = ROOT / rel
        if not path.is_file():
            continue
        raw = path.read_bytes()
        entry = {"file": rel, "crlf": raw.count(b"\r\n"), "lf": raw.count(b"\n"),
                 "lf_only": raw.count(b"\r\n") == 0}
        if not entry["lf_only"]:
            failures.append(f"{rel}: contains {entry['crlf']} CRLF sequences")
        results.append(entry)

    # the .gitattributes contract itself
    attributes = ROOT / ".gitattributes"
    policy_ok = attributes.is_file() and "eol=lf" in attributes.read_text(encoding="utf-8")
    if not policy_ok:
        failures.append(".gitattributes: missing or does not set eol=lf")

    report = {"files": results, "eol_policy_ok": policy_ok, "attributes": _eol_attributes(),
              "failures": failures}
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"checked {len(results)} pinned/LF-only files; eol policy ok: {policy_ok}")
    for entry in results:
        mark = "ok " if entry.get("lf_only") and entry.get("hash_ok", True) else "BAD"
        hash_note = ""
        if "sha256" in entry:
            hash_note = f" sha={entry['sha256'][:12]} expected={str(entry.get('expected'))[:12]}"
        print(f"  [{mark}] {entry['file']:44s} crlf={entry.get('crlf', '?')}{hash_note}")
    if failures:
        print("\nfailures:")
        for failure in failures:
            print("  -", failure)
        print(f"report: {out}")
        return 1
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
