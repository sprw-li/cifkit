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
import time
from typing import Any, Callable

from cifkit import api
from cifkit.api import API_VERSION, CifkitError, InvalidRequest
from cifkit.contract import validate_request, validate_response

#: operations callable through the service (mirrors :data:`cifkit.api.OPS`)
OPS: dict[str, Callable[..., dict[str, Any]]] = dict(api.OPS)

#: parameters that must never be echoed back to the caller (secret hygiene)
_SECRET_KEYS = {"api_key", "mp_api_key", "pmg_mapi_key", "authorization", "token", "password"}


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
    # contract check first: schema violations become a 400 with the exact paths
    violations = validate_request({"op": op, "params": params})
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
        out["params_echo"] = _redact(params)
    return out


def health() -> dict[str, Any]:
    """Cheap readiness probe (no imports of heavy optional deps)."""
    return {"ok": True, "api_version": API_VERSION, "ops": sorted(OPS),
            "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


# ---------------------------------------------------------------------------
# optional: zero-dependency HTTP server (for local integration tests / demos)
# ---------------------------------------------------------------------------
def make_handler():  # pragma: no cover - exercised through tests via serve()
    from http.server import BaseHTTPRequestHandler

    class _Handler(BaseHTTPRequestHandler):
        server_version = "cifkit-service"

        def _send(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib API
            if self.path.rstrip("/") in ("", "/health"):
                self._send(health())
            else:
                self._send({"ok": False, "error": {"code": "not-found", "message": "use POST /rpc"}}, 404)

        def do_POST(self) -> None:  # noqa: N802 - stdlib API
            if self.path.rstrip("/") != "/rpc":
                self._send({"ok": False, "error": {"code": "not-found", "message": "POST /rpc"}}, 404)
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                request = json.loads(raw.decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                self._send({"ok": False, "error": {"code": "invalid-request",
                                                   "message": f"body is not JSON: {exc}"}}, 400)
                return
            response = handle(request)
            self._send(response, 200 if response.get("ok") else int(response.get("http_status", 500)))

        def log_message(self, fmt: str, *args: Any) -> None:  # keep the test output quiet
            return

    return _Handler


def serve(host: str = "127.0.0.1", port: int = 8765, *, background: bool = False):
    """Start the stdlib HTTP server.  ``background=True`` returns ``(server, thread)``."""
    from http.server import ThreadingHTTPServer
    import threading

    server = ThreadingHTTPServer((host, int(port)), make_handler())
    if not background:
        server.serve_forever()
        return server
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


__all__ = ["OPS", "handle", "health", "make_handler", "serve"]
