"""HTTP routes for conversation management — Phase 4c+.

Exposes the SQLite conversation store to the frontend:
  - GET /api/v1/conversations                 → list user's conversations
  - GET /api/v1/conversations/{id}/events     → replay event history

Both are read-only. Mutations happen implicitly through
POST /api/v1/conversations/{id}/messages (in routes_runs.py).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from cagent_os.conversations.sqlite_store import SqliteConversationRepository
from cagent_os.interfaces.http.auth_context import require_principal_id, resolve_principal_id
from fastapi import Request

logger = logging.getLogger(__name__)


def build_conversations_router(
    repository: Any,
) -> APIRouter:
    """Construct the conversations router.

    Args:
        repository: must be a SqliteConversationRepository (or implement
            list_conversations + list_events). When it's InMemory, the
            list endpoint returns 501 to signal "feature unavailable".
    """
    router = APIRouter()

    @router.get("/api/v1/conversations")
    def list_conversations(
        request: Request,
        limit: int = Query(50, ge=1, le=200),
    ) -> dict:
        """List the caller's conversations, most-recent first.

        Returns: { "conversations": [...], "total": N }
        Each item: {conversation_id, principal_id, user_id,
                    created_at, last_activity_at, last_user_message, first_user_message, event_count}
        """
        principal_id = resolve_principal_id(request)

        if not isinstance(repository, SqliteConversationRepository):
            raise HTTPException(
                status_code=501,
                detail="Conversation listing requires SQLite-backed storage. "
                       "Current repository does not support it.",
            )

        try:
            rows = repository.list_conversations(principal_id=principal_id, limit=limit)
        except Exception as exc:
            logger.exception("list_conversations failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

        return {
            "conversations": rows,
            "total": len(rows),
            "principal_id": principal_id,
        }

    @router.get("/api/v1/conversations/{conversation_id}/events")
    def list_events(conversation_id: str, request: Request) -> dict:
        """Replay all events for a conversation (for loading history into UI).

        Returns: { "conversation_id": str, "events": [...], "total": N }
        Each event: {type, role, content, data}
        """
        principal_id = require_principal_id(request)

        # Ownership check via ConversationService.get_conversation — this
        # validates that the conversation exists AND belongs to principal_id.
        # Using repository.get directly would BYPASS the ownership check.
        from cagent_os.conversations.service import ConversationService
        from cagent_os.shared.errors import ConversationOwnershipError
        try:
            # Wrap repository in a service for the ownership check
            svc = ConversationService(repository=repository)
            svc.get_conversation(principal_id, conversation_id)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail=f"Conversation '{conversation_id}' not found.",
            )
        except ConversationOwnershipError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except Exception as exc:
            # Be safe — if we can't verify ownership, deny
            raise HTTPException(status_code=403, detail=str(exc))

        try:
            events = repository.list_events(conversation_id)
        except Exception as exc:
            logger.exception("list_events failed for %s: %s", conversation_id, exc)
            raise HTTPException(status_code=500, detail=str(exc))

        # Serialize events (JournalEntry → dict)
        event_dicts = []
        for evt in events:
            event_dicts.append({
                "type": evt.type,
                "role": evt.role,
                "content": evt.content or "",
                "data": evt.data or {},
            })

        return {
            "conversation_id": conversation_id,
            "events": event_dicts,
            "total": len(event_dicts),
        }

    return router
