"""Packaging declarations (round 35).

The first wheel built here was missing ``cifkit/schemas/*.json``: the contract
validation and ``python -m cifkit.contract --dump`` would break in an installed
distribution.  These tests read ``pyproject.toml`` and the package tree, so the
declaration cannot silently regress.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def pyproject() -> dict:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_schemas_are_declared_as_package_data(pyproject):
    data = pyproject["tool"]["setuptools"]["package-data"]["cifkit"]
    assert any("schemas" in pattern for pattern in data), data


def test_topology_references_are_declared(pyproject):
    data = pyproject["tool"]["setuptools"]["package-data"]["cifkit"]
    assert any(pattern.startswith("data/") for pattern in data), data


def test_runtime_data_files_exist_in_the_tree():
    assert list((ROOT / "cifkit" / "schemas").glob("*.json"))
    references = list((ROOT / "cifkit" / "data" / "nets").glob("*-reference.cif"))
    assert len(references) == 6


def test_console_script_and_python_requirement(pyproject):
    assert pyproject["project"]["scripts"]["cifkit"] == "cifkit.cli:main"
    assert pyproject["project"]["requires-python"].startswith(">=3.11")


def test_check_package_report_is_clean_if_present():
    import json

    path = ROOT / "runs" / "check_package.json"
    if not path.is_file():
        pytest.skip("package check not run yet")
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["ok"], report.get("errors")
    assert report["packaged_schemas"], "wheel must ship schemas"
    probe = report.get("probe") or {}
    assert probe.get("is_target_copy") is True, "must import the installed copy, not the source"
    assert probe.get("capabilities_ok") is True
    assert all((report.get("topology") or {}).values()), report.get("topology")
