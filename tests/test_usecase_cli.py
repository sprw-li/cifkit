"""Contract tests for the four use-case subcommands: teach / bravais / metals / fec.

The commands live in ``cifkit/usecases_cli.py``.  ``cifkit/cli.py`` registration is
added by the Lead; until that lands, ``python -m cifkit.usecases_cli <cmd>`` is the
same entry point and these tests auto-detect which one is available.

Slow/large runs are opt-in via ``CIFKIT_USECASE_FULL=1`` (full Bain range, all
metals + kits); the default suite uses small parameters and stays under ~2 min.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
USECASES = ROOT / "usecases"
U1_CACHE = USECASES / "u1_fd3m" / "data" / "structures"
ENTRY: list[list[str]] = []
FULL = os.environ.get("CIFKIT_USECASE_FULL") == "1"


def _entry() -> list[str]:
    """Return the argv prefix that exposes the four subcommands (real CLI if registered)."""
    if ENTRY:
        return ENTRY[0]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "cifkit", "--help"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=env, timeout=120,
    )
    registered = proc.returncode == 0 and all(
        cmd in proc.stdout for cmd in ("teach", "bravais", "metals", "fec")
    )
    ENTRY.append(
        [sys.executable, "-m", "cifkit"] if registered
        else [sys.executable, "-m", "cifkit.usecases_cli"]
    )
    return ENTRY[0]


def _run(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [*_entry(), *args], cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=timeout,
    )


def _json(proc: subprocess.CompletedProcess) -> dict:
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)  # must not raise: stdout is pure JSON in --json mode


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------------------- #
# help / argparse surface
# --------------------------------------------------------------------------- #
def test_top_level_help_lists_four_commands():
    proc = _run(["--help"])
    assert proc.returncode == 0, proc.stderr
    for cmd in ("teach", "bravais", "metals", "fec"):
        assert cmd in proc.stdout


@pytest.mark.parametrize(
    "cmd,flags",
    [
        ("teach", ["--spacegroup", "--outdir", "--offline", "--online", "--json"]),
        ("bravais", ["--outdir", "--bain-range", "--json"]),
        ("metals", ["--outdir", "--elements", "--zip", "--no-zip", "--json"]),
        ("fec", ["--outdir", "--zip", "--no-zip", "--json"]),
    ],
)
def test_command_help(cmd, flags):
    proc = _run([cmd, "--help"])
    assert proc.returncode == 0, proc.stderr
    for flag in flags:
        assert flag in proc.stdout, f"{flag} missing from `cifkit {cmd} --help`"


# --------------------------------------------------------------------------- #
# teach: cached Fd-3m examples -> spglib verification -> CSV + PNG
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    not U1_CACHE.is_dir() or not any(U1_CACHE.glob("*.cif")),
    reason="u1_fd3m 缓存缺失（联网用例，CI 可跳过）",
)
def test_teach_offline_produces_png_and_csv(tmp_path):
    out = tmp_path / "teach"
    proc = _run(["teach", "--outdir", str(out), "--offline", "--json"])
    data = _json(proc)
    assert data["ok"] is True, data
    assert data["examples"] == 6 and data["verified_227"] == 6
    png = out / "figures" / "fd3m_examples.png"
    csv_path = out / "data" / "examples.csv"
    assert png.is_file() and png.stat().st_size > 10_000
    rows = _read_csv(csv_path)
    assert len(rows) == 6
    assert all(str(r["verified_227"]).strip() in {"1", "True"} for r in rows)
    assert all(r["sg_number"] == "227" and r["point_group"] == "m-3m" for r in rows)


# --------------------------------------------------------------------------- #
# bravais: Bain path + 14 Bravais lattices (small step for speed)
# --------------------------------------------------------------------------- #
def test_bravais_small_range(tmp_path):
    out = tmp_path / "bravais"
    proc = _run(["bravais", "--outdir", str(out), "--bain-range", "0.9:1.7:0.05", "--json"])
    data = _json(proc)
    assert data["ok"] is True, data
    assert data["bain_points"] >= 15
    assert data["bravais_lattices"] == 14 and data["bravais_verified"] == 14
    assert data["equivalences"] >= 4
    assert data["equivalences_verified"] == data["equivalences"]
    # the two special metrics must come back as cI (#229) and cF (#225)
    specials = data["bain_specials"]
    assert int(specials["1.0"]["spacegroup_number"]) == 229  # bcc cI
    assert int(specials["1.414214"]["spacegroup_number"]) == 225  # fcc cF
    for name in ("bain_path.csv", "bain_tolerance.csv", "bravais14.csv",
                 "equivalences.csv", "hR_alpha_scan.csv"):
        assert (out / "data" / name).is_file(), name
    assert len(list((out / "figures").glob("*.png"))) == 3
    assert len(_read_csv(out / "data" / "bravais14.csv")) == 14


# --------------------------------------------------------------------------- #
# fec: offline hull + structures + VASP templates + kit zip
# --------------------------------------------------------------------------- #
def test_fec_offline_kit(tmp_path):
    out = tmp_path / "fec"
    proc = _run(["fec", "--outdir", str(out), "--zip", "--json"])
    data = _json(proc)
    assert data["ok"] is True, data
    assert data["structures"] == 7
    assert data["vasp_input_dirs"] >= 7
    assert data["hull_points"] > 0
    fe3c = data["fe3c"]
    assert fe3c is not None
    assert abs(float(fe3c["energy_formation_eV_per_atom"]) - 0.0456) < 1e-3
    assert fe3c["status"] == "metastable"
    for name in ("fe_c_hull.png",):
        assert (out / "figures" / name).is_file()
    for name in ("aflow_fe_c_energies.csv", "fe_c_compounds.csv", "hull_points.csv"):
        assert (out / "data" / name).is_file(), name
    for name in ("fe3c_cementite", "fe23c6", "ref_fe_bcc"):
        assert (out / "vasp_inputs" / name / "POSCAR").is_file(), name
    assert (out / "fe_c_kit.zip").is_file() and (out / "fe_c_kit.zip").stat().st_size > 10_000
    assert data["zip"].endswith("fe_c_kit.zip")


# --------------------------------------------------------------------------- #
# metals: subset of three elements, bulk/slab/POSCAR/CSV checks
# --------------------------------------------------------------------------- #
def test_metals_subset_fe_cu_mg(tmp_path):
    out = tmp_path / "metals"
    proc = _run(["metals", "--outdir", str(out), "--elements", "Fe,Cu,Mg", "--no-zip", "--json"])
    data = _json(proc)
    assert data["ok"] is True, data
    assert data["n_exported"] == 3
    assert set(data["elements_exported"]) == {"Fe", "Cu", "Mg"}
    for element in ("Fe", "Cu", "Mg"):
        d = out / "elements" / element
        for name in ("bulk.cif", "bulk_POSCAR", "slab.cif", "slab_POSCAR",
                     "lattice.csv", "INCAR", "KPOINTS"):
            assert (d / name).is_file(), f"{element}/{name}"
        # the slab POSCAR must be a real structure and not empty
        assert (d / "slab_POSCAR").stat().st_size > 100
    summary = _read_csv(out / "metals_summary.csv")
    assert len(summary) == 3
    by_el = {row["element"]: row for row in summary}
    assert set(by_el) == {"Fe", "Cu", "Mg"}
    assert all(float(row["vacuum_measured"]) >= 15.0 for row in summary)
    assert by_el["Fe"]["densest_plane"] == "(110)"
    assert by_el["Cu"]["densest_plane"] == "(111)"
    assert by_el["Mg"]["densest_plane"] == "(0001)"
    assert not (out / "metals_kit.zip").exists()  # --no-zip


@pytest.mark.skipif(not FULL, reason="opt-in full-ish run via CIFKIT_USECASE_FULL=1")
def test_metals_zip_full(tmp_path):
    out = tmp_path / "metals_zip"
    proc = _run(["metals", "--outdir", str(out), "--elements", "Fe,Cu,Mg", "--zip", "--json"])
    data = _json(proc)
    assert data["ok"] is True, data
    assert (out / "metals_kit.zip").is_file()


# --------------------------------------------------------------------------- #
# error handling: clear exit codes + messages
# --------------------------------------------------------------------------- #
def test_teach_unknown_spacegroup_exits_2(tmp_path):
    proc = _run(["teach", "--outdir", str(tmp_path / "x"), "--spacegroup", "Pnma"])
    assert proc.returncode == 2
    assert "Fd-3m" in proc.stderr


def test_bravais_bad_range_exits_2(tmp_path):
    proc = _run(["bravais", "--outdir", str(tmp_path / "x"), "--bain-range", "1.7:0.9:0.01"])
    assert proc.returncode == 2
    assert "bain-range" in proc.stderr


def test_metals_unknown_element_exits_nonzero_with_json(tmp_path):
    proc = _run(["metals", "--outdir", str(tmp_path / "x"), "--elements", "Xx", "--json"])
    assert proc.returncode == 2
    payload = json.loads(proc.stdout)  # error JSON must still be pure JSON
    assert payload["ok"] is False
    assert "Xx" in proc.stderr
