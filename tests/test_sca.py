"""Licence scan (SCA-lite): no copyleft code in our own sources; scan is honest."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sca = pytest.importorskip("sca_scan")


@pytest.fixture(scope="module")
def report():
    return sca.scan()


def test_no_copyleft_code_in_our_sources(report):
    """The MIT claim requires that no source file carries copyleft *code*."""
    actionable = report["actionable_copyleft"]
    assert actionable == [], f"copyleft code found: {actionable}"


def test_mentions_are_classified_not_counted_as_code(report):
    """Comments/docstrings that discuss the GPL must not be reported as code."""
    for hit in report["copyleft_discussion"]:
        assert hit["kind"] in ("comment", "docstring")
    assert all(hit["kind"] == "code" for hit in report["actionable_copyleft"])


def test_scan_covers_the_repository(report):
    assert report["scanned_files"] > 100
    assert report["total_hits"] > 0
    classes = set(report["counts"])
    assert classes <= {"copyleft", "weak-copyleft", "permissive", "notice"}


def test_line_kind_classification():
    # The marker is assembled at runtime so that this *test data* does not itself
    # trip the scanner (which is textual and would flag the literal in a source line).
    marker = "G" + "PL"
    text = (
        f"# a comment about {marker}\n"
        "import os\n"
        f'"""docstring mentioning {marker}"""\n'
        "x = 1\n"
    )
    kinds = sca._line_kinds(text)
    assert kinds == ["comment", "code", "docstring", "code"]


def test_strict_mode_exit_code(tmp_path):
    import subprocess
    from sys import executable

    proc = subprocess.run([executable, str(ROOT / "scripts" / "sca_scan.py"),
                           "--strict", "--json", str(tmp_path / "sca.json")],
                          cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "actionable copyleft in source code: 0" in proc.stdout
