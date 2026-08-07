"""HTTP routes for authentication — Phase 4c+ multi-user (PIN mode).

Registration modes:
  - Invitation + PIN (内测 default): {invitation_code, username, pin}
  - Email/password (legacy):         {email, password}

Login:
  - username + PIN (default)
  - email + password (legacy)

Admin endpoints (require admin token via X-Admin-Token header for MVP):
  - GET  /api/v1/admin/users              list all users
  - POST /api/v1/admin/users/{username}/disable
  - POST /api/v1/admin/users/{username}/enable
  - POST /api/v1/admin/invitations/generate {count, note}
  - GET  /api/v1/admin/invitations        alias for /api/v1/auth/invitations
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from cagent_os.auth import (
    AuthError,
    InvitationCodeError,
    InvitationCodeStore,
    InvalidCredentialsError,
    UserAlreadyExistsError,
    UserDisabledError,
    UserStore,
)
from cagent_os.auth.jwt_utils import create_access_token, decode_access_token, JWTError
from cagent_os.auth.user_store import _validate_pin
from cagent_os.interfaces.http.rate_limiter import limiter
import secrets as _secrets

logger = logging.getLogger(__name__)

# Alphabet without confusing chars (matches generate_invitation_codes.py)
_INVITE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _generate_invitation_code() -> str:
    return "".join(_secrets.choice(_INVITE_ALPHABET) for _ in range(8))


# ── Schemas ───────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    """Invitation+PIN (default) or email+password (legacy)."""
    invitation_code: str | None = None
    username: str | None = None
    pin: str | None = None          # NEW: 4-6 digit PIN (replaces passwordless mode)
    email: str | None = None
    password: str | None = None
    display_name: str | None = None


class LoginRequest(BaseModel):
    """username + PIN (default) or email + password (legacy)."""
    username: str | None = None
    pin: str | None = None
    email: str | None = None
    password: str | None = None


class AuthResponse(BaseModel):
    token: str
    token_type: str = "Bearer"
    user: dict


class GenerateInvitationsRequest(BaseModel):
    count: int = Field(default=5, ge=1, le=100)
    note: str = ""


# ── Router factory ────────────────────────────────────────────────────

def build_auth_router(user_store: UserStore, invitation_store: InvitationCodeStore) -> APIRouter:
    router = APIRouter()

    # Admin token check (simple shared secret via env, MVP only)
    def _require_admin(request: Request) -> None:
        """Validate X-Admin-Token header against ADMIN_TOKEN env var.

        For MVP, we use a shared secret instead of role-based auth.
        Set ADMIN_TOKEN env var to enable; if unset, admin endpoints 503.
        """
        expected = os.environ.get("ADMIN_TOKEN", "").strip()
        if not expected:
            raise HTTPException(
                status_code=503,
                detail="Admin endpoints disabled. Set ADMIN_TOKEN env var to enable.",
            )
        provided = request.headers.get("X-Admin-Token", "").strip()
        if not provided or provided != expected:
            raise HTTPException(status_code=403, detail="Invalid admin token")

    # ── Auth endpoints (public) ──────────────────────────────────

    @router.post("/api/v1/auth/register", response_model=AuthResponse)
    @limiter.limit("3/minute")
    def register(payload: RegisterRequest, request: Request) -> AuthResponse:
        # Mode 1: Invitation + PIN
        if payload.invitation_code and payload.username and payload.pin:
            try:
                user = user_store.register_with_invitation(
                    username=payload.username,
                    pin=payload.pin,
                    invitation_code=payload.invitation_code,
                    invitation_store=invitation_store,
                )
            except InvitationCodeError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
            except UserAlreadyExistsError as exc:
                raise HTTPException(status_code=409, detail=str(exc))
            except AuthError as exc:
                raise HTTPException(status_code=400, detail=str(exc))

            token = create_access_token(user_id=user.id, username=user.username)
            logger.info("User registered via invitation: %s", user.username)
            return AuthResponse(token=token, user=user.to_dict())

        # Mode 2: Email/password (legacy)
        if payload.email and payload.password:
            try:
                user = user_store.register(
                    email=payload.email,
                    password=payload.password,
                    display_name=payload.display_name,
                )
            except UserAlreadyExistsError as exc:
                raise HTTPException(status_code=409, detail=str(exc))
            except AuthError as exc:
                raise HTTPException(status_code=400, detail=str(exc))

            token = create_access_token(user_id=user.id, username=user.username, email=user.email)
            return AuthResponse(token=token, user=user.to_dict())

        raise HTTPException(
            status_code=400,
            detail="Provide {invitation_code, username, pin} or {email, password}",
        )

    @router.post("/api/v1/auth/login", response_model=AuthResponse)
    @limiter.limit("5/minute")
    def login(payload: LoginRequest, request: Request) -> AuthResponse:
        # Mode 1: username + PIN
        if payload.username and payload.pin:
            try:
                user = user_store.authenticate_by_pin(payload.username, payload.pin)
            except UserDisabledError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
            except InvalidCredentialsError as exc:
                raise HTTPException(status_code=401, detail=str(exc))
            token = create_access_token(
                user_id=user.id, username=user.username, email=user.email,
            )
            logger.info("User logged in via PIN: %s", user.username)
            return AuthResponse(token=token, user=user.to_dict())

        # Mode 2: email + password (legacy)
        if payload.email and payload.password:
            try:
                user = user_store.authenticate(email=payload.email, password=payload.password)
            except UserDisabledError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
            except InvalidCredentialsError as exc:
                raise HTTPException(status_code=401, detail=str(exc))
            token = create_access_token(
                user_id=user.id, username=user.username, email=user.email,
            )
            return AuthResponse(token=token, user=user.to_dict())

        raise HTTPException(
            status_code=400,
            detail="Provide {username, pin} or {email, password}",
        )

    @router.get("/api/v1/auth/me")
    def me(request: Request) -> dict:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing Authorization header")
        token = auth_header.removeprefix("Bearer ").strip()
        try:
            payload = decode_access_token(token)
        except JWTError as exc:
            raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token missing 'sub'")

        user = user_store.get_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="User no longer exists")
        if user.disabled:
            raise HTTPException(status_code=403, detail="Account has been disabled")

        return {
            "user": user.to_dict(),
            "token_expires_at": payload.get("exp"),
        }

    @router.get("/api/v1/auth/invitations")
    def list_invitations(request: Request) -> dict:
        """List invitation codes (admin only)."""
        _require_admin(request)
        return {
            "all": invitation_store.list_all(),
            "available": invitation_store.list_available(),
        }

    # ── Admin endpoints ──────────────────────────────────────────

    @router.get("/api/v1/admin/users")
    def admin_list_users(request: Request) -> dict:
        """List all registered users (admin only)."""
        _require_admin(request)
        users = user_store.list_users(include_disabled=True)
        return {
            "users": [u.to_dict() for u in users],
            "total": len(users),
        }

    @router.post("/api/v1/admin/users/{username}/disable")
    def admin_disable_user(username: str, request: Request) -> dict:
        """Disable a user account (admin only)."""
        _require_admin(request)
        try:
            user_store.set_disabled(username, disabled=True)
        except InvalidCredentialsError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"status": "disabled", "username": username}

    @router.post("/api/v1/admin/users/{username}/enable")
    def admin_enable_user(username: str, request: Request) -> dict:
        """Re-enable a disabled user account (admin only)."""
        _require_admin(request)
        try:
            user_store.set_disabled(username, disabled=False)
        except InvalidCredentialsError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"status": "enabled", "username": username}

    @router.post("/api/v1/admin/invitations/generate")
    def admin_generate_invitations(payload: GenerateInvitationsRequest, request: Request) -> dict:
        """Generate new invitation codes (admin only)."""
        _require_admin(request)
        codes = [_generate_invitation_code() for _ in range(payload.count)]
        invitation_store.add_many(codes, created_by="admin-api", note=payload.note)
        return {
            "generated": codes,
            "count": len(codes),
            "note": payload.note,
        }

    return router
