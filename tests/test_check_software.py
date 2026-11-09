"""The software-acceptance harness itself (H3) must work before software exists.

We cannot install VASP/QE/CP2K here, so the harness is validated against **stub
executables**: detection → minimal input → run → success-marker check.  This is
honest about what it proves: the harness works, the real codes remain unverified.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
cs = pytest.importorskip("check_software")


def _stub(directory: Path, body: str, name: str = "stub-bin") -> Path:
    """Create a cross-platform stub executable that runs ``body`` as Python."""
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / f"{name}.py"
    script.write_text(body, encoding="utf-8")
    if sys.platform == "win32":
        launcher = directory / f"{name}.bat"
        launcher.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
        return launcher
    launcher = directory / name
    launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
    launcher.chmod(0o755)
    return launcher


def _spec(marker: str = "DONE") -> cs.Software:
    return cs.Software(name="Stub", binaries=("stub-bin",), min_case="stub",
                       success_marker=marker)


def _wire(monkeypatch, tmp_path, body: str, marker: str = "DONE"):
    stub = _stub(tmp_path / "bin", body)
    spec = _spec(marker)
    monkeypatch.setattr(cs.shutil, "which",
                        lambda name: str(stub) if name in ("stub-bin", stub.name) else None)
    monkeypatch.setattr(cs, "minimal_case_path",
                        lambda software, directory: (directory / "in.txt", "stub-bin in.txt"))
    return spec


def test_detect_finds_installed_binary(monkeypatch, tmp_path):
    spec = _wire(monkeypatch, tmp_path, "print('DONE')\n")
    cs.detect(spec)
    assert spec.found and spec.runnable


def test_not_installed_is_reported(monkeypatch):
    spec = _spec()
    monkeypatch.setattr(cs.shutil, "which", lambda name: None)
    cs.detect(spec)
    assert spec.found is None and not spec.runnable


def test_run_verified_when_marker_appears(monkeypatch, tmp_path):
    spec = _wire(monkeypatch, tmp_path, "print('hello'); print('DONE')\n")
    cs.detect(spec)
    cs.run_case(spec, timeout=60)
    assert spec.run_status == "verified", spec.run_detail


def test_run_without_marker_is_not_verified(monkeypatch, tmp_path):
    spec = _wire(monkeypatch, tmp_path, "print('finished but nothing else')\n")
    cs.detect(spec)
    cs.run_case(spec, timeout=60)
    assert spec.run_status == "ran-no-marker"


def test_nonzero_exit_is_failure(monkeypatch, tmp_path):
    spec = _wire(monkeypatch, tmp_path, "import sys; print('boom'); sys.exit(3)\n")
    cs.detect(spec)
    cs.run_case(spec, timeout=60)
    assert spec.run_status == "failed"
    assert "exit 3" in spec.run_detail


def test_timeout_is_reported(monkeypatch, tmp_path):
    spec = _wire(monkeypatch, tmp_path, "import time; time.sleep(30)\n")
    cs.detect(spec)
    cs.run_case(spec, timeout=1.0)
    assert spec.run_status == "timeout"


def test_missing_external_data_blocks_the_run(monkeypatch, tmp_path):
    spec = _wiper = cs.Software(name="Stub", binaries=("stub-bin",), data_env="CIFKIT_TEST_PP",
                                data_label="POTCAR", min_case="stub", success_marker="DONE")
    stub = _stub(tmp_path / "bin", "print('DONE')\n")
    monkeypatch.setattr(cs.shutil, "which",
                        lambda name: str(stub) if name in ("stub-bin", stub.name) else None)
    monkeypatch.delenv("CIFKIT_TEST_PP", raising=False)
    cs.detect(spec)
    assert spec.data_ok is False
    assert not spec.runnable, "main() only runs software when the data is present"
    # calling run_case directly is still safe: it refuses and says what is missing
    cs.run_case(spec, timeout=10)
    assert spec.run_status in ("no-minimal-case", "not-run")


def test_report_is_written_and_says_what_it_proves(monkeypatch, tmp_path):
    out = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["check_software.py", "--json", str(out)])
    monkeypatch.setattr(cs, "detect", lambda software: setattr(software, "found", None))
    assert cs.main() == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["counts"].get("not-installed") == len(cs.SOFTWARE)
    assert "≠" in report["honesty"] or "verified" in report["honesty"]
    assert all("min_case" in row and "success_marker" in row for row in report["software"])
