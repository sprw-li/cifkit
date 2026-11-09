"""Generated artifacts must not leak host-specific paths (round 28).

The NWChem export used to contain an absolute Windows path because ASE's
``nwchem-in`` writer calls ``os.path.abspath`` on its default label.  That file
would be useless in a container or on a cluster — the defect was found by running
the export in a Bohrium container.  These tests keep the class closed.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "data" / "zif8_cr_sod.cif"


def _load():
    spec = importlib.util.spec_from_file_location("check_portability",
                                                  ROOT / "scripts" / "check_portability.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def portability():
    return _load()


def test_nwchem_export_has_relative_dirs(tmp_path):
    from pymatgen.core import Structure

    from cifkit.export import write_structure

    target = tmp_path / "mol.nw"
    write_structure(Structure.from_file(FIXTURE), target, fmt="nwchem")
    text = target.read_text(encoding="utf-8")
    permanent = [line for line in text.splitlines() if line.startswith("permanent_dir")]
    scratch = [line for line in text.splitlines() if line.startswith("scratch_dir")]
    assert permanent and scratch
    assert all(line.strip().endswith(".") for line in permanent + scratch), (permanent, scratch)
    assert ":" not in permanent[0], "no drive letter / absolute host path allowed"
    assert str(ROOT) not in text


def test_forbidden_patterns_cover_windows_and_posix(portability):
    names = {name for name, _pattern in portability.forbidden_patterns()}
    assert {"workspace-root", "windows-drive", "posix-home"} <= names


def test_generated_text_artifacts_are_portable(portability, tmp_path):
    """Every text format we generate must be free of host paths."""
    from pymatgen.core import Structure

    from cifkit.export import supported_formats, write_structure

    structure = Structure.from_file(FIXTURE)
    patterns = portability.forbidden_patterns()
    offenders: list[str] = []
    checked = 0
    for fmt in supported_formats():
        written = None
        for candidate in (tmp_path / f"artifact.{fmt}", tmp_path / fmt.replace("/", "_")):
            try:
                write_structure(structure, candidate, fmt=fmt)
            except Exception:  # noqa: BLE001
                continue
            if candidate.is_file():
                written = candidate
                break
        if written is None:
            continue
        raw = written.read_bytes()
        if b"\x00" in raw:
            continue
        text = raw.decode("utf-8", errors="replace")
        checked += 1
        for name, pattern in patterns:
            if pattern.search(text):
                offenders.append(f"{fmt}:{name}")
    assert checked >= 20, f"only {checked} text formats were written"
    assert not offenders, offenders


def test_the_real_report_is_clean_if_present(portability):
    import json

    path = ROOT / "runs" / "portability.json"
    if not path.is_file():
        pytest.skip("portability report not generated yet")
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["findings"] == []
    assert report["n_formats"] >= 25
