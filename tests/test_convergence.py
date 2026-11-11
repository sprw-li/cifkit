"""Convergence machinery (round 45, limitation E3).

E3: every template ships default parameters and no convergence testing was done.
The machinery itself is testable offline; these tests pin the parts that determine
whether a convergence *claim* is honest.
"""
from __future__ import annotations

import pytest

from cifkit.export.convergence import (SWEEPS, Sample, analyse, parse_energy,
                                       render_markdown, sweep)

NWCHEM = """start demo
permanent_dir .
scratch_dir .
geometry units angstrom
  system crystal
    lattice_vectors
      6.0 0.0 0.0
      0.0 6.0 0.0
      0.0 0.0 6.0
  end
  H 0.0 0.0 0.0
  H 0.0 0.0 0.74
end
nwpw
  cutoff 20
  xc pbe
end
task pspw energy
"""


def test_sweep_replaces_only_the_parameter():
    variants = sweep("nwchem", NWCHEM, [30, 45])
    assert [value for value, _ in variants] == [30.0, 45.0]
    for value, text in variants:
        assert f"cutoff {value:g}" in text
        assert text.count("cutoff") == 1
        # everything else is untouched
        assert "task pspw energy" in text
        assert "xc pbe" in text


def test_sweep_rejects_an_input_without_the_parameter():
    with pytest.raises(ValueError):
        sweep("nwchem", "start x\ngeometry units angstrom\nend\n", [20])


def test_unknown_code_is_rejected():
    with pytest.raises(ValueError):
        sweep("gromacs", "")


def test_every_known_code_exposes_its_parameter():
    for code, spec in SWEEPS.items():
        assert spec["pattern"] and "{value}" in spec["render"], code
        assert spec["defaults"] == sorted(spec["defaults"]), code


@pytest.mark.parametrize("line,expected", [
    ("  Total DFT energy = -17.123456", -17.123456),
    ("Total PSPW energy = -17.200000", -17.2),
    ("!    total energy              =     -76.12345678 Ry", -76.12345678),
    ("FINAL SINGLE POINT ENERGY      -75.123456", -75.123456),
])
def test_energy_dialects(line, expected):
    assert parse_energy(line) == expected


def test_missing_energy_returns_none():
    assert parse_energy("PROGRAM ENDED AT\nTotal times  cpu: 1.0s") is None


def _samples(values, energies):
    return [Sample(value, energy, True) for value, energy in zip(values, energies)]


def test_convergence_picks_the_first_value_with_all_later_steps_inside():
    # 20 -> 30 moves 0.5 eV; every step after 30 is below 1e-3, so 30 is the answer
    report = analyse("nwchem", _samples([20, 30, 40, 50],
                                        [-17.0000, -17.5000, -17.5009, -17.5010]),
                     1e-3)
    assert report.converged_at == 30, report.note
    assert report.as_dict()["complete"] is True


def test_not_converged_is_reported_not_hidden():
    report = analyse("nwchem", _samples([20, 30, 40], [-17.0, -17.5, -18.0]), 1e-3)
    assert report.converged_at is None
    assert "not converged" in report.note


def test_two_points_are_not_enough():
    report = analyse("nwchem", _samples([20, 30], [-17.0, -17.5]), 1e-3)
    assert report.converged_at is None
    assert "at least 3" in report.note


def test_failed_samples_make_the_report_incomplete():
    samples = _samples([20, 30, 40], [-17.0, -17.5, -17.5009])
    samples.append(Sample(50, None, False, "timeout"))
    report = analyse("nwchem", samples, 1e-3)
    assert report.as_dict()["complete"] is False
    assert report.converged_at == 30, "failures must not be mistaken for convergence"


def test_per_atom_threshold_is_applied():
    # per-cell deltas: 0.5, 0.0004, 0.0001 -> converged at 30 for a 1e-3 threshold
    energies = [-100.0, -100.5, -100.5004, -100.5005]
    per_cell = analyse("nwchem", _samples([20, 30, 40, 50], energies), 1e-3)
    assert per_cell.converged_at == 30
    # dividing by 16 atoms turns 0.0004 into 2.5e-5: with a 1e-5 per-atom threshold
    # the sweep needs one more step, which proves the divisor is actually used
    per_atom = analyse("nwchem", _samples([20, 30, 40, 50], energies), 1e-5, per_atom=16)
    assert per_atom.converged_at == 40, per_atom.note
    assert per_atom.converged_at > per_cell.converged_at


def test_markdown_states_the_verdict():
    report = analyse("nwchem", _samples([20, 30, 40], [-17.0, -17.5, -17.5009]), 1e-3)
    text = render_markdown(report, title="demo")
    assert "demo" in text and "converged at" in text
    assert "| value | energy | ok | detail |" in text
    assert text.count("|") >= 12

def test_failed_samples_serialise_as_null_not_nan():
    """NaN is not valid JSON; a strict consumer must be able to parse the report."""
    import json
    import math

    report = analyse("nwchem", _samples([20, 30, 40], [-17.0, -17.5, -17.5009]), 1e-3)
    report.samples.append(Sample(50, float("nan"), False, "not run"))
    blob = json.dumps(report.as_dict())
    assert "NaN" not in blob
    parsed = json.loads(blob)
    assert parsed["samples"][-1]["energy"] is None
    assert math.isnan(report.samples[-1].energy)


def test_cloud_line_format_is_parseable():
    """The cloud script prints one CONVERGENCE line per cutoff; keep it parseable."""
    import re

    pattern = re.compile(r"CONVERGENCE value=(\S+) energy=(\S+) status=(\S+)(?: seconds=(\S+))?")
    match = pattern.search("CONVERGENCE value=40 energy=-17.123456 status=ok seconds=421.4")
    assert match
    assert match.group(1) == "40" and match.group(3) == "ok"
    bad = pattern.search("CONVERGENCE value=40 energy=nan status=no-energy seconds=22.4")
    assert bad and bad.group(2) == "nan"

NWCHEM_PSPW_OUTPUT = """\
===============================  Energy Calculation  ===========================
 iter.           Energy         DeltaE       DeltaRho
    1    -0.1076404459E+03
total orbital energy:  -0.3162791516E+02 (   -0.10543E+01/electron)
hartree   energy    :   0.2232207638E+03 (    0.74407E+01/electron)
exc-corr  energy    :  -0.2809657456E+02 (   -0.93655E+00/electron)
ion-ion   energy    :   0.1388116803E+03 (    0.86757E+01/ion)
Total PSPW energy     :  -0.1076404459E+03
    2    -0.1112953510E+03
total     energy    :  -0.1112953510E+03 (   -0.69560E+01/ion)
Total PSPW energy     :  -0.1112953510E+03
Total times  cpu: 1020.8s     wall: 1031.8s
"""


def test_nwchem_fortran_energy_is_parsed():
    assert parse_energy(NWCHEM_PSPW_OUTPUT) == -111.2953510


def test_the_last_energy_wins_not_the_first():
    """SCF codes print the energy every iteration: only the final one counts."""
    first_is_wrong = parse_energy(NWCHEM_PSPW_OUTPUT)
    assert first_is_wrong != -107.6404459
    assert first_is_wrong == -111.2953510


def test_nwchem_real_output_from_the_convergence_job():
    """Line taken verbatim from cloud job ec5ef67c (cutoff 20)."""
    line = "Total PSPW energy     :  -0.1076404459E+03\nTotal PSPW energy     :  -0.1112953510E+03\n"
    assert parse_energy(line) == -111.2953510


def test_fortran_exponents_and_case_variants():
    assert parse_energy("Total DFT energy = -1.2345E+02\n") == -123.45
    assert parse_energy("total     energy    :  -0.1112953510E+03\n") == -111.2953510
    assert parse_energy("Total PSPW energy : -1.5d+02\n") == -150.0
