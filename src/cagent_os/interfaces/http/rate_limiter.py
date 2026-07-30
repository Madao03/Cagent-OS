"""Rate limiter — per-user limit keys with IP fallback.

Key resolution priority:
  1. JWT Bearer token → decode sub claim → "user:{user_id}"
  2. X-Principal-Id header → "user:{principal_id}"
  3. Client IP → get_remote_address (fallback for auth endpoints)

Limits (in-memory storage, single-instance):
  - /api/v1/conversations/{id}/messages: 5/min/user
  - /api/v1/auth/login:    5/min/IP
  - /api/v1/auth/register: 3/min/IP

For multi-instance deployment, swap to redis storage in `init_limiter()`.
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def _get_rate_limit_key(request: Request) -> str:
    """Extract principal_id from JWT or X-Principal-Id header, fallback to IP.

    Auth endpoints (login/register) have no token → auto-fallback to IP,
    which is the correct behaviour for brute-force prevention.
    """
    # 1) Try JWT Bearer token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            token = auth_header.removeprefix("Bearer ").strip()
            from cagent_os.auth.jwt_utils import decode_access_token
            payload = decode_access_token(token)
            user_id = payload.get("sub")
            if user_id:
                return f"user:{user_id}"
        except Exception:
            pass

    # 2) Try X-Principal-Id legacy header
    principal_id = request.headers.get("X-Principal-Id", "").strip()
    if principal_id:
        return f"user:{principal_id}"

    # 3) Fallback to client IP
    return get_remote_address(request)


limiter = Limiter(key_func=_get_rate_limit_key, storage_uri="memory://")


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
