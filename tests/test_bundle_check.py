"""Bundle internal consistency (round 39).

A bundle is only usable if its files agree with each other.  These tests check the
contracts *and* prove the checker catches a broken bundle (otherwise it would just
be decoration).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pymatgen.core import Structure

from cifkit.export import supported_bundles, write_bundle
from cifkit.export.bundle_check import check_bundle

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "data" / "terephthalic_acid_hfree.cif"


@pytest.fixture(scope="module")
def structure() -> Structure:
    return Structure.from_file(FIXTURE)


@pytest.mark.parametrize("code", sorted(supported_bundles()))
def test_every_bundle_is_internally_consistent(tmp_path, structure, code):
    info = write_bundle(structure, code, tmp_path / code)
    result = check_bundle(code, tmp_path / code, info.get("missing") or [])
    assert result["ok"], result["errors"]
    assert result["checks"], "a bundle must be checked, not just assumed"


@pytest.mark.parametrize("code", sorted(supported_bundles()))
def test_returned_files_are_exactly_what_was_written(tmp_path, structure, code):
    """Round 58: the returned ``files`` *is* the bundle contract.

    ``write_bundle`` used to write ``README.md`` without listing it, so every caller
    that counted the returned list (``api.convert`` reports it raw; the CLI had to
    paper over it) was short by one file.  It must now list every file it produced —
    and nothing it did not.
    """
    outdir = tmp_path / code
    info = write_bundle(structure, code, outdir)
    on_disk = {path.name for path in outdir.iterdir() if path.is_file()}
    assert set(info["files"]) == on_disk, (code, info["files"], sorted(on_disk))
    assert "README.md" in info["files"]
    assert len(info["files"]) == len(set(info["files"])), f"{code}: duplicate names"
    # every declared file really is there and non-empty (the callers rely on it)
    for name in info["files"]:
        path = outdir / name
        assert path.is_file() and path.stat().st_size > 0, f"{code}/{name}"


def test_returned_files_do_not_include_unrelated_preexisting_files(tmp_path, structure):
    """A reused outdir is not a licence to report somebody else's files."""
    outdir = tmp_path / "vasp"
    outdir.mkdir()
    (outdir / "user_notes.txt").write_text("mine", encoding="utf-8")
    info = write_bundle(structure, "vasp", outdir)
    assert "user_notes.txt" not in info["files"]
    assert set(info["files"]) == {path.name for path in outdir.iterdir()
                                  if path.is_file()} - {"user_notes.txt"}


def test_readme_lists_the_full_file_set(tmp_path, structure):
    info = write_bundle(structure, "dftb", tmp_path / "dftb")
    readme = (tmp_path / "dftb" / "README.md").read_text(encoding="utf-8")
    listing = next(line for line in readme.splitlines() if line.startswith("Files: "))
    assert listing == f"Files: {', '.join(info['files'])}", listing
    assert "README.md" in listing


def test_missing_file_is_detected(tmp_path, structure):
    info = write_bundle(structure, "lammps", tmp_path / "lammps")
    (tmp_path / "lammps" / "in.min").unlink()
    result = check_bundle("lammps", tmp_path / "lammps", info.get("missing") or [])
    assert not result["ok"]
    assert any("in.min" in error for error in result["errors"])


def test_broken_reference_is_detected(tmp_path, structure):
    info = write_bundle(structure, "dftb", tmp_path / "dftb")
    (tmp_path / "dftb" / "geo.gen").unlink()
    result = check_bundle("dftb", tmp_path / "dftb", info.get("missing") or [])
    assert not result["ok"]
    assert any("geo.gen" in error for error in result["errors"])


def test_wrong_reference_target_is_detected(tmp_path, structure):
    info = write_bundle(structure, "lammps", tmp_path / "lammps")
    (tmp_path / "lammps" / "data.lammps").rename(tmp_path / "lammps" / "other.lammps")
    result = check_bundle("lammps", tmp_path / "lammps", info.get("missing") or [])
    assert not result["ok"]


def test_declared_missing_must_match_reality(tmp_path, structure):
    """If a bundle ships the thing it calls missing, the docs are lying."""
    info = write_bundle(structure, "vasp", tmp_path / "vasp")
    (tmp_path / "vasp" / "POTCAR").write_text("fake", encoding="utf-8")
    result = check_bundle("vasp", tmp_path / "vasp", info.get("missing") or [])
    assert not result["ok"]
    assert any("POTCAR" in error for error in result["errors"])


def test_unknown_bundle_is_rejected(tmp_path):
    result = check_bundle("not-a-code", tmp_path, [])
    assert not result["ok"]
