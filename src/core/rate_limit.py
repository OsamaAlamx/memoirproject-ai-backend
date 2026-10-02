"""Simple in-memory per-IP rate limiter (no extra deps, survives for pen-test window)."""
import time
from collections import defaultdict, deque
from fastapi import HTTPException, Request, status

_buckets: dict[str, deque[float]] = defaultdict(deque)

def rate_limit(max_calls: int, window_s: int = 60):
    async def _dep(request: Request):
        ip = request.client.host if request.client else "unknown"
        key = f"{request.url.path}:{ip}"
        now = time.monotonic()
        q = _buckets[key]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= max_calls:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again shortly.",
            )
        q.append(now)
    return _dep

# Presets
auth_limit = rate_limit(10, 60)
share_limit = rate_limit(30, 60)
transcript_limit = rate_limit(5, 60)
comment_limit = rate_limit(30, 60)
