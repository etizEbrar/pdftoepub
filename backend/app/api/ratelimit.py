"""Per-client request throttling.

Conversions cost minutes of CPU, so an unthrottled upload endpoint is a cheap
way for anyone to exhaust the machine. This is a sliding-window counter held in
process memory: no Redis, no extra infrastructure, in keeping with the rest of
the backend.

Its limitation is honest and worth stating: the counters are per process, so
running several workers multiplies the effective limit, and a restart clears
them. That is adequate protection against casual abuse and accidental client
loops. It is *not* a defence against a distributed attack, which belongs at the
CDN or load balancer in front of this service.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    """Allows `limit` events per `window_seconds` for each key."""

    def __init__(self, limit: int, window_seconds: float):
        self._limit = limit
        self._window = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """Record an attempt. Returns (allowed, seconds_until_retry)."""
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            events = self._events[key]
            while events and events[0] < cutoff:
                events.popleft()
            if len(events) >= self._limit:
                retry_after = max(1, int(events[0] + self._window - now) + 1)
                return False, retry_after
            events.append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._events.clear()

    def forget(self, key: str) -> None:
        """Drop a key's history — used when an attempt turns out not to count."""
        with self._lock:
            self._events.pop(key, None)

    def release_one(self, key: str) -> None:
        """Undo the most recent recorded attempt for a key."""
        with self._lock:
            events = self._events.get(key)
            if events:
                events.pop()


def client_key(request) -> str:
    """Identify the caller for throttling.

    Behind a reverse proxy the socket address is the proxy, so the first hop in
    X-Forwarded-For is used when present. That header is client-controlled and
    trivially spoofed, so this is abuse mitigation, not authentication — it must
    never be used to make a security decision.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    client = getattr(request, "client", None)
    return getattr(client, "host", None) or "unknown"
