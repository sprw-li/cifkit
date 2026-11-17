"""Streaming error path: one HTTP response, always (round 58, task-6, defect A).

The bug: ``/stream/dataset_rows`` wrote its ``200 OK`` + ``Transfer-Encoding:
chunked`` status line *before* pulling the first chunk.  When the generator
raised on its first ``next()`` (``dir=.`` with no ``dataset.jsonl``), the
handler's error branch wrote a second, complete ``HTTP/1.0 404`` response
*inside* the chunked body — and never wrote the ``0\\r\\n\\r\\n`` terminator.
Standard clients reported ``IncompleteRead`` and never saw the JSON error.

These tests read the raw socket bytes, because ``http.client``/``urllib`` hide
protocol damage: a client that gets a 200 cannot tell you the 404 was in the
body.  The assertions are deliberately byte-level:

* exactly one status line per connection;
* the error is a normal ``404 + Content-Length`` JSON response, not a chunked
  body with another response inside it;
* a successful stream is still chunked and ends with the terminator;
* a failure *after* the first chunk can never produce a second response either.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

TERMINATOR = b"0\r\n\r\n"


def _raw_get(port: int, path: str, host: str = "127.0.0.1", timeout: float = 15.0) -> bytes:
    """Send a minimal HTTP/1.0 request and return every byte the peer sent."""
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        request = f"GET {path} HTTP/1.0\r\nHost: {host}\r\nConnection: close\r\n\r\n"
        sock.sendall(request.encode("ascii"))
        chunks: list[bytes] = []
        while True:
            try:
                data = sock.recv(65536)
            except socket.timeout:
                break
            if not data:
                break
            chunks.append(data)
        return b"".join(chunks)
    finally:
        sock.close()


def _status_lines(raw: bytes) -> list[bytes]:
    return [line for line in raw.split(b"\r\n") if line.startswith(b"HTTP/1.")]


def _split(raw: bytes) -> tuple[bytes, bytes]:
    head, _, body = raw.partition(b"\r\n\r\n")
    return head, body


def _dechunk(body: bytes) -> bytes:
    """Decode a complete chunked body (must include the terminator)."""
    out: list[bytes] = []
    index = 0
    while True:
        end = body.index(b"\r\n", index)
        size = int(body[index:end], 16)
        index = end + 2
        if size == 0:
            return b"".join(out)
        out.append(body[index:index + size])
        assert body[index + size:index + size + 2] == b"\r\n"
        index += size + 2


def _url(port: int, dataset_dir: Path, extra: str = "") -> str:
    query = urllib.parse.urlencode({"dir": str(dataset_dir)})
    return f"http://127.0.0.1:{port}/stream/dataset_rows?{query}{extra}"


def _path(dataset_dir: Path, extra: str = "") -> str:
    """Raw request target (percent-encoded) for the socket-level probes."""
    query = urllib.parse.urlencode({"dir": str(dataset_dir)})
    return f"/stream/dataset_rows?{query}{extra}"


@pytest.fixture()
def live_service(tmp_path: Path):
    from cifkit.platform import Policy
    from cifkit.service import serve

    # read_roots = tmp_path so the sandbox check passes; the *runtime* not-found
    # (no dataset.jsonl) is exactly the path under test.
    policy = Policy(allow_network=False, read_roots=(str(tmp_path),))
    server, thread = serve(host="127.0.0.1", port=0, background=True, policy=policy)
    yield {"port": server.server_address[1], "root": tmp_path}
    server.shutdown()
    server.server_close()
    thread.join(timeout=10)


@pytest.fixture()
def dataset_dir(tmp_path: Path) -> Path:
    base = tmp_path / "ds"
    base.mkdir()
    lines = [json.dumps({"run_id": f"run{index:03d}",
                         "meta": {"run_id": f"run{index:03d}"}}) for index in range(3)]
    (base / "dataset.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return base


# ------------------------------------------------------------- the regression
def test_runtime_error_is_exactly_one_response(live_service):
    """Before the fix: two status lines (200 chunked, then a 404 in the body)."""
    raw = _raw_get(live_service["port"], _path(live_service["root"]))
    statuses = _status_lines(raw)
    assert len(statuses) == 1, f"expected a single HTTP response, got {statuses!r}\n{raw!r}"
    assert statuses[0].startswith(b"HTTP/1.0 404"), statuses

    head, body = _split(raw)
    assert b"Transfer-Encoding" not in head, (
        "an error response must not advertise chunked encoding")
    assert b"application/json" in head
    length = int(head.split(b"Content-Length: ")[1].split(b"\r\n")[0])
    assert length == len(body), "Content-Length must match the body exactly"
    payload = json.loads(body.decode("utf-8"))
    assert payload["ok"] is False
    assert payload["error"]["code"] == "not-found"
    assert b"dataset.jsonl" in body


def test_runtime_error_reaches_a_standard_client(live_service):
    """The user-visible symptom was IncompleteRead instead of a 404 + JSON."""
    try:
        urllib.request.urlopen(_url(live_service["port"], live_service["root"]), timeout=30)
    except urllib.error.HTTPError as exc:
        assert exc.code == 404, exc.code
        payload = json.loads(exc.read().decode("utf-8"))
        assert payload["error"]["code"] == "not-found"
    else:  # pragma: no cover - the buggy version got here with a 200
        pytest.fail("a missing dataset must not answer 200")


def test_error_path_never_writes_a_chunked_body(live_service):
    raw = _raw_get(live_service["port"], _path(live_service["root"]))
    head, body = _split(raw)
    assert not body.startswith(b"HTTP/1."), "a second response leaked into the body"
    assert b"HTTP/1." not in body, "a second response leaked into the body"


# ------------------------------------------------------------- the success path
def test_successful_stream_is_chunked_and_terminated(live_service, dataset_dir):
    raw = _raw_get(live_service["port"], _path(dataset_dir))
    statuses = _status_lines(raw)
    assert len(statuses) == 1 and statuses[0].startswith(b"HTTP/1.0 200"), statuses
    head, body = _split(raw)
    assert b"Transfer-Encoding: chunked" in head
    assert body.endswith(TERMINATOR), "the success path must terminate the chunked body"
    payload = _dechunk(body)
    lines = [line for line in payload.decode("utf-8").splitlines() if line.strip()]
    assert len(lines) == 3
    assert all(json.loads(line)["run_id"].startswith("run") for line in lines)


def test_empty_dataset_is_a_clean_200_with_terminator(live_service, tmp_path):
    """Zero rows is not an error: first next() raises StopIteration, not an HTTP bug."""
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "dataset.jsonl").write_text("", encoding="utf-8")
    raw = _raw_get(live_service["port"], _path(empty))
    statuses = _status_lines(raw)
    assert len(statuses) == 1 and statuses[0].startswith(b"HTTP/1.0 200"), statuses
    _, body = _split(raw)
    assert body == TERMINATOR, body


# ------------------------------------- failure after the first chunk (no header yet?)
def test_failure_after_the_first_chunk_still_never_writes_a_second_response(
        live_service, dataset_dir, monkeypatch):
    """Once the 200 is committed a second response is impossible — abort instead.

    The generator yields one good row, then explodes.  The client must see a
    single status line and a *truncated* stream (no terminator pretending the
    data was complete) — never a 404 stitched into the body.
    """
    import cifkit.api as api_module

    def exploding(**kwargs):  # noqa: ARG001 - mirrors stream_dataset_rows_ndjson
        yield '{"run_id": "run000"}\n'
        raise ValueError("simulated mid-stream failure")

    monkeypatch.setattr(api_module, "stream_dataset_rows_ndjson", exploding)
    raw = _raw_get(live_service["port"], _path(dataset_dir))
    statuses = _status_lines(raw)
    assert len(statuses) == 1, f"a second response leaked: {statuses!r}\n{raw!r}"
    assert statuses[0].startswith(b"HTTP/1.0 200"), statuses
    _, body = _split(raw)
    assert b'{"run_id": "run000"}' in body, "the already-produced chunk is not lost"
    assert b"HTTP/1." not in body, "the error branch must never write a response"
    assert not body.endswith(TERMINATOR), (
        "a truncated stream must not be terminated as if it were complete")
