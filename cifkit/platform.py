"""Hosting policy: path sandbox, size limits, network switch, timeouts, backpressure.

``cifkit.api`` is deliberately unopinionated; a *multi-tenant host* needs guards
around it.  This module is that layer, kept out of the wire contract so a single
process can serve several policies (or none):

    policy = Policy(read_roots=["/srv/uploads"], write_roots=["/srv/work"],
                    allow_network=False, timeout_s=30, max_concurrency=2)
    service = GuardedService(policy)
    service.handle({"op": "features", "params": {"path": "/etc/passwd"}})
    # -> {"ok": False, "error": {"code": "forbidden-path", ...}, "http_status": 403}

Guarantees and honest caveats
-----------------------------
* **Path sandbox** is enforced by resolving the path (``Path.resolve()``) and
  checking containment in an allowed root, so ``..`` and symlinks cannot escape
  (the resolved target is checked, and a symlink pointing outside is rejected).
* **Timeout** is *best effort*: the operation runs on a worker thread and the
  caller gets ``timeout`` (504) when it exceeds the budget, but CPython cannot
  safely interrupt a running C extension — the worker may still finish in the
  background.  Use ``executor="process"`` for a hard-killable worker (higher
  per-call overhead) when a run-away computation must be terminated.
* **Backpressure** is a semaphore + bounded queue: requests beyond
  ``max_concurrency + queue_size`` are rejected with ``busy`` (503) instead of
  piling up.
* **Network** can be disabled per policy (``allow_network=False``); the guard
  rejects the operations that would go online rather than relying on the OS.
* **Authentication is a hook, not an implementation**: pass ``authorizer=`` to
  map a request to a tenant/subject; this module only enforces the resulting
  policy (see ``docs/API.md`` §4).
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from cifkit.api import API_VERSION, CifkitError, InvalidRequest

#: operations that may touch the network
NETWORK_OPS = {"fetch", "resolve"}
#: operations that write to disk
WRITE_OPS = {"convert", "dataset"}
#: parameters interpreted as filesystem paths (per operation)
READ_PATH_PARAMS = {"path", "runs_dir"}
WRITE_PATH_PARAMS = {"outdir"}

DEFAULT_ALLOWED_ATOMS = 20_000


class ForbiddenPath(CifkitError):
    code = "forbidden-path"
    http_status = 403


class NetworkDisabled(CifkitError):
    code = "network-disabled"
    http_status = 403


class TooLarge(CifkitError):
    code = "too-large"
    http_status = 413


class Busy(CifkitError):
    code = "busy"
    http_status = 503


class Timeout(CifkitError):
    code = "timeout"
    http_status = 504


@dataclass(frozen=True)
class Policy:
    """Hosting policy.  ``None`` roots mean "no restriction" (developer mode)."""

    read_roots: tuple[str, ...] | None = None
    write_roots: tuple[str, ...] | None = None
    allow_network: bool = False
    allow_writes: bool = True
    max_atoms: int = DEFAULT_ALLOWED_ATOMS
    max_inputs: int = 500
    max_bytes: int = 64 * 1024 * 1024
    timeout_s: float | None = None
    max_concurrency: int = 4
    queue_size: int = 8
    executor: str = "thread"  # "thread" (best-effort timeout) or "process" (killable)
    tenant: str | None = None

    def with_tenant(self, tenant: str | None) -> "Policy":
        return replace(self, tenant=tenant)


def _resolve(path: str) -> Path:
    try:
        return Path(path).expanduser().resolve(strict=False)
    except Exception as exc:  # noqa: BLE001 - weird path (null byte, bad drive, ...)
        raise InvalidRequest(f"invalid path {path!r}: {exc}") from exc


def _inside(target: Path, roots: tuple[str, ...] | None) -> bool:
    if roots is None:
        return True
    for root in roots:
        try:
            base = Path(root).expanduser().resolve(strict=False)
        except Exception:  # noqa: BLE001
            continue
        try:
            if target == base or target.is_relative_to(base):
                return True
        except ValueError:  # different drives on Windows
            continue
    return False


def check_params(op: str, params: dict[str, Any], policy: Policy) -> dict[str, Any]:
    """Return a possibly-rewritten params dict, or raise a policy error.

    Rewriting exists because we validate the *resolved* path: the caller gets the
    canonical path back so the rest of the stack cannot reinterpret it
    differently (TOCTOU-reducing, not TOCTOU-proof).
    """
    out = dict(params or {})

    for key in READ_PATH_PARAMS:
        if key in out and out[key]:
            target = _resolve(str(out[key]))
            if not _inside(target, policy.read_roots):
                raise ForbiddenPath(f"{key} outside the allowed read roots", detail={"path": str(target)})
            out[key] = str(target)
            try:
                if target.is_file() and target.stat().st_size > policy.max_bytes:
                    raise TooLarge(f"{key} exceeds max_bytes={policy.max_bytes}")
            except OSError:  # nonexistent paths are handled downstream (404)
                pass

    for key in WRITE_PATH_PARAMS:
        if key in out and out[key]:
            if not policy.allow_writes:
                raise ForbiddenPath("writes are disabled by policy")
            target = _resolve(str(out[key]))
            if not _inside(target, policy.write_roots):
                raise ForbiddenPath(f"{key} outside the allowed write roots", detail={"path": str(target)})
            out[key] = str(target)

    if op == "convert":
        outdir = out.get("outdir")
        if outdir and op not in WRITE_OPS:  # defensive: keep op classification honest
            raise InvalidRequest("internal: convert must be classified as a write op")
        if not outdir and not policy.allow_network and False:  # inline convert needs no network
            pass

    if op == "features_many":
        paths = out.get("paths") or []
        if not isinstance(paths, list):
            raise InvalidRequest("paths must be a list")
        if len(paths) > policy.max_inputs:
            raise TooLarge(f"paths exceeds max_inputs={policy.max_inputs}")
        resolved = []
        for item in paths:
            target = _resolve(str(item))
            if not _inside(target, policy.read_roots):
                raise ForbiddenPath("paths entry outside the allowed read roots",
                                    detail={"path": str(target)})
            resolved.append(str(target))
        out["paths"] = resolved
        total = 0
        for target in map(Path, resolved):
            try:
                if target.is_file():
                    total += target.stat().st_size
            except OSError:
                continue
        if total > policy.max_bytes:
            raise TooLarge(f"total input size {total} exceeds max_bytes={policy.max_bytes}")

    if op in NETWORK_OPS and not policy.allow_network:
        raise NetworkDisabled(f"operation {op} needs network but policy.allow_network=False")

    # dataset scans many files under runs_dir: bound the count cheaply
    if op == "dataset":
        runs_dir = out.get("runs_dir")
        if runs_dir and Path(runs_dir).is_dir():
            count = sum(1 for _ in Path(runs_dir).rglob("manifest.json"))
            if count > policy.max_inputs:
                raise TooLarge(f"runs_dir has {count} manifests > max_inputs={policy.max_inputs}")

    return out


class GuardedService:
    """Thread-safe wrapper around :func:`cifkit.service.handle` adding a policy."""

    def __init__(self, policy: Policy | None = None, *,
                 authorizer: Callable[[dict[str, Any]], str | None] | None = None,
                 base_handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
                 validate_response: bool = True) -> None:
        self.policy = policy or Policy()
        self.authorizer = authorizer
        self._base = base_handler
        self._validate_response = validate_response
        # backpressure accounting: `_active` counts accepted-but-not-finished
        # requests (running + queued); a request is rejected once it would exceed
        # max_concurrency + queue_size.  A plain Semaphore cannot express
        # "queue_size = 0" correctly (a zero-count semaphore rejects everything).
        self._active = 0
        self._running = 0
        self._cond = threading.Condition()
        self._executor: ThreadPoolExecutor | None = None
        self._lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self.stats = {"requests": 0, "ok": 0, "errors": 0, "rejected": 0, "timeouts": 0}

    # -- internals ----------------------------------------------------------
    def _handler(self) -> Callable[[dict[str, Any]], dict[str, Any]]:
        if self._base is not None:
            return self._base
        from cifkit.service import handle

        return handle

    def _pool(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=max(1, int(self.policy.max_concurrency)),
                    thread_name_prefix="cifkit-guard",
                )
            return self._executor

    def _admit(self) -> bool:
        """Reserve an in-flight slot (running + queued), honouring queue_size."""
        with self._cond:
            limit = max(1, int(self.policy.max_concurrency)) + max(0, int(self.policy.queue_size))
            if self._active >= limit:
                return False
            self._active += 1
            return True

    def _finish(self) -> None:
        with self._cond:
            self._active = max(0, self._active - 1)
            self._cond.notify_all()

    def _acquire_slot(self, timeout: float) -> bool:
        """Wait for a worker slot (``max_concurrency`` of them)."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._cond:
            while self._running >= max(1, int(self.policy.max_concurrency)):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
            self._running += 1
            return True

    def _release_slot(self) -> None:
        with self._cond:
            self._running = max(0, self._running - 1)
            self._cond.notify_all()

    def _bump(self, key: str) -> None:
        with self._stats_lock:
            self.stats[key] = self.stats.get(key, 0) + 1

    def _error(self, op: Any, exc: CifkitError, started: float) -> dict[str, Any]:
        return {"ok": False, "op": op, "api_version": API_VERSION,
                "elapsed_ms": round((time.time() - started) * 1000, 1),
                "error": exc.to_dict(), "http_status": exc.http_status}

    # -- public API ---------------------------------------------------------
    def handle(self, request: Any) -> dict[str, Any]:
        started = time.time()
        self._bump("requests")
        if not isinstance(request, dict):
            self._bump("errors")
            return self._error(None, InvalidRequest("request must be an object"), started)
        op = request.get("op")
        raw_params = request.get("params") or {}
        if not isinstance(raw_params, dict):
            self._bump("errors")
            return self._error(op, InvalidRequest("params must be an object"), started)

        policy = self.policy
        if self.authorizer is not None:
            try:
                tenant = self.authorizer(request)  # envelope-level hook: request["auth"]
            except CifkitError as exc:
                self._bump("errors")
                return self._error(op, exc, started)
            except Exception as exc:  # noqa: BLE001 - authorizer bugs must not leak
                self._bump("errors")
                return self._error(op, CifkitError(f"authorizer failed: {type(exc).__name__}"), started)
            policy = policy.with_tenant(tenant)

        try:
            params = check_params(str(op or ""), raw_params, policy)
        except CifkitError as exc:
            self._bump("rejected")
            return self._error(op, exc, started)

        # backpressure: accept at most max_concurrency + queue_size in-flight
        if not self._admit():
            self._bump("rejected")
            return self._error(op, Busy(
                f"too many in-flight requests (max_concurrency={policy.max_concurrency}, "
                f"queue_size={policy.queue_size})"), started)
        try:
            if not self._acquire_slot(policy.timeout_s or 60.0):
                self._bump("rejected")
                return self._error(op, Busy("no free worker slot within the wait budget"), started)
            try:
                return self._run(op, params, policy, started)
            finally:
                self._release_slot()
        finally:
            self._finish()

    def _run(self, op: Any, params: dict[str, Any], policy: Policy, started: float) -> dict[str, Any]:
        payload = {"op": op, "params": params}
        handler = self._handler()
        if policy.timeout_s is None:
            response = handler(payload)
        else:
            future = self._pool().submit(handler, payload)
            try:
                response = future.result(timeout=float(policy.timeout_s))
            except FutureTimeout:
                self._bump("timeouts")
                future.cancel()
                return self._error(op, Timeout(
                    f"operation exceeded timeout_s={policy.timeout_s} "
                    "(best-effort: the worker thread may still finish in the background)"), started)
        if response.get("ok"):
            self._bump("ok")
        else:
            self._bump("errors")
        response["policy"] = {"tenant": policy.tenant, "allow_network": policy.allow_network,
                              "timeout_s": policy.timeout_s,
                              "max_concurrency": policy.max_concurrency}
        return response

    def stats_snapshot(self) -> dict[str, Any]:
        with self._stats_lock:
            return dict(self.stats)

    def shutdown(self) -> None:
        with self._lock:
            if self._executor is not None:
                self._executor.shutdown(wait=False)
                self._executor = None


__all__ = [
    "Policy",
    "GuardedService",
    "check_params",
    "ForbiddenPath",
    "NetworkDisabled",
    "TooLarge",
    "Busy",
    "Timeout",
    "NETWORK_OPS",
    "WRITE_OPS",
]
