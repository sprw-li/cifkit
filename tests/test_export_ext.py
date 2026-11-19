"""Extended export: all cif→anything formats + computation-software bundles."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from cifkit import export

DATA = Path(__file__).resolve().parent / "data"
ZIF8 = DATA / "zif8_cr_sod.cif"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def structure():
    from pymatgen.core import Structure

    return Structure.from_file(str(ZIF8))


def test_png_export_survives_a_gui_backend_request(tmp_path):
    """`--to png` must not depend on the caller's matplotlib backend being usable.

    Round 58: CI's windows/py3.13 runner has no usable Tcl/Tk, matplotlib's automatic
    selection picked TkAgg, and writing a PNG died with
    ``_tkinter.TclError: Can't find a usable init.tcl`` — a headless container would
    have failed the same way.  cifkit.render now forces Agg, so the render succeeds
    and the effective backend is Agg even when MPLBACKEND asks for TkAgg.
    """
    out = tmp_path / "preview.png"
    code = (
        "import pathlib, sys\n"
        "import matplotlib\n"
        "from pymatgen.core import Structure\n"
        "from cifkit import export\n"
        "s = Structure.from_file(sys.argv[1])\n"
        "export.write_structure(s, pathlib.Path(sys.argv[2]), 'png', title='test')\n"
        "print('backend=' + matplotlib.get_backend().lower())\n"
    )
    env = {**os.environ, "MPLBACKEND": "TkAgg", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run([sys.executable, "-c", code, str(ZIF8), str(out)],
                          cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "backend=agg" in proc.stdout.lower(), proc.stdout
    assert out.is_file() and out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_all_formats_write_and_readback(tmp_path, structure):
    """Every supported format must write a non-empty file; writers self-verify read-back."""
    formats = sorted(export.supported_formats())
    assert len(formats) >= 31, f"expected >=31 formats, got {len(formats)}: {formats}"
    for fmt in formats:
        path = tmp_path / f"structure.{fmt}"
        try:
            out = export.write_structure(structure, path, fmt, title="test")
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"format {fmt} failed: {type(exc).__name__}: {exc}")
        p = Path(out)
        assert p.is_file() and p.stat().st_size > 0, fmt


def test_aliases_are_accepted(tmp_path, structure):
    for alias, expected in {
        "poscar": "vasp",
        "gjf": "gaussian",
        "gro": "gromacs",
        "ext_xyz": "extxyz",
        "pymatgen-json": "json",
        "abacus-stru": "abacus",
        "fdf": "siesta",
    }.items():
        assert export.normalize_format(alias) == expected


def test_all_bundles_write_files(tmp_path, structure):
    bundles = sorted(export.supported_bundles())
    assert len(bundles) >= 12, bundles
    for code in bundles:
        outdir = tmp_path / code
        info = export.write_bundle(structure, code, outdir, title="test")
        assert info["template"] is True
        assert info["missing"], f"bundle {code} must declare missing items"
        files = info["files"]
        assert files, code
        for name in files:
            path = outdir / name
            assert path.is_file() and path.stat().st_size > 0, f"{code}/{name}"
        assert (outdir / "README.md").is_file()


def test_bundle_unknown_code_raises(tmp_path, structure):
    with pytest.raises(ValueError, match="unsupported bundle"):
        export.write_bundle(structure, "not-a-code", tmp_path / "x")


def test_vasp_bundle_has_expected_files(tmp_path, structure):
    export.write_bundle(structure, "vasp", tmp_path / "vasp", title="t")
    for name in ("POSCAR", "INCAR", "INCAR.static", "KPOINTS", "POTCAR.readme"):
        assert (tmp_path / "vasp" / name).is_file(), name
    assert "POTCAR" in (tmp_path / "vasp" / "POTCAR.readme").read_text(encoding="utf-8")


def test_png_format_is_a_real_png(tmp_path, structure):
    out = export.write_structure(structure, tmp_path / "preview.png", "png", title="test")
    data = Path(out).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) > 5000
