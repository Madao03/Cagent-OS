"""SqliteMemoryStore — async SQLite-backed cold memory.

Tables:
  - user_facts: key-value facts per user
  - investment_theses: ticker-level thesis history
  - contradiction_log: detected contradictions between old and new facts
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import aiosqlite

from cagent_os.memory.api import (
    ContradictionLog,
    InvestmentThesis,
    MemoryAPI,
    UserFact,
)

logger = logging.getLogger(__name__)


class SqliteMemoryStore(MemoryAPI):
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS user_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                source TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS investment_theses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                thesis_type TEXT DEFAULT '',
                content TEXT NOT NULL,
                version TEXT DEFAULT 'v1',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS contradiction_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                old_fact TEXT NOT NULL,
                new_fact TEXT NOT NULL,
                detected_at TEXT NOT NULL,
                resolved INTEGER DEFAULT 0
            );
        """)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def get_user_facts(self, user_id: str) -> list[UserFact]:
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT user_id, key, value, source, created_at FROM user_facts WHERE user_id=?",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [
            UserFact(user_id=r[0], key=r[1], value=json.loads(r[2]), source=r[3],
                     created_at=datetime.fromisoformat(r[4]))
            for r in rows
        ]

    async def save_fact(self, fact: UserFact) -> None:
        if not self._db:
            return
        await self._db.execute(
            "INSERT INTO user_facts (user_id, key, value, source, created_at) VALUES (?, ?, ?, ?, ?)",
            (fact.user_id, fact.key, json.dumps(fact.value, ensure_ascii=False),
             fact.source, fact.created_at.isoformat()),
        )
        await self._db.commit()

    async def query_by_ticker(self, user_id: str, ticker: str) -> list[InvestmentThesis]:
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT user_id, ticker, thesis_type, content, version, created_at "
            "FROM investment_theses WHERE user_id=? AND ticker=? ORDER BY created_at DESC",
            (user_id, ticker),
        )
        rows = await cursor.fetchall()
        return [
            InvestmentThesis(user_id=r[0], ticker=r[1], thesis_type=r[2],
                            content=r[3], version=r[4],
                            created_at=datetime.fromisoformat(r[5]))
            for r in rows
        ]

    async def save_thesis(self, thesis: InvestmentThesis) -> None:
        if not self._db:
            return
        await self._db.execute(
            "INSERT INTO investment_theses (user_id, ticker, thesis_type, content, version, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (thesis.user_id, thesis.ticker, thesis.thesis_type, thesis.content,
             thesis.version, thesis.created_at.isoformat()),
        )
        await self._db.commit()

    async def detect_contradiction(
        self, user_id: str, ticker: str, new_fact: str
    ) -> list[ContradictionLog]:
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT user_id, ticker, old_fact, new_fact, detected_at, resolved "
            "FROM contradiction_log WHERE user_id=? AND ticker=? AND resolved=0",
            (user_id, ticker),
        )
        rows = await cursor.fetchall()
        return [
            ContradictionLog(user_id=r[0], ticker=r[1], old_fact=r[2], new_fact=r[3],
                            detected_at=datetime.fromisoformat(r[4]), resolved=bool(r[5]))
            for r in rows
        ]

    async def save_contradiction(self, log: ContradictionLog) -> None:
        if not self._db:
            return
        await self._db.execute(
            "INSERT INTO contradiction_log (user_id, ticker, old_fact, new_fact, detected_at, resolved) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (log.user_id, log.ticker, log.old_fact, log.new_fact,
             log.detected_at.isoformat(), int(log.resolved)),
        )
        await self._db.commit()

    async def get_hot_memory_prompt(self, user_id: str) -> str:
        """Return ≤500-char hot memory string for system prompt injection."""
        facts = await self.get_user_facts(user_id)
        if not facts:
            return ""
        lines = [f"{f.key}: {f.value}" for f in facts]
        prompt = "; ".join(lines)
        return prompt[:500]
