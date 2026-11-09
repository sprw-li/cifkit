"""Machine-readable API contract (cifkit.contract) + dumped schema files."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cifkit import api, contract
from cifkit.service import handle

DATA = Path(__file__).resolve().parent / "data"
ZIF8 = DATA / "zif8_cr_sod.cif"
SCHEMAS = Path(contract.__file__).resolve().parent / "schemas"


def test_op_schemas_cover_every_operation():
    from cifkit.service import OPS

    assert set(contract.OP_SCHEMAS) == set(OPS), "schemas and ops drifted apart"


def test_validate_request_accepts_good_requests():
    assert contract.validate_request({"op": "capabilities", "params": {}}) == []
    assert contract.validate_request({"op": "features", "params": {"path": "a.cif"}}) == []
    assert contract.validate_request(
        {"op": "features_many", "params": {"paths": ["a.cif"], "jobs": 2}}) == []
    assert contract.validate_request(
        {"op": "convert", "params": {"path": "a.cif", "formats": ["vasp"], "bundles": ["qe"]}}) == []
    assert contract.validate_request(
        {"op": "dataset", "params": {"runs_dir": "runs", "outdir": "ds"}}) == []
    assert contract.validate_request({"op": "topology", "params": {"path": "a.cif", "net": "sod"}}) == []


def test_validate_request_rejects_bad_requests():
    assert contract.validate_request(None)
    assert contract.validate_request({"params": {}})  # missing op
    assert contract.validate_request({"op": "nope", "params": {}})
    assert contract.validate_request({"op": "features", "params": {"nope": 1}})
    assert contract.validate_request({"op": "features", "params": {"rdf_bins": 0}})
    assert contract.validate_request({"op": "features_many", "params": {"paths": []}})
    assert contract.validate_request({"op": "dataset", "params": {"runs_dir": "runs"}})  # outdir required
    assert contract.validate_request({"op": "topology", "params": {"net": "made-up"}})
    assert contract.validate_request({"op": "convert", "params": {"title": 5}})


def test_service_returns_contract_violations():
    response = handle({"op": "features", "params": {"rdf_max": -1}})
    assert response["ok"] is False and response["http_status"] == 400
    assert response["error"]["code"] == "invalid-request"
    violations = response["error"]["detail"]["violations"]
    assert any("rdf_max" in v for v in violations)


def test_service_response_matches_schema_for_every_op(tmp_path):
    """Every op's successful response must satisfy RESPONSE_SCHEMA and FEATURE_ROW_SCHEMA."""
    runs = tmp_path / "runs" / "r1"
    runs.mkdir(parents=True)
    (runs / "standardized.cif").write_bytes(ZIF8.read_bytes())
    (runs / "manifest.json").write_text(json.dumps({
        "ok": True, "artifacts": {"standardized.cif": str(runs / "standardized.cif")},
        "source": {"source": "local", "record": {"record_id": "local:x"}},
    }), encoding="utf-8")

    requests = [
        {"op": "capabilities", "params": {}},
        {"op": "features", "params": {"path": str(ZIF8), "rdf": False, "rings": True}},
        {"op": "features_many", "params": {"paths": [str(ZIF8)], "rdf": False}},
        {"op": "convert", "params": {"path": str(ZIF8), "formats": ["vasp"]}},
        {"op": "dataset", "params": {"runs_dir": str(tmp_path / "runs"),
                                     "outdir": str(tmp_path / "ds"), "rdf": False}},
        {"op": "topology", "params": {"path": str(ZIF8)}},
        {"op": "validate", "params": {"path": str(ZIF8)}},
    ]
    for request in requests:
        response = handle(request)
        assert response["ok"] is True, (request["op"], response)
        assert contract.validate_response(response) == [], request["op"]
    features_response = handle(requests[1])
    assert contract.validate_against(features_response["data"], contract.FEATURE_ROW_SCHEMA) == []


def test_accepts_openbabel_free_environment():
    """The API must not import Open Babel (GPL): the module list is checked directly."""
    import subprocess
    import sys

    code = (
        "import sys\n"
        "class B:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ('openbabel', 'pybel'):\n"
        "            raise ImportError('blocked')\n"
        "        return None\n"
        "sys.meta_path.insert(0, B())\n"
        "from cifkit import api\n"
        "r = api.convert(path=r'{}', formats=['vasp'])\n"
        "print('OK', len(r['formats']['vasp']['text']))\n"
    ).format(ZIF8)
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("OK"), proc.stdout


def test_dumped_schemas_match_the_code():
    """cifkit/schemas/*.json must stay in sync with the in-code contract."""
    expected = {
        "request.json": contract.REQUEST_SCHEMA,
        "response.json": contract.RESPONSE_SCHEMA,
        "feature_row.json": contract.FEATURE_ROW_SCHEMA,
    }
    for name, payload in expected.items():
        path = SCHEMAS / name
        assert path.is_file(), f"{name} not dumped; run `python -m cifkit.contract --dump`"
        assert json.loads(path.read_text(encoding="utf-8")) == payload, f"{name} is stale"
    ops = json.loads((SCHEMAS / "ops.json").read_text(encoding="utf-8"))
    assert ops["properties"] == contract.OP_SCHEMAS
