"""The NWChem memory directive is required, and the export must say so (round 45).

Measured 2026-11-11 on the cloud (job `4f204600…`): five cutoffs, five aborts with
``electron_init: out of heap memory 0`` because the input had no ``memory`` line.
These tests pin the guidance we now ship, including the arithmetic NWChem demands.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pymatgen.core import Structure

from cifkit.export import write_structure

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "data" / "zif8_cr_sod.cif"


@pytest.fixture(scope="module")
def nwchem_text(tmp_path_factory):
    target = tmp_path_factory.mktemp("nwchem") / "mol.nw"
    write_structure(Structure.from_file(FIXTURE), target, fmt="nwchem")
    return target.read_text(encoding="utf-8")


def test_periodic_export_documents_the_memory_requirement(nwchem_text):
    assert "memory" in nwchem_text
    assert "out of heap memory" in nwchem_text
    assert "REQUIRED" in nwchem_text


def test_documented_example_arithmetic_adds_up(nwchem_text):
    """``total = stack + heap + global`` — NWChem rejects anything else."""
    line = next(line for line in nwchem_text.splitlines()
                if line.strip().startswith("#   memory total"))
    numbers = dict(re.findall(r"(total|stack|heap|global)\s+(\d+)", line))
    total = int(numbers["total"])
    parts = int(numbers["stack"]) + int(numbers["heap"]) + int(numbers["global"])
    assert parts == total, (numbers, parts, total)


def test_guidance_is_a_comment_not_an_active_directive(nwchem_text):
    """We must not hard-code a machine size into a runnable input."""
    for line in nwchem_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("memory total"):
            pytest.fail(f"active memory directive would pin a machine size: {line!r}")
    assert re.search(r"(?m)^\s*memory\b", nwchem_text) is None


def test_pspw_pattern_still_present(nwchem_text):
    # comments may *discuss* the rejected directives, so only active lines count
    active = "\n".join(line for line in nwchem_text.splitlines()
                       if not line.lstrip().startswith("#"))
    assert "nwpw" in active
    assert "cutoff 20" in active
    assert "task pspw energy" in active
    assert "task dft" not in active

def test_export_warns_that_the_default_cutoff_is_not_converged(nwchem_text):
    """Our own measurement: 20 -> 30 Ha moved 582 meV/atom, 30 -> 40 still 53."""
    assert "NOT a" in nwchem_text and "converged" in nwchem_text
    assert "582 meV/atom" in nwchem_text
    assert "53 meV/atom" in nwchem_text
    assert "MEASURED" in nwchem_text
