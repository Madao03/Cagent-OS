"""Memory API — the single interface all agents and skills use.

Stage 0: SQLite-backed KV store (no vector search).
Stage 3+: add vector retrieval behind the same API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class UserFact:
    user_id: str
    key: str
    value: Any
    source: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class InvestmentThesis:
    user_id: str
    ticker: str
    thesis_type: str
    content: str
    version: str = "v1"
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ContradictionLog:
    user_id: str
    ticker: str
    old_fact: str
    new_fact: str
    detected_at: datetime = field(default_factory=datetime.utcnow)
    resolved: bool = False


class MemoryAPI:
    """Async interface to the memory store.

    Concrete implementation: SqliteMemoryStore (memory/sqlite_store.py).
    """

    async def get_user_facts(self, user_id: str) -> list[UserFact]:
        raise NotImplementedError

    async def save_fact(self, fact: UserFact) -> None:
        raise NotImplementedError

    async def query_by_ticker(self, user_id: str, ticker: str) -> list[InvestmentThesis]:
        raise NotImplementedError

    async def save_thesis(self, thesis: InvestmentThesis) -> None:
        raise NotImplementedError

    async def detect_contradiction(
        self, user_id: str, ticker: str, new_fact: str
    ) -> list[ContradictionLog]:
        raise NotImplementedError

    async def save_contradiction(self, log: ContradictionLog) -> None:
        raise NotImplementedError

    async def get_hot_memory_prompt(self, user_id: str) -> str:
        """Return ≤500-char hot memory string for system prompt injection."""
        raise NotImplementedError
