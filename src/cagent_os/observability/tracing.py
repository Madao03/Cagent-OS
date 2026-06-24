"""Structured trace logging — SQLite-backed event stream.

DICA (Detect-Interaction-Context-Answer) cold optimization framework:
  Each run produces a trace that captures the four DICA dimensions:
    D — Detect: What triggered this? (user_query in run_started)
    I — Interaction: What happened? (tool calls, skill loads, LLM rounds)
    C — Context: What was the state? (memory injects, watchlist state)
    A — Answer: What was the result? (final_output in run_completed)

  Phase 2b: Capture the right data. Phase 5: Use for SFT/DPO fine-tuning.

Stage 0: SQLite JSON log.
Stage 3+: migrate to Langfuse (replace the store, keep the write API).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


class TraceWriter:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.execute(
            """CREATE TABLE IF NOT EXISTS trace_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                agent_name TEXT,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL
            )"""
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def log(
        self,
        *,
        conversation_id: str,
        agent_name: str | None,
        event_type: str,
        **payload: Any,
    ) -> None:
        if not self._db:
            logger.warning("TraceWriter not open, dropping event: %s", event_type)
            return
        await self._db.execute(
            "INSERT INTO trace_events (timestamp, conversation_id, agent_name, event_type, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                conversation_id,
                agent_name,
                event_type,
                json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )
        await self._db.commit()

    # -- DICA-aligned convenience methods -------------------------------------

    async def log_query(self, conversation_id: str, user_query: str, **extra: Any) -> None:
        """Log the user's query (DICA: Detect). Call at run start."""
        await self.log(
            conversation_id=conversation_id,
            agent_name="harness",
            event_type="run_started",
            user_query=user_query,
            **extra,
        )

    async def log_completion(
        self, conversation_id: str, final_output: str, **extra: Any,
    ) -> None:
        """Log the agent's final response (DICA: Answer). Call at run end."""
        # Truncate to avoid bloating the database
        truncated = final_output[:2000] if len(final_output) > 2000 else final_output
        await self.log(
            conversation_id=conversation_id,
            agent_name="harness",
            event_type="run_completed",
            final_output=truncated,
            final_output_length=len(final_output),
            **extra,
        )
