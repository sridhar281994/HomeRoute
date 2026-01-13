from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException


class RateLimiter:
    """
    Very small in-memory rate limiter (per-process).

    Production note: for multi-instance deployments, replace with Redis-based limits.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, *, key: str, limit: int, window_seconds: int, detail: str = "Too many requests") -> None:
        now = time.monotonic()
        win_start = now - float(window_seconds)
        with self._lock:
            q = self._events[key]
            while q and q[0] < win_start:
                q.popleft()
            if len(q) >= int(limit):
                raise HTTPException(status_code=429, detail=detail)
            q.append(now)


limiter = RateLimiter()

