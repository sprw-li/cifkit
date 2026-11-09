"""Cloud-GPU escalation wrapper: the cost/credential gates must be unbreakable.

These tests never touch the network.  They pin the properties that protect the
user's photons: no credentials ⇒ no submit; no ``--go`` ⇒ dry-run only; and the
input bundle is reproducible.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("cloud_h3_submit", ROOT / "scripts" / "cloud_h3_submit.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def wrapper():
    return _load()


def test_credentials_state_only_reports_presence(wrapper, monkeypatch):
    for name in wrapper.CREDENTIAL_VARS:
        monkeypatch.delenv(name, raising=False)
    assert wrapper.credentials_state() == {name: False for name in wrapper.CREDENTIAL_VARS}
    monkeypatch.setenv(wrapper.CREDENTIAL_VARS[1], "x")
    state = wrapper.credentials_state()
    assert state[wrapper.CREDENTIAL_VARS[1]] is True
    assert "x" not in json.dumps(state), "values must never be echoed"


def test_input_bundle_is_reproducible(wrapper):
    first = wrapper.build_zip()
    digest_a = hashlib.sha256(first.read_bytes()).hexdigest()
    second = wrapper.build_zip()
    digest_b = hashlib.sha256(second.read_bytes()).hexdigest()
    assert digest_a == digest_b
    import zipfile

    with zipfile.ZipFile(second) as archive:
        names = set(archive.namelist())
    assert {"run_acceptance.py", "README.md"} <= names
    assert any(name.startswith("cases/") for name in names)


def test_go_without_credentials_refuses_and_stays_offline(wrapper):
    """The whole point: never spend photons by accident.

    The subprocess uses the *real* ``runs/cloud_h3`` directory (monkeypatching the
    parent cannot reach it), so this test watches that directory instead.
    """
    import os
    import time

    out_dir = wrapper.OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in ("cli_probe.log", "cli_submit.log", "submit_probe.json"):
        (out_dir / stale).unlink(missing_ok=True)
    marker = out_dir / "dryrun_probe.json"
    before = marker.stat().st_mtime if marker.exists() else 0.0

    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "cloud_h3_submit.py"),
                           "--go", "--stage", "probe"],
                          cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=900,
                          env={k: v for k, v in os.environ.items()
                               if k not in wrapper.CREDENTIAL_VARS})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "refusing to submit" in proc.stdout
    assert "missing credentials" in proc.stdout
    # only the zero-network dry-run ran: no probe/submit evidence was produced
    assert not (out_dir / "cli_probe.log").exists(), "probe must not run without credentials"
    assert not (out_dir / "cli_submit.log").exists(), "submit must not run without credentials"
    assert not (out_dir / "submit_probe.json").exists()
    # the payload is still verifiable
    assert marker.is_file() and marker.stat().st_mtime >= before


def test_stage_defaults_are_cheap(wrapper):
    probe_label, probe_command, probe_minutes, probe_wait, _ = wrapper.STAGES["probe"]
    assert probe_minutes <= 10, "the default stage must stay in the 'tiny probe' bracket"
    assert "run_acceptance.py" in probe_command
    assert wrapper.DEFAULT_PRICE == 5.5
