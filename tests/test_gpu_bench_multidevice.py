"""Multi-GPU benchmark must time each device on that device (round 31).

The first 2xL20 run reported device 1 at 110 TFLOPS with CV 0.82 — a bogus number
caused by CUDA events being recorded on the *current* device (0) while the matmul
ran on device 1.  The fix wraps everything in ``torch.cuda.device(index)``.  These
tests pin the fix statically (the real numbers need a GPU).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / "cloud_gpu" / "gpu_bench.py"


@pytest.fixture(scope="module")
def payload():
    spec = importlib.util.spec_from_file_location("gpu_bench", PAYLOAD)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_bench_device_uses_a_device_context(payload):
    source = PAYLOAD.read_text(encoding="utf-8")
    body = source[source.index("def bench_device"):source.index("def concurrent_aggregate")]
    assert "with torch.cuda.device(index):" in body
    assert "torch.cuda.synchronize(index)" in body


def test_concurrent_bench_runs_per_device_threads(payload):
    source = PAYLOAD.read_text(encoding="utf-8")
    body = source[source.index("def concurrent_aggregate"):source.index("def main()")]
    assert "threading.Thread" in body
    assert "scaling_efficiency" in body
    assert "with torch.cuda.device(index):" in body


def test_multi_device_is_reported(payload):
    source = PAYLOAD.read_text(encoding="utf-8")
    assert 'report["multi_device"] = safe("multi_device", multi)' in source
    assert '"device_count"' in source and '"concurrent"' in source


def test_result_shape_is_self_describing(payload):
    """A reader must be able to tell what was measured and on which card."""
    source = PAYLOAD.read_text(encoding="utf-8")
    for field in ("status", "device_name", "device_count", "math_mode", "params",
                  "checksum", "errors"):
        assert f'"{field}"' in source, field
