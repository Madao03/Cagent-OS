"""HTTP routes for memory management — Phase A (Hermes-style).

Endpoints:
  GET  /api/v1/memory/{kind}        — read agent_notes | user_profile
  PUT  /api/v1/memory/{kind}        — replace entire body (with char cap)
  GET  /api/v1/memory/full_state    — return both files + char usage

These endpoints are for human inspection / debugging. LLM tools live in
plugins/memory/plugin.py and call the same store directly.
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from cagent_os.interfaces.http.auth_context import require_principal_id, resolve_principal_id
from cagent_os.memory.sqlite_store import (
    AGENT_NOTES_CHAR_LIMIT,
    MemoryOverflow,
    USER_PROFILE_CHAR_LIMIT,
    SqliteMemoryStore,
)

logger = logging.getLogger(__name__)

MemoryKind = Literal["agent_notes", "user_profile"]

_CHAR_LIMITS = {
    "agent_notes": AGENT_NOTES_CHAR_LIMIT,
    "user_profile": USER_PROFILE_CHAR_LIMIT,
}


class UpdateMemoryRequest(BaseModel):
    body: str


def build_memory_router(memory_store: SqliteMemoryStore) -> APIRouter:
    router = APIRouter()

    # IMPORTANT: register /full_state BEFORE /{kind}, otherwise FastAPI
    # route matching will try to parse "full_state" as a MemoryKind and 422.
    @router.get("/api/v1/memory/full_state")
    async def get_full_state(request: Request) -> dict:
        """Return both memory files + char usage, for LLM consolidation tool."""
        principal_id = resolve_principal_id(request)
        notes = await memory_store.get_agent_notes(principal_id)
        profile = await memory_store.get_user_profile(principal_id)
        return {
            "agent_notes": {
                "body": notes.body,
                "chars_used": notes.chars_used,
                "char_limit": notes.char_limit,
            },
            "user_profile": {
                "body": profile.body,
                "chars_used": profile.chars_used,
                "char_limit": profile.char_limit,
            },
        }

    @router.get("/api/v1/memory/{kind}")
    async def get_memory(kind: MemoryKind, request: Request) -> dict:
        """Read one of the two markdown memory files."""
        principal_id = require_principal_id(request)
        if kind == "agent_notes":
            mem = await memory_store.get_agent_notes(principal_id)
        else:
            mem = await memory_store.get_user_profile(principal_id)
        return {
            "kind": kind,
            "body": mem.body,
            "chars_used": mem.chars_used,
            "char_limit": mem.char_limit,
            "remaining": mem.remaining,
            "updated_at": mem.updated_at.isoformat(),
        }

    @router.put("/api/v1/memory/{kind}")
    async def put_memory(
        kind: MemoryKind, payload: UpdateMemoryRequest, request: Request,
    ) -> dict:
        """Replace the entire body. 409 if exceeds cap (caller should consolidate)."""
        principal_id = resolve_principal_id(request)
        try:
            if kind == "agent_notes":
                mem = await memory_store.update_agent_notes(principal_id, payload.body)
            else:
                mem = await memory_store.update_user_profile(principal_id, payload.body)
        except MemoryOverflow as exc:
            # Return the current state + consolidation hint — matches Hermes
            # behavior of "don't fail silently, instruct the LLM to clean up"
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "memory_overflow",
                    "message": str(exc),
                    "current_body": exc.current_body,
                    "attempted_chars": len(exc.attempted_body),
                    "char_limit": exc.char_limit,
                    "hint": "Consolidate the current_body: merge overlapping entries, "
                            "drop stale ones, then retry with a shorter version.",
                },
            )
        return {
            "kind": kind,
            "body": mem.body,
            "chars_used": mem.chars_used,
            "char_limit": mem.char_limit,
            "remaining": mem.remaining,
            "updated_at": mem.updated_at.isoformat(),
        }

    return router
