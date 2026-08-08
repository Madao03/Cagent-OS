"""HTTP routes for the opinion bank + message feedback — Beta+ feature.

Two tables in a single SQLite DB (``data/opinions.db``, WAL mode):

  - **opinions**: user-saved snippets from chat answers, categorized as
    fact / opinion / framework. Private per user.
  - **message_feedback**: like / dislike / report signals tied to specific
    assistant messages. Used for 8-L1 telemetry + self-optimization.

Endpoints:
  - POST   /api/v1/opinions           — save a snippet to opinion bank
  - GET    /api/v1/opinions           — list current user's opinions
  - PUT    /api/v1/opinions/{id}      — edit category / note / tags
  - DELETE /api/v1/opinions/{id}      — remove from opinion bank
  - POST   /api/v1/feedback/message   — submit like/dislike/report on a message
  - GET    /api/v1/feedback/message   — admin: list all message feedback
"""
from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from cagent_os.interfaces.http.auth_context import (
    require_admin,
    require_principal_id,
)

logger = logging.getLogger(__name__)

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS opinions (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    conversation_id TEXT,
    message_id      TEXT,
    selected_text   TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT 'opinion',
    note            TEXT NOT NULL DEFAULT '',
    tags            TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_opinions_user ON opinions(user_id);

CREATE TABLE IF NOT EXISTS message_feedback (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    message_id    TEXT NOT NULL,
    conversation_id TEXT,
    feedback_type TEXT NOT NULL,
    report_reason TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_msg ON message_feedback(message_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_unique ON message_feedback(user_id, message_id, feedback_type);
"""

_VALID_CATEGORIES = {"fact", "opinion", "framework"}
_VALID_FEEDBACK_TYPES = {"like", "dislike", "report"}


# ── Pydantic schemas ─────────────────────────────────────────────────

class OpinionCreate(BaseModel):
    conversation_id: str = ""
    message_id: str = ""
    selected_text: str = Field(..., min_length=1, max_length=10000)
    category: str = Field(default="opinion")
    note: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list)


class OpinionUpdate(BaseModel):
    category: str | None = None
    note: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = None


class MessageFeedbackCreate(BaseModel):
    message_id: str = Field(..., min_length=1)
    conversation_id: str = ""
    feedback_type: str = Field(...)
    report_reason: str = Field(default="", max_length=2000)


# ── DB helpers ───────────────────────────────────────────────────────

def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_table(db_path: str | Path) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path)
    try:
        conn.executescript(_TABLE_DDL)
        conn.commit()
    finally:
        conn.close()


def _row_to_opinion(row: sqlite3.Row) -> dict[str, Any]:
    import json
    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"] or "",
        "message_id": row["message_id"] or "",
        "selected_text": row["selected_text"],
        "category": row["category"],
        "note": row["note"],
        "tags": json.loads(row["tags"]) if row["tags"] else [],
        "created_at": row["created_at"],
    }


def _row_to_feedback(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "message_id": row["message_id"],
        "conversation_id": row["conversation_id"] or "",
        "feedback_type": row["feedback_type"],
        "report_reason": row["report_reason"] or "",
        "created_at": row["created_at"],
    }


# ── Router factory ───────────────────────────────────────────────────

def build_opinions_router(db_path: str | Path) -> APIRouter:
    _ensure_table(db_path)
    router = APIRouter()

    # ══ Opinions ══════════════════════════════════════════════════════

    @router.post("/api/v1/opinions")
    def create_opinion(payload: OpinionCreate, request: Request) -> dict:
        """Save a snippet to the current user's opinion bank."""
        user_id = require_principal_id(request)
        if payload.category not in _VALID_CATEGORIES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid category. Must be one of: {', '.join(sorted(_VALID_CATEGORIES))}",
            )
        import json
        opinion_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        conn = _connect(db_path)
        try:
            conn.execute(
                """INSERT INTO opinions
                   (id, user_id, conversation_id, message_id, selected_text, category, note, tags, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (opinion_id, user_id, payload.conversation_id, payload.message_id,
                 payload.selected_text, payload.category, payload.note,
                 json.dumps(payload.tags, ensure_ascii=False), created_at),
            )
            conn.commit()
        finally:
            conn.close()
        logger.info("Opinion saved by %s (category=%s)", user_id, payload.category)
        return {"status": "ok", "id": opinion_id}

    @router.get("/api/v1/opinions")
    def list_opinions(
        request: Request,
        category: str | None = Query(default=None),
        limit: int = Query(default=100, le=500),
    ) -> dict:
        """List current user's opinions, optionally filtered by category."""
        user_id = require_principal_id(request)
        if category is not None and category not in _VALID_CATEGORIES:
            raise HTTPException(status_code=400, detail=f"Invalid category filter")
        conn = _connect(db_path)
        try:
            if category:
                cur = conn.execute(
                    "SELECT * FROM opinions WHERE user_id = ? AND category = ? ORDER BY created_at DESC LIMIT ?",
                    (user_id, category, limit),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM opinions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit),
                )
            rows = cur.fetchall()
        finally:
            conn.close()
        return {"items": [_row_to_opinion(r) for r in rows], "total": len(rows)}

    @router.put("/api/v1/opinions/{opinion_id}")
    def update_opinion(opinion_id: str, payload: OpinionUpdate, request: Request) -> dict:
        """Edit category / note / tags of an opinion."""
        user_id = require_principal_id(request)
        conn = _connect(db_path)
        try:
            existing = conn.execute(
                "SELECT user_id FROM opinions WHERE id = ?", (opinion_id,)
            ).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Opinion not found")
            if existing["user_id"] != user_id:
                raise HTTPException(status_code=403, detail="Not your opinion")

            updates = []
            params = []
            if payload.category is not None:
                if payload.category not in _VALID_CATEGORIES:
                    raise HTTPException(status_code=400, detail="Invalid category")
                updates.append("category = ?")
                params.append(payload.category)
            if payload.note is not None:
                updates.append("note = ?")
                params.append(payload.note)
            if payload.tags is not None:
                import json
                updates.append("tags = ?")
                params.append(json.dumps(payload.tags, ensure_ascii=False))
            if updates:
                params.append(opinion_id)
                conn.execute(f"UPDATE opinions SET {', '.join(updates)} WHERE id = ?", params)
                conn.commit()
        finally:
            conn.close()
        return {"status": "ok", "id": opinion_id}

    @router.delete("/api/v1/opinions/{opinion_id}")
    def delete_opinion(opinion_id: str, request: Request) -> dict:
        """Remove an opinion from the bank."""
        user_id = require_principal_id(request)
        conn = _connect(db_path)
        try:
            existing = conn.execute(
                "SELECT user_id FROM opinions WHERE id = ?", (opinion_id,)
            ).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Opinion not found")
            if existing["user_id"] != user_id:
                raise HTTPException(status_code=403, detail="Not your opinion")
            conn.execute("DELETE FROM opinions WHERE id = ?", (opinion_id,))
            conn.commit()
        finally:
            conn.close()
        return {"status": "ok", "id": opinion_id}

    # ══ Message feedback (8-L1 telemetry) ═════════════════════════════

    @router.post("/api/v1/feedback/message")
    def create_message_feedback(payload: MessageFeedbackCreate, request: Request) -> dict:
        """Submit like / dislike / report on a message."""
        user_id = require_principal_id(request)
        if payload.feedback_type not in _VALID_FEEDBACK_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid feedback_type. Must be one of: {', '.join(sorted(_VALID_FEEDBACK_TYPES))}",
            )
        feedback_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        conn = _connect(db_path)
        try:
            # Upsert: replace existing feedback of same type from same user on same message
            conn.execute(
                """INSERT OR REPLACE INTO message_feedback
                   (id, user_id, message_id, conversation_id, feedback_type, report_reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (feedback_id, user_id, payload.message_id, payload.conversation_id,
                 payload.feedback_type, payload.report_reason, created_at),
            )
            conn.commit()
        finally:
            conn.close()
        logger.info("Feedback by %s on msg %s: %s", user_id, payload.message_id, payload.feedback_type)
        return {"status": "ok", "id": feedback_id}

    @router.get("/api/v1/feedback/message")
    def list_message_feedback(
        request: Request,
        feedback_type: str | None = Query(default=None),
        limit: int = Query(default=100, le=500),
    ) -> dict:
        """Admin only — list all message feedback for telemetry."""
        require_admin(request)
        conn = _connect(db_path)
        try:
            if feedback_type:
                cur = conn.execute(
                    "SELECT * FROM message_feedback WHERE feedback_type = ? ORDER BY created_at DESC LIMIT ?",
                    (feedback_type, limit),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM message_feedback ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            rows = cur.fetchall()
        finally:
            conn.close()
        return {"items": [_row_to_feedback(r) for r in rows], "total": len(rows)}

    return router
