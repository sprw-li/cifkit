"""The cloud runner's NWChem memory spec must be self-consistent (round 29).

Real failures that cost three cloud jobs:
  * ``nwchem -memory "total …"`` and even ``nwchem -help`` -> "failed to open the
    input file" (Debian's build treats extra words as input filenames);
  * ``memory total X mb heap Y mb global Z mb`` with Y+Z > X ->
    ``Memory_Defaults: Inconsistent memory specification``.

These tests pin the arithmetic so the runner cannot regress.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def runner():
    spec = importlib.util.spec_from_file_location("run_our_template",
                                                  ROOT / "cloud_h3" / "run_our_template.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def parse(spec: str) -> dict[str, int]:
    parts = re.findall(r"(total|stack|heap|global)\s+(\d+)\s+mb", spec)
    return {name: int(value) for name, value in parts}


def test_parts_add_up_to_total(runner):
    values = parse(runner.memory_directive(0.6))
    assert set(values) == {"total", "stack", "heap", "global"}
    assert values["stack"] + values["heap"] + values["global"] == values["total"]


def test_positive_and_sized(runner):
    values = parse(runner.memory_directive(0.5))
    assert values["total"] >= 1024
    assert values["heap"] > 0 and values["stack"] > 0 and values["global"] > 0


def test_fraction_controls_the_total(runner):
    small = parse(runner.memory_directive(0.2))["total"]
    large = parse(runner.memory_directive(0.8))["total"]
    assert large > small


def test_runner_does_not_pass_memory_on_the_command_line(runner):
    """Debian's NWChem reads extra argv words as input filenames."""
    source = (ROOT / "cloud_h3" / "run_our_template.py").read_text(encoding="utf-8")
    assert '"-memory"' not in source
    assert "memory_directive" in source
