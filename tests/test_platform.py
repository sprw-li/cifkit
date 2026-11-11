"""Hosting policy guard (cifkit.platform): sandbox, timeouts, backpressure, auth hook."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from cifkit import api
from cifkit.platform import (
    Busy,
    ForbiddenPath,
    GuardedService,
    NetworkDisabled,
    Policy,
    Timeout,
    TooLarge,
    check_params,
)

DATA = Path(__file__).resolve().parent / "data"
ZIF8 = DATA / "zif8_cr_sod.cif"


@pytest.fixture()
def sandbox(tmp_path):
    uploads = tmp_path / "uploads"
    work = tmp_path / "work"
    uploads.mkdir()
    work.mkdir()
    (uploads / "a.cif").write_bytes(ZIF8.read_bytes())
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.cif").write_bytes(ZIF8.read_bytes())
    return uploads, work, outside


# --------------------------------------------------------------------- sandbox
def test_read_sandbox_allows_inside_and_rewrites_to_resolved_path(sandbox):
    uploads, work, outside = sandbox
    policy = Policy(read_roots=[str(uploads)], write_roots=[str(work)])
    params = check_params("features", {"path": str(uploads / "." / "a.cif")}, policy)
    assert Path(params["path"]).is_absolute()
    assert Path(params["path"]).name == "a.cif"


def test_read_sandbox_rejects_outside_and_traversal(sandbox):
    uploads, work, outside = sandbox
    policy = Policy(read_roots=[str(uploads)], write_roots=[str(work)])
    with pytest.raises(ForbiddenPath):
        check_params("features", {"path": str(outside / "secret.cif")}, policy)
    with pytest.raises(ForbiddenPath):
        check_params("features", {"path": str(uploads / ".." / "outside" / "secret.cif")}, policy)
    # a symlink pointing outside must also be rejected
    link = uploads / "link.cif"
    try:
        link.symlink_to(outside / "secret.cif")
    except (OSError, NotImplementedError):  # pragma: no cover - needs privileges
        pytest.skip("symlinks not available")
    with pytest.raises(ForbiddenPath):
        check_params("features", {"path": str(link)}, policy)


def test_write_sandbox_and_disable_writes(sandbox):
    uploads, work, outside = sandbox
    policy = Policy(read_roots=[str(uploads)], write_roots=[str(work)])
    with pytest.raises(ForbiddenPath):
        check_params("convert", {"path": str(uploads / "a.cif"), "outdir": str(outside)}, policy)
    ok = check_params("convert", {"path": str(uploads / "a.cif"), "outdir": str(work)}, policy)
    assert Path(ok["outdir"]) == work.resolve()
    with pytest.raises(ForbiddenPath):
        check_params("convert", {"path": str(uploads / "a.cif"), "outdir": str(work)},
                     Policy(read_roots=[str(uploads)], allow_writes=False))


def test_no_roots_means_developer_mode(sandbox):
    uploads, _work, outside = sandbox
    params = check_params("features", {"path": str(outside / "secret.cif")}, Policy())
    assert params["path"]


def test_features_many_paths_are_sandboxed_and_bounded(sandbox):
    uploads, work, outside = sandbox
    policy = Policy(read_roots=[str(uploads)], max_inputs=1)
    check_params("features_many", {"paths": [str(uploads / "a.cif")]}, policy)
    with pytest.raises(TooLarge):
        check_params("features_many", {"paths": [str(uploads / "a.cif")] * 2}, policy)
    with pytest.raises(ForbiddenPath):
        check_params("features_many", {"paths": [str(outside / "secret.cif")]}, policy)


def test_max_bytes_enforced(sandbox):
    uploads, _work, _outside = sandbox
    policy = Policy(read_roots=[str(uploads)], max_bytes=10)
    with pytest.raises(TooLarge):
        check_params("features", {"path": str(uploads / "a.cif")}, policy)


def test_network_can_be_disabled(sandbox):
    uploads, _work, _outside = sandbox
    policy = Policy(read_roots=[str(uploads)])
    with pytest.raises(NetworkDisabled):
        check_params("fetch", {"source": "cod", "structure_id": "7111973"}, policy)
    allowed = Policy(read_roots=[str(uploads)], allow_network=True)
    assert check_params("fetch", {"source": "cod"}, allowed)


# ------------------------------------------------------------------- guarded svc
def test_guarded_service_end_to_end(sandbox):
    uploads, work, outside = sandbox
    svc = GuardedService(Policy(read_roots=[str(uploads)], write_roots=[str(work)],
                                allow_network=False, timeout_s=120))
    ok = svc.handle({"op": "features", "params": {"path": str(uploads / "a.cif"), "rdf": False}})
    assert ok["ok"] is True and ok["data"]["natoms"] == 138
    assert ok["policy"]["tenant"] is None

    blocked = svc.handle({"op": "features", "params": {"path": str(outside / "secret.cif")}})
    assert blocked["ok"] is False and blocked["error"]["code"] == "forbidden-path"
    assert blocked["http_status"] == 403

    write_outside = svc.handle({"op": "convert", "params": {"path": str(uploads / "a.cif"),
                                                            "formats": ["vasp"],
                                                            "outdir": str(outside)}})
    assert write_outside["error"]["code"] == "forbidden-path"

    write_inside = svc.handle({"op": "convert", "params": {"path": str(uploads / "a.cif"),
                                                           "formats": ["vasp"],
                                                           "outdir": str(work)}})
    assert write_inside["ok"] is True
    assert Path(write_inside["data"]["formats"]["vasp"]).is_file()

    offline = svc.handle({"op": "fetch", "params": {"source": "cod", "structure_id": "7111973"}})
    assert offline["error"]["code"] == "network-disabled" and offline["http_status"] == 403


def test_guarded_service_validation_and_unknown_ops(sandbox):
    uploads, _work, _outside = sandbox
    svc = GuardedService(Policy(read_roots=[str(uploads)]))
    assert svc.handle("not-an-object")["error"]["code"] == "invalid-request"
    assert svc.handle({"op": "features", "params": ["not", "a", "dict"]})["error"]["code"] == "invalid-request"
    assert svc.handle({"op": "nope"})["error"]["code"] == "invalid-request"
    contract = svc.handle({"op": "features", "params": {"rdf_bins": 0}})
    assert contract["error"]["code"] == "invalid-request"


def test_timeout_is_enforced_and_reported():
    """Deterministic: the handler blocks on an event, so timing cannot race."""
    started = threading.Event()
    release = threading.Event()

    def slow(_request):  # noqa: ANN001 - test double
        started.set()
        release.wait(timeout=10)
        return {"ok": True, "op": "features", "api_version": api.API_VERSION, "data": {}}

    svc = GuardedService(Policy(timeout_s=0.5), base_handler=slow)
    begin = time.time()
    response = svc.handle({"op": "features", "params": {}})
    elapsed = time.time() - begin
    release.set()
    svc.shutdown()
    assert response["ok"] is False and response["error"]["code"] == "timeout"
    assert response["http_status"] == 504
    assert elapsed < 1.9, f"timeout returned after {elapsed:.2f}s despite timeout_s=0.5"
    assert started.is_set(), "the worker should have started the operation"
    # round 50 (J2): the wording changed from "best-effort" to "cooperative", because a
    # timed-out request now also *cancels* the worker (it stops at its next
    # cancellation checkpoint) instead of merely abandoning it.
    assert "cooperative" in response["error"]["message"]
    assert "cancellation checkpoint" in response["error"]["message"]


def test_backpressure_rejects_when_saturated():
    """Deterministic: wait until the first request is inside the handler."""
    entered = threading.Event()
    release = threading.Event()

    def slow(_request):  # noqa: ANN001 - test double
        entered.set()
        release.wait(timeout=10)
        return {"ok": True, "op": "features", "api_version": api.API_VERSION, "data": {}}

    svc = GuardedService(Policy(timeout_s=30, max_concurrency=1, queue_size=0),
                         base_handler=slow)
    results: list[dict] = []

    def call():
        results.append(svc.handle({"op": "features", "params": {}}))

    first = threading.Thread(target=call)
    first.start()
    assert entered.wait(timeout=10), "first request never reached the handler"
    second = svc.handle({"op": "features", "params": {}})
    release.set()
    first.join(timeout=10)
    svc.shutdown()
    assert second["ok"] is False and second["error"]["code"] == "busy"
    assert second["http_status"] == 503
    assert results and results[0]["ok"] is True


def test_queue_size_allows_one_waiting_request():
    """max_concurrency=1, queue_size=1 → one running + one waiting is admitted."""
    entered = threading.Event()
    release = threading.Event()

    def slow(_request):  # noqa: ANN001
        entered.set()
        release.wait(timeout=10)
        return {"ok": True, "op": "features", "api_version": api.API_VERSION, "data": {}}

    svc = GuardedService(Policy(timeout_s=30, max_concurrency=1, queue_size=1),
                         base_handler=slow)
    results: list[dict] = []

    def call():
        results.append(svc.handle({"op": "features", "params": {}}))

    first = threading.Thread(target=call)
    first.start()
    assert entered.wait(timeout=10)
    second = threading.Thread(target=call)
    second.start()
    time.sleep(0.3)  # let the second request queue up
    third = svc.handle({"op": "features", "params": {}})
    assert third["ok"] is False and third["error"]["code"] == "busy"
    release.set()
    first.join(timeout=10)
    second.join(timeout=10)
    svc.shutdown()
    assert [r["ok"] for r in results] == [True, True]


def test_authorizer_hook_sets_tenant_and_can_deny():
    def authorizer(request):  # noqa: ANN001 - envelope-level hook
        token = (request.get("auth") or {}).get("tenant")
        if token == "deny":
            raise ForbiddenPath("tenant not allowed")
        return token or "public"

    svc = GuardedService(Policy(timeout_s=60), authorizer=authorizer)
    ok = svc.handle({"op": "capabilities", "params": {}, "auth": {"tenant": "acme"}})
    assert ok["ok"] is True and ok["policy"]["tenant"] == "acme"
    denied = svc.handle({"op": "capabilities", "params": {}, "auth": {"tenant": "deny"}})
    assert denied["ok"] is False and denied["error"]["code"] == "forbidden-path"


def test_stats_track_requests_and_rejections(sandbox):
    uploads, _work, outside = sandbox
    svc = GuardedService(Policy(read_roots=[str(uploads)]))
    svc.handle({"op": "features", "params": {"path": str(uploads / "a.cif"), "rdf": False}})
    svc.handle({"op": "features", "params": {"path": str(outside / "secret.cif")}})
    stats = svc.stats_snapshot()
    assert stats["requests"] == 2 and stats["ok"] == 1 and stats["rejected"] == 1


def test_policy_is_immutable_and_tenant_is_derived():
    policy = Policy(read_roots=["/a"])
    derived = policy.with_tenant("acme")
    assert policy.tenant is None and derived.tenant == "acme"
    assert derived.read_roots == policy.read_roots
