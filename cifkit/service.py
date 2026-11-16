"""Service layer: mount cifkit behind any web framework (or as a bare HTTP server).

``handle(request)`` is the whole protocol: a plain dict in, a plain dict out, no
framework imports, no global state.  That makes it trivial to mount:

FastAPI::

    from fastapi import FastAPI
    from cifkit.service import handle
    app = FastAPI()
    @app.post("/rpc")
    def rpc(request: dict):
        return handle(request)

Flask::

    from flask import Flask, request, jsonify
    from cifkit.service import handle
    app = Flask(__name__)
    @app.post("/rpc")
    def rpc():
        return jsonify(handle(request.get_json()))

AWS Lambda::

    from cifkit.service import handle
    def lambda_handler(event, context):
        return handle(event)

Request shape (``docs/API.md``)::

    {"op": "features", "params": {"path": "a.cif", "rdf": false}}

Response shape::

    {"ok": true,  "op": "features", "api_version": "1.0", "data": {...}}
    {"ok": false, "op": "features", "api_version": "1.0", "error": {"code": ..., "message": ...}}

Authentication, quotas, tenancy and rate limiting are **deliberately not** part of
this module: the embedding platform owns those (see ``docs/LIMITATIONS.md`` §J).
"""
from __future__ import annotations

import json
import math
import time
from typing import Any, Callable

from cifkit import api
from cifkit.api import API_VERSION, CifkitError, InvalidRequest
from cifkit.contract import validate_request, validate_response

#: operations callable through the service (mirrors :data:`cifkit.api.OPS`)
OPS: dict[str, Callable[..., dict[str, Any]]] = dict(api.OPS)

#: parameters that must never be echoed back to the caller (secret hygiene)
_SECRET_KEYS = {"api_key", "mp_api_key", "pmg_mapi_key", "authorization", "token", "password"}


def _reject_constant(name: str) -> None:
    """``json.loads(parse_constant=...)`` hook: NaN/Infinity are not JSON.

    RFC 8259 has no constants; Python's json module accepts them by default,
    which let a hand-written body smuggle them past the boundary and blow up
    later as a 500.  Raising here turns them into a clean 400 (round 57).
    """
    raise ValueError(f"non-JSON constant {name} in request body")


def _finite_float(text: str) -> float:
    """``json.loads(parse_float=...)`` hook: ``1e309`` is *valid JSON* that
    overflows to ``inf`` — without this hook such a body sailed past
    ``parse_constant`` (round 57 adversarial F3) and only died at the op."""
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"number {text} overflows to a non-finite value")
    return value


def _sanitize_nonfinite(value: Any) -> Any:
    """Make a value strictly JSON-serialisable (error echoes may carry the very
    params that were rejected for being non-finite — round 57 adversarial F3:
    without this, the 400 with the violations could not be serialised and
    degraded into a 500)."""
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)  # "nan" / "inf" / "-inf" — echo only, never dispatched
    if isinstance(value, dict):
        return {key: _sanitize_nonfinite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_nonfinite(item) for item in value]
    return value


def _redact(params: dict[str, Any]) -> dict[str, Any]:
    return {k: ("***" if k.lower() in _SECRET_KEYS else v) for k, v in (params or {}).items()}


def handle(request: Any) -> dict[str, Any]:
    """Execute one API request.  Never raises for bad input (maps to an error dict)."""
    started = time.time()
    op = None
    params: dict[str, Any] = {}
    if not isinstance(request, dict):
        return _error(None, InvalidRequest(f"request must be an object, got {type(request).__name__}"),
                      started)
    op = request.get("op")
    params = request.get("params") or {}
    if not isinstance(params, dict):
        return _error(op, InvalidRequest("params must be an object"), started)
    if not op or not isinstance(op, str):
        return _error(op, InvalidRequest(f"op is required; known ops: {sorted(OPS)}"), started)
    func = OPS.get(op)
    if func is None:
        return _error(op, InvalidRequest(f"unknown op {op!r}; known ops: {sorted(OPS)}"), started)
    # contract check first: schema violations become a 400 with the exact paths.
    # round 57: validate the *original* request object, so the envelope schema's
    # additionalProperties:false and auth typing are live checks — rebuilding
    # {"op","params"} here had silently turned both into dead code.
    violations = validate_request(request)
    if violations:
        return _error(op, InvalidRequest("request does not match the API contract",
                                         detail={"violations": violations}), started, params=params)
    try:
        data = func(**params)
    except CifkitError as exc:
        return _error(op, exc, started, params=params)
    except TypeError as exc:  # wrong/extra parameter names
        return _error(op, InvalidRequest(f"bad parameters for {op}: {exc}"), started, params=params)
    except FileNotFoundError as exc:
        return _error(op, api.NotFound(str(exc)), started, params=params)
    except Exception as exc:  # noqa: BLE001 - never leak a traceback to the caller
        return _error(op, exc, started, params=params)
    response = {
        "ok": True,
        "op": op,
        "api_version": API_VERSION,
        "elapsed_ms": round((time.time() - started) * 1000, 1),
        "data": data,
    }
    violations = validate_response(response)
    if violations:  # programming error on our side: fail loudly, not silently
        return _error(op, CifkitError(f"response envelope violated the contract: {violations}",
                                      detail={"violations": violations}), started, params=params)
    return response


def _error(op: Any, exc: Exception, started: float, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(exc, CifkitError):
        payload = exc.to_dict()
        status = exc.http_status
    else:
        payload = {"code": "internal-error", "message": f"{type(exc).__name__}: {exc}"}
        status = 500
    out: dict[str, Any] = {
        "ok": False,
        "op": op,
        "api_version": API_VERSION,
        "elapsed_ms": round((time.time() - started) * 1000, 1),
        "error": payload,
        "http_status": status,
    }
    if params is not None:
        out["params_echo"] = _sanitize_nonfinite(_redact(params))
    return out


def health() -> dict[str, Any]:
    """Cheap readiness probe (no imports of heavy optional deps)."""
    return {"ok": True, "api_version": API_VERSION, "ops": sorted(OPS),
            "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


# ---------------------------------------------------------------------------
# optional: zero-dependency HTTP server (for local integration tests / demos)
# ---------------------------------------------------------------------------
def make_handler(policy=None):  # pragma: no cover - exercised through tests via serve()
    from http.server import BaseHTTPRequestHandler

    from cifkit.platform import Policy, check_params

    active_policy = policy or Policy()

    class _Handler(BaseHTTPRequestHandler):
        server_version = "cifkit-service"

        def _send(self, payload: dict[str, Any], status: int = 200) -> None:
            # round 57: strict JSON on the wire.  allow_nan=False fails *loudly*
            # (clean 500) instead of silently emitting NaN/Infinity bodies that
            # RFC 8259 clients (JSON.parse, JSONSchema validators) cannot read.
            try:
                body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            except ValueError:
                body = json.dumps({"ok": False, "error": {"code": "internal-error",
                                   "message": "response contained non-finite floats and was refused"}},
                                  ensure_ascii=False, allow_nan=False).encode("utf-8")
                status = 500
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_chunked(self, chunks) -> None:
            """Stream ``chunks`` as NDJSON (round 52, J4) with chunked encoding."""
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            sent = 0
            try:
                for chunk in chunks:
                    body = chunk.encode("utf-8")
                    self.wfile.write(f"{len(body):X}\r\n".encode("ascii") + body + b"\r\n")
                    sent += 1
                self.wfile.write(b"0\r\n\r\n")
            except (BrokenPipeError, ConnectionResetError):
                # the client hung up: stop pulling rows (this is what streaming is for)
                pass
        def do_GET(self) -> None:  # noqa: N802 - stdlib API
            from urllib.parse import parse_qs, urlparse

            parsed = urlparse(self.path)
            route = parsed.path.rstrip("/") or "/"
            if route in ("", "/health"):
                self._send(health())
                return
            if route == "/stream/dataset_rows":
                from cifkit.api import stream_dataset_rows_ndjson

                query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
                # round 57: numeric params are parsed and bounded *here* — int()
                # used to run outside any try, so ?offset=abc killed the
                # connection with a traceback instead of a JSON 400; and the
                # policy check claimed limit=1_000_000 while the actual call was
                # unbounded (None), so the route did not honour the contract's
                # dataset_rows maximum of 10000.
                try:
                    params = {"dataset_dir": query.get("dir") or query.get("dataset_dir"),
                              "offset": int(query.get("offset", 0) or 0),
                              "limit": int(query["limit"]) if query.get("limit") else 10_000,
                              "with_features": str(query.get("with_features", "")).lower()
                              in ("1", "true", "yes")}
                except (TypeError, ValueError):
                    self._send({"ok": False, "error": {"code": "invalid-request",
                                                       "message": "offset/limit must be integers"}}, 400)
                    return
                if params["offset"] < 0 or not 1 <= params["limit"] <= 10_000:
                    self._send({"ok": False, "error": {"code": "invalid-request",
                                                       "message": "offset must be >= 0 and limit must be 1..10000 (contract dataset_rows)"}}, 400)
                    return
                if not params["dataset_dir"]:
                    self._send({"ok": False, "error": {"code": "invalid-request",
                                                       "message": "dir is required"}}, 400)
                    return
                try:
                    # the *same* policy checks as /rpc: a streaming route must not be a
                    # sandbox bypass (path resolution, tenant rules, size limits)
                    checked = check_params("dataset_rows", {
                        "dataset_dir": params["dataset_dir"],
                        "offset": params["offset"],
                        "limit": params["limit"],  # always a real int now (1..10000)
                        "with_features": params["with_features"]}, active_policy)
                except Exception as exc:  # noqa: BLE001 - report, never leak a traceback
                    code = getattr(exc, "code", "error")
                    status = 403 if code == "forbidden-path" else 400
                    self._send({"ok": False, "error": {"code": code, "message": str(exc)}},
                               status)
                    return
                params["dataset_dir"] = checked.get("dataset_dir", params["dataset_dir"])
                try:
                    chunks = stream_dataset_rows_ndjson(
                        dataset_dir=params["dataset_dir"], offset=params["offset"],
                        limit=params["limit"], with_features=params["with_features"])
                    self._send_chunked(chunks)
                except Exception as exc:  # noqa: BLE001
                    code = getattr(exc, "code", "error")
                    self._send({"ok": False, "error": {"code": code, "message": str(exc)}},
                               404 if code == "not-found" else 400)
                return
            self._send({"ok": False, "error": {"code": "not-found", "message": "use POST /rpc"}},
                       404)

        def do_POST(self) -> None:  # noqa: N802 - stdlib API
            if self.path.rstrip("/") != "/rpc":
                self._send({"ok": False, "error": {"code": "not-found", "message": "POST /rpc"}}, 404)
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                # round 57: reject NaN/Infinity literals at the boundary — JSON
                # forbids them, and letting them through produced non-serialisable
                # responses (500) instead of a clean 400.  parse_float additionally
                # catches *valid* JSON numbers that overflow to inf (1e309).
                request = json.loads(raw.decode("utf-8"),
                                     parse_constant=_reject_constant,
                                     parse_float=_finite_float)
            except Exception as exc:  # noqa: BLE001
                self._send({"ok": False, "error": {"code": "invalid-request",
                                                   "message": f"body is not JSON: {exc}"}}, 400)
                return
            response = handle(request)
            self._send(response, 200 if response.get("ok") else int(response.get("http_status", 500)))

        def log_message(self, fmt: str, *args: Any) -> None:  # keep the test output quiet
            return

    return _Handler


def serve(host: str = "127.0.0.1", port: int = 8765, *, background: bool = False,
          policy=None):
    """Start the stdlib HTTP server.  ``background=True`` returns ``(server, thread)``.

    ``policy`` is applied to the streaming route as well (round 52), so
    ``/stream/dataset_rows`` cannot read outside the sandbox.
    """
    from http.server import ThreadingHTTPServer
    import threading

    server = ThreadingHTTPServer((host, int(port)), make_handler(policy))
    if not background:
        server.serve_forever()
        return server
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


__all__ = ["OPS", "handle", "health", "make_handler", "serve"]
