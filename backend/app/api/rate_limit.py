"""A small in-process rate limiter.

Suitable for a single-instance deployment and for protecting expensive
endpoints (uploads, AI evaluation, login) from accidental hammering. In a
multi-instance deployment, back this with Redis instead — the interface is
deliberately narrow so that swap is contained.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status


class RateLimiter:
    def __init__(self, *, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        if len(bucket) >= self.limit:
            retry_after = int(self.window - (now - bucket[0])) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please slow down and try again shortly.",
                headers={"Retry-After": str(retry_after)},
            )
        bucket.append(now)

    def reset(self) -> None:
        self._hits.clear()


#: Every limiter created in this process, so tests can reset the shared state.
_LIMITERS: list[RateLimiter] = []


def register(bucket: RateLimiter) -> RateLimiter:
    """Track a limiter so :func:`reset_all` can clear it (used by tests)."""
    _LIMITERS.append(bucket)
    return bucket


def reset_all() -> None:
    """Clear every recorded limiter's window."""
    for bucket in _LIMITERS:
        bucket.reset()


def limiter(limit: int, window_seconds: int, *, scope: str):
    """Dependency factory keying the bucket by client IP + authenticated user."""
    bucket = register(RateLimiter(limit=limit, window_seconds=window_seconds))

    async def _dep(request: Request) -> None:
        user_id = getattr(request.state, "user_id", None)
        client = request.client.host if request.client else "unknown"
        bucket.check(f"{scope}:{user_id or client}")

    _dep.bucket = bucket  # type: ignore[attr-defined]
    return _dep
