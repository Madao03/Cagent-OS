from __future__ import annotations

from fastapi import Request


def resolve_current_user_id(request: Request) -> str:
    user_id = request.headers.get("X-Principal-Id", "").strip()
    return user_id or "default"


def resolve_principal_id(request: Request) -> str:
    return resolve_current_user_id(request)
