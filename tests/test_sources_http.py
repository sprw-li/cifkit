"""The source adapters must use the *tested* shared HTTP client (limitation A6).

``tests/test_http_client.py`` proves the retry/pacing behaviour on the client; this
file proves the COD/AFLOW/MP adapters actually go through it, by pointing them at a
local mock server that rate-limits and throttles.
"""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from cifkit.sources import aflow, cod, materials_project as mp
from cifkit.sources.http import HttpClient

CIF_BODY = (Path(__file__).resolve().parent / "data" / "zif8_cr_sod.cif").read_bytes()


class _State:
    def __init__(self) -> None:
        self.statuses: list[int] = []
        self.retry_after: str | None = None
        self.requests: list[float] = []
        self.violations = 0
        self.rate_budget: float | None = None
        self.lock = threading.Lock()

    def take_status(self) -> int:
        with self.lock:
            return self.statuses.pop(0) if self.statuses else 200

    def record(self) -> bool:
        now = time.time()
        with self.lock:
            self.requests.append(now)
            if self.rate_budget:
                recent = [t for t in self.requests if now - t <= 1.0]
                if len(recent) > self.rate_budget:
                    self.violations += 1
                    return False
            return True


@pytest.fixture()
def mock_server():
    state = _State()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            status = 429 if not state.record() else state.take_status()
            self.send_response(status)
            if status in (429, 503) and state.retry_after:
                self.send_header("Retry-After", state.retry_after)
            body = CIF_BODY if status == 200 else b"throttled"
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # noqa: D102
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_cod_adapter_retries_429_through_shared_client(mock_server, monkeypatch):
    base, state = mock_server
    state.statuses = [429, 503]
    state.retry_after = "0"
    sleeps: list[float] = []
    client = HttpClient(user_agent=cod._USER_AGENT, retries=4, jitter=0.0,
                        sleeper=lambda s: sleeps.append(s))
    monkeypatch.setattr(cod, "_HTTP", client)
    body = cod._http_get(f"{base}/cod/1234.cif")
    assert body == CIF_BODY
    assert len(state.requests) == 3, "429 + 503 then success"
    assert sleeps, "the adapter must back off between retries"
    assert client.stats["http_errors"] == 2


def test_cod_adapter_fails_fast_on_404(mock_server, monkeypatch):
    base, state = mock_server
    state.statuses = [404, 200]
    client = HttpClient(user_agent=cod._USER_AGENT, retries=4, sleeper=lambda s: None)
    monkeypatch.setattr(cod, "_HTTP", client)
    with pytest.raises(RuntimeError):
        cod._http_get(f"{base}/cod/missing.cif")
    assert len(state.requests) == 1, "404 must not be retried"


def test_aflow_adapter_backs_off_and_succeeds(mock_server, monkeypatch):
    base, state = mock_server
    state.statuses = [503]
    state.retry_after = "0"
    sleeps: list[float] = []
    client = HttpClient(user_agent=aflow._USER_AGENT, retries=3, jitter=0.0,
                        sleeper=lambda s: sleeps.append(s))
    monkeypatch.setattr(aflow, "_HTTP", client)
    assert aflow._http_get(f"{base}/AFLOWDATA/x.cif") == CIF_BODY
    assert len(state.requests) == 2 and sleeps


def test_mp_adapter_maps_401_to_key_error(mock_server, monkeypatch):
    base, state = mock_server
    state.statuses = [401]
    client = HttpClient(user_agent=mp._USER_AGENT, retries=2, sleeper=lambda s: None)
    monkeypatch.setattr(mp, "_HTTP", client)
    monkeypatch.setattr(mp, "_require_key", lambda: "fake-key")
    monkeypatch.setattr(mp, "_REQUEST_JSON", None)
    with pytest.raises(ValueError, match="API key"):
        mp._http_json("/materials/summary/", {"material_ids": "mp-149"},
                      host=base, retries=2)


def test_mp_adapter_retries_500_then_succeeds(mock_server, monkeypatch):
    base, state = mock_server
    state.statuses = [500, 503]
    state.retry_after = "0"
    sleeps: list[float] = []
    client = HttpClient(user_agent=mp._USER_AGENT, retries=4, jitter=0.0,
                        sleeper=lambda s: sleeps.append(s))
    monkeypatch.setattr(mp, "_HTTP", client)
    monkeypatch.setattr(mp, "_require_key", lambda: "fake-key")
    monkeypatch.setattr(mp, "_REQUEST_JSON", None)

    # the mock returns a CIF, not JSON, so a successful parse is not the point here:
    # what matters is that 500/503 are retried through the shared client.
    def fake_get_json(url, headers=None, timeout=None, opener=None):
        client.get(url, headers=headers, timeout=timeout)
        return {"data": []}

    monkeypatch.setattr(client, "get_json", fake_get_json)
    assert mp._http_json("/materials/summary/", {"material_ids": "mp-149"},
                         host=base, retries=4) == {"data": []}
    assert len(state.requests) == 3 and len(sleeps) == 2


def test_batch_fetch_respects_server_rate_budget(mock_server, monkeypatch):
    """The A6 batch scenario end-to-end through the COD adapter: 30 CIFs, 5 req/s."""
    base, state = mock_server
    state.rate_budget = 5.0
    client = HttpClient(user_agent=cod._USER_AGENT, retries=6, base_backoff=0.5,
                        jitter=0.0, min_interval=0.25)
    monkeypatch.setattr(cod, "_HTTP", client)
    bodies = [cod._http_get(f"{base}/cod/{index}.cif") for index in range(30)]
    assert all(body == CIF_BODY for body in bodies)
    assert len(state.requests) == 30
    assert state.violations == 0, f"adapter exceeded the server budget {state.violations} times"
    assert client.stats.get("paced", 0) >= 29
