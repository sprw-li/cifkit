"""Independent format/bundle round-trip verification script (scripts/verify_formats.py)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ZIF8 = ROOT / "tests" / "data" / "zif8_cr_sod.cif"
SYS_PATH = ROOT / "scripts"
if str(SYS_PATH) not in sys.path:
    sys.path.insert(0, str(SYS_PATH))

verify_formats = pytest.importorskip("verify_formats")


def test_every_supported_format_has_a_reader_category():
    """No supported format may silently lack a verification path (docs claim coverage)."""
    from cifkit import export

    covered = (
        set(verify_formats.PYMATGEN_READERS)
        | set(verify_formats.ASE_READERS)
        | set(verify_formats.TEMPLATES)
        | set(verify_formats.SPECIAL)
    )
    missing = sorted(set(export.supported_formats()) - covered)
    assert not missing, f"formats without a verification path: {missing}"


def test_third_party_readback_exceeds_template_only():
    """A meaningful share of formats must be checked by a *different* library."""
    third_party = set(verify_formats.PYMATGEN_READERS) | set(verify_formats.ASE_READERS)
    assert len(third_party) >= 20, f"only {len(third_party)} third-party readers registered"


@pytest.mark.skipif(not ZIF8.is_file(), reason="fixture missing")
def test_verify_formats_fast_subset_exit_zero(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_formats.py"),
         "--only", "vasp,cif,xyz,extxyz,castep,png,pdb,lammps",
         "--outdir", str(tmp_path / "vf")],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=600,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads((tmp_path / "vf" / "verify_formats.json").read_text(encoding="utf-8"))
    assert report["n_formats"] == 8 and report["n_ok"] == 8
    readers = {row["format"]: row["reader"] for row in report["formats"]}
    assert readers["vasp"] == "pymatgen" and readers["extxyz"] == "ase"
    assert readers["png"] == "magic-bytes"


@pytest.mark.skipif(not ZIF8.is_file(), reason="fixture missing")
def test_verify_formats_rejects_unknown_format(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_formats.py"),
         "--only", "not-a-format", "--outdir", str(tmp_path / "x")],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=300,
    )
    assert proc.returncode == 2
    assert "unsupported" in (proc.stderr + proc.stdout).lower()
