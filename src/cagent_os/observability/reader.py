"""Trace Reader — query-side of the observability system.

Companion to TraceWriter. Provides structured read access to the trace
database for debugging, analysis, and DICA (Detect-Interaction-Context-Answer)
cold optimization.

Phase 2b: Basic query API.
Phase 3-5: Will be used by Golden Cases analysis, Langfuse migration, and
           SFT/DPO training data extraction.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class TraceSummary:
    """Lightweight summary of one conversation run."""
    conversation_id: str
    started_at: str = ""
    ended_at: str = ""
    user_query: str = ""
    final_output_preview: str = ""   # first 500 chars
    event_count: int = 0
    tool_call_count: int = 0
    tool_failure_count: int = 0
    skill_loaded: list[str] = field(default_factory=list)
    outcome: str = ""  # "completed" | "failed" | "iteration_limit" | "unknown"


@dataclass
class TraceEvent:
    """One event from the trace_events table."""
    id: int
    timestamp: str
    conversation_id: str
    agent_name: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)


class TraceReader:
    """Read-side access to the trace event database.

    Usage:
        reader = TraceReader("data/trace.db")
        await reader.open()
        conversations = await reader.list_conversations(limit=20)
        timeline = await reader.get_timeline("conv_xxx")
        summary = await reader.get_summary("conv_xxx")
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db = None

    async def open(self) -> None:
        import aiosqlite
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    async def list_conversations(
        self,
        limit: int = 20,
        offset: int = 0,
        since: str = "",
        until: str = "",
    ) -> list[TraceSummary]:
        """List recent conversations with metadata.

        Returns one summary per conversation, ordered by most recent first.
        """
        if not self._db:
            return []

        where = ""
        params: list[Any] = []
        if since:
            where += " AND timestamp >= ?"
            params.append(since)
        if until:
            where += " AND timestamp <= ?"
            params.append(until)

        # Get distinct conversation_ids with their first/last events
        query = f"""
            SELECT
                conversation_id,
                MIN(timestamp) as started_at,
                MAX(timestamp) as ended_at,
                COUNT(*) as event_count
            FROM trace_events
            WHERE 1=1 {where}
            GROUP BY conversation_id
            ORDER BY started_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()

        summaries: list[TraceSummary] = []
        for row in rows:
            cid = row["conversation_id"]
            summary = TraceSummary(
                conversation_id=cid,
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                event_count=row["event_count"],
            )

            # Get event-type counts
            counts = await self._get_event_counts(cid)
            summary.tool_call_count = counts.get("tool_executed", 0)
            summary.tool_failure_count = counts.get("tool_failed", 0)

            # Get user query from run_started payload
            query_text = await self._get_first_event_payload(cid, "run_started", "user_query")
            summary.user_query = query_text or ""

            # Get final output from run_completed payload
            final = await self._get_first_event_payload(cid, "run_completed", "final_output")
            summary.final_output_preview = (final or "")[:500]

            # Determine outcome
            has_completed = counts.get("run_completed", 0) > 0
            has_failed = counts.get("run_failed", 0) > 0
            if has_completed:
                summary.outcome = "completed"
            elif has_failed:
                # Get the failure reason
                reason = await self._get_first_event_payload(cid, "run_failed", "reason")
                if reason == "iteration_limit":
                    summary.outcome = "iteration_limit"
                else:
                    summary.outcome = "failed"
            else:
                summary.outcome = "unknown"

            # Get skills loaded
            skills = await self._get_first_event_payload(cid, "user_skill_loaded", "skills")
            if skills:
                summary.skill_loaded = skills if isinstance(skills, list) else [skills]

            summaries.append(summary)

        return summaries

    async def get_timeline(self, conversation_id: str) -> list[TraceEvent]:
        """Get the full event timeline for one conversation."""
        if not self._db:
            return []

        cursor = await self._db.execute(
            """SELECT id, timestamp, conversation_id, agent_name, event_type, payload
               FROM trace_events
               WHERE conversation_id = ?
               ORDER BY id ASC""",
            (conversation_id,),
        )
        rows = await cursor.fetchall()

        events: list[TraceEvent] = []
        for row in rows:
            try:
                payload = json.loads(row["payload"]) if row["payload"] else {}
            except json.JSONDecodeError:
                payload = {"raw": row["payload"]}
            events.append(TraceEvent(
                id=row["id"],
                timestamp=row["timestamp"],
                conversation_id=row["conversation_id"],
                agent_name=row["agent_name"] or "",
                event_type=row["event_type"],
                payload=payload,
            ))
        return events

    async def get_summary(self, conversation_id: str) -> Optional[TraceSummary]:
        """Get a detailed summary for one conversation."""
        summaries = await self.list_conversations(limit=1, offset=0)
        for s in summaries:
            if s.conversation_id == conversation_id:
                # Populate skills
                timeline = await self.get_timeline(conversation_id)
                skills = []
                for ev in timeline:
                    if ev.event_type == "user_skill_loaded":
                        loaded = ev.payload.get("skills", [])
                        if isinstance(loaded, list):
                            skills.extend(loaded)
                s.skill_loaded = list(set(skills))
                return s
        return None

    async def get_recent_runs(self, limit: int = 10) -> list[TraceSummary]:
        """Get the most recent completed runs."""
        return await self.list_conversations(limit=limit)

    async def count_runs(self, outcome: str = "") -> int:
        """Count total runs, optionally filtered by outcome."""
        # This is approximate — counts distinct conversation_ids
        if not self._db:
            return 0
        query = "SELECT COUNT(DISTINCT conversation_id) as cnt FROM trace_events"
        if outcome:
            query += " WHERE conversation_id IN (SELECT DISTINCT conversation_id FROM trace_events WHERE event_type = ?)"
            cursor = await self._db.execute(query, (f"run_{outcome}",))
        else:
            cursor = await self._db.execute(query)
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_event_counts(self, conversation_id: str) -> dict[str, int]:
        cursor = await self._db.execute(
            """SELECT event_type, COUNT(*) as cnt
               FROM trace_events
               WHERE conversation_id = ?
               GROUP BY event_type""",
            (conversation_id,),
        )
        rows = await cursor.fetchall()
        return {row["event_type"]: row["cnt"] for row in rows}

    async def _get_first_event_payload(
        self, conversation_id: str, event_type: str, key: str,
    ) -> Optional[str]:
        cursor = await self._db.execute(
            """SELECT payload FROM trace_events
               WHERE conversation_id = ? AND event_type = ?
               ORDER BY id ASC LIMIT 1""",
            (conversation_id, event_type),
        )
        row = await cursor.fetchone()
        if row and row["payload"]:
            try:
                data = json.loads(row["payload"])
                val = data.get(key, "")
                return str(val) if val else ""
            except json.JSONDecodeError:
                pass
        return None
