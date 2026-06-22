"""Structured trace logging — SQLite-backed event stream.

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
