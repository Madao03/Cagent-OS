"""Rate limiter for auth endpoints — prevents PIN brute-force attacks.

Limits:
  - /api/v1/auth/login:    5 attempts / minute / IP
  - /api/v1/auth/register: 3 attempts / minute / IP

Uses in-memory storage by default (fine for single-instance deployment).
For multi-instance deployment, swap to redis storage in `init_limiter()`.
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


# Default limiter — uses client IP as the key
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")


def init_limiter(app: FastAPI) -> None:
    """Register rate-limiter middleware and exception handler on the app.

    Call this ONCE during app initialization, before routes are added.
    """
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={
                "detail": "请求过于频繁,请稍后再试",
                "retry_after_seconds": getattr(exc, "retry_after", 60),
                "limit": str(exc.limit.limit) if hasattr(exc, "limit") else None,
            },
            headers={
                "Retry-After": str(getattr(exc, "retry_after", 60)),
            },
        )
