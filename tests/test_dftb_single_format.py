"""The single-format DFTB+ export is a *pair*: ``structure.dftb`` + ``geo.gen``.

Before round 58 ``cifkit convert X.cif --to dftb`` wrote only the ~515 B
``dftb_in.hsd`` (which references ``<<< "geo.gen"``) and reported ``ok: true`` /
exit 0 — an unusable half-product.  Worse, ``scripts/verify_formats.py`` switched
to ``outdir/dftb_bundle`` when checking dftb, so the official "31/31" never covered
the bare product at all.

These tests pin the fix (task-5, defect B):

* the bare writer emits ``geo.gen`` next to the HSD, byte-identical to the bundle's;
* ``write_structure`` verifies the *pair* — a missing/inconsistent companion is a
  real failure, never a silent success;
* the CLI ``--to dftb`` leaves a usable pair on disk;
* ``verify_formats`` checks the bare product against **its own** sibling geo.gen
  (the exact function it uses refuses an HSD with no companion), while the bundle
  is verified separately.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pymatgen.core import Structure

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cifkit import export  # noqa: E402
from cifkit.export.disorder_guard import DisorderedStructureError  # noqa: E402
from cifkit.export.template_check import check_template  # noqa: E402
from cifkit.export.writers import _verify  # noqa: E402

ZIF8 = ROOT / "tests" / "data" / "zif8_cr_sod.cif"
DISORDERED = ROOT / "tests" / "data" / "zif8_disordered_h.cif"


@pytest.fixture(scope="module")
def structure() -> Structure:
    return Structure.from_file(ZIF8)


def test_bare_dftb_writes_the_referenced_geo_gen(structure, tmp_path):
    path = tmp_path / "x.dftb"
    export.write_structure(structure, path, "dftb")
    gen = tmp_path / "geo.gen"
    assert path.is_file() and gen.is_file(), "the HSD references geo.gen: both must exist"
    assert '<<< "geo.gen"' in path.read_text(encoding="utf-8")
    report = check_template("dftb", path.read_text(encoding="utf-8"),
                            {"geo.gen": gen.read_text(encoding="utf-8")})
    assert report.ok and report.natoms == len(structure)
    # not the 515-byte half-product: the companion carries the coordinates
    assert gen.stat().st_size > 1000
    assert path.stat().st_size < gen.stat().st_size


def test_bare_product_is_identical_to_the_bundle_product(structure, tmp_path):
    export.write_structure(structure, tmp_path / "bare" / "x.dftb", "dftb", title="same")
    export.write_bundle(structure, "dftb", tmp_path / "bundle", title="same")
    bare = tmp_path / "bare"
    assert (bare / "geo.gen").read_bytes() == (tmp_path / "bundle" / "geo.gen").read_bytes()
    assert (bare / "x.dftb").read_bytes() == (tmp_path / "bundle" / "dftb_in.hsd").read_bytes()


def test_missing_companion_is_a_real_failure(structure, tmp_path):
    path = tmp_path / "x.dftb"
    export.write_structure(structure, path, "dftb")
    (tmp_path / "geo.gen").unlink()
    with pytest.raises(RuntimeError) as info:
        _verify(path, "dftb", len(structure))
    assert "geo.gen" in str(info.value)
    # the same checker used by verify_formats refuses a lone HSD
    report = check_template("dftb", path.read_text(encoding="utf-8"), {})
    assert report.ok is False and report.natoms is None
    assert any("geo.gen" in error for error in report.errors)


def test_companion_atom_count_mismatch_is_refused(structure, tmp_path):
    """A truncated geo.gen must fail the pair check, not pass as 'usable'."""
    path = tmp_path / "x.dftb"
    export.write_structure(structure, path, "dftb")
    gen = tmp_path / "geo.gen"
    lines = gen.read_text(encoding="utf-8").splitlines()
    gen.write_text("\n".join(lines[:5]) + "\n", encoding="utf-8")  # header lies: 138 vs 3 rows
    with pytest.raises(RuntimeError):
        _verify(path, "dftb", len(structure))


def test_disordered_structures_are_refused_for_dftb(tmp_path):
    disordered = Structure.from_file(DISORDERED)
    with pytest.raises(DisorderedStructureError):
        export.write_structure(disordered, tmp_path / "x.dftb", "dftb")


def test_cli_convert_to_dftb_leaves_a_usable_pair(tmp_path):
    outdir = tmp_path / "cli"
    proc = subprocess.run(
        [sys.executable, "-m", "cifkit", "convert", str(ZIF8),
         "--to", "dftb", "--outdir", str(outdir), "--json"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=900)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    hsd = outdir / "zif8_cr_sod.dftb"
    gen = outdir / "geo.gen"
    assert hsd.is_file() and gen.is_file(), "bare --to dftb must write the pair"
    report = check_template("dftb", hsd.read_text(encoding="utf-8"),
                            {"geo.gen": gen.read_text(encoding="utf-8")})
    assert report.ok and report.natoms == payload["natoms"]


def test_verify_formats_checks_the_bare_product_against_its_own_companion(tmp_path):
    outdir = tmp_path / "vf"
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "verify_formats.py"),
         "--only", "dftb", "--outdir", str(outdir)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=900)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads((outdir / "verify_formats.json").read_text(encoding="utf-8"))
    row = next(r for r in report["formats"] if r["format"] == "dftb")
    assert row["ok"] and row["parsed_natoms"] == report["natoms"]
    # the checked pair lives in outdir itself, not in the bundle directory
    assert (outdir / "structure.dftb").is_file()
    assert (outdir / "geo.gen").is_file()
    assert row["companion"] == "geo.gen" and row["companion_bytes"] > 1000
    assert "single file" in row["reader"]
    # --only dftb still verifies the bundle, separately, with a real parse
    bundle = next(b for b in report["bundles"] if b["code"] == "dftb")
    assert bundle["template_ok"] is True
    assert bundle["template_natoms"] == report["natoms"]
    assert (outdir / "bundles" / "dftb" / "geo.gen").is_file()


def test_verify_formats_would_reject_the_old_half_product(structure, tmp_path):
    """The checker verify_formats applies to the bare product rejects a lone HSD.

    This is the regression guard for "verify_formats 不能再拿 bundle 目录顶替":
    even when a *bundle* exists elsewhere in the output directory, the bare file is
    checked against its own sibling.
    """
    import verify_formats

    bare = tmp_path / "out"
    (bare / "bundles" / "dftb").mkdir(parents=True)
    export.write_bundle(structure, "dftb", bare / "bundles" / "dftb")
    export.write_structure(structure, bare / "structure.dftb", "dftb")
    (bare / "geo.gen").unlink()  # simulate the pre-round-58 half-product
    ok, detail, parsed = verify_formats._check_template(bare / "structure.dftb", "dftb")
    assert ok is False and parsed is None
    assert "geo.gen" in detail, "a bundle elsewhere must not satisfy the bare product check"
