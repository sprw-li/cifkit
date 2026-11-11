"""Every shipped input file must use the comment character its code understands.

Round 53: two real defects of exactly this kind were found by *running* the codes —
LAMMPS rejects ``;`` (``ERROR: Unknown command``) and CP2K rejects ``#``.  The bundle
gate now enforces the rule, and these tests pin the two artifacts and the rule itself.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pymatgen.core import Structure

from cifkit.export import write_bundle
from cifkit.export.bundle_check import COMMENT_STYLE, check_bundle

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "data" / "terephthalic_acid_hfree.cif"


@pytest.fixture(scope="module")
def bundle_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("styles")


@pytest.fixture(scope="module")
def structure() -> Structure:
    return Structure.from_file(FIXTURE)


def test_lammps_input_uses_hash_comments(bundle_dir, structure):
    out = bundle_dir / "lammps"
    write_bundle(structure, "lammps", out)
    text = (out / "in.min").read_text(encoding="utf-8")
    assert text.lstrip().startswith("#")
    for number, line in enumerate(text.splitlines(), 1):
        assert not line.strip().startswith(";"), f"line {number} uses ';' (LAMMPS cannot)"


def test_cp2k_input_uses_bang_comments(bundle_dir, structure):
    out = bundle_dir / "cp2k"
    write_bundle(structure, "cp2k", out)
    text = (out / "cp2k.inp").read_text(encoding="utf-8")
    assert text.lstrip().startswith("!")
    for number, line in enumerate(text.splitlines(), 1):
        assert not line.strip().startswith("#"), f"line {number} uses '#' (CP2K cannot)"


@pytest.mark.parametrize("code", sorted(COMMENT_STYLE))
def test_written_bundle_passes_the_comment_rule(bundle_dir, structure, code):
    out = bundle_dir / code
    info = write_bundle(structure, code, out)
    result = check_bundle(code, out, info.get("missing") or [])
    comment_checks = [item for item in result["checks"]
                      if item["check"].startswith("comments in")]
    assert comment_checks, f"{code} has no comment-style check"
    assert all(item["ok"] for item in comment_checks), result["errors"]


def test_the_rule_actually_rejects_a_wrong_comment(bundle_dir, structure):
    """Prove the gate fails on the defect it was written for."""
    out = bundle_dir / "lammps_wrong"
    info = write_bundle(structure, "lammps", out)
    text = (out / "in.min").read_text(encoding="utf-8")
    (out / "in.min").write_text("; wrong comment\n" + text, encoding="utf-8")
    result = check_bundle("lammps", out, info.get("missing") or [])
    assert not result["ok"]
    assert any("in.min" in error for error in result["errors"])
