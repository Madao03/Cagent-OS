"""Auth context — resolve the current user from each HTTP request.

Strategy (in priority order):
  1. Check `Authorization: Bearer <jwt>` header → decode JWT → return user_id
  2. Fall back to `X-Principal-Id` header (legacy/debug, NOT for production)
  3. Fall back to "default" (MVP mode — single user, no auth enforced)

The `require_principal_id()` variant raises 401 if no valid token is present,
used for routes that MUST be authenticated.

Phase 4c+ note (2026-07-20):
  Currently still resolves to "default" when no auth header is present, to
  preserve backward compat with scripts and tests. After all routes are
  migrated to require auth, switch the default to raise 401.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request

from cagent_os.auth.jwt_utils import JWTError, decode_access_token

logger = logging.getLogger(__name__)


def _extract_token(request: Request) -> str | None:
    """Pull the bearer token from Authorization header. Returns None if absent."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header.removeprefix("Bearer ").strip() or None


def resolve_principal_id(request: Request) -> str:
    """Resolve the current user's principal_id (user_id).

    Does NOT raise on missing token — falls back to "default" so existing
    unauthenticated callers keep working during the migration window.
    Use `require_principal_id()` for routes that must be authenticated.
    """
    token = _extract_token(request)
    if token:
        try:
            payload = decode_access_token(token)
            user_id = payload.get("sub")
            if user_id:
                return user_id
        except JWTError as exc:
            logger.warning("Invalid JWT in request: %s", exc)
            # Don't raise here — let the downstream route decide whether
            # to reject the call. resolve_principal_id is permissive by design.

    # Legacy / debug fallback
    return request.headers.get("X-Principal-Id", "").strip() or "default"


def require_principal_id(request: Request) -> str:
    """Strict variant: raises 401 if no valid JWT is present.

    Use this on routes that MUST be authenticated (conversations, messages,
    supervisor runs, etc.). Use `resolve_principal_id` for public routes
    (health checks, auth/login itself).
    """
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Provide `Authorization: Bearer <token>`.",
        )
    try:
        payload = decode_access_token(token)
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing 'sub' field")
    return user_id


# Backward compat — existing code imports resolve_current_user_id
def resolve_current_user_id(request: Request) -> str:
    return resolve_principal_id(request)
