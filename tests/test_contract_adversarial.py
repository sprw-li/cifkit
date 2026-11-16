"""Adversarial contract tests (round 57): the envelope schema and numeric bounds
must also hold for hostile input, not only for well-formed requests.

README/docs/API.md sell "派发前契约校验" as an embedding feature; these tests pin
the two input classes that previously sailed through it:

* NaN/±Infinity — a plain ``value < minimum`` comparison is always False for
  NaN, so every bound was vacuously true and the junk value became a 500 in
  the op (``int(limit)``, ``np.linspace(nan, ...)``);
* envelope junk — the handler used to rebuild ``{"op", "params"}`` before
  validating, which turned the top-level ``additionalProperties: false`` and
  the ``auth`` typing in ``schemas/request.json`` into dead code.
"""
from __future__ import annotations

import json
import math

from cifkit.service import handle


def _invalid(request: dict) -> dict:
    response = handle(request)
    assert response["ok"] is False, request
    assert response["error"]["code"] == "invalid-request", request
    assert response["http_status"] == 400, request
    return response


def test_numeric_params_reject_nan_and_infinity():
    # number-typed params pass the type check and must be caught by the
    # finiteness guard (a plain bound comparison never trips on NaN)
    number_cases = [
        {"op": "features", "params": {"path": "whatever.cif", "rdf_max": float("nan")}},
        {"op": "features", "params": {"path": "whatever.cif", "symprec": math.inf}},
        {"op": "validate", "params": {"path": "whatever.cif", "vacuum": float("nan")}},
        {"op": "validate", "params": {"path": "whatever.cif", "vacuum": math.inf}},
    ]
    for request in number_cases:
        response = _invalid(request)
        blob = json.dumps(response["error"], allow_nan=False)
        assert "finite" in blob, (request, blob)
    # integer-typed params are already caught by the type check (NaN/inf are
    # floats); the requirement is only that they cannot reach the op
    integer_cases = [
        {"op": "fetch", "params": {"limit": float("nan")}},
        {"op": "fetch", "params": {"limit": math.inf}},
        {"op": "fetch", "params": {"limit": -math.inf}},
        {"op": "dataset_rows", "params": {"dataset_dir": "d", "limit": float("nan")}},
        {"op": "dataset_rows", "params": {"dataset_dir": "d", "offset": -math.inf}},
        {"op": "features_many", "params": {"paths": ["a.cif"], "offset": float("nan")}},
        {"op": "features_many", "params": {"paths": ["a.cif"], "limit": math.inf}},
    ]
    for request in integer_cases:
        response = _invalid(request)
        assert response["error"]["code"] == "invalid-request"


def test_finite_values_still_pass_the_bounds():
    """Finite numeric params pass the contract and reach dispatch: the error that
    comes back is the op's own not-found, not a contract violation."""
    response = handle({"op": "dataset_rows", "params": {"dataset_dir": "no-such-dir",
                                                        "offset": 0, "limit": 10}})
    assert response["ok"] is False
    assert response["error"]["code"] == "not-found"
    violations = json.dumps(response["error"])
    assert "finite" not in violations and "minimum" not in violations and "maximum" not in violations


def test_handle_rejects_unknown_top_level_keys_and_bad_auth():
    response = _invalid({"op": "capabilities", "junk": 1})
    assert "junk" in json.dumps(response["error"])
    response = _invalid({"op": "capabilities", "auth": "not-an-object"})
    assert "auth" in json.dumps(response["error"])
    response = _invalid({"op": "not-an-op"})
    assert response["error"]["code"] == "invalid-request"


def test_handle_still_accepts_well_formed_requests_with_auth():
    response = handle({"op": "capabilities", "auth": {"tenant": "t1"}})
    assert response["ok"] is True
    assert response["op"] == "capabilities"


def test_contract_rejects_nan_at_the_schema_level():
    """The schema files a platform generates from must behave like the dispatcher."""
    from cifkit.contract import validate_against

    violations = validate_against(float("nan"), {"type": "number", "minimum": 0})
    assert violations, "NaN must not pass a minimum:0 bound"
    violations = validate_against(math.inf, {"type": "integer", "maximum": 200})
    assert violations
    assert validate_against(5, {"type": "integer", "minimum": 1, "maximum": 200}) == []


def test_responses_are_strict_json_for_degenerate_structures(tmp_path):
    """API.md:25 promises "返回值全部 JSON 可序列化" — pin it with strict parsing
    (parse_constant=raise) on the responses for a single-atom structure, where
    'no neighbour' edges historically produced math.inf.

    Provenance note (round 57): the adversarial review claimed the HTTP body for
    this case contained ``Infinity``; that did **not** reproduce at HEAD
    (checks.py maps non-finite distances to None at the metrics stage).  The
    guard below keeps it that way, and service._send now refuses non-finite
    bodies loudly instead of emitting invalid JSON.
    """
    from pymatgen.core import Lattice, Structure
    from pymatgen.io.cif import CifWriter

    cif = str(CifWriter(Structure(Lattice.cubic(5.0), ["Na"], [[0, 0, 0]])))
    strict_loads = lambda text: json.loads(text, parse_constant=lambda name: (_ for _ in ()).throw(
        ValueError(f"non-JSON constant {name}")))
    for op, params in (("validate", {}), ("features", {"rdf": True})):
        response = handle({"op": op, "params": {"cif_text": cif, **params}})
        assert response["ok"] is True, response
        strict_loads(json.dumps(response, allow_nan=False))  # no NaN/Infinity anywhere


def test_rejected_request_echo_is_strictly_serialisable():
    """Round 57 adversarial F3: the 400 that *carries the violations* used to
    contain the raw (non-finite) params in params_echo, which made the 400 itself
    non-serialisable — the client saw a 500 instead.  The echo must be cleaned."""
    response = _invalid({"op": "features", "params": {"path": "a.cif", "symprec": math.inf}})
    blob = json.dumps(response, allow_nan=False)  # must not raise
    assert "inf" in blob  # the offending value survives as a repr string
    assert "finite" in blob
