"""CLI coverage for `cifkit surface-energy` (round 49, limitation D3)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([PY, "-m", "cifkit", *args], cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=600)


def test_command_is_registered():
    proc = run("surface-energy", "--help")
    assert proc.returncode == 0, proc.stderr[-500:]
    assert "--slab-e" in proc.stdout
    assert "--bulk-per-atom" in proc.stdout


def test_cli_reproduces_the_module_value(tmp_path):
    out = tmp_path / "e.json"
    proc = run("surface-energy", "--slab-e", "-100", "--slab-atoms", "32",
               "--area", "100", "--bulk-per-atom", "-5", "--json", str(out))
    assert proc.returncode == 0, proc.stderr[-500:]
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["E_surf_eV_per_A2"] == 0.3
    assert payload["E_surf_J_per_m2"] == 4.80653
    assert "J/m²" in proc.stdout


def test_cli_accepts_total_bulk_energy():
    proc = run("surface-energy", "--slab-e", "-100", "--slab-atoms", "32",
               "--area", "100", "--bulk-e", "-80", "--bulk-atoms", "16")
    assert proc.returncode == 0, proc.stderr[-500:]
    assert "0.300000 eV/Å²" in proc.stdout


def test_cli_rejects_a_bad_formula_string():
    proc = run("surface-energy", "--slab-e", "-100", "--slab-atoms", "32",
               "--area", "100", "--bulk-per-atom", "-5",
               "--slab-formula", "ZnO", "--bulk-formula", "Zn:1,O:1")
    assert proc.returncode != 0
    assert "元素:个数" in (proc.stdout + proc.stderr)


def test_cli_reports_stoichiometry_errors_instead_of_a_number():
    proc = run("surface-energy", "--slab-e", "-100", "--slab-atoms", "32",
               "--area", "100", "--bulk-per-atom", "-5",
               "--slab-formula", "Zn:4,O:4,C:8", "--bulk-formula", "Zn:4,O:4")
    assert proc.returncode == 2
    assert "integer multiple" in proc.stdout


def test_cli_formula_check_passes_for_a_valid_multiple():
    proc = run("surface-energy", "--slab-e", "-100", "--slab-atoms", "32",
               "--area", "100", "--bulk-per-atom", "-5",
               "--slab-formula", "Zn:8,O:8", "--bulk-formula", "Zn:4,O:4")
    assert proc.returncode == 0, proc.stdout[-400:]
