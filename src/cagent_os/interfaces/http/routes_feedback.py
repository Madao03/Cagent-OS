"""HTTP routes for user feedback — Beta+ feature.

Stores user feedback in a single SQLite table (`data/feedback.db`, WAL mode).
Feedback is categorized as bug / feature / other, with status tracking
(open / resolved / ignored) for admin management.

Endpoints:
  - POST /api/v1/feedback                 — login user submits feedback
  - GET  /api/v1/feedback                 — admin only, list all feedback
  - PATCH /api/v1/feedback/{id}           — admin only, update feedback status
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

from cagent_os.auth.jwt_utils import JWTError, decode_access_token
from cagent_os.interfaces.http.auth_context import (
    require_admin,
    require_principal_id,
)

logger = logging.getLogger(__name__)

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS feedbacks (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    username    TEXT NOT NULL,
    category    TEXT NOT NULL,
    content     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TEXT NOT NULL
);
"""

_VALID_CATEGORIES = {"bug", "feature", "other"}
_VALID_STATUSES = {"open", "resolved", "ignored"}


# ── Pydantic schemas ─────────────────────────────────────────────────

class FeedbackCreate(BaseModel):
    category: str = Field(..., description="bug / feature / other")
    content: str = Field(..., min_length=1, max_length=5000, description="feedback content")


class FeedbackStatusUpdate(BaseModel):
    status: str = Field(..., description="open / resolved / ignored")


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


def _row_to_feedback(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "username": row["username"],
        "category": row["category"],
        "content": row["content"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


def _resolve_username(request: Request) -> str:
    """Extract username from JWT.

    Token validity is already enforced by ``require_principal_id`` upstream,
    so decoding here is safe. Falls back to empty string if anything is off.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return ""
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        return ""
    try:
        payload = decode_access_token(token)
        return payload.get("username", "") or ""
    except JWTError:
        return ""


# ── Router factory ───────────────────────────────────────────────────

def build_feedback_router(db_path: str | Path) -> APIRouter:
    _ensure_table(db_path)
    router = APIRouter()

    @router.post("/api/v1/feedback")
    def create_feedback(payload: FeedbackCreate, request: Request) -> dict:
        """Login user submits feedback."""
        user_id = require_principal_id(request)
        if payload.category not in _VALID_CATEGORIES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid category. Must be one of: {', '.join(sorted(_VALID_CATEGORIES))}",
            )
        username = _resolve_username(request)
        feedback_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        conn = _connect(db_path)
        try:
            conn.execute(
                """INSERT INTO feedbacks
                   (id, user_id, username, category, content, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'open', ?)""",
                (feedback_id, user_id, username, payload.category, payload.content, created_at),
            )
            conn.commit()
        finally:
            conn.close()

        logger.info("Feedback submitted by %s (category=%s)", user_id, payload.category)
        return {"status": "ok", "id": feedback_id}

    @router.get("/api/v1/feedback")
    def list_feedback(
        request: Request,
        status: str | None = Query(default=None, description="filter by status"),
    ) -> dict:
        """Admin only — list all feedback, optionally filtered by status."""
        require_admin(request)
        if status is not None and status not in _VALID_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
            )

        conn = _connect(db_path)
        try:
            if status:
                cur = conn.execute(
                    "SELECT * FROM feedbacks WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                )
            else:
                cur = conn.execute("SELECT * FROM feedbacks ORDER BY created_at DESC")
            rows = cur.fetchall()
        finally:
            conn.close()

        feedbacks = [_row_to_feedback(r) for r in rows]
        return {"items": feedbacks, "total": len(feedbacks)}

    @router.patch("/api/v1/feedback/{feedback_id}")
    def update_status(
        feedback_id: str,
        payload: FeedbackStatusUpdate,
        request: Request,
    ) -> dict:
        """Admin only — update feedback status."""
        require_admin(request)
        if payload.status not in _VALID_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
            )

        conn = _connect(db_path)
        try:
            cur = conn.execute(
                "UPDATE feedbacks SET status = ? WHERE id = ?",
                (payload.status, feedback_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Feedback not found")
            conn.commit()
        finally:
            conn.close()

        logger.info("Feedback %s status updated to %s", feedback_id, payload.status)
        return {"status": "ok", "id": feedback_id, "new_status": payload.status}

    return router
