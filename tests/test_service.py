"""Service layer (cifkit.service): protocol, error mapping, secret hygiene, HTTP mount."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from cifkit import api
from cifkit.service import OPS, handle, health, serve

DATA = Path(__file__).resolve().parent / "data"
ZIF8 = DATA / "zif8_cr_sod.cif"


def test_health_and_ops():
    h = health()
    assert h["ok"] is True and h["api_version"] == api.API_VERSION
    assert set(h["ops"]) == set(OPS) >= {"capabilities", "features", "convert", "topology", "validate"}
    json.dumps(h)


def test_handle_success_shape():
    response = handle({"op": "features", "params": {"path": str(ZIF8), "rdf": False}})
    assert response["ok"] is True and response["op"] == "features"
    assert response["api_version"] == api.API_VERSION
    assert response["data"]["natoms"] == 138
    assert isinstance(response["elapsed_ms"], (int, float))
    json.dumps(response)


def test_handle_error_mapping():
    unknown = handle({"op": "nope"})
    assert unknown["ok"] is False and unknown["error"]["code"] == "invalid-request"
    assert unknown["http_status"] == 400

    missing = handle({"op": "features", "params": {"path": "missing.cif"}})
    assert missing["error"]["code"] == "not-found" and missing["http_status"] == 404

    bad_format = handle({"op": "convert", "params": {"path": str(ZIF8), "formats": ["bogus"]}})
    assert bad_format["error"]["code"] == "unsupported-format" and bad_format["http_status"] == 400

    bad_params = handle({"op": "features", "params": {"nope": 1}})
    assert bad_params["error"]["code"] == "invalid-request"

    not_object = handle(["nope"])
    assert not_object["ok"] is False and not_object["error"]["code"] == "invalid-request"

    bad_params_type = handle({"op": "features", "params": "not-a-dict"})
    assert bad_params_type["error"]["code"] == "invalid-request"


def test_handle_never_leaks_secrets_or_tracebacks():
    response = handle({"op": "features",
                       "params": {"path": "missing.cif", "api_key": "SECRET-123", "token": "T0K"}})
    blob = json.dumps(response, ensure_ascii=False)
    assert "SECRET-123" not in blob and "T0K" not in blob
    assert response["params_echo"]["api_key"] == "***"
    # an unexpected internal failure must not surface a traceback string
    boom = handle({"op": "capabilities", "params": {}})
    assert boom["ok"] is True


def test_handle_capabilities_and_convert_roundtrip(tmp_path):
    caps = handle({"op": "capabilities", "params": {}})
    assert caps["ok"] and len(caps["data"]["formats"]) >= 31
    converted = handle({"op": "convert",
                        "params": {"path": str(ZIF8), "formats": ["xyz"], "outdir": str(tmp_path)}})
    assert converted["ok"] is True
    assert Path(converted["data"]["formats"]["xyz"]).is_file()


@pytest.mark.parametrize("op,params", [
    ("features", {"path": "missing.cif"}),
    ("topology", {"path": "missing.cif"}),
    ("validate", {"path": "missing.cif"}),
])
def test_missing_files_map_to_404(op, params):
    response = handle({"op": op, "params": params})
    assert response["http_status"] == 404


def test_http_server_smoke(tmp_path):
    """The stdlib server must expose /health and /rpc with correct status codes."""
    server, thread = serve("127.0.0.1", 0, background=True)
    try:
        port = server.server_address[1]
        base = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(f"{base}/health", timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            assert resp.status == 200 and body["ok"] is True

        payload = json.dumps({"op": "features",
                              "params": {"path": str(ZIF8), "rdf": False}}).encode()
        request = urllib.request.Request(f"{base}/rpc", data=payload,
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            assert resp.status == 200 and body["ok"] is True and body["data"]["natoms"] == 138

        bad = json.dumps({"op": "features", "params": {"path": "missing.cif"}}).encode()
        request = urllib.request.Request(f"{base}/rpc", data=bad,
                                         headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(request, timeout=30)
        assert excinfo.value.code == 404
        assert json.loads(excinfo.value.read().decode("utf-8"))["error"]["code"] == "not-found"

        with pytest.raises(urllib.error.HTTPError) as excinfo2:
            urllib.request.urlopen(f"{base}/nope", timeout=10)
        assert excinfo2.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
