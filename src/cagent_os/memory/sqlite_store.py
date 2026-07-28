"""SqliteMemoryStore — async SQLite-backed cold memory.

Tables (Phase A — Hermes-inspired two-layer markdown memory):
  - user_facts: key-value facts per user (structured)
  - investment_theses: ticker-level thesis history (structured)
  - contradiction_log: detected contradictions between old and new facts
  - agent_notes:    Hermes-style MEMORY.md (≤2000 chars, single-row per user)
  - user_profile:   Hermes-style USER.md   (≤1500 chars, single-row per user)

Design notes:
  - agent_notes and user_profile are "single-row per user" — every update
    replaces the entire body. This matches Hermes's "one markdown file"
    model while keeping SQLite for multi-user concurrency.
  - Character caps force the LLM to consolidate rather than hoard.
    On overflow, update returns the full current content + a "please
    consolidate" instruction instead of raising.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

import aiosqlite

from cagent_os.memory.api import (
    ContradictionLog,
    InvestmentThesis,
    MemoryAPI,
    UserFact,
)

logger = logging.getLogger(__name__)

# Character caps (Hermes defaults). Override per-call if needed.
AGENT_NOTES_CHAR_LIMIT = 2000
USER_PROFILE_CHAR_LIMIT = 1500


@dataclass(frozen=True)
class MarkdownMemory:
    """One of the two markdown memory files (agent_notes or user_profile)."""
    user_id: str
    body: str
    updated_at: datetime
    char_limit: int

    @property
    def chars_used(self) -> int:
        return len(self.body)

    @property
    def remaining(self) -> int:
        return max(0, self.char_limit - len(self.body))


class MemoryOverflow(Exception):
    """Raised when content exceeds char_limit. Caller should return a
    'consolidate' instruction to the LLM instead of writing.

    Attrs:
        current_body: what's currently stored
        attempted_body: what the LLM tried to write
        char_limit: the cap that was exceeded
    """

    def __init__(self, current_body: str, attempted_body: str, char_limit: int):
        self.current_body = current_body
        self.attempted_body = attempted_body
        self.char_limit = char_limit
        super().__init__(
            f"Memory body exceeds limit ({len(attempted_body)}/{char_limit} chars). "
            f"Consolidate before writing."
        )


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
            -- Phase A: Hermes-style markdown memory (single row per user)
            CREATE TABLE IF NOT EXISTS agent_notes (
                user_id TEXT PRIMARY KEY,
                body TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS user_profile (
                user_id TEXT PRIMARY KEY,
                body TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
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
        """Return ≤500-char hot memory string for system prompt injection.

        Phase A: prefer the two markdown tables (agent_notes, user_profile).
        Fall back to structured user_facts if markdown tables are empty
        (backward compat with pre-Phase-A data).
        """
        # 1. Try agent_notes + user_profile (Hermes-style)
        notes = await self.get_agent_notes(user_id)
        profile = await self.get_user_profile(user_id)
        parts = []
        if profile.body:
            parts.append(f"[用户档案]\n{profile.body}")
        if notes.body:
            parts.append(f"[Agent 笔记]\n{notes.body}")
        if parts:
            return "\n\n".join(parts)[:1500]  # generous cap for hot prompt

        # 2. Fallback: structured facts (legacy)
        facts = await self.get_user_facts(user_id)
        if not facts:
            return ""
        lines = [f"{f.key}: {f.value}" for f in facts]
        prompt = "; ".join(lines)
        return prompt[:500]

    # ── Phase A: Hermes-style markdown memory (single-row per user) ──

    async def get_agent_notes(self, user_id: str) -> MarkdownMemory:
        """Return the user's agent_notes (MEMORY.md equivalent)."""
        if not self._db:
            return MarkdownMemory(user_id, "", datetime.utcnow(), AGENT_NOTES_CHAR_LIMIT)
        cursor = await self._db.execute(
            "SELECT body, updated_at FROM agent_notes WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return MarkdownMemory(user_id, "", datetime.utcnow(), AGENT_NOTES_CHAR_LIMIT)
        return MarkdownMemory(
            user_id=user_id,
            body=row[0] or "",
            updated_at=datetime.fromisoformat(row[1]),
            char_limit=AGENT_NOTES_CHAR_LIMIT,
        )

    async def update_agent_notes(self, user_id: str, body: str) -> MarkdownMemory:
        """Replace the entire agent_notes body. Raises MemoryOverflow on cap exceed."""
        if len(body) > AGENT_NOTES_CHAR_LIMIT:
            current = await self.get_agent_notes(user_id)
            raise MemoryOverflow(current.body, body, AGENT_NOTES_CHAR_LIMIT)
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            """
            INSERT INTO agent_notes (user_id, body, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at
            """,
            (user_id, body, now),
        )
        await self._db.commit()
        return MarkdownMemory(user_id, body, datetime.fromisoformat(now), AGENT_NOTES_CHAR_LIMIT)

    async def get_user_profile(self, user_id: str) -> MarkdownMemory:
        """Return the user's user_profile (USER.md equivalent)."""
        if not self._db:
            return MarkdownMemory(user_id, "", datetime.utcnow(), USER_PROFILE_CHAR_LIMIT)
        cursor = await self._db.execute(
            "SELECT body, updated_at FROM user_profile WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return MarkdownMemory(user_id, "", datetime.utcnow(), USER_PROFILE_CHAR_LIMIT)
        return MarkdownMemory(
            user_id=user_id,
            body=row[0] or "",
            updated_at=datetime.fromisoformat(row[1]),
            char_limit=USER_PROFILE_CHAR_LIMIT,
        )

    async def update_user_profile(self, user_id: str, body: str) -> MarkdownMemory:
        """Replace the entire user_profile body. Raises MemoryOverflow on cap exceed."""
        if len(body) > USER_PROFILE_CHAR_LIMIT:
            current = await self.get_user_profile(user_id)
            raise MemoryOverflow(current.body, body, USER_PROFILE_CHAR_LIMIT)
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            """
            INSERT INTO user_profile (user_id, body, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at
            """,
            (user_id, body, now),
        )
        await self._db.commit()
        return MarkdownMemory(user_id, body, datetime.fromisoformat(now), USER_PROFILE_CHAR_LIMIT)
