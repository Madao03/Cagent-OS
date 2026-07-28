"""JWT utilities — sign and verify access tokens.

Tokens carry:
  - sub: user_id (subject, always present)
  - username: display name (always present)
  - email: optional (set when registered via email mode)
  - exp: expiration (30 days default for 内测 — long lived for convenience)
  - iat: issued-at timestamp

Token format: HS256-signed JWT, passed as `Authorization: Bearer <token>`.
"""
from __future__ import annotations

import os
import time

from jose import JWTError, jwt

# 内测 mode: 30 days. Reduce to 7 days before public launch.
DEFAULT_TOKEN_EXPIRY_SECONDS = 30 * 24 * 3600

# Algorithm used for signing
ALGORITHM = "HS256"


def _get_secret_key() -> str:
    """Load JWT secret from env, or generate a random one for the session.

    WARNING: when the random fallback is used, all tokens become invalid
    on every server restart. For production, always set JWT_SECRET_KEY.
    """
    secret = os.environ.get("JWT_SECRET_KEY", "").strip()
    if secret:
        return secret
    global _SESSION_SECRET
    try:
        return _SESSION_SECRET
    except NameError:
        import secrets as _secrets
        _SESSION_SECRET = _secrets.token_urlsafe(64)
        return _SESSION_SECRET


def create_access_token(
    *,
    user_id: str,
    username: str,
    email: str | None = None,
    expires_in_seconds: int = DEFAULT_TOKEN_EXPIRY_SECONDS,
) -> str:
    """Sign and return a JWT for the given user."""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "username": username,
        "iat": now,
        "exp": now + expires_in_seconds,
    }
    if email:
        payload["email"] = email
    return jwt.encode(payload, _get_secret_key(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Verify and decode a JWT. Raises JWTError on invalid/expired tokens."""
    return jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])


def is_token_expired_error(exc: Exception) -> bool:
    """Convenience: was the JWT error due to expiry?"""
    if isinstance(exc, JWTError):
        return "expired" in str(exc).lower()
    return False


__all__ = [
    "ALGORITHM",
    "DEFAULT_TOKEN_EXPIRY_SECONDS",
    "create_access_token",
    "decode_access_token",
    "is_token_expired_error",
]
