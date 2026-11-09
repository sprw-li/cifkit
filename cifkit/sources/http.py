"""Shared HTTP client for the data sources: retries, backoff, pacing, Retry-After.

The source adapters used to each carry their own copy of "retry twice with a
linear sleep".  This module centralises that behaviour so it can be *tested*
against a local mock server (limitation **A6**: no rate-limit verification):

* retryable statuses: 408, 425, 429, 500, 502, 503, 504
* non-retryable statuses: 400, 401, 403, 404, 422 (raise immediately)
* backoff: exponential with jitter, capped by ``max_backoff``
* ``Retry-After`` honoured (delta-seconds **or** HTTP-date), capped by ``max_backoff``
* optional **pacing**: ``min_interval`` seconds between requests to the same host,
  so a batch fetch does not hammer a public database
* injectable ``sleeper`` / ``opener`` so tests run instantly and without network

Errors are raised as :class:`HttpError` (with ``status``/``url``/``attempts``) so
callers can map them to their own exception types.
"""
from __future__ import annotations

import email.utils
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

DEFAULT_USER_AGENT = "cifkit/0.1 (CIF workbench; structure retrieval; python-urllib)"

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
NON_RETRYABLE_STATUS = frozenset({400, 401, 403, 404, 422})


class HttpError(RuntimeError):
    """Unrecoverable/retry-exhausted HTTP failure with structured context."""

    def __init__(self, message: str, *, url: str = "", status: int | None = None,
                 attempts: int = 0, retryable: bool = False, body: str = "") -> None:
        super().__init__(message)
        self.url = url
        self.status = status
        self.attempts = attempts
        self.retryable = retryable
        self.body = body


@dataclass
class HttpClient:
    """Small retrying HTTP client.  One instance per host is enough.

    Args:
        retries: total attempts (1 = no retry).
        base_backoff: first backoff in seconds; doubles per attempt.
        max_backoff: cap for a single sleep (also caps ``Retry-After``).
        jitter: fraction of the delay randomised in ``[1 - jitter, 1]``.
        min_interval: minimum seconds between two requests to the same host.
        respect_retry_after: honour the ``Retry-After`` header on 429/503.
        sleeper: injection point for tests (defaults to ``time.sleep``).
        clock: injection point for tests (defaults to ``time.monotonic``).
    """

    user_agent: str = DEFAULT_USER_AGENT
    retries: int = 3
    base_backoff: float = 1.5
    max_backoff: float = 30.0
    jitter: float = 0.25
    min_interval: float = 0.0
    respect_retry_after: bool = True
    timeout: float = 30.0
    sleeper: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    _last_request: dict[str, float] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    stats: dict[str, int] = field(default_factory=dict, repr=False)

    # -- pacing ------------------------------------------------------------
    def _pace(self, host: str) -> None:
        if self.min_interval <= 0 or not host:
            return
        with self._lock:
            previous = self._last_request.get(host)
            now = self.clock()
            if previous is not None:
                wait = self.min_interval - (now - previous)
                if wait > 0:
                    self.sleeper(wait)
                    self.stats["paced"] = self.stats.get("paced", 0) + 1
            self._last_request[host] = self.clock()

    def _next_delay(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None and self.respect_retry_after and retry_after >= 0:
            return min(float(retry_after), self.max_backoff)
        delay = self.base_backoff * (2 ** max(0, attempt - 1))
        if self.jitter:
            delay *= 1.0 - self.jitter * random.random()
        return min(delay, self.max_backoff)

    @staticmethod
    def _retry_after_seconds(response: Any) -> float | None:
        value = None
        try:
            value = response.headers.get("Retry-After") if response is not None else None
        except Exception:  # noqa: BLE001
            value = None
        if not value:
            return None
        value = str(value).strip()
        try:
            return max(0.0, float(value))
        except ValueError:
            pass
        parsed = email.utils.parsedate_to_datetime(value) if value else None
        if parsed is None:
            return None
        try:
            return max(0.0, parsed.timestamp() - time.time())
        except Exception:  # noqa: BLE001
            return None

    # -- request -----------------------------------------------------------
    def get(self, url: str, *, headers: dict[str, str] | None = None,
            timeout: float | None = None, opener: Callable[..., Any] = urllib.request.urlopen) -> bytes:
        """GET ``url`` with retries; returns the body bytes."""
        host = urllib.parse.urlsplit(url).netloc
        merged = {"User-Agent": self.user_agent, "Accept": "*/*"}
        if headers:
            merged.update(headers)
        last: Exception | None = None
        last_status: int | None = None
        attempts = max(1, int(self.retries))
        for attempt in range(1, attempts + 1):
            self._pace(host)
            self.stats["requests"] = self.stats.get("requests", 0) + 1
            try:
                request = urllib.request.Request(url, headers=merged)
                with opener(request, timeout=timeout or self.timeout) as response:
                    body = response.read()
                self.stats["ok"] = self.stats.get("ok", 0) + 1
                return body
            except urllib.error.HTTPError as exc:
                last, last_status = exc, exc.code
                body = ""
                try:
                    body = exc.read().decode("utf-8", "replace")[:300]
                except Exception:  # noqa: BLE001
                    body = ""
                if exc.code in NON_RETRYABLE_STATUS:
                    self.stats["failed"] = self.stats.get("failed", 0) + 1
                    raise HttpError(f"HTTP {exc.code} for {url}", url=url, status=exc.code,
                                    attempts=attempt, retryable=False, body=body) from exc
                if exc.code not in RETRYABLE_STATUS:
                    self.stats["failed"] = self.stats.get("failed", 0) + 1
                    raise HttpError(f"HTTP {exc.code} for {url} (not retryable)", url=url,
                                    status=exc.code, attempts=attempt, retryable=False,
                                    body=body) from exc
                self.stats["http_errors"] = self.stats.get("http_errors", 0) + 1
                if attempt < attempts:
                    delay = self._next_delay(attempt, self._retry_after_seconds(exc))
                    self.stats["slept_s"] = self.stats.get("slept_s", 0) + int(delay * 1000)
                    self.sleeper(delay)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last, last_status = exc, None
                self.stats["network_errors"] = self.stats.get("network_errors", 0) + 1
                if attempt < attempts:
                    delay = self._next_delay(attempt, None)
                    self.stats["slept_s"] = self.stats.get("slept_s", 0) + int(delay * 1000)
                    self.sleeper(delay)
        self.stats["failed"] = self.stats.get("failed", 0) + 1
        raise HttpError(f"HTTP request failed after {attempts} attempt(s): {url}",
                        url=url, status=last_status, attempts=attempts, retryable=True) from last

    def get_json(self, url: str, *, headers: dict[str, str] | None = None,
                 timeout: float | None = None, opener: Callable[..., Any] = urllib.request.urlopen) -> Any:
        import json

        return json.loads(self.get(url, headers=headers, timeout=timeout, opener=opener)
                          .decode("utf-8", "replace"))


__all__ = ["HttpClient", "HttpError", "RETRYABLE_STATUS", "NON_RETRYABLE_STATUS",
           "DEFAULT_USER_AGENT"]
