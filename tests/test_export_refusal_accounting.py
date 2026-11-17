"""Refusal accounting: a *correct* refusal must never look like a broken format.

Round 57 made the LAMMPS writer honest: when ASE's ``Prism`` produces a tilt
factor beyond half the box length, real LAMMPS would reject the box, so the writer
refuses instead of silently writing a wrong periodic box.  But the refusal was a
bare ``ValueError``, and ``scripts/verify_corpus.py`` classified "wrote nothing and
not marked unsupported" as a **bad format** — so ``sod_zn_mof.cif`` made the
corpus gate red through no defect of its own, and ``check_all``/``release_check``
went red with it.

These tests pin the contract (task-5, defect A/A2):

* the LAMMPS refusal is a typed :class:`CellNotRepresentableError` sharing the
  :class:`ExportRefusalError` base with the disorder/format-limit refusals;
* ``verify_corpus`` books it as ``unsupported`` (with a reason), never as ``bad``,
  for the single format *and* the LAMMPS bundle of ``sod_zn_mof.cif``;
* ``verify_formats`` exits 0 when the only non-ok format is a refusal;
* a first row that fails to *load* no longer crashes the reporter or empties the
  cross-structure aggregation (the A2 ``KeyError: 'bad_formats'``).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import verify_corpus  # noqa: E402  (needs scripts/ on sys.path)

from cifkit.export import write_structure  # noqa: E402
from cifkit.export.disorder_guard import DisorderedStructureError  # noqa: E402
from cifkit.export.format_limits import FormatLimitError  # noqa: E402
from cifkit.export.refusals import (CellNotRepresentableError,  # noqa: E402
                                    ExportRefusalError, refusal_reason)

SOD_ZN_MOF = ROOT / "tests" / "data" / "sod_zn_mof.cif"
ZIF8 = ROOT / "tests" / "data" / "zif8_cr_sod.cif"


def _unrepresentable_cell() -> Structure:
    """A cell whose LAMMPS tilt exceeds half the box (γ=170° leaves xy=-2.95 on a
    3 Å box).  Real LAMMPS rejects such a box, so the writer must refuse."""
    return Structure(Lattice.from_parameters(3.0, 3.0, 3.0, 90, 90, 170),
                     ["C"], [[0.0, 0.0, 0.0]])


def test_refusal_hierarchy_shares_one_base_and_stays_a_valueerror():
    for exc in (DisorderedStructureError, FormatLimitError, CellNotRepresentableError):
        assert issubclass(exc, ExportRefusalError)
        assert issubclass(exc, ValueError), "callers already catch ValueError"


def test_lammps_refusal_is_typed_and_actionable(tmp_path):
    with pytest.raises(CellNotRepresentableError) as info:
        write_structure(_unrepresentable_cell(), tmp_path / "x.lammps", "lammps")
    assert info.value.code == "cell-not-representable"
    assert info.value.fmt == "lammps"
    message = str(info.value)
    assert "tilt" in message and "half the box" in message
    assert "Reorient" in message, "the refusal must say how to get a usable export"
    assert not (tmp_path / "x.lammps").exists(), "no half-written box may be left behind"


def test_refusal_reason_carries_a_stable_code():
    reason = refusal_reason(CellNotRepresentableError("lammps", "tilt 3 > 1.5"))
    assert reason.startswith("cell-not-representable: ")
    assert "lammps" in reason


def test_verify_formats_treats_a_refusal_as_unsupported_not_a_failure(tmp_path):
    """End-to-end: a structure whose only refused format is lammps still exits 0."""
    cif = tmp_path / "skewed.cif"
    from pymatgen.io.cif import CifWriter

    CifWriter(_unrepresentable_cell()).write_file(str(cif))
    outdir = tmp_path / "vf"
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "verify_formats.py"),
         "--structure", str(cif), "--only", "cif,lammps",
         "--outdir", str(outdir)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=900)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads((outdir / "verify_formats.json").read_text(encoding="utf-8"))
    assert report["unsupported_formats"] == ["lammps"]
    assert report["bad_formats"] == []
    assert report["n_bad"] == 0 and report["all_representable_ok"] is True
    row = next(r for r in report["formats"] if r["format"] == "lammps")
    assert row["unsupported"].startswith("cell-not-representable")
    assert "unsupported" in report["accounting"]


def test_verify_corpus_books_sod_zn_mof_lammps_as_unsupported_not_bad(tmp_path):
    """The exact HEAD regression: the 750-atom tilted cell must be 'unsupported'."""
    if not SOD_ZN_MOF.is_file():
        pytest.skip("sod_zn_mof fixture missing")
    row = verify_corpus.check_one(str(SOD_ZN_MOF))
    assert row["ok"] is True, row["errors"][:3]
    assert row["bad_formats"] == [] and row["bad_bundles"] == [] and row["bad_templates"] == []
    assert row["formats"]["lammps"]["unsupported"].startswith("cell-not-representable")
    assert row["bundles"]["lammps"]["unsupported"].startswith("cell-not-representable")
    assert row["n_formats_unsupported"] == 1 and row["n_formats_ok"] == 30
    assert "lammps" in row["unsupported_formats"]
    # the refusal is *reported*, not hidden: the lammps line still carries no file
    assert not row["formats"]["lammps"]["ok"]


def test_aggregate_uses_the_union_of_rows_not_the_first_row():
    """A2: a load-failed first row used to empty by_format/by_bundle entirely."""
    load_failed = verify_corpus.check_one(str(ROOT / "tests" / "data" / "does-not-exist.cif"))
    assert load_failed["load_failed"] is True
    good = {
        "structure": "ok.cif", "ok": True, "load_failed": False,
        "formats": {"cif": {"ok": True}, "lammps": {"ok": False, "unsupported": "x"}},
        "bundles": {"vasp": {"ok": True}},
        "n_formats_ok": 1, "n_formats_unsupported": 1,
        "n_bundles_ok": 1, "n_bundles_unsupported": 0,
    }
    report = verify_corpus.aggregate([load_failed, good])
    assert report["by_format"] == {"cif": 1, "lammps": 0}
    assert report["by_format_unsupported"] == {"cif": 0, "lammps": 1}
    assert report["by_bundle"] == {"vasp": 1}
    assert report["n_ok"] == 1 and report["n_load_failed"] == 1


def test_format_row_and_report_survive_a_load_failed_row(tmp_path):
    bad = tmp_path / "aaa_bad.cif"
    bad.write_text("not a CIF at all\n", encoding="utf-8")
    row = verify_corpus.check_one(str(bad))
    assert row["load_failed"] is True and row["ok"] is False
    # the reporter must not raise on the row that used to KeyError
    line = verify_corpus.format_row(row)
    assert "LOAD-FAILED" in line and "bad=[]" in line
    report = verify_corpus.aggregate([row])
    assert report["n_load_failed"] == 1 and report["by_format"] == {}


def test_verify_corpus_script_with_only_a_broken_input_does_not_crash(tmp_path):
    """A2 end-to-end: the script must report the load failure, not raise KeyError."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "aaa_bad.cif").write_text("garbage\nnot a cif\n", encoding="utf-8")
    out = tmp_path / "report.json"
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "verify_corpus.py"),
         "--source", str(source), "--limit", "1", "--jobs", "1", "--json", str(out)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=900)
    output = proc.stdout + proc.stderr
    assert "KeyError" not in output and "Traceback" not in output, output
    assert proc.returncode == 1, "a structure that cannot even be loaded is a real failure"
    assert "LOAD-FAILED" in output
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["n_load_failed"] == 1 and report["all_ok"] is False


def test_disordered_and_limit_refusals_keep_their_own_codes(tmp_path):
    """The common base must not erase the specific refusal codes."""
    disordered = Structure.from_file(ROOT / "tests" / "data" / "zif8_disordered_h.cif")
    with pytest.raises(DisorderedStructureError) as info:
        write_structure(disordered, tmp_path / "x.xyz", "xyz")
    assert info.value.code == "disordered"
    limit = FormatLimitError("mol", 1000, 999, "3-digit field")
    assert limit.code == "format-limit" and isinstance(limit, ExportRefusalError)
