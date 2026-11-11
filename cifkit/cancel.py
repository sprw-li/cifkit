"""Cooperative cancellation (round 50, limitation J2).

J2: the guarded service's timeout is best-effort — the caller gets ``504`` but the
worker keeps running, because CPython cannot kill a thread.  This module makes the
*work* cancellable instead: a token that long loops check at safe points, and that
:class:`cifkit.platform.GuardedService` cancels when a request times out.

Contract:

* :class:`CancellationToken` is thread-safe and may be shared;
* :func:`checkpoint` raises :class:`Cancelled` when the token for the *current
  thread* is set — so library code does not have to thread a parameter through every
  call;
* loops that check are documented as "cancellable"; loops that do not are documented
  as "not cancellable" (we never claim more than we implement).
"""
from __future__ import annotations

import contextlib
import threading
from typing import Iterator


class Cancelled(RuntimeError):
    """Raised at a cancellation checkpoint."""

    code = "cancelled"

    def __init__(self, message: str = "operation cancelled", *, reason: str | None = None):
        super().__init__(message)
        self.reason = reason


class CancellationToken:
    """A one-way cancellation flag with an optional reason."""

    __slots__ = ("_event", "_reason", "_lock")

    def __init__(self) -> None:
        self._event = threading.Event()
        self._reason: str | None = None
        self._lock = threading.Lock()

    def cancel(self, reason: str | None = None) -> None:
        with self._lock:
            if self._reason is None:
                self._reason = reason
            self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        return self._reason

    def checkpoint(self) -> None:
        """Raise :class:`Cancelled` if this token has been cancelled."""
        if self._event.is_set():
            raise Cancelled(f"operation cancelled ({self._reason or 'no reason given'})",
                            reason=self._reason)

    def wait(self, timeout: float | None = None) -> bool:
        """Block until cancelled (or ``timeout``); returns the flag."""
        return self._event.wait(timeout)


_CURRENT = threading.local()


def current_token() -> CancellationToken | None:
    return getattr(_CURRENT, "token", None)


def checkpoint() -> None:
    """Check the current thread's token (no-op when there is none)."""
    token = current_token()
    if token is not None:
        token.checkpoint()


@contextlib.contextmanager
def use_token(token: CancellationToken | None) -> Iterator[CancellationToken | None]:
    previous = current_token()
    _CURRENT.token = token
    try:
        yield token
    finally:
        _CURRENT.token = previous


__all__ = ["Cancelled", "CancellationToken", "checkpoint", "current_token", "use_token"]
