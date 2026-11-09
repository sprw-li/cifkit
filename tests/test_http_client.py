"""Rate-limit / retry behaviour against a **local** mock server (limitation A6).

The mock server can be told to answer 429 with ``Retry-After``, 503, 500, 404 and
to enforce a real request-rate budget (rejecting bursts with 429).  Nothing here
touches the internet, so the behaviour is verified deterministically instead of
hoping a public database rate-limits us during a test run.
"""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cifkit.sources.http import HttpClient, HttpError

PAYLOAD = b"data_test\n_cell_length_a 5\n"


class _State:
    def __init__(self) -> None:
        self.script: list[int] = []          # statuses to return, in order
        self.retry_after: str | None = None
        self.requests: list[float] = []      # arrival timestamps
        self.paths: list[str] = []
        self.rate_budget: float | None = None  # requests per second allowed
        self.violations = 0
        self.lock = threading.Lock()

    def next_status(self) -> int:
        with self.lock:
            if self.script:
                return self.script.pop(0)
            return 200

    def record(self, path: str) -> bool:
        """Record a request; return False when the caller exceeded the budget."""
        now = time.time()
        with self.lock:
            self.paths.append(path)
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
            allowed = state.record(self.path)
            status = 429 if not allowed else state.next_status()
            self.send_response(status)
            if status in (429, 503) and state.retry_after:
                self.send_header("Retry-After", state.retry_after)
            if status == 200:
                body = PAYLOAD
            else:
                body = b"rate limited"
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # noqa: D102
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _record_sleeps() -> tuple[list[float], callable]:
    sleeps: list[float] = []

    def sleeper(seconds: float) -> None:
        sleeps.append(seconds)

    return sleeps, sleeper


def test_retries_429_then_succeeds(mock_server):
    base, state = mock_server
    state.script = [429, 429]
    state.retry_after = "0"
    sleeps, sleeper = _record_sleeps()
    client = HttpClient(retries=4, jitter=0, sleeper=sleeper, min_interval=0)
    body = client.get(f"{base}/cif/1.cif")
    assert body == PAYLOAD
    assert len(state.paths) == 3, "two 429s then success"
    assert len(sleeps) == 2 and all(s >= 0 for s in sleeps)
    assert client.stats["http_errors"] == 2 and client.stats["ok"] == 1


def test_retry_after_header_is_honoured(mock_server):
    base, state = mock_server
    state.script = [429, 200]
    state.retry_after = "2"
    sleeps, sleeper = _record_sleeps()
    client = HttpClient(retries=3, jitter=0.0, sleeper=sleeper, base_backoff=10.0, max_backoff=30.0)
    assert client.get(f"{base}/x") == PAYLOAD
    assert sleeps and sleeps[0] == 2.0, f"Retry-After must win over base_backoff: {sleeps}"


def test_retry_after_caps_at_max_backoff(mock_server):
    base, state = mock_server
    state.script = [503, 200]
    state.retry_after = "600"
    sleeps, sleeper = _record_sleeps()
    client = HttpClient(retries=3, jitter=0.0, sleeper=sleeper, max_backoff=5.0)
    assert client.get(f"{base}/x") == PAYLOAD
    assert sleeps[0] == 5.0


def test_backoff_grows_exponentially_without_retry_after(mock_server):
    base, state = mock_server
    state.script = [500, 500, 500]
    sleeps, sleeper = _record_sleeps()
    client = HttpClient(retries=4, base_backoff=1.0, jitter=0.0, sleeper=sleeper, max_backoff=100.0)
    assert client.get(f"{base}/x") == PAYLOAD
    assert sleeps == [1.0, 2.0, 4.0], sleeps


def test_non_retryable_status_fails_fast(mock_server):
    base, state = mock_server
    state.script = [404, 200]
    sleeps, sleeper = _record_sleeps()
    client = HttpClient(retries=4, sleeper=sleeper)
    with pytest.raises(HttpError) as excinfo:
        client.get(f"{base}/missing.cif")
    assert excinfo.value.status == 404 and excinfo.value.retryable is False
    assert len(state.paths) == 1, "a 404 must not be retried"
    assert sleeps == []


def test_retries_exhausted_raises_with_context(mock_server):
    base, state = mock_server
    state.script = [503, 503, 503]
    sleeps, sleeper = _record_sleeps()
    client = HttpClient(retries=3, base_backoff=0.01, sleeper=sleeper)
    with pytest.raises(HttpError) as excinfo:
        client.get(f"{base}/x")
    assert excinfo.value.attempts == 3 and excinfo.value.retryable is True
    assert len(state.paths) == 3 and len(sleeps) == 2


def test_network_error_is_retried(monkeypatch):
    calls = {"n": 0}
    sleeps: list[float] = []

    class _Fake:
        def __enter__(self):
            raise ConnectionResetError("boom")

        def __exit__(self, *args):
            return False

    def fake_opener(request, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionResetError("boom")
        return _RealResponse(PAYLOAD)

    class _RealResponse:
        def __init__(self, body: bytes) -> None:
            self._body = body
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *args):
            return self._body

    client = HttpClient(retries=4, base_backoff=0.01, jitter=0.0,
                        sleeper=lambda s: sleeps.append(s))
    assert client.get("http://example.invalid/x", opener=fake_opener) == PAYLOAD
    assert calls["n"] == 3


def test_pacing_enforces_min_interval_with_real_sleeps(mock_server):
    """Pacing must actually delay requests (real clock, real sleep)."""
    base, state = mock_server
    client = HttpClient(retries=1, min_interval=0.12)  # default sleeper = time.sleep
    start = time.monotonic()
    for _ in range(4):
        client.get(f"{base}/x")
    elapsed = time.monotonic() - start
    assert client.stats.get("paced", 0) >= 3, client.stats
    assert elapsed >= 0.3, f"pacing did not delay requests ({elapsed:.3f}s)"


def test_paced_client_stays_within_server_budget(mock_server):
    """A6: a server allowing 5 req/s must see **zero** violations from a paced batch."""
    base, state = mock_server
    state.rate_budget = 5.0
    client = HttpClient(retries=6, min_interval=0.25, base_backoff=0.5, jitter=0.0)
    for index in range(20):
        assert client.get(f"{base}/cif/{index}.cif") == PAYLOAD
    assert len(state.paths) == 20
    assert state.violations == 0, f"client exceeded the server budget {state.violations} times"


def test_throttled_burst_client_recovers(mock_server):
    """A6: when the server throttles a burst, backoff must let the batch finish."""
    base, state = mock_server
    state.rate_budget = 5.0
    client = HttpClient(retries=10, base_backoff=0.3, jitter=0.0, min_interval=0.0)
    for index in range(12):
        assert client.get(f"{base}/cif/{index}.cif") == PAYLOAD
    assert state.violations > 0, "the server never throttled us — the test proves nothing"
    assert client.stats.get("http_errors", 0) > 0, "no 429 was retried"
    assert client.stats["ok"] == 12
